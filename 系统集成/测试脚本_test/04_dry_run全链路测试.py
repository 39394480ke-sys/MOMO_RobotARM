from __future__ import annotations

import time

import 系统测试路径_test_paths  # noqa: F401

from integration.config_loader import load_config
from integration.health_checker import HealthChecker
from integration.process_manager import ProcessManager
from 通用_http import request_json_object


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
    config = load_config()
    config["services"]["vision"]["enabled"] = False
    manager = ProcessManager(config)
    try:
        result = manager.start_service("web_api")
        assert result["ok"], result
        wait_health("http://127.0.0.1:8010/api/v1/health")
        connected = request_json_object(
            "http://127.0.0.1:8010/api/v1/session/connect",
            method="POST",
            payload={"mode": "dry_run", "confirm_text": ""},
            timeout=10,
        )
        assert connected["ok"] is True, connected
        state = request_json_object("http://127.0.0.1:8010/api/v1/robot/state", timeout=10)
        assert state["ok"] is True, state
        stopped = request_json_object("http://127.0.0.1:8010/api/v1/motion/stop", method="POST", timeout=10)
        assert stopped["ok"] is True, stopped
        print("dry_run 全链路测试通过。")
        return 0
    finally:
        manager.stop_service("web_api")


if __name__ == "__main__":
    raise SystemExit(main())
