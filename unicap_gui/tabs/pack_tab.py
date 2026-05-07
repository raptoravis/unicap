"""PackTab —— main.py pack 子命令 + session 树展示。"""

from __future__ import annotations

import re

from PySide6.QtWidgets import QWidget

from unicap_gui.shared.cli_schema import PACK
from unicap_gui.tabs.base_tab import BaseTab
from unicap_gui.widgets.session_tree import SessionTree


_RE_PACK_DONE = re.compile(r"\[PACK\].*?完成")


class PackTab(BaseTab):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(PACK, parent)

    def _wire_extra(self) -> None:
        self._tree = SessionTree(self)
        self._top_box.addWidget(self._tree)

        self._form.values_changed.connect(self._on_form_changed)
        self._on_form_changed()

        self._runner.line_received.connect(self._on_log_line)

    def _on_form_changed(self) -> None:
        v = self._form.values()
        self._tree.set_game_dir(v.get("game_dir") or "")

    def _on_log_line(self, line: str) -> None:
        if _RE_PACK_DONE.search(line):
            self._tree.rescan()
