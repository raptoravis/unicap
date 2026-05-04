"""dHash + hamming + wait_for_match — visual sync-point matching.

dHash chosen over pHash: simpler (no DCT), faster on numpy, plenty robust for
"is this the same game scene" use case (tolerates compression noise + minor
lighting drift, distinguishes different rooms / menus).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


log = logging.getLogger("unicap.replay")


@dataclass(slots=True)
class MatchResult:
    matched: bool
    waited_s: float
    distance: int = -1
    reason: str = ""           # 'matched' | 'timeout' | 'no_frames' | 'ref_unreadable'


def dhash(img: np.ndarray) -> int:
    """64-bit difference hash. Accepts BGR uint8 ndarray; resizes to 9x8 grayscale.

    Algorithm:
      1) grayscale + resize 9x8 (one extra column for adjacent diff)
      2) for each row, bit_i = (px[i] > px[i+1])
      3) pack 64 bits into a single int

    Same image → distance 0. Lighting noise / JPEG-style compression typically
    moves only a few bits.
    """
    if img.ndim == 3:
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    else:
        gray = img
    small = cv2.resize(gray, (9, 8), interpolation=cv2.INTER_AREA)
    # vectorized: compare each col to the next col
    diff = small[:, 1:] > small[:, :-1]   # shape (8, 8) bool
    # pack to 64-bit int (row-major, MSB = top-left)
    bits = diff.flatten()
    h = 0
    for b in bits:
        h = (h << 1) | int(b)
    return h


def hamming(a: int, b: int) -> int:
    """Population count of XOR — 0 to 64 for 64-bit hashes."""
    return bin(a ^ b).count("1")


def _read_latest_bmp(frames_dir: Path, min_age_s: float = 0.5) -> np.ndarray | None:
    """Find newest *BackBuffer.png older than min_age_s (avoid mid-write reads).

    Mirrors watchdog._BMP_MIN_AGE_S guard — addon takes ~50ms to write a 1920x1080
    frame; 0.5s is comfortably past that.
    """
    if not frames_dir.is_dir():
        return None
    now = time.time()
    latest_path: Path | None = None
    latest_mtime = -1.0
    for p in frames_dir.iterdir():
        # Only care about main BackBuffer (not BackBufferUI for sync purposes —
        # sync ref was captured during recording with same fc_output_dir, so
        # whatever the addon writes is what we see during replay).
        if not p.name.endswith(".png"):
            continue
        try:
            m = p.stat().st_mtime
        except OSError:
            continue
        if now - m < min_age_s:
            continue
        if m > latest_mtime:
            latest_mtime = m
            latest_path = p
    if latest_path is None:
        return None
    # np.fromfile + cv2.imdecode (instead of cv2.imread) so partial/locked
    # BMPs return None silently — imread's path-based variant prints
    # "can't open/read file" WARN to stderr that floods the console.
    try:
        data = np.fromfile(str(latest_path), dtype=np.uint8)
    except OSError:
        return None
    if data.size < 100:
        return None
    return cv2.imdecode(data, cv2.IMREAD_COLOR)


def wait_for_match(
    ref_path: Path,
    frames_dir: Path,
    threshold: int = 16,
    timeout_s: float = 30.0,
    poll_interval_s: float = 0.2,
    abort_check=None,
) -> MatchResult:
    """Poll frames_dir for a frame matching ref_path within `threshold` hamming distance.

    Returns matched=True at first match, matched=False on timeout or error.
    abort_check (optional) is a callable returning bool — when True, returns early
    with reason='aborted'. Never raises (caller handles all failures via reason).
    """
    t0 = time.monotonic()

    if not ref_path.is_file():
        return MatchResult(matched=False, waited_s=0.0, reason="ref_unreadable")
    try:
        ref_data = np.fromfile(str(ref_path), dtype=np.uint8)
    except OSError:
        return MatchResult(matched=False, waited_s=0.0, reason="ref_unreadable")
    if ref_data.size < 100:
        return MatchResult(matched=False, waited_s=0.0, reason="ref_unreadable")
    ref_img = cv2.imdecode(ref_data, cv2.IMREAD_COLOR)
    if ref_img is None:
        return MatchResult(matched=False, waited_s=0.0, reason="ref_unreadable")
    ref_hash = dhash(ref_img)

    deadline = t0 + timeout_s
    best_dist = 64
    while time.monotonic() < deadline:
        if abort_check is not None and abort_check():
            return MatchResult(matched=False, waited_s=time.monotonic() - t0,
                               distance=best_dist, reason="aborted")
        latest = _read_latest_bmp(frames_dir)
        if latest is not None:
            d = hamming(ref_hash, dhash(latest))
            if d < best_dist:
                best_dist = d
            if d <= threshold:
                return MatchResult(matched=True, waited_s=time.monotonic() - t0,
                                   distance=d, reason="matched")
        time.sleep(poll_interval_s)

    if best_dist == 64:
        return MatchResult(matched=False, waited_s=time.monotonic() - t0,
                           reason="no_frames")
    return MatchResult(matched=False, waited_s=time.monotonic() - t0,
                       distance=best_dist, reason="timeout")
