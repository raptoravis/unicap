"""InputBackend — OS-level input injection.

Combines two channels:
  - keyboard / mouse via Win32 SendInput (always available)
  - virtual gamepad via vgamepad (ViGEm Bus driver; soft-import; warn + fallback)

Thread-safe: a single internal Lock serialises every inject() call so concurrent
callers (driver thread + watchdog thread) cannot interleave key down/up events.
"""

from __future__ import annotations

import ctypes
import logging
import threading
import time
from ctypes import wintypes
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tools.auto_play.driver import Action
    from tools.auto_play.profile import GameProfile


log = logging.getLogger("unicap.auto_play")


# ── Win32 SendInput types ────────────────────────────────────────────────────

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1

KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008

# VKs that need KEYEVENTF_EXTENDEDKEY when sent via scan code (E0-prefixed).
# Without this, RCtrl/RAlt collapse to LCtrl/LAlt and arrow keys don't work
# in raw-input-aware games.
_EXTENDED_VKS = frozenset({
    0x21, 0x22, 0x23, 0x24,        # PgUp PgDn End Home
    0x25, 0x26, 0x27, 0x28,        # arrow keys
    0x2D, 0x2E,                    # Insert Delete
    0x90,                          # NumLock
    0xA3, 0xA5,                    # RCtrl RAlt
})
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040


