"""主窗口：左侧切换「解压」「压缩」两个模式页。"""
from __future__ import annotations

import os

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMainWindow,
                               QStackedWidget, QToolButton, QVBoxLayout,
                               QWidget)

from .. import version
from ..core import engine
from ..core.engine import TaskManager
from .compress_page import CompressPage
from .extract_page import ExtractPage

PAGE_EXTRACT, PAGE_COMPRESS = 0, 1


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(version.APP_TITLE)
        self.resize(920, 620)
        self.setMinimumSize(780, 540)

        self.manager = TaskManager(self)

        central = QWidget()
        root = QHBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ---- 左侧导航 ----
        nav = QWidget()
        nav.setFixedWidth(120)
        nav_lay = QVBoxLayout(nav)
        nav_lay.setContentsMargins(8, 12, 8, 12)
        nav_lay.setSpacing(6)

        logo = QLabel(version.APP_NAME)
        logo.setObjectName("logo")
        logo.setAlignment(Qt.AlignCenter)
        nav_lay.addWidget(logo)
        sub = QLabel(version.APP_NAME_EN)
        sub.setObjectName("logoSub")
        sub.setAlignment(Qt.AlignCenter)
        nav_lay.addWidget(sub)
        nav_lay.addSpacing(10)

        self.btn_extract = self._nav_button("解压", "📦")
        self.btn_compress = self._nav_button("压缩", "🗜")
        self.btn_extract.setObjectName("navBtn")
        self.btn_compress.setObjectName("navBtn")
        nav_lay.addWidget(self.btn_extract)
        nav_lay.addWidget(self.btn_compress)
        nav_lay.addStretch(1)

        ver = QLabel(f"v{version.VERSION}")
        ver.setObjectName("versionLabel")
        ver.setAlignment(Qt.AlignCenter)
        nav_lay.addWidget(ver)

        line = QFrame()
        line.setFrameShape(QFrame.VLine)
        line.setObjectName("divider")

        # ---- 右侧页面 ----
        self.stack = QStackedWidget()
        self.page_extract = ExtractPage(self.manager)
        self.page_compress = CompressPage(self.manager)
        self.stack.addWidget(self.page_extract)
        self.stack.addWidget(self.page_compress)

        self.page_extract.open_folder.connect(self._open_folder)
        self.page_compress.open_folder.connect(self._open_folder)

        root.addWidget(nav)
        root.addWidget(line)
        root.addWidget(self.stack, 1)
        self.setCentralWidget(central)

        self.btn_extract.clicked.connect(lambda: self._switch(PAGE_EXTRACT))
        self.btn_compress.clicked.connect(lambda: self._switch(PAGE_COMPRESS))
        self.btn_extract.setChecked(True)

        self.statusBar().showMessage(
            f"解压引擎：7-Zip {engine.engine_version()}（支持 zip / rar / 7z / tar 等数十种格式）")
        QShortcut(QKeySequence("Ctrl+Q"), self, activated=self.close)

    @staticmethod
    def _nav_button(text: str, icon: str) -> QToolButton:
        btn = QToolButton()
        btn.setText(f"{icon}  {text}")
        btn.setCheckable(True)
        btn.setAutoExclusive(True)
        btn.setIconSize(QSize(20, 20))
        btn.setMinimumHeight(44)
        btn.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        return btn

    def _switch(self, page: int) -> None:
        if self.manager.busy():
            # 任务进行中允许切换查看进度，不阻止
            pass
        self.stack.setCurrentIndex(page)

    def _open_folder(self, path: str) -> None:
        try:
            if os.path.isdir(path):
                os.startfile(path)  # noqa: S606 - Windows 资源管理器
        except OSError:
            pass
