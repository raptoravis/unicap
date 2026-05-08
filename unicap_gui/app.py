"""MainWindow —— 三 tab 容器；负责 launch 与 video/pack 之间的 Start 锁定。"""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QMainWindow, QMessageBox, QTabWidget, QWidget

from unicap_gui.shared import settings as gui_settings
from unicap_gui.tabs.launch_tab import LaunchTab
from unicap_gui.tabs.video_tab import VideoTab
from unicap_gui.tabs.pack_tab import PackTab
from unicap_gui.tabs.train_tab import TrainBCTab


class MainWindow(QMainWindow):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("unicap GUI")

        self._tabs = QTabWidget(self)
        self._tabs.setTabPosition(QTabWidget.North)
        self._tabs.setMovable(False)
        self._tabs.setStyleSheet(
            "QTabBar::tab {"
            " min-width: 140px; min-height: 36px;"
            " padding: 8px 20px;"
            " font-size: 16px; font-weight: 600;"
            "}"
            "QTabBar::tab:selected {"
            " background: palette(base);"
            " border-bottom: 3px solid palette(highlight);"
            "}"
        )

        self._launch = LaunchTab(self)
        self._video = VideoTab(self)
        self._pack = PackTab(self)
        self._train = TrainBCTab(self)

        self._tabs.addTab(self._launch, "采集")
        self._tabs.addTab(self._video, "生成视频")
        self._tabs.addTab(self._pack, "打包")
        self._tabs.addTab(self._train, "训练")
        self.setCentralWidget(self._tabs)

        # G-011 + G-006c：双向 Start 互斥 —— launch / train 任一跑时，禁止启动
        # 另一方（避免 GPU/IO 抢占）。video / pack 也跟 launch 一起锁。
        self._launch.process_running_changed.connect(self._on_launch_running_changed)
        self._train.process_running_changed.connect(self._on_train_running_changed)

        self._restore_window_settings()

    # ── 锁定逻辑 ──────────────────────────────────────────────────────────

    def _on_launch_running_changed(self, running: bool) -> None:
        reason = "launch 正在跑，暂不可启动（避 GPU 抢占）" if running else ""
        self._video.set_start_enabled(not running, reason)
        self._pack.set_start_enabled(not running, reason)
        self._train.set_start_enabled(not running, reason)

    def _on_train_running_changed(self, running: bool) -> None:
        reason = "train-bc 正在跑，暂不可启动（避 GPU 显存抢占）" if running else ""
        self._launch.set_start_enabled(not running, reason)
        # video / pack 不吃 GPU，与 train 并行无显存冲突 — 不锁。

    # ── 持久化 ────────────────────────────────────────────────────────────

    def _restore_window_settings(self) -> None:
        size = gui_settings.load("window/size", None)
        if isinstance(size, QSize) and size.isValid():
            self.resize(size)
        else:
            self.resize(1100, 800)

        self._tabs.setCurrentIndex(0)

    def _save_window_settings(self) -> None:
        gui_settings.save("window/size", self.size())

    # ── 关闭 ──────────────────────────────────────────────────────────────

    def closeEvent(self, event) -> None:
        # 任意 tab 子进程跑着 —— 弹模态确认（避免孤儿子进程）
        running_tabs = [t for t in (self._launch, self._video, self._pack, self._train)
                        if t.is_running()]
        if running_tabs:
            names = ", ".join(t.schema().name for t in running_tabs)
            ret = QMessageBox.question(
                self, "确认退出",
                f"以下子进程仍在运行：{names}\n\n"
                "关 GUI 会发 CTRL_BREAK 让 main.py 优雅退出；游戏进程不动（与 Ctrl+C 退 main.py 行为一致）。继续？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if ret != QMessageBox.Yes:
                event.ignore()
                return
            for t in running_tabs:
                t.runner().stop(timeout_s=5.0)

        self._save_window_settings()
        super().closeEvent(event)
