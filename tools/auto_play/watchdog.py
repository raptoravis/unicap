"""StaticFrameWatchdog — daemon thread, samples BackBuffer.bmp, triggers
recovery Actions when frames go static for too long.
"""

from __future__ import annotations

import logging
import random
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from tools.auto_play.keep_alive import step_to_actions

if TYPE_CHECKING:
    from tools.auto_play.input_backend import InputBackend
    from tools.auto_play.profile import GameProfile


log = logging.getLogger("unicap.auto_play")


class StaticFrameWatchdog:
    def __init__(
        self,
        frames_dir: Path,
        profile: "GameProfile",
        input_backend: "InputBackend",
        log_path: Path | None = None,
    ) -> None:
        self._frames_dir = frames_dir
        self._profile = profile
        self._backend = input_backend
        self._log_path = log_path

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

            diff = float(
                np.abs(prev_frame.astype(np.int16) - current.astype(np.int16))
                .mean() / 255.0
            )
            prev_frame = current

            if diff <= self._diff_threshold:
                consecutive_static += 1
                if consecutive_static >= self._consecutive_required:
                    self._trigger_recovery(diff)
                    consecutive_static = 0
            else:
                consecutive_static = 0

    # BMPs younger than this are likely still being written by the addon →
    # cv2.imread would print "can't open/read" to stderr. 500ms is comfortably
    # longer than addon's per-frame BMP write at 1920x1080 (~50ms).
    _BMP_MIN_AGE_S = 0.5

    def _read_latest_bmp(self) -> np.ndarray | None:
        """Prefer BackBufferUI.bmp (post-UI, has HUD/menus) when --ui-mode={ui,both}.
        Fall back to BackBuffer.bmp under --ui-mode=no-ui or pre-UI-only sessions.
        Watchdog needs to see UI to detect 'Game Over' / pause menus / static HUD."""
        if not self._frames_dir.is_dir():
            return None
        now = time.time()
        latest_ui_mtime = -1.0
        latest_ui_path: Path | None = None
        latest_bb_mtime = -1.0
        latest_bb_path: Path | None = None
        for p in self._frames_dir.iterdir():
            if not p.name.endswith(".bmp"):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            # Skip BMPs likely still being written (addon writes ~50ms/frame
            # at 1920x1080; 500ms guard is comfortable)
            if now - m < self._BMP_MIN_AGE_S:
                continue
            if "BackBufferUI" in p.name:
                if m > latest_ui_mtime:
                    latest_ui_mtime = m
                    latest_ui_path = p
            else:
                if m > latest_bb_mtime:
                    latest_bb_mtime = m
                    latest_bb_path = p
        latest_path = latest_ui_path if latest_ui_path is not None else latest_bb_path
        if latest_path is None:
            return None
        try:
            img = cv2.imread(str(latest_path), cv2.IMREAD_COLOR)
        except Exception:
            return None
        if img is None:
            return None
        # Subsample to 320x180 for cheap diff
        h, w = img.shape[:2]
        if w > 320:
            img = cv2.resize(img, (320, max(1, int(h * 320 / w))),
                             interpolation=cv2.INTER_AREA)
        return img

    def _trigger_recovery(self, diff: float) -> None:
        self._trigger_count += 1
        log.info(
            "[WATCHDOG] static-frame 触发 #%d diff=%.4f → 注入 recovery (%d 步)",
            self._trigger_count, diff, len(self._recovery_steps),
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
