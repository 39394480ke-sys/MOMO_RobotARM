"""停止所有由系统集成启动的服务。"""

from __future__ import annotations

import json

from integration.config_loader import load_config
from integration.log_manager import LogManager
from integration.process_manager import ProcessManager


def main() -> int:
    config = load_config()
    results = ProcessManager(config).stop_all()
    LogManager(config).log_info("stop_all", "所有集成服务停止流程完成。", results=results)
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

