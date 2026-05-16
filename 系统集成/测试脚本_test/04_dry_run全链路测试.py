from __future__ import annotations

import sys
import time
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from integration.config_loader import load_config
from integration.health_checker import HealthChecker
from integration.process_manager import ProcessManager


def wait_health(url: str, timeout: float = 30.0) -> None:
    deadline = time.time() + timeout
    last = ""
    while time.time() < deadline:
        ok, data = HealthChecker._get_json(url)
        if ok:
            return
        last = str(data)
        time.sleep(1.0)
    raise AssertionError(f"health 超时：{last}")


def main() -> int:
    import requests

    config = load_config()
    config["services"]["vision"]["enabled"] = False
    manager = ProcessManager(config)
    try:
        result = manager.start_service("web_api")
        assert result["ok"], result
        wait_health("http://127.0.0.1:8010/api/v1/health")
        resp = requests.post("http://127.0.0.1:8010/api/v1/session/connect", json={"mode": "dry_run", "confirm_text": ""}, timeout=10)
        assert resp.status_code == 200, resp.text
        state_resp = requests.get("http://127.0.0.1:8010/api/v1/robot/state", timeout=10)
        assert state_resp.status_code == 200, state_resp.text
        stop_resp = requests.post("http://127.0.0.1:8010/api/v1/motion/stop", timeout=10)
        assert stop_resp.status_code == 200, stop_resp.text
        print("dry_run 全链路测试通过。")
        return 0
    finally:
        manager.stop_service("web_api")


if __name__ == "__main__":
    raise SystemExit(main())

