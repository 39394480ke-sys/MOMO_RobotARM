"""只启动 GUI，不连接真实硬件。"""

from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from GUI主程序_main import main


if __name__ == "__main__":
    raise SystemExit(main())

