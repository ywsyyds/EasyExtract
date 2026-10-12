"""调试：观察 7z 对加密压缩包在管道 stdin 下的密码提示行为。"""
import subprocess
import sys
from pathlib import Path

SEVENZ = str(Path(__file__).resolve().parent.parent / "app" / "bin" / "7z.exe")
SAMPLES = Path(__file__).resolve().parent.parent / "tests" / "samples"

print("=== 1. enc.7z (加密头) stdin=EOF ===")
r = subprocess.run([SEVENZ, "x", "-y", f"-o{SAMPLES/'_dbg1'}", str(SAMPLES/"sample_enc.7z")],
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
print("rc:", r.returncode)
print("stderr:", r.stderr[:400])
print("stdout:", r.stdout[:400])

print("\n=== 2. enc.7z stdin 管道喂密码 ===")
r = subprocess.run([SEVENZ, "x", "-y", f"-o{SAMPLES/'_dbg2'}", str(SAMPLES/"sample_enc.7z")],
                   input="1234\n", capture_output=True, text=True, errors="replace")
print("rc:", r.returncode)
print("stderr:", r.stderr[:400])
print("stdout:", r.stdout[:400])

print("\n=== 3. enc.zip (无加密头) stdin=EOF ===")
r = subprocess.run([SEVENZ, "x", "-y", f"-o{SAMPLES/'_dbg3'}", str(SAMPLES/"sample_enc.zip")],
                   stdin=subprocess.DEVNULL, capture_output=True, text=True, errors="replace")
print("rc:", r.returncode)
print("stderr:", r.stderr[:400])
print("stdout:", r.stdout[-600:])

print("\n=== 4. enc.zip stdin 管道喂密码 ===")
r = subprocess.run([SEVENZ, "x", "-y", f"-o{SAMPLES/'_dbg4'}", str(SAMPLES/"sample_enc.zip")],
                   input="1234\n", capture_output=True, text=True, errors="replace")
print("rc:", r.returncode)
print("stderr:", r.stderr[:400])
print("stdout:", r.stdout[-600:])

print("\n=== 5. 嵌套列表 tar.gz# ===")
r = subprocess.run([SEVENZ, "l", "-ba", str(SAMPLES/"sample.tar.gz") + "#" + str(SAMPLES/"sample.tar.gz#sample.tar")],
                   capture_output=True, text=True, errors="replace")
print("rc:", r.returncode, "out:", r.stdout[:300], r.stderr[:200])
