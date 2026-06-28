"""阶段六通用工具。"""

from __future__ import annotations

import tempfile
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from 动作路径工具_motion_path_utils import ACTION_ROOT, PROJECT_ROOT, ensure_project_root_on_path

BASE_DIR = ACTION_ROOT
ensure_project_root_on_path()

from 控制桥接_common import (  # noqa: E402
    JOINT_ORDER as COMMON_JOINT_ORDER,
    LEGACY_JOINT_ALIASES as COMMON_LEGACY_JOINT_ALIASES,
    MULTI_TURN_JOINTS as COMMON_MULTI_TURN_JOINTS,
    approximate_tcp_pose,
    ensure_import_paths,
    extract_joints_from_state as common_extract_joints_from_state,
    normalize_gripper_state as common_normalize_gripper_state,
    normalize_joint_targets as common_normalize_joint_targets,
    normalize_multi_turn_state as common_normalize_multi_turn_state,
    normalize_playback_speed as common_normalize_playback_speed,
    normalize_raw_present_position as common_normalize_raw_present_position,
    targets_to_kinematics_q,
)
from 通用_io import atomic_write_json, deep_merge, read_structured  # noqa: E402

STAGE3_DIR = PROJECT_ROOT / "仿真控制系统"
STAGE4_DIR = PROJECT_ROOT / "真实舵机控制"
STAGE5_DIR = PROJECT_ROOT / "URDF运动学仿真"

SCHEMA_VERSION = "arm_replay_sequence_v1"
JOINT_ORDER = list(COMMON_JOINT_ORDER)
MULTI_TURN_JOINTS = list(COMMON_MULTI_TURN_JOINTS)
LEGACY_JOINT_ALIASES = dict(COMMON_LEGACY_JOINT_ALIASES)
CHINESE_JOINT_NAMES = {
    "j10": "底盘导轨",
    "j11": "底座旋转",
    "j12": "肩部抬升",
    "j13": "肘部弯曲",
    "j14": "腕部俯仰",
    "j15": "腕部旋转",
}
DEFAULT_JOINT_SPEED_LIMITS = {
    "j10": 20.0,
    "j11": 45.0,
    "j12": 35.0,
    "j13": 45.0,
    "j14": 45.0,
    "j15": 60.0,
}


DEFAULT_CONFIG: dict[str, Any] = {
    "robot": {
        "sdk_joint_names": list(JOINT_ORDER),
        "中文关节名": dict(CHINESE_JOINT_NAMES),
        "multi_turn_joints": list(MULTI_TURN_JOINTS),
        "gripper_key": "gripper",
    },
    "files": {
        "action_library_dir": "动作库",
        "record_dir": "录制记录",
        "runtime_log": "运行日志/motion_runtime.log",
    },
    "recording": {
        "default_pose_count": 2,
        "wait_for_enter": True,
        "include_tcp_pose": True,
        "include_raw_position": True,
        "include_multi_turn_state": True,
        "include_gripper": True,
        "recorded_pose_duration_sec": 0.0,
    },
    "playback": {
        "default_duration_sec": 1.5,
        "default_interval_sec": 0.3,
        "update_hz": 25.0,
        "continuous_interpolation_default": True,
        "synchronized_segment_timing": True,
        "auto_duration_from_distance": True,
        "joint_speed_limits": dict(DEFAULT_JOINT_SPEED_LIMITS),
        "real_mode_min_duration_sec": 2.0,
        "real_mode_wait_until_reached": True,
        "real_mode_reach_timeout_sec": 12.0,
        "real_mode_reach_tolerance_deg": 2.0,
        "real_mode_reach_tolerance_mm": 2.0,
        "dry_run_default": True,
        "clamp_to_limits": True,
        "stop_on_limit_violation": True,
        "return_to_first_pose_before_replay": True,
    },
    "safety": {
        "max_single_step_deg": 15.0,
        "real_mode_max_single_step_deg": 5.0,
        "require_confirm_before_real_replay": False,
    },
}


class SimpleResult:
    def __init__(self, 成功: bool, 消息: str):
        self.成功 = bool(成功)
        self.消息 = str(消息)

    def __bool__(self) -> bool:
        return self.成功


