"""SendInput VK_F8 / VK_F9 镜像到游戏窗口。

我们**不**用 PostMessage（绕过 SetForegroundWindow 但游戏 GetAsyncKeyState
不会读到）。SendInput 走全局 input queue —— 与 main.py 的轮询兼容。

Windows-only。Linux/macOS 该函数会安全 no-op + return False。
"""

from __future__ import annotations

import ctypes
import logging
import sys
from ctypes import wintypes

log = logging.getLogger("unicap_gui.sendinput")

# VK codes —— Windows User32 spec
VK_F8 = 0x77
VK_F9 = 0x78

# INPUT structure constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002


if sys.platform == "win32":

    LONG = ctypes.c_long
    DWORD = wintypes.DWORD
    WORD = wintypes.WORD
    ULONG_PTR = ctypes.c_size_t

    class _MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
            ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR),
        ]

    class _KEYBDINPUT(ctypes.Structure):
        _fields_ = [
            ("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
            ("time", DWORD), ("dwExtraInfo", ULONG_PTR),
        ]

    class _HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]

    class _INPUT_UNION(ctypes.Union):
        _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT), ("hi", _HARDWAREINPUT)]

    class _INPUT(ctypes.Structure):
        _anonymous_ = ("u",)
        _fields_ = [("type", DWORD), ("u", _INPUT_UNION)]

    _user32 = ctypes.windll.user32
    _user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(_INPUT), ctypes.c_int]
    _user32.SendInput.restype = ctypes.c_uint

    def _send_key(vk: int, up: bool) -> bool:
        ki = _KEYBDINPUT(wVk=vk, wScan=0,
                         dwFlags=KEYEVENTF_KEYUP if up else 0,
                         time=0, dwExtraInfo=0)
        inp = _INPUT(type=INPUT_KEYBOARD)
        inp.ki = ki
        n = _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_INPUT))
        return n == 1

    def press_release(vk: int) -> bool:
        """完整 press → release 一次。返回是否两次 SendInput 都成功。"""
        if not _send_key(vk, up=False):
            log.warning("SendInput press failed for vk=0x%x", vk)
            return False
        # 极短延迟，避免被游戏认为同帧合并掉
        import time
        time.sleep(0.05)
        ok = _send_key(vk, up=True)
        if not ok:
            log.warning("SendInput release failed for vk=0x%x", vk)
        return ok

else:

    def press_release(vk: int) -> bool:
        log.warning("SendInput is Windows-only; vk=0x%x ignored", vk)
        return False


def press_f8() -> bool:
    return press_release(VK_F8)


def press_f9() -> bool:
    return press_release(VK_F9)
