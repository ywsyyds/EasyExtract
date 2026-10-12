"""GUI 冒烟测试：渲染主窗口各页面并截图，模拟端到端解压/压缩操作。

用法：py scripts/gui_smoke.py
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from app.ui.main_window import MainWindow
from app.ui.password_dialog import PasswordDialog

ROOT = Path(__file__).resolve().parent.parent
SHOTS = ROOT / "tests" / "_shots"
SAMPLES = ROOT / "tests" / "samples"
OUT = ROOT / "tests" / "_smoke_out"


def snap(widget, name: str) -> None:
    SHOTS.mkdir(parents=True, exist_ok=True)
    widget.grab().save(str(SHOTS / f"{name}.png"))
    print(f"saved {name}.png")


def main() -> int:
    app = QApplication(sys.argv)
    win = MainWindow()
    win.show()
    results: list[str] = []
    states: list[str] = []

    if OUT.exists():
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)

    # 自动应答密码对话框（enc.7z 触发），记录调用
    asks = []
    PasswordDialog.ask = staticmethod(
        lambda name, retry=False, parent=None: (asks.append(name), "1234")[1])

    def step1():
        snap(win, "1_extract_page")
        win.page_extract.add_archives([
            str(SAMPLES / "sample.zip"),
            str(SAMPLES / "sample.7z"),
            str(SAMPLES / "sample.tar.gz"),
            str(SAMPLES / "sample.rar"),
            str(SAMPLES / "sample_enc.7z"),
        ])

    def step2():
        snap(win, "2_extract_added")
        win.page_extract.btn_start.click()

    def step3():
        if win.manager.busy():
            QTimer.singleShot(500, step3)
            return
        snap(win, "3_extract_done")
        states[:] = [win.page_extract.tree.topLevelItem(i).text(4)
                     for i in range(win.page_extract.tree.topLevelItemCount())]
        results.append("extract states: " + " | ".join(states))
        results.append(f"password asked: {len(asks)} times")

        win.page_extract._clear()
        win.btn_compress.click()
        win.page_compress.add_paths([
            str(ROOT / "tests" / "_payload" / "readme.md"),
            str(ROOT / "tests" / "_payload" / "文档"),
        ])
        win.page_compress.edit_outdir.setText(str(OUT))
        win.page_compress.edit_name.setText("smoke_test.7z")
        win.page_compress.edit_pwd.setText("smoke123")
        win.page_compress._name_dirty = True
        QTimer.singleShot(200, step4)

    def step4():
        snap(win, "4_compress_page")
        win.page_compress.btn_start.click()
        QTimer.singleShot(400, step5)

    def step5():
        if win.manager.busy():
            QTimer.singleShot(400, step5)
            return
        snap(win, "5_compress_done")
        results.append("compress state: " + win.page_compress.label_state.text())
        arc = OUT / "smoke_test.7z"
        results.append(f"archive exists: {arc.exists()}")
        extract_states_ok = all("完成" in s for s in states) if states else False
        print("\n".join(results))
        ok = (extract_states_ok and arc.exists()
              and "压缩完成" in win.page_compress.label_state.text())
        print("GUI SMOKE " + ("OK" if ok else "FAILED"))
        app.quit()

    QTimer.singleShot(400, step1)
    QTimer.singleShot(900, step2)
    QTimer.singleShot(2500, step3)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
