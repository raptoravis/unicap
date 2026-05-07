"""AutoPlayPanel —— launch tab 表单上方的 auto-play profile 选择面板。

只剩一个职责：让用户从 `profiles/*.yaml` 列表里直接选 profile（避免手填 typo），
选中后通过 `profile_selected` signal 把名字写回 FlagForm 的 `--profile` 行。

VLM / hybrid driver 已废弃，原 .env 显示 / 改 .env / 重读 .env 三个增强一并删除。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QGroupBox, QHBoxLayout, QLabel, QListWidget, QPushButton,
    QVBoxLayout, QWidget,
)

from unicap_gui.shared.paths import profiles_dir


class AutoPlayPanel(QGroupBox):
    """profile 下拉 + 刷新按钮。"""

    # 用户从下拉选了 profile —— LaunchTab 把它写回 FlagForm 的 --profile
    profile_selected = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Auto-Play 辅助（点击折叠 / 展开）", parent)
        # checkable=True 让 QGroupBox 显示折叠 checkbox；缺省展开（checked=True）
        self.setCheckable(True)
        self.setChecked(True)
        self.toggled.connect(self._on_toggle)

        # profile 下拉（QListWidget + 单选）
        self._profile_list = QListWidget()
        self._profile_list.setMaximumHeight(80)
        self._profile_list.itemSelectionChanged.connect(self._on_profile_selected)

        btn_refresh = QPushButton("⟳ 刷新")
        btn_refresh.setMaximumWidth(80)
        btn_refresh.clicked.connect(self.reload_profiles)

        profile_head = QHBoxLayout()
        profile_head.addWidget(QLabel("profiles/*.yaml"))
        profile_head.addStretch(1)
        profile_head.addWidget(btn_refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 14, 8, 8)
        layout.setSpacing(6)
        layout.addLayout(profile_head)
        layout.addWidget(self._profile_list)

        self.reload_profiles()

    # ── 公开 ─────────────────────────────────────────────────────────────

    def reload_profiles(self) -> None:
        self._profile_list.clear()
        try:
            names = sorted(p.stem for p in profiles_dir().glob("*.yaml"))
        except OSError:
            names = []
        if not names:
            self._profile_list.addItem("(无 profile —— 创建 profiles/<name>.yaml)")
            self._profile_list.setEnabled(False)
            return
        self._profile_list.setEnabled(True)
        for n in names:
            self._profile_list.addItem(n)

    def selected_profile(self) -> str | None:
        items = self._profile_list.selectedItems()
        return items[0].text() if items and self._profile_list.isEnabled() else None

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _on_toggle(self, checked: bool) -> None:
        """折叠 / 展开：递归 show/hide 所有非 self 直系 child widget。"""
        for child in self.children():
            if isinstance(child, QWidget) and child is not self:
                child.setVisible(checked)
        if checked:
            self.setMaximumHeight(16777215)
        else:
            self.setMaximumHeight(self.fontMetrics().height() + 24)

    def _on_profile_selected(self) -> None:
        name = self.selected_profile()
        if name:
            self.profile_selected.emit(name)
