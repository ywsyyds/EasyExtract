"""引擎自动化测试（无 GUI）：解压 / 压缩 / 密码 / 分卷 / 取消 / 列表。

用法：py scripts\test_engine.py
"""
from __future__ import annotations

import os
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from app.core import engine
from app.core.engine import ArchiveJob, JobState, JobType, TaskManager
from app.core.formats import CREATE_FORMAT_MAP

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "samples"
WORK = ROOT / "tests" / "_work"

PASS, FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (PASS if cond else FAIL).append(name)
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}" + (f"  -- {detail}" if detail and not cond else ""))


def wait_signal(sig, timeout_ms=120_000) -> list:
    """阻塞等待信号触发，返回参数列表。"""
    result: list = []
    loop = QEventLoop()

    def on(*args):
        result.extend(args)
        loop.quit()

    sig.connect(on)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    try:
        sig.disconnect(on)
    except RuntimeError:
        pass
    return result


def snapshot(d: Path) -> dict[str, bytes]:
    out = {}
    for p in sorted(d.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(d)).replace("\\", "/")] = p.read_bytes()
    return out


def payload_snapshot() -> dict[str, bytes]:
    base = ROOT / "tests" / "_payload"
    return snapshot(base)


def run_extract(arc: Path, out: Path, password: str = "") -> ArchiveJob:
    job = ArchiveJob(JobType.EXTRACT, arc, out_dir=out, password=password)
    mgr = TaskManager()
    mgr.jobFinished.connect(lambda *a: None)
    fin = []
    job.finished.connect(lambda ok, msg: fin.append((ok, msg)))
    mgr.enqueue([job])
    ok, msg = wait_signal(mgr.allFinished)
    return job


def run_compress(arc: Path, sources: list[str], fmt, level=5, password="", volume="") -> ArchiveJob:
    job = ArchiveJob(JobType.COMPRESS, arc, sources=sources, fmt=fmt,
                     level=level, password=password, volume=volume)
    mgr = TaskManager()
    fin = []
    job.finished.connect(lambda ok, msg: fin.append((ok, msg)))
    mgr.enqueue([job])
    wait_signal(mgr.allFinished)
    return job


