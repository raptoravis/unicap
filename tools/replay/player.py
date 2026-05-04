"""ReplayPlayer — replay script.jsonl events through InputBackend with sync waiting.

Time discipline: events scheduled by *absolute* t_rel from playback start, so
scheduling jitter doesn't accumulate across long replays.

Mouse policy: SetCursorPos with `recorded_x * scale_x, recorded_y * scale_y`.
Won't replay FPS look (which uses raw HID delta, not cursor position) — that
limitation is documented in the requirements doc.
"""

from __future__ import annotations

import ctypes
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from tools.auto_play.driver import Action
from tools.auto_play.input_backend import InputBackend
from tools.replay.schema import iter_events, load_meta
from tools.replay.sync_match import wait_for_match


log = logging.getLogger("unicap.replay")


_user32 = ctypes.WinDLL("user32")
_SM_CXSCREEN = 0
_SM_CYSCREEN = 1


VK_R = 0x52
VK_Q = 0x51


@dataclass(slots=True)
class ReplayResult:
    status: str          # 'reached' | 'sync_miss_aborted' | 'user_abort' | 'script_error'
    exit_code: int
    elapsed_s: float
    recorded_s: float
    drift_s: float
    syncs_passed: int
    syncs_total: int
    failed_sync: str | None = None


def get_screen_center() -> tuple[int, int]:
    w = _user32.GetSystemMetrics(_SM_CXSCREEN)
    h = _user32.GetSystemMetrics(_SM_CYSCREEN)
    return w // 2, h // 2


def recenter_cursor() -> None:
    cx, cy = get_screen_center()
    _user32.SetCursorPos(cx, cy)


