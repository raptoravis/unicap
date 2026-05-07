"""BaseTab —— launch / video / pack 三个 tab 的公共骨架。

布局：
    [可选 顶部插槽 — dashboard / 状态条]
    [FlagForm scroll 区]
    [CLIPreview]
    [Start / Stop 按钮 + status label]
    [LogPane]

子类加 dashboard / session_tree 时通过 add_top_widget() 插。
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt

from unicap_gui.shared import settings as gui_settings
from unicap_gui.shared.cli_schema import SubcommandSchema, values_to_argv
from unicap_gui.shared.process import SubprocessRunner
from unicap_gui.widgets.cli_preview import CLIPreview
from unicap_gui.widgets.flag_form import FlagForm
from unicap_gui.widgets.log_pane import LogPane


class BaseTab(QWidget):
    """通用 subcommand tab。launch tab 重写 _wire_extra() 加 dashboard 等。"""

    # broadcast：本 tab 子进程跑起来 / 退出 → MainWindow 用来锁/解锁 launch 关联
    process_running_changed = Signal(bool)

    def __init__(self, schema: SubcommandSchema,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._schema = schema
        self._runner = SubprocessRunner(self)

        # 表单
        self._form = FlagForm(schema, self)

        # CLI preview
        self._preview = CLIPreview(schema.name, self)

        # 控制按钮（放大 + 着色，便于一眼看到）
        self._btn_start = QPushButton("▶ Start")
        self._btn_stop = QPushButton("■ Stop")
        self._btn_stop.setEnabled(False)
        self._btn_start.clicked.connect(self._on_start_clicked)
        self._btn_stop.clicked.connect(self._on_stop_clicked)

        for btn in (self._btn_start, self._btn_stop):
            btn.setMinimumHeight(44)
            btn.setMinimumWidth(140)
        self._btn_start.setStyleSheet(
            "QPushButton {"
            " font-size: 16px; font-weight: 700;"
            " background: #2e7d32; color: white;"
            " border: 1px solid #1b5e20; border-radius: 6px;"
            " padding: 6px 18px;"
            "}"
            "QPushButton:hover { background: #388e3c; }"
            "QPushButton:disabled { background: #555; color: #bbb; border-color: #444; }"
        )
        self._btn_stop.setStyleSheet(
            "QPushButton {"
            " font-size: 16px; font-weight: 700;"
            " background: #c62828; color: white;"
            " border: 1px solid #8e0000; border-radius: 6px;"
            " padding: 6px 18px;"
            "}"
            "QPushButton:hover { background: #d32f2f; }"
            "QPushButton:disabled { background: #555; color: #bbb; border-color: #444; }"
        )

        self._status = QLabel("未运行")
        self._status.setStyleSheet("color: #888; font-size: 14px;")

        ctrl = QHBoxLayout()
        ctrl.setSpacing(10)
        ctrl.addWidget(self._btn_start)
        ctrl.addWidget(self._btn_stop)
        ctrl.addStretch(1)
        ctrl.addWidget(self._status)

        # log pane
        self._log = LogPane(self)

        # 顶部 / 底部分割。子类可通过 self._top_box 插控件
        self._top_box = QVBoxLayout()
        self._top_box.setContentsMargins(0, 0, 0, 0)
        top = QWidget()
        top.setLayout(self._top_box)

        # 表单 + preview + ctrl 合在 form_box
        form_box = QWidget()
        self._form_layout = QVBoxLayout(form_box)
        self._form_layout.setContentsMargins(0, 0, 0, 0)
        self._form_layout.setSpacing(6)
        self._form_layout.addWidget(self._form, stretch=1)
        self._form_layout.addWidget(self._preview)
        self._form_layout.addLayout(ctrl)

        # log 在右侧（splitter）
        splitter = QSplitter(Qt.Vertical)
        splitter.addWidget(form_box)
        splitter.addWidget(self._log)
        splitter.setSizes([500, 300])

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.addWidget(top)
        layout.addWidget(splitter, stretch=1)

        # signal wiring
        self._form.values_changed.connect(self._refresh_preview)
        self._preview.extra_args_changed.connect(lambda: None)  # _refresh 自更新
        self._runner.line_received.connect(self._log.append_line)
        self._runner.started.connect(self._on_subprocess_started)
        self._runner.stopped.connect(self._on_subprocess_stopped)
        self._runner.error.connect(self._on_subprocess_error)

        self._wire_extra()
        self._restore_settings()
        self._refresh_preview()

    # ── 子类 hook ────────────────────────────────────────────────────────

    def _wire_extra(self) -> None:
        """子类在这里加 dashboard / session_tree 等扩展。"""

    def _precheck_before_start(self) -> tuple[bool, str]:
        """子类返回 (ok, reason)；ok=False 时弹模态拦截。"""
        return True, ""

    # ── 公开属性 ──────────────────────────────────────────────────────────

    def schema(self) -> SubcommandSchema:
        return self._schema

    def runner(self) -> SubprocessRunner:
        return self._runner

    def is_running(self) -> bool:
        return self._runner.is_running()

    def set_start_enabled(self, enabled: bool, reason: str = "") -> None:
        """MainWindow 通过这个锁/解锁 video/pack 的 Start 按钮（C-LOCK / G-011）。"""
        self._btn_start.setEnabled(enabled and not self._runner.is_running())
        self._btn_start.setToolTip(reason if not enabled else "")

    # ── slot：start / stop ────────────────────────────────────────────────

    def _on_start_clicked(self) -> None:
        ok, reason = self._precheck_before_start()
        if not ok:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, "启动前预检失败", reason)
            return

        argv_tail = self._build_argv_tail() + self._preview.extra_args_argv()
        self._save_settings()
        self._log.append_separator(f"启动 {self._schema.name}")
        self._runner.start(self._schema.name, argv_tail)

    def _on_stop_clicked(self) -> None:
        self._log.append_line("[unicap-gui] 发送 CTRL_BREAK_EVENT…")
        self._runner.stop()

    def _on_subprocess_started(self, cmd: list[str]) -> None:
        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self._status.setText(f"运行中（pid={self._runner.pid()}）")
        self._status.setStyleSheet("color: #2e7d32; font-weight: bold;")
        self._log.append_line(f"[unicap-gui] cmd: {_format_cmd(cmd)}")
        self.process_running_changed.emit(True)

    def _on_subprocess_stopped(self, rc: int) -> None:
        self._btn_start.setEnabled(True)
        self._btn_stop.setEnabled(False)
        self._status.setText(f"已退出 rc={rc}")
        color = "#2e7d32" if rc == 0 else "#c62828"
        self._status.setStyleSheet(f"color: {color};")
        self._log.append_line(f"[unicap-gui] 子进程退出 rc={rc}")
        self.process_running_changed.emit(False)

    def _on_subprocess_error(self, msg: str) -> None:
        self._log.append_line(f"[unicap-gui] error: {msg}")

    # ── 辅助 ──────────────────────────────────────────────────────────────

    def _build_argv_tail(self) -> list[str]:
        return values_to_argv(self._schema, self._form.values())

    def _refresh_preview(self) -> None:
        self._preview.set_argv(self._build_argv_tail())

    def _save_settings(self) -> None:
        gui_settings.save_flag_values(self._schema.name, self._form.values())
        gui_settings.save(f"flags/{self._schema.name}/__extra_args__",
                          self._preview.extra_args_text())

    def _restore_settings(self) -> None:
        saved = gui_settings.load_flag_values(self._schema.name)
        if saved:
            self._form.set_values(saved)
        extra = gui_settings.load(f"flags/{self._schema.name}/__extra_args__", "")
        if extra:
            self._preview.set_extra_args(str(extra))


def _format_cmd(cmd: list[str]) -> str:
    parts = []
    for c in cmd:
        if " " in c or "\t" in c:
            parts.append(f'"{c}"')
        else:
            parts.append(c)
    return " ".join(parts)
