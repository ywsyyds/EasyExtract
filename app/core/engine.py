"""7-Zip 命令行引擎封装：解压、压缩、列内容，全部基于 QProcess 异步执行。

密码处理流程：
  1. 启动进程时不带 -p；7z 需要密码时会在 stderr 输出 "Enter password" 并等待 stdin；
  2. 引擎发出 passwordNeeded 信号，界面弹框后调用 provide_password()，密码写入 stdin；
  3. 若密码错误，7z 以 "Wrong password" 退出，引擎清掉缓存后重新询问并带 -p 重启。
密码按压缩包路径缓存，批量任务无需重复输入。
"""
from __future__ import annotations

import locale
import os
import re
import shutil
import sys
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

import tarfile

from PySide6.QtCore import QEventLoop, QObject, QProcess, Signal


# ---------------------------------------------------------------- 路径定位

def bin_dir() -> Path:
    """7z.exe 所在目录：打包后位于 _MEIPASS/bin，源码运行位于 app/bin。"""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent)) / "bin"
    return Path(__file__).resolve().parent.parent / "bin"


def sevenz_exe() -> str:
    return str(bin_dir() / "7z.exe")


# 密码缓存：{归一化路径: 密码}
PASSWORD_CACHE: dict[str, str] = {}


def cache_key(path: str | Path) -> str:
    return os.path.normcase(os.path.normpath(str(path)))


def _decode(b: bytes) -> str:
    """7z 按 Windows 控制台代码页输出（中文系统为 GBK）。"""
    enc = locale.getpreferredencoding(False) or "utf-8"
    return b.decode(enc, errors="replace")


# ---------------------------------------------------------------- 数据结构

@dataclass
class ArchiveEntry:
    path: str
    size: int = 0
    packed: int = 0
    modified: str = ""
    attr: str = ""
    is_dir: bool = False


class JobType(Enum):
    EXTRACT = "extract"
    COMPRESS = "compress"


class JobState(Enum):
    PENDING = "等待中"
    RUNNING = "处理中"
    NEED_PASSWORD = "需要密码"
    SUCCESS = "完成"
    FAILED = "失败"
    CANCELLED = "已取消"


class EngineError(Exception):
    pass


# tar.* 复合格式：解压需两步（先解外层压缩，再解内层 tar），列表用 tarfile 读取
COMPOUND_SUFFIXES = (".tar.gz", ".tgz", ".tar.bz2", ".tbz", ".tbz2",
                     ".tar.xz", ".txz", ".tar.zst", ".tzst")


def is_compound_tar(path: str | Path) -> bool:
    return str(path).lower().endswith(COMPOUND_SUFFIXES)


