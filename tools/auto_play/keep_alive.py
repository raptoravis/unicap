"""KeepAliveDriver — A-layer driver, no vision, follows profile sequence.

Also exposes the standalone `step_to_actions(profile, step, rng)` translator
that the watchdog reuses for its profile-declared recovery sequence.
"""

from __future__ import annotations

import random
from typing import Any

from tools.auto_play.driver import Action, BotDriver, Observation
from tools.auto_play.profile import GameProfile


def step_to_actions(
    profile: GameProfile,
    step: dict[str, Any],
    rng: random.Random,
) -> list[Action]:
    """Translate one keep_alive.sequence / recovery step into Actions.

    Public so the watchdog can reuse the same translation without reaching
    into a driver's internals. `wait` returns a single zero-action no-op so
    the caller's loop honors duration_ms as a real pause.
    """
    action_name = step["action"]
    base_dur = int(step.get("duration_ms", 100))
    # ±20% jitter so input stream isn't exactly periodic
    dur = max(0, int(base_dur * rng.uniform(0.8, 1.2)))
    payload = step.get("payload") or {}

    controls = profile.controls
    prefer_pad = bool(profile.input.get("prefer_gamepad", False))
    mouse_sens = float(profile.input.get("mouse_sensitivity", 1.0))

    if action_name == "wait":
        return [Action(kind="wait", payload={}, duration_ms=dur)]

    if action_name in ("move_forward", "move_back", "move_left", "move_right"):
        ctrl = controls.get(action_name)
        return _press_control(ctrl, dur)

    if action_name in ("attack", "interact", "jump"):
        ctrl_key = action_name
        if prefer_pad and f"gamepad_{action_name}" in controls:
            ctrl_key = f"gamepad_{action_name}"
        ctrl = controls.get(ctrl_key)
        return _press_control(ctrl, dur)

    if action_name == "dismiss_ui":
        # Per-game "back / close current UI" key. FF7R=M, most others=ESC.
        # Profile authors set controls.dismiss_ui to keep recovery / sequence
        # YAML portable across games (don't hardcode press_key vk:M for FF7R
        # only to discover the same step needs vk:ESC for DOOM Eternal).
        ctrl = controls.get("dismiss_ui")
        return _press_control(ctrl, dur)

    if action_name == "press_key":
        vk = payload.get("vk")
        if not vk:
            return []
        return [Action(kind="key", payload={"vk": vk, "event": "press"},
                       duration_ms=dur)]

    if action_name == "turn":
        direction = payload.get("direction", "random")
        magnitude = float(payload.get("magnitude", 1.0))
        sign = rng.choice([-1, 1]) if direction == "random" else (
            -1 if direction == "left" else 1
        )
        turn_axis = controls.get("turn_axis", "mouse")
        if turn_axis == "gamepad_rstick" and prefer_pad:
            return [Action(
                kind="gamepad",
                payload={"op": "stick", "side": "right",
                         "x": sign * 0.7 * magnitude, "y": 0.0},
                duration_ms=dur,
            )]
        dx = int(sign * 300 * magnitude * mouse_sens)
        return [Action(
            kind="mouse",
            payload={"op": "move", "dx": dx, "dy": 0},
            duration_ms=0,
        )]

    if action_name == "stick_jitter":
        x = rng.uniform(-0.3, 0.3)
        y = rng.uniform(-0.3, 0.3)
        return [Action(
            kind="gamepad",
            payload={"op": "stick", "side": "left", "x": x, "y": y},
            duration_ms=dur,
        )]

    return []


def _press_control(ctrl: Any, duration_ms: int) -> list[Action]:
    if ctrl is None:
        return []
    ctrl_str = str(ctrl)
    if ctrl_str.startswith("mouse_"):
        button = ctrl_str.split("_", 1)[1]
        return [Action(
            kind="mouse",
            payload={"op": "click", "button": button},
            duration_ms=duration_ms,
        )]
    if ctrl_str.startswith("gamepad_"):
        button = ctrl_str.split("_", 1)[1]
        return [Action(
            kind="gamepad",
            payload={"op": "button", "button": button},
            duration_ms=duration_ms,
        )]
    # Default: treat as keyboard vk name
    return [Action(
        kind="key",
        payload={"vk": ctrl_str, "event": "press"},
        duration_ms=duration_ms,
    )]


class KeepAliveDriver(BotDriver):
    """No-vision bot. Outputs Actions per profile.keep_alive.sequence."""

    def __init__(self, profile: GameProfile, seed: int | None = None) -> None:
        self._profile = profile
        self._seq: list[dict[str, Any]] = list(profile.keep_alive.get("sequence") or [])
        if not self._seq:
            raise ValueError(
                f"profile {profile.name}: keep_alive.sequence 为空 — 无 keep-alive 行为可执行"
            )
        self._cursor = 0
        self._rng = random.Random(seed)
        self._period_s = float(profile.keep_alive.get("period_s", 1.0))

    @property
    def decision_period_s(self) -> float:
        """Minimum seconds between next_actions calls.

        The runner uses this as a sleep floor — if a step's actions take
        longer than period_s to inject, the next call happens immediately
        without further delay.
        """
        return self._period_s

    def next_actions(self, observation: Observation) -> list[Action]:
        step = self._seq[self._cursor]
        self._cursor = (self._cursor + 1) % len(self._seq)
        return step_to_actions(self._profile, step, self._rng)
