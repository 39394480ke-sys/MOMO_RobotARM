"""只启动 GUI，不连接真实硬件。"""

from __future__ import annotations

import GUI测试路径_test_paths  # noqa: F401

from GUI主程序_main import main


if __name__ == "__main__":
    raise SystemExit(main())
