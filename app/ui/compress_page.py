"""压缩页：选择文件/文件夹 → 设置格式与选项 → 压缩进度。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QCheckBox, QComboBox, QFileDialog, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QProgressBar,
                               QPushButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from ..core.engine import ArchiveJob, JobState, JobType, TaskManager
from ..core.formats import (CREATE_FORMATS, CREATE_FORMAT_MAP, CreateFormat,
                            human_duration, human_size, suggested_archive_path)
from .password_dialog import PasswordDialog

COL_NAME, COL_SIZE, COL_TYPE = range(3)

LEVELS = (("仅存储（最快）", 0), ("最快", 1), ("标准", 5), ("最大", 9))
VOLUMES = (("不分卷", ""), ("10 MB", "10m"), ("50 MB", "50m"),
           ("100 MB", "100m"), ("512 MB", "512m"), ("1 GB", "1g"))


class CompressPage(QWidget):
    open_folder = Signal(str)

    def __init__(self, manager: TaskManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._items: dict[str, QTreeWidgetItem] = {}
        self._name_dirty = False
        self._fmt: CreateFormat = CREATE_FORMATS[0]
        self._job_started_at: float | None = None
        self.setAcceptDrops(True)
        self._build_ui()
        manager.jobStarted.connect(self._on_job_started)
        manager.jobProgressed.connect(self._on_job_progressed)
        manager.jobFinished.connect(self._on_job_finished)
        manager.allFinished.connect(self._on_all_finished)
        manager.passwordNeeded.connect(self._on_password_needed)

    # ------------------------------------------------------------ 界面

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)

        tip = QLabel("将文件或文件夹拖入下方列表（保留目录结构），或使用按钮添加。")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        btn_row = QHBoxLayout()
        self.btn_add_files = QPushButton("添加文件…")
        self.btn_add_dir = QPushButton("添加文件夹…")
        self.btn_remove = QPushButton("移除所选")
        self.btn_clear = QPushButton("清空列表")
        for b in (self.btn_add_files, self.btn_add_dir, self.btn_remove, self.btn_clear):
            btn_row.addWidget(b)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(3)
        self.tree.setHeaderLabels(("名称", "大小", "类型"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setColumnWidth(0, 430)
        self.tree.setColumnWidth(1, 100)
        lay.addWidget(self.tree, 1)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("保存到："))
        self.edit_outdir = QLineEdit()
        self.edit_outdir.setPlaceholderText("默认与所选文件同级")
        self.btn_outdir = QPushButton("浏览…")
        out_row.addWidget(self.edit_outdir, 1)
        out_row.addWidget(self.btn_outdir)
        lay.addLayout(out_row)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("压缩包名："))
        self.edit_name = QLineEdit()
        self.edit_name.setPlaceholderText("自动按所选内容命名")
        name_row.addWidget(self.edit_name, 1)
        name_row.addWidget(QLabel("格式："))
        self.cmb_fmt = QComboBox()
        for f in CREATE_FORMATS:
            self.cmb_fmt.addItem(f.label, f.key)
        name_row.addWidget(self.cmb_fmt)
        lay.addLayout(name_row)

        opt_row = QHBoxLayout()
        opt_row.addWidget(QLabel("压缩等级："))
        self.cmb_level = QComboBox()
        for label, _ in LEVELS:
            self.cmb_level.addItem(label)
        self.cmb_level.setCurrentIndex(2)
        opt_row.addWidget(self.cmb_level)
        opt_row.addWidget(QLabel("分卷："))
        self.cmb_volume = QComboBox()
        for label, _ in VOLUMES:
            self.cmb_volume.addItem(label)
        opt_row.addWidget(self.cmb_volume)
        opt_row.addStretch(1)
        lay.addLayout(opt_row)

        pwd_row = QHBoxLayout()
        pwd_row.addWidget(QLabel("密码："))
        self.edit_pwd = QLineEdit()
        self.edit_pwd.setEchoMode(QLineEdit.Password)
        self.edit_pwd.setPlaceholderText("留空则不加密")
        pwd_row.addWidget(self.edit_pwd, 1)
        self.cb_show = QCheckBox("显示")
        pwd_row.addWidget(self.cb_show)
        self.cb_encrypt_names = QCheckBox("加密文件名（仅 7z）")
        pwd_row.addWidget(self.cb_encrypt_names)
        lay.addLayout(pwd_row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        bottom = QHBoxLayout()
        self.cb_open = QCheckBox("完成后打开所在文件夹")
        self.cb_open.setChecked(True)
        self.label_state = QLabel("就绪")
        self.label_state.setWordWrap(True)
        self.btn_start = QPushButton("开始压缩")
        self.btn_start.setEnabled(False)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        bottom.addWidget(self.label_state, 1)
        bottom.addWidget(self.cb_open)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_cancel)
        lay.addLayout(bottom)

        self.btn_add_files.clicked.connect(self._add_files_dialog)
        self.btn_add_dir.clicked.connect(self._add_dir_dialog)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_outdir.clicked.connect(self._browse_outdir)
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self.manager.cancel_current)
        self.edit_name.textEdited.connect(lambda _: setattr(self, "_name_dirty", True))
        self.cmb_fmt.currentIndexChanged.connect(self._fmt_changed)
        self.cb_show.toggled.connect(
            lambda on: self.edit_pwd.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.edit_pwd.textChanged.connect(self._update_opt_enabled)

    # ------------------------------------------------------------ 拖拽

    def dragEnterEvent(self, ev) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev) -> None:
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        self.add_paths(paths)

    # ------------------------------------------------------------ 列表

    def add_paths(self, paths: list[str]) -> int:
        added = 0
        for p in paths:
            pp = Path(p)
            if not pp.exists() or p in self._items:
                continue
            kind = "文件夹" if pp.is_dir() else "文件"
            try:
                if pp.is_dir():
                    size = sum(f.stat().st_size for f in pp.rglob("*") if f.is_file())
                else:
                    size = pp.stat().st_size
            except OSError:
                size = 0
            item = QTreeWidgetItem([pp.name, human_size(size), kind])
            item.setData(0, Qt.UserRole, p)
            item.setToolTip(0, p)
            self.tree.addTopLevelItem(item)
            self._items[p] = item
            added += 1
        if added:
            self._suggest_name()
        self._update_start_btn()
        return added

    def _selected_paths(self) -> list[str]:
        return [i.data(0, Qt.UserRole) for i in self.tree.selectedItems()
                if i.data(0, Qt.UserRole)]

    def _remove_selected(self) -> None:
        if self.manager.busy():
            return
        for p in self._selected_paths():
            item = self._items.pop(p, None)
            if item is not None:
                self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self._update_start_btn()

    def _clear(self) -> None:
        if self.manager.busy():
            return
        self.tree.clear()
        self._items.clear()
        self._suggest_name()
        self._update_start_btn()

    # ------------------------------------------------------------ 输出设置

    def _suggest_name(self) -> None:
        if self._name_dirty:
            return
        if not self._items:
            self.edit_name.clear()
            self.edit_name.setPlaceholderText("自动按所选内容命名")
            return
        suggested = suggested_archive_path(list(self._items), self._fmt)
        self.edit_outdir.setText(str(suggested.parent) if not self.edit_outdir.text()
                                 else self.edit_outdir.text())
        self.edit_name.setText(suggested.name)
        self._name_dirty = False

    def _fmt_changed(self) -> None:
        key = self.cmb_fmt.currentData()
        self._fmt = CREATE_FORMAT_MAP[key]
        # 等级对 tar 无意义
        self.cmb_level.setEnabled(self._fmt.sevenz_type != "tar")
        self._update_opt_enabled()
        if not self._name_dirty and self._items:
            base = suggested_archive_path(list(self._items), self._fmt).name
            self.edit_name.setText(base)
            self._name_dirty = False

    def _update_opt_enabled(self, *_):
        self.edit_pwd.setEnabled(self._fmt.password)
        self.cb_show.setEnabled(self._fmt.password)
        self.cb_encrypt_names.setEnabled(self._fmt.encrypt_names and self._fmt.password)
        self.cmb_volume.setEnabled(self._fmt.volume)

    def _browse_outdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择保存目录",
                                             self.edit_outdir.text() or "")
        if d:
            self.edit_outdir.setText(d)

    # ------------------------------------------------------------ 动作

    def _add_files_dialog(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "选择要压缩的文件")
        if files:
            self.add_paths(files)

    def _add_dir_dialog(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择要压缩的文件夹")
        if d:
            self.add_paths([d])

    def _update_start_btn(self) -> None:
        self.btn_start.setEnabled(bool(self._items) and not self.manager.busy())

    def _start(self) -> None:
        if not self._items:
            return
        outdir = Path(self.edit_outdir.text().strip() or str(suggested_archive_path(
            list(self._items), self._fmt).parent))
        name = self.edit_name.text().strip()
        if not name:
            QMessageBox.information(self, "提示", "请填写压缩包名称")
            return
        if not name.lower().endswith(self._fmt.ext):
            name += self._fmt.ext
        outdir.mkdir(parents=True, exist_ok=True)
        archive = outdir / name
        if archive.exists():
            ret = QMessageBox.question(
                self, "覆盖确认", f"{archive.name} 已存在，覆盖它吗？",
                QMessageBox.Yes | QMessageBox.No)
            if ret != QMessageBox.Yes:
                return
            try:
                archive.unlink()
            except OSError as exc:
                QMessageBox.warning(self, "错误", f"无法覆盖：{exc}")
                return

        _, level = LEVELS[self.cmb_level.currentIndex()]
        _, volume = VOLUMES[self.cmb_volume.currentIndex()]
        job = ArchiveJob(
            JobType.COMPRESS, archive,
            sources=list(self._items), fmt=self._fmt, level=level,
            password=self.edit_pwd.text() if self._fmt.password else "",
            encrypt_names=self.cb_encrypt_names.isChecked(),
            volume=volume)
        job.open_after_done = outdir if self.cb_open.isChecked() else None
        job.display_name = archive.name

        self.bar.setValue(0)
        self.label_state.setText("开始压缩…")
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.manager.enqueue([job])

    # ------------------------------------------------------------ 任务回调

    def _on_password_needed(self, job: ArchiveJob, retry: bool) -> None:
        if job is not self.manager.current or job.type is not JobType.COMPRESS:
            return
        pw = PasswordDialog.ask(job.display_name, retry, self.window())
        if pw is None:
            job.cancel()
            return
        self.manager.provide_password(job, pw)

    def _on_job_started(self, job: ArchiveJob) -> None:
        if job.type is not JobType.COMPRESS:
            return
        self._job_started_at = time.monotonic()
        self.bar.setValue(0)
        self.label_state.setText(f"正在压缩 {job.display_name}")

    def _on_job_progressed(self, job: ArchiveJob, pct: int, name: str) -> None:
        if job is not self.manager.current or job.type is not JobType.COMPRESS:
            return
        self.bar.setValue(max(0, min(100, pct)))
        parts = [f"正在压缩 {job.display_name}（{pct}%）"]
        if self._job_started_at is not None:
            elapsed = time.monotonic() - self._job_started_at
            if 1 <= pct <= 99 and elapsed >= 2:
                remain = elapsed * (100 - pct) / pct
                parts.append(f"已用 {human_duration(elapsed)}，预计剩余 {human_duration(remain)}")
            elif elapsed >= 2:
                parts.append(f"已用 {human_duration(elapsed)}")
        self.label_state.setText("，".join(parts))

    def _on_job_finished(self, job: ArchiveJob, ok: bool, msg: str) -> None:
        if job.type is not JobType.COMPRESS:
            return
        if ok:
            self.label_state.setText(f"{job.display_name} 压缩完成")
            if job.open_after_done:
                self.open_folder.emit(str(job.open_after_done))
        elif job.state is JobState.CANCELLED:
            self.label_state.setText("已取消")
        else:
            self.label_state.setText(f"失败：{msg}")

    def _on_all_finished(self, ok_count: int, total: int) -> None:
        self.btn_cancel.setEnabled(False)
        self._update_start_btn()
        if total:
            self.bar.setValue(100 if ok_count == total else self.bar.value())
