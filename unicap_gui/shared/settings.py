"""QSettings(IniFormat) wrapper —— 持久化窗口大小、active tab、各 tab 的 flag 值。

INI 路径：%APPDATA%/unicap-gui/unicap-gui.ini —— 不写注册表（FZ：好审计、好删）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PySide6.QtCore import QSettings

from unicap_gui.shared.paths import gui_settings_dir


def ini_path() -> Path:
    return gui_settings_dir() / "unicap-gui.ini"


def _make_settings() -> QSettings:
    ini = ini_path()
    ini.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(ini), QSettings.Format.IniFormat)


def clear_all() -> Path:
    """清空 unicap-gui.ini 所有键。返回 ini 路径供调用者展示给用户。

    用 QSettings.clear() 而非直接删文件 —— sync() 后文件清成空 [General]，
    不会在内存里留 stale 值。
    """
    s = _make_settings()
    s.clear()
    s.sync()
    return ini_path()


def save(key: str, value: Any) -> None:
    s = _make_settings()
    s.setValue(key, value)
    s.sync()


def load(key: str, default: Any = None) -> Any:
    s = _make_settings()
    return s.value(key, default)


def save_flag_values(subcommand: str, values: dict[str, Any]) -> None:
    """把一个 tab 的 flag 值整组存。Key 形如 `flags/launch/game_path`。"""
    s = _make_settings()
    for k, v in values.items():
        # bool 必须显式存为 "true"/"false" 字符串，否则 IniFormat 读回是 str
        if isinstance(v, bool):
            s.setValue(f"flags/{subcommand}/{k}", "true" if v else "false")
        else:
            s.setValue(f"flags/{subcommand}/{k}", v)
    s.sync()


def load_flag_values(subcommand: str) -> dict[str, Any]:
    s = _make_settings()
    s.beginGroup(f"flags/{subcommand}")
    keys = s.childKeys()
    out: dict[str, Any] = {}
    for k in keys:
        out[k] = s.value(k)
    s.endGroup()
    return out


def save_string_list(group_key: str, items: list[str]) -> None:
    """每条独立编号 key（避免 IniFormat list / 含 `,`/`\\` 的 JSON string roundtrip 抽风）。

    存储位 `<group_key>/0`, `<group_key>/1`, ...；先 remove 整组（含老格式同名 flat key）再写。
    """
    s = _make_settings()
    s.remove(group_key)  # 清掉同名 flat key（legacy 单 string 残留）+ group 下所有 child
    s.beginGroup(group_key)
    for i, v in enumerate(items):
        if v:
            s.setValue(str(i), v)
    s.endGroup()
    s.sync()


def derive_train_dataset_from_launch() -> str:
    """train-bc tab 的 --dataset 智能默认。

    从 launch tab 已保存的 game_path + dataset_root 推 `<dataset_root>/<exe stem>/`，
    然后挑一个 session：
      - 优先最新的 dataset.h5 (`<game_dir>/<ts>/dataset.h5`，--raw 关时直接用)
      - 没有就挑最新的 raw session 目录（含 frames/ + inputs.jsonl，--raw 时用）
      - 都没有就回退到 game_dir 本身（让用户自己点浏览）
      - launch tab 从未存过路径 → 返回空字符串

    "最新" 按目录名字典序最大（`YYYYMMDD_HHMMSS` 排序与时间一致）。
    """
    launch = load_flag_values("launch")
    game_path = str(launch.get("game_path") or "")
    dataset_root = str(launch.get("dataset_root") or "")

    # 回退源 1：launch tab 的 game_path history（用户只用过 dropdown 选过游戏，
    # 但还没按 Start 持久化 game_path 时，能从 history 里捞到第一条）
    if not game_path:
        history = load_string_list("flags/launch/__game_path_history__")
        if history:
            game_path = history[0]

    # 回退源 2：schema 里 --dataset-root 的硬编码默认（main.py 也用同一份）
    if not dataset_root:
        from unicap_gui.shared.cli_schema import LAUNCH
        for f in LAUNCH.flags:
            if f.name == "--dataset-root":
                dataset_root = str(f.default or "")
                break

    if not dataset_root:
        return ""

    stem = Path(game_path).stem if game_path else ""
    game_dir = Path(dataset_root) / stem if stem else Path(dataset_root)

    # game_dir 已经存在 → 优先扫 session 目录，挑最新一份带数据的
    if game_dir.is_dir():
        sessions = sorted(
            (p for p in game_dir.iterdir() if p.is_dir() and p.name != "survey"),
            reverse=True,
        )
        for s in sessions:
            h5 = s / "dataset.h5"
            if h5.is_file():
                return str(h5)  # h5 模式默认值
        for s in sessions:
            if (s / "frames").is_dir() and (s / "inputs.jsonl").is_file():
                return str(s)   # raw 模式默认值

    # game_dir 还没建 / 没 session：回退到 game_dir，再回退到 dataset_root
    if game_dir.is_dir():
        return str(game_dir)
    if Path(dataset_root).is_dir():
        return str(dataset_root)
    return str(game_dir) if stem else str(dataset_root)


def derive_game_dir_from_launch() -> str:
    """video/pack tab 的 --game-dir 智能默认：从 launch tab 已保存的
    game_path + dataset_root 推 `<dataset_root>/<exe stem>`。

    返回空字符串表示无法推（用户从未 Start 过 launch tab，或路径残缺）。
    """
    launch = load_flag_values("launch")
    game_path = str(launch.get("game_path") or "")
    dataset_root = str(launch.get("dataset_root") or "")
    if not game_path or not dataset_root:
        return ""
    stem = Path(game_path).stem
    if not stem:
        return ""
    return str(Path(dataset_root) / stem)


def load_string_list(group_key: str) -> list[str]:
    """读 save_string_list 写的内容；按数字 key 排序还原顺序。"""
    s = _make_settings()
    s.beginGroup(group_key)
    keys = s.childKeys()
    s.endGroup()
    pairs: list[tuple[int, str]] = []
    for k in keys:
        try:
            idx = int(k)
        except ValueError:
            continue
        v = s.value(f"{group_key}/{k}")
        if v is None:
            continue
        if not isinstance(v, str):
            v = str(v)
        if v:
            pairs.append((idx, v))
    pairs.sort(key=lambda p: p[0])
    return [v for _, v in pairs]