class ArchiveJob(QObject):
    """一个压缩/解压任务，对应一次（或 tar.* 两步）7z.exe 调用。"""

    progressed = Signal(int, str)        # 百分比 0-100, 当前文件
    stateChanged = Signal(object)        # JobState
    passwordNeeded = Signal(bool)        # True 表示上一次密码错误
    finished = Signal(bool, str)         # 成功?, 消息

    def __init__(self, job_type: JobType, archive: Path, *, parent=None,
                 out_dir: Path | None = None,          # extract
                 sources: list[str] | None = None,     # compress
                 fmt=None,                              # CreateFormat
                 level: int = 5,
                 password: str = "",
                 encrypt_names: bool = False,
                 volume: str = ""):
        super().__init__(parent)
        self.type = job_type
        self.archive = Path(archive)
        self.out_dir = Path(out_dir) if out_dir else None
        self.sources = list(sources or [])
        self.fmt = fmt
        self.level = int(level)
        self.password = password or ""
        self.encrypt_names = encrypt_names
        self.volume = volume

        self.state = JobState.PENDING
        self.error_msg = ""
        self.open_after_done: Path | None = None   # 完成后建议打开的目录
        self.display_name = self.archive.name

        self._proc: QProcess | None = None
        self._cancelled = False
        self._awaiting_stdin = False
        self._last_progress_text = ""
        self._tail = ""                # 最近输出，用于提取错误信息
        self._phase = 0                # 两步流程（tar.* 解包/打包）的当前步骤
        self._temp_tar: Path | None = None
        self._temp_dir: Path | None = None
        self._cwd: str | None = None
        self._percent_scale = (0.0, 1.0)
        self._compound = job_type is JobType.EXTRACT and is_compound_tar(archive)

    # ---------------------------------------------------------- 对外控制

    def start(self) -> None:
        self._set_state(JobState.RUNNING)
        self._launch()

    def cancel(self) -> None:
        if self._cancelled:
            return
        self._cancelled = True
        if self._proc is not None:
            self._proc.kill()

    def provide_password(self, pw: str, from_wrong: bool) -> None:
        """界面收到 passwordNeeded 后调用。"""
        self.password = pw
        if pw:
            PASSWORD_CACHE[cache_key(self.archive)] = pw
        if from_wrong or self._proc is None:
            # 上次密码错误或进程已退出：带 -p 重启
            self._launch()
            return
        # 进程正在等待 stdin
        self._awaiting_stdin = False
        self._set_state(JobState.RUNNING)
        self._proc.write((pw + "\n").encode(locale.getpreferredencoding(False)))

    # ---------------------------------------------------------- 命令构建

    def _final_output(self) -> Path:
        return self.archive

    def _build_args(self) -> tuple[list[str], str | None]:
        """返回 (参数列表, 工作目录)。"""
        args: list[str] = ["a" if self.type is JobType.COMPRESS else "x", "-y", "-bsp1"]
        cwd: str | None = None

        if self.type is JobType.EXTRACT:
            if self._compound and self._phase == 0:
                # 第一步：把外层（gz/xz/zst）解开，得到内层 .tar（进度占 0-50%）
                self._percent_scale = (0.0, 0.5)
                self._temp_dir = self.out_dir / ".ee_tmp_extract"
                args += [f"-o{self._temp_dir}", str(self.archive)]
            elif self._compound:
                # 第二步：解内层 tar 到最终目录（进度占 50-100%）
                self._percent_scale = (0.5, 1.0)
                args += [f"-o{self.out_dir}", str(self._temp_tar)]
            else:
                args += [f"-o{self.out_dir}", str(self.archive)]
            if self.password:
                args.append(f"-p{self.password}")
            return args, None

        # ---- 压缩 ----
        fmt = self.fmt
        if self._phase == 0 and fmt.two_step:
            # 第一步：打 tar 包（进度占 0-60%）
            self._percent_scale = (0.0, 0.6)
            self._temp_tar = self.archive.parent / (self.archive.name[: -len(fmt.ext)] + ".tar")
            args += ["-ttar", "-mx=0", str(self._temp_tar)]
            cwd = self._compress_common_dir()
            args += self._compress_relative_sources()
            return args, cwd
        if fmt.two_step:
            # 第二步：压缩外层（tar → gz/bz2/xz，进度占 60-100%）
            self._percent_scale = (0.6, 1.0)
            args += [f"-t{fmt.sevenz_type}", f"-mx={self.level}",
                     str(self.archive), str(self._temp_tar)]
            return args, None

        args += [f"-t{fmt.sevenz_type}"]
        if fmt.sevenz_type == "tar":
            args.append("-mx=0")
        else:
            args.append(f"-mx={self.level}")
        if fmt.sevenz_type == "7z":
            args.append("-ms=on")
        if self.password and fmt.password:
            args.append(f"-p{self.password}")
            if fmt.sevenz_type == "zip":
                args.append("-mem=AES256")
        if self.encrypt_names and fmt.encrypt_names and self.password:
            args.append("-mhe=on")
        if self.volume and fmt.volume:
            args.append(f"-v{self.volume}")
        args.append(str(self.archive))
        cwd = self._compress_common_dir()
        args += self._compress_relative_sources()
        return args, cwd

    def _compress_common_dir(self) -> str:
        abs_sources = [os.path.abspath(s) for s in self.sources]
        try:
            common = os.path.commonpath(abs_sources)
        except ValueError:
            return ""
        if not common or os.path.isfile(common):
            return os.path.dirname(common) if common else ""
        return common

    def _compress_relative_sources(self) -> list[str]:
        common = self._compress_common_dir()
        rels = []
        for s in self.sources:
            abs_s = os.path.abspath(s)
            try:
                rels.append(os.path.relpath(abs_s, common) if common else abs_s)
            except ValueError:
                rels.append(abs_s)
        return rels

    # ---------------------------------------------------------- 进程管理

    def _launch(self) -> None:
        args, cwd = self._build_args()
        proc = QProcess(self)
        proc.setProcessChannelMode(QProcess.SeparateChannels)
        if cwd:
            proc.setWorkingDirectory(cwd)
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_error)
        self._proc = proc
        self._awaiting_stdin = False
        self._tail = ""
        proc.start(sevenz_exe(), args)

    def _append_tail(self, text: str) -> None:
        self._tail = (self._tail + text)[-8192:]

    def _on_stdout(self) -> None:
        proc = self._proc
        if proc is None:
            return
        text = _decode(bytes(proc.readAllStandardOutput()))
        self._append_tail(text)
        self._check_prompt(text)
        for line in text.splitlines():
            m = re.match(r"^\s*(\d{1,3})%\s*(.*)$", line)
            if m:
                pct = int(m.group(1))
                lo, hi = self._percent_scale
                scaled = int(lo * 100 + pct * (hi - lo))
                name = m.group(2).strip()
                # 去掉 "12 + " / "3 - " 之类的前缀计数
                name = re.sub(r"^\d+\s*[-+]\s*", "", name).strip()
                self.progressed.emit(max(0, min(100, scaled)), name or self._last_progress_text)
                if name:
                    self._last_progress_text = name

    def _on_stderr(self) -> None:
        proc = self._proc
        if proc is None:
            return
        text = _decode(bytes(proc.readAllStandardError()))
        self._append_tail(text)
        self._check_prompt(text)

    def _check_prompt(self, text: str) -> None:
        """密码提示可能出现在 stdout 或 stderr（实测以 stdout 为主）。"""
        if self._cancelled or not text:
            return
        if "Enter password" in text and not self._awaiting_stdin and self._proc is not None:
            self._awaiting_stdin = True
            cached = PASSWORD_CACHE.get(cache_key(self.archive))
            if cached is not None:
                # 静默尝试缓存密码
                self._awaiting_stdin = False
                self._proc.write((cached + "\n").encode(locale.getpreferredencoding(False)))
                return
            self._set_state(JobState.NEED_PASSWORD)
            self.passwordNeeded.emit(False)

    def _on_error(self, err) -> None:
        if self._cancelled:
            return
        if err == QProcess.FailedToStart:
            self._set_state(JobState.FAILED)
            self.finished.emit(False, "无法启动 7z.exe，程序安装可能不完整")

    def _on_finished(self, code: int, status) -> None:
        self._proc = None
        if self._cancelled:
            self._cleanup_temp()
            self._set_state(JobState.CANCELLED)
            self.finished.emit(False, "已取消")
            return

        out = self._tail
        if "Wrong password" in out or "Wrong Password" in out:
            PASSWORD_CACHE.pop(cache_key(self.archive), None)
            self.password = ""
            self._set_state(JobState.NEED_PASSWORD)
            self.passwordNeeded.emit(True)
            return

        if code in (0, 1):  # 1 = 有警告但成功
            self._advance_after_ok()
            return

        # 失败：提取错误行
        errs = [ln.strip() for ln in out.splitlines()
                if ln.strip().upper().startswith("ERROR")]
        msg = "\n".join(errs[-3:]) if errs else f"7z.exe 退出码 {code}"
        if "Cannot get password" in out or "Enter password" in out:
            msg = "该压缩包已加密，需要提供密码"
            PASSWORD_CACHE.pop(cache_key(self.archive), None)
            self._set_state(JobState.NEED_PASSWORD)
            self.passwordNeeded.emit(True)
            return
        self._cleanup_temp()
        self._set_state(JobState.FAILED)
        self.finished.emit(False, msg)

    def _advance_after_ok(self) -> None:
        if self.type is JobType.COMPRESS and self.fmt.two_step and self._phase == 0:
            # tar 打包完成 → 第二步压缩
            self._phase = 1
            self._launch()
            return
        if self.type is JobType.EXTRACT and self._compound and self._phase == 0:
            # 外层解开 → 定位内层 tar → 第二步解包
            tars = list(self._temp_dir.glob("*.tar")) if self._temp_dir else []
            if not tars:
                self._cleanup_temp()
                self._set_state(JobState.FAILED)
                self.finished.emit(False, "无法定位压缩包内层的 tar 文件")
                return
            self._temp_tar = tars[0]
            self._phase = 1
            self._launch()
            return
        self._cleanup_temp()
        self.progressed.emit(100, "")
        self._set_state(JobState.SUCCESS)
        self.finished.emit(True, "解压完成" if self.type is JobType.EXTRACT else "压缩完成")

    def _cleanup_temp(self) -> None:
        if self._temp_tar is not None:
            try:
                self._temp_tar.unlink(missing_ok=True)
            except OSError:
                pass
            self._temp_tar = None
        if self._temp_dir is not None:
            shutil.rmtree(self._temp_dir, ignore_errors=True)
            self._temp_dir = None

    def _set_state(self, st: JobState) -> None:
        self.state = st
        self.stateChanged.emit(st)


