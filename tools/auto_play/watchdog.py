"""StaticFrameWatchdog — daemon thread, samples BackBuffer.png, triggers
recovery Actions when frames go static for too long.
"""

from __future__ import annotations

import collections
import logging
import random
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from tools.auto_play.driver import Action
from tools.auto_play.keep_alive import step_to_actions

try:
    from tools.auto_play import ocr_detector
except Exception:  # pragma: no cover — defensive: ocr_detector itself imports lazily
    ocr_detector = None  # type: ignore[assignment]

if TYPE_CHECKING:
    from tools.auto_play.input_backend import InputBackend
    from tools.auto_play.profile import GameProfile
    from tools.auto_play.takeover import TakeoverDetector


log = logging.getLogger("unicap.auto_play")


class StaticFrameWatchdog:
    # A pixel counts as "moved" if its strongest channel differs by more than
    # this many gray levels — picks up real motion, ignores compression noise.
    _PIXEL_MOTION_THRESHOLD = 30  # out of 255

    # Local-motion arm of the static detector: if fewer than this fraction of
    # pixels actually moved, treat the scene as frozen even when overall mean
    # diff is non-trivial. Catches the "tutorial GIF over a frozen scene" /
    # "animated dialog cursor" case that the global-mean test misses.
    _LOCAL_MOTION_RATIO_CAP = 0.05  # 5% of pixels

    # ...but only when overall activity is also genuinely low. Loading
    # fade-ins, scene transitions, and uniform brightness ramps shift every
    # pixel slightly (mean ≈ 0.02-0.04, moved ≈ 0%) — we do NOT want to call
    # those static, the scene is mid-change. Keep the cap tight enough to
    # exclude them while still letting frozen-scene-with-overlay through.
    _LOCAL_MOTION_MEAN_CAP = 0.025  # normalized 0-1

    # Long-window check: even when every frame-to-frame transition looks
    # active (e.g. character idle-loop animation + HUD pulse + tutorial GIF),
    # compare the *current* frame against the one captured N samples ago. If
    # the long-window diff is small (= the player hasn't really gone
    # anywhere), the scene is stuck despite per-frame motion. Catches
    # tutorial popups / dialog windows where the underlying game scene
    # freezes but cinematic-style elements keep animating in place.
    _LONG_WINDOW_SAMPLES = 3         # → window = sample_period_s * (N-1) ≈ 4-6s
    _LONG_WINDOW_MEAN_CAP = 0.04     # mean diff vs N-old frame
    _LONG_WINDOW_RATIO_CAP = 0.30    # moved-pixel ratio vs N-old frame

    # OCR arm: every N samples, run Windows.Media.Ocr on the latest frame and
    # check for explicit dismiss-prompt text ("M Back" / "ESC Close" / etc.).
    # When matched, inject the key directly. Sampled less often than other arms
    # because OCR costs 100-500ms CPU.
    _OCR_SAMPLE_INTERVAL = 4               # × sample_period_s ≈ 8s

    def __init__(
        self,
        frames_dir: Path,
        profile: "GameProfile",
        input_backend: "InputBackend",
        log_path: Path | None = None,
        recovery_active_evt: "threading.Event | None" = None,
        takeover_detector: "TakeoverDetector | None" = None,
    ) -> None:
        self._frames_dir = frames_dir
        self._profile = profile
        self._backend = input_backend
        self._log_path = log_path
        # 人在玩时不要 inject recovery / OCR dismiss — runner 创建并传入
        self._takeover = takeover_detector
        # Cross-thread "recovery in progress" flag. While set, the main driver
        # loop skips its own inject calls so it doesn't collide with the
        # recovery sequence (e.g. watchdog wants S 1500ms back-step, main loop
        # simultaneously injects W 2500ms — they cancel). The runner constructs
        # the Event and passes it to both watchdog and the loop; watchdog
        # sets/clears around _trigger_recovery.
        self._recovery_active_evt = recovery_active_evt or threading.Event()

        wd_cfg = profile.watchdog
        self._sample_period_s = float(wd_cfg.get("sample_period_s", 5.0))
        self._diff_threshold = float(wd_cfg.get("static_diff_threshold", 0.01))
        self._consecutive_required = int(wd_cfg.get("consecutive_static_required", 2))

        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        self._trigger_count = 0
        self._recovery_steps: list[dict[str, Any]] = list(
            profile.keep_alive.get("recovery") or []
        )
        self._rng = random.Random(0xCA75)
        # Ring buffer of the last N samples for long-window comparison.
        self._frame_history: collections.deque = collections.deque(
            maxlen=self._LONG_WINDOW_SAMPLES,
        )
        # OCR arm sample counter (mod _OCR_SAMPLE_INTERVAL).
        self._ocr_tick_counter = 0

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._run, name="auto-play-watchdog", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            if self._thread.is_alive():
                log.warning("[WATCHDOG] thread join 超时 (%.1fs)", timeout_s)
            self._thread = None

    @property
    def trigger_count(self) -> int:
        return self._trigger_count

    def _run(self) -> None:
        prev_frame: np.ndarray | None = None
        consecutive_static = 0
        # Don't trigger recovery for the first 30s — capture may not have
        # produced frames yet. Wait for first frame before counting static.
        warmup_deadline = time.monotonic() + 30.0

        while not self._stop_evt.is_set():
            self._stop_evt.wait(self._sample_period_s)
            if self._stop_evt.is_set():
                break

            current = self._read_latest_bmp()
            if current is None:
                if time.monotonic() > warmup_deadline:
                    log.debug("[WATCHDOG] frames_dir 无可读 BMP，跳过本轮")
                continue

            if prev_frame is None or prev_frame.shape != current.shape:
                prev_frame = current
                consecutive_static = 0
                continue

            diff_3d = np.abs(prev_frame.astype(np.int16) - current.astype(np.int16))
            mean_diff = float(diff_3d.mean() / 255.0)
            # Per-pixel max-across-channels → 2D map of "did this pixel really move".
            diff_2d = diff_3d.max(axis=2)
            moved_ratio = float((diff_2d > self._PIXEL_MOTION_THRESHOLD).mean())
            prev_frame = current

            # Two-arm short-window static detection. Either:
            #   global: total activity is below threshold (the original test)
            #   local-only: a tiny fraction of pixels moved meaningfully AND
            #               overall activity stayed moderate — characteristic
            #               of a frozen scene with a small overlay animation
            #               (FF7R tutorial GIF, dialog cursor blink, etc.)
            global_static = mean_diff <= self._diff_threshold
            local_only = (moved_ratio < self._LOCAL_MOTION_RATIO_CAP
                          and mean_diff < self._LOCAL_MOTION_MEAN_CAP)
            is_short_static = global_static or local_only

            if is_short_static:
                consecutive_static += 1
                if consecutive_static >= self._consecutive_required:
                    if self._taken_over_skip("short-window"):
                        consecutive_static = 0
                        self._frame_history.clear()
                        self._frame_history.append(current)
                        continue
                    self._trigger_recovery(mean_diff, moved_ratio)
                    consecutive_static = 0
                    self._frame_history.clear()  # reset to avoid double-firing
                    self._frame_history.append(current)
                    continue
            else:
                consecutive_static = 0

            # Long-window check — only meaningful once history is full. Compare
            # current vs oldest in window: if very little has changed, the
            # player isn't getting anywhere despite per-frame motion (tutorial
            # popup / dialog window with idle animations underneath).
            self._frame_history.append(current)
            if len(self._frame_history) == self._frame_history.maxlen:
                oldest = self._frame_history[0]
                long_3d = np.abs(oldest.astype(np.int16) - current.astype(np.int16))
                long_mean = float(long_3d.mean() / 255.0)
                long_2d = long_3d.max(axis=2)
                long_moved = float(
                    (long_2d > self._PIXEL_MOTION_THRESHOLD).mean()
                )
                long_window_s = (
                    self._sample_period_s * (self._frame_history.maxlen - 1)
                )
                if (long_mean < self._LONG_WINDOW_MEAN_CAP
                        and long_moved < self._LONG_WINDOW_RATIO_CAP):
                    if self._taken_over_skip("long-window"):
                        self._frame_history.clear()
                        continue
                    log.info(
                        "[WATCHDOG] long-window static (%.0fs): "
                        "long_mean=%.4f long_moved=%.1f%% — 当作卡死",
                        long_window_s, long_mean, long_moved * 100,
                    )
                    self._trigger_recovery(long_mean, long_moved)
                    self._frame_history.clear()
                    continue

            # OCR arm — every _OCR_SAMPLE_INTERVAL samples, scan for explicit
            # dismiss-prompt text. Match → inject key directly (OCR's match is
            # the literal on-screen hint). Disabled when winrt-Windows.Media.Ocr
            # is not installed.
            self._ocr_tick_counter += 1
            if (ocr_detector is not None
                    and self._ocr_tick_counter >= self._OCR_SAMPLE_INTERVAL):
                self._ocr_tick_counter = 0
                key = ocr_detector.detect_dismiss_prompt(current)
                if key:
                    if self._taken_over_skip(f"OCR/{key}"):
                        continue
                    log.info(
                        "[WATCHDOG] OCR dismiss-prompt key=%s — 直接注入", key,
                    )
                    self._trigger_count += 1
                    try:
                        self._backend.inject(Action(
                            kind="key",
                            payload={"vk": key, "event": "press"},
                            duration_ms=80,
                        ))
                    except Exception as e:
                        log.warning("[WATCHDOG] OCR inject 异常: %s", e)

    # Frames younger than this are likely still being written by the addon →
    # cv2.imdecode would fail mid-write. 500ms is comfortably longer than
    # addon's per-frame PNG write at 1920x1080.
    _BMP_MIN_AGE_S = 0.5

    def _read_latest_bmp(self) -> np.ndarray | None:
        """Read latest BackBuffer.png (no-ui / pre-UI scene). Watchdog only looks
        at the no-ui stream now — UI/menu detection is delegated to OCR + frame-
        diff arms; we no longer rely on post-UI BackBufferUI.png."""
        if not self._frames_dir.is_dir():
            return None
        now = time.time()
        latest_mtime = -1.0
        latest_path: Path | None = None
        for p in self._frames_dir.iterdir():
            if not p.name.endswith(".png"):
                continue
            if "BackBufferUI" in p.name:
                continue  # post-UI 流不再使用
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            # Skip frames likely still being written; PNG encode + write
            # at 1920x1080 takes longer than BMP, but 500ms is still comfortable.
            if now - m < self._BMP_MIN_AGE_S:
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
        if data.size < 100:  # too small to be a valid BMP header
            return None
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is None:
            return None
        # Subsample to 320x180 for cheap diff
        h, w = img.shape[:2]
        if w > 320:
            img = cv2.resize(img, (320, max(1, int(h * 320 / w))),
                             interpolation=cv2.INTER_AREA)
        return img

    def _taken_over_skip(self, source: str) -> bool:
        """True 时调用方应该 skip 本次 inject 路径（人在玩）。"""
        if self._takeover is None:
            return False
        if not self._takeover.is_taken_over():
            return False
        log.info("[WATCHDOG] %s 触发但人在接管 — 跳过", source)
        return True

    def _trigger_recovery(self, mean_diff: float, moved_ratio: float) -> None:
        self._trigger_count += 1
        diag = f"mean={mean_diff:.4f} moved={moved_ratio*100:.1f}%"
        # Set the recovery flag so the main driver loop pauses its own inject
        # calls — without this, watchdog's S+turn back-step gets cancelled
        # mid-flight by main loop's W+turn. Always cleared in finally.
        self._recovery_active_evt.set()
        try:
            log.info(
                "[WATCHDOG] static-frame 触发 #%d %s → 注入 recovery (%d 步)",
                self._trigger_count, diag, len(self._recovery_steps),
            )
            for step in self._recovery_steps:
                try:
                    action_list = step_to_actions(self._profile, step, self._rng)
                except Exception as e:
                    log.warning("[WATCHDOG] recovery step %s 解析失败: %s", step, e)
                    continue
                for action in action_list:
                    try:
                        self._backend.inject(action)
                    except Exception as e:
                        log.warning("[WATCHDOG] recovery inject 异常: %s", e)
                    if self._stop_evt.is_set():
                        return
        finally:
            self._recovery_active_evt.clear()
