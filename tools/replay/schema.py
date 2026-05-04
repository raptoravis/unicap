"""script.jsonl event types + meta.json schema + read/write helpers.

Forward compat: unknown meta fields don't fail validation; unknown event types
are warned-and-skipped by iter_events (player decides per event how strict to be).
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator


RECORDER_VERSION = "1.0"
SCHEMA_VERSION = 1

# Known event types. Unknown types are warned by iter_events; player ignores.
KNOWN_EVENT_TYPES = {
    "key_down",
    "key_up",
    "mouse_move",
    "mouse_button_down",
    "mouse_button_up",
    "gamepad_button_down",
    "gamepad_button_up",
    "gamepad_stick",
    "gamepad_trigger",
    "sync",
}

REQUIRED_META_FIELDS = {
    "name", "version", "recorded_at", "recorder_version",
    "game_exe", "api", "window_size",
}

log = logging.getLogger("unicap.replay")


@dataclass(slots=True)
class MetaModel:
    """meta.json structure. `syncs` is per-sync-id overrides for thresholds."""

    name: str
    version: int
    recorded_at: str            # ISO8601
    recorder_version: str
    game_exe: str
    api: str                    # 'dx' | 'vulkan'
    window_size: tuple[int, int]
    mouse_origin: tuple[int, int] = (0, 0)
    vlm_fallback_enabled: bool = False
    syncs: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["window_size"] = list(self.window_size)
        d["mouse_origin"] = list(self.mouse_origin)
        return d


def write_meta(path: Path, meta: MetaModel) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(meta.to_dict(), indent=2, ensure_ascii=False),
                    encoding="utf-8")


def load_meta(path: Path) -> MetaModel:
    raw = json.loads(path.read_text(encoding="utf-8"))
    validate_meta(raw)
    return MetaModel(
        name=raw["name"],
        version=int(raw["version"]),
        recorded_at=raw["recorded_at"],
        recorder_version=raw["recorder_version"],
        game_exe=raw["game_exe"],
        api=raw["api"],
        window_size=tuple(raw["window_size"]),  # type: ignore[arg-type]
        mouse_origin=tuple(raw.get("mouse_origin", [0, 0])),  # type: ignore[arg-type]
        vlm_fallback_enabled=bool(raw.get("vlm_fallback_enabled", False)),
        syncs=dict(raw.get("syncs", {})),
    )


def validate_meta(raw: dict[str, Any]) -> None:
    """Raise ValueError listing missing fields. Unknown fields are accepted (forward compat)."""
    if not isinstance(raw, dict):
        raise ValueError(f"meta.json: 顶层必须是 dict，实际 {type(raw).__name__}")
    missing = REQUIRED_META_FIELDS - raw.keys()
    if missing:
        raise ValueError(f"meta.json: 缺少必填字段 {sorted(missing)}")
    ws = raw.get("window_size")
    if not (isinstance(ws, (list, tuple)) and len(ws) == 2 and all(isinstance(x, int) for x in ws)):
        raise ValueError(f"meta.json: window_size 必须是 [int, int]，实际 {ws!r}")


def iter_events(jsonl_path: Path) -> Iterator[dict[str, Any]]:
    """Stream events from script.jsonl. Validates t_rel monotonic; raises on regression.

    Unknown event types are logged at WARNING and skipped (forward compat).
    Bad JSON lines abort iteration with ValueError including line number.
    """
    last_t = -1.0
    with open(jsonl_path, "r", encoding="utf-8") as f:
        for lineno, raw_line in enumerate(f, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                evt = json.loads(line)
            except json.JSONDecodeError as e:
                raise ValueError(f"{jsonl_path}:{lineno} JSON 解析失败: {e}") from e
            if not isinstance(evt, dict):
                raise ValueError(f"{jsonl_path}:{lineno} event 必须是 dict")

            t_rel = evt.get("t_rel")
            if not isinstance(t_rel, (int, float)) or t_rel < 0:
                raise ValueError(
                    f"{jsonl_path}:{lineno} t_rel 必须是非负数，实际 {t_rel!r}"
                )
            if t_rel < last_t:
                raise ValueError(
                    f"{jsonl_path}:{lineno} t_rel 倒退: {t_rel} < {last_t}"
                )
            last_t = float(t_rel)

            etype = evt.get("type")
            if etype not in KNOWN_EVENT_TYPES:
                log.warning("script %s:%d unknown event type %r — skipped",
                            jsonl_path, lineno, etype)
                continue
            yield evt
