"""V1/V2 机械版本 profile 的统一加载与校验。"""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping

from 通用_io import deep_merge, read_structured


PROJECT_ROOT = Path(__file__).resolve().parent
PROFILE_DIR = PROJECT_ROOT / "配置"
JOINT_NAMES = ("j10", "j11", "j12", "j13", "j14", "j15")
SUPPORTED_VARIANTS = ("V1", "V2")


def validate_robot_variant(variant: object) -> str:
    """只接受精确的 V1/V2，避免拼写错误静默落到错误机械版本。"""

    if not isinstance(variant, str) or variant not in SUPPORTED_VARIANTS:
        raise ValueError(f"robot.variant 必须精确为 V1 或 V2，当前值：{variant!r}")
    return variant


def _require_mapping(payload: Mapping[str, Any], key: str, source: Path) -> dict[str, Any]:
    value = payload.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"robot profile 缺少对象 {key}：{source}")
    return dict(value)


def _validate_joint_map(value: object, field: str, source: Path) -> dict[str, float]:
    if not isinstance(value, Mapping) or set(value) != set(JOINT_NAMES):
        raise ValueError(f"robot profile 的 {field} 必须完整包含 {list(JOINT_NAMES)}：{source}")
    try:
        return {joint: float(value[joint]) for joint in JOINT_NAMES}
    except (TypeError, ValueError) as exc:
        raise ValueError(f"robot profile 的 {field} 必须全部为数值：{source}") from exc


def validate_robot_profile(
    payload: Mapping[str, Any],
    *,
    expected_variant: str | None = None,
    source: str | Path = "<memory>",
) -> dict[str, Any]:
    """校验并规范化一个 profile。"""

    profile_path = Path(source)
    robot = _require_mapping(payload, "robot", profile_path)
    kinematics = _require_mapping(payload, "kinematics", profile_path)
    hardware = _require_mapping(payload, "hardware", profile_path)

    variant = validate_robot_variant(robot.get("variant"))
    if expected_variant is not None and variant != validate_robot_variant(expected_variant):
        raise ValueError(f"robot profile variant 与文件选择不一致：期望 {expected_variant}，实际 {variant}")
    name = robot.get("name")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"robot profile 缺少 robot.name：{profile_path}")

    urdf_path = kinematics.get("urdf_path")
    target_frame = kinematics.get("target_frame")
    if not isinstance(urdf_path, str) or not urdf_path.strip():
        raise ValueError(f"robot profile 缺少 kinematics.urdf_path：{profile_path}")
    if not isinstance(target_frame, str) or not target_frame.strip():
        raise ValueError(f"robot profile 缺少 kinematics.target_frame：{profile_path}")

    kinematics_scales = _validate_joint_map(
        kinematics.get("joint_scales"),
        "kinematics.joint_scales",
        profile_path,
    )
    hardware_scales = _validate_joint_map(
        hardware.get("joint_scales"),
        "hardware.joint_scales",
        profile_path,
    )

    raw_limits = hardware.get("joint_limits")
    if not isinstance(raw_limits, Mapping) or set(raw_limits) != set(JOINT_NAMES):
        raise ValueError(f"robot profile 的 hardware.joint_limits 必须完整包含 {list(JOINT_NAMES)}：{profile_path}")
    limits: dict[str, list[float]] = {}
    for joint in JOINT_NAMES:
        pair = raw_limits[joint]
        if not isinstance(pair, (list, tuple)) or len(pair) != 2:
            raise ValueError(f"robot profile 的 hardware.joint_limits.{joint} 必须是 [min, max]：{profile_path}")
        try:
            lower, upper = float(pair[0]), float(pair[1])
        except (TypeError, ValueError) as exc:
            raise ValueError(f"robot profile 的 hardware.joint_limits.{joint} 必须是数值：{profile_path}") from exc
        if lower >= upper:
            raise ValueError(f"robot profile 的 hardware.joint_limits.{joint} 下限必须小于上限：{profile_path}")
        limits[joint] = [lower, upper]

    raw_reachable = hardware.get("raw_reachable_joints")
    if not isinstance(raw_reachable, list) or any(joint not in JOINT_NAMES for joint in raw_reachable):
        raise ValueError(f"robot profile 的 hardware.raw_reachable_joints 含未知关节：{profile_path}")
    if len(raw_reachable) != len(set(raw_reachable)):
        raise ValueError(f"robot profile 的 hardware.raw_reachable_joints 不得重复：{profile_path}")

    return {
        "robot": {"variant": variant, "name": name.strip()},
        "kinematics": {
            "urdf_path": urdf_path.strip(),
            "target_frame": target_frame.strip(),
            "joint_scales": kinematics_scales,
        },
        "hardware": {
            "joint_scales": hardware_scales,
            "joint_limits": limits,
            "raw_reachable_joints": list(raw_reachable),
        },
    }


