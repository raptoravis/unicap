"""ReplayRecorder — polls input state, emits diff events, auto-emits sync points.

Polling cadence: 120 Hz (matches capture_all._thread_input). Each tick:
  - GetKeyboardState → 256-byte snapshot
  - GetCursorPos     → (x, y) absolute
  - XInput           → optional gamepad state
Diff against previous snapshot → emit only changed-bit events.

F7 = stop. Sync points are auto-emitted by two mechanisms:
  1. press-sync: every key/mouse-button/gamepad-button DOWN event emits a sync
     just before the press, so player dHash-confirms the pre-press picture
     before injecting (rugged against per-key game stutter / animation slip).
     Multiple presses in the same poll tick coalesce to one sync (same BMP).
  2. long-gap fallback: if input idles for `auto_sync_gap_s` seconds, emit a
     sync at gap start. Catches loading screens / cutscenes where input is
     entirely absent (mouse-look-only games, cinematic gaps).

Sync frame source: addon writes BMPs continuously to `sync_scratch_dir` while
fc_output_dir.txt is set. After F7 (or on close()), the scratch dir is
rmtree'd to reclaim disk (BMPs are ~6MB each at 1080p; 30s recording = ~5GB).
"""

from __future__ import annotations

import ctypes
import json
import logging
import shutil
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from tools.replay.schema import MetaModel, RECORDER_VERSION, SCHEMA_VERSION, write_meta


log = logging.getLogger("unicap.replay")


_user32 = ctypes.WinDLL("user32")


