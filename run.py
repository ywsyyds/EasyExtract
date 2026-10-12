"""易解压 EasyExtract 启动器（开发运行入口）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.main import main

if __name__ == "__main__":
    sys.exit(main())
