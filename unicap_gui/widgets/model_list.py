"""ModelList — 简洁列出 models/<profile>/{model.onnx + metrics.json} 的小部件。

读 metrics.json 显示 macro_kb_f1 / mouse_dir_top1 / kl_action_dist —— 让用户
肉眼判断该模型当前训练质量。无 metrics.json 时显示 "(metrics 缺)"。
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import Qt, QFileSystemWatcher, QTimer, Signal
from PySide6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout, QWidget,
)


class ModelList(QWidget):
    """显示某 profile 下已训练的 model 目录（顶层 models/<profile>/）+ 子目录。

    点 "刷新" 重新扫盘；模型子目录的 metrics.json 摘要打到 item 文本里。
    """

    rescan_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._models_root: Path | None = None
        self._profile_name: str = ""

        # QFileSystemWatcher 触发频繁（重命名 = 多次 dirChanged）→ 用 QTimer
        # 折叠 200ms 内的连续事件成单次 rescan，避免每次写文件都重读 metrics.json。
        self._watcher = QFileSystemWatcher(self)
        self._watcher.directoryChanged.connect(self._schedule_rescan)
        self._rescan_timer = QTimer(self)
        self._rescan_timer.setSingleShot(True)
        self._rescan_timer.setInterval(200)
        self._rescan_timer.timeout.connect(self.rescan)

        self._title = QLabel("已训练模型")
        self._title.setStyleSheet("font-weight: bold; font-size: 13px;")
        self._refresh_btn = QPushButton("刷新")
        self._refresh_btn.setMaximumWidth(80)
        self._refresh_btn.clicked.connect(self._on_refresh)

        head = QHBoxLayout()
        head.setContentsMargins(0, 0, 0, 0)
        head.addWidget(self._title)
        head.addStretch(1)
        head.addWidget(self._refresh_btn)

        self._list = QListWidget(self)
        self._list.setMaximumHeight(110)
        self._list.setStyleSheet(
            "QListWidget { font-family: Consolas, 'Courier New', monospace; "
            "font-size: 12px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self._list)

    def set_models_root(self, root: Path | None, profile: str) -> None:
        self._models_root = root
        self._profile_name = profile or ""
        self._title.setText(f"已训练模型 (profile={self._profile_name or '?'})")
        self._update_watch_paths()
        self.rescan()

    def _update_watch_paths(self) -> None:
        """Track models_root + models_root/<profile> + each model run subdir.
        QFileSystemWatcher needs explicit paths — it does NOT recurse."""
        # 清空旧监听
        existing = self._watcher.directories()
        if existing:
            self._watcher.removePaths(existing)

        if not self._models_root:
            return
        new_paths: list[str] = []
        if self._models_root.is_dir():
            new_paths.append(str(self._models_root))
            if self._profile_name:
                prof_dir = self._models_root / self._profile_name
                if prof_dir.is_dir():
                    new_paths.append(str(prof_dir))
                    # 每个 run 子目录：metrics.json 写入触发 dirChanged，更新摘要
                    for child in prof_dir.iterdir():
                        if child.is_dir():
                            new_paths.append(str(child))
        if new_paths:
            self._watcher.addPaths(new_paths)

    def _schedule_rescan(self, _path: str) -> None:
        # debounced：folder 变化 → 200ms 后单次 rescan
        self._rescan_timer.start()

    def rescan(self) -> None:
        # New subdirs may have appeared since last set_models_root call —
        # re-register so the next train run is also tracked.
        self._update_watch_paths()
        self._list.clear()
        if not self._models_root or not self._profile_name:
            self._list.addItem("(profile 未选)")
            return
        prof_dir = self._models_root / self._profile_name
        if not prof_dir.is_dir():
            self._list.addItem(f"(目录不存在: {prof_dir})")
            return

        # Top-level + immediate subdir model.onnx — covers both `models/<prof>/`
        # and `models/<prof>/<run_ts>/` layouts.
        candidates: list[Path] = []
        if (prof_dir / "model.onnx").is_file():
            candidates.append(prof_dir)
        for child in sorted(prof_dir.iterdir(), reverse=True):
            if child.is_dir() and (child / "model.onnx").is_file():
                candidates.append(child)

        if not candidates:
            self._list.addItem(f"(无模型于 {prof_dir})")
            return

        for d in candidates:
            label = self._format_entry(d)
            item = QListWidgetItem(label)
            item.setToolTip(str(d.resolve()))
            self._list.addItem(item)

    def _format_entry(self, d: Path) -> str:
        rel = d.name if d.parent.name == self._profile_name else d.name
        size_mb = (d / "model.onnx").stat().st_size / 1024 / 1024
        metrics_path = d / "metrics.json"
        if metrics_path.is_file():
            try:
                m = json.loads(metrics_path.read_text(encoding="utf-8"))
                f1 = m.get("macro_kb_f1", 0.0)
                dir_acc = m.get("mouse_dir_top1", 0.0)
                kl = m.get("kl_action_dist", 0.0)
                summary = f"f1={f1:.2f} mouse={dir_acc:.2f} kl={kl:.2f}"
            except (OSError, json.JSONDecodeError):
                summary = "(metrics 解析失败)"
        else:
            summary = "(metrics 缺)"
        return f"{rel}/  {size_mb:5.1f}MB  {summary}"

    def _on_refresh(self) -> None:
        self.rescan_requested.emit()
        self.rescan()
