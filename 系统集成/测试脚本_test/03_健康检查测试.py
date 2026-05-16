from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from integration.config_loader import load_config
from integration.health_checker import HealthChecker


def main() -> int:
    result = HealthChecker(load_config()).check()
    assert "ok" in result
    assert "services" in result
    assert "errors" in result
    print("健康检查测试通过。服务未启动时允许返回失败，但程序不能崩溃。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

