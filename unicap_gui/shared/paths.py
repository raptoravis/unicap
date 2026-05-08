"""Well-known paths shared by all UI modules."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    """是否运行在 Nuitka standalone 产物里（vs 源码 dev 运行）。

    判据：sys.executable 不是 python.exe / pythonw.exe / py.exe。
    Nuitka standalone 把 sys.executable 设为产物 exe（如 unicap-gui.exe）。
    """
    if getattr(sys, "frozen", False):  # PyInstaller marker (兜底)
        return True
    name = Path(sys.executable).name.lower()
    return "python" not in name and name not in ("py.exe", "py")


def repo_root() -> Path:
    """unicap repo 根目录（dev: main.py 所在目录；frozen: exe 所在目录）。"""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def main_py() -> Path:
    return repo_root() / "main.py"


def cli_executable() -> Path:
    """frozen 模式下同目录的 unicap.exe（GUI 包用 multidist 内置）。"""
    return Path(sys.executable).resolve().parent / "unicap.exe"


def cli_argv_prefix() -> list[str]:
    """spawn CLI 子进程的 argv 前缀（不含 subcommand 本体）。

    frozen: ``[unicap.exe]``         —— 直接调同目录的 multidist 产物
    dev:    ``[python, -X utf8, -u, main.py]``  —— 走 venv python
    """
    if is_frozen():
        return [str(cli_executable())]
    return [sys.executable, "-X", "utf8", "-u", str(main_py())]


def profiles_dir() -> Path:
    return repo_root() / "profiles"


def models_dir() -> Path:
    """`<repo_root>/models/<profile>/...` —— train-bc 产物根。"""
    return repo_root() / "models"


def favicon_path() -> Path:
    """程序图标。Dev 模式：repo 根；frozen 模式：exe 同目录（build 时
    --include-data-files 拷到 dist 根）。返回值可能不存在 —— caller 自己 fallback。"""
    return repo_root() / "favicon.png"


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
    """当前 venv 的 python 解释器。子进程跑 main.py 用它，确保依赖一致。

    Deprecated for spawn —— 用 ``cli_argv_prefix()`` 代替（frozen 自适应）。
    保留供旧 caller 直接读 venv python 路径。
    """
    return sys.executable
