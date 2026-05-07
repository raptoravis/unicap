"""SubprocessRunner —— 启动 / 监控 / 优雅停止 main.py 子进程。

不使用 QProcess（Windows kill = TerminateProcess，忽略 main.py finally
块清理 sidecar / Vulkan 注册表）。改用 subprocess.Popen 配合：

  · CREATE_NEW_PROCESS_GROUP    —— 让我们能发 CTRL_BREAK_EVENT
  · CTRL_BREAK_EVENT            —— Python 把它转成 KeyboardInterrupt
  · taskkill /T /F /PID         —— 5s 兜底（连游戏子进程一起带走）

stdout 在 worker QThread 里 readline，每行 emit Qt signal 到 GUI 线程。
"""

from __future__ import annotations

import logging
import re
import signal
import subprocess
import sys
import time
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from unicap_gui.shared.paths import cli_argv_prefix, repo_root

log = logging.getLogger("unicap_gui.process")

# Windows 专用 flag。Linux/macOS 没这个常量但我们整体不支持。
CREATE_NEW_PROCESS_GROUP = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)

# `[CAPTURE] 开始采集 ... → <session_dir>` —— main.py:728/731
_RE_SESSION = re.compile(r"\[CAPTURE\].*?→\s*(.+)$")


class _StdoutReader(QObject):
    """在 worker thread 里 readline，逐行 emit。结束时 emit finished。"""

    line = Signal(str)
    finished = Signal(int)  # exit code

    def __init__(self, proc: subprocess.Popen[str]) -> None:
        super().__init__()
        self._proc = proc

    def run(self) -> None:
        try:
            assert self._proc.stdout is not None
            for raw in self._proc.stdout:
                # raw 已是 str（text=True），保留尾部换行供 GUI 直接 append
                self.line.emit(raw.rstrip("\r\n"))
        except Exception as e:  # noqa: BLE001
            self.line.emit(f"[unicap-gui] stdout reader 异常：{e}")
        finally:
            rc = self._proc.wait()
            self.finished.emit(rc)


class SubprocessRunner(QObject):
    """单实例子进程管理器。launch / video / pack tab 各拥有一个。"""

    line_received = Signal(str)            # 每行 stdout
    started = Signal(list)                 # 实际 cmdline
    stopped = Signal(int)                  # exit code
    session_changed = Signal(str)          # 解析 `[CAPTURE] ... → <dir>` 后 emit
    error = Signal(str)                    # 异常文本

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._proc: subprocess.Popen[str] | None = None
        self._reader: _StdoutReader | None = None
        self._thread: QThread | None = None

    # ── 状态查询 ──────────────────────────────────────────────────────────

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def pid(self) -> int | None:
        return self._proc.pid if self._proc else None

    # ── 启动 ──────────────────────────────────────────────────────────────

    def start(self, subcommand: str, argv_tail: list[str]) -> None:
        """argv_tail 是 `--game-path X --auto-play ...` 这部分；不含 python/main.py/subcommand。"""
        if self.is_running():
            self.error.emit("子进程已在运行，先 Stop 再 Start。")
            return

        # frozen: [unicap.exe, subcommand, ...]；dev: [python, -X utf8, -u, main.py, subcommand, ...]
        cmd: list[str] = [*cli_argv_prefix(), subcommand, *argv_tail]

        # 兜底环境变量：老 Python / 第三方库即便忽略 -X utf8 也按 PYTHONIOENCODING
        import os
        env = {**os.environ, "PYTHONIOENCODING": "utf-8"}

        try:
            self._proc = subprocess.Popen(
                cmd,
                cwd=str(repo_root()),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,   # 合流：所有输出走一个 pipe
                bufsize=1,                  # 行缓冲（text mode 必需 1）
                text=True,
                encoding="utf-8",
                errors="replace",           # 中文路径 / 非法 utf-8 不崩
                env=env,
                creationflags=CREATE_NEW_PROCESS_GROUP,
            )
        except FileNotFoundError as e:
            self.error.emit(f"找不到可执行文件：{e}")
            return
        except OSError as e:
            self.error.emit(f"启动失败：{e}")
            return

        log.info("spawn pid=%d cmd=%r", self._proc.pid, cmd)
        self.started.emit(cmd)

        # stdout reader 跑在 QThread
        self._thread = QThread()
        self._thread.setObjectName(f"unicap-stdout-{subcommand}")
        self._reader = _StdoutReader(self._proc)
        self._reader.moveToThread(self._thread)
        self._thread.started.connect(self._reader.run)
        self._reader.line.connect(self._on_line)
        self._reader.finished.connect(self._on_finished)
        self._reader.finished.connect(self._thread.quit)
        # reader / thread 都用 deleteLater 让 Qt event loop 在 thread 真退出后清；
        # 不在 Python 端把 ref 提前置 None（提前置 None 会让 PyObject 在 thread
        # 还跑着时被 sip GC，触发 "QThread: Destroyed while thread is still running"）
        self._reader.finished.connect(self._reader.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.start()

    # ── 优雅停止 ──────────────────────────────────────────────────────────

    def stop(self, timeout_s: float = 5.0) -> None:
        """先发 CTRL_BREAK，等 5s 不退则 taskkill /T /F。"""
        if not self.is_running():
            return
        assert self._proc is not None

        pid = self._proc.pid
        log.info("stop: send CTRL_BREAK_EVENT to pid=%d", pid)

        # signal.CTRL_BREAK_EVENT 仅 Windows 有；Python 把它递给整个 process group
        if sys.platform == "win32":
            try:
                self._proc.send_signal(signal.CTRL_BREAK_EVENT)
            except (OSError, ValueError) as e:
                log.warning("CTRL_BREAK 发送失败：%s（落到 taskkill）", e)
        else:
            self._proc.terminate()

        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                log.info("stop: 子进程优雅退出 rc=%d", self._proc.returncode)
                return
            time.sleep(0.1)

        # 5s 兜底：taskkill /F（**无 /T**）只杀 main.py 主进程；游戏子进程留着跑。
        # 这样匹配 main.py 的 `Ctrl+C 退出 main.py（不会关闭游戏）` 约定，避免：
        # · Windows 11 Game Bar 检测到游戏异常退出后弹 ms-gamingoverlay 对话框
        # · 游戏未保存进度被强 kill
        # 用户想关游戏自己 alt+F4 即可。
        log.warning("stop: 5s 内未优雅退出，taskkill /F /PID %d（不带 /T，不杀游戏）", pid)
        self._taskkill_main_only(pid)

    @staticmethod
    def _taskkill_main_only(pid: int) -> None:
        if sys.platform != "win32":
            return
        try:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                check=False,
                capture_output=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                timeout=10,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            log.error("taskkill 失败：%s", e)

    # ── 内部 slot ─────────────────────────────────────────────────────────

    def _on_line(self, text: str) -> None:
        self.line_received.emit(text)
        m = _RE_SESSION.search(text)
        if m:
            self.session_changed.emit(m.group(1).strip())

    def _on_finished(self, rc: int) -> None:
        log.info("subprocess finished rc=%d", rc)
        self._proc = None
        # _reader / _thread 不在这清 Python ref —— 它们 schedule 了 deleteLater，
        # 由 Qt main event loop 在 thread 真正退出后销毁底层 C++ 对象。
        # 下一次 start() 会用新 QThread() 覆盖旧 ref，旧 wrapper 那时已 safe。
        self.stopped.emit(rc)
