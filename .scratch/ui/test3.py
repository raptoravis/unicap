import os, sys
os.environ["QT_QPA_PLATFORM"] = "offscreen"
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
print("sys.path[0]:", sys.path[0])
from PySide6.QtWidgets import QApplication
from unicap_gui.shared.process import SubprocessRunner
print("imports OK")
app = QApplication([])
runner = SubprocessRunner()
print("runner created")
runner.start("--version", [])
print("start called, pid=", runner.pid())
import time
time.sleep(2)
print("done")