class ReplayPlayer:
    """Replay one scene. Public surface: __init__ → run() → ReplayResult."""

    def __init__(
        self,
        scene_dir: Path,
        sync_scratch_dir: Path,
        game_dir: Path,
        backend: InputBackend,
        current_window_size: tuple[int, int] | None = None,
        paused_input_provider: Callable[[], str] | None = None,
        sync_timeout_default_s: float = 30.0,
        sync_threshold_default: int = 16,
    ) -> None:
        """
        scene_dir: _scenes/<name>/
        sync_scratch_dir: where addon writes BMPs during replay (sync_match reads here)
        game_dir: for fc_output_dir.txt sidecar
        backend: shared InputBackend (caller manages lifecycle)
        current_window_size: for mouse coord scaling. None = use recorded size unchanged.
        paused_input_provider: testing hook — returns 'R' or 'Q' synchronously when
                               called. Production: None → real GetAsyncKeyState polling.
        """
        self.scene_dir = scene_dir
        self.sync_scratch_dir = sync_scratch_dir
        self.game_dir = game_dir
        self.backend = backend
        self.current_window_size = current_window_size
        self._paused_input_provider = paused_input_provider
        self._sync_timeout_default = sync_timeout_default_s
        self._sync_threshold_default = sync_threshold_default

    def run(self) -> ReplayResult:
        # Load script + meta
        meta_path = self.scene_dir / "meta.json"
        script_path = self.scene_dir / "script.jsonl"
        if not meta_path.is_file() or not script_path.is_file():
            print(f"[REPLAY] missing scene files in {self.scene_dir}", flush=True)
            return ReplayResult(status="script_error", exit_code=2, elapsed_s=0.0,
                                recorded_s=0.0, drift_s=0.0,
                                syncs_passed=0, syncs_total=0)
        try:
            meta = load_meta(meta_path)
            events = list(iter_events(script_path))
        except (ValueError, OSError) as e:
            print(f"[REPLAY] script load failed: {e}", flush=True)
            return ReplayResult(status="script_error", exit_code=2, elapsed_s=0.0,
                                recorded_s=0.0, drift_s=0.0,
                                syncs_passed=0, syncs_total=0)

        # Window-scale factors (mouse coord rescaling)
        if self.current_window_size is not None and self.current_window_size != meta.window_size:
            print(f"[REPLAY] window size differs (rec={meta.window_size},"
                  f" cur={self.current_window_size}) — scaling mouse coords",
                  flush=True)
            scale_x = self.current_window_size[0] / max(meta.window_size[0], 1)
            scale_y = self.current_window_size[1] / max(meta.window_size[1], 1)
        else:
            scale_x = scale_y = 1.0

        # Set up addon BMP redirect for sync matching
        sidecar = self.game_dir / "fc_output_dir.txt"
        self.sync_scratch_dir.mkdir(parents=True, exist_ok=True)
        try:
            sidecar.write_text(str(self.sync_scratch_dir), encoding="utf-8")
        except OSError as e:
            log.warning("[REPLAY] could not set fc_output_dir.txt: %s", e)

        recorded_s = events[-1]["t_rel"] if events else 0.0
        sync_total = sum(1 for e in events if e["type"] == "sync")
        sync_passed = 0

        t_start = time.monotonic()
        try:
            for evt in events:
                # Wait until the event's absolute time
                target_t = t_start + float(evt["t_rel"])
                while True:
                    now = time.monotonic()
                    if now >= target_t:
                        break
                    time.sleep(min(target_t - now, 0.05))

                etype = evt["type"]
                if etype == "sync":
                    sid = evt["id"]
                    threshold = meta.syncs.get(sid, {}).get(
                        "hamming_threshold", self._sync_threshold_default,
                    )
                    timeout_s = float(meta.syncs.get(sid, {}).get(
                        "timeout_s", self._sync_timeout_default,
                    ))
                    frame = evt.get("frame")
                    if not frame:
                        log.warning("[REPLAY] sync %s has no frame — skipping match",
                                    sid)
                        sync_passed += 1
                        continue
                    ref_path = self.scene_dir / frame
                    res = wait_for_match(
                        ref_path=ref_path,
                        frames_dir=self.sync_scratch_dir,
                        threshold=int(threshold),
                        timeout_s=timeout_s,
                    )
                    if res.matched:
                        print(f"[REPLAY] sync {sid} matched"
                              f" (waited {res.waited_s:.1f}s, dist={res.distance})",
                              flush=True)
                        sync_passed += 1
                        continue
                    # Sync miss — go paused, ask user
                    print(f"[REPLAY] sync {sid} miss after {res.waited_s:.0f}s"
                          f" (best dist={res.distance}, reason={res.reason})."
                          " Press R to resume, Q to abort.", flush=True)
                    decision = self._wait_paused_decision()
                    if decision == "Q":
                        elapsed = time.monotonic() - t_start
                        return ReplayResult(
                            status="user_abort", exit_code=2,
                            elapsed_s=elapsed, recorded_s=recorded_s,
                            drift_s=elapsed - recorded_s,
                            syncs_passed=sync_passed, syncs_total=sync_total,
                            failed_sync=sid,
                        )
                    # 'R' → continue, but reset clock so we don't try to catch up
                    # to all the time we spent paused
                    delta = time.monotonic() - target_t
                    t_start += delta
                    sync_passed += 1
                    continue

                # Input event → translate to Action and inject
                action = self._event_to_action(evt, scale_x, scale_y)
                if action is None:
                    continue
                try:
                    self.backend.inject(action)
                except ValueError as e:
                    log.warning("[REPLAY] inject rejected: %s — continuing", e)
                except Exception:
                    log.exception("[REPLAY] inject crashed — continuing")
        except KeyboardInterrupt:
            elapsed = time.monotonic() - t_start
            print("[REPLAY] interrupted by user (Ctrl+C)", flush=True)
            return ReplayResult(
                status="user_abort", exit_code=130,
                elapsed_s=elapsed, recorded_s=recorded_s,
                drift_s=elapsed - recorded_s,
                syncs_passed=sync_passed, syncs_total=sync_total,
            )
        finally:
            try:
                sidecar.unlink(missing_ok=True)
            except OSError:
                try:
                    sidecar.write_text("", encoding="utf-8")
                except OSError:
                    pass

        elapsed = time.monotonic() - t_start
        drift = elapsed - recorded_s
        sign = "+" if drift >= 0 else ""
        print(f"[REPLAY] reached scene {meta.name} in {elapsed:.1f}s"
              f" (recorded {recorded_s:.1f}s, drift {sign}{drift:.1f}s)",
              flush=True)
        return ReplayResult(
            status="reached", exit_code=0,
            elapsed_s=elapsed, recorded_s=recorded_s, drift_s=drift,
            syncs_passed=sync_passed, syncs_total=sync_total,
        )

    # ── helpers ────────────────────────────────────────────────────────────

    def _event_to_action(self, evt: dict[str, Any],
                         scale_x: float, scale_y: float) -> Action | None:
        etype = evt["type"]
        if etype == "key_down":
            return Action(kind="key", payload={"vk": evt["vk"], "event": "down"})
        if etype == "key_up":
            return Action(kind="key", payload={"vk": evt["vk"], "event": "up"})
        if etype == "mouse_move":
            # Inject via SetCursorPos (absolute), bypass InputBackend's MOUSEEVENTF_MOVE
            # which expects relative deltas. Direct call here is intentional —
            # mouse position is one of the few things the recorder captures
            # absolutely, so absolute placement is the faithful replay.
            x = int(evt["x"] * scale_x)
            y = int(evt["y"] * scale_y)
            try:
                _user32.SetCursorPos(x, y)
            except Exception:
                pass
            return None  # already injected directly
        if etype == "mouse_button_down":
            return Action(kind="mouse",
                          payload={"op": "down", "button": evt["button"]})
        if etype == "mouse_button_up":
            return Action(kind="mouse",
                          payload={"op": "up", "button": evt["button"]})
        if etype == "gamepad_button_down":
            return Action(kind="gamepad",
                          payload={"op": "button_down", "button": evt["button"]})
        if etype == "gamepad_button_up":
            return Action(kind="gamepad",
                          payload={"op": "button_up", "button": evt["button"]})
        if etype == "gamepad_stick":
            return Action(kind="gamepad",
                          payload={"op": "stick", "side": evt["side"],
                                   "x": evt["x"], "y": evt["y"]},
                          duration_ms=0)
        if etype == "gamepad_trigger":
            return Action(kind="gamepad",
                          payload={"op": "trigger", "side": evt["side"],
                                   "value": evt["value"]},
                          duration_ms=0)
        return None

    def _wait_paused_decision(self) -> str:
        """Block until user decides R(esume) or Q(uit). 'R' default."""
        if self._paused_input_provider is not None:
            return self._paused_input_provider()
        # Drain so a held key doesn't auto-trigger
        while bool(_user32.GetAsyncKeyState(VK_R) & 0x8000) or \
              bool(_user32.GetAsyncKeyState(VK_Q) & 0x8000):
            time.sleep(0.05)
        while True:
            try:
                if bool(_user32.GetAsyncKeyState(VK_R) & 0x8000):
                    return "R"
                if bool(_user32.GetAsyncKeyState(VK_Q) & 0x8000):
                    return "Q"
                time.sleep(0.05)
            except KeyboardInterrupt:
                return "Q"
