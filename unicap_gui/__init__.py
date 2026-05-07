"""unicap_gui — PySide6 控制台，包装 main.py 的 launch / video / pack 子命令。

UI 不修改 main.py 任何一行；通过 subprocess 调用 + 文件 polling 实现状态可见性。
入口：`uv run python -m unicap_gui` 或 `unicap-gui` console-script。
"""

__version__ = "0.1.0"
