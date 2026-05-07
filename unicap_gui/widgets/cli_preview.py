"""CLIPreview —— 等价 CLI 文本框（只读）+ 复制按钮 + Extra args LineEdit。

依赖外部喂值：tab 拿表单值后调 set_argv()；用户改 Extra args → emit extra_args_changed。
拼出来的命令格式：
    uv run main.py <subcommand> --flag1 v1 --flag2 v2 [extra args...]
"""

from __future__ import annotations

import shlex

from PySide6.QtCore import Signal
from PySide6.QtGui import QClipboard, QFont
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton,
    QVBoxLayout, QWidget,
)


class CLIPreview(QWidget):
    """显示等价 CLI；提供 Extra args 透传。"""

    extra_args_changed = Signal()  # 用户改了 Extra args → tab 拿去 rebuild

    def __init__(self, subcommand: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._subcommand = subcommand
        self._argv: list[str] = []

        title = QLabel(f"等价 CLI 命令（{subcommand}）：")
        title.setStyleSheet("font-weight: bold;")

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setMaximumHeight(70)
        self._preview.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        font = QFont("Consolas")
        font.setStyleHint(QFont.Monospace)
        font.setPointSize(9)
        self._preview.setFont(font)

        btn_copy = QPushButton("复制")
        btn_copy.setMaximumWidth(80)
        btn_copy.clicked.connect(self._on_copy)

        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(btn_copy)

        extra_label = QLabel("Extra args（透传到子进程；空格分隔，shell-quoted）：")
        self._extra = QLineEdit()
        self._extra.setPlaceholderText("--auto-play-debug")
        self._extra.textChanged.connect(self._on_extra_changed)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self._preview)
        layout.addWidget(extra_label)
        layout.addWidget(self._extra)

    # ── 公开 API ──────────────────────────────────────────────────────────

    def set_argv(self, argv_tail: list[str]) -> None:
        """argv_tail 不含 python/main.py/subcommand。"""
        self._argv = argv_tail
        self._refresh()

    def extra_args_argv(self) -> list[str]:
        """把 LineEdit 里的字符串 shlex.split 成 argv。"""
        text = self._extra.text().strip()
        if not text:
            return []
        try:
            return shlex.split(text, posix=False)
        except ValueError:
            return []

    def set_extra_args(self, text: str) -> None:
        self._extra.blockSignals(True)
        self._extra.setText(text)
        self._extra.blockSignals(False)
        self._refresh()

    def extra_args_text(self) -> str:
        return self._extra.text()

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _refresh(self) -> None:
        parts = ["uv", "run", "main.py", self._subcommand, *self._argv,
                 *self.extra_args_argv()]
        cmd = " ".join(_quote(p) for p in parts)
        self._preview.setPlainText(cmd)

    def _on_copy(self) -> None:
        cb: QClipboard = QApplication.clipboard()
        cb.setText(self._preview.toPlainText())

    def _on_extra_changed(self, _: str) -> None:
        self._refresh()
        self.extra_args_changed.emit()


def _quote(part: str) -> str:
    """Windows-friendly quoting：含空格的加双引号。"""
    if not part:
        return '""'
    if any(c in part for c in (" ", "\t")):
        return f'"{part}"'
    return part
