"""BotDriver contract — what every driver exposes.

Drivers turn an `Observation` (current frame + timestamp + profile) into a list
of `Action` objects. The runner injects each Action via the shared InputBackend.

The contract is intentionally narrow: drivers declare *what* to do, never
*how* it is delivered to the OS — leaves room for future driver implementations
behind the same `next_actions(...)` call.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal, TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from tools.auto_play.profile import GameProfile


ActionKind = Literal["key", "mouse", "gamepad", "wait"]


@dataclass(slots=True)
class Action:
    """One unit of input injection.

    kind=='key':     payload = {'vk': 'W', 'event': 'press' | 'down' | 'up'}
    kind=='mouse':   payload = {'op': 'move' | 'click', 'dx': int, 'dy': int, 'button': 'left'|'right'}
    kind=='gamepad': payload = {'op': 'button' | 'stick' | 'trigger',
                                'button': str, 'side': 'left'|'right',
                                'x': float, 'y': float, 'value': float}
    kind=='wait':    payload = {} — pure pause for duration_ms (no input injected)
    duration_ms decides how long a press is held before release; 0 = instant tap.
    """

    kind: ActionKind
    payload: dict[str, Any]
    duration_ms: int = 0


@dataclass(slots=True)
class Observation:
    """What the driver sees on each decision tick.

    frame_bgr is the latest BackBuffer.png content (BGR uint8 ndarray) or None
    when the watchdog hasn't read a frame yet (capture just started).
    """

    timestamp: float
    profile: "GameProfile"
    frame_bgr: np.ndarray | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class BotDriver(ABC):
    """Contract: A subclass produces Actions; the runner injects them."""

    @abstractmethod
    def next_actions(self, observation: Observation) -> list[Action]:
        """Return zero or more Actions to inject *now*.

        Must be non-blocking (caller is the runner's decision thread). Driver
        is allowed to maintain internal state across calls (cursors, RNG, etc.)
        but must NOT touch the InputBackend directly — only via returned Actions.
        """

    def on_start(self) -> None:
        """Optional one-time hook before the first next_actions call."""

    def on_stop(self) -> None:
        """Optional cleanup hook called once during runner.stop()."""

    @property
    def decision_period_s(self) -> float:
        """Seconds between successive next_actions calls. Override if needed."""
        return 1.0