# ---------------------------------------------------------------- 任务队列

class TaskManager(QObject):
    """顺序执行任务队列；负责密码转交与缓存。"""

    jobStarted = Signal(object)              # ArchiveJob
    jobProgressed = Signal(object, int, str)  # ArchiveJob, 百分比, 当前文件
    jobFinished = Signal(object, bool, str)  # ArchiveJob, ok, msg
    allFinished = Signal(int, int)           # 成功数, 总数
    passwordNeeded = Signal(object, bool)    # ArchiveJob, 重试?

    def __init__(self, parent=None):
        super().__init__(parent)
        self.queue: list[ArchiveJob] = []
        self.current: ArchiveJob | None = None
        self._results: list[tuple[bool]] = []
        self._total = 0

    def enqueue(self, jobs: list[ArchiveJob]) -> None:
        self.queue.extend(jobs)
        self._total += len(jobs)
        for j in jobs:
            j.passwordNeeded.connect(self._on_password_needed)
        if self.current is None:
            self._start_next()

    def busy(self) -> bool:
        return self.current is not None or bool(self.queue)

    def cancel_current(self) -> None:
        if self.current is not None:
            self.current.cancel()

    def cancel_all(self) -> None:
        for j in list(self.queue):
            j.cancel()
        self.queue.clear()
        self.cancel_current()

    def provide_password(self, job: ArchiveJob, pw: str) -> None:
        if job is self.current:
            job.provide_password(pw, from_wrong=False)

    def _on_password_needed(self, from_wrong: bool) -> None:
        job = self.sender()
        self.passwordNeeded.emit(job, from_wrong)

    def _start_next(self) -> None:
        if not self.queue:
            self.current = None
            ok = sum(1 for (o,) in self._results if o)
            self.allFinished.emit(ok, self._total)
            self._results = []
            self._total = 0
            return
        self.current = self.queue.pop(0)
        self.current.finished.connect(self._on_job_finished)
        self.current.progressed.connect(self._on_job_progressed)
        self.jobStarted.emit(self.current)
        self.current.start()

    def _on_job_progressed(self, pct: int, name: str) -> None:
        self.jobProgressed.emit(self.current, pct, name)

    def _on_job_finished(self, ok: bool, msg: str) -> None:
        job = self.current
        if job is None:
            return
        self._results.append((ok,))
        self.jobFinished.emit(job, ok, msg)
        self._start_next()


