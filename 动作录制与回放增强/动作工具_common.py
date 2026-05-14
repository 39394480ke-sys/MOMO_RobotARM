"""阶段六通用工具。"""

from __future__ import annotations

import json
import math
import sys
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping


BASE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BASE_DIR.parent
STAGE3_DIR = PROJECT_ROOT / "仿真控制系统"
STAGE4_DIR = PROJECT_ROOT / "真实舵机控制"
STAGE5_DIR = PROJECT_ROOT / "URDF运动学仿真"

SCHEMA_VERSION = "momo_replay_sequence_v1"
JOINT_ORDER = ["shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_roll"]
MULTI_TURN_JOINTS = ["shoulder_lift", "elbow_flex", "wrist_roll"]
CHINESE_JOINT_NAMES = {
    "shoulder_pan": "底座旋转",
    "shoulder_lift": "肩部抬升",
    "elbow_flex": "肘部弯曲",
    "wrist_flex": "腕部俯仰",
    "wrist_roll": "腕部旋转",
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
    },
    "playback": {
        "default_duration_sec": 1.5,
        "default_interval_sec": 0.3,
        "update_hz": 25.0,
        "real_mode_min_duration_sec": 2.0,
        "dry_run_default": True,
        "clamp_to_limits": True,
        "stop_on_limit_violation": True,
        "return_to_first_pose_before_replay": True,
    },
    "safety": {
        "max_single_step_deg": 15.0,
        "real_mode_max_single_step_deg": 5.0,
        "require_confirm_before_real_replay": True,
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
    for path in (str(STAGE3_DIR), str(STAGE4_DIR), str(STAGE5_DIR)):
        if path not in sys.path:
            sys.path.insert(0, path)


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    path = Path(config_path) if config_path else BASE_DIR / "动作配置.yaml"
    if not path.is_absolute():
        path = BASE_DIR / path
    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)
    text = path.read_text(encoding="utf-8")
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(text) or {}
    except Exception:
        data = json.loads(text)
    return deep_merge(deepcopy(DEFAULT_CONFIG), data)


def deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in dict(override).items():
        if isinstance(value, Mapping) and isinstance(base.get(key), dict):
            base[key] = deep_merge(base[key], value)
        else:
            base[key] = value
    return base


def resolve_stage6_path(path_value: str | Path) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    return BASE_DIR / path


def read_json(path: str | Path) -> Any:
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def write_json(path: str | Path, payload: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, ensure_ascii=False, indent=2)
        file.write("\n")


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


def normalize_joint_targets(value: Any, joint_order: list[str] | None = None) -> dict[str, float]:
    order = joint_order or JOINT_ORDER
    if isinstance(value, Mapping):
        return {joint: float(value.get(joint, 0.0)) for joint in order}
    if isinstance(value, (list, tuple)):
        return {joint: float(value[index]) for index, joint in enumerate(order) if index < len(value)}
    return {joint: 0.0 for joint in order}


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
    return state if isinstance(state, dict) else {}


def state_joint_targets(state: Mapping[str, Any], joint_order: list[str]) -> dict[str, float]:
    for key in ("joint_state", "joint_targets_deg", "关节角度", "joints_deg"):
        if key in state:
            return normalize_joint_targets(state[key], joint_order)
    return {joint: 0.0 for joint in joint_order}


def normalize_gripper_state(state: Mapping[str, Any]) -> dict[str, Any]:
    raw = state.get("gripper_state", state.get("gripper", state.get("夹爪")))
    if raw is None:
        return {"available": False}
    if isinstance(raw, Mapping):
        if raw.get("available") is False:
            return {"available": False}
        present_raw = raw.get("present_raw", raw.get("raw", raw.get("goal_raw")))
        open_ratio = raw.get("open_ratio")
        open_percent = raw.get("open_percent", raw.get("open_value", raw.get("开合")))
        payload: dict[str, Any] = {"available": True}
        if present_raw is not None:
            payload["present_raw"] = int(round(float(present_raw)))
        if open_ratio is not None:
            payload["open_ratio"] = float(open_ratio)
            payload["open_percent"] = int(round(float(open_ratio) * 100))
        elif open_percent is not None:
            payload["open_percent"] = int(round(float(open_percent)))
            payload["open_ratio"] = float(open_percent) / 100.0
        return payload
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return {"available": False}
    return {"available": True, "open_ratio": value / 100.0, "open_percent": int(round(value))}


