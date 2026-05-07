"""SessionTree —— video / pack tab 的 session 树状管理。

数据源：用户先选 game-dir（dataset-root 下的某个游戏目录），扫描其 `<ts>/`
子目录，每行展示三列状态图标：

    frames ✓ / ✗     video.mp4 ✓ / ✗     dataset.h5 ✓ / ✗

复选框多选 → 选中的 session 名汇总成"逗号分隔" 让 caller 拼成 video/pack 命令的
"target sessions"（如果 main.py 当前不支持过滤，把它当 UX 提示用 + 默认全跑）。

5c MVP：纯展示 + 选择，不改 main.py。caller 用法：
  · 用户改了 --game-dir → tree.set_game_dir() 触发扫描
  · 用户勾选某些 session → tree.selected_session_names() 拿列表
  · 三个快捷按钮：全选 / 反选 / 仅缺失
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QHeaderView, QPushButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget,
)


_HEADERS = ["session", "frames", "video.mp4", "dataset.h5"]
_FRAMES_COL = 1
_VIDEO_COL = 2
_DSET_COL = 3


def _icon(ok: bool) -> str:
    return "✓" if ok else "✗"


class SessionTree(QWidget):
    """game-dir 下所有 session 的状态树。"""

    selection_changed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_dir: Path | None = None

        self._tree = QTreeWidget(self)
        self._tree.setColumnCount(len(_HEADERS))
        self._tree.setHeaderLabels(_HEADERS)
        self._tree.setRootIsDecorated(False)
        self._tree.setAlternatingRowColors(True)
        self._tree.itemChanged.connect(self._on_item_changed)
        header = self._tree.header()
        header.setSectionResizeMode(0, QHeaderView.Stretch)
        for c in range(1, len(_HEADERS)):
            header.setSectionResizeMode(c, QHeaderView.ResizeToContents)

        # 快捷按钮
        btn_all = QPushButton("全选")
        btn_all.clicked.connect(self._select_all)
        btn_none = QPushButton("反选")
        btn_none.clicked.connect(self._invert)
        btn_missing = QPushButton("仅缺失")
        btn_missing.setToolTip("只选 video.mp4 或 dataset.h5 缺失的 session（与 CLI 跳过逻辑一致）")
        btn_missing.clicked.connect(self._select_missing)
        btn_refresh = QPushButton("⟳ 刷新")
        btn_refresh.clicked.connect(self.rescan)

        bar = QHBoxLayout()
        bar.addWidget(btn_all)
        bar.addWidget(btn_none)
        bar.addWidget(btn_missing)
        bar.addStretch(1)
        bar.addWidget(btn_refresh)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(bar)
        layout.addWidget(self._tree, stretch=1)

    # ── 公开 ─────────────────────────────────────────────────────────────

    def set_game_dir(self, path: str) -> None:
        if not path:
            self._game_dir = None
            self._tree.clear()
            return
        p = Path(path)
        if p == self._game_dir:
            return
        self._game_dir = p
        self.rescan()

    def rescan(self) -> None:
        self._tree.clear()
        if self._game_dir is None or not self._game_dir.exists():
            self._tree.addTopLevelItem(QTreeWidgetItem(["(game-dir 未选 / 不存在)"]))
            return

        sessions = sorted([d for d in self._game_dir.iterdir()
                           if d.is_dir() and d.name != "survey"])
        if not sessions:
            self._tree.addTopLevelItem(QTreeWidgetItem(["(无 session)"]))
            return

        self._tree.blockSignals(True)
        for s in sessions:
            frames_ok = (s / "frames").exists()
            video_ok = (s / "video.mp4").exists() or (s / "video_ui.mp4").exists()
            dset_ok = (s / "dataset.h5").exists()

            it = QTreeWidgetItem([s.name, _icon(frames_ok), _icon(video_ok), _icon(dset_ok)])
            it.setFlags(it.flags() | Qt.ItemIsUserCheckable)
            # 默认勾选缺失产物的 session（与 CLI"已存在跳过"行为一致）
            it.setCheckState(0, Qt.Checked if not (video_ok and dset_ok) else Qt.Unchecked)

            # 状态色
            for col, ok in ((_FRAMES_COL, frames_ok), (_VIDEO_COL, video_ok), (_DSET_COL, dset_ok)):
                it.setForeground(col, _make_color(ok))
            self._tree.addTopLevelItem(it)
        self._tree.blockSignals(False)
        self.selection_changed.emit()

    def selected_session_names(self) -> list[str]:
        out: list[str] = []
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            if it.checkState(0) == Qt.Checked:
                out.append(it.text(0))
        return out

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _select_all(self) -> None:
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            self._tree.topLevelItem(i).setCheckState(0, Qt.Checked)
        self._tree.blockSignals(False)
        self.selection_changed.emit()

    def _invert(self) -> None:
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            new = Qt.Unchecked if it.checkState(0) == Qt.Checked else Qt.Checked
            it.setCheckState(0, new)
        self._tree.blockSignals(False)
        self.selection_changed.emit()

    def _select_missing(self) -> None:
        self._tree.blockSignals(True)
        for i in range(self._tree.topLevelItemCount()):
            it = self._tree.topLevelItem(i)
            video_ok = it.text(_VIDEO_COL) == "✓"
            dset_ok = it.text(_DSET_COL) == "✓"
            it.setCheckState(0, Qt.Unchecked if (video_ok and dset_ok) else Qt.Checked)
        self._tree.blockSignals(False)
        self.selection_changed.emit()

    def _on_item_changed(self, _it: QTreeWidgetItem, _col: int) -> None:
        self.selection_changed.emit()


def _make_color(ok: bool):
    from PySide6.QtGui import QBrush, QColor
    return QBrush(QColor("#66bb6a" if ok else "#ef5350"))
