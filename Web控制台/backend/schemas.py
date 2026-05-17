"""阶段八 Web API 的 Pydantic 请求模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ConnectRequest(BaseModel):
    mode: Literal["sim", "dry_run", "real"] = "dry_run"
    confirm_text: str = ""


class JointStepRequest(BaseModel):
    joint_key: str
    delta_deg: float
    speed_percent: int = Field(50, ge=1, le=100)
    # 真实模式下前端会补充该字段；dry-run / sim 可以为空。
    confirm_text: str = ""


class MoveJointsRequest(BaseModel):
    targets_deg: dict[str, float]
    speed_percent: int = Field(50, ge=1, le=100)
    confirm_text: str = ""


class CartesianJogRequest(BaseModel):
    axis: Literal["+X", "-X", "+Y", "-Y", "+Z", "-Z", "+RX", "-RX", "+RY", "-RY", "+RZ", "-RZ"]
    coord_frame: Literal["base", "tool"] = "base"
    step_dist_mm: float = Field(5.0, ge=0.1, le=200.0)
    step_angle_deg: float = Field(5.0, ge=0.1, le=180.0)
    speed_percent: int = Field(50, ge=1, le=100)
    confirm_text: str = ""


class HomeRequest(BaseModel):
    speed_percent: int = Field(50, ge=1, le=100)
    confirm_text: str = ""


class GripperRequest(BaseModel):
    open_ratio: float = Field(..., ge=0.0, le=1.0)
    wait: bool = True
    confirm_text: str = ""


class SavePoseRequest(BaseModel):
    name: str
    description: str = ""


class GotoPoseRequest(BaseModel):
    name: str
    speed_percent: int = Field(50, ge=1, le=100)
    confirm_text: str = ""


class PlayActionRequest(BaseModel):
    name: str
    speed: float = Field(1.0, ge=0.1, le=3.0)
    loop: bool = False
    confirm_text: str = ""


class MovePoseRequest(BaseModel):
    xyz: list[float]
    rpy: list[float] | None = None
    speed_percent: int = Field(50, ge=1, le=100)
    confirm_text: str = ""


class FKRequest(BaseModel):
    joints_deg: list[float] = Field(..., min_items=5)


class IKRequest(BaseModel):
    xyz: list[float] = Field(..., min_items=3)
    rpy: list[float] | None = None


class ModeRequest(BaseModel):
    mode: Literal["sim", "dry_run", "real"] = "dry_run"
    confirm_text: str = ""


class FollowStartRequest(BaseModel):
    latest_url: str = "http://127.0.0.1:8000/latest"
    poll_interval: float | None = Field(None, gt=0.0)
    move_duration: float | None = Field(None, gt=0.0)
    robot_api_base: str | None = None
    pan_joint: str | None = None
    tilt_joint: str | None = None
    pan_gain: float | None = None
    tilt_gain: float | None = None
    dry_run: bool = True
    speed_percent: int | None = Field(None, ge=1, le=100)
    confirm_text: str = ""
