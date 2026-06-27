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


class ContinuousJogStartRequest(BaseModel):
    joint_key: str
    direction: int = Field(..., ge=-1, le=1)
    speed_deg_s: float = Field(5.0, gt=0.0, le=90.0)
    confirm_text: str = ""


class MotionTuningRequest(BaseModel):
    default_speed_percent: float | None = Field(None, ge=10.0, le=100.0)
    quick_step_duration_s: float | None = Field(None, ge=0.05, le=10.0)
    quick_step_frames: int | None = Field(None, ge=1, le=240)
    continuous_update_hz: float | None = Field(None, ge=2.0, le=60.0)
    continuous_target_horizon_s: float | None = Field(None, ge=0.0, le=2.0)
    playback_update_hz: float | None = Field(None, ge=2.0, le=60.0)
    jog_direction_overrides: dict[str, int] | None = None


class CalibrationCurrentAngleRequest(BaseModel):
    joint_key: str = "j12"
    current_angle_deg: float
    confirm_text: str = ""


class CalibrationBatchCurrentAngleRequest(BaseModel):
    joint_angles_deg: dict[str, float] = Field(..., min_items=1)
    confirm_text: str = ""


class AgentAskRequest(BaseModel):
    text: str = Field(..., min_length=1)
    speak: bool = False
    force_new_session: bool = False


class CinematicAnalyzeRequest(BaseModel):
    record_path: str = ""
    video_path: str = ""


class CinematicKeyframesRequest(BaseModel):
    project_path: str = Field(..., min_length=1)
    min_count: int = Field(3, ge=3, le=8)
    max_count: int = Field(8, ge=3, le=8)


class CinematicGenerateActionRequest(BaseModel):
    project_path: str = Field(..., min_length=1)
    action_name: str = ""


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


class ActionRecordingStartRequest(BaseModel):
    name: str = Field(..., min_length=1)
    source: Literal["web_record", "web_teach_mode"] = "web_record"
    confirm_text: str = ""


class ActionRecordingCaptureRequest(BaseModel):
    confirm_text: str = ""


class MovePoseRequest(BaseModel):
    xyz: list[float]
    rpy: list[float] | None = None
    speed_percent: int = Field(50, ge=1, le=100)
    confirm_text: str = ""


class FKRequest(BaseModel):
    joints_deg: list[float] = Field(..., min_items=6)


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
    rail_enabled: bool | None = None
    rail_start_mm: float | None = None
    rail_end_mm: float | None = None
    rail_speed_mm_s: float | None = Field(None, gt=0.0)
    rail_step_mm: float | None = Field(None, gt=0.0)
    rail_interval_sec: float | None = Field(None, gt=0.0)


class VisionTargetSelectRequest(BaseModel):
    x: int = Field(..., ge=0)
    y: int = Field(..., ge=0)
    w: int = Field(..., ge=1)
    h: int = Field(..., ge=1)
