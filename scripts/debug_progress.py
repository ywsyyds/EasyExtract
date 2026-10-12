"""验证：大文件压缩/解压时 7z -bsp1 经 QProcess 管道是否输出百分比进度。"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QTimer

from app.core import engine
from app.core.engine import ArchiveJob, JobState, JobType
from app.core.formats import CREATE_FORMAT_MAP

ROOT = Path(__file__).resolve().parent.parent
WORK = ROOT / "tests" / "_work"
BIG = WORK / "_progress_big.bin"


def main() -> int:
    app = QCoreApplication(sys.argv)
    WORK.mkdir(parents=True, exist_ok=True)

    # 200MB 随机数据，压缩需要数秒
    if not BIG.exists() or BIG.stat().st_size != 200 * 1024 * 1024:
        import os
        chunk = os.urandom(1024 * 1024)
        with open(BIG, "wb") as f:
            for _ in range(200):
                f.write(chunk)

    updates = []

    job = ArchiveJob(JobType.COMPRESS, WORK / "_progress_big.7z",
                     sources=[str(BIG)], fmt=CREATE_FORMAT_MAP["7z"], level=1)
    job.progressed.connect(lambda pct, name: updates.append((time.time(), pct, name)))

    fin = []
    job.finished.connect(lambda ok, msg: fin.append((ok, msg)))
    job.start()

    def done():
        if job.state in (JobState.SUCCESS, JobState.FAILED, JobState.CANCELLED):
            ok, msg = fin[0] if fin else (None, "?")
            print("state:", job.state, "msg:", msg)
            print(f"progress updates received: {len(updates)}")
            for t, pct, name in updates[::max(1, len(updates) // 10)]:
                print(f"  {pct:3d}%  {name[:50]}")
            app.quit()

    timer = QTimer()
    timer.timeout.connect(done)
    timer.start(300)
    QTimer.singleShot(300_000, app.quit)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