class _Point(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


# Reuse XInput surface from capture_all to avoid double-loading
_xinput = None
for lib in ("xinput1_4", "xinput9_1_0"):
    try:
        _xinput = ctypes.WinDLL(lib)
        break
    except OSError:
        pass


class _XInputGamepad(ctypes.Structure):
    _fields_ = [
        ("wButtons",      ctypes.c_ushort),
        ("bLeftTrigger",  ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX",      ctypes.c_short),
        ("sThumbLY",      ctypes.c_short),
        ("sThumbRX",      ctypes.c_short),
        ("sThumbRY",      ctypes.c_short),
    ]


class _XInputState(ctypes.Structure):
    _fields_ = [("dwPacketNumber", ctypes.c_ulong), ("Gamepad", _XInputGamepad)]


# VK code → friendly name (must round-trip with InputBackend.VK_MAP)
_VK_TO_NAME: dict[int, str] = {
    **{c: chr(c) for c in range(ord("A"), ord("Z") + 1)},
    **{0x30 + d: str(d) for d in range(10)},
    0x70: "F1", 0x71: "F2", 0x72: "F3", 0x73: "F4", 0x74: "F5", 0x75: "F6",
    0x76: "F7", 0x77: "F8", 0x78: "F9", 0x79: "F10", 0x7A: "F11", 0x7B: "F12",
    0x1B: "ESC", 0x0D: "ENTER", 0x20: "SPACE", 0x09: "TAB", 0x08: "BACKSPACE",
    0x10: "SHIFT", 0xA0: "LSHIFT", 0xA1: "RSHIFT",
    0x11: "CTRL", 0xA2: "LCTRL", 0xA3: "RCTRL",
    0x12: "ALT", 0xA4: "LALT", 0xA5: "RALT",
    0x26: "UP", 0x28: "DOWN", 0x25: "LEFT", 0x27: "RIGHT",
    0x24: "HOME", 0x23: "END", 0x21: "PAGEUP", 0x22: "PAGEDOWN",
    0x2D: "INSERT", 0x2E: "DELETE",
}

# Mouse buttons live in the keyboard-state byte array on Windows
VK_LBUTTON = 0x01
VK_RBUTTON = 0x02
VK_MBUTTON = 0x04
_MOUSE_VKS = {VK_LBUTTON: "left", VK_RBUTTON: "right", VK_MBUTTON: "middle"}

# F7 = stop. Recorder ignores F8/F9 — those belong to capture/idle loop.
VK_F7 = 0x76

# Don't emit F7 as a key event (would self-trigger on stop).
_HOTKEY_VKS = {VK_F7}

# Press events trigger per-press sync (subject to dedup).
_PRESS_EVENT_TYPES = frozenset({
    "key_down", "mouse_button_down", "gamepad_button_down",
})


@dataclass(slots=True)
class _State:
    kb: list[int] = field(default_factory=lambda: [0] * 256)
    mouse: tuple[int, int] = (0, 0)
    gamepad_buttons: int = 0
    gamepad_lt: int = 0
    gamepad_rt: int = 0
    gamepad_lx: int = 0
    gamepad_ly: int = 0
    gamepad_rx: int = 0
    gamepad_ry: int = 0


def _is_pressed(byte: int) -> bool:
    """High bit of GetKeyboardState byte = currently down."""
    return bool(byte & 0x80)


def _read_state() -> _State:
    s = _State()
    # GetAsyncKeyState returns the *physical* key state, independent of the
    # caller thread's message queue. GetKeyboardState would return all zeros
    # in a daemon polling thread (no window → no message queue → no keyboard
    # messages dispatched to update the per-thread state). 256 syscalls/tick
    # × 120Hz ≈ 30k syscalls/s ≈ 3% CPU — fine.
    kb = [0] * 256
    for vk in range(256):
        if _user32.GetAsyncKeyState(vk) & 0x8000:
            kb[vk] = 0x80  # mimic GetKeyboardState's "high bit = currently down"
    s.kb = kb
    pt = _Point()
    _user32.GetCursorPos(ctypes.byref(pt))
    s.mouse = (pt.x, pt.y)
    if _xinput is not None:
        st = _XInputState()
        if _xinput.XInputGetState(0, ctypes.byref(st)) == 0:
            g = st.Gamepad
            s.gamepad_buttons = g.wButtons
            s.gamepad_lt = g.bLeftTrigger
            s.gamepad_rt = g.bRightTrigger
            s.gamepad_lx = g.sThumbLX
            s.gamepad_ly = g.sThumbLY
            s.gamepad_rx = g.sThumbRX
            s.gamepad_ry = g.sThumbRY
    return s


# Stick deadzone — anything inside is reported as 0 (XInput convention).
_STICK_DZ = 8000
# Trigger threshold for gamepad_trigger event emission (any cross emits).
_TRIG_DZ = 30


def _diff_events(prev: _State, cur: _State, t_rel: float) -> list[dict[str, Any]]:
    """Compare two snapshots, emit minimal event list."""
    events: list[dict[str, Any]] = []

    # Keyboard / mouse buttons (256-byte array spans both)
    for vk in range(256):
        if vk in _HOTKEY_VKS:
            continue
        was = _is_pressed(prev.kb[vk])
        now = _is_pressed(cur.kb[vk])
        if was == now:
            continue
        if vk in _MOUSE_VKS:
            etype = "mouse_button_down" if now else "mouse_button_up"
            events.append({"type": etype, "t_rel": t_rel,
                           "button": _MOUSE_VKS[vk]})
            continue
        name = _VK_TO_NAME.get(vk)
        if name is None:
            continue  # don't record un-mapped VKs (numpad, OEM, etc. for v1.0)
        etype = "key_down" if now else "key_up"
        events.append({"type": etype, "t_rel": t_rel, "vk": name})

    # Mouse position (only emit on change)
    if cur.mouse != prev.mouse:
        events.append({"type": "mouse_move", "t_rel": t_rel,
                       "x": cur.mouse[0], "y": cur.mouse[1]})

    # Gamepad buttons (16-bit bitmask)
    if _xinput is not None:
        prev_bits = prev.gamepad_buttons
        cur_bits = cur.gamepad_buttons
        for bit_idx, name in _GAMEPAD_BIT_NAMES.items():
            mask = 1 << bit_idx
            was = bool(prev_bits & mask)
            now = bool(cur_bits & mask)
            if was == now:
                continue
            etype = "gamepad_button_down" if now else "gamepad_button_up"
            events.append({"type": etype, "t_rel": t_rel, "button": name})

        # Sticks: emit when crossing in/out of deadzone or magnitude changes meaningfully
        for side, (px, py, cx, cy) in (
            ("left", (prev.gamepad_lx, prev.gamepad_ly, cur.gamepad_lx, cur.gamepad_ly)),
            ("right", (prev.gamepad_rx, prev.gamepad_ry, cur.gamepad_rx, cur.gamepad_ry)),
        ):
            p_active = abs(px) > _STICK_DZ or abs(py) > _STICK_DZ
            c_active = abs(cx) > _STICK_DZ or abs(cy) > _STICK_DZ
            if p_active or c_active:
                # Only emit if delta exceeds 25% of full range (avoids 120Hz spam)
                if abs(cx - px) > 8000 or abs(cy - py) > 8000 or p_active != c_active:
                    events.append({
                        "type": "gamepad_stick", "t_rel": t_rel, "side": side,
                        "x": cx / 32767.0, "y": cy / 32767.0,
                    })

        # Triggers: emit on cross of dead zone
        for side, (pv, cv) in (
            ("left", (prev.gamepad_lt, cur.gamepad_lt)),
            ("right", (prev.gamepad_rt, cur.gamepad_rt)),
        ):
            if (pv > _TRIG_DZ) != (cv > _TRIG_DZ):
                events.append({
                    "type": "gamepad_trigger", "t_rel": t_rel, "side": side,
                    "value": cv / 255.0,
                })

    return events


_GAMEPAD_BIT_NAMES = {
    0:  "DPAD_UP",
    1:  "DPAD_DOWN",
    2:  "DPAD_LEFT",
    3:  "DPAD_RIGHT",
    4:  "START",
    5:  "BACK",
    6:  "LSTICK",
    7:  "RSTICK",
    8:  "LB",
    9:  "RB",
    12: "A",
    13: "B",
    14: "X",
    15: "Y",
}


class ReplayRecorder:
    """Records a scene script. Lifecycle: __init__ → start() → wait_until_done() → close().

    Sync points are auto-emitted whenever input idles for ``auto_sync_gap_s``
    seconds (default 1.5s). F7 stops recording.
    """

    def __init__(
        self,
        scene_dir: Path,
        sync_scratch_dir: Path,
        game_dir: Path,
        game_exe: str,
        api: str,
        window_size: tuple[int, int],
        mouse_origin: tuple[int, int],
        scene_name: str,
        poll_hz: float = 120.0,
        hotkey_poll_hz: float = 50.0,
        auto_sync_gap_s: float = 1.5,
    ) -> None:
        self.scene_dir = scene_dir
        self.sync_scratch_dir = sync_scratch_dir
        self.game_dir = game_dir
        self.scene_name = scene_name
        self.game_exe = game_exe
        self.api = api
        self.window_size = window_size
        self.mouse_origin = mouse_origin

        self._poll_period = 1.0 / max(poll_hz, 1.0)
        self._hotkey_period = 1.0 / max(hotkey_poll_hz, 1.0)
        self._auto_sync_gap_s = max(auto_sync_gap_s, 0.1)

        self._events: list[dict[str, Any]] = []
        self._sync_count = 0
        self._last_input_t_rel: float | None = None
        self._t_start: float | None = None
        self._stop_evt = threading.Event()
        self._poll_thread: threading.Thread | None = None
        self._hotkey_thread: threading.Thread | None = None

    def start(self) -> None:
        if self._poll_thread is not None:
            return
        self.scene_dir.mkdir(parents=True, exist_ok=True)
        self.sync_scratch_dir.mkdir(parents=True, exist_ok=True)
        # Redirect addon BMP output into scratch dir for the duration of recording
        sidecar = self.game_dir / "fc_output_dir.txt"
        sidecar.write_text(str(self.sync_scratch_dir), encoding="utf-8")

        self._t_start = time.monotonic()
        self._stop_evt.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, name="replay-recorder-poll", daemon=True,
        )
        self._poll_thread.start()
        self._hotkey_thread = threading.Thread(
            target=self._hotkey_loop, name="replay-recorder-hotkey", daemon=True,
        )
        self._hotkey_thread.start()

    def stop(self) -> None:
        self._stop_evt.set()

    def wait_until_done(self, timeout: float | None = None) -> None:
        """Block until F7 pressed (or external stop()). Returns; caller calls save() then close()."""
        self._stop_evt.wait(timeout)

    @property
    def auto_sync_gap_s(self) -> float:
        return self._auto_sync_gap_s

    def save(self) -> Path:
        """Write script.jsonl + meta.json. Returns scene_dir."""
        # script.jsonl
        script_path = self.scene_dir / "script.jsonl"
        with open(script_path, "w", encoding="utf-8") as f:
            for evt in self._events:
                f.write(json.dumps(evt) + "\n")

        # meta.json — aggregate per-sync settings (defaults; recorder doesn't
        # know per-sync overrides yet — sponsor edits manually if needed)
        sync_ids = sorted({e["id"] for e in self._events if e.get("type") == "sync"})
        meta = MetaModel(
            name=self.scene_name,
            version=SCHEMA_VERSION,
            recorded_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            recorder_version=RECORDER_VERSION,
            game_exe=self.game_exe,
            api=self.api,
            window_size=self.window_size,
            mouse_origin=self.mouse_origin,
            vlm_fallback_enabled=False,
            syncs={sid: {"hamming_threshold": 16, "timeout_s": 30}
                   for sid in sync_ids},
        )
        write_meta(self.scene_dir / "meta.json", meta)

        # Stats
        input_count = sum(1 for e in self._events if e.get("type") != "sync")
        sync_count = len(sync_ids)
        log.info("[REPLAY-REC] saved %s (%d inputs / %d syncs)",
                 script_path, input_count, sync_count)
        print(f"[REPLAY-REC] saved {script_path} ({input_count} inputs / {sync_count} syncs)",
              flush=True)
        return self.scene_dir

    def close(self) -> None:
        """Stop threads, clear sidecar, rmtree scratch dir."""
        self.stop()
        for t in (self._poll_thread, self._hotkey_thread):
            if t is not None:
                t.join(timeout=2.0)
        # Clear addon sidecar so it stops writing BMPs
        sidecar = self.game_dir / "fc_output_dir.txt"
        try:
            sidecar.unlink(missing_ok=True)
        except OSError:
            try:
                sidecar.write_text("", encoding="utf-8")
            except OSError:
                pass
        # Reclaim scratch space
        if self.sync_scratch_dir.exists():
            try:
                shutil.rmtree(self.sync_scratch_dir, ignore_errors=True)
            except OSError as e:
                log.warning("[REPLAY-REC] scratch cleanup failed: %s", e)

    @property
    def event_count(self) -> int:
        return len(self._events)

    @property
    def sync_count(self) -> int:
        return self._sync_count

    # ── polling loops ──────────────────────────────────────────────────────

    def _poll_loop(self) -> None:
        """120Hz state diff. Auto-emits sync (press + long-gap). Runs until stop_evt set."""
        prev = _read_state()
        while not self._stop_evt.is_set():
            time.sleep(self._poll_period)
            cur = _read_state()
            t_rel = time.monotonic() - (self._t_start or time.monotonic())
            evts = _diff_events(prev, cur, t_rel)
            if evts:
                long_gap = (self._last_input_t_rel is not None
                            and t_rel - self._last_input_t_rel > self._auto_sync_gap_s)
                has_press = any(e["type"] in _PRESS_EVENT_TYPES for e in evts)
                # long-gap takes priority when both apply (fires earlier in time
                # than press would). Same-tick multi-press → 1 sync (one BMP).
                if long_gap and self._last_input_t_rel is not None:
                    self._emit_auto_sync(self._last_input_t_rel + 0.1)
                elif has_press:
                    self._emit_auto_sync(t_rel - 0.001)
                self._events.extend(evts)
                self._last_input_t_rel = t_rel
            prev = cur

        # F7 (or manual stop) — emit a trailing time-marker sync at the actual
        # stop moment so the player waits for the in-game state to settle
        # (menu transition / loading screen still in flight after last input)
        # before declaring "reached". frame=None deliberately: dHash on the
        # post-final-input state is brittle (HUD text / random tip / animation
        # state vary 20-40 bits across runs); the wall-clock wait is the
        # robust guarantee. Press/long-gap syncs continue to do full dHash.
        if self._events:
            stop_t_rel = time.monotonic() - (self._t_start or time.monotonic())
            if self._last_input_t_rel is None or stop_t_rel > self._last_input_t_rel:
                self._sync_count += 1
                sid = f"S-{self._sync_count:02d}"
                self._events.append({"type": "sync", "id": sid, "frame": None,
                                     "t_rel": stop_t_rel,
                                     "description": "trailing time-marker"})
                print(f"[REPLAY-REC] trailing sync {sid} at {stop_t_rel:.1f}s "
                      "(time-only, no dHash)", flush=True)

    def _hotkey_loop(self) -> None:
        """50Hz F7 polling with edge detection (debounced 300ms)."""
        last_f7 = 0.0
        debounce = 0.3
        while not self._stop_evt.is_set():
            time.sleep(self._hotkey_period)
            now = time.monotonic()
            if bool(_user32.GetAsyncKeyState(VK_F7) & 0x8000) and now - last_f7 > debounce:
                last_f7 = now
                self._stop_evt.set()
                return

    def _emit_auto_sync(self, t_rel: float) -> None:
        """Auto-sync at gap end: copy newest BMP from scratch + insert sync event."""
        self._sync_count += 1
        sid = f"S-{self._sync_count:02d}"
        frame_name = f"sync_{self._sync_count:02d}.png"
        frame_path = self._latest_scratch_bmp()
        if frame_path is None:
            log.warning("[REPLAY-REC] auto-sync %s: no frame — frame=null", sid)
            print(f"[REPLAY-REC] auto-sync {sid} at {t_rel:.1f}s (warn: no frame)",
                  flush=True)
            self._events.append({"type": "sync", "id": sid, "frame": None,
                                 "t_rel": t_rel, "description": ""})
            return
        # Retry copy on sharing violation — addon may still be writing the BMP
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                shutil.copy2(frame_path, self.scene_dir / frame_name)
                last_err = None
                break
            except OSError as e:
                last_err = e
                time.sleep(0.05)
        if last_err is not None:
            log.warning("[REPLAY-REC] auto-sync %s: copy failed after retries: %s — frame=null",
                        sid, last_err)
            self._events.append({"type": "sync", "id": sid, "frame": None,
                                 "t_rel": t_rel, "description": ""})
            return
        print(f"[REPLAY-REC] auto-sync {sid} at {t_rel:.1f}s "
              f"(gap > {self._auto_sync_gap_s:.1f}s)", flush=True)
        self._events.append({"type": "sync", "id": sid, "frame": frame_name,
                             "t_rel": t_rel, "description": ""})

    def _latest_scratch_bmp(self, min_age_s: float = 0.1) -> Path | None:
        """Newest *BackBuffer.png at least `min_age_s` old (avoid addon write race).

        Addon takes ~50ms to write a 1920x1080 frame; 100ms covers that plus a
        frame interval of safety margin. The selected frame is at most 100ms
        older than the gap-end moment — visually indistinguishable.
        """
        if not self.sync_scratch_dir.is_dir():
            return None
        now = time.time()
        latest: Path | None = None
        latest_mt = -1.0
        for p in self.sync_scratch_dir.iterdir():
            if not p.name.endswith("BackBuffer.png"):
                continue
            try:
                m = p.stat().st_mtime
            except OSError:
                continue
            if now - m < min_age_s:
                continue
            if m > latest_mt:
                latest_mt = m
                latest = p
        return latest
