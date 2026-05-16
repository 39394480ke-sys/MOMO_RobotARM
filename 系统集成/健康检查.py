"""运行完整健康检查。"""

from __future__ import annotations

import json

from integration.config_loader import load_config
from integration.health_checker import HealthChecker


def main() -> int:
    result = HealthChecker(load_config()).check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

