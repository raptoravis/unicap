"""TakeoverDetector — 检测人类是否正在主动操作游戏。

需求：auto-play 模式下，**3 秒**没有主动按键时才允许 bot 注入；只要检测到
任意主动按键，3 秒内 bot 全部 inject 路径（driver tick / attack heartbeat /
watchdog recovery / OCR dismiss）都暂停。

Inject 路径在 `runner` / `watchdog` 里都 gate `is_taken_over()`。

判定原则：
- 主动按键 = profile.controls 里出现的键 + 鼠标 L/R/Middle 按键。
- 鼠标移动**不算**（玩家挥鼠标看视角不视为接管，避免 bot 自己 mouse turn 的
  GetCursorPos diff 误判）。
- 手柄按键不通过 GetAsyncKeyState 读，profile 用 gamepad_* 时只能靠键鼠路径
  判定。
- F8/F9（unicap 自身热键）永远不算接管。

如何避免把 bot 自己的 inject 当人类按键：
- bot 通过 InputBackend.inject 注入时持有 `backend._lock`；detector 试取
  `_lock.acquire(blocking=False)`，取不到说明 bot 正在 inject — 跳过本轮。
- bot inject 完成后 OS 还需 ~10-50ms 完成 KeyUp 处理（残留高电平），加
  `bot_inject_grace_s` 软窗口（默认 150ms）跳过。
- 这两条结合后剩下的真高电平视为人类输入。
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from typing import TYPE_CHECKING

from tools.auto_play.input_backend import VK_MAP, _resolve_vk

if TYPE_CHECKING:
    from tools.auto_play.input_backend import InputBackend
    from tools.auto_play.profile import GameProfile


log = logging.getLogger("unicap.auto_play")


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.GetAsyncKeyState.argtypes = (ctypes.c_int,)
_user32.GetAsyncKeyState.restype = ctypes.c_short

# Win32 mouse-button virtual keys (also consumable by GetAsyncKeyState).
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04

_MOUSE_BTN_VKS = {
    "mouse_left":   VK_LBUTTON,
    "mouse_right":  VK_RBUTTON,
    "mouse_middle": VK_MBUTTON,
}


def _build_sample_vks(profile: "GameProfile") -> list[int]:
    """Collect VKs to poll for human takeover.

    Sources:
      - profile.controls.values() — keyboard names (W/SPACE/M/...) and
        mouse_left/right/middle. `mouse` (no suffix, used for turn_axis) and
        `gamepad_*` are skipped.
      - Mouse L/R always included as a baseline (profile may omit them but
        humans tend to click during takeover regardless).

    Excluded:
      - profile.reserved_keys (F8/F9 are unicap hotkeys, not game input).
    """
    vks: set[int] = set()
    reserved: set[int] = set()
    for k in profile.reserved_keys:
        vk = _resolve_vk(k)
        if vk is not None:
            reserved.add(vk)

    for ctrl_value in profile.controls.values():
        if not isinstance(ctrl_value, str):
            continue
        ctrl_lower = ctrl_value.lower()
        if ctrl_lower in _MOUSE_BTN_VKS:
            vks.add(_MOUSE_BTN_VKS[ctrl_lower])
            continue
        if ctrl_lower == "mouse":
            continue  # turn_axis: mouse — 鼠标移动不算
        if ctrl_lower.startswith("gamepad_"):
            continue  # GetAsyncKeyState 读不到手柄
        vk = _resolve_vk(ctrl_value)
        if vk is not None:
            vks.add(vk)

    # Baseline mouse buttons — 玩家接管时绝大多数会用到攻击/瞄准，即便
    # profile 没显式列也兜底加上。
    vks.add(VK_LBUTTON)
    vks.add(VK_RBUTTON)

    vks -= reserved
    return sorted(vks)


class TakeoverDetector:
    """Background poller that flips a "human is driving" flag for 3s after
    any sampled key is observed high while the bot isn't injecting."""

    def __init__(
        self,
        backend: "InputBackend",
        profile: "GameProfile",
        grace_s: float = 3.0,
        sample_period_s: float = 0.08,
        bot_inject_grace_s: float = 0.15,
    ) -> None:
        self._backend = backend
        self._grace_s = float(grace_s)
        self._sample_period_s = float(sample_period_s)
        self._bot_inject_grace_s = float(bot_inject_grace_s)

        self._sample_vks: list[int] = _build_sample_vks(profile)
        # Far in the past so first is_taken_over() returns False.
        self._last_human_at: float = time.monotonic() - self._grace_s - 1.0
        self._stop_evt = threading.Event()
        self._thread: threading.Thread | None = None
        # Diagnostic: number of takeover detections in this session.
        self._detection_count = 0

        # If profile yields zero sample keys (defensive), detector is a no-op.
        if not self._sample_vks:
            log.warning(
                "[TAKEOVER] profile %r 提取到 0 个 sample VK — detector 将常态返回 False",
                profile.name,
            )

    @property
    def grace_s(self) -> float:
        return self._grace_s

    @property
    def detection_count(self) -> int:
        return self._detection_count

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        if not self._sample_vks:
            return  # no-op detector
        self._stop_evt.clear()
        self._thread = threading.Thread(
            target=self._loop, name="auto-play-takeover", daemon=True,
        )
        self._thread.start()
        # Map vk → name (best-effort) for log readability.
        names = sorted(
            {n for n, v in VK_MAP.items() if v in self._sample_vks}
            | {n for n, v in _MOUSE_BTN_VKS.items() if v in self._sample_vks}
        )
        log.info(
            "[TAKEOVER] 启动 grace=%.1fs sample_period=%.0fms keys=%s",
            self._grace_s, self._sample_period_s * 1000.0, names,
        )

    def stop(self, timeout_s: float = 2.0) -> None:
        self._stop_evt.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout_s)
            if self._thread.is_alive():
                log.warning("[TAKEOVER] thread join 超时 (%.1fs)", timeout_s)
            self._thread = None

    def is_taken_over(self) -> bool:
        return (time.monotonic() - self._last_human_at) < self._grace_s

    def _loop(self) -> None:
        while not self._stop_evt.is_set():
            self._stop_evt.wait(self._sample_period_s)
            if self._stop_evt.is_set():
                break

            # 1) bot inject 中？lock 拿不到说明正在 inject。
            got = self._backend._lock.acquire(blocking=False)
            if not got:
                continue
            self._backend._lock.release()

            # 2) bot 刚 inject 完？OS 还在 propagate KeyUp，跳过。
            if (time.monotonic() - self._backend.last_inject_at_mono
                    < self._bot_inject_grace_s):
                continue

            # 3) sample 关键键 — 任何高电平 → 标记接管
            for vk in self._sample_vks:
                if _user32.GetAsyncKeyState(vk) & 0x8000:
                    if not self.is_taken_over():
                        self._detection_count += 1
                        if (self._detection_count <= 3
                                or self._detection_count % 20 == 0):
                            log.info(
                                "[TAKEOVER] 检测到主动按键 vk=0x%02X #%d — 暂停 auto-play %.1fs",
                                vk, self._detection_count, self._grace_s,
                            )
                    self._last_human_at = time.monotonic()
                    break
