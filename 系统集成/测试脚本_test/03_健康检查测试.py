from __future__ import annotations

import 系统测试路径_test_paths  # noqa: F401

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
