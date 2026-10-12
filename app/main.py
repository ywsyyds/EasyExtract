"""易解压 EasyExtract — 应用模块。"""
from __future__ import annotations

import sys
import traceback
from pathlib import Path

from PySide6.QtGui import QIcon, QFont
from PySide6.QtWidgets import QApplication, QMessageBox

from app.version import APP_TITLE, VERSION

APP_DIR = Path(__file__).resolve().parent


def resource_path(name: str) -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", ".")) / name
    return APP_DIR / "resources" / name


STYLESHEET = """
    QToolButton#navBtn { text-align: left; padding: 8px 10px;
                         border: none; border-radius: 6px; font-size: 13px; }
    QToolButton#navBtn:hover { background: #e8f0fe; }
    QToolButton#navBtn:checked { background: #d7e7ff; color: #0b57d0;
                                 font-weight: bold; }
    QLabel#logo { font-size: 17px; font-weight: bold; color: #0b57d0; }
    QLabel#logoSub { font-size: 10px; color: #667; }
    QLabel#versionLabel { color: #99a; font-size: 10px; }
    QFrame#divider { color: #dde; }
    QTreeWidget { font-size: 12px; }
    QPushButton { min-height: 26px; padding: 3px 14px; }
"""


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("EasyExtract")
    app.setApplicationVersion(VERSION)
    app.setApplicationDisplayName(APP_TITLE)

    icon_file = resource_path("icon.ico")
    if icon_file.exists():
        app.setWindowIcon(QIcon(str(icon_file)))
    app.setFont(QFont("Microsoft YaHei UI", 9))
    app.setStyleSheet(STYLESHEET)

    def excepthook(exc_type, exc, tb) -> None:
        traceback.print_exception(exc_type, exc, tb)
        QMessageBox.critical(
            None, "程序错误",
            "发生未处理的错误：\n"
            + "".join(traceback.format_exception_only(exc_type, exc)))
    sys.excepthook = excepthook

    from app.ui.main_window import MainWindow
    win = MainWindow()
    win.show()
    return app.exec()
