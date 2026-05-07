"""Entry point for `python -m unicap_gui` / `unicap-gui` console-script."""

from __future__ import annotations

import sys


def main() -> int:
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
