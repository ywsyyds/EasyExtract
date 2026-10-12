"""压缩格式的识别、展示与命名规则。"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CreateFormat:
    """一种可创建的压缩格式。"""
    key: str              # 内部标识
    label: str            # 界面显示名
    ext: str              # 输出文件扩展名（含点）
    sevenz_type: str      # 传给 7z.exe 的 -t 参数
    two_step: str | None = None   # 两步打包时的外层 -t（tar.gz 等）
    level_max: int = 9
    password: bool = True         # 支持密码
    encrypt_names: bool = False   # 支持加密文件名（-mhe）
    volume: bool = True           # 支持分卷


# 可创建的格式（RAR 为专有格式，任何第三方都无法创建）
CREATE_FORMATS: list[CreateFormat] = [
    CreateFormat("7z",     "7z（推荐，压缩率最高）", ".7z",     "7z",    None,    9, True,  True,  True),
    CreateFormat("zip",    "zip（兼容性最好）",      ".zip",    "zip",   None,    9, True,  False, True),
    CreateFormat("tar",    "tar（仅打包）",          ".tar",    "tar",   None,    0, False, False, False),
    CreateFormat("tgz",    "tar.gz",                 ".tar.gz", "gzip",  "tar",   9, False, False, False),
    CreateFormat("tbz",    "tar.bz2",                ".tar.bz2","bzip2", "tar",   9, False, False, False),
    CreateFormat("txz",    "tar.xz",                 ".tar.xz", "xz",    "tar",   9, False, False, False),
]
CREATE_FORMAT_MAP = {f.key: f for f in CREATE_FORMATS}


# 可解压识别的扩展名（小写、含点）。7z.exe 实际支持更多（msi/wim/iso 等），此处覆盖常见场景。
EXTRACT_EXTS: dict[str, str] = {
    ".zip": "zip", ".7z": "7z", ".rar": "rar",
    ".tar": "tar", ".tgz": "tar.gz", ".tbz": "tar.bz2", ".tbz2": "tar.bz2",
    ".txz": "tar.xz", ".gz": "gzip", ".bz2": "bzip2", ".xz": "xz",
    ".zst": "zstd", ".tzst": "tar.zst",
    ".cab": "cab", ".iso": "iso", ".img": "img", ".udf": "udf",
    ".wim": "wim", ".swm": "swm", ".esd": "esd",
    ".msi": "msi", ".dmg": "dmg", ".jar": "jar", ".apk": "apk",
    ".cpio": "cpio", ".rpm": "rpm", ".deb": "deb", ".vhd": "vhd", ".vhdx": "vhdx",
}
TAR_COMPOUND = (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst")


def archive_format_name(path: str | Path) -> str:
    """返回用于展示的格式名；未知扩展名返回 '未知'。"""
    name = str(path).lower()
    for compound in TAR_COMPOUND:
        if name.endswith(compound):
            return compound[1:]
    ext = Path(name).suffix
    return EXTRACT_EXTS.get(ext, "未知")


def is_archive(path: str | Path) -> bool:
    name = str(path).lower()
    if any(name.endswith(c) for c in TAR_COMPOUND):
        return True
    return Path(name).suffix in EXTRACT_EXTS


def archive_stem(path: str | Path) -> str:
    """去掉压缩包扩展名后的主名（正确处理 .tar.gz 等双扩展名）。"""
    name = Path(path).name
    low = name.lower()
    for suffix in (".tar.gz", ".tar.bz2", ".tar.xz", ".tar.zst"):
        if low.endswith(suffix):
            return name[: -len(suffix)]
    return Path(name).stem


def human_size(n: int | float) -> str:
    size = float(n)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"


def human_duration(seconds: float) -> str:
    """秒数 → '1 分 23 秒' / '23 秒' / '1 时 02 分'。"""
    seconds = int(max(0, seconds))
    if seconds >= 3600:
        return f"{seconds // 3600} 时 {seconds % 3600 // 60:02d} 分"
    if seconds >= 60:
        return f"{seconds // 60} 分 {seconds % 60:02d} 秒"
    return f"{seconds} 秒"


def unique_target_dir(base: Path) -> Path:
    """base 目录已存在时追加 ' (2)'、' (3)' ……"""
    if not base.exists():
        return base
    i = 2
    while True:
        cand = base.with_name(f"{base.name} ({i})")
        if not cand.exists():
            return cand
        i += 1


def default_extract_dir(archive: str | Path, into_subfolder: bool) -> Path:
    """解压目标目录：默认为压缩包同目录下的同名文件夹。"""
    p = Path(archive)
    if not into_subfolder:
        return p.parent
    return unique_target_dir(p.parent / archive_stem(p))


def suggested_archive_path(sources: list[str], fmt: CreateFormat) -> Path:
    """根据所选文件建议输出压缩包路径：取公共父目录下以首个对象命名。"""
    if not sources:
        return Path.cwd() / ("新建压缩包" + fmt.ext)
    first = Path(sources[0])
    parent = first.parent
    if len(sources) > 1:
        try:
            parent = Path(os.path.commonpath([str(Path(s).absolute()) for s in sources]))
        except ValueError:
            pass
    name = first.stem if len(sources) > 1 else first.name
    target = parent / (name + fmt.ext)
    i = 2
    while target.exists():
        target = parent / (f"{name} ({i})" + fmt.ext)
        i += 1
    return target
