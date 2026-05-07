"""Headless test: import + create MainWindow + read tab labels + close."""

import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
print("path:", sys.path[0], flush=True)

from PySide6.QtWidgets import QApplication, QTabWidget
from unicap_gui.app import MainWindow
from unicap_gui.shared.cli_schema import LAUNCH, VIDEO, PACK, values_to_argv

app = QApplication([])
print("QApp OK", flush=True)

win = MainWindow()
print("Window created, size=%dx%d" % (win.width(), win.height()), flush=True)

tabs = win.findChild(QTabWidget)
print("tabs: %d - %s" % (tabs.count(),
                         [tabs.tabText(i) for i in range(tabs.count())]),
      flush=True)

# Verify schema flag counts vs requirement
print("LAUNCH flags=%d VIDEO=%d PACK=%d"
      % (len(LAUNCH.flags), len(VIDEO.flags), len(PACK.flags)),
      flush=True)

# Verify default values_to_argv produces empty (all defaults = no flag emitted)
launch_argv = values_to_argv(LAUNCH, {f.cli_key(): f.default for f in LAUNCH.flags})
print("default launch argv:", launch_argv, flush=True)

# Verify a modified set produces correct argv
mod = {f.cli_key(): f.default for f in LAUNCH.flags}
mod["auto_play"] = True
mod["driver"] = "hybrid"
mod["profile"] = "ff7r"
mod["force_borderless"] = False  # bool_optional → --no-force-borderless
mod["capture_duration"] = 90.0
launch_argv = values_to_argv(LAUNCH, mod)
print("modified launch argv:", launch_argv, flush=True)

print("DONE", flush=True)

# 必须显式销毁窗口避免 atexit 报 ResourceWarning
win.close()
del win
app.quit()
del app
