"""显示当前系统状态。"""

from __future__ import annotations

from integration.calibration_checker import CalibrationChecker
from integration.config_loader import load_config
from integration.dependency_checker import DependencyChecker
from integration.health_checker import HealthChecker
from integration.process_manager import ProcessManager
from integration.runtime_state import RuntimeState
from integration.service_registry import ServiceRegistry


def main() -> int:
    config = load_config()
    state = RuntimeState(config).load()
    pm = ProcessManager(config)
    registry = ServiceRegistry(config)
    health = HealthChecker(config).check()
    deps = DependencyChecker(config).check_all()
    calibration = CalibrationChecker(config).check()

    print(f"当前模式：{state.get('mode', 'dry_run')}")
    print("服务运行状态：")
    for service in registry.all():
        status = pm.status_service(service.name)
        healthy = health.get("services", {}).get(service.name, {}).get("healthy")
        print(f"- {service.name}: enabled={service.enabled} running={status['running']} pid={status['pid']} healthy={healthy}")
    print(f"Web API health：{health.get('services', {}).get('web_api', {}).get('healthy')}")
    print(f"Vision health：{health.get('services', {}).get('vision', {}).get('healthy')}")
    print(f"标定状态：{calibration.get('ok')} ({calibration.get('path')})")
    print(f"依赖状态：required_ok={deps.get('required_ok')} real_mode_ready={deps.get('real_mode_ready')}")
    print("Web 地址：http://127.0.0.1:8010/web/")
    print(f"最近错误：{state.get('last_error') or '无'}")
    return 0 if health.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())