class _MouseInput(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _KeybdInput(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _HardwareInput(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _InputUnion(ctypes.Union):
    _fields_ = [
        ("mi", _MouseInput),
        ("ki", _KeybdInput),
        ("hi", _HardwareInput),
    ]


class _Input(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("ii", _InputUnion)]


_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(_Input), ctypes.c_int)
_user32.SendInput.restype = wintypes.UINT
_user32.MapVirtualKeyW.argtypes = (wintypes.UINT, wintypes.UINT)
_user32.MapVirtualKeyW.restype = wintypes.UINT
_MAPVK_VK_TO_VSC = 0


# ── VK code map (alphanumerics + common keys) ────────────────────────────────

VK_MAP: dict[str, int] = {
    **{chr(c): c for c in range(ord("A"), ord("Z") + 1)},
    **{str(d): 0x30 + d for d in range(10)},
    "F1": 0x70, "F2": 0x71, "F3": 0x72, "F4": 0x73, "F5": 0x74, "F6": 0x75,
    "F7": 0x76, "F8": 0x77, "F9": 0x78, "F10": 0x79, "F11": 0x7A, "F12": 0x7B,
    "ESC": 0x1B, "ESCAPE": 0x1B,
    "ENTER": 0x0D, "RETURN": 0x0D,
    "SPACE": 0x20, "TAB": 0x09, "BACKSPACE": 0x08,
    "SHIFT": 0x10, "LSHIFT": 0xA0, "RSHIFT": 0xA1,
    "CTRL": 0x11, "CONTROL": 0x11, "LCTRL": 0xA2, "RCTRL": 0xA3,
    "ALT": 0x12, "LALT": 0xA4, "RALT": 0xA5,
    "UP": 0x26, "DOWN": 0x28, "LEFT": 0x25, "RIGHT": 0x27,
    "HOME": 0x24, "END": 0x23, "PAGEUP": 0x21, "PAGEDOWN": 0x22,
    "INSERT": 0x2D, "DELETE": 0x2E,
}


def _resolve_vk(name: str) -> int | None:
    return VK_MAP.get(name.upper())


# ── ViGEm soft-import ────────────────────────────────────────────────────────

_VG_IMPORT_ERROR: str | None = None
try:
    import vgamepad  # type: ignore[import-not-found]
except Exception as e:
    vgamepad = None  # type: ignore[assignment]
    _VG_IMPORT_ERROR = f"{type(e).__name__}: {e}"


_GAMEPAD_BUTTON_MAP = {
    "A": "XUSB_GAMEPAD_A",
    "B": "XUSB_GAMEPAD_B",
    "X": "XUSB_GAMEPAD_X",
    "Y": "XUSB_GAMEPAD_Y",
    "LB": "XUSB_GAMEPAD_LEFT_SHOULDER",
    "RB": "XUSB_GAMEPAD_RIGHT_SHOULDER",
    "LSTICK": "XUSB_GAMEPAD_LEFT_THUMB",
    "RSTICK": "XUSB_GAMEPAD_RIGHT_THUMB",
    "START": "XUSB_GAMEPAD_START",
    "BACK": "XUSB_GAMEPAD_BACK",
    "DPAD_UP": "XUSB_GAMEPAD_DPAD_UP",
    "DPAD_DOWN": "XUSB_GAMEPAD_DPAD_DOWN",
    "DPAD_LEFT": "XUSB_GAMEPAD_DPAD_LEFT",
    "DPAD_RIGHT": "XUSB_GAMEPAD_DPAD_RIGHT",
}


# ── InputBackend ─────────────────────────────────────────────────────────────


class InputBackend:
    """OS-level input injector. One instance per AutoPlayRunner."""

    def __init__(self, profile: "GameProfile", debug: bool = False) -> None:
        self.profile = profile
        self.debug = debug
        self._lock = threading.Lock()
        self._closed = False

        self._reserved_vks: set[int] = set()
        for k in profile.reserved_keys:
            vk = _resolve_vk(k)
            if vk is not None:
                self._reserved_vks.add(vk)

        self._gamepad = None
        self._gamepad_warned = False
        prefer_pad = bool(profile.input.get("prefer_gamepad", False))
        if vgamepad is not None:
            try:
                self._gamepad = vgamepad.VX360Gamepad()
                if prefer_pad:
                    log.info("[AUTO-PLAY] gamepad=vigem_ok (VX360Gamepad ready)")
            except Exception as e:
                log.warning(
                    "[AUTO-PLAY] vgamepad 装了但 ViGEm Bus driver 未响应: %s — 降级键鼠", e,
                )
        elif prefer_pad:
            log.warning(
                "[AUTO-PLAY] profile.input.prefer_gamepad=true 但 vgamepad 未装"
                " (%s) — 降级键鼠通道。装法: pip install vgamepad + ViGEmBus",
                _VG_IMPORT_ERROR or "import failed",
            )

    @property
    def gamepad_available(self) -> bool:
        return self._gamepad is not None

    def inject(self, action: "Action") -> None:
        if self._closed:
            return
        if action.kind == "key":
            self._inject_key(action)
        elif action.kind == "mouse":
            self._inject_mouse(action)
        elif action.kind == "gamepad":
            self._inject_gamepad(action)
        elif action.kind == "wait":
            if action.duration_ms > 0:
                time.sleep(action.duration_ms / 1000.0)
        else:
            raise ValueError(f"未知 Action.kind={action.kind!r}")

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            if self._gamepad is not None:
                try:
                    self._gamepad.reset()
                    self._gamepad.update()
                except Exception:
                    pass
                self._gamepad = None

    def __enter__(self) -> "InputBackend":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    # ── key ────────────────────────────────────────────────────────────────

    def _inject_key(self, action: "Action") -> None:
        vk_name = action.payload.get("vk")
        if not isinstance(vk_name, str):
            raise ValueError(f"key Action 缺少 'vk' 字段: {action.payload}")
        vk = _resolve_vk(vk_name)
        if vk is None:
            raise ValueError(f"未知 vk 名: {vk_name!r}（看 VK_MAP）")
        if vk in self._reserved_vks:
            raise ValueError(
                f"vk={vk_name!r} 在 reserved_keys 内 — 拒绝注入"
                f" (reserved={self.profile.reserved_keys})"
            )
        event = action.payload.get("event", "press")
        if self.debug:
            log.debug("[AUTO-PLAY] inject key vk=%s event=%s dur=%dms",
                      vk_name, event, action.duration_ms)
        with self._lock:
            if event == "down":
                self._send_key(vk, up=False)
            elif event == "up":
                self._send_key(vk, up=True)
            else:  # press
                self._send_key(vk, up=False)
                if action.duration_ms > 0:
                    time.sleep(action.duration_ms / 1000.0)
                self._send_key(vk, up=True)

    @staticmethod
    def _send_key(vk: int, up: bool) -> None:
        # Send via scan code + KEYEVENTF_SCANCODE so games using Raw Input or
        # DirectInput (id Tech 7, most modern FPS) actually see the keypress.
        # Pure virtual-key SendInput (wVk, no SCANCODE flag) only lands in the
        # Win32 message queue and is invisible to raw-input listeners.
        scan = _user32.MapVirtualKeyW(vk, _MAPVK_VK_TO_VSC)
        flags = KEYEVENTF_SCANCODE
        if vk in _EXTENDED_VKS:
            flags |= KEYEVENTF_EXTENDEDKEY
        if up:
            flags |= KEYEVENTF_KEYUP
        ki = _KeybdInput(wVk=0, wScan=scan, dwFlags=flags, time=0, dwExtraInfo=None)
        inp = _Input(type=INPUT_KEYBOARD, ii=_InputUnion(ki=ki))
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_Input))

    # ── mouse ──────────────────────────────────────────────────────────────

    def _inject_mouse(self, action: "Action") -> None:
        op = action.payload.get("op", "move")
        if self.debug:
            log.debug("[AUTO-PLAY] inject mouse %s payload=%s", op, action.payload)
        with self._lock:
            if op == "move":
                dx = int(action.payload.get("dx", 0))
                dy = int(action.payload.get("dy", 0))
                self._send_mouse(dx, dy, MOUSEEVENTF_MOVE)
            elif op in ("click", "down", "up"):
                button = action.payload.get("button", "left")
                down_flag, up_flag = {
                    "left":  (MOUSEEVENTF_LEFTDOWN,   MOUSEEVENTF_LEFTUP),
                    "right": (MOUSEEVENTF_RIGHTDOWN,  MOUSEEVENTF_RIGHTUP),
                    "middle":(MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP),
                }.get(button, (MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP))
                if op == "click":
                    self._send_mouse(0, 0, down_flag)
                    if action.duration_ms > 0:
                        time.sleep(action.duration_ms / 1000.0)
                    self._send_mouse(0, 0, up_flag)
                elif op == "down":
                    self._send_mouse(0, 0, down_flag)
                else:  # op == "up"
                    self._send_mouse(0, 0, up_flag)
            else:
                raise ValueError(f"未知 mouse op: {op!r}")

    @staticmethod
    def _send_mouse(dx: int, dy: int, flags: int) -> None:
        mi = _MouseInput(dx=dx, dy=dy, mouseData=0, dwFlags=flags,
                         time=0, dwExtraInfo=None)
        inp = _Input(type=INPUT_MOUSE, ii=_InputUnion(mi=mi))
        _user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(_Input))

    # ── gamepad ────────────────────────────────────────────────────────────

    def _inject_gamepad(self, action: "Action") -> None:
        if self._gamepad is None:
            if not self._gamepad_warned:
                log.warning(
                    "[AUTO-PLAY] gamepad Action 注入但 ViGEm 不可用 — 跳过 (后续静默)"
                )
                self._gamepad_warned = True
            return
        op = action.payload.get("op")
        if self.debug:
            log.debug("[AUTO-PLAY] inject gamepad %s payload=%s",
                      op, action.payload)
        with self._lock:
            try:
                if op in ("button", "button_down", "button_up"):
                    name = action.payload.get("button", "")
                    enum_name = _GAMEPAD_BUTTON_MAP.get(name.upper())
                    if enum_name is None:
                        raise ValueError(f"未知 gamepad button: {name!r}")
                    button_enum = getattr(vgamepad.XUSB_BUTTON, enum_name)
                    if op == "button":
                        self._gamepad.press_button(button=button_enum)
                        self._gamepad.update()
                        if action.duration_ms > 0:
                            time.sleep(action.duration_ms / 1000.0)
                        self._gamepad.release_button(button=button_enum)
                        self._gamepad.update()
                    elif op == "button_down":
                        self._gamepad.press_button(button=button_enum)
                        self._gamepad.update()
                    else:  # op == "button_up"
                        self._gamepad.release_button(button=button_enum)
                        self._gamepad.update()
                elif op == "stick":
                    side = action.payload.get("side", "left")
                    x = float(action.payload.get("x", 0.0))
                    y = float(action.payload.get("y", 0.0))
                    if side == "left":
                        self._gamepad.left_joystick_float(x_value_float=x, y_value_float=y)
                    else:
                        self._gamepad.right_joystick_float(x_value_float=x, y_value_float=y)
                    self._gamepad.update()
                    if action.duration_ms > 0:
                        time.sleep(action.duration_ms / 1000.0)
                        if side == "left":
                            self._gamepad.left_joystick_float(x_value_float=0.0, y_value_float=0.0)
                        else:
                            self._gamepad.right_joystick_float(x_value_float=0.0, y_value_float=0.0)
                        self._gamepad.update()
                elif op == "trigger":
                    side = action.payload.get("side", "left")
                    value = float(action.payload.get("value", 1.0))
                    if side == "left":
                        self._gamepad.left_trigger_float(value_float=value)
                    else:
                        self._gamepad.right_trigger_float(value_float=value)
                    self._gamepad.update()
                    if action.duration_ms > 0:
                        time.sleep(action.duration_ms / 1000.0)
                        if side == "left":
                            self._gamepad.left_trigger_float(value_float=0.0)
                        else:
                            self._gamepad.right_trigger_float(value_float=0.0)
                        self._gamepad.update()
                else:
                    raise ValueError(f"未知 gamepad op: {op!r}")
            except Exception as e:
                log.warning("[AUTO-PLAY] gamepad inject 异常: %s — 后续静默", e)
