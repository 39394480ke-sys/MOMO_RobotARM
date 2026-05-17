"""阶段八 FastAPI 应用。

app.py 只负责路由、异常处理和静态前端挂载；业务逻辑在 service.py。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .errors import WebAPIError, api_error, api_success
from .schemas import (
    CartesianJogRequest,
    ConnectRequest,
    FKRequest,
    FollowStartRequest,
    GotoPoseRequest,
    GripperRequest,
    HomeRequest,
    IKRequest,
    JointStepRequest,
    ModeRequest,
    MoveJointsRequest,
    MovePoseRequest,
    PlayActionRequest,
    SavePoseRequest,
)
from .service import WebControlService
from .static_server import install_static_routes
from .websocket_manager import WebSocketManager


BASE_DIR = Path(__file__).resolve().parents[1]
CONFIG = None


def load_web_config(path: str | Path | None = None) -> dict[str, Any]:
    config_path = Path(path) if path else BASE_DIR / "Web配置.yaml"
    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    except Exception:
        data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("Web配置.yaml 最外层必须是对象。")
    return data


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


# ----------------------------------------------------------------------
# 运动控制
# ----------------------------------------------------------------------
@app.post("/api/v1/motion/joint-step")
async def motion_joint_step(request: JointStepRequest) -> dict[str, Any]:
    return await _call(service.joint_step, request)


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


# ----------------------------------------------------------------------
# 姿态
# ----------------------------------------------------------------------
@app.get("/api/v1/poses")
async def poses() -> dict[str, Any]:
    return api_success(service.list_poses())


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


@app.get("/api/v1/actions/{name}")
async def action_detail(name: str) -> dict[str, Any]:
    return api_success(service.get_action(name))


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
