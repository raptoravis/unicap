"""LaunchDashboard —— launch tab 顶部仪表盘。

显示元素（G-005）：
  · 大色块状态条（IDLE / SURVEYING / CAPTURING / 未连接）—— 从
    <game_dir>/fc_state.txt 1Hz 读
  · session 路径 link（点击 explorer 打开）
  · frame count（数 frames_dir 下 *BackBuffer*.bmp）
  · elapsed timer
  · capture-duration 进度条（按 --capture-duration 参数）
  · watchdog 触发计数（log_tailer 喂）
  · attack heartbeat 灯（橙色脉冲 / recovery 时常亮橙）
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QProgressBar, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from unicap_gui.shared.log_tailer import LogTailer
from unicap_gui.shared.paths import auto_play_log

# ── 状态色映射 ────────────────────────────────────────────────────────────────


_STATE_COLORS = {
    "idle":       ("#9e9e9e", "IDLE"),         # 灰
    "surveying":  ("#fb8c00", "SURVEYING"),    # 橙
    "capturing":  ("#2e7d32", "CAPTURING"),    # 绿
    "unknown":    ("#616161", "未连接"),       # 深灰
}


class _LED(QLabel):
    """3-state 心跳灯：off=暗灰 / pulse=渐变绿 / hot=橙。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setFixedSize(14, 14)
        self._set_color("#444")
        self._fade_timer: QTimer | None = None

    def _set_color(self, color: str) -> None:
        self.setStyleSheet(
            f"background: {color}; border-radius: 7px; border: 1px solid #222;"
        )

    def pulse(self, color: str = "#4caf50", decay_ms: int = 600) -> None:
        self._set_color(color)
        if self._fade_timer is None:
            self._fade_timer = QTimer(self)
            self._fade_timer.setSingleShot(True)
            self._fade_timer.timeout.connect(lambda: self._set_color("#444"))
        self._fade_timer.start(decay_ms)

    def set_steady(self, color: str) -> None:
        if self._fade_timer is not None:
            self._fade_timer.stop()
        self._set_color(color)


# ── Dashboard ─────────────────────────────────────────────────────────────────


