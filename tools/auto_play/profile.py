"""GameProfile — declarative per-game config loaded from profiles/*.yaml.

Profile is data, not code: control bindings, keep-alive sequence, watchdog
parameters, VLM operation guidance. Loaded once at runner start, immutable
afterwards.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


PROFILES_DIR_NAME = "profiles"

REQUIRED_TOP_LEVEL_KEYS = {
    "name", "description", "controls", "reserved_keys",
    "keep_alive", "watchdog", "input", "vlm",
}
REQUIRED_KEEP_ALIVE_KEYS = {"period_s", "sequence", "recovery"}
REQUIRED_WATCHDOG_KEYS = {
    "sample_period_s", "static_diff_threshold", "consecutive_static_required",
}
REQUIRED_INPUT_KEYS = {"prefer_gamepad", "mouse_sensitivity"}
REQUIRED_VLM_KEYS = {"game_instructions", "frame_subsample_long_edge"}

# F7 = replay record stop, F8/F9 = capture start/stop. These three are unicap's
# hotkeys — auto-play (and replay player's input injection) must NEVER inject
# them. Profile may add more entries (e.g. F6) but cannot remove these three.
MANDATORY_RESERVED_KEYS = {"F7", "F8", "F9"}

VALID_STEP_ACTIONS = {
    "move_forward", "move_back", "move_left", "move_right",
    "turn", "attack", "interact", "jump",
    "press_key", "stick_jitter", "wait",
}


@dataclass(slots=True)
class GameProfile:
    name: str
    description: str
    controls: dict[str, Any]
    reserved_keys: list[str]
    keep_alive: dict[str, Any]
    watchdog: dict[str, Any]
    input: dict[str, Any]
    vlm: dict[str, Any]
    source_path: Path | None = None


def _profiles_dir(override: Path | None) -> Path:
    if override is not None:
        return override
    # tools/auto_play/profile.py → repo root → profiles/
    return Path(__file__).resolve().parents[2] / PROFILES_DIR_NAME


def _validate_profile(data: dict, source: str) -> None:
    missing = REQUIRED_TOP_LEVEL_KEYS - data.keys()
    if missing:
        raise ValueError(f"profile {source}: 缺少必填字段 {sorted(missing)}")

    for sub_name, required in (
        ("keep_alive", REQUIRED_KEEP_ALIVE_KEYS),
        ("watchdog",   REQUIRED_WATCHDOG_KEYS),
        ("input",      REQUIRED_INPUT_KEYS),
        ("vlm",        REQUIRED_VLM_KEYS),
    ):
        sub = data.get(sub_name)
        if not isinstance(sub, dict):
            raise ValueError(f"profile {source}: '{sub_name}' 必须是 dict")
        sub_missing = required - sub.keys()
        if sub_missing:
            raise ValueError(
                f"profile {source}: '{sub_name}' 缺少 {sorted(sub_missing)}"
            )

    reserved = data["reserved_keys"]
    if not isinstance(reserved, list) or not all(isinstance(k, str) for k in reserved):
        raise ValueError(f"profile {source}: 'reserved_keys' 必须是 str list")
    reserved_upper = {k.upper() for k in reserved}
    if not MANDATORY_RESERVED_KEYS.issubset(reserved_upper):
        raise ValueError(
            f"profile {source}: reserved_keys 必须包含 {sorted(MANDATORY_RESERVED_KEYS)}"
            f"（unicap 自身的 F8/F9 不允许 bot 注入）"
        )

    controls = data["controls"]
    if not isinstance(controls, dict):
        raise ValueError(f"profile {source}: 'controls' 必须是 dict")
    for ctrl_name, ctrl_value in controls.items():
        if isinstance(ctrl_value, str) and ctrl_value.upper() in reserved_upper:
            raise ValueError(
                f"profile {source}: controls.{ctrl_name}={ctrl_value!r}"
                f" 与 reserved_keys 冲突"
            )

    for seq_name in ("sequence", "recovery"):
        seq = data["keep_alive"].get(seq_name)
        if not isinstance(seq, list):
            raise ValueError(
                f"profile {source}: 'keep_alive.{seq_name}' 必须是 list"
            )
        for i, step in enumerate(seq):
            if not isinstance(step, dict) or "action" not in step:
                raise ValueError(
                    f"profile {source}: keep_alive.{seq_name}[{i}] 缺少 'action'"
                )
            if step["action"] not in VALID_STEP_ACTIONS:
                raise ValueError(
                    f"profile {source}: keep_alive.{seq_name}[{i}].action="
                    f"{step['action']!r} 不在 {sorted(VALID_STEP_ACTIONS)}"
                )


def load_profile(
    name: str,
    fallback: bool = True,
    profiles_dir: Path | None = None,
) -> GameProfile:
    """Load `<profiles_dir>/<name>.yaml`. With fallback=True, fuzzy-match the
    name against existing profile stems; if nothing matches, return _default.
    """
    pdir = _profiles_dir(profiles_dir)
    if not pdir.is_dir():
        raise FileNotFoundError(f"profiles 目录不存在: {pdir}")

    target_path = pdir / f"{name}.yaml"
    if target_path.is_file():
        return _read_profile_file(target_path)

    if fallback:
        # Fuzzy: strip non-alnum, case-insensitive substring match against stems
        norm = re.sub(r"[^a-z0-9]", "", name.lower())
        for p in pdir.glob("*.yaml"):
            stem_norm = re.sub(r"[^a-z0-9]", "", p.stem.lower())
            if stem_norm and (stem_norm in norm or norm in stem_norm):
                if p.stem == "_default":
                    continue
                print(f"[AUTO-PLAY] profile fuzzy match: {name!r} → {p.name}")
                return _read_profile_file(p)

        default_path = pdir / "_default.yaml"
        if default_path.is_file():
            print(f"[AUTO-PLAY] profile {name!r} 未找到，回落 _default.yaml")
            return _read_profile_file(default_path)

    raise FileNotFoundError(
        f"profile '{name}' 未在 {pdir} 找到 (fallback={'on' if fallback else 'off'})"
    )


def _read_profile_file(path: Path) -> GameProfile:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"profile {path} YAML 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"profile {path}: 顶层必须是 mapping/dict")
    _validate_profile(data, str(path))
    return GameProfile(
        name=data["name"],
        description=data["description"],
        controls=data["controls"],
        reserved_keys=[k.upper() for k in data["reserved_keys"]],
        keep_alive=data["keep_alive"],
        watchdog=data["watchdog"],
        input=data["input"],
        vlm=data["vlm"],
        source_path=path,
    )


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    pdir = _profiles_dir(profiles_dir)
    if not pdir.is_dir():
        return []
    return sorted(p.stem for p in pdir.glob("*.yaml") if p.stem != "_default")
