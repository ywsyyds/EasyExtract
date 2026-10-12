"""生成测试用压缩包样本到 tests/samples/。

用法：py scripts/make_samples.py
"""
from __future__ import annotations

import io
import os
import random
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SEVENZ = str(ROOT / "app" / "bin" / "7z.exe")
SAMPLES = ROOT / "tests" / "samples"
PAYLOAD = ROOT / "tests" / "_payload"

PASSWORD = "1234"


def build_payload() -> None:
    """构造待压缩的原始文件：中文文件名 + 嵌套目录 + 二进制数据。"""
    (PAYLOAD / "文档").mkdir(parents=True, exist_ok=True)
    (PAYLOAD / "data").mkdir(parents=True, exist_ok=True)
    (PAYLOAD / "文档" / "说明.txt").write_text(
        "这是一个测试文件。\nEasyExtract 解压测试，包含中文内容。\n" * 20, encoding="utf-8")
    (PAYLOAD / "data" / "binary.bin").write_bytes(bytes(random.Random(42).randrange(256) for _ in range(300_000)))
    (PAYLOAD / "readme.md").write_text("# 测试数据包\n\n用于自动化验证。\n", encoding="utf-8")


def _sources() -> list[str]:
    return [str(p) for p in sorted(PAYLOAD.iterdir())]


def make_zip() -> None:
    with zipfile.ZipFile(SAMPLES / "sample.zip", "w", zipfile.ZIP_DEFLATED) as zf:
        for p in PAYLOAD.rglob("*"):
            zf.write(p, p.relative_to(PAYLOAD))


def _7z(args: list[str]) -> None:
    r = subprocess.run([SEVENZ, *args], capture_output=True, text=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"7z {' '.join(args[:6])}... 失败: {r.stdout[-500:]}")


def make_7z() -> None:
    _7z(["a", "-y", "-t7z", str(SAMPLES / "sample.7z"), *_sources()])


def make_encrypted() -> None:
    _7z(["a", "-y", "-t7z", "-mhe=on", f"-p{PASSWORD}",
         str(SAMPLES / "sample_enc.7z"), *_sources()])
    _7z(["a", "-y", "-tzip", f"-p{PASSWORD}", "-mem=AES256",
         str(SAMPLES / "sample_enc.zip"), *_sources()])


def make_tars() -> None:
    import tarfile
    for name, mode in (("sample.tar", "w"), ("sample.tar.gz", "w:gz"), ("sample.tar.xz", "w:xz")):
        with tarfile.open(SAMPLES / name, mode) as tf:
            for p in sorted(PAYLOAD.rglob("*")):
                tf.add(p, arcname=p.relative_to(PAYLOAD))


def make_big() -> None:
    """供分卷测试用的大文件。"""
    data = bytes(random.Random(7).randrange(256) for _ in range(1024)) * 3072  # ~3 MB
    (SAMPLES / "_big.bin").write_bytes(data)


def make_rar() -> bool:
    """下载公开的 rar 测试样本（尽力而为，失败则跳过）。"""
    target = SAMPLES / "sample.rar"
    if target.exists():
        return True
    import urllib.request
    import zipfile as zf2

    proxies = [
        "https://ghfast.top/",
        "https://gh-proxy.com/",
        "",
    ]
    url = "https://github.com/markokr/rarfile/archive/refs/heads/master.zip"
    for prefix in proxies:
        try:
            data = urllib.request.urlopen(prefix + url, timeout=60).read()
            with zf2.ZipFile(io.BytesIO(data)) as z:
                rars = [n for n in z.namelist() if n.lower().endswith(".rar")]
                # 优先取较小的 rar5 样本
                rars.sort(key=lambda n: (5 if "rar5" in n.lower() or "5." in Path(n).name else 0,
                                         z.getinfo(n).file_size))
                if rars:
                    with z.open(rars[0]) as src, open(target, "wb") as dst:
                        dst.write(src.read())
                    return True
        except Exception:
            continue
    return False


def main() -> None:
    SAMPLES.mkdir(parents=True, exist_ok=True)
    build_payload()
    make_zip()
    make_7z()
    make_encrypted()
    make_tars()
    make_big()
    ok = make_rar()
    print("samples:")
    for f in sorted(SAMPLES.iterdir()):
        print(f"  {f.name}  {f.stat().st_size:,} B")
    print("rar sample:", "ok" if ok else "skipped (download failed)")


if __name__ == "__main__":
    sys.exit(main())
