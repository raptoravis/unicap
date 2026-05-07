"""LogPane —— 5000 行环形 buffer + 导出 + 自动滚动到底部。

QPlainTextEdit 自带 setMaximumBlockCount —— 直接用，省手撸 deque。
"""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import (
    QFileDialog, QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget,
)


class LogPane(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._view = QPlainTextEdit(self)
        self._view.setReadOnly(True)
        self._view.setMaximumBlockCount(5000)  # MH-7 环形 buffer 上限
        self._view.setUndoRedoEnabled(False)
        self._view.setLineWrapMode(QPlainTextEdit.NoWrap)
        font = QFont("Consolas")
        if not font.exactMatch():
            font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self._view.setFont(font)

        self._auto_scroll = True

        btn_clear = QPushButton("清空", self)
        btn_clear.setMaximumWidth(80)
        btn_clear.clicked.connect(self._view.clear)

        btn_export = QPushButton("导出日志…", self)
        btn_export.setMaximumWidth(110)
        btn_export.clicked.connect(self._on_export)

        bar = QHBoxLayout()
        bar.addStretch(1)
        bar.addWidget(btn_clear)
        bar.addWidget(btn_export)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        layout.addWidget(self._view, stretch=1)
        layout.addLayout(bar)

        # 当用户手动滚到非底部时关掉 auto-scroll；回到底部时打开
        self._view.verticalScrollBar().valueChanged.connect(self._on_scrolled)

    # ── slot ──────────────────────────────────────────────────────────────

    def append_line(self, line: str) -> None:
        self._view.appendPlainText(line)
        if self._auto_scroll:
            self._view.moveCursor(QTextCursor.End)
            self._view.ensureCursorVisible()

    def append_separator(self, label: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        self.append_line(f"\n──────── {ts} {label} ────────")

    def text_buffer(self) -> str:
        return self._view.toPlainText()

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _on_scrolled(self, value: int) -> None:
        sb = self._view.verticalScrollBar()
        self._auto_scroll = (value >= sb.maximum() - 4)

    def _on_export(self) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        path, _ = QFileDialog.getSaveFileName(
            self, "导出日志", f"unicap-gui-{ts}.log", "Log (*.log *.txt);;All (*)",
        )
        if not path:
            return
        try:
            Path(path).write_text(self.text_buffer(), encoding="utf-8")
        except OSError as e:
            self.append_line(f"[unicap-gui] 导出失败：{e}")