def normalize_multi_turn_state(state: Mapping[str, Any], multi_turn_joints: list[str]) -> dict[str, dict[str, Any]]:
    source = state.get("multi_turn_state") or {}
    if not isinstance(source, Mapping):
        source = {}
    result: dict[str, dict[str, Any]] = {}
    for joint in multi_turn_joints:
        item = source.get(joint, {})
        if isinstance(item, Mapping):
            current_raw = item.get("current_raw", item.get("present_raw", item.get("goal_raw")))
            relative_raw = item.get("relative_raw")
            continuous_raw = item.get("continuous_raw")
            if continuous_raw is None:
                continuous_raw = relative_raw if relative_raw is not None else 0
            result[joint] = {
                "startup_raw": item.get("startup_raw", item.get("home_present_raw")),
                "current_raw": current_raw,
                "continuous_raw": continuous_raw,
                "relative_raw": relative_raw if relative_raw is not None else continuous_raw,
                "motor_deg": item.get("motor_deg"),
                "joint_deg": item.get("joint_deg"),
                "goal_raw": item.get("goal_raw"),
            }
        else:
            result[joint] = {
                "startup_raw": None,
                "current_raw": None,
                "continuous_raw": 0,
                "relative_raw": 0,
                "motor_deg": None,
                "joint_deg": None,
                "goal_raw": None,
            }
    return result


def compute_tcp_pose_if_possible(joint_targets_deg: Mapping[str, float], explicit_tcp_pose: Any = None) -> Any:
    if explicit_tcp_pose is not None:
        return explicit_tcp_pose
    ensure_stage_paths()
    try:
        from 运动学模型_kinematics_model import 创建运动学模型

        model = 创建运动学模型(use_gui=False)
        q_rad = [math.radians(float(joint_targets_deg[joint])) for joint in JOINT_ORDER]
        return model.forward(q_rad)
    except Exception:
        return approximate_tcp_pose(joint_targets_deg)


def approximate_tcp_pose(joint_targets_deg: Mapping[str, float]) -> dict[str, Any]:
    """PyBullet 不可用时的教学级 TCP 兜底。

    真实或阶段五控制器提供 tcp_pose 时不会走这里。此值只保证动作文件包含
    TCP 字段，方便后续流程和摘要测试，不替代阶段五 URDF FK。
    """

    base = math.radians(float(joint_targets_deg.get("shoulder_pan", 0.0)))
    shoulder = math.radians(float(joint_targets_deg.get("shoulder_lift", 0.0)))
    elbow = math.radians(float(joint_targets_deg.get("elbow_flex", 0.0)))
    wrist = math.radians(float(joint_targets_deg.get("wrist_flex", 0.0)))
    l1, l2, l3 = 0.12, 0.12, 0.08
    reach = l1 * math.cos(shoulder) + l2 * math.cos(shoulder + elbow) + l3 * math.cos(shoulder + elbow + wrist)
    z = 0.08 + l1 * math.sin(shoulder) + l2 * math.sin(shoulder + elbow) + l3 * math.sin(shoulder + elbow + wrist)
    return {
        "xyz": [round(reach * math.cos(base), 6), round(reach * math.sin(base), 6), round(z, 6)],
        "rpy": [
            0.0,
            round(shoulder + elbow + wrist, 6),
            round(base + math.radians(float(joint_targets_deg.get("wrist_roll", 0.0))), 6),
        ],
        "source": "approximate_fk_without_pybullet",
    }


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

            config = read_json(STAGE3_DIR / "配置_config.yaml")
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
        raw.update({"shoulder_lift": 2241, "elbow_flex": 6628, "wrist_roll": 311})
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


def create_dry_run_real_controller() -> Any:
    ensure_stage_paths()
    from copy import deepcopy
    from 真实机械臂控制器_real_arm_controller import RealArmController

    original_config = read_json(STAGE4_DIR / "真实配置.yaml")
    config = deepcopy(original_config)
    config.setdefault("transport", {})["dry_run"] = True
    runtime_config = BASE_DIR / "运行日志" / "dry_run_真实配置_runtime.yaml"
    write_json(runtime_config, config)
    controller = RealArmController(runtime_config)
    return controller
