"""服务进程管理。"""

from __future__ import annotations

import os
import shlex
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .path_utils import ensure_project_root_on_path
from .path_utils import INTEGRATION_DIR, PROJECT_ROOT

ensure_project_root_on_path()

from 通用_io import read_env_values, read_text, write_text

from .log_manager import LogManager
from .runtime_state import RuntimeState
from .service_registry import ServiceDefinition, ServiceRegistry


class ProcessManager:
    def __init__(self, config: dict[str, Any]):
        self.config = config
        self.registry = ServiceRegistry(config)
        self.log_manager = LogManager(config)
        self.state = RuntimeState(config)

    def start_service(self, service_name: str) -> dict[str, Any]:
        service = self.registry.get(service_name)
        if not service.enabled:
            msg = f"服务未启用：{service_name}"
            self.log_manager.log_warning("start_service_skipped", msg, service=service_name)
            return self._result(False, service_name, msg)
        existing = self.status_service(service_name)
        if existing["running"]:
            return self._result(True, service_name, "服务已在运行。", pid=existing["pid"])
        if not service.cwd.exists():
            msg = f"服务工作目录不存在：{service.cwd}"
            self.log_manager.log_error("start_service_failed", msg, service=service_name)
            self.state.set_error(msg)
            return self._result(False, service_name, msg)
        service.log_file.parent.mkdir(parents=True, exist_ok=True)
        service.pid_file.parent.mkdir(parents=True, exist_ok=True)
        cmd = self._normalize_command(service.command)
        log_fh = service.log_file.open("a", encoding="utf-8")
        try:
            process = subprocess.Popen(
                cmd,
                cwd=str(service.cwd),
                stdout=log_fh,
                stderr=subprocess.STDOUT,
                env={**read_env_values((PROJECT_ROOT / ".env", INTEGRATION_DIR / "环境变量.env")), **os.environ, "PYTHONUNBUFFERED": "1"},
                start_new_session=True,
            )
        except Exception as exc:
            log_fh.close()
            msg = f"启动服务失败：{service_name}：{exc}"
            self.log_manager.log_error("start_service_failed", msg, service=service_name)
            self.state.set_error(msg)
            return self._result(False, service_name, msg)
        write_text(service.pid_file, str(process.pid))
        self.log_manager.log_info("start_service", "服务已启动。", service=service_name, pid=process.pid, command=service.command)
        self.state.update_service(service_name, pid=process.pid, running=True, started_at=time.time(), log_file=str(service.log_file))
        return self._result(True, service_name, "服务已启动。", pid=process.pid)

    def stop_service(self, service_name: str) -> dict[str, Any]:
        service = self.registry.get(service_name)
        status = self.status_service(service_name)
        pid = status.get("pid")
        if not pid or not status["running"]:
            self._cleanup_pid_file(service)
            self.state.update_service(service_name, pid=None, running=False, stopped_at=time.time())
            return self._result(True, service_name, "服务未运行。")
        try:
            os.killpg(pid, signal.SIGTERM)
        except ProcessLookupError:
            self._cleanup_pid_file(service)
            return self._result(True, service_name, "进程已不存在。")
        except Exception:
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if not self._pid_alive(pid):
                self._cleanup_pid_file(service)
                self.log_manager.log_info("stop_service", "服务已停止。", service=service_name, pid=pid)
                self.state.update_service(service_name, pid=None, running=False, stopped_at=time.time())
                return self._result(True, service_name, "服务已停止。")
            time.sleep(0.2)
        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        self._cleanup_pid_file(service)
        self.log_manager.log_warning("kill_service", "服务优雅停止超时，已强制结束。", service=service_name, pid=pid)
        self.state.update_service(service_name, pid=None, running=False, stopped_at=time.time())
        return self._result(True, service_name, "服务优雅停止超时，已强制结束。")

    def restart_service(self, service_name: str) -> dict[str, Any]:
        self.stop_service(service_name)
        return self.start_service(service_name)

    def status_service(self, service_name: str) -> dict[str, Any]:
        service = self.registry.get(service_name)
        pid = self._read_pid(service.pid_file)
        running = bool(pid and self._pid_alive(pid))
        if pid and not running:
            self._cleanup_pid_file(service)
            pid = None
        return {"service": service_name, "enabled": service.enabled, "pid": pid, "running": running, "pid_file": str(service.pid_file)}

    def start_all(self) -> dict[str, Any]:
        results = {}
        for service in self.registry.all(only_enabled=True):
            results[service.name] = self.start_service(service.name)
        return results

    def stop_all(self) -> dict[str, Any]:
        results = {}
        for service in reversed(self.registry.all()):
            results[service.name] = self.stop_service(service.name)
        return results

    def _normalize_command(self, command: str) -> list[str]:
        parts = shlex.split(command)
        if parts and parts[0] in {"python", "python.exe"}:
            parts[0] = sys.executable
        return parts

    @staticmethod
    def _result(ok: bool, service_name: str, message: str, **extra: Any) -> dict[str, Any]:
        payload = {"ok": bool(ok), "service": service_name, "message": message}
        payload.update(extra)
        return payload

    @staticmethod
    def _read_pid(pid_file: Path) -> int | None:
        if not pid_file.exists():
            return None
        try:
            return int(read_text(pid_file).strip())
        except Exception:
            return None

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        try:
            os.kill(pid, 0)
            return True
        except ProcessLookupError:
            return False
        except PermissionError:
            return True

    @staticmethod
    def _cleanup_pid_file(service: ServiceDefinition) -> None:
        try:
            service.pid_file.unlink()
        except FileNotFoundError:
            pass
