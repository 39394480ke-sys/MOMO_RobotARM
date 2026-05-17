"""阶段八 WebControlService。

service.py 只处理业务规则：
- session / 模式管理
- 真实模式安全确认
- 手动运动前停止动作回放
- 统一调用 ControllerBridge
- 维护最近错误和 WebSocket 状态
"""

from __future__ import annotations

import threading
import time
import traceback
import sys
from pathlib import Path
from typing import Any, Callable

from .controller_bridge import ControllerBridge
from .errors import WebAPIError
from .logger import JsonLineLogger
from .schemas import (
    CartesianJogRequest,
    ConnectRequest,
    FollowStartRequest,
    GotoPoseRequest,
    GripperRequest,
    HomeRequest,
    JointStepRequest,
    MoveJointsRequest,
    MovePoseRequest,
    PlayActionRequest,
    SavePoseRequest,
)
from .state_manager import SessionStateManager
from .websocket_manager import WebSocketManager


class WebControlService:
    """Web/API 统一业务入口。"""

    def __init__(self, config: dict[str, Any], base_dir: str | Path, websocket_manager: WebSocketManager):
        self.config = config
        self.base_dir = Path(base_dir).resolve()
        self.websocket_manager = websocket_manager
        self.started_at = time.time()
        self.default_mode = self._normalize_mode(config.get("app", {}).get("default_mode", "dry_run"))
        self.confirm_text = str(config.get("safety", {}).get("real_confirm_text", "我确认机械臂周围安全"))
        self.logger = JsonLineLogger(self._resolve_app_path(config.get("app", {}).get("log_path", "runtime/logs/web_api.log")))
        self.state_manager = SessionStateManager(
            self._resolve_app_path(config.get("app", {}).get("session_state_path", "runtime/state/session_state.json")),
            default_mode=self.default_mode,
        )
        self.bridge = ControllerBridge(config, base_dir=self.base_dir, logger=self.logger)
        self._lock = threading.RLock()
        self._action_thread: threading.Thread | None = None
        self._follow_controller: Any | None = None
        self.recent_error: dict[str, Any] | None = None

    # ------------------------------------------------------------------
    # 基础信息
    # ------------------------------------------------------------------
    def health(self) -> dict[str, Any]:
        return {
            "service": "arm_web_control_api",
            "status": "ok",
            "title": self.config.get("app", {}).get("title", "我的机械臂 Web 控制台"),
            "default_mode": self.default_mode,
            "uptime_sec": round(time.time() - self.started_at, 3),
            "time": time.time(),
        }

    def public_config(self) -> dict[str, Any]:
        return {
            "server": self.config.get("server", {}),
            "app": self.config.get("app", {}),
            "controller": self.config.get("controller", {}),
            "safety": {
                "default_dry_run": self.config.get("safety", {}).get("default_dry_run", True),
                "real_mode_requires_confirm": self.config.get("safety", {}).get("real_mode_requires_confirm", True),
                "real_confirm_text": self.confirm_text,
                "max_manual_step_deg": self.config.get("safety", {}).get("max_manual_step_deg", 5.0),
                "max_real_step_deg": self.config.get("safety", {}).get("max_real_step_deg", 2.0),
            },
            "motion": self.config.get("motion", {}),
            "follow": self.config.get("follow", {}),
        }

    # ------------------------------------------------------------------
    # 会话
    # ------------------------------------------------------------------
    def session_status(self) -> dict[str, Any]:
        state = self.state_manager.get()
        state["mode"] = self.bridge.mode
        state["connected"] = self.bridge.is_connected()
        state["action"] = self.current_action_status()
        return state

    def connect(self, request: ConnectRequest) -> dict[str, Any]:
        with self._lock:
            mode = self._normalize_mode(request.mode)
            self._require_real_confirm_if_needed(mode, request.confirm_text, action="连接真实模式")
            result = self.bridge.connect(mode)
            if not result.get("ok"):
                self.state_manager.update(mode=mode, connected=False, disconnected_at=time.time())
            data = self._unwrap_bridge(result, code="CONNECT_FAILED")
            if self.bridge.is_connected():
                session = self.state_manager.mark_connected(mode)
            else:
                self.state_manager.update(mode=mode)
                session = self.state_manager.mark_disconnected()
            self._clear_error()
            return {"message": result.get("message", "连接完成。"), "session": session, "bridge": data}

    def disconnect(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.disconnect()
            data = self._unwrap_bridge(result, code="DISCONNECT_FAILED")
            session = self.state_manager.mark_disconnected()
            self._clear_error()
            return {"message": result.get("message", "已断开。"), "session": session, "bridge": data}

    def set_mode(self, mode: str, confirm_text: str = "") -> dict[str, Any]:
        with self._lock:
            normalized = self._normalize_mode(mode)
            self._require_real_confirm_if_needed(normalized, confirm_text, action="切换真实模式")
            result = self.bridge.set_mode(normalized)
            data = self._unwrap_bridge(result, code="MODE_SWITCH_FAILED")
            session = self.state_manager.update(mode=normalized, connected=False)
            self._clear_error()
            return {"message": result.get("message", "模式已切换。"), "session": session, "bridge": data}

    # ------------------------------------------------------------------
    # 状态
    # ------------------------------------------------------------------
    def get_robot_state(self) -> dict[str, Any]:
        result = self.bridge.get_state()
        return self._unwrap_bridge(result, code="STATE_FAILED")

    def get_calibration_status(self) -> dict[str, Any]:
        result = self.bridge.get_calibration_status()
        return self._unwrap_bridge(result, code="CALIBRATION_STATUS_FAILED")

    def get_dependencies(self) -> dict[str, Any]:
        result = self.bridge.check_dependencies()
        return self._unwrap_bridge(result, code="DEPENDENCY_CHECK_FAILED")

    # ------------------------------------------------------------------
    # 运动控制
    # ------------------------------------------------------------------
    def joint_step(self, request: JointStepRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            limit = self._manual_step_limit()
            if abs(float(request.delta_deg)) > limit:
                raise WebAPIError("STEP_TOO_LARGE", f"步长 {request.delta_deg}° 超过当前模式限制 {limit}°。")
            result = self.bridge.move_joint_delta(request.joint_key, request.delta_deg)
            return self._unwrap_bridge(result, code="JOINT_STEP_FAILED")

    def move_joints(self, request: MoveJointsRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            result = self.bridge.move_joints(request.targets_deg)
            return self._unwrap_bridge(result, code="MOVE_JOINTS_FAILED")

    def cartesian_jog(self, request: CartesianJogRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            step_m = float(request.step_dist_mm) / 1000.0
            step_rad = _deg_to_rad(float(request.step_angle_deg))
            dx = dy = dz = drx = dry = drz = 0.0
            match request.axis:
                case "+X":
                    dx = step_m
                case "-X":
                    dx = -step_m
                case "+Y":
                    dy = step_m
                case "-Y":
                    dy = -step_m
                case "+Z":
                    dz = step_m
                case "-Z":
                    dz = -step_m
                case "+RX":
                    drx = step_rad
                case "-RX":
                    drx = -step_rad
                case "+RY":
                    dry = step_rad
                case "-RY":
                    dry = -step_rad
                case "+RZ":
                    drz = step_rad
                case "-RZ":
                    drz = -step_rad
            result = self.bridge.move_delta(dx, dy, dz, drx, dry, drz, request.coord_frame)
            return self._unwrap_bridge(result, code="CARTESIAN_JOG_FAILED")

    def move_pose(self, request: MovePoseRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            if len(request.xyz) < 3:
                raise WebAPIError("BAD_REQUEST", "xyz 至少需要 3 个数字。")
            if request.rpy is not None and len(request.rpy) < 3:
                raise WebAPIError("BAD_REQUEST", "rpy 至少需要 3 个数字。")
            result = self.bridge.move_pose(request.xyz[:3], request.rpy[:3] if request.rpy is not None else None)
            return self._unwrap_bridge(result, code="MOVE_POSE_FAILED")

    def home(self, request: HomeRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            result = self.bridge.home()
            return self._unwrap_bridge(result, code="HOME_FAILED")

    def stop(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.stop()
            data = self._unwrap_bridge(result, code="STOP_FAILED")
            return {"message": result.get("message", "已急停。"), "bridge": data}

    def set_gripper(self, request: GripperRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            result = self.bridge.set_gripper(request.open_ratio)
            return self._unwrap_bridge(result, code="GRIPPER_FAILED")

    # ------------------------------------------------------------------
    # 视觉跟随
    # ------------------------------------------------------------------
    def follow_status(self) -> dict[str, Any]:
        if self._follow_controller is None:
            return {
                "running": False,
                "dry_run": True,
                "message": "视觉跟随未启动。",
            }
        return self._follow_controller.get_status()

    def start_follow(self, request: FollowStartRequest) -> dict[str, Any]:
        with self._lock:
            if not request.dry_run and (self.bridge.mode != "real" or not self.bridge.is_connected()):
                raise WebAPIError("REAL_SESSION_REQUIRED", "启动真实视觉跟随前，请先连接 real 模式。")
            if self.bridge.mode == "real" and not request.dry_run:
                self._require_real_confirm(request.confirm_text, action="启动真实视觉跟随")
            if self._follow_controller is not None:
                try:
                    self._follow_controller.stop()
                except Exception:
                    pass
            controller = self._create_follow_controller(request)
            self._follow_controller = controller
            controller.start()
            self.logger.log(
                "info",
                "follow_started",
                "视觉跟随已启动。",
                dry_run=request.dry_run,
                latest_url=request.latest_url,
            )
            return {"message": "视觉跟随已启动。", "follow": controller.get_status()}

    def stop_follow(self) -> dict[str, Any]:
        with self._lock:
            if self._follow_controller is None:
                return {"message": "视觉跟随未启动。", "follow": self.follow_status()}
            status = self._follow_controller.stop()
            self.logger.log("info", "follow_stopped", "视觉跟随已停止。")
            return {"message": "视觉跟随已停止。", "follow": status}

    # ------------------------------------------------------------------
    # 姿态
    # ------------------------------------------------------------------
    def list_poses(self) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.list_poses(), code="POSE_LIST_FAILED")

    def save_pose(self, request: SavePoseRequest) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.save_pose(request.name, request.description), code="POSE_SAVE_FAILED")

    def goto_pose(self, request: GotoPoseRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            return self._unwrap_bridge(self.bridge.goto_pose(request.name), code="POSE_GOTO_FAILED")

    def delete_pose(self, name: str) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.delete_pose(name), code="POSE_DELETE_FAILED")

    # ------------------------------------------------------------------
    # 动作
    # ------------------------------------------------------------------
    def list_actions(self) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.list_actions(), code="ACTION_LIST_FAILED")

    def get_action(self, name: str) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.get_action(name), code="ACTION_DETAIL_FAILED")

    def play_action(self, request: PlayActionRequest) -> dict[str, Any]:
        with self._lock:
            self._require_real_confirm(request.confirm_text, action="播放真实动作")
            if self._action_thread and self._action_thread.is_alive():
                self.bridge.stop_action()
                self._action_thread.join(timeout=0.5)

            def worker() -> None:
                try:
                    self.bridge.play_action(request.name, request.speed, request.loop)
                except Exception as exc:
                    self._remember_error("ACTION_WORKER_FAILED", f"动作线程异常：{exc}")
                    self.logger.log("error", "action_worker_exception", str(exc), traceback=traceback.format_exc())

            self._action_thread = threading.Thread(target=worker, name=f"web-action-{request.name}", daemon=True)
            self._action_thread.start()
            self.logger.log("info", "action_started", f"动作已开始：{request.name}", name=request.name, speed=request.speed, loop=request.loop)
            return {
                "message": f"动作已开始播放：{request.name}",
                "action": self.current_action_status(),
            }

    def pause_action(self) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.pause_action(), code="ACTION_PAUSE_FAILED")

    def resume_action(self) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.resume_action(), code="ACTION_RESUME_FAILED")

    def stop_action(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.stop_action()
            if self._action_thread and self._action_thread.is_alive():
                self._action_thread.join(timeout=0.5)
            return self._unwrap_bridge(result, code="ACTION_STOP_FAILED")

    def current_action_status(self) -> dict[str, Any]:
        action = dict(self.bridge.action_status)
        action["thread_alive"] = bool(self._action_thread and self._action_thread.is_alive())
        return action

    # ------------------------------------------------------------------
    # 运动学额外接口，供前端 FK / IK 页使用。
    # ------------------------------------------------------------------
    def compute_fk(self, joints_deg: list[float]) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.compute_fk(joints_deg), code="FK_FAILED")

    def compute_ik(self, xyz: list[float], rpy: list[float] | None = None) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.compute_ik(xyz, rpy), code="IK_FAILED")

    # ------------------------------------------------------------------
    # WebSocket 状态
    # ------------------------------------------------------------------
    def websocket_payload(self) -> dict[str, Any]:
        try:
            robot = self.get_robot_state()
            error = self.recent_error
        except Exception as exc:
            robot = {}
            error = {"code": "STATE_PUSH_FAILED", "message": str(exc)}
        return {
            "type": "state",
            "timestamp": time.time(),
            "data": {
                "session": self.session_status(),
                "robot": robot,
                "action": self.current_action_status(),
                "follow": self.follow_status(),
                "error": error,
            },
        }

    async def broadcast_state(self) -> None:
        try:
            await self.websocket_manager.broadcast(self.websocket_payload())
        except Exception as exc:
            self.logger.log("warning", "websocket_broadcast_failed", str(exc))

    # ------------------------------------------------------------------
    # 内部工具
    # ------------------------------------------------------------------
    def _before_manual_motion(self, confirm_text: str = "") -> None:
        self._require_real_confirm(confirm_text, action="真实模式手动运动")
        if self._action_thread and self._action_thread.is_alive():
            self.bridge.stop_action()
            self._action_thread.join(timeout=0.5)

    def _require_real_confirm(self, confirm_text: str, action: str) -> None:
        if self.bridge.mode != "real":
            return
        self._require_real_confirm_if_needed("real", confirm_text, action=action)

    def _require_real_confirm_if_needed(self, mode: str, confirm_text: str, action: str) -> None:
        requires = bool(self.config.get("safety", {}).get("real_mode_requires_confirm", True))
        if mode == "real" and requires and str(confirm_text).strip() != self.confirm_text:
            raise WebAPIError("SAFETY_CONFIRM_REQUIRED", f"{action} 需要安全确认，请输入：{self.confirm_text}")

    def _manual_step_limit(self) -> float:
        key = "max_real_step_deg" if self.bridge.mode == "real" else "max_manual_step_deg"
        return float(self.config.get("safety", {}).get(key, 5.0))

    def _unwrap_bridge(self, result: dict[str, Any], code: str) -> dict[str, Any]:
        if result.get("ok"):
            data = result.get("data", {})
            if isinstance(data, dict):
                data.setdefault("message", result.get("message", "成功"))
                return data
            return {"value": data, "message": result.get("message", "成功")}
        message = str(result.get("message") or result.get("error") or "操作失败")
        self._remember_error(code, message)
        raise WebAPIError(code, message)

    def _remember_error(self, code: str, message: str) -> None:
        self.recent_error = {"code": str(code), "message": str(message), "time": time.time()}
        self.logger.log("error", code, message)

    def _clear_error(self) -> None:
        self.recent_error = None

    def _resolve_app_path(self, path_value: str | Path) -> Path:
        path = Path(path_value)
        if path.is_absolute():
            return path
        return self.base_dir / path

    def _create_follow_controller(self, request: FollowStartRequest) -> Any:
        vision_root = self.base_dir.parent / "视觉识别与跟随"
        vision_root_text = str(vision_root)
        if vision_root_text not in sys.path:
            sys.path.insert(0, vision_root_text)
        from vision.视觉跟随_controller import VisionFollowController

        follow_cfg = dict(self.config.get("follow", {}))
        follow_cfg.update(self._load_vision_follow_config(vision_root))
        follow_cfg["latest_url"] = request.latest_url
        follow_cfg["robot_api_base"] = request.robot_api_base or follow_cfg.get("robot_api_base") or self._local_api_base()
        follow_cfg["confirm_text"] = request.confirm_text
        if request.pan_joint is not None:
            follow_cfg["pan_joint"] = request.pan_joint
        if request.tilt_joint is not None:
            follow_cfg["tilt_joint"] = request.tilt_joint
        if request.pan_gain is not None:
            follow_cfg["pan_gain_deg_per_norm"] = float(request.pan_gain)
        if request.tilt_gain is not None:
            follow_cfg["tilt_gain_deg_per_norm"] = float(request.tilt_gain)
        if request.speed_percent is not None:
            follow_cfg["speed_percent"] = int(request.speed_percent)
        if request.poll_interval is not None:
            follow_cfg["poll_interval_sec"] = float(request.poll_interval)
        if request.move_duration is not None:
            follow_cfg["move_duration_sec"] = float(request.move_duration)
        return VisionFollowController({"follow": follow_cfg}, latest_url=request.latest_url, dry_run=request.dry_run)

    def _load_vision_follow_config(self, vision_root: Path) -> dict[str, Any]:
        config_path = vision_root / "视觉配置.yaml"
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        except Exception:
            return {}
        if not isinstance(data, dict):
            return {}
        follow = data.get("follow", {})
        return dict(follow) if isinstance(follow, dict) else {}

    def _local_api_base(self) -> str:
        server = self.config.get("server", {})
        host = str(server.get("host", "127.0.0.1"))
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = int(server.get("port", 8010))
        return f"http://{host}:{port}"

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        value = str(mode).strip().lower()
        mapping = {"simulation": "sim", "dry-run": "dry_run", "dryrun": "dry_run", "仿真": "sim", "真实": "real"}
        value = mapping.get(value, value)
        if value not in {"sim", "dry_run", "real"}:
            raise WebAPIError("BAD_MODE", f"未知模式：{mode}")
        return value


def _deg_to_rad(value: float) -> float:
    return float(value) * 3.141592653589793 / 180.0
