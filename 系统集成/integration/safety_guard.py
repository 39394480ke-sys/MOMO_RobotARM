"""真实模式安全门。"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

from .calibration_checker import CalibrationChecker
from .config_loader import INTEGRATION_DIR, resolve_path
from .dependency_checker import DependencyChecker
from .health_checker import HealthChecker
from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import real_confirm_matches, real_confirm_required, real_confirm_text  # noqa: E402
from 通用_io import read_json_object_or_default, read_structured  # noqa: E402


class SafetyGuard:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.base_dir = Path(config.get("_base_dir", INTEGRATION_DIR)).resolve()

    def check_real_mode_allowed(self, confirm_text: str = "", require_web_api: bool = True) -> dict[str, Any]:
        errors: list[str] = []
        expected = real_confirm_text(self.config, "confirm_text", "real_confirm_text")
        if real_confirm_required(self.config) and not real_confirm_matches(self.config, confirm_text, "confirm_text", "real_confirm_text"):
            errors.append(f"真实模式需要输入确认文本：{expected}")
        calibration = CalibrationChecker(self.config).check()
        if not calibration.get("ok"):
            errors.append("标定文件不完整，不能进入真实模式。")
        real_deps = DependencyChecker(self.config).check_real_hardware_dependencies()
        missing_deps = [name for name, ok in real_deps.items() if not ok]
        if missing_deps:
            errors.append(f"真实硬件依赖缺失：{', '.join(missing_deps)}")
        if require_web_api:
            web_health = HealthChecker._get_json("http://127.0.0.1:8010/api/v1/health")[0]
            if not web_health:
                errors.append("Web API 未启动，真实硬件只能由阶段八控制服务统一持有。")
        dry_run_error = self._check_real_config_dry_run_disabled()
        if dry_run_error:
            errors.append(dry_run_error)
        session_error = self._check_hardware_session()
        if session_error:
            errors.append(session_error)
        serial_error = self._check_serial_port()
        if serial_error:
            errors.append(serial_error)
        return {
            "ok": not errors,
            "errors": errors,
            "calibration": calibration,
            "real_dependencies": real_deps,
        }

    def _check_real_config_dry_run_disabled(self) -> str:
        real_config_path = resolve_path(self.config.get("hardware", {}).get("real_config_path", "../真实舵机控制/真实配置.yaml"), self.base_dir)
        if not real_config_path.exists():
            return f"真实配置不存在：{real_config_path}"
        try:
            data = read_structured(real_config_path)
        except Exception as exc:
            return f"真实配置无法解析：{exc}"
        if bool((data.get("transport") or {}).get("dry_run", True)):
            return "真实配置 transport.dry_run 仍为 true，不能进入 real。"
        return ""

    def _check_hardware_session(self) -> str:
        if not self.config.get("safety", {}).get("prevent_multiple_hardware_sessions", True):
            return ""
        runtime_path = (self.base_dir / "../真实舵机控制/硬件状态记录_runtime_state.json").resolve()
        if not runtime_path.exists():
            return ""
        data = read_json_object_or_default(runtime_path)
        if not data:
            return ""
        connected = bool(data.get("connected") or data.get("已连接"))
        mode = str(data.get("mode") or data.get("模式") or "")
        owner = str(data.get("owner") or data.get("持有者") or "")
        if connected and mode == "real" and owner and owner != "web_api":
            return f"检测到其他硬件会话正在持有真实舵机：{owner}"
        return ""

    def _check_serial_port(self) -> str:
        real_config_path = resolve_path(self.config.get("hardware", {}).get("real_config_path", "../真实舵机控制/真实配置.yaml"), self.base_dir)
        if not real_config_path.exists():
            return ""
        try:
            data = read_structured(real_config_path)
        except Exception:
            return ""
        port = str((data.get("transport") or {}).get("port") or "")
        if not port:
            return "真实配置缺少串口 port。"
        if not Path(port).exists():
            return f"串口不存在：{port}"
        try:
            output = subprocess.run(["lsof", "-t", port], capture_output=True, text=True, timeout=2)
        except Exception:
            return ""
        pids = [item for item in output.stdout.splitlines() if item.strip() and item.strip() != str(os.getpid())]
        if pids:
            return f"串口可能已被其他进程占用：{port}，PID={', '.join(pids)}"
        return ""