def load_robot_profile(variant: object, profile_dir: str | Path | None = None) -> dict[str, Any]:
    """加载指定机械版本的 tracked profile。"""

    selected = validate_robot_variant(variant)
    directory = Path(profile_dir) if profile_dir is not None else PROFILE_DIR
    path = directory / f"robot_{selected.lower()}.yaml"
    if not path.is_file():
        raise ValueError(f"robot.variant={selected} 的 profile 不存在：{path}")
    return validate_robot_profile(read_structured(path), expected_variant=selected, source=path)


def apply_hardware_profile(
    config: Mapping[str, Any],
    profile: Mapping[str, Any],
    *,
    base_config: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """把 profile 的硬件权威字段强制写回真实配置兼容结构。"""

    result = deepcopy(dict(config))
    normalized = validate_robot_profile(profile)
    robot = result.setdefault("robot", {})
    profile_robot = normalized["robot"]
    hardware = normalized["hardware"]

    robot["variant"] = profile_robot["variant"]
    robot["name"] = profile_robot["name"]
    robot["joint_scales"] = deepcopy(hardware["joint_scales"])
    robot["关节减速比_joint_scales"] = deepcopy(hardware["joint_scales"])
    robot["joint_limits"] = deepcopy(hardware["joint_limits"])
    robot["raw_reachable_joints"] = list(hardware["raw_reachable_joints"])
    robot["joint_order"] = list(JOINT_NAMES)
    canonical_hardware = result.setdefault("hardware", {})
    canonical_hardware["joint_scales"] = deepcopy(hardware["joint_scales"])
    canonical_hardware["joint_limits"] = deepcopy(hardware["joint_limits"])
    canonical_hardware["raw_reachable_joints"] = list(hardware["raw_reachable_joints"])

    base_robot = dict((base_config or config).get("robot", {}))
    base_joints = {
        joint.get("key"): dict(joint)
        for joint in base_robot.get("joints", [])
        if isinstance(joint, Mapping) and joint.get("key") in JOINT_NAMES
    }
    effective_joints = {
        joint.get("key"): dict(joint)
        for joint in robot.get("joints", [])
        if isinstance(joint, Mapping) and joint.get("key") in JOINT_NAMES
    }
    structural_fields = ("key", "编号", "关节编号", "舵机ID", "模式")
    canonical_joints: list[dict[str, Any]] = []
    for key in JOINT_NAMES:
        joint = deep_merge(base_joints.get(key, {"key": key}), effective_joints.get(key, {}))
        for field in structural_fields:
            if field in base_joints.get(key, {}):
                joint[field] = deepcopy(base_joints[key][field])
        joint["key"] = key
        lower, upper = hardware["joint_limits"][key]
        joint["最小角度"] = lower
        joint["最大角度"] = upper
        joint["raw_reachable"] = key in hardware["raw_reachable_joints"]
        canonical_joints.append(joint)
    robot["joints"] = canonical_joints
    return result


__all__ = [
    "JOINT_NAMES",
    "PROFILE_DIR",
    "SUPPORTED_VARIANTS",
    "apply_hardware_profile",
    "load_robot_profile",
    "validate_robot_profile",
    "validate_robot_variant",
]
