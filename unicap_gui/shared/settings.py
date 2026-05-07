"""QSettings(IniFormat) wrapper —— 持久化窗口大小、active tab、各 tab 的 flag 值。

INI 路径：%APPDATA%/unicap-gui/unicap-gui.ini —— 不写注册表（FZ：好审计、好删）。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QSettings

from unicap_gui.shared.paths import gui_settings_dir


def _make_settings() -> QSettings:
    ini = gui_settings_dir() / "unicap-gui.ini"
    ini.parent.mkdir(parents=True, exist_ok=True)
    return QSettings(str(ini), QSettings.Format.IniFormat)


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