# ---------------------------------------------------------------- 同步工具（列表/版本）

def run_7z_sync(args: list[str], archive: str | None = None,
                parent: QObject | None = None) -> tuple[int, str]:
    """同步执行 7z 并返回 (退出码, 全部输出)。需要密码时通过缓存或回调取。"""
    from PySide6.QtWidgets import QApplication

    loop = QEventLoop()
    proc = QProcess(parent)
    out: list[bytes] = []

    def on_stdout():
        out.append(bytes(proc.readAllStandardOutput()))

    def on_stderr():
        data = bytes(proc.readAllStandardError())
        out.append(data)
        text = _decode(data)
        if "Enter password" in text and archive:
            pw = PASSWORD_CACHE.get(cache_key(archive))
            if pw is None and callable(globals().get("password_prompt_callback")):
                pw = password_prompt_callback(archive, False)
                if pw:
                    PASSWORD_CACHE[cache_key(archive)] = pw
            if pw:
                proc.write((pw + "\n").encode(locale.getpreferredencoding(False)))

    def on_done(*_):
        loop.quit()

    proc.readyReadStandardOutput.connect(on_stdout)
    proc.readyReadStandardError.connect(on_stderr)
    proc.finished.connect(on_done)
    proc.start(sevenz_exe(), args)
    loop.exec()
    if not proc.waitForFinished(2000):
        proc.kill()
        proc.waitForFinished(1000)
    return proc.exitCode(), "".join(_decode(o) for o in out)


