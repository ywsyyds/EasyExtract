"""压缩包内容浏览对话框（异步加载 7z l -slt）。"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtWidgets import (QDialog, QDialogButtonBox, QLabel, QProgressBar,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout)

from ..core import engine
from ..core.formats import human_size


class ContentDialog(QDialog):
    COLUMNS = ("名称", "大小", "压缩后", "修改时间", "属性")

    def __init__(self, archive: str | Path, parent=None):
        super().__init__(parent)
        self.archive = Path(archive)
        self.setWindowTitle(f"浏览内容 — {self.archive.name}")
        self.resize(720, 480)

        lay = QVBoxLayout(self)
        self.info_label = QLabel("正在读取内容列表…")
        lay.addWidget(self.info_label)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(len(self.COLUMNS))
        self.tree.setHeaderLabels(self.COLUMNS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSortingEnabled(True)
        self.tree.sortByColumn(0, Qt.AscendingOrder)
        self.tree.setColumnWidth(0, 320)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 90)
        self.tree.setColumnWidth(3, 150)
        lay.addWidget(self.tree)

        self.bar = QProgressBar()
        self.bar.setRange(0, 0)  # 忙碌指示
        self.bar.setVisible(False)
        lay.addWidget(self.bar)

        btns = QDialogButtonBox(QDialogButtonBox.Close)
        btns.rejected.connect(self.reject)
        btns.clicked.connect(self.accept)
        lay.addWidget(btns)

        self._start()

    def _start(self) -> None:
        self._thread = _ListThread(self.archive)
        self._thread.done.connect(self._on_done)
        self.bar.setVisible(True)
        self._thread.start()

    def _on_done(self, entries, error: str) -> None:
        self.bar.setVisible(False)
        if error:
            # 需要密码时向用户询问后重试
            if "密码" in error or "password" in error.lower():
                from .password_dialog import PasswordDialog
                pw = PasswordDialog.ask(self.archive.name, retry="错误" in error, parent=self)
                if pw is not None:
                    engine.PASSWORD_CACHE[engine.cache_key(self.archive)] = pw
                    self._start()
                    return
            self.info_label.setText(f"<span style='color:#c00'>读取失败：{error}</span>")
            return

        self.tree.clear()
        n_files = n_dirs = 0
        total = 0
        for e in entries:
            if e.is_dir:
                n_dirs += 1
            else:
                n_files += 1
                total += e.size
            item = QTreeWidgetItem(
                [e.path, "" if e.is_dir else human_size(e.size),
                 "" if e.is_dir else human_size(e.packed), e.modified, e.attr])
            item.setData(0, Qt.UserRole, e.size)
            self.tree.addTopLevelItem(item)
        summary = f"共 {n_files} 个文件"
        if n_dirs:
            summary += f"，{n_dirs} 个文件夹"
        summary += f"，总大小 {human_size(total)}"
        self.info_label.setText(summary)

    def closeEvent(self, ev) -> None:
        t = getattr(self, "_thread", None)
        if t is not None and t.isRunning():
            t.wait(1500)
        super().closeEvent(ev)


class _ListThread(QThread):
    """在子线程中同步调用 7z 列表，避免大压缩包卡住界面。"""

    done = Signal(object, str)

    def __init__(self, archive: Path):
        super().__init__()
        self.archive = archive

    def run(self) -> None:
        try:
            entries = engine.list_archive(self.archive)
            self.done.emit(entries, "")
        except Exception as exc:  # noqa: BLE001
            self.done.emit(None, str(exc))
