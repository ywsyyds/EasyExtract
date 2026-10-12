"""探查：加密包解压时密码询问触发次数。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QCoreApplication, QTimer

from app.core import engine
from app.core.engine import ArchiveJob, JobType, TaskManager

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "tests" / "samples"


def main() -> int:
    app = QCoreApplication(sys.argv)
    engine.PASSWORD_CACHE.clear()
    asks = []

    job = ArchiveJob(JobType.EXTRACT, SAMPLES / "sample_enc.7z",
                     out_dir=ROOT / "tests" / "_askprobe")
    job.passwordNeeded.connect(lambda retry: asks.append(retry))
    mgr = TaskManager()
    mgr.passwordNeeded.connect(lambda j, retry: (asks.append(("mgr", retry)),
                                                 j.provide_password("1234", retry)))
    mgr.enqueue([job])

    def report():
        print("job state:", job.state)
        print("asks:", asks)
        app.quit()

    QTimer.singleShot(8000, report)
    app.exec()


if __name__ == "__main__":
    sys.exit(main())
