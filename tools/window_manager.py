"""Force borderless windowed mode — 避免 DXGI fullscreen-exclusive 让 DWM 暂停
后台 console 渲染。

游戏全屏独占（FF7R 等）让 Windows Terminal 在游戏占据前台时停止刷新；按 F8/F9
后 unicap 的 [CAPTURE] / [AUTO-PLAY] / [WATCHDOG] print 看似没出现，其实 stdout
正常工作，alt-tab 出游戏后会一次补全。把游戏窗口 style 改成 borderless windowed
（无边框 + 撑满显示器）后，DXGI 自动从 fullscreen-exclusive transition 到 windowed
fullscreen，DWM 不再暂停其他窗口的渲染。视觉上跟全屏独占基本一致，console 实时刷新。

不污染游戏配置文件 — 仅在 unicap session 内强制 style，下次启动游戏按它原本设定走。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import threading
import time
from ctypes import wintypes

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

# Win32 constants ----------------------------------------------------------------
_GWL_STYLE = -16
_WS_POPUP = 0x80000000
_WS_VISIBLE = 0x10000000
_HWND_TOP = 0
_SWP_FRAMECHANGED = 0x0020
_SWP_SHOWWINDOW = 0x0040
_SWP_NOZORDER = 0x0004
_MONITOR_DEFAULTTONEAREST = 0x00000002

_WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


# argtypes / restype 设置 — 否则 ctypes 默认 c_int 触发 OverflowError on WS_POPUP
_user32.EnumWindows.argtypes = [_WNDENUMPROC, wintypes.LPARAM]
_user32.EnumWindows.restype = wintypes.BOOL
_user32.IsWindowVisible.argtypes = [wintypes.HWND]
_user32.IsWindowVisible.restype = wintypes.BOOL
_user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
_user32.GetWindowThreadProcessId.restype = wintypes.DWORD
_user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
_user32.GetWindowRect.restype = wintypes.BOOL
# SetWindowLongPtrW 用 LONG_PTR (64-bit on x64) — c_ssize_t 容下 WS_POPUP=0x80000000
_user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
_user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t
_user32.SetWindowPos.argtypes = [
    wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
    ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
_user32.SetWindowPos.restype = wintypes.BOOL
_user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
_user32.MonitorFromWindow.restype = wintypes.HANDLE
_user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(_MONITORINFO)]
_user32.GetMonitorInfoW.restype = wintypes.BOOL

_SW_RESTORE = 9

_user32.SetForegroundWindow.argtypes = [wintypes.HWND]
_user32.SetForegroundWindow.restype = wintypes.BOOL
_user32.GetForegroundWindow.restype = wintypes.HWND
_user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
_user32.SwitchToThisWindow.restype = None
_user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
_user32.ShowWindow.restype = wintypes.BOOL

_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
_kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
_kernel32.OpenProcess.restype = wintypes.HANDLE
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.restype = wintypes.BOOL
_kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD),
]
_kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL


def _query_image_basename(pid: int) -> str | None:
    """Return the exe basename (lowercased) for pid, or None on access denial / dead pid.

    Used to match game windows by exe name when launcher→game PID handoff makes the
    Popen-returned pid stale by the time the actual game window appears."""
    h = _kernel32.OpenProcess(_PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return None
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if not _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return None
        return os.path.basename(buf.value).lower()
    finally:
        _kernel32.CloseHandle(h)


def _find_main_window(pid: int, exe_basename: str | None,
                      timeout_s: float) -> int | None:
    """Poll EnumWindows for a top-level visible window owned by pid OR by a process
    whose image basename matches exe_basename (case-insensitive). Skip windows < 320×240.

    Belt-and-suspenders: launchers (Steam / FF7R 之类多 exe 的) often hand off the
    game to a different PID than the one Popen returned. Exe-basename fallback
    survives those PID swaps."""
    target_name = (exe_basename or "").lower() or None
    deadline = time.monotonic() + timeout_s
    found = [0]

    def _enum(hwnd, _lparam):
        if not _user32.IsWindowVisible(hwnd):
            return True
        wpid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
        match = (wpid.value == pid)
        if not match and target_name is not None:
            img = _query_image_basename(wpid.value)
            match = (img == target_name)
        if not match:
            return True
        rect = wintypes.RECT()
        _user32.GetWindowRect(hwnd, ctypes.byref(rect))
        if (rect.right - rect.left) < 320 or (rect.bottom - rect.top) < 240:
            return True  # 跳过 splash / loading 小窗
        found[0] = hwnd
        return False

    while time.monotonic() < deadline:
        found[0] = 0
        _user32.EnumWindows(_WNDENUMPROC(_enum), 0)
        if found[0]:
            return found[0]
        time.sleep(0.5)
    return None


def _monitor_rect(hwnd: int) -> tuple[int, int, int, int]:
    """Return (x, y, width, height) of the monitor containing hwnd (handles multi-monitor)."""
    hmon = _user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
    mi = _MONITORINFO()
    mi.cbSize = ctypes.sizeof(_MONITORINFO)
    _user32.GetMonitorInfoW(hmon, ctypes.byref(mi))
    r = mi.rcMonitor
    return r.left, r.top, r.right - r.left, r.bottom - r.top


def force_borderless(pid: int, exe_basename: str | None = None,
                     timeout_s: float = 30.0,
                     settle_delay_s: float = 2.0) -> bool:
    """Strip frame from game window; resize to fill its monitor.

    Match by pid OR exe basename (launcher→game PID handoff fallback).
    DXGI swap chain re-evaluates fullscreen state on style change → transitions
    to windowed (visually identical to fullscreen-exclusive). Returns True on
    success, False if window never appeared within timeout."""
    hwnd = _find_main_window(pid, exe_basename, timeout_s)
    if not hwnd:
        return False
    time.sleep(settle_delay_s)  # 让游戏先初始化完 fullscreen state，再改 style
    x, y, w, h = _monitor_rect(hwnd)
    _user32.SetWindowLongPtrW(hwnd, _GWL_STYLE, _WS_POPUP | _WS_VISIBLE)
    _user32.SetWindowPos(hwnd, _HWND_TOP, x, y, w, h,
                         _SWP_FRAMECHANGED | _SWP_SHOWWINDOW | _SWP_NOZORDER)
    return True


def focus_game_window(exe_basename: str | None = None,
                      pid: int = 0,
                      timeout_s: float = 5.0) -> int | None:
    """Find game window (by pid or exe basename) and pull it to foreground.

    Required before replay's SendInput — otherwise the console window is fg
    and all keyboard events get eaten by the terminal instead of the game.
    Returns hwnd on success, None if not found.
    """
    hwnd = _find_main_window(pid, exe_basename, timeout_s)
    if not hwnd:
        return None
    _user32.ShowWindow(hwnd, _SW_RESTORE)
    _user32.SetForegroundWindow(hwnd)
    _user32.SwitchToThisWindow(hwnd, True)
    time.sleep(0.3)
    return hwnd


def wait_for_game_foreground(exe_basename: str, timeout_s: float = 60.0) -> int | None:
    """Poll GetForegroundWindow until a window owned by `exe_basename` is in
    the foreground (e.g. user manually alt-tabbed to the game). Returns hwnd
    or None on timeout. No SetForegroundWindow call — caller already brought
    it to fg, we just detect when that happened.
    """
    target = exe_basename.lower()
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        hwnd = _user32.GetForegroundWindow()
        if hwnd:
            wpid = wintypes.DWORD()
            _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(wpid))
            img = _query_image_basename(wpid.value)
            if img and img == target:
                return hwnd
        time.sleep(0.3)
    return None


def is_process_alive_by_name(exe_basename: str) -> bool:
    """tasklist 检查 exe basename 是否仍有进程在运行（不依赖 pid，FF7R 等
    launcher → game handoff 场景下 Popen-returned pid 已死但游戏本体仍在跑）。

    检查失败时返回 True（保守 —— 避免假阳性触发误退出）。
    """
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {exe_basename}", "/NH"],
            text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            stderr=subprocess.DEVNULL,
            encoding="utf-8", errors="replace",
        )
    except (subprocess.SubprocessError, OSError):
        return True
    return exe_basename.lower() in out.lower()


def force_borderless_async(pid: int, exe_basename: str | None = None,
                           timeout_s: float = 30.0,
                           settle_delay_s: float = 2.0) -> threading.Thread:
    """Non-blocking: spawn a daemon thread that calls force_borderless."""
    def _run():
        ok = force_borderless(pid, exe_basename, timeout_s, settle_delay_s)
        if ok:
            print("[WINDOW] 已强制 borderless 窗口模式（避免全屏独占冻结 console）",
                  flush=True)
        else:
            tag = f"pid={pid}"
            if exe_basename:
                tag += f" / exe={exe_basename}"
            print(f"[WINDOW] 未找到游戏窗口 ({tag}, timeout={timeout_s:.0f}s) — "
                  f"如游戏全屏独占，console 实时输出会延迟到 alt-tab 才补出",
                  flush=True)

    t = threading.Thread(target=_run, name="auto-borderless", daemon=True)
    t.start()
    return t
