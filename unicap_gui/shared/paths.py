"""Well-known paths shared by all UI modules."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def repo_root() -> Path:
    """unicap repo 根目录（即 main.py 所在目录）。"""
    return Path(__file__).resolve().parents[2]


def main_py() -> Path:
    return repo_root() / "main.py"


def profiles_dir() -> Path:
    return repo_root() / "profiles"


def unicap_temp() -> Path:
    """%TEMP%/unicap — addon + auto_play log 写这里。"""
    base = os.environ.get("TEMP") or os.environ.get("TMP") or "."
    return Path(base) / "unicap"


def auto_play_log() -> Path:
    return unicap_temp() / "auto_play.log"


def gui_settings_dir() -> Path:
    """`%APPDATA%/unicap-gui/`（QSettings IniFormat 写这里）。"""
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / "unicap-gui"
    return Path.home() / ".unicap-gui"


def gui_log_path() -> Path:
    return gui_settings_dir() / "unicap-gui.log"


def python_for_subprocess() -> str:
    """当前 venv 的 python 解释器。子进程跑 main.py 用它，确保依赖一致。"""
    return sys.executable
