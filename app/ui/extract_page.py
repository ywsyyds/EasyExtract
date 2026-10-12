"""解压页：添加压缩包 → 任务队列 → 解压进度。"""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QFileDialog,
                               QHBoxLayout, QLabel, QLineEdit, QProgressBar,
                               QRadioButton, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import engine
from ..core.engine import ArchiveJob, JobState, JobType, TaskManager
from ..core.formats import (archive_format_name, default_extract_dir,
                            human_duration, human_size, is_archive)
from .content_dialog import ContentDialog
from .password_dialog import PasswordDialog

COL_NAME, COL_SIZE, COL_FMT, COL_DST, COL_STATE = range(5)


class ExtractPage(QWidget):
    open_folder = Signal(str)   # 请求主窗口打开某文件夹

    def __init__(self, manager: TaskManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        self._rows: dict[ArchiveJob, QTreeWidgetItem] = {}
        self._batch: list[ArchiveJob] = []
        self._done_count = 0
        self._job_started_at: float | None = None
        self._set_accept_drops(True)
        self._build_ui()
        self.manager.jobStarted.connect(self._on_job_started)
        self.manager.jobProgressed.connect(self._on_job_progressed)
        self.manager.jobFinished.connect(self._on_job_finished)
        self.manager.allFinished.connect(self._on_all_finished)
        self.manager.passwordNeeded.connect(self._on_password_needed)

    # ------------------------------------------------------------ 界面

    def _build_ui(self) -> None:
        lay = QVBoxLayout(self)

        tip = QLabel("将压缩包拖入下方列表，或点击「添加压缩包」。支持 zip / rar / 7z / tar / gz / xz / iso 等数十种格式，双击行可预览内容。")
        tip.setWordWrap(True)
        lay.addWidget(tip)

        btn_row = QHBoxLayout()
        self.btn_add = QPushButton("添加压缩包…")
        self.btn_remove = QPushButton("移除所选")
        self.btn_clear = QPushButton("清空列表")
        btn_row.addWidget(self.btn_add)
        btn_row.addWidget(self.btn_remove)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(5)
        self.tree.setHeaderLabels(("文件", "大小", "格式", "解压到", "状态"))
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tree.setColumnWidth(0, 300)
        self.tree.setColumnWidth(1, 90)
        self.tree.setColumnWidth(2, 70)
        self.tree.setColumnWidth(3, 240)
        self.tree.itemDoubleClicked.connect(self._preview)
        lay.addWidget(self.tree, 1)

        dst_row = QHBoxLayout()
        self.rb_subfolder = QRadioButton("解压到各自同名文件夹")
        self.rb_custom = QRadioButton("解压到指定目录：")
        self.rb_subfolder.setChecked(True)
        self.edit_dst = QLineEdit()
        self.edit_dst.setPlaceholderText("选择目录后启用")
        self.edit_dst.setEnabled(False)
        self.btn_browse = QPushButton("浏览…")
        self.btn_browse.setEnabled(False)
        dst_row.addWidget(self.rb_subfolder)
        dst_row.addWidget(self.rb_custom)
        dst_row.addWidget(self.edit_dst, 1)
        dst_row.addWidget(self.btn_browse)
        lay.addLayout(dst_row)

        opt_row = QHBoxLayout()
        self.cb_open = QCheckBox("完成后打开目标文件夹")
        self.cb_open.setChecked(True)
        opt_row.addWidget(self.cb_open)
        opt_row.addStretch(1)
        lay.addLayout(opt_row)

        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setValue(0)
        self.bar.setTextVisible(False)
        lay.addWidget(self.bar)

        bottom = QHBoxLayout()
        self.label_state = QLabel("就绪")
        self.label_state.setWordWrap(True)
        self.btn_start = QPushButton("开始解压")
        self.btn_start.setEnabled(False)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setEnabled(False)
        bottom.addWidget(self.label_state, 1)
        bottom.addWidget(self.btn_start)
        bottom.addWidget(self.btn_cancel)
        lay.addLayout(bottom)

        self.btn_add.clicked.connect(self._add_dialog)
        self.btn_remove.clicked.connect(self._remove_selected)
        self.btn_clear.clicked.connect(self._clear)
        self.btn_start.clicked.connect(self._start)
        self.btn_cancel.clicked.connect(self.manager.cancel_current)
        self.rb_subfolder.toggled.connect(
            lambda on: (self.edit_dst.setEnabled(not on), self.btn_browse.setEnabled(not on)))
        self.btn_browse.clicked.connect(self._browse_dst)
        self._update_start_btn()

    def _set_accept_drops(self, on: bool) -> None:
        self.setAcceptDrops(on)

    def dragEnterEvent(self, ev: QDragEnterEvent) -> None:
        if ev.mimeData().hasUrls():
            ev.acceptProposedAction()

    def dropEvent(self, ev: QDropEvent) -> None:
        paths = [u.toLocalFile() for u in ev.mimeData().urls() if u.isLocalFile()]
        self.add_archives([p for p in paths if is_archive(p)])

    # ------------------------------------------------------------ 列表管理

    def add_archives(self, paths: list[str]) -> int:
        added = 0
        for p in paths:
            ap = Path(p)
            if not ap.is_file() or not is_archive(ap):
                continue
            # 去重
            if any(Path(j.archive) == ap for j in self._rows):
                continue
            job = ArchiveJob(JobType.EXTRACT, ap,
                             out_dir=default_extract_dir(ap, self.rb_subfolder.isChecked()))
            item = QTreeWidgetItem(
                [ap.name, "…", archive_format_name(ap), str(job.out_dir), "等待中"])
            item.setData(0, Qt.UserRole, str(ap))
            item.setToolTip(0, str(ap))
            item.setToolTip(3, str(job.out_dir))
            self.tree.addTopLevelItem(item)
            self._rows[job] = item
            self._fill_size_async(ap, item)
            added += 1
        self._update_start_btn()
        return added

    def _fill_size_async(self, path: Path, item: QTreeWidgetItem) -> None:
        try:
            item.setText(COL_SIZE, human_size(path.stat().st_size))
        except OSError:
            item.setText(COL_SIZE, "?")

    def _remove_selected(self) -> None:
        if self.manager.busy():
            return
        for item in self.tree.selectedItems():
            for job, it in list(self._rows.items()):
                if it is item:
                    del self._rows[job]
            self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(item))
        self._update_start_btn()

    def _clear(self) -> None:
        if self.manager.busy():
            return
        self.tree.clear()
        self._rows.clear()
        self._batch = []
        self._done_count = 0
        self.bar.setValue(0)
        self.label_state.setText("就绪")
        self._update_start_btn()

    def _update_start_btn(self) -> None:
        self.btn_start.setEnabled(bool(self._rows) and not self.manager.busy())

    # ------------------------------------------------------------ 目标/动作

    def _add_dialog(self) -> None:
        exts = " ".join(f"*{e}" for e in
                        (".zip", ".7z", ".rar", ".tar", ".gz", ".tgz", ".bz2",
                         ".xz", ".zst", ".cab", ".iso", ".wim", ".msi", ".dmg"))
        files, _ = QFileDialog.getOpenFileNames(
            self, "选择压缩包", "", f"压缩包 ({exts});;所有文件 (*.*)")
        if files:
            self.add_archives(files)

    def _browse_dst(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择解压目标目录", self.edit_dst.text() or "")
        if d:
            self.edit_dst.setText(d)
            # 更新未开始任务的显示
            for job, item in self._rows.items():
                job.out_dir = Path(d)
                item.setText(COL_DST, d)

    def _start(self) -> None:
        jobs = list(self._rows.keys())
        if not jobs:
            return
        if self.rb_custom.isChecked() and not self.edit_dst.text().strip():
            self.label_state.setText("请先选择目标目录")
            return
        for job in jobs:
            if self.rb_custom.isChecked():
                job.out_dir = Path(self.edit_dst.text().strip())
            job.open_after_done = job.out_dir if self.cb_open.isChecked() else None
        self._batch = jobs
        self._done_count = 0
        self.bar.setValue(0)
        self.label_state.setText("开始解压…")
        self.btn_start.setEnabled(False)
        self.btn_cancel.setEnabled(True)
        self.manager.enqueue(jobs)

    # ------------------------------------------------------------ 任务回调

    def _on_password_needed(self, job: ArchiveJob, retry: bool) -> None:
        if job is not self.manager.current or job.type is not JobType.EXTRACT:
            return
        pw = PasswordDialog.ask(job.archive.name, retry, self.window())
        if pw is None:
            job.cancel()
            return
        self.manager.provide_password(job, pw)

    def _on_job_started(self, job: ArchiveJob) -> None:
        item = self._rows.get(job)
        if item:
            item.setText(COL_STATE, "解压中 0%")
        self._job_started_at = time.monotonic()
        self.bar.setValue(0)

    def _on_job_progressed(self, job: ArchiveJob, pct: int, name: str) -> None:
        if job is not self.manager.current or job.type is not JobType.EXTRACT:
            return
        item = self._rows.get(job)
        if item:
            item.setText(COL_STATE, f"解压中 {pct}%")

        total = max(1, len(self._batch))
        overall = int((self._done_count + pct / 100) / total * 100)
        self.bar.setValue(max(0, min(100, overall)))

        parts = [f"正在解压 {job.archive.name}（第 {self._done_count + 1}/{total} 个，{pct}%）"]
        if self._job_started_at is not None:
            elapsed = time.monotonic() - self._job_started_at
            if 1 <= pct <= 99 and elapsed >= 2:
                remain = elapsed * (100 - pct) / pct
                parts.append(f"已用 {human_duration(elapsed)}，预计剩余 {human_duration(remain)}")
            elif elapsed >= 2:
                parts.append(f"已用 {human_duration(elapsed)}")
        if name:
            parts.append(f"当前：{name}")
        self.label_state.setText("，".join(parts))

    def _on_job_finished(self, job: ArchiveJob, ok: bool, msg: str) -> None:
        if job not in self._rows:
            return
        self._done_count += 1
        item = self._rows.get(job)
        if item:
            state_text = job.state.value
            if not ok and msg and job.state in (JobState.FAILED,):
                state_text = f"失败：{msg.replace(chr(10), ' ')}"
            elif job.state is JobState.CANCELLED:
                state_text = "已取消"
            item.setText(COL_STATE, state_text)
            if job.state is JobState.FAILED:
                item.setToolTip(COL_STATE, msg)
        if ok and job.open_after_done is not None:
            self.open_folder.emit(str(job.open_after_done))

    def _on_all_finished(self, ok_count: int, total: int) -> None:
        self.btn_cancel.setEnabled(False)
        self._update_start_btn()
        self.label_state.setText(f"全部完成：{ok_count}/{total} 个成功")
        self.bar.setValue(100 if ok_count == total else self.bar.value())

    def _preview(self, item: QTreeWidgetItem, _col: int) -> None:
        path = item.data(0, Qt.UserRole)
        if path and Path(path).is_file():
            dlg = ContentDialog(path, self.window())
            dlg.setModal(True)
            dlg.show()