password_prompt_callback = None  # 由 UI 注入：def cb(archive_name, retry) -> str|None


def list_archive(archive: str | Path, parent: QObject | None = None) -> list[ArchiveEntry]:
    """列出压缩包内容（同步）。加密头需要密码时回调 password_prompt_callback。"""
    arc = str(archive)
    if is_compound_tar(arc):
        return _list_compound_tar(arc)

    args = ["l", "-slt", "-ba", arc]
    # 预先带上缓存的密码
    cached = PASSWORD_CACHE.get(cache_key(arc))
    if cached:
        args.insert(1, f"-p{cached}")
    code, out = run_7z_sync(args, archive=arc, parent=parent)
    if "Wrong password" in out:
        raise EngineError("密码错误")
    if code not in (0, 1):
        errs = [ln.strip() for ln in out.splitlines() if "ERROR" in ln.upper()]
        if "Enter password" in out or "Cannot get password" in out:
            raise EngineError("需要密码")
        raise EngineError("\n".join(errs[-2:]) or f"无法读取压缩包（退出码 {code}）")

    entries: list[ArchiveEntry] = []
    cur: dict[str, str] = {}

    def flush():
        if not cur or "Path" not in cur:
            return
        entries.append(ArchiveEntry(
            path=cur.get("Path", ""),
            size=int(cur.get("Size", "0") or 0),
            packed=int(cur.get("Packed Size", "0") or 0),
            modified=cur.get("Modified", ""),
            attr=cur.get("Attributes", ""),
            is_dir=cur.get("Folder", "-") == "+",
        ))

    for line in out.splitlines():
        if not line.strip():
            flush()
            cur = {}
            continue
        if " = " in line:
            k, _, v = line.partition(" = ")
            cur[k.strip()] = v.strip()
    flush()
    return entries


def _list_compound_tar(arc: str) -> list[ArchiveEntry]:
    """tar.gz / tar.xz 等复合包：用 Python tarfile 流式读取（7z 命令行嵌套列表不可靠）。"""
    import datetime

    def _fmt_mtime(ts: float) -> str:
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S") if ts else ""

    entries: list[ArchiveEntry] = []
    try:
        with tarfile.open(arc, mode="r|*", encoding="utf-8", errors="replace") as tf:
            while True:
                member = tf.next()
                if member is None:
                    break
                if member.isdir():
                    entries.append(ArchiveEntry(
                        path=member.name.replace("\\", "/"),
                        size=0, packed=0, modified=_fmt_mtime(member.mtime),
                        attr="D", is_dir=True))
                elif member.isreg():
                    entries.append(ArchiveEntry(
                        path=member.name.replace("\\", "/"),
                        size=member.size, packed=0,
                        modified=_fmt_mtime(member.mtime), attr="A"))
                # 其他类型（链接、pax 头等）跳过
    except (tarfile.TarError, OSError) as exc:
        raise EngineError(f"无法读取压缩包：{exc}") from exc
    return entries


def engine_version() -> str:
    code, out = run_7z_sync(["i"], parent=None)
    if code != 0:
        return "未知"
    m = re.search(r"7-Zip\s+([\d.]+)", out)
    return m.group(1) if m else "未知"
