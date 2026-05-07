import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
print("env set")
from PySide6.QtWidgets import QApplication
print("import done")
app = QApplication([])
print("QApp created")
