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
import urllib.error
import urllib.request
import sys
from pathlib import Path
from typing import Any

from .path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 控制桥接_common import (  # noqa: E402
    DEFAULT_MOTION_TUNING,
    FOLLOW_JOINT_AXES,
    JOINT_ORDER,
    normalize_control_mode,
    normalize_joint_key,
    normalize_motion_tuning,
    real_confirm_matches,
    real_confirm_required,
    real_confirm_text,
    resolve_base_path,
    tool_result_fail,
    tool_result_ok,
)
from 通用_io import read_json_object, read_structured_section, update_structured_section  # noqa: E402

from .controller_bridge import ControllerBridge
from .errors import WebAPIError
from .logger import JsonLineLogger
from .schemas import (
    ActionRecordingCaptureRequest,
    ActionRecordingStartRequest,
    AgentAskRequest,
    CalibrationBatchCurrentAngleRequest,
    CalibrationCurrentAngleRequest,
    CartesianJogRequest,
    CinematicAnalyzeRequest,
    CinematicGenerateActionRequest,
    CinematicKeyframesRequest,
    ConnectRequest,
    ContinuousJogStartRequest,
    FollowConfigRequest,
    FollowStartRequest,
    GotoPoseRequest,
    GripperRequest,
    HomeRequest,
    JointStepRequest,
    MotionTuningRequest,
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
        self.confirm_text = real_confirm_text(config, "real_confirm_text", "confirm_text")
        self.logger = JsonLineLogger(self._resolve_app_path(config.get("app", {}).get("log_path", "runtime/logs/web_api.log")))
        self.state_manager = SessionStateManager(
            self._resolve_app_path(config.get("app", {}).get("session_state_path", "runtime/state/session_state.json")),
            default_mode=self.default_mode,
        )
        self.bridge = ControllerBridge(config, base_dir=self.base_dir, logger=self.logger)
        self._lock = threading.RLock()
        self._action_thread: threading.Thread | None = None
        self._follow_controller: Any | None = None
        self._continuous_jog_thread: threading.Thread | None = None
        self._continuous_jog_stop = threading.Event()
        self._continuous_jog_status: dict[str, Any] = {"running": False, "message": "连续控制未启动。"}
        self.recent_error: dict[str, Any] | None = None
        self._agent_app: Any | None = None

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
    # AI Agent
    # ------------------------------------------------------------------
    def agent_status(self) -> dict[str, Any]:
        try:
            config = self._load_agent_config()
            agent = config.get("agent", {})
            backend = str(agent.get("backend", "openai_compatible"))
            openai_cfg = config.get("openai_compatible", {})
            robot_api = config.get("robot_api", {})
            stt = config.get("stt", {})
            tts = config.get("tts", {})
            safety = config.get("safety", {})
            return {
                "available": True,
                "backend": backend,
                "model": str(openai_cfg.get("model", "")),
                "api_base": str(openai_cfg.get("api_base", "")),
                "robot_api_base": str(robot_api.get("base_url", "")),
                "stt_url": str(stt.get("url", "")),
                "stt_provider": str(stt.get("provider", "")),
                "tts_enabled": bool(tts.get("enabled", True)),
                "tts_url": str(tts.get("url", "")),
                "max_turns": int(agent.get("max_turns", 0) or 0),
                "allow_real_robot_tools": bool(safety.get("allow_real_robot_tools", False)),
                "allowed_tools": list(safety.get("allowed_tools", [])) if isinstance(safety.get("allowed_tools", []), list) else [],
                "tool_check": self.agent_tool_check(include_state=True),
            }
        except Exception as exc:
            return {"available": False, "message": str(exc)}

    def agent_tool_check(self, include_state: bool = True) -> dict[str, Any]:
        try:
            config = self._load_agent_config()
            safety = config.get("safety", {}) if isinstance(config.get("safety", {}), dict) else {}
            result: dict[str, Any] = {
                "ok": True,
                "robot_api_base": str(config.get("robot_api", {}).get("base_url", "")),
                "mode": self.bridge.mode,
                "connected": bool(self.bridge.is_connected()),
                "allow_real_robot_tools": bool(safety.get("allow_real_robot_tools", False)),
                "message": "机器人状态工具可用。",
            }
            if include_state:
                robot_state = self.get_robot_state()
                joints = robot_state.get("joints_deg") if isinstance(robot_state.get("joints_deg"), dict) else {}
                result["state_summary"] = {
                    "mode": robot_state.get("mode"),
                    "connected": robot_state.get("connected"),
                    "joints": list(joints.keys()) if isinstance(joints, dict) else [],
                    "raw_error": (robot_state.get("raw") or {}).get("错误") if isinstance(robot_state.get("raw"), dict) else "",
                }
            return result
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def agent_ask(self, request: AgentAskRequest) -> dict[str, Any]:
        content = str(request.text or "").strip()
        if not content:
            raise WebAPIError("BAD_INPUT", "请输入要发送给 AI 的内容。")
        try:
            app = self._get_agent_app(force_new_session=bool(request.force_new_session))
            reply = app.ask_text(content, speak=bool(request.speak))
            return {
                "message": "AI 对话完成。",
                "reply": reply.text,
                "session_id": reply.session_id,
                "raw_payload": reply.raw_payload,
            }
        except Exception as exc:
            self._remember_error("AGENT_ASK_FAILED", str(exc))
            raise WebAPIError("AGENT_ASK_FAILED", f"AI 对话失败：{exc}") from exc

    def agent_reset_session(self) -> dict[str, Any]:
        try:
            app = self._get_agent_app(force_new_session=True)
            app.reset_session()
            return {"message": "AI 会话已重置。"}
        except Exception as exc:
            self._remember_error("AGENT_RESET_FAILED", str(exc))
            raise WebAPIError("AGENT_RESET_FAILED", f"AI 会话重置失败：{exc}") from exc

    def cinematic_status(self) -> dict[str, Any]:
        vision_root = self.base_dir.parent / "视觉识别与跟随"
        record_dir = vision_root / "runtime" / "cinematic_records"
        project_dir = vision_root / "runtime" / "cinematic_director_projects"
        records = self._latest_files(record_dir, "cinematic_rehearsal_*.json", limit=8)
        projects = self._latest_files(project_dir, "*.json", limit=8)
        follow_cfg = self._load_vision_follow_config(vision_root)
        rail = follow_cfg.get("rail_cinematic", {}) if isinstance(follow_cfg.get("rail_cinematic"), dict) else {}
        two_step = follow_cfg.get("two_step_cinematic", {}) if isinstance(follow_cfg.get("two_step_cinematic"), dict) else {}
        return {
            "available": True,
            "record_dir": str(record_dir),
            "project_dir": str(project_dir),
            "latest_record": records[0] if records else None,
            "latest_project": projects[0] if projects else None,
            "records": records,
            "projects": projects,
            "rail": rail,
            "two_step": two_step,
            "message": "AI 运镜状态已读取。",
        }

    def cinematic_project(self, project_path: str = "") -> dict[str, Any]:
        vision_root = self.base_dir.parent / "视觉识别与跟随"
        project_dir = (vision_root / "runtime" / "cinematic_director_projects").resolve()
        if str(project_path).strip():
            path = resolve_base_path(project_path, self.base_dir.parent)
        else:
            latest = self._latest_files(project_dir, "*.json", limit=1)
            if not latest:
                return {"available": False, "project": None, "project_path": "", "message": "暂无 AI 运镜导演项目。"}
            path = Path(latest[0]["path"])
        path = path.resolve()
        try:
            path.relative_to(project_dir)
        except ValueError as exc:
            raise WebAPIError("CINEMATIC_PROJECT_PATH_INVALID", "导演项目路径必须位于 cinematic_director_projects 目录。") from exc
        if not path.exists():
            raise WebAPIError("CINEMATIC_PROJECT_NOT_FOUND", f"导演项目不存在：{path}")
        project = read_json_object(path)
        return {
            "available": True,
            "project_path": str(path),
            "project": project,
            "message": "AI 运镜导演项目已读取。",
        }

    def cinematic_analyze(self, request: CinematicAnalyzeRequest) -> dict[str, Any]:
        result = self.bridge.cinematic_analyze(request.record_path, request.video_path)
        return self._unwrap_bridge(result, code="CINEMATIC_ANALYZE_FAILED")

    def cinematic_keyframes(self, request: CinematicKeyframesRequest) -> dict[str, Any]:
        result = self.bridge.cinematic_select_keyframes(request.project_path, request.min_count, request.max_count)
        return self._unwrap_bridge(result, code="CINEMATIC_KEYFRAMES_FAILED")

    def cinematic_generate_action(self, request: CinematicGenerateActionRequest) -> dict[str, Any]:
        result = self.bridge.cinematic_generate_action(request.project_path, request.action_name)
        return self._unwrap_bridge(result, code="CINEMATIC_ACTION_FAILED")

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
        with self._lock:
            result = self.bridge.get_state()
            return self._unwrap_bridge(result, code="STATE_FAILED")

    def get_calibration_status(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.get_calibration_status()
            return self._unwrap_bridge(result, code="CALIBRATION_STATUS_FAILED")

    def get_dependencies(self) -> dict[str, Any]:
        result = self.bridge.check_dependencies()
        return self._unwrap_bridge(result, code="DEPENDENCY_CHECK_FAILED")

    def get_hardware_check(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.check_real_hardware()
            return self._unwrap_bridge(result, code="HARDWARE_CHECK_FAILED")

    def get_joint_diagnostics(self, joint_key: str = "j12") -> dict[str, Any]:
        with self._lock:
            result = self.bridge.get_joint_diagnostics(joint_key)
            return self._unwrap_bridge(result, code="JOINT_DIAGNOSTICS_FAILED")

    def get_joint_diagnostics_batch(self, joint_keys: list[str] | None = None) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.get_joint_diagnostics_batch(joint_keys)
            return self._unwrap_bridge(result, code="JOINT_DIAGNOSTICS_BATCH_FAILED")

    def set_calibration_current_angle(self, request: CalibrationCurrentAngleRequest) -> dict[str, Any]:
        with self._lock:
            self._require_real_confirm_if_needed("real", request.confirm_text, action="保存真实标定修正")
            result = self.bridge.set_calibration_current_angle(request.joint_key, request.current_angle_deg)
            return self._unwrap_bridge(result, code="CALIBRATION_UPDATE_FAILED")

    def set_calibration_current_angles(self, request: CalibrationBatchCurrentAngleRequest) -> dict[str, Any]:
        with self._lock:
            self._require_real_confirm_if_needed("real", request.confirm_text, action="批量保存真实标定修正")
            result = self.bridge.set_calibration_current_angles(request.joint_angles_deg)
            return self._unwrap_bridge(result, code="CALIBRATION_BATCH_UPDATE_FAILED")

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

    def motion_tuning(self) -> dict[str, Any]:
        return normalize_motion_tuning(DEFAULT_MOTION_TUNING, self.config.get("motion", {}), joint_order=JOINT_ORDER)

    def set_motion_tuning(self, request: MotionTuningRequest) -> dict[str, Any]:
        payload = {key: value for key, value in request.dict(exclude_none=True).items()}
        tuning = normalize_motion_tuning(self.config.get("motion", {}), payload, joint_order=JOINT_ORDER)
        self.config.setdefault("motion", {}).update(tuning)
        saved_paths = self._persist_motion_tuning(tuning)
        return {"message": "运动调参已更新并同步到 GUI/Web 配置。", "motion": tuning, "saved_paths": saved_paths}

    def reset_motion_tuning(self) -> dict[str, Any]:
        tuning = normalize_motion_tuning(DEFAULT_MOTION_TUNING, {}, joint_order=JOINT_ORDER)
        self.config.setdefault("motion", {}).update(tuning)
        saved_paths = self._persist_motion_tuning(tuning)
        return {"message": "运动调参已恢复推荐值并同步到 GUI/Web 配置。", "motion": tuning, "saved_paths": saved_paths}

    def continuous_jog_status(self) -> dict[str, Any]:
        status = dict(self._continuous_jog_status)
        thread_alive = bool(self._continuous_jog_thread and self._continuous_jog_thread.is_alive())
        status["running"] = bool(status.get("running") and thread_alive)
        return status

    def start_continuous_jog(self, request: ContinuousJogStartRequest) -> dict[str, Any]:
        with self._lock:
            self._before_manual_motion(request.confirm_text)
            joint = normalize_joint_key(request.joint_key)
            if int(request.direction) == 0:
                raise WebAPIError("BAD_DIRECTION", "连续控制方向不能为 0。")
            self.stop_continuous_jog(join_timeout=0.4)
            tuning = self.motion_tuning()
            direction = 1 if int(request.direction) > 0 else -1
            direction *= int(tuning.get("jog_direction_overrides", {}).get(joint, 1))
            update_hz = max(2.0, float(tuning.get("continuous_update_hz", 20.0)))
            horizon_s = max(0.0, float(tuning.get("continuous_target_horizon_s", 0.25)))
            sleep_s = 1.0 / update_hz
            max_step = self._manual_step_limit()
            speed = min(abs(float(request.speed_deg_s)), max_step * update_hz)
            delta_per_tick = max(0.02, min(max_step, speed / update_hz)) * direction
            state_result = self.bridge.get_state()
            state_data = self._unwrap_bridge(state_result, code="CONTINUOUS_JOG_STATE_FAILED")
            current_joints = state_data.get("joints_deg", {})
            start_deg = float(current_joints.get(joint, 0.0))
            stop_event = threading.Event()
            self._continuous_jog_stop = stop_event
            self._continuous_jog_status = {
                "running": True,
                "joint_key": joint,
                "direction": direction,
                "speed_deg_s": speed,
                "update_hz": update_hz,
                "horizon_s": horizon_s,
                "start_deg": start_deg,
                "target_deg": start_deg,
                "delta_per_tick": delta_per_tick,
                "started_at": time.time(),
                "tick_count": 0,
                "message": "连续控制运行中。",
            }
            started_monotonic = time.monotonic()

            def worker() -> None:
                last_target = start_deg
                try:
                    while not stop_event.is_set():
                        elapsed = time.monotonic() - started_monotonic
                        ideal_target = start_deg + direction * speed * elapsed
                        step_delta = max(-max_step, min(max_step, ideal_target - last_target))
                        if abs(step_delta) < 1e-6:
                            if stop_event.wait(sleep_s):
                                break
                            continue
                        target_deg = last_target + step_delta
                        with self._lock:
                            result = self.bridge.move_single_joint_target(joint, target_deg)
                            if not result.get("ok"):
                                code, message = self._classify_motion_error(
                                    str(result.get("message") or result.get("error") or "连续控制失败。"),
                                    fallback_code="CONTINUOUS_JOG_FAILED",
                                    action="连续控制",
                                )
                                self._continuous_jog_status.update(
                                    running=False,
                                    code=code,
                                    message=message,
                                    stopped_at=time.time(),
                                )
                                self._remember_error(code, message)
                                return
                            last_target = target_deg
                            self._continuous_jog_status["target_deg"] = target_deg
                            self._continuous_jog_status["tick_count"] = int(self._continuous_jog_status.get("tick_count", 0)) + 1
                        if stop_event.wait(sleep_s):
                            break
                except Exception as exc:
                    code, message = self._classify_motion_error(str(exc), fallback_code="CONTINUOUS_JOG_FAILED", action="连续控制")
                    self._continuous_jog_status.update(running=False, code=code, message=message, stopped_at=time.time())
                    self._remember_error(code, message)
                finally:
                    self._continuous_jog_status.update(running=False, stopped_at=time.time())

            self._continuous_jog_thread = threading.Thread(target=worker, name=f"web-continuous-jog-{joint}", daemon=True)
            self._continuous_jog_thread.start()
            return {"message": "连续控制已启动。", "jog": self.continuous_jog_status()}

    def stop_continuous_jog(self, join_timeout: float = 0.8) -> dict[str, Any]:
        self._continuous_jog_stop.set()
        thread = self._continuous_jog_thread
        if thread and thread.is_alive():
            thread.join(timeout=join_timeout)
        self._continuous_jog_status.update(running=False, stopped_at=time.time(), message="连续控制已停止。")
        return {"message": "连续控制已停止。", "jog": self.continuous_jog_status()}

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
            return self._unwrap_bridge(result, code="HOME_FAILED", action="Home")

    def home_precheck(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.home_precheck()
            return self._unwrap_bridge(result, code="HOME_PRECHECK_FAILED")

    def stop(self) -> dict[str, Any]:
        with self._lock:
            self.stop_continuous_jog(join_timeout=0.2)
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
            follow_cfg = self._load_vision_follow_config(self.base_dir.parent / "视觉识别与跟随")
            rail_cfg = follow_cfg.get("rail_cinematic", {}) if isinstance(follow_cfg.get("rail_cinematic"), dict) else {}
            return {
                "running": False,
                "thread_alive": False,
                "dry_run": True,
                "latest_url": str(self.config.get("follow", {}).get("latest_url", "http://127.0.0.1:8000/latest")),
                "robot_api_base": str(self.config.get("follow", {}).get("robot_api_base", self._local_api_base())),
                "effective_config": {
                    "pan_joint": follow_cfg.get("pan_joint", "j11"),
                    "tilt_joint": follow_cfg.get("tilt_joint", "j13"),
                    "enabled_follow_joints": self._normalize_follow_joints(follow_cfg.get("enabled_follow_joints")),
                    "pan_sign": follow_cfg.get("pan_sign", 1.0),
                    "tilt_sign": follow_cfg.get("tilt_sign", -1.0),
                    "pan_gain_deg_per_norm": follow_cfg.get("pan_gain_deg_per_norm", 4.8),
                    "tilt_gain_deg_per_norm": follow_cfg.get("tilt_gain_deg_per_norm", 4.8),
                    "pan_dead_zone_norm": follow_cfg.get("pan_dead_zone_norm", 0.02),
                    "tilt_dead_zone_norm": follow_cfg.get("tilt_dead_zone_norm", 0.025),
                    "pan_resume_zone_norm": follow_cfg.get("pan_resume_zone_norm", 0.05),
                    "tilt_resume_zone_norm": follow_cfg.get("tilt_resume_zone_norm", 0.055),
                    "min_pan_step_deg": follow_cfg.get("min_pan_step_deg", 0.5),
                    "min_tilt_step_deg": follow_cfg.get("min_tilt_step_deg", 0.5),
                    "pan_min_step_zone_norm": follow_cfg.get("pan_min_step_zone_norm", 0.12),
                    "tilt_min_step_zone_norm": follow_cfg.get("tilt_min_step_zone_norm", 0.12),
                    "max_pan_step_deg": follow_cfg.get("max_pan_step_deg", 1.0),
                    "max_tilt_step_deg": follow_cfg.get("max_tilt_step_deg", 1.0),
                    "rail_cinematic": rail_cfg,
                },
                "rail": {"enabled": bool(rail_cfg.get("enabled", False)), "running": False, "phase": "idle", "joint": rail_cfg.get("joint", "j10")},
                "step_count": 0,
                "last_command": None,
                "last_vision": {},
                "last_error": "",
                "message": "视觉跟随未启动。",
            }
        return self._follow_controller.get_status()

    def follow_config(self) -> dict[str, Any]:
        vision_root = self.base_dir.parent / "视觉识别与跟随"
        follow = self._load_vision_follow_config(vision_root)
        follow["enabled_follow_joints"] = self._normalize_follow_joints(follow.get("enabled_follow_joints"))
        return {"follow": follow, "config_path": str(vision_root / "视觉配置.yaml")}

    def set_follow_config(self, request: FollowConfigRequest) -> dict[str, Any]:
        vision_root = self.base_dir.parent / "视觉识别与跟随"
        config_path = vision_root / "视觉配置.yaml"
        follow = self._load_vision_follow_config(vision_root)
        payload = {key: value for key, value in request.dict(exclude_none=True).items()}
        if "enabled_follow_joints" in payload:
            payload["enabled_follow_joints"] = self._normalize_follow_joints(payload.get("enabled_follow_joints"))
        if "pan_joint" in payload and payload["pan_joint"] is not None:
            payload["pan_joint"] = normalize_joint_key(str(payload["pan_joint"]))
        if "tilt_joint" in payload and payload["tilt_joint"] is not None:
            payload["tilt_joint"] = normalize_joint_key(str(payload["tilt_joint"]))
        if "rail_cinematic" in payload and isinstance(payload["rail_cinematic"], dict):
            rail = dict(follow.get("rail_cinematic", {})) if isinstance(follow.get("rail_cinematic", {}), dict) else {}
            rail.update(payload["rail_cinematic"])
            payload["rail_cinematic"] = rail
        follow.update(payload)
        follow["enabled_follow_joints"] = self._normalize_follow_joints(follow.get("enabled_follow_joints"))
        update_structured_section(config_path, "follow", follow)
        if self._follow_controller is not None:
            try:
                self._follow_controller.stop()
            except Exception:
                pass
            self._follow_controller = None
        return {"message": "视觉跟随参数已保存。", "follow": follow, "config_path": str(config_path)}

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
        with self._lock:
            return self._unwrap_bridge(self.bridge.list_poses(), code="POSE_LIST_FAILED")

    def get_pose(self, name: str) -> dict[str, Any]:
        with self._lock:
            return self._unwrap_bridge(self.bridge.get_pose(name), code="POSE_DETAIL_FAILED")

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
        with self._lock:
            return self._unwrap_bridge(self.bridge.list_actions(), code="ACTION_LIST_FAILED")

    def get_action(self, name: str) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.get_action(name), code="ACTION_DETAIL_FAILED")

    def delete_action(self, name: str) -> dict[str, Any]:
        with self._lock:
            current = self.bridge.action_status
            if current.get("state") == "playing" and current.get("name") == name:
                self.bridge.stop_action()
                if self._action_thread and self._action_thread.is_alive():
                    self._action_thread.join(timeout=0.5)
            return self._unwrap_bridge(self.bridge.delete_action(name), code="ACTION_DELETE_FAILED")

    def action_recording_status(self) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.get_recording_status(), code="ACTION_RECORDING_STATUS_FAILED")

    def start_action_recording(self, request: ActionRecordingStartRequest) -> dict[str, Any]:
        with self._lock:
            if request.source == "web_teach_mode":
                self._require_real_confirm(request.confirm_text, action="真实示教录制")
            result = self.bridge.start_action_recording(request.name, request.source)
            return self._unwrap_bridge(result, code="ACTION_RECORDING_START_FAILED")

    def capture_action_recording_pose(self, request: ActionRecordingCaptureRequest) -> dict[str, Any]:
        with self._lock:
            self._require_real_confirm(request.confirm_text, action="采集真实动作帧")
            result = self.bridge.capture_recording_pose()
            return self._unwrap_bridge(result, code="ACTION_RECORDING_CAPTURE_FAILED")

    def save_action_recording(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.save_recording_action()
            return self._unwrap_bridge(result, code="ACTION_RECORDING_SAVE_FAILED")

    def cancel_action_recording(self) -> dict[str, Any]:
        with self._lock:
            result = self.bridge.cancel_recording_action()
            return self._unwrap_bridge(result, code="ACTION_RECORDING_CANCEL_FAILED")

    def play_action(self, request: PlayActionRequest) -> dict[str, Any]:
        with self._lock:
            self._require_real_confirm(request.confirm_text, action="播放真实动作")
            if self._action_thread and self._action_thread.is_alive():
                self.bridge.stop_action()
                self._action_thread.join(timeout=0.5)
            self.stop_continuous_jog(join_timeout=0.2)

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

    def kinematics_status(self) -> dict[str, Any]:
        return self._unwrap_bridge(self.bridge.kinematics_status(), code="KINEMATICS_STATUS_FAILED")

    def kinematics_render(self, width: int = 960, height: int = 640) -> tuple[bytes, str]:
        result = self.bridge.render_kinematics_snapshot(width=width, height=height)
        data = self._unwrap_bridge(result, code="KINEMATICS_RENDER_FAILED")
        image_bytes = data.get("image_bytes", b"")
        media_type = str(data.get("media_type") or "image/jpeg")
        if not isinstance(image_bytes, (bytes, bytearray)) or not image_bytes:
            raise WebAPIError("KINEMATICS_RENDER_FAILED", "仿真快照为空。", status_code=500)
        return bytes(image_bytes), media_type

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
                "continuous_jog": self.continuous_jog_status(),
                "error": error,
            },
        }

    # ------------------------------------------------------------------
    # 视觉服务代理。前端只访问 Web 服务，避免浏览器侧 127.0.0.1 指向错误机器。
    # ------------------------------------------------------------------
    def vision_health(self) -> dict[str, Any]:
        return self._fetch_vision_json("/health")

    def vision_latest(self) -> dict[str, Any]:
        return self._fetch_vision_json("/latest")

    def vision_status(self) -> dict[str, Any]:
        return self._fetch_vision_json("/status")

    def vision_target_state(self) -> dict[str, Any]:
        return self._fetch_vision_json("/target/state")

    def vision_select_target(self, x: int, y: int, w: int, h: int) -> dict[str, Any]:
        return self._post_vision_json("/target/select", {"x": int(x), "y": int(y), "w": int(w), "h": int(h)})

    def vision_reset_target(self) -> dict[str, Any]:
        return self._post_vision_json("/target/reset", {})

    def vision_frame(self) -> tuple[bytes, str]:
        url = self._vision_service_url("/frame.jpg")
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                return response.read(), response.headers.get("content-type", "image/jpeg")
        except Exception as exc:
            raise WebAPIError("VISION_FRAME_FAILED", f"无法读取视觉画面：{exc}", status_code=502)

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
        if self._continuous_jog_thread and self._continuous_jog_thread.is_alive():
            self.stop_continuous_jog(join_timeout=0.2)

    def _require_real_confirm(self, confirm_text: str, action: str) -> None:
        if self.bridge.mode != "real":
            return
        self._require_real_confirm_if_needed("real", confirm_text, action=action)

    def _require_real_confirm_if_needed(self, mode: str, confirm_text: str, action: str) -> None:
        requires = real_confirm_required(self.config)
        if mode == "real" and requires and not real_confirm_matches(self.config, confirm_text, "real_confirm_text", "confirm_text"):
            raise WebAPIError("SAFETY_CONFIRM_REQUIRED", f"{action} 需要安全确认，请输入：{self.confirm_text}")

    def _manual_step_limit(self) -> float:
        key = "max_real_step_deg" if self.bridge.mode == "real" else "max_manual_step_deg"
        return float(self.config.get("safety", {}).get(key, 5.0))

    def _unwrap_bridge(self, result: dict[str, Any], code: str, action: str = "真实动作") -> dict[str, Any]:
        if result.get("ok"):
            data = result.get("data", {})
            if isinstance(data, dict):
                data.setdefault("message", result.get("message", "成功"))
                return data
            return {"value": data, "message": result.get("message", "成功")}
        message = str(result.get("message") or result.get("error") or "操作失败")
        code, message = self._classify_motion_error(message, fallback_code=code, action=action)
        self._remember_error(code, message)
        raise WebAPIError(code, message)

    @staticmethod
    def _classify_motion_error(message: str, fallback_code: str, action: str = "真实动作") -> tuple[str, str]:
        text = str(message or "")
        lower = text.lower()
        comm_markers = (
            "there is no status packet",
            "txrxresult",
            "status packet",
            "no status",
        )
        write_id_failed = "写入" in text and "ID" in text and ("失败" in text or "重试" in text)
        if any(marker in lower for marker in comm_markers) or "无状态包" in text or write_id_failed:
            guidance = (
                f"{action} 已停止：真实舵机通信/写入失败。"
                "请不要继续发送真实动作；先运行轻量 SDK 只读总线扫描 "
                "`诊断舵机总线_lightweight_sdk.py --port /dev/momo-servo --no-gripper`，"
                "再检查对应 ID 的电源、负载、线序、USB/串口稳定性和重试配置。"
            )
            if text and guidance not in text:
                return "REAL_SERVO_COMM_FAILED", f"{guidance} 原始错误：{text}"
            return "REAL_SERVO_COMM_FAILED", guidance
        return fallback_code, text

    def _load_agent_config(self) -> dict[str, Any]:
        agent_root = self.base_dir.parent / "语音Agent"
        if str(agent_root) not in sys.path:
            sys.path.insert(0, str(agent_root))
        from agent.配置_config import load_config

        return load_config(agent_root / "Agent配置.yaml")

    def _get_agent_app(self, force_new_session: bool = False) -> Any:
        if force_new_session:
            self._agent_app = None
        if self._agent_app is None:
            agent_root = self.base_dir.parent / "语音Agent"
            if str(agent_root) not in sys.path:
                sys.path.insert(0, str(agent_root))
            from agent.对话应用_agent_app import AgentApp

            config = self._load_agent_config()
            config.setdefault("tts", {})["enabled"] = False
            self._agent_app = AgentApp(config, force_new_session=force_new_session, tool_bridge=self._create_agent_tool_bridge(config))
        return self._agent_app

    def _create_agent_tool_bridge(self, config: dict[str, Any]) -> Any:
        service = self

        class WebServiceToolBridge:
            def execute(self, tool_name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
                if tool_name == "get_robot_state":
                    try:
                        return tool_result_ok(tool_name, service.get_robot_state())
                    except Exception as exc:
                        return tool_result_fail(tool_name, f"读取 Web 同进程机械臂状态失败：{exc}")
                if tool_name == "stop_robot":
                    try:
                        return tool_result_ok(tool_name, service.stop())
                    except Exception as exc:
                        return tool_result_fail(tool_name, f"停止命令失败：{exc}")
                from agent.工具桥接_tool_bridge import RobotToolBridge

                return RobotToolBridge(config).execute(tool_name, arguments or {})

        return WebServiceToolBridge()

    @staticmethod
    def _latest_files(directory: Path, pattern: str, limit: int = 8) -> list[dict[str, Any]]:
        if not directory.exists():
            return []
        items = sorted(directory.glob(pattern), key=lambda path: path.stat().st_mtime, reverse=True)
        result = []
        for path in items[: max(1, int(limit))]:
            stat = path.stat()
            result.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "size": stat.st_size,
                    "modified_at": stat.st_mtime,
                }
            )
        return result

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
        from 控制桥接_common import ensure_import_paths

        ensure_import_paths([vision_root])
        from vision.视觉跟随_controller import VisionFollowController

        follow_cfg = dict(self.config.get("follow", {}))
        follow_cfg.update(self._load_vision_follow_config(vision_root))
        follow_cfg["latest_url"] = request.latest_url
        follow_cfg["robot_api_base"] = request.robot_api_base or follow_cfg.get("robot_api_base") or self._local_api_base()
        follow_cfg["confirm_text"] = request.confirm_text
        if not request.dry_run and self.bridge.mode == "real":
            real_step_limit = self._manual_step_limit()
            follow_cfg["max_pan_step_deg"] = min(float(follow_cfg.get("max_pan_step_deg", real_step_limit)), real_step_limit)
            follow_cfg["max_tilt_step_deg"] = min(float(follow_cfg.get("max_tilt_step_deg", real_step_limit)), real_step_limit)
        if request.pan_joint is not None:
            follow_cfg["pan_joint"] = normalize_joint_key(request.pan_joint)
        if request.tilt_joint is not None:
            follow_cfg["tilt_joint"] = normalize_joint_key(request.tilt_joint)
        if request.enabled_follow_joints is not None:
            follow_cfg["enabled_follow_joints"] = self._normalize_follow_joints(request.enabled_follow_joints)
        if request.pan_gain is not None:
            follow_cfg["pan_gain_deg_per_norm"] = float(request.pan_gain)
        if request.tilt_gain is not None:
            follow_cfg["tilt_gain_deg_per_norm"] = float(request.tilt_gain)
        if request.pan_sign is not None:
            follow_cfg["pan_sign"] = float(request.pan_sign)
        if request.tilt_sign is not None:
            follow_cfg["tilt_sign"] = float(request.tilt_sign)
        if request.max_pan_step_deg is not None:
            follow_cfg["max_pan_step_deg"] = float(request.max_pan_step_deg)
        if request.max_tilt_step_deg is not None:
            follow_cfg["max_tilt_step_deg"] = float(request.max_tilt_step_deg)
        if request.speed_percent is not None:
            follow_cfg["speed_percent"] = int(request.speed_percent)
        if request.poll_interval is not None:
            follow_cfg["poll_interval_sec"] = float(request.poll_interval)
        if request.move_duration is not None:
            follow_cfg["move_duration_sec"] = float(request.move_duration)
        rail_cfg = dict(follow_cfg.get("rail_cinematic", {})) if isinstance(follow_cfg.get("rail_cinematic", {}), dict) else {}
        if request.rail_enabled is not None:
            rail_cfg["enabled"] = bool(request.rail_enabled)
        if request.rail_start_mm is not None:
            rail_cfg["start_mm"] = float(request.rail_start_mm)
        if request.rail_end_mm is not None:
            rail_cfg["end_mm"] = float(request.rail_end_mm)
        if request.rail_speed_mm_s is not None:
            rail_cfg["speed_mm_s"] = float(request.rail_speed_mm_s)
        if request.rail_step_mm is not None:
            rail_cfg["step_mm"] = float(request.rail_step_mm)
        if request.rail_interval_sec is not None:
            rail_cfg["interval_sec"] = float(request.rail_interval_sec)
        if rail_cfg:
            rail_cfg.setdefault("joint", "j10")
            rail_cfg.setdefault("bounce", False)
            follow_cfg["rail_cinematic"] = rail_cfg
        return VisionFollowController({"follow": follow_cfg}, latest_url=request.latest_url, dry_run=request.dry_run)

    def _load_vision_follow_config(self, vision_root: Path) -> dict[str, Any]:
        config_path = vision_root / "视觉配置.yaml"
        try:
            return read_structured_section(config_path, "follow")
        except Exception:
            return {}

    def _persist_motion_tuning(self, tuning: dict[str, Any]) -> list[str]:
        paths = [self.base_dir / "Web配置.yaml", self.base_dir.parent / "GUI图形界面" / "GUI配置.yaml"]
        saved: list[str] = []
        for path in paths:
            try:
                update_structured_section(path, "motion", tuning)
                saved.append(str(path))
            except Exception as exc:
                self._remember_error("MOTION_TUNING_SAVE_FAILED", f"{path}: {exc}")
        return saved

    @staticmethod
    def _normalize_follow_joints(value: Any) -> list[str]:
        raw = value if isinstance(value, list) else ["j11", "j13"]
        result: list[str] = []
        for item in raw:
            try:
                joint = normalize_joint_key(str(item))
            except Exception:
                continue
            if joint in FOLLOW_JOINT_AXES and joint not in result:
                result.append(joint)
        return result or ["j11", "j13"]

    def _fetch_vision_json(self, path: str) -> dict[str, Any]:
        url = self._vision_service_url(path)
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                import json

                payload = json.loads(response.read().decode("utf-8"))
                if isinstance(payload, dict):
                    payload.setdefault("proxy_url", url)
                    return payload
                return {"value": payload, "proxy_url": url}
        except urllib.error.HTTPError as exc:
            raise WebAPIError("VISION_HTTP_ERROR", f"视觉服务 HTTP {exc.code}：{url}", status_code=502)
        except Exception as exc:
            raise WebAPIError("VISION_UNAVAILABLE", f"视觉服务不可用：{url}，{exc}", status_code=502)

    def _post_vision_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = self._vision_service_url(path)
        try:
            import json

            body = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=3.0) as response:
                result = json.loads(response.read().decode("utf-8"))
                if isinstance(result, dict):
                    result.setdefault("proxy_url", url)
                    return result
                return {"value": result, "proxy_url": url}
        except urllib.error.HTTPError as exc:
            raise WebAPIError("VISION_HTTP_ERROR", f"视觉服务 HTTP {exc.code}：{url}", status_code=502)
        except Exception as exc:
            raise WebAPIError("VISION_UNAVAILABLE", f"视觉服务不可用：{url}，{exc}", status_code=502)

    def _vision_service_url(self, path: str) -> str:
        follow = self.config.get("follow", {})
        latest_url = str(follow.get("latest_url", "http://127.0.0.1:8000/latest"))
        try:
            from urllib.parse import urljoin

            base = latest_url.rsplit("/", 1)[0] + "/"
            return urljoin(base, path.lstrip("/"))
        except Exception:
            return f"http://127.0.0.1:8000/{path.lstrip('/')}"

    def _local_api_base(self) -> str:
        server = self.config.get("server", {})
        host = str(server.get("host", "127.0.0.1"))
        if host in {"0.0.0.0", "::"}:
            host = "127.0.0.1"
        port = int(server.get("port", 8010))
        return f"http://{host}:{port}"

    @staticmethod
    def _normalize_mode(mode: str) -> str:
        try:
            return normalize_control_mode(mode, simulation_value="sim")
        except ValueError:
            raise WebAPIError("BAD_MODE", f"未知模式：{mode}")


def _deg_to_rad(value: float) -> float:
    return float(value) * 3.141592653589793 / 180.0
