"""replay — record / playback game-launch input sequences with visual sync points.

Public API:
  RECORDER_VERSION         — bumped on schema change
  ReplayRecorder           — records F6/F7-driven scene scripts
  ReplayPlayer, ReplayResult — replays scripts with sync-point waiting
  load_meta, write_meta, iter_events, validate_meta — schema helpers

Usage flows live in main.py (`--record-scene` / `--replay-scene`).
"""

from tools.replay.player import ReplayPlayer, ReplayResult
from tools.replay.recorder import ReplayRecorder
from tools.replay.schema import (
    RECORDER_VERSION,
    iter_events,
    load_meta,
    validate_meta,
    write_meta,
)

__all__ = [
    "RECORDER_VERSION",
    "ReplayPlayer",
    "ReplayRecorder",
    "ReplayResult",
    "iter_events",
    "load_meta",
    "validate_meta",
    "write_meta",
]
