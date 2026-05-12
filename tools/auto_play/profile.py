"""GameProfile — declarative per-game config loaded from profiles/*.yaml.

Profile is data, not code: control bindings, keep-alive sequence, watchdog
parameters. Loaded once at runner start, immutable afterwards.
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
    "keep_alive", "watchdog", "input",
}
# Optional top-level keys (do not raise if missing).
OPTIONAL_TOP_LEVEL_KEYS = {"driver", "bc", "hybrid"}
VALID_DRIVERS = {"keep_alive", "bc", "hybrid"}
REQUIRED_KEEP_ALIVE_KEYS = {"period_s", "sequence", "recovery"}
REQUIRED_WATCHDOG_KEYS = {
    "sample_period_s", "static_diff_threshold", "consecutive_static_required",
}
REQUIRED_INPUT_KEYS = {"prefer_gamepad", "mouse_sensitivity"}

# F6/F7 = demo-quality markers (good/bad), F8/F9 = capture start/stop.
# These are unicap's hotkeys — auto-play must NEVER inject them. Profile may
# add more entries but cannot remove these.
MANDATORY_RESERVED_KEYS = {"F6", "F7", "F8", "F9"}

VALID_STEP_ACTIONS = {
    "move_forward", "move_back", "move_left", "move_right",
    "turn", "attack", "interact", "jump",
    "press_key", "stick_jitter", "wait",
    # `dismiss_ui` resolves to controls.dismiss_ui — the per-game "back / close
    # current UI / return to gameplay" key. ff7r=M, most other games=ESC.
    "dismiss_ui",
    # `climb_down` resolves to controls.climb_down — Batman: AK 房檐/扶手解卡键
    # (LCtrl)，其他游戏可不设这个 control 就不会用。
    "climb_down",
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
    source_path: Path | None = None
    driver: str = "keep_alive"          # 'keep_alive' (default) | 'bc' | 'hybrid'
    bc: dict[str, Any] = field(default_factory=dict)
    hybrid: dict[str, Any] = field(default_factory=dict)


def _profiles_dir(override: Path | None) -> Path:
    if override is not None:
        return override
    # tools/auto_play/profile.py → repo root → profiles/
    return Path(__file__).resolve().parents[2] / PROFILES_DIR_NAME


def _validate_profile(data: dict, source: str) -> None:
    missing = REQUIRED_TOP_LEVEL_KEYS - data.keys()
    if missing:
        raise ValueError(f"profile {source}: 缺少必填字段 {sorted(missing)}")

    driver = str(data.get("driver", "keep_alive"))
    if driver not in VALID_DRIVERS:
        raise ValueError(
            f"profile {source}: driver={driver!r} 不在 {sorted(VALID_DRIVERS)}"
        )
    if driver in ("bc", "hybrid"):
        bc = data.get("bc")
        if not isinstance(bc, dict):
            raise ValueError(
                f"profile {source}: driver={driver} 时必须有 'bc:' 段（含 model_path）"
            )
        if not bc.get("model_path"):
            raise ValueError(
                f"profile {source}: driver={driver} 时 bc.model_path 必填"
                f"（指向 train-bc 输出的 model.onnx）"
            )

    for sub_name, required in (
        ("keep_alive", REQUIRED_KEEP_ALIVE_KEYS),
        ("watchdog",   REQUIRED_WATCHDOG_KEYS),
        ("input",      REQUIRED_INPUT_KEYS),
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
    # Auto-merge mandatory keys (F6/F7/F8/F9 are unicap-managed; profile may
    # omit them — we silently inject so existing profiles stay valid).
    reserved_upper = {k.upper() for k in reserved} | MANDATORY_RESERVED_KEYS

    controls = data["controls"]
    if not isinstance(controls, dict):
        raise ValueError(f"profile {source}: 'controls' 必须是 dict")
    for ctrl_name, ctrl_value in controls.items():
        if isinstance(ctrl_value, str) and ctrl_value.upper() in reserved_upper:
            raise ValueError(
                f"profile {source}: controls.{ctrl_name}={ctrl_value!r}"
                f" 与 reserved_keys 冲突（含 unicap 自管 F6/F7/F8/F9）"
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

    # fallback=False 且 profile 不存在：从 _default 复制一份 stub 出来再 raise，
    # 让用户少一步 cp，但强制确认 controls 后再重跑（避免拿默认绑定训出错的模型）。
    default_path = pdir / "_default.yaml"
    if not target_path.exists() and default_path.is_file() and _is_safe_profile_name(name):
        _stub_profile_from_default(default_path, target_path, name)
        raise FileNotFoundError(
            f"profile '{name}' 不存在，已基于 _default 生成模板:\n"
            f"  {target_path}\n"
            f"请编辑 controls / keep_alive 后重跑（确保按键绑定匹配实际游戏）。"
        )

    raise FileNotFoundError(
        f"profile '{name}' 未在 {pdir} 找到 (fallback={'on' if fallback else 'off'})"
    )


_SAFE_PROFILE_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_\-]*$")


def _is_safe_profile_name(name: str) -> bool:
    # 防止 ../ 之类路径注入；只允许常见 stem 字符。
    return bool(_SAFE_PROFILE_NAME_RE.match(name)) and name != "_default"


def _stub_profile_from_default(default_path: Path, target_path: Path, name: str) -> None:
    text = default_path.read_text(encoding="utf-8")
    # 替换顶层 `name:` 行
    new_text = re.sub(
        r"^name:\s*.*$",
        f"name: {name}",
        text,
        count=1,
        flags=re.MULTILINE,
    )
    header = (
        f"# AUTO-GENERATED stub for '{name}' — 复制自 _default.yaml\n"
        f"# TODO: 检查 controls 是否匹配游戏实际按键（互动键、攻击键、dismiss_ui 等）\n"
        f"# 改完后重跑命令；本注释可删。\n"
    )
    target_path.write_text(header + new_text, encoding="utf-8")
    print(f"[AUTO-PLAY] stub profile 已生成: {target_path}")


def _read_profile_file(path: Path) -> GameProfile:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        raise ValueError(f"profile {path} YAML 解析失败: {e}") from e
    if not isinstance(data, dict):
        raise ValueError(f"profile {path}: 顶层必须是 mapping/dict")
    _validate_profile(data, str(path))
    # Auto-merge MANDATORY_RESERVED_KEYS so callers can rely on F6/F7/F8/F9
    # being present regardless of the profile YAML's explicit list.
    merged_reserved = sorted({k.upper() for k in data["reserved_keys"]} | MANDATORY_RESERVED_KEYS)
    return GameProfile(
        name=data["name"],
        description=data["description"],
        controls=data["controls"],
        reserved_keys=merged_reserved,
        keep_alive=data["keep_alive"],
        watchdog=data["watchdog"],
        input=data["input"],
        source_path=path,
        driver=str(data.get("driver", "keep_alive")),
        bc=dict(data.get("bc", {})),
        hybrid=dict(data.get("hybrid", {})),
    )


def list_profiles(profiles_dir: Path | None = None) -> list[str]:
    pdir = _profiles_dir(profiles_dir)
    if not pdir.is_dir():
        return []
    return sorted(p.stem for p in pdir.glob("*.yaml") if p.stem != "_default")
