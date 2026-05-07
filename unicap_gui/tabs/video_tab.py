"""VideoTab —— main.py video 子命令 + session 树展示。

5c：在 BaseTab 上面插 SessionTree；--game-dir 改时触发扫描；子进程跑期间
grep `[VIDEO] ... 完成` 行重新扫，让图标实时更新（acceptance G-010）。
"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QWidget

from unicap_gui.shared import settings as gui_settings
from unicap_gui.shared.cli_schema import VIDEO
from unicap_gui.tabs.base_tab import BaseTab
from unicap_gui.widgets.session_tree import SessionTree


_RE_VIDEO_DONE = re.compile(r"\[VIDEO\].*?完成")
_RE_PACK_DONE = re.compile(r"\[PACK\].*?完成")


class VideoTab(BaseTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(VIDEO, parent)

    def _wire_extra(self) -> None:
        self._tree = SessionTree(self)
        self._top_box.addWidget(self._tree)

        # 表单 --game-dir 改 → 重扫
        self._form.values_changed.connect(self._on_form_changed)
        self._on_form_changed()  # 初始扫一次

        # 子进程行抓 `[VIDEO] xxx 完成` —— 增量重扫该 session 行
        self._runner.line_received.connect(self._on_log_line)

    def _apply_smart_defaults(self) -> None:
        # 用户没保存 game_dir 时，从 launch tab 推：<dataset_root>/<exe stem>
        if self._form.values().get("game_dir"):
            return
        derived = gui_settings.derive_game_dir_from_launch()
        if derived:
            self._form.set_values({"game_dir": derived})

    def _on_form_changed(self) -> None:
        v = self._form.values()
        self._tree.set_game_dir(v.get("game_dir") or "")

    def _on_log_line(self, line: str) -> None:
        if _RE_VIDEO_DONE.search(line):
            self._tree.rescan()


