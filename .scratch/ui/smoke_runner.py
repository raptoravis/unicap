"""Smoke test: SubprocessRunner against main.py --version."""

import os
import sys

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

# Add repo root to sys.path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from unicap_gui.shared.process import SubprocessRunner

app = QApplication([])
runner = SubprocessRunner()
lines: list[str] = []
runner.line_received.connect(lambda s: lines.append(s))


def on_stopped(rc: int) -> None:
    print("STOPPED rc=%d" % rc, flush=True)
    QTimer.singleShot(200, app.quit)


runner.stopped.connect(on_stopped)
runner.error.connect(lambda m: print("ERROR:", m))
runner.started.connect(lambda c: print("STARTED:", c))


# subcommand="--version" 让 argparse special-handle 立即退出
runner.start("--version", [])

QTimer.singleShot(10000, app.quit)
app.exec()

print("=== lines (%d) ===" % len(lines))
for L in lines:
    print(repr(L))
