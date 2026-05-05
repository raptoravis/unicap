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
    """meta.json structure. `syncs` is per-sync-id overrides for thresholds.

    `observed_inputs` is the union of every input the recorder saw fired during
    this session — "the player at least once pressed each of these". It's a
    capability *minimum*, not the game's full input space. Useful as a starting
    point for a profile.controls map and (eventually) as a hard constraint on
    the VLM driver's output space.
    """

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
    observed_inputs: dict[str, list[str]] = field(default_factory=dict)

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
        observed_inputs=dict(raw.get("observed_inputs", {})),
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


def aggregate_observed_inputs(events: list[dict[str, Any]]) -> dict[str, list[str]]:
    """Walk `events` once, return the union of every input channel that fired.

    Outputs a dict with sorted lists per channel:
      - kb: virtual-key friendly names (W, SPACE, SHIFT, ...)
      - mouse_buttons: left | right | middle
      - gamepad_buttons: A | B | DPAD_UP | ...
      - gamepad_sticks / gamepad_triggers: left | right (which side ever moved)

    Empty channels are omitted from the dict so meta.json stays compact for
    keyboard-only sessions.
    """
    kb: set[str] = set()
    mouse_btns: set[str] = set()
    gp_btns: set[str] = set()
    gp_sticks: set[str] = set()
    gp_trigs: set[str] = set()
    for e in events:
        t = e.get("type")
        if t == "key_down":
            v = e.get("vk")
            if isinstance(v, str):
                kb.add(v)
        elif t == "mouse_button_down":
            b = e.get("button")
            if isinstance(b, str):
                mouse_btns.add(b)
        elif t == "gamepad_button_down":
            b = e.get("button")
            if isinstance(b, str):
                gp_btns.add(b)
        elif t == "gamepad_stick":
            s = e.get("side")
            if isinstance(s, str):
                gp_sticks.add(s)
        elif t == "gamepad_trigger":
            s = e.get("side")
            if isinstance(s, str):
                gp_trigs.add(s)
    out: dict[str, list[str]] = {}
    if kb:         out["kb"] = sorted(kb)
    if mouse_btns: out["mouse_buttons"] = sorted(mouse_btns)
    if gp_btns:    out["gamepad_buttons"] = sorted(gp_btns)
    if gp_sticks:  out["gamepad_sticks"] = sorted(gp_sticks)
    if gp_trigs:   out["gamepad_triggers"] = sorted(gp_trigs)
    return out


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
