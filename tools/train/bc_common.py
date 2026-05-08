"""Shared utilities for the BC training/eval pipeline — label space derivation
from profile, mouse-delta binning, demo-quality weight resolution.

No torch import here so this module can be used by `eval_bc.py` and the runtime
`BCDriver` without forcing a torch install at inference time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Sequence

import numpy as np

from tools.auto_play.input_backend import VK_MAP


# ── Mouse-button virtual keys (mirror takeover.py) ───────────────────────────
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04

MOUSE_BTN_NAMES = ("mouse_left", "mouse_right", "mouse_middle")
MOUSE_BTN_VKS = (VK_LBUTTON, VK_RBUTTON, VK_MBUTTON)


# ── Mouse-direction binning ──────────────────────────────────────────────────
# Signed log-bin layout: 16 classes per axis (dx and dy independently).
#   bin 0..7  → dx < 0 (most-negative at 0)
#   bin 8..15 → dx >= 0 (smallest at 8)
# Magnitude edges: 0, 1, 2, 4, 8, 16, 32, 64+ → 8 levels per side.
MOUSE_DIR_BINS_PER_AXIS = 16  # = 2 * 8 levels
_MOUSE_MAG_EDGES = (0.5, 1.5, 3.0, 6.0, 12.0, 25.0, 50.0, 100.0)


def mouse_bin(delta: float) -> int:
    """Map a signed mouse delta (dx OR dy) to a 0..15 bin index."""
    a = abs(float(delta))
    mag = 0
    for edge in _MOUSE_MAG_EDGES:
        if a > edge:
            mag += 1
        else:
            break
    mag = min(mag, 7)
    if delta < 0:
        return 7 - mag
    return 8 + mag


# ── Profile-driven label space ───────────────────────────────────────────────

@dataclass(slots=True)
class ActionSpace:
    """Resolved label space for one game profile.

    kb_keys: list of (control_name, vk_index) — the multi-label keyboard slots
             ordered by control_name for stable indexing.
    mouse_btns: subset of (mouse_left, mouse_right, mouse_middle) that the
                profile actually uses (multi-label sigmoid head).
    Mouse direction is always 2 × 16 bins (dx, dy independently); not derived
    from profile.
    """
    kb_keys: list[tuple[str, int]] = field(default_factory=list)
    mouse_btns: list[str] = field(default_factory=list)

    @property
    def num_kb(self) -> int:
        return len(self.kb_keys)

    @property
    def num_mouse_btn(self) -> int:
        return len(self.mouse_btns)

    @property
    def num_mouse_dir(self) -> int:
        return MOUSE_DIR_BINS_PER_AXIS  # per axis

    def to_meta(self) -> dict:
        return {
            "kb_keys": [
                {"control": name, "vk": vk} for name, vk in self.kb_keys
            ],
            "mouse_btns": list(self.mouse_btns),
            "mouse_dir_bins_per_axis": MOUSE_DIR_BINS_PER_AXIS,
            "mouse_mag_edges": list(_MOUSE_MAG_EDGES),
        }


def derive_action_space(profile_controls: dict) -> ActionSpace:
    """From profile.controls, produce an ActionSpace.

    Heuristic:
      - String value in VK_MAP → keyboard slot
      - Value 'mouse_left|right|middle' → mouse button slot
      - Anything else (axis declarations 'mouse', 'gamepad_*', None) → ignored
    Duplicates collapse (two controls mapped to same VK become one slot,
    keyed on the first control name encountered alphabetically).
    """
    kb_seen: dict[int, str] = {}
    mouse_btn_seen: set[str] = set()

    for ctrl_name in sorted(profile_controls.keys()):
        val = profile_controls[ctrl_name]
        if not isinstance(val, str):
            continue
        if val in MOUSE_BTN_NAMES:
            mouse_btn_seen.add(val)
            continue
        vk = VK_MAP.get(val.upper())
        if vk is None:
            continue  # unsupported (gamepad_*, axis tags, free-form)
        if vk in kb_seen:
            continue  # already represented by another control
        kb_seen[vk] = ctrl_name

    kb_keys = sorted(
        ((ctrl, vk) for vk, ctrl in kb_seen.items()), key=lambda p: p[0]
    )
    mouse_btns = sorted(mouse_btn_seen, key=MOUSE_BTN_NAMES.index)
    return ActionSpace(kb_keys=kb_keys, mouse_btns=mouse_btns)


# ── Demo-quality sample weighting ────────────────────────────────────────────

DEMO_QUALITY_WEIGHTS = {
    0: 0.5,   # unmarked
    1: 1.0,   # good
    2: 0.0,   # bad → drop
    3: 2.0,   # good_recovery → DAgger upweight (G-004)
}


def quality_weight(q: int, recovery_weight: float = 2.0) -> float:
    """Resolve demo_quality enum → sample weight. recovery_weight overrides
    the default 2.0 from spec G-004."""
    if q == 3:
        return float(recovery_weight)
    return float(DEMO_QUALITY_WEIGHTS.get(int(q), 0.5))


# ── Label extraction from a single (kb_byte_array, mouse_xy_prev/cur) ────────

def kb_label_from_row(kb_row: np.ndarray, action_space: ActionSpace) -> np.ndarray:
    """kb_row: shape (256,) uint8 (high-bit byte). Returns shape (K,) float32
    multi-hot where bit i = 1 if action_space.kb_keys[i].vk is pressed."""
    out = np.zeros(action_space.num_kb, dtype=np.float32)
    for i, (_, vk) in enumerate(action_space.kb_keys):
        if kb_row[vk] & 0x80:
            out[i] = 1.0
    return out


def mouse_btn_label_from_row(kb_row: np.ndarray, action_space: ActionSpace) -> np.ndarray:
    """Mouse buttons are stored in kb[VK_LBUTTON|RBUTTON|MBUTTON] (GetAsyncKeyState
    reports them too)."""
    out = np.zeros(action_space.num_mouse_btn, dtype=np.float32)
    for i, name in enumerate(action_space.mouse_btns):
        vk = MOUSE_BTN_VKS[MOUSE_BTN_NAMES.index(name)]
        if kb_row[vk] & 0x80:
            out[i] = 1.0
    return out


def mouse_dir_label(dx: float, dy: float) -> tuple[int, int]:
    """Return (dx_bin, dy_bin) in [0, 16)."""
    return mouse_bin(dx), mouse_bin(dy)


# ── Activity heuristic (used by sample weighting) ────────────────────────────

def is_active_frame(kb_label: np.ndarray, mouse_btn_label: np.ndarray,
                    dx: float, dy: float, mouse_motion_thresh: float = 3.0) -> bool:
    """Frame is "active" if any modeled key/btn is down OR mouse moved."""
    if float(kb_label.sum()) > 0:
        return True
    if float(mouse_btn_label.sum()) > 0:
        return True
    if abs(dx) + abs(dy) >= mouse_motion_thresh:
        return True
    return False
