"""进度显示端到端测试：大文件下验证 GUI 进度条/百分比/耗时提示真实更新。

用法：py scripts/gui_progress_test.py
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "tests" / "_work"
BIG = WORK / "_progress_big.bin"
BIG7Z = WORK / "_progress_big.7z"
MANY7Z = WORK / "_many_files.7z"
OUT = WORK / "_progress_out"


def ensure_big_files() -> None:
    if not BIG.exists() or BIG.stat().st_size != 200 * 1024 * 1024:
        chunk = os.urandom(1024 * 1024)
        with open(BIG, "wb") as f:
            for _ in range(200):
                f.write(chunk)
    if not BIG7Z.exists():
        from PySide6.QtCore import QCoreApplication
        _ = QCoreApplication.instance()
        from app.core.engine import ArchiveJob, JobType
        from app.core.formats import CREATE_FORMAT_MAP
        job = ArchiveJob(JobType.COMPRESS, BIG7Z, sources=[str(BIG)],
                         fmt=CREATE_FORMAT_MAP["7z"], level=1)
        fin: list[bool] = []
        job.finished.connect(lambda ok, msg: fin.append(True))
        job.start()
        app = QApplication.instance()
        while not fin:
            app.processEvents()
    # 海量小文件压缩包：解压耗时长，便于观测进度
    if not MANY7Z.exists():
        import subprocess
        many_dir = WORK / "_many"
        if not many_dir.exists():
            many_dir.mkdir(parents=True)
            chunk = os.urandom(100 * 1024)
            for i in range(2000):
                (many_dir / f"f{i:05d}.dat").write_bytes(chunk)
        r = subprocess.run([str(ROOT / "app" / "bin" / "7z.exe"), "a", "-y", "-t7z",
                            "-mx=0", str(MANY7Z), str(many_dir) + "\\*"],
                           capture_output=True, text=True)
        assert r.returncode in (0, 1), r.stdout[-300:]
        shutil.rmtree(many_dir, ignore_errors=True)


def main() -> int:
    app = QApplication(sys.argv)
    ensure_big_files()
    win = MainWindow()
    win.resize(920, 620)
    win.show()

    ext_samples: list[tuple[int, str]] = []
    cmp_samples: list[tuple[int, str]] = []
    results: list[str] = []

    def poll(get_bar, get_label, store):
        store.append((get_bar(), get_label()))

    def poll_ext():
        poll(win.page_extract.bar.value, win.page_extract.label_state.text, ext_samples)

    def poll_cmp():
        poll(win.page_compress.bar.value, win.page_compress.label_state.text, cmp_samples)

    ext_timer = QTimer()
    ext_timer.timeout.connect(poll_ext)
    cmp_timer = QTimer()
    cmp_timer.timeout.connect(poll_cmp)

    def wait_idle_then(callback, interval=200):
        """定时轮询 manager，空闲后停表并回调。"""
        chk = QTimer()

        def check():
            if win.manager.busy():
                return
            chk.stop()
            QTimer.singleShot(150, callback)

        chk.timeout.connect(check)
        chk.start(interval)

    # ---------- 阶段 1：解压海量小文件压缩包（耗时长，可观测） ----------
    def start_extract():
        if OUT.exists():
            shutil.rmtree(OUT, ignore_errors=True)
        win.page_extract.add_archives([str(MANY7Z)])
        win.page_extract.rb_custom.setChecked(True)
        win.page_extract.edit_dst.setText(str(OUT))
        ext_timer.start(200)
        win.page_extract.btn_start.click()
        wait_idle_then(finish_extract)

    def finish_extract():
        mid = [(b, t) for b, t in ext_samples if 0 < b < 100]
        peak = max((b for b, _ in ext_samples), default=0)
        saw_running = any("正在解压" in t for _, t in ext_samples)
        results.append(f"[extract] samples={len(ext_samples)} mid-bar={len(mid)} peak={peak} "
                       f"running-label={saw_running}")
        results.append(f"[extract] mid sample: {mid[0][1][:90] if mid else '(none)'}")
        ok = bool(mid) and saw_running and peak >= 100
        results.append(f"[extract] PASS={ok}")
        globals()["_ok_extract"] = ok

        # ---------- 阶段 2：压缩大文件（标准等级，足够慢以观察剩余时间） ----------
        win.page_extract._clear()
        (WORK / "progress_ui.7z").unlink(missing_ok=True)
        win.btn_compress.click()
        win.page_compress.add_paths([str(BIG)])
        win.page_compress.edit_outdir.setText(str(WORK))
        win.page_compress.edit_name.setText("progress_ui.7z")
        win.page_compress._name_dirty = True
        win.page_compress.cmb_level.setCurrentIndex(2)  # 标准
        cmp_timer.start(300)
        win.page_compress.btn_start.click()
        wait_idle_then(finish_compress)

    def finish_compress():
        mid = [(b, t) for b, t in cmp_samples if 0 < b < 100]
        peak = max((b for b, _ in cmp_samples), default=0)
        saw_running = any("正在压缩" in t for _, t in cmp_samples)
        saw_eta = any("预计剩余" in t for _, t in cmp_samples)
        results.append(f"[compress] samples={len(cmp_samples)} mid-bar={len(mid)} peak={peak} "
                       f"running-label={saw_running} eta-label={saw_eta}")
        results.append(f"[compress] mid sample: {mid[len(mid)//2][1][:90] if mid else '(none)'}")
        ok = len(mid) >= 3 and saw_running and peak >= 100
        results.append(f"[compress] PASS={ok} (eta observed: {saw_eta})")
        results.append("PROGRESS UI TEST " + ("OK" if globals().get("_ok_extract") and ok else "FAILED"))
        print("\n".join(results))
        app.quit()

    QTimer.singleShot(400, start_extract)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
