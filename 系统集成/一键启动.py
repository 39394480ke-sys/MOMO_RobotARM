"""阶段十一一键启动器。"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

from integration.calibration_checker import CalibrationChecker
from integration.config_loader import load_config
from integration.dependency_checker import DependencyChecker
from integration.health_checker import HealthChecker
from integration.log_manager import LogManager
from integration.mode_manager import ModeManager
from integration.process_manager import ProcessManager
from integration.runtime_state import RuntimeState


WEB_BASE = "http://127.0.0.1:8010"
VISION_BASE = "http://127.0.0.1:8000"


def main() -> int:
    parser = argparse.ArgumentParser(description="阶段十一：统一启动器")
    parser.add_argument("--mode", choices=["sim", "dry_run", "real"], default=None)
    parser.add_argument("--with-gui", action="store_true")
    parser.add_argument("--with-agent", action="store_true")
    parser.add_argument("--no-vision", action="store_true")
    parser.add_argument("--confirm-text", default="")
    args = parser.parse_args()

    config = load_config()
    mode = args.mode or config.get("project", {}).get("default_mode", "dry_run")
    _apply_service_flags(config, with_gui=args.with_gui, with_agent=args.with_agent, no_vision=args.no_vision)
    log = LogManager(config)
    state = RuntimeState(config)
    process_manager = ProcessManager(config)

    state.update(started_at=time.strftime("%Y-%m-%dT%H:%M:%S%z"), last_error="")
    log.log_info("startup_begin", "系统集成启动流程开始。", mode=mode)

    if not _check_python(config):
        return 1

    deps = DependencyChecker(config).check_all()
    if not deps["required_ok"]:
        missing = [name for name, ok in deps["required"].items() if not ok]
        print(f"必需依赖缺失：{', '.join(missing)}")
        print("请运行：bash scripts/bootstrap.sh")
        state.set_error(f"必需依赖缺失：{', '.join(missing)}")
        return 1

    calibration = CalibrationChecker(config).check()
    if not calibration["ok"]:
        print("标定检查未通过。dry_run/sim 可继续，real 不允许。")
        print("请运行：python ../真实舵机控制/标定程序_calibrate.py")
        if mode == "real":
            state.set_error("real 模式需要完整标定。")
            return 1

    confirm_text = args.confirm_text
    if mode == "real" and not confirm_text:
        confirm_text = input("请输入真实模式确认文本：").strip()

    if mode == "real":
        print("先启动 Web API，再通过统一 Web 控制服务进入 real。")
        result = process_manager.start_service("web_api")
        if not result.get("ok"):
            print(result.get("message"))
            return 1
        if not _wait_health("web_api", f"{WEB_BASE}/api/v1/health"):
            print("Web API health 未通过，请查看 runtime/logs/web.log")
            return 1
        mode_result = ModeManager(config).set_mode("real", confirm_text=confirm_text, require_web_api_for_real=True)
        if not mode_result.get("ok"):
            print("真实模式安全检查失败：")
            for error in mode_result.get("errors", []):
                print(f"- {error}")
            return 1
    else:
        mode_result = ModeManager(config).set_mode(mode)
        if not mode_result.get("ok"):
            print(json.dumps(mode_result, ensure_ascii=False, indent=2))
            return 1
        result = process_manager.start_service("web_api")
        if not result.get("ok"):
            print(result.get("message"))
            return 1
        if not _wait_health("web_api", f"{WEB_BASE}/api/v1/health"):
            print("Web API health 未通过，请查看 runtime/logs/web.log")
            return 1

    _set_web_mode(mode, confirm_text)

    if not args.no_vision and config["services"]["vision"].get("enabled", True):
        result = process_manager.start_service("vision")
        if not result.get("ok"):
            print(result.get("message"))
            return 1
        if not _wait_health("vision", f"{VISION_BASE}/health"):
            print("Vision health 未通过，请查看 runtime/logs/vision.log")
            return 1

    if args.with_agent:
        process_manager.start_service("agent")
    if args.with_gui:
        process_manager.start_service("gui")

    health = HealthChecker(config).check()
    log.log_info("startup_done", "系统集成启动流程完成。", mode=mode, health_ok=health.get("ok"))
    print("")
    print(f"Web 控制台：{WEB_BASE}/web/")
    print(f"视觉服务：{VISION_BASE}/latest")
    print(f"当前模式：{ModeManager(config).get_mode()}")
    if not health.get("ok"):
        print("健康检查存在告警，可运行：python 健康检查.py")
    return 0


def _apply_service_flags(config: dict[str, Any], with_gui: bool, with_agent: bool, no_vision: bool) -> None:
    if with_gui:
        config["services"]["gui"]["enabled"] = True
    if with_agent:
        config["services"]["agent"]["enabled"] = True
    if no_vision:
        config["services"]["vision"]["enabled"] = False


def _check_python(config: dict[str, Any]) -> bool:
    expected = str(config.get("project", {}).get("python_version", "3.11"))
    actual = f"{sys.version_info.major}.{sys.version_info.minor}"
    if not actual.startswith(expected):
        print(f"Python 版本不匹配：需要 {expected}，当前 {sys.version.split()[0]}")
        return False
    return True


def _wait_health(name: str, url: str, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    last_error = ""
    while time.time() < deadline:
        ok, data = HealthChecker._get_json(url, timeout=2.0)
        if ok:
            return True
        last_error = str(data)
        time.sleep(1.0)
    print(f"{name} health 超时：{last_error}")
    return False


def _set_web_mode(mode: str, confirm_text: str) -> None:
    try:
        import requests

        requests.post(f"{WEB_BASE}/api/v1/session/mode", json={"mode": mode, "confirm_text": confirm_text}, timeout=5)
    except Exception:
        pass


if __name__ == "__main__":
    raise SystemExit(main())

