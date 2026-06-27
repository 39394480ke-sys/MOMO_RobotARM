"""阶段八 FastAPI 应用。

app.py 只负责路由、异常处理和静态前端挂载；业务逻辑在 service.py。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response

from .path_utils import PROJECT_ROOT, WEB_DIR, ensure_project_root_on_path
from 控制桥接_common import api_error, api_success
from .errors import WebAPIError
from .schemas import (
    ActionRecordingCaptureRequest,
    ActionRecordingStartRequest,
    AgentAskRequest,
    CartesianJogRequest,
    CalibrationBatchCurrentAngleRequest,
    CalibrationCurrentAngleRequest,
    CinematicAnalyzeRequest,
    CinematicGenerateActionRequest,
    CinematicKeyframesRequest,
    ConnectRequest,
    ContinuousJogStartRequest,
    FKRequest,
    FollowStartRequest,
    GotoPoseRequest,
    GripperRequest,
    HomeRequest,
    IKRequest,
    JointStepRequest,
    ModeRequest,
    MotionTuningRequest,
    MoveJointsRequest,
    MovePoseRequest,
    PlayActionRequest,
    SavePoseRequest,
    VisionTargetSelectRequest,
)
from .service import WebControlService
from .static_server import install_static_routes
from .websocket_manager import WebSocketManager


BASE_DIR = WEB_DIR
CONFIG = None


def load_web_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else BASE_DIR / "Web配置.yaml"
    ensure_project_root_on_path()
    from 通用_io import env_int, env_value, read_config

    config = read_config(config_path)
    env_paths = (PROJECT_ROOT / ".env", BASE_DIR / "环境变量.env", PROJECT_ROOT / "系统集成" / "环境变量.env")
    server = config.setdefault("server", {})
    follow = config.setdefault("follow", {})
    app_cfg = config.setdefault("app", {})

    server["host"] = env_value("ARM_WEB_HOST", server.get("host", "127.0.0.1"), env_paths=env_paths)
    server["port"] = env_int("ARM_WEB_PORT", int(server.get("port", 8010)), env_paths=env_paths)
    app_cfg["default_mode"] = env_value("ARM_DEFAULT_MODE", app_cfg.get("default_mode", "dry_run"), env_paths=env_paths)

    vision_host = str(env_value("ARM_VISION_HOST", "127.0.0.1", env_paths=env_paths))
    vision_port = env_int("ARM_VISION_PORT", 8000, env_paths=env_paths)
    web_host = str(server.get("host", "127.0.0.1"))
    web_port = int(server.get("port", 8010))
    latest_default = f"http://127.0.0.1:{vision_port}/latest" if vision_host == "0.0.0.0" else f"http://{vision_host}:{vision_port}/latest"
    api_default = f"http://127.0.0.1:{web_port}" if web_host == "0.0.0.0" else f"http://{web_host}:{web_port}"
    vision_env_changed = any(env_value(name, "", env_paths=env_paths) for name in ("ARM_VISION_HOST", "ARM_VISION_PORT"))
    web_env_changed = any(env_value(name, "", env_paths=env_paths) for name in ("ARM_WEB_HOST", "ARM_WEB_PORT"))
    follow["latest_url"] = env_value(
        "ARM_VISION_LATEST_URL",
        latest_default if vision_env_changed else follow.get("latest_url", latest_default),
        env_paths=env_paths,
    )
    follow["robot_api_base"] = env_value(
        "ARM_ROBOT_API_BASE",
        api_default if web_env_changed else follow.get("robot_api_base", api_default),
        env_paths=env_paths,
    )
    return config


CONFIG = load_web_config()
websocket_manager = WebSocketManager()
service = WebControlService(CONFIG, BASE_DIR, websocket_manager)

app = FastAPI(title=CONFIG.get("app", {}).get("title", "我的机械臂 Web 控制台"))

server_cfg = CONFIG.get("server", {})
if server_cfg.get("cors_enabled", True):
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(server_cfg.get("allowed_origins", ["http://127.0.0.1:8010", "http://localhost:8010"])),
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


@app.exception_handler(WebAPIError)
async def web_api_error_handler(_request, exc: WebAPIError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content=api_error(exc.code, exc.message))


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content=api_error("VALIDATION_ERROR", f"请求参数不合法：{exc}"))


@app.exception_handler(Exception)
async def generic_error_handler(_request, exc: Exception) -> JSONResponse:
    service.logger.log("error", "unhandled_exception", str(exc))
    return JSONResponse(status_code=500, content=api_error("INTERNAL_ERROR", f"服务内部错误：{exc}"))


async def _call(fn: Callable[..., dict[str, Any]], *args: Any, broadcast: bool = True) -> dict[str, Any]:
    data = fn(*args)
    if broadcast:
        await service.broadcast_state()
    return api_success(data)


# ----------------------------------------------------------------------
# 基础
# ----------------------------------------------------------------------
@app.get("/api/v1/health")
async def health() -> dict[str, Any]:
    return api_success(service.health())


@app.get("/api/v1/config")
async def config() -> dict[str, Any]:
    return api_success(service.public_config())


# ----------------------------------------------------------------------
# AI Agent
# ----------------------------------------------------------------------
@app.get("/api/v1/agent/status")
async def agent_status() -> dict[str, Any]:
    return api_success(service.agent_status())


@app.post("/api/v1/agent/ask")
async def agent_ask(request: AgentAskRequest) -> dict[str, Any]:
    return await _call(service.agent_ask, request, broadcast=False)


@app.post("/api/v1/agent/reset-session")
async def agent_reset_session() -> dict[str, Any]:
    return await _call(service.agent_reset_session, broadcast=False)


@app.get("/api/v1/cinematic/status")
async def cinematic_status() -> dict[str, Any]:
    return api_success(service.cinematic_status())


@app.get("/api/v1/cinematic/project")
async def cinematic_project(project_path: str = Query(default="")) -> dict[str, Any]:
    return api_success(service.cinematic_project(project_path))


@app.post("/api/v1/cinematic/analyze")
async def cinematic_analyze(request: CinematicAnalyzeRequest) -> dict[str, Any]:
    return await _call(service.cinematic_analyze, request, broadcast=False)


@app.post("/api/v1/cinematic/keyframes")
async def cinematic_keyframes(request: CinematicKeyframesRequest) -> dict[str, Any]:
    return await _call(service.cinematic_keyframes, request, broadcast=False)


@app.post("/api/v1/cinematic/generate-action")
async def cinematic_generate_action(request: CinematicGenerateActionRequest) -> dict[str, Any]:
    return await _call(service.cinematic_generate_action, request, broadcast=False)


# ----------------------------------------------------------------------
# 会话
# ----------------------------------------------------------------------
@app.get("/api/v1/session/status")
async def session_status() -> dict[str, Any]:
    return api_success(service.session_status())


@app.post("/api/v1/session/connect")
async def session_connect(request: ConnectRequest) -> dict[str, Any]:
    return await _call(service.connect, request)


@app.post("/api/v1/session/disconnect")
async def session_disconnect() -> dict[str, Any]:
    return await _call(service.disconnect)


@app.post("/api/v1/session/mode")
async def session_mode(request: ModeRequest) -> dict[str, Any]:
    return await _call(service.set_mode, request.mode, request.confirm_text)


# ----------------------------------------------------------------------
# 机器人状态
# ----------------------------------------------------------------------
@app.get("/api/v1/robot/state")
async def robot_state() -> dict[str, Any]:
    return api_success(service.get_robot_state())


@app.get("/api/v1/robot/calibration-status")
async def calibration_status() -> dict[str, Any]:
    return api_success(service.get_calibration_status())


@app.get("/api/v1/robot/dependencies")
async def dependencies() -> dict[str, Any]:
    return api_success(service.get_dependencies())


@app.get("/api/v1/robot/hardware-check")
async def hardware_check() -> dict[str, Any]:
    return api_success(service.get_hardware_check())


@app.get("/api/v1/robot/joint-diagnostics")
async def joint_diagnostics(joint_key: str = "j12") -> dict[str, Any]:
    return api_success(service.get_joint_diagnostics(joint_key))


@app.get("/api/v1/robot/joint-diagnostics/batch")
async def joint_diagnostics_batch(joint_keys: str = "j10,j11,j12,j13,j15") -> dict[str, Any]:
    joints = [item.strip() for item in joint_keys.split(",") if item.strip()]
    return api_success(service.get_joint_diagnostics_batch(joints or None))


@app.post("/api/v1/robot/calibration/current-angle")
async def calibration_current_angle(request: CalibrationCurrentAngleRequest) -> dict[str, Any]:
    return await _call(service.set_calibration_current_angle, request)


@app.post("/api/v1/robot/calibration/current-angles")
async def calibration_current_angles(request: CalibrationBatchCurrentAngleRequest) -> dict[str, Any]:
    return await _call(service.set_calibration_current_angles, request)


# ----------------------------------------------------------------------
# 运动控制
# ----------------------------------------------------------------------
@app.post("/api/v1/motion/joint-step")
async def motion_joint_step(request: JointStepRequest) -> dict[str, Any]:
    return await _call(service.joint_step, request)


@app.get("/api/v1/motion/tuning")
async def motion_tuning() -> dict[str, Any]:
    return api_success(service.motion_tuning())


@app.post("/api/v1/motion/tuning")
async def motion_tuning_update(request: MotionTuningRequest) -> dict[str, Any]:
    return await _call(service.set_motion_tuning, request, broadcast=False)


@app.post("/api/v1/motion/tuning/reset")
async def motion_tuning_reset() -> dict[str, Any]:
    return await _call(service.reset_motion_tuning, broadcast=False)


@app.get("/api/v1/motion/continuous-jog/status")
async def motion_continuous_jog_status() -> dict[str, Any]:
    return api_success(service.continuous_jog_status())


@app.post("/api/v1/motion/continuous-jog/start")
async def motion_continuous_jog_start(request: ContinuousJogStartRequest) -> dict[str, Any]:
    return await _call(service.start_continuous_jog, request)


@app.post("/api/v1/motion/continuous-jog/stop")
async def motion_continuous_jog_stop() -> dict[str, Any]:
    return await _call(service.stop_continuous_jog)


@app.post("/api/v1/motion/move-joints")
async def motion_move_joints(request: MoveJointsRequest) -> dict[str, Any]:
    return await _call(service.move_joints, request)


@app.post("/api/v1/motion/cartesian-jog")
async def motion_cartesian_jog(request: CartesianJogRequest) -> dict[str, Any]:
    return await _call(service.cartesian_jog, request)


@app.post("/api/v1/motion/move-pose")
async def motion_move_pose(request: MovePoseRequest) -> dict[str, Any]:
    return await _call(service.move_pose, request)


@app.post("/api/v1/motion/home")
async def motion_home(request: HomeRequest) -> dict[str, Any]:
    return await _call(service.home, request)


@app.get("/api/v1/motion/home-precheck")
async def motion_home_precheck() -> dict[str, Any]:
    return api_success(service.home_precheck())


@app.post("/api/v1/motion/stop")
async def motion_stop() -> dict[str, Any]:
    return await _call(service.stop)


@app.post("/api/v1/motion/gripper")
async def motion_gripper(request: GripperRequest) -> dict[str, Any]:
    return await _call(service.set_gripper, request)


# ----------------------------------------------------------------------
# 视觉跟随。跟随控制器只调用阶段八 /motion/joint-step，不直接写舵机。
# ----------------------------------------------------------------------
@app.get("/api/v1/follow/status")
async def follow_status() -> dict[str, Any]:
    return api_success(service.follow_status())


@app.post("/api/v1/follow/start")
async def follow_start(request: FollowStartRequest) -> dict[str, Any]:
    return await _call(service.start_follow, request)


@app.post("/api/v1/follow/stop")
async def follow_stop() -> dict[str, Any]:
    return await _call(service.stop_follow)


@app.get("/api/v1/vision/health")
async def vision_health() -> dict[str, Any]:
    return api_success(service.vision_health())


@app.get("/api/v1/vision/latest")
async def vision_latest() -> dict[str, Any]:
    return api_success(service.vision_latest())


@app.get("/api/v1/vision/status")
async def vision_status() -> dict[str, Any]:
    return api_success(service.vision_status())


@app.get("/api/v1/vision/target/state")
async def vision_target_state() -> dict[str, Any]:
    return api_success(service.vision_target_state())


@app.post("/api/v1/vision/target/select")
async def vision_target_select(request: VisionTargetSelectRequest) -> dict[str, Any]:
    return api_success(service.vision_select_target(request.x, request.y, request.w, request.h))


@app.post("/api/v1/vision/target/reset")
async def vision_target_reset() -> dict[str, Any]:
    return api_success(service.vision_reset_target())


@app.get("/api/v1/vision/frame.jpg")
async def vision_frame() -> Response:
    content, media_type = service.vision_frame()
    return Response(content=content, media_type=media_type)


# ----------------------------------------------------------------------
# 姿态
# ----------------------------------------------------------------------
@app.get("/api/v1/poses")
async def poses() -> dict[str, Any]:
    return api_success(service.list_poses())


@app.get("/api/v1/poses/{name}")
async def poses_detail(name: str) -> dict[str, Any]:
    return api_success(service.get_pose(name))


@app.post("/api/v1/poses/save")
async def poses_save(request: SavePoseRequest) -> dict[str, Any]:
    return await _call(service.save_pose, request)


@app.post("/api/v1/poses/goto")
async def poses_goto(request: GotoPoseRequest) -> dict[str, Any]:
    return await _call(service.goto_pose, request)


@app.delete("/api/v1/poses/{name}")
async def poses_delete(name: str) -> dict[str, Any]:
    return await _call(service.delete_pose, name)


# ----------------------------------------------------------------------
# 动作
# ----------------------------------------------------------------------
@app.get("/api/v1/actions")
async def actions() -> dict[str, Any]:
    return api_success(service.list_actions())


@app.get("/api/v1/actions/recording/status")
async def actions_recording_status() -> dict[str, Any]:
    return api_success(service.action_recording_status())


@app.post("/api/v1/actions/recording/start")
async def actions_recording_start(request: ActionRecordingStartRequest) -> dict[str, Any]:
    return await _call(service.start_action_recording, request)


@app.post("/api/v1/actions/recording/capture")
async def actions_recording_capture(request: ActionRecordingCaptureRequest) -> dict[str, Any]:
    return await _call(service.capture_action_recording_pose, request)


@app.post("/api/v1/actions/recording/save")
async def actions_recording_save() -> dict[str, Any]:
    return await _call(service.save_action_recording)


@app.post("/api/v1/actions/recording/cancel")
async def actions_recording_cancel() -> dict[str, Any]:
    return await _call(service.cancel_action_recording)


@app.get("/api/v1/actions/{name}")
async def action_detail(name: str) -> dict[str, Any]:
    return api_success(service.get_action(name))


@app.delete("/api/v1/actions/{name}")
async def action_delete(name: str) -> dict[str, Any]:
    return await _call(service.delete_action, name)


@app.post("/api/v1/actions/play")
async def actions_play(request: PlayActionRequest) -> dict[str, Any]:
    return await _call(service.play_action, request)


@app.post("/api/v1/actions/pause")
async def actions_pause() -> dict[str, Any]:
    return await _call(service.pause_action)


@app.post("/api/v1/actions/resume")
async def actions_resume() -> dict[str, Any]:
    return await _call(service.resume_action)


@app.post("/api/v1/actions/stop")
async def actions_stop() -> dict[str, Any]:
    return await _call(service.stop_action)


# ----------------------------------------------------------------------
# 运动学辅助接口。前端只展示计算结果，执行仍走 /api/v1/motion/move-pose 或 move-joints。
# ----------------------------------------------------------------------
@app.get("/api/v1/kinematics/status")
async def kinematics_status() -> dict[str, Any]:
    return api_success(service.kinematics_status())


@app.get("/api/v1/kinematics/render.jpg")
async def kinematics_render(width: int = Query(960, ge=320, le=1600), height: int = Query(640, ge=240, le=1200)) -> Response:
    image_bytes, media_type = service.kinematics_render(width=width, height=height)
    return Response(content=image_bytes, media_type=media_type, headers={"Cache-Control": "no-store"})


@app.post("/api/v1/kinematics/fk")
async def kinematics_fk(request: FKRequest) -> dict[str, Any]:
    return api_success(service.compute_fk(request.joints_deg))


@app.post("/api/v1/kinematics/ik")
async def kinematics_ik(request: IKRequest) -> dict[str, Any]:
    return api_success(service.compute_ik(request.xyz, request.rpy))


# ----------------------------------------------------------------------
# WebSocket 状态推送
# ----------------------------------------------------------------------
@app.websocket("/api/v1/ws/state")
async def ws_state(websocket: WebSocket) -> None:
    await websocket_manager.connect(websocket)
    interval = max(0.05, float(CONFIG.get("app", {}).get("state_poll_interval_ms", 500)) / 1000.0)
    try:
        await websocket_manager.send_json(websocket, service.websocket_payload())
        while True:
            # 浏览器通常只接收状态，不需要发消息；sleep 失败时连接会在 send_json 处断开。
            import asyncio

            await asyncio.sleep(interval)
            await websocket_manager.send_json(websocket, service.websocket_payload())
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        try:
            await websocket_manager.send_json(websocket, {"type": "error", "message": f"状态推送失败：{exc}"})
        except Exception:
            pass
    finally:
        await websocket_manager.disconnect(websocket)


install_static_routes(app, BASE_DIR)