class LaunchDashboard(QWidget):
    """仪表盘 widget。LaunchTab 通过 setters 喂动态数据。"""

    # 用户点 session 路径 link → 打开 explorer
    open_session_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._game_dir: Path | None = None
        self._session_dir: Path | None = None
        self._capture_duration_s: float = 60.0
        self._capture_start_mono: float | None = None

        # 状态条
        self._state_label = QLabel("未连接")
        font = QFont()
        font.setPointSize(18)
        font.setBold(True)
        self._state_label.setFont(font)
        self._state_label.setAlignment(Qt.AlignCenter)
        self._state_label.setMinimumHeight(48)
        self._set_state_color("unknown")

        # session info row
        self._session_link = QLabel("session: —")
        self._session_link.setOpenExternalLinks(False)
        self._session_link.linkActivated.connect(self._on_session_clicked)
        self._frame_count_label = QLabel("frames: 0")
        self._elapsed_label = QLabel("elapsed: 0s")
        self._duration_bar = QProgressBar()
        self._duration_bar.setRange(0, 100)
        self._duration_bar.setMaximumWidth(220)
        self._duration_bar.setTextVisible(True)
        self._duration_bar.setFormat("%v / %m s")

        # counters row
        self._watchdog_label = QLabel("WATCHDOG: 0")
        self._attack_led = _LED()

        # 顶层 layout
        layout = QGridLayout(self)
        layout.setContentsMargins(8, 8, 8, 4)
        layout.setHorizontalSpacing(12)
        layout.setVerticalSpacing(4)

        # row 0: 大状态条（跨整行）
        layout.addWidget(self._state_label, 0, 0, 1, 6)

        # row 1: session link + frame + elapsed + duration
        layout.addWidget(self._session_link, 1, 0, 1, 2)
        layout.addWidget(self._frame_count_label, 1, 2)
        layout.addWidget(self._elapsed_label, 1, 3)
        layout.addWidget(self._duration_bar, 1, 4, 1, 2)

        # row 2: counters
        layout.addWidget(self._watchdog_label, 2, 0)
        ab_box = QHBoxLayout()
        ab_box.addWidget(QLabel("ATK:"))
        ab_box.addWidget(self._attack_led)
        ab_w = QWidget(); ab_w.setLayout(ab_box)
        layout.addWidget(ab_w, 2, 1)

        # 1Hz 主 timer：读 fc_state.txt + 数 frames + 算 elapsed
        self._tick = QTimer(self)
        self._tick.setInterval(1000)
        self._tick.timeout.connect(self._on_tick)

        # 0.5s log tailer（watchdog 触发计数 + attack 心跳灯 + recovery 状态）
        self._tailer = LogTailer(auto_play_log(), interval_ms=500, parent=self)
        self._tailer.watchdog_trigger.connect(self._on_watchdog_count)
        self._tailer.attack.connect(lambda: self._attack_led.pulse("#ef6c00"))
        self._tailer.recovery_active.connect(self._on_recovery_active)

        # 仪表盘文字：用 palette 文本色 + 加大字号，避免浅主题下浅灰看不清
        self.setStyleSheet("""
        QLabel { color: palette(text); font-size: 13px; }
        QLabel a { color: palette(link); }
        QProgressBar { font-size: 12px; min-height: 18px; }
        QFrame#dash_frame { background: palette(base); border: 1px solid palette(mid); }
        """)
        self.setMinimumHeight(120)

        # 关键标签加粗 + 略大，让 frames / elapsed / counters 一眼可读
        for lbl in (self._session_link, self._frame_count_label,
                    self._elapsed_label, self._watchdog_label):
            f = lbl.font()
            f.setPointSize(max(f.pointSize(), 10) + 1)
            f.setBold(True)
            lbl.setFont(f)

    # ── public：LaunchTab 连接进来的设置 ──────────────────────────────────

    def attach_to_launch(self, game_dir: Path | None, capture_duration_s: float) -> None:
        """子进程启动后由 LaunchTab 调一次。"""
        self._game_dir = game_dir
        self._capture_duration_s = max(capture_duration_s, 0.0)
        self._capture_start_mono = None  # 仅在进入 capturing 状态时才开始计时
        self._reset_counters()
        self._tailer.reset()
        self._tailer.start()
        self._tick.start()

    def detach(self) -> None:
        """子进程退出时调。"""
        self._tick.stop()
        self._tailer.stop()
        self._set_state_color("unknown")
        self._state_label.setText("未连接")
        self._attack_led.set_steady("#444")

    def set_session_dir(self, session_dir: str) -> None:
        """SubprocessRunner.session_changed 接进来。`[CAPTURE] 开始采集 → <dir>`
        是真正的 capture 起点，所以这里启动 capture-duration 计时。"""
        self._session_dir = Path(session_dir)
        self._capture_start_mono = time.monotonic()
        # 显示成可点击 link（Qt 富文本）
        self._session_link.setText(
            f"session: <a href='open'>{self._session_dir.name}</a>"
        )

    # ── internal slots ────────────────────────────────────────────────────

    def _on_tick(self) -> None:
        # state from fc_state.txt
        if self._game_dir:
            try:
                txt = (self._game_dir / "fc_state.txt").read_text(
                    encoding="utf-8", errors="replace").strip()
            except OSError:
                txt = "unknown"
        else:
            txt = "unknown"
        self._set_state_color(txt)

        # frame count
        n = 0
        if self._session_dir:
            frames_dir = self._session_dir / "frames"
            try:
                n = sum(1 for _ in frames_dir.glob("*BackBuffer*.bmp"))
            except OSError:
                pass
        self._frame_count_label.setText(f"frames: {n}")

        # elapsed + progress bar —— 仅在进入 capturing（即 set_session_dir 后）才走
        if self._capture_start_mono is not None and txt == "capturing":
            elapsed = time.monotonic() - self._capture_start_mono
            self._elapsed_label.setText(
                f"elapsed: {timedelta(seconds=int(elapsed))}"
            )
            if self._capture_duration_s > 0:
                pct = min(int(elapsed), int(self._capture_duration_s))
                self._duration_bar.setRange(0, int(self._capture_duration_s))
                self._duration_bar.setValue(pct)
            else:
                # 不限时：进度条变 indeterminate
                self._duration_bar.setRange(0, 0)
        else:
            # idle / surveying：清零进度条 + elapsed 显示 "—"
            self._elapsed_label.setText("elapsed: —")
            self._duration_bar.setRange(0, int(self._capture_duration_s)
                                        if self._capture_duration_s > 0 else 100)
            self._duration_bar.setValue(0)

    def _set_state_color(self, state: str) -> None:
        color, label = _STATE_COLORS.get(state, _STATE_COLORS["unknown"])
        self._state_label.setText(label)
        self._state_label.setStyleSheet(
            f"background: {color}; color: white; border-radius: 6px; padding: 6px;"
        )

    def _on_watchdog_count(self, n: int) -> None:
        self._watchdog_label.setText(f"WATCHDOG: {n}")
        # 红色脉冲 1s 后回灰
        self._watchdog_label.setStyleSheet("color: #ef5350; font-weight: bold;")
        QTimer.singleShot(1000, lambda: self._watchdog_label.setStyleSheet(""))

    def _on_recovery_active(self, active: bool) -> None:
        if active:
            self._attack_led.set_steady("#ef6c00")  # 橙：recovery 中
        # active=False 时不主动 reset attack_led —— 让它自然恢复（pulse fade）

    def _on_session_clicked(self, _href: str) -> None:
        if self._session_dir is None:
            return
        path = str(self._session_dir)
        try:
            if sys.platform == "win32":
                os.startfile(path)
            else:
                subprocess.Popen(["xdg-open", path])
        except OSError:
            self.open_session_requested.emit(path)  # 让 caller 兜底

    def _reset_counters(self) -> None:
        self._watchdog_label.setText("WATCHDOG: 0")
        self._frame_count_label.setText("frames: 0")
        self._duration_bar.setValue(0)
