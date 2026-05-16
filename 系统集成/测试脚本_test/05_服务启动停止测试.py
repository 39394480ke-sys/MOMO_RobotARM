from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from integration.config_loader import load_config
from integration.process_manager import ProcessManager


def main() -> int:
    config = load_config()
    config["services"]["vision"]["enabled"] = False
    manager = ProcessManager(config)
    result = manager.start_service("web_api")
    assert result["ok"], result
    time.sleep(1.0)
    status = manager.status_service("web_api")
    assert status["running"], status
    assert Path(status["pid_file"]).exists(), status
    stop_result = manager.stop_service("web_api")
    assert stop_result["ok"], stop_result
    assert not Path(status["pid_file"]).exists(), status
    print("服务启动停止测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

