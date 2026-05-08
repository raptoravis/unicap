"""Entry point for `python -m unicap_gui` / `unicap-gui` console-script."""

from __future__ import annotations

import sys


def _hide_console_if_frozen() -> None:
    """Nuitka multidist 打包时 unicap.exe 与 unicap-gui.exe 字节相同，都是
    Console subsystem 二进制 —— 双击 unicap-gui.exe 会先弹出黑色 console，
    然后 GUI 窗口才出来。

    解决：frozen 模式下，先 FreeConsole + ShowWindow(SW_HIDE)。CLI 路径
    （unicap.exe）不会走到这里，console 仍然正常显示。

    Dev 模式（python -m unicap_gui）跳过 —— 否则会把用户跑命令的终端关掉。
    """
    from unicap_gui.shared.paths import is_frozen
    if not is_frozen():
        return
    if sys.platform != "win32":
        return
    try:
        import ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            # SW_HIDE = 0；先隐藏窗口（无视觉残留），再 FreeConsole 释放句柄
            user32.ShowWindow(hwnd, 0)
            kernel32.FreeConsole()
    except (OSError, AttributeError):
        # FreeConsole 失败不致命：用户能看到 console 仍能用 GUI。
        pass


def main() -> int:
    _hide_console_if_frozen()

    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        sys.stderr.write(
            "[unicap-gui] 缺少 PySide6 依赖。请安装：\n"
            "    uv sync --extra gui\n"
            "或 pip install \"unicap[gui]\"\n"
        )
        return 1

    from unicap_gui.app import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("unicap-gui")
    app.setOrganizationName("unicap")
    app.setOrganizationDomain("unicap.local")

    win = MainWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