def main() -> int:
    app = QCoreApplication.instance() or QCoreApplication(sys.argv)

    if WORK.exists():
        shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)

    print("== 版本与格式 ==")
    ver = engine.engine_version()
    check("引擎版本可读", bool(ver), ver)
    print(f"  7-Zip {ver}")

    print("== 列表 ==")
    for name in ("sample.zip", "sample.7z", "sample.tar.gz"):
        entries = engine.list_archive(SAMPLES / name)
        files = [e for e in entries if not e.is_dir]
        check(f"list {name}", len(files) >= 3, f"got {len(files)} files")

    print("== 解压（无密码）==")
    expect = payload_snapshot()
    for name in ("sample.zip", "sample.7z", "sample.tar", "sample.tar.gz", "sample.tar.xz"):
        out = WORK / ("out_" + name.replace(".", "_"))
        job = run_extract(SAMPLES / name, out)
        check(f"extract {name}", job.state is JobState.SUCCESS, str(job.error_msg))
        if job.state is JobState.SUCCESS:
            got = snapshot(out)
            check(f"  内容一致 {name}", got == expect,
                  f"files: {sorted(got)[:5]}...")

    rar = SAMPLES / "sample.rar"
    if rar.exists():
        job = run_extract(rar, WORK / "out_rar")
        check("extract sample.rar", job.state is JobState.SUCCESS, str(job.error_msg))

    print("== 加密压缩包 ==")
    # 正确密码直接传入
    job = run_extract(SAMPLES / "sample_enc.7z", WORK / "out_enc7z", password="1234")
    check("extract sample_enc.7z (密码参数)", job.state is JobState.SUCCESS, str(job.error_msg))

    # 交互式密码流程：无缓存 → 触发 passwordNeeded → 提供密码
    engine.PASSWORD_CACHE.clear()
    job = ArchiveJob(JobType.EXTRACT, SAMPLES / "sample_enc.zip", out_dir=WORK / "out_enczip")
    asked = []
    job.passwordNeeded.connect(lambda retry: asked.append(retry))
    mgr = TaskManager()
    mgr.passwordNeeded.connect(lambda j, retry: j.provide_password("1234", retry))
    mgr.enqueue([job])
    wait_signal(mgr.allFinished)
    check("extract sample_enc.zip (交互密码)", job.state is JobState.SUCCESS, str(job.error_msg))
    check("  触发过密码询问", len(asked) >= 1)

    # 错误密码 → 重问 → 正确
    engine.PASSWORD_CACHE.clear()
    job = ArchiveJob(JobType.EXTRACT, SAMPLES / "sample_enc.7z", out_dir=WORK / "out_enc7z2")
    mgr = TaskManager()
    mgr.passwordNeeded.connect(
        lambda j, retry: j.provide_password("错误密码" if not retry else "1234", retry))
    mgr.enqueue([job])
    wait_signal(mgr.allFinished)
    check("错误密码后重试成功", job.state is JobState.SUCCESS, str(job.error_msg))

    print("== 压缩 round-trip ==")
    sources = [str(p) for p in sorted((ROOT / "tests" / "_payload").iterdir())]
    for key in ("7z", "zip", "tar", "tgz", "txz"):
        fmt = CREATE_FORMAT_MAP[key]
        arc = WORK / ("c_" + key + fmt.ext)
        job = run_compress(arc, sources, fmt)
        check(f"compress {key}", job.state is JobState.SUCCESS and arc.exists(),
              str(job.error_msg))
        if arc.exists():
            out = WORK / ("rt_" + key)
            ex = run_extract(arc, out)
            got = snapshot(out)
            check(f"  round-trip {key}",
                  ex.state is JobState.SUCCESS and got == expect,
                  f"{sorted(got)[:5]}...")

    print("== 加密压缩 ==")
    fmt = CREATE_FORMAT_MAP["7z"]
    arc = WORK / "c_enc.7z"
    job = run_compress(arc, sources, fmt, password="abc123")
    check("compress 7z 加密", job.state is JobState.SUCCESS, str(job.error_msg))
    entries = engine.list_archive(arc)  # -mhe 未开，文件名可读
    check("  加密包可列出", len(entries) >= 3)
    if "Encrypted = +" in " ".join(e.attr for e in entries) or True:
        # 用正确/错误密码验证
        ok_job = run_extract(arc, WORK / "rt_enc", password="abc123")
        check("  加密包正确密码解压", ok_job.state is JobState.SUCCESS, str(ok_job.error_msg))

    zip_fmt = CREATE_FORMAT_MAP["zip"]
    zarc = WORK / "c_enc.zip"
    job = run_compress(zarc, sources, zip_fmt, password="abc123")
    check("compress zip 加密(AES256)", job.state is JobState.SUCCESS, str(job.error_msg))
    zjob = run_extract(zarc, WORK / "rt_enczip", password="abc123")
    check("  zip 加密包解压", zjob.state is JobState.SUCCESS, str(zjob.error_msg))

    print("== 分卷 ==")
    big = SAMPLES / "_big.bin"
    arc = WORK / "c_vol.7z"
    job = run_compress(arc, [str(big)], fmt, level=0, volume="1m")
    parts = sorted(WORK.glob("c_vol.7z.*"))
    check("compress 分卷", job.state is JobState.SUCCESS and len(parts) >= 2,
          f"{len(parts)} parts")
    if len(parts) >= 2:
        vjob = run_extract(WORK / "c_vol.7z.001", WORK / "rt_vol")
        check("  分卷解压", vjob.state is JobState.SUCCESS
              and (WORK / "rt_vol" / "_big.bin").read_bytes() == big.read_bytes(),
              str(vjob.error_msg))

    print("== 取消 ==")
    # 30MB 随机数据 xz 压缩耗时数秒，保证能在完成前取消
    big_cancel = WORK / "_cancel_src.bin"
    big_cancel.write_bytes(os.urandom(30 * 1024 * 1024))
    fmt_xz = CREATE_FORMAT_MAP["txz"]
    job = ArchiveJob(JobType.COMPRESS, WORK / "c_cancel.tar.xz",
                     sources=[str(big_cancel)], fmt=fmt_xz, level=9)
    fin = []
    job.finished.connect(lambda ok, msg: fin.append((ok, msg)))
    job.start()
    QTimer.singleShot(400, job.cancel)
    deadline = time.time() + 30
    while job.state not in (JobState.CANCELLED, JobState.SUCCESS, JobState.FAILED) and time.time() < deadline:
        app.processEvents()
    check("取消任务", job.state is JobState.CANCELLED, str(job.state))
    big_cancel.unlink(missing_ok=True)

    print(f"\n结果：{len(PASS)} 通过，{len(FAIL)} 失败")
    if FAIL:
        print("失败项：", *FAIL, sep="\n  - ")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
