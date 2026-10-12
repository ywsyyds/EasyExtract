"""密码输入对话框。"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QDialog, QDialogButtonBox, QLabel,
                               QLineEdit, QVBoxLayout)


class PasswordDialog(QDialog):
    """询问压缩包密码。retry=True 表示上一次密码错误。"""

    def __init__(self, archive_name: str, retry: bool = False, parent=None):
        super().__init__(parent)
        self.setWindowTitle("需要密码")
        self.setMinimumWidth(380)
        self.setModal(True)

        lay = QVBoxLayout(self)
        tip = "该压缩包已加密，请输入密码："
        if retry:
            tip = "密码错误，请重新输入："
        lay.addWidget(QLabel(f"<b>{archive_name}</b>"))
        lay.addWidget(QLabel(tip))

        self.edit = QLineEdit()
        self.edit.setEchoMode(QLineEdit.Password)
        self.edit.setPlaceholderText("密码")
        lay.addWidget(self.edit)

        self.show_cb = QCheckBox("显示密码")
        lay.addWidget(self.show_cb)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        lay.addWidget(btns)

        self.show_cb.toggled.connect(
            lambda on: self.edit.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.edit.textChanged.connect(
            lambda _: btns.button(QDialogButtonBox.Ok).setEnabled(bool(self.edit.text())))
        btns.button(QDialogButtonBox.Ok).setEnabled(False)

    @staticmethod
    def ask(archive_name: str, retry: bool = False, parent=None) -> str | None:
        dlg = PasswordDialog(archive_name, retry, parent)
        dlg.edit.setFocus()
        if dlg.exec() == QDialog.Accepted:
            return dlg.edit.text()
        return None