def now_text() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def ensure_stage_paths() -> None:
    ensure_import_paths((STAGE3_DIR, STAGE4_DIR, STAGE5_DIR))


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else BASE_DIR / "动作配置.yaml"
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    data = read_structured(path)
    return deep_merge(deepcopy(DEFAULT_CONFIG), data)


def resolve_stage6_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def build_empty_sequence(
    name: str,
    description: str = "通过示教模式录制的动作",
    source: str = "teach_mode",
    config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    cfg = dict(config or DEFAULT_CONFIG)
    playback = cfg.get("playback", {})
    joint_order = list(cfg.get("robot", {}).get("sdk_joint_names", JOINT_ORDER))
    return {
        "schema_version": SCHEMA_VERSION,
        "name": name,
        "description": description,
        "created_at": now_text(),
        "source": source,
        "joint_order": joint_order,
        "pose_count": 0,
        "playback": {
            "default_duration_sec": float(playback.get("default_duration_sec", 1.5)),
            "default_interval_sec": float(playback.get("default_interval_sec", 0.3)),
        },
        "poses": [],
    }


def refresh_sequence_pose_count(sequence: dict[str, Any]) -> dict[str, Any]:
    """Synchronize ``pose_count`` with the current ``poses`` list."""

    poses = sequence.get("poses", []) if isinstance(sequence, dict) else []
    sequence["pose_count"] = len(poses) if isinstance(poses, list) else 0
    return sequence


def append_sequence_pose(sequence: dict[str, Any], pose: dict[str, Any]) -> dict[str, Any]:
    """Append one pose and keep sequence metadata consistent."""

    sequence.setdefault("poses", []).append(pose)
    return refresh_sequence_pose_count(sequence)


def summarize_sequence_payload(sequence: Mapping[str, Any]) -> dict[str, Any]:
    poses = sequence.get("poses", []) if isinstance(sequence, Mapping) else []
    poses = poses if isinstance(poses, list) else []
    total = sum(
        float(pose.get("duration_sec", 0)) + float(pose.get("hold_sec", 0))
        for pose in poses
        if isinstance(pose, Mapping)
    )
    tcp_points = [
        pose.get("tcp_pose", {}).get("xyz")
        for pose in poses
        if isinstance(pose, Mapping)
        and isinstance(pose.get("tcp_pose"), Mapping)
        and pose.get("tcp_pose", {}).get("xyz") is not None
    ]
    return {
        "动作名称": sequence.get("name") if isinstance(sequence, Mapping) else None,
        "pose_count": len(poses),
        "创建时间": sequence.get("created_at") if isinstance(sequence, Mapping) else None,
        "总时长": round(total, 3),
        "是否包含 raw": any(pose.get("raw_present_position") for pose in poses if isinstance(pose, Mapping)),
        "是否包含 tcp_pose": any(pose.get("tcp_pose") for pose in poses if isinstance(pose, Mapping)),
        "是否包含 gripper": any((pose.get("gripper") or {}).get("available") for pose in poses if isinstance(pose, Mapping)),
        "是否包含 multi_turn_state": any(pose.get("multi_turn_state") for pose in poses if isinstance(pose, Mapping)),
        "末端轨迹点数": len(tcp_points),
        "末端轨迹起点": tcp_points[0] if tcp_points else None,
        "末端轨迹终点": tcp_points[-1] if tcp_points else None,
    }


def normalize_joint_targets(value: Any, joint_order: list[str] | None = None) -> dict[str, float]:
    order = joint_order or JOINT_ORDER
    return common_normalize_joint_targets(
        value,
        order,
        ignore_unknown=True,
        legacy_5_joint_list=True,
        fill_missing=not isinstance(value, (list, tuple)),
    )


def extract_state(controller: Any) -> dict[str, Any]:
    if hasattr(controller, "get_state"):
        state = controller.get_state()
    elif hasattr(controller, "获取当前状态"):
        legacy = controller.获取当前状态()
        state = {
            "关节角度": legacy.get("关节角度", []),
            "夹爪": legacy.get("夹爪"),
        }
    else:
        state = {}
    if isinstance(state, Mapping) and "data" in state and any(key in state for key in ("ok", "message")):
        data = state.get("data")
        if isinstance(data, Mapping):
            return dict(data)
    return state if isinstance(state, dict) else {}


def state_joint_targets(state: Mapping[str, Any], joint_order: list[str]) -> dict[str, float]:
    return common_extract_joints_from_state(
        state,
        joint_order,
        keys=("joint_state", "joint_targets_deg", "关节角度", "joints_deg"),
        ignore_unknown=True,
        legacy_5_joint_list=True,
        fill_missing=False,
    )


def normalize_gripper_state(state: Mapping[str, Any]) -> dict[str, Any]:
    return common_normalize_gripper_state(state)


def normalize_multi_turn_state(state: Mapping[str, Any], multi_turn_joints: list[str]) -> dict[str, dict[str, Any]]:
    return common_normalize_multi_turn_state(state, multi_turn_joints)


def normalize_raw_present_position(raw_present_position: Any) -> dict[str, int] | None:
    return common_normalize_raw_present_position(raw_present_position)


def normalize_playback_speed(speed: Any, default: float = 1.0) -> float:
    return common_normalize_playback_speed(speed, default)


def compute_tcp_pose_if_possible(joint_targets_deg: Mapping[str, float], explicit_tcp_pose: Any = None) -> Any:
    if explicit_tcp_pose is not None:
        return explicit_tcp_pose
    ensure_stage_paths()
    try:
        from 运动学模型_kinematics_model import 创建运动学模型

        model = 创建运动学模型(use_gui=False)
        return model.forward(targets_to_kinematics_q(joint_targets_deg))
    except Exception:
        return approximate_tcp_pose(joint_targets_deg)


def is_dry_run_controller(controller: Any) -> bool:
    if hasattr(controller, "is_dry_run"):
        try:
            return bool(controller.is_dry_run())
        except Exception:
            return True
    mode = getattr(controller, "mode", None) or getattr(controller, "模式", None)
    if mode:
        return "dry" in str(mode).lower() or "仿真" in str(mode)
    return True


def is_real_mode_controller(controller: Any) -> bool:
    return not is_dry_run_controller(controller)


def call_move_joints(controller: Any, target_deg_by_joint: Mapping[str, float], multi_turn_raw: Mapping[str, float] | None = None) -> tuple[bool, str]:
    target = {key: float(value) for key, value in target_deg_by_joint.items()}
    if hasattr(controller, "move_joints"):
        method = controller.move_joints
        if multi_turn_raw:
            try:
                result = method(target, multi_turn_targets_continuous_raw=dict(multi_turn_raw))
                return result_to_tuple(result)
            except TypeError:
                print("当前控制器不支持多圈 continuous_raw 回放，已退化为角度回放。")
        result = method(target)
        return result_to_tuple(result)
    if hasattr(controller, "移动到关节角度"):
        result = controller.移动到关节角度([target[joint] for joint in JOINT_ORDER])
        return result_to_tuple(result)
    return False, "控制器不支持 move_joints / 移动到关节角度。"


def call_set_gripper(controller: Any, gripper_payload: Mapping[str, Any]) -> tuple[bool, str]:
    if not gripper_payload or gripper_payload.get("available") is not True:
        return True, "夹爪不可用，已跳过。"
    open_value = gripper_payload.get("open_percent")
    if open_value is None and gripper_payload.get("open_ratio") is not None:
        open_value = float(gripper_payload["open_ratio"]) * 100.0
    if open_value is not None:
        if hasattr(controller, "set_gripper"):
            return result_to_tuple(controller.set_gripper(float(open_value)))
        if hasattr(controller, "设置夹爪"):
            return result_to_tuple(controller.设置夹爪(float(open_value)))
        print("当前控制器不支持夹爪 set_gripper，已跳过夹爪回放。")
        return True, "控制器不支持夹爪。"
    if "present_raw" in gripper_payload and hasattr(controller, "write_gripper_raw"):
        return result_to_tuple(controller.write_gripper_raw(int(gripper_payload["present_raw"])))
    print("当前控制器不支持夹爪 raw 回放，已跳过夹爪回放。")
    return True, "控制器不支持夹爪 raw。"


def call_stop(controller: Any) -> tuple[bool, str]:
    if hasattr(controller, "stop"):
        return result_to_tuple(controller.stop())
    if hasattr(controller, "停止播放"):
        controller.停止播放()
        return True, "已停止。"
    return True, "控制器没有 stop，阶段六已停止下发后续姿态。"


def result_to_tuple(result: Any) -> tuple[bool, str]:
    if result is None:
        return True, "完成。"
    if isinstance(result, tuple) and len(result) >= 2:
        return bool(result[0]), str(result[1])
    if hasattr(result, "成功"):
        return bool(result.成功), str(getattr(result, "消息", ""))
    if isinstance(result, Mapping):
        if "成功" in result:
            return bool(result["成功"]), str(result.get("消息", ""))
        if "ok" in result:
            return bool(result["ok"]), str(result.get("message", result.get("消息", "")))
    return bool(result), str(result)


class SimulatedStage6Controller:
    """阶段六测试和默认 CLI 使用的仿真控制器。

    它优先包裹阶段三的机械臂模型，并额外暴露 get_state / move_joints /
    set_gripper，便于阶段六统一调用。
    """

    def __init__(self):
        ensure_stage_paths()
        try:
            from 机械臂模型_robot_arm import 机械臂模型

            config = read_structured(STAGE3_DIR / "配置_config.yaml")
            self.robot = 机械臂模型(config)
        except Exception:
            self.robot = None
            self.current = {joint: 0.0 for joint in JOINT_ORDER}
            self.gripper = 50.0
        self.mode = "仿真"
        self.joint_order = list(JOINT_ORDER)

    def connect(self) -> SimpleResult:
        return SimpleResult(True, "仿真控制器已就绪。")

    def is_dry_run(self) -> bool:
        return True

    def get_state(self) -> dict[str, Any]:
        if self.robot is not None:
            state = self.robot.获取当前状态()
            joints = normalize_joint_targets(state.get("关节角度", []), self.joint_order)
            gripper_value = float(state.get("夹爪", 50.0))
        else:
            joints = dict(self.current)
            gripper_value = float(self.gripper)
        raw = {joint: 2047 + int(round(joints[joint] * 10)) for joint in self.joint_order}
        raw.update({"j10": 2047, "j12": 2241, "j13": 6628, "j15": 311})
        multi = {}
        for joint in MULTI_TURN_JOINTS:
            continuous = int(round(joints[joint] * 4096.0 / 360.0))
            multi[joint] = {
                "startup_raw": raw[joint],
                "current_raw": raw[joint] + continuous,
                "continuous_raw": continuous,
                "relative_raw": continuous,
                "motor_deg": joints[joint],
                "joint_deg": joints[joint],
                "goal_raw": None,
            }
        return {
            "模式": "仿真",
            "已连接": True,
            "关节角度": joints,
            "raw_present_position": raw,
            "multi_turn_state": multi,
            "gripper_state": {
                "available": True,
                "present_raw": int(round(1000 + gripper_value * 20)),
                "open_ratio": gripper_value / 100.0,
                "open_percent": int(round(gripper_value)),
            },
            "tcp_pose": compute_tcp_pose_if_possible(joints, None),
        }

    def move_joints(self, target_deg_by_joint: Mapping[str, float], multi_turn_targets_continuous_raw: Mapping[str, float] | None = None) -> SimpleResult:
        target = {joint: float(target_deg_by_joint[joint]) for joint in self.joint_order}
        if self.robot is not None:
            return self.robot.移动到关节角度([target[joint] for joint in self.joint_order])
        self.current = target
        return SimpleResult(True, "仿真关节已移动。")

    def set_gripper(self, open_value: float) -> SimpleResult:
        if self.robot is not None:
            return self.robot.设置夹爪(float(open_value))
        self.gripper = float(open_value)
        return SimpleResult(True, "仿真夹爪已设置。")

    def stop(self) -> SimpleResult:
        return SimpleResult(True, "仿真已停止。")


def create_stage4_controller(dry_run: bool = True) -> Any:
    ensure_stage_paths()
    from copy import deepcopy
    from 真实机械臂控制器_real_arm_controller import RealArmController

    original_config = read_structured(STAGE4_DIR / "真实配置.yaml")
    config = deepcopy(original_config)
    config.setdefault("transport", {})["dry_run"] = bool(dry_run)
    mode_name = "dry_run" if dry_run else "real"
    runtime_config = Path(tempfile.gettempdir()) / f"arm_stage6_{mode_name}_真实配置_runtime.yaml"
    atomic_write_json(runtime_config, config)
    controller = RealArmController(runtime_config)
    return controller


def create_dry_run_real_controller() -> Any:
    return create_stage4_controller(dry_run=True)


def create_real_controller() -> Any:
    return create_stage4_controller(dry_run=False)
