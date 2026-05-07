"""LogTailer —— 增量读 %TEMP%/unicap/auto_play.log，提取 dashboard 计数器。

`[WATCHDOG] static-frame 触发 # / [ATTACK-HB]` 走 logging 模块，
**只到文件**不到 stdout。Dashboard 想计数就只能 tail。

策略：QTimer 每 0.5s 触发：按文件名 reopen（不持 fd），seek 到上次 offset，
读到 EOF 提行；若文件大小变小（rotate）则 offset 回 0；文件不存在静默 retry。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator

from PySide6.QtCore import QObject, QTimer, Signal

log = logging.getLogger("unicap_gui.log_tailer")

_RE_WATCHDOG = re.compile(r"\[WATCHDOG\].*static-frame\s+触发\s+#(\d+)")
_RE_ATTACK_HB = re.compile(r"\[ATTACK-HB\]")
_RE_RECOVERY_BEGIN = re.compile(r"\[WATCHDOG\].*static-frame\s+触发\s+#\d+.*注入\s+recovery")
_RE_RECOVERY_END = re.compile(r"\[AUTO-PLAY\]")  # 任意 driver tick 行 → recovery 结束


class LogTailer(QObject):
    """文件 tail —— 暴露 signal 给 dashboard。"""

    watchdog_trigger = Signal(int)      # 累计 watchdog static-frame 触发数
    attack = Signal()                   # 每次 [ATTACK-HB] 一次
    recovery_active = Signal(bool)      # True=进入 recovery；False=退出

    def __init__(self, log_path: Path, interval_ms: int = 500,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = log_path
        self._offset = 0
        self._inode_size: int = 0
        self._in_recovery = False

        self._timer = QTimer(self)
        self._timer.setInterval(interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self) -> None:
        # 首次启动 seek 到当前 EOF，避免把历史日志全 replay 一遍
        try:
            self._offset = self._path.stat().st_size
            self._inode_size = self._offset
        except OSError:
            self._offset = 0
        self._timer.start()

    def stop(self) -> None:
        self._timer.stop()

    def reset(self) -> None:
        """新 launch session 时调一下，把计数清零的责任留给 dashboard 自己。"""
        # 只是把 offset 设到当前 EOF，避免读到上一次 launch 的尾部日志
        try:
            self._offset = self._path.stat().st_size
            self._inode_size = self._offset
        except OSError:
            self._offset = 0

    # ── 内部 ──────────────────────────────────────────────────────────────

    def _tick(self) -> None:
        try:
            size = self._path.stat().st_size
        except OSError:
            return  # 文件还没建 / rotate 中：下次再试

        if size < self._inode_size:
            # 文件被 rotate / truncate，从头开始读
            self._offset = 0
        self._inode_size = size

        if size <= self._offset:
            return  # 没新内容

        try:
            with self._path.open("r", encoding="utf-8", errors="replace") as f:
                f.seek(self._offset)
                for line in self._read_lines(f):
                    self._dispatch(line)
                self._offset = f.tell()
        except OSError as e:
            log.debug("log_tailer read failed: %s", e)

    @staticmethod
    def _read_lines(f) -> Iterator[str]:
        for line in f:
            yield line.rstrip("\n")

    def _dispatch(self, line: str) -> None:
        if m := _RE_WATCHDOG.search(line):
            self.watchdog_trigger.emit(int(m.group(1)))

        # recovery 状态机
        if _RE_RECOVERY_BEGIN.search(line):
            if not self._in_recovery:
                self._in_recovery = True
                self.recovery_active.emit(True)
        elif self._in_recovery and _RE_RECOVERY_END.search(line):
            self._in_recovery = False
            self.recovery_active.emit(False)

        if _RE_ATTACK_HB.search(line):
            self.attack.emit()
