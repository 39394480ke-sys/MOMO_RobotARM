"""阶段五：URDF / PyBullet 运动学模型。

这个模块仿照 MomoAgent 的 PybulletKinematicsModel：
- URDF 负责机器人结构和 FK / IK。
- SDK 上层仍使用固定的 5 个逻辑关节顺序。
- joint_name_aliases 负责把 SDK 关节名映射到 URDF 关节名。
- 不直接控制真实舵机。
"""

from __future__ import annotations

import json
import math
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np

try:
    import pybullet as _pb

    PYBULLET_AVAILABLE = True
    PYBULLET_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - 由用户环境决定
    _pb = None
    PYBULLET_AVAILABLE = False
    PYBULLET_IMPORT_ERROR = exc

try:
    import yaml as _yaml

    YAML_AVAILABLE = True
    YAML_IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover - 由用户环境决定
    _yaml = None
    YAML_AVAILABLE = False
    YAML_IMPORT_ERROR = exc


SDK_JOINT_NAMES = [
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
]

JOINT_NAME_ALIASES = {
    "shoulder_pan": "shoulder",
    "shoulder_lift": "shoulder_lift",
    "elbow_flex": "elbow",
    "wrist_flex": "wrist",
    "wrist_roll": "wrist_roll",
}

DEFAULT_CONFIG: dict[str, Any] = {
    "robot": {
        "name": "soarmmoce",
        "urdf_path": "urdf/soarmoce_urdf.urdf",
        "target_frame": "wrist_roll",
        "sdk_joint_names": list(SDK_JOINT_NAMES),
        "joint_name_aliases": dict(JOINT_NAME_ALIASES),
        "joint_scales": {
            "shoulder_pan": 1.0,
            "shoulder_lift": -5.3,
            "elbow_flex": 5.6,
            "wrist_flex": -1.0,
            "wrist_roll": 1.0,
        },
        "model_offsets_deg": {joint_name: 0.0 for joint_name in SDK_JOINT_NAMES},
    },
    "kinematics": {
        "backend": "pybullet",
        "ik_max_iters": 200,
        "ik_target_tol_m": 0.001,
        "ik_orientation_tol_rad": 0.02,
        "max_ee_pos_err_m": 0.03,
        "seed_policy": "current",
    },
    "control": {
        "default_move_duration": 1.0,
        "cartesian_update_hz": 25.0,
        "linear_step_m": 0.01,
        "joint_step_deg": 5.0,
    },
    "viewer": {
        "use_gui": True,
        "fixed_base": True,
    },
}


def pybullet缺失提示() -> str:
    return "当前环境没有安装 pybullet。\n请运行：\npip install pybullet"


def yaml缺失提示() -> str:
    return "当前环境没有安装 pyyaml。\n请运行：\npip install pyyaml"


def _deep_merge(base: dict[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in dict(override).items():
        if isinstance(value, Mapping) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def 加载运动学配置(config_path: str | Path | None = None) -> dict[str, Any]:
    """加载阶段五配置。

    pyyaml 未安装时返回内置默认配置，让 URDF 检查工具仍可工作；
    FK / IK 仍会在需要 PyBullet 时给出中文安装提示。
    """

    base_dir = Path(__file__).resolve().parent
    path = Path(config_path) if config_path else base_dir / "运动学配置.yaml"
    if not path.is_absolute():
        path = base_dir / path

    if not path.exists():
        return deepcopy(DEFAULT_CONFIG)

    if not YAML_AVAILABLE or _yaml is None:
        config = deepcopy(DEFAULT_CONFIG)
        config["_warning"] = yaml缺失提示()
        return config

    with path.open("r", encoding="utf-8") as file:
        payload = _yaml.safe_load(file) or {}
    if not isinstance(payload, dict):
        raise ValueError(f"配置文件最外层必须是字典：{path}")
    return _deep_merge(DEFAULT_CONFIG, payload)


def 解析资源路径(path_text: str | Path, base_dir: str | Path | None = None) -> Path:
    path = Path(path_text).expanduser()
    if path.is_absolute():
        return path.resolve()
    root = Path(base_dir).resolve() if base_dir else Path(__file__).resolve().parent
    return (root / path).resolve()


def 创建运动学模型(config_path: str | Path | None = None, use_gui: bool | None = None) -> "KinematicsModel":
    config = 加载运动学配置(config_path)
    base_dir = Path(__file__).resolve().parent
    robot = config.get("robot", {})
    viewer = config.get("viewer", {})
    urdf_path = 解析资源路径(robot.get("urdf_path", "urdf/soarmoce_urdf.urdf"), base_dir)
    return KinematicsModel(
        urdf_path=urdf_path,
        sdk_joint_names=robot.get("sdk_joint_names", SDK_JOINT_NAMES),
        joint_name_aliases=robot.get("joint_name_aliases", JOINT_NAME_ALIASES),
        model_offsets_deg=robot.get("model_offsets_deg", {}),
        target_frame=robot.get("target_frame", "wrist_roll"),
        use_gui=bool(viewer.get("use_gui", False)) if use_gui is None else bool(use_gui),
    )


def _require_pybullet() -> None:
    if not PYBULLET_AVAILABLE or _pb is None:
        raise RuntimeError(pybullet缺失提示())


def _normalized_name(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "").replace("-", "_")


def _wrap_angle_rad(value: float) -> float:
    return float((float(value) + math.pi) % (2.0 * math.pi) - math.pi)


def _angular_error_norm(target_rpy: Sequence[float], actual_rpy: Sequence[float]) -> float:
    diff = [_wrap_angle_rad(float(target_rpy[idx]) - float(actual_rpy[idx])) for idx in range(3)]
    return float(np.linalg.norm(np.asarray(diff, dtype=float)))


def _matrix_to_rpy(rotation: np.ndarray) -> np.ndarray:
    rot = np.asarray(rotation, dtype=float).reshape(3, 3)
    sy = math.sqrt(float(rot[0, 0]) ** 2 + float(rot[1, 0]) ** 2)
    singular = sy < 1e-8
    if not singular:
        roll = math.atan2(float(rot[2, 1]), float(rot[2, 2]))
        pitch = math.atan2(-float(rot[2, 0]), sy)
        yaw = math.atan2(float(rot[1, 0]), float(rot[0, 0]))
    else:
        roll = math.atan2(-float(rot[1, 2]), float(rot[1, 1]))
        pitch = math.atan2(-float(rot[2, 0]), sy)
        yaw = 0.0
    return np.asarray([roll, pitch, yaw], dtype=float)


def _rpy_to_matrix(rpy: Sequence[float]) -> np.ndarray:
    _require_pybullet()
    quat = _pb.getQuaternionFromEuler([float(rpy[0]), float(rpy[1]), float(rpy[2])])
    matrix = _pb.getMatrixFromQuaternion(quat)
    return np.asarray(matrix, dtype=float).reshape(3, 3)


class KinematicsModel:
    """URDF-backed FK / IK helper.

    q_user_rad 是上层 SDK 的 5 轴逻辑关节弧度，不包含夹爪。
    model_offsets_deg 只用于 URDF 模型显示/对齐，不写入真实舵机标定。
    """

    def __init__(
        self,
        urdf_path: str | Path,
        sdk_joint_names: Sequence[str],
        joint_name_aliases: Mapping[str, str],
        model_offsets_deg: Mapping[str, float],
        target_frame: str,
        user_joint_limits: Sequence[tuple[float, float]] | None = None,
        use_gui: bool = False,
    ) -> None:
        _require_pybullet()
        self.urdf_path = Path(urdf_path).expanduser().resolve()
        if not self.urdf_path.exists():
            raise FileNotFoundError(f"URDF 文件不存在：{self.urdf_path}")

        self.sdk_joint_names = [str(name) for name in sdk_joint_names]
        self.joint_name_aliases = {str(key): str(value) for key, value in dict(joint_name_aliases).items()}
        self.target_frame = str(target_frame or "wrist_roll").strip() or "wrist_roll"
        self.model_offsets_rad = np.asarray(
            [math.radians(float(dict(model_offsets_deg).get(name, 0.0))) for name in self.sdk_joint_names],
            dtype=float,
        )
        self.use_gui = bool(use_gui)
        self._client_id = _pb.connect(_pb.GUI if self.use_gui else _pb.DIRECT)
        if self._client_id < 0:
            raise RuntimeError("PyBullet 连接失败。")

        self._robot_id = _pb.loadURDF(
            str(self.urdf_path),
            basePosition=[0.0, 0.0, 0.0],
            baseOrientation=[0.0, 0.0, 0.0, 1.0],
            useFixedBase=True,
            physicsClientId=self._client_id,
        )

        self.movable_joint_index_by_name: dict[str, int] = {}
        self.movable_joint_index_by_link_name: dict[str, int] = {}
        self.movable_joint_limits_by_name: dict[str, tuple[float, float]] = {}
        self.movable_joint_link_name_by_name: dict[str, str] = {}
        self._movable_joint_parent_indices: set[int] = set()
        self.links: list[str] = ["base"]
        self.joints: list[dict[str, Any]] = []

        for joint_index in range(_pb.getNumJoints(self._robot_id, physicsClientId=self._client_id)):
            info = _pb.getJointInfo(self._robot_id, joint_index, physicsClientId=self._client_id)
            joint_name = info[1].decode("utf-8")
            joint_type = int(info[2])
            link_name = info[12].decode("utf-8")
            parent_index = int(info[16])
            lower = float(info[8])
            upper = float(info[9])
            self.links.append(link_name)
            self.joints.append(
                {
                    "index": int(joint_index),
                    "name": joint_name,
                    "type": int(joint_type),
                    "child_link": link_name,
                    "parent_index": parent_index,
                    "lower": lower,
                    "upper": upper,
                }
            )
            if joint_type not in (_pb.JOINT_REVOLUTE, _pb.JOINT_PRISMATIC):
                continue

            if (not math.isfinite(lower)) or (not math.isfinite(upper)) or lower >= upper:
                lower, upper = -math.pi, math.pi
            self.movable_joint_index_by_name[joint_name] = int(joint_index)
            self.movable_joint_index_by_link_name[link_name] = int(joint_index)
            self.movable_joint_limits_by_name[joint_name] = (lower, upper)
            self.movable_joint_link_name_by_name[joint_name] = link_name
            if parent_index >= 0:
                self._movable_joint_parent_indices.add(parent_index)
            _pb.resetJointState(self._robot_id, int(joint_index), 0.0, physicsClientId=self._client_id)

        if not self.movable_joint_index_by_name:
            raise RuntimeError(f"URDF 中没有找到可动关节：{self.urdf_path}")

        self.ordered_joint_indices: list[int] = []
        self.ordered_joint_urdf_names: list[str] = []
        self.ordered_joint_model_limits: list[tuple[float, float]] = []
        for sdk_joint_name in self.sdk_joint_names:
            urdf_joint_name = self._resolve_urdf_joint_name(sdk_joint_name)
            self.ordered_joint_urdf_names.append(urdf_joint_name)
            self.ordered_joint_indices.append(self.movable_joint_index_by_name[urdf_joint_name])
            self.ordered_joint_model_limits.append(self.movable_joint_limits_by_name[urdf_joint_name])

        requested_user_limits = list(user_joint_limits or [])
        self.ordered_joint_user_limits: list[tuple[float, float]] = []
        for idx, (lower, upper) in enumerate(list(self.ordered_joint_model_limits)):
            offset = float(self.model_offsets_rad[idx])
            user_lower = float(lower - offset)
            user_upper = float(upper - offset)
            if idx < len(requested_user_limits):
                req_lower, req_upper = requested_user_limits[idx]
                clipped_lower = max(min(float(req_lower), float(req_upper)), user_lower)
                clipped_upper = min(max(float(req_lower), float(req_upper)), user_upper)
                if clipped_lower <= clipped_upper:
                    user_lower, user_upper = clipped_lower, clipped_upper
                    self.ordered_joint_model_limits[idx] = (user_lower + offset, user_upper + offset)
            self.ordered_joint_user_limits.append((user_lower, user_upper))

        self.ee_link_index = self._resolve_end_effector_link_index(self.target_frame)
        if self.ee_link_index is None:
            raise RuntimeError(f"找不到末端 target_frame：{self.target_frame}")

    def close(self) -> None:
        client_id = getattr(self, "_client_id", None)
        if client_id is None or not PYBULLET_AVAILABLE or _pb is None:
            return
        try:
            _pb.disconnect(physicsClientId=int(client_id))
        finally:
            self._client_id = None

    def forward(self, q_user_rad: Sequence[float]) -> dict[str, list[float]]:
        q_model = self._user_to_model_q(q_user_rad)
        self._check_user_limits(q_user_rad)
        self._reset_joint_state_model(q_model)
        state = _pb.getLinkState(
            self._robot_id,
            int(self.ee_link_index),
            computeForwardKinematics=True,
            physicsClientId=self._client_id,
        )
        xyz = np.asarray(state[4], dtype=float)
        rpy = np.asarray(_pb.getEulerFromQuaternion(state[5]), dtype=float)
        return {"xyz": xyz.tolist(), "rpy": rpy.tolist()}

    def inverse(
        self,
        target_xyz: Sequence[float],
        target_rpy: Sequence[float] | None = None,
        seed_q_user: Sequence[float] | None = None,
        max_iters: int = 200,
        residual_threshold: float = 1e-5,
    ) -> dict[str, Any]:
        target_xyz_arr = np.asarray(target_xyz, dtype=float).reshape(3)
        target_rpy_arr = None if target_rpy is None else np.asarray(target_rpy, dtype=float).reshape(3)
        seed_q = np.zeros(len(self.sdk_joint_names), dtype=float) if seed_q_user is None else np.asarray(seed_q_user, dtype=float)
        seed_q = seed_q.reshape(len(self.sdk_joint_names))
        seed_q = self._clip_user_q(seed_q)

        lower_limits = [float(lower) for lower, _ in self.ordered_joint_model_limits]
        upper_limits = [float(upper) for _, upper in self.ordered_joint_model_limits]
        joint_ranges = [max(1e-4, upper - lower) for lower, upper in self.ordered_joint_model_limits]
        target_orientation = None
        if target_rpy_arr is not None:
            target_orientation = _pb.getQuaternionFromEuler(target_rpy_arr.tolist())

        def solve_once(seed_candidate: Sequence[float]) -> dict[str, Any]:
            seed_model = self._user_to_model_q(seed_candidate)
            self._reset_joint_state_model(seed_model)
            ik_kwargs = {
                "bodyUniqueId": self._robot_id,
                "endEffectorLinkIndex": int(self.ee_link_index),
                "targetPosition": target_xyz_arr.tolist(),
                "lowerLimits": lower_limits,
                "upperLimits": upper_limits,
                "jointRanges": joint_ranges,
                "restPoses": seed_model.tolist(),
                "maxNumIterations": max(1, int(max_iters)),
                "residualThreshold": max(1e-9, float(residual_threshold)),
                "physicsClientId": self._client_id,
            }
            if target_orientation is not None:
                ik_kwargs["targetOrientation"] = target_orientation
            q_full = _pb.calculateInverseKinematics(**ik_kwargs)

            q_values = list(q_full) if q_full is not None else []
            q_model = np.asarray(seed_model, dtype=float).copy()
            for ordered_idx, joint_index in enumerate(self.ordered_joint_indices):
                if joint_index < len(q_values):
                    raw_value = float(q_values[joint_index])
                elif ordered_idx < len(q_values):
                    raw_value = float(q_values[ordered_idx])
                else:
                    raw_value = float(q_model[ordered_idx])
                lower, upper = self.ordered_joint_model_limits[ordered_idx]
                q_model[ordered_idx] = float(np.clip(raw_value, lower, upper))

            q_user = self._clip_user_q(self._model_to_user_q(q_model))
            fk = self.forward(q_user)
            actual_xyz = np.asarray(fk["xyz"], dtype=float)
            actual_rpy = np.asarray(fk["rpy"], dtype=float)
            pos_error = float(np.linalg.norm(actual_xyz - target_xyz_arr))
            rot_error = _angular_error_norm(target_rpy_arr, actual_rpy) if target_rpy_arr is not None else None
            return {
                "q_user_rad": q_user.tolist(),
                "xyz": actual_xyz.tolist(),
                "rpy": actual_rpy.tolist(),
                "position_error_m": pos_error,
                "orientation_error_rad": rot_error,
                "backend": "pybullet",
            }

        best = solve_once(seed_q)
        if target_rpy_arr is not None:
            for _ in range(4):
                refined = solve_once(best["q_user_rad"])
                best_key = (
                    float("inf") if best["orientation_error_rad"] is None else float(best["orientation_error_rad"]),
                    float(best["position_error_m"]),
                )
                refined_key = (
                    float("inf")
                    if refined["orientation_error_rad"] is None
                    else float(refined["orientation_error_rad"]),
                    float(refined["position_error_m"]),
                )
                if refined_key >= best_key:
                    break
                best = refined
                if best["orientation_error_rad"] is not None and best["orientation_error_rad"] <= 1e-3:
                    break
        return best

    def compose_delta_target(
        self,
        current_xyz: Sequence[float],
        current_rpy: Sequence[float],
        delta_xyz: Sequence[float],
        delta_rpy: Sequence[float],
        frame: str,
    ) -> tuple[list[float], list[float]]:
        current_xyz_arr = np.asarray(current_xyz, dtype=float).reshape(3)
        current_rpy_arr = np.asarray(current_rpy, dtype=float).reshape(3)
        delta_xyz_arr = np.asarray(delta_xyz, dtype=float).reshape(3)
        delta_rpy_arr = np.asarray(delta_rpy, dtype=float).reshape(3)
        current_rot = _rpy_to_matrix(current_rpy_arr)
        delta_rot = _rpy_to_matrix(delta_rpy_arr)
        frame_norm = "tool" if str(frame or "").strip().lower() == "tool" else "base"

        if frame_norm == "tool":
            target_xyz = current_xyz_arr + current_rot @ delta_xyz_arr
            target_rot = current_rot @ delta_rot
        else:
            target_xyz = current_xyz_arr + delta_xyz_arr
            target_rot = delta_rot @ current_rot
        target_rpy = _matrix_to_rpy(target_rot)
        return target_xyz.tolist(), target_rpy.tolist()

    def joint_limits_report(self) -> dict[str, dict[str, float | str]]:
        report: dict[str, dict[str, float | str]] = {}
        for idx, sdk_name in enumerate(self.sdk_joint_names):
            lower, upper = self.ordered_joint_user_limits[idx]
            report[sdk_name] = {
                "urdf_joint": self.ordered_joint_urdf_names[idx],
                "lower_rad": float(lower),
                "upper_rad": float(upper),
                "lower_deg": math.degrees(float(lower)),
                "upper_deg": math.degrees(float(upper)),
            }
        return report

    def _resolve_urdf_joint_name(self, sdk_joint_name: str) -> str:
        alias_name = str(self.joint_name_aliases.get(sdk_joint_name, sdk_joint_name))
        if alias_name in self.movable_joint_index_by_name:
            return alias_name
        if sdk_joint_name in self.movable_joint_index_by_name:
            return sdk_joint_name
        alias_key = _normalized_name(alias_name)
        sdk_key = _normalized_name(sdk_joint_name)
        for candidate_name in self.movable_joint_index_by_name:
            if _normalized_name(candidate_name) in {alias_key, sdk_key}:
                return candidate_name
        raise KeyError(f"SDK 关节 {sdk_joint_name} 无法映射到 URDF 关节 {alias_name}")

    def _resolve_end_effector_link_index(self, target_frame: str) -> int | None:
        target_text = str(target_frame or "").strip()
        candidate_names = [target_text] if target_text else []
        if target_text in self.joint_name_aliases:
            candidate_names.append(self.joint_name_aliases[target_text])
        target_key = _normalized_name(target_text)
        for sdk_name, alias_name in self.joint_name_aliases.items():
            if _normalized_name(alias_name) == target_key:
                candidate_names.extend([alias_name, sdk_name])

        for candidate_name in candidate_names:
            if candidate_name in self.movable_joint_index_by_name:
                return self.movable_joint_index_by_name[candidate_name]
            if candidate_name in self.movable_joint_index_by_link_name:
                return self.movable_joint_index_by_link_name[candidate_name]

        candidate_keys = {_normalized_name(name) for name in candidate_names if str(name).strip()}
        for joint_name, joint_index in self.movable_joint_index_by_name.items():
            if _normalized_name(joint_name) in candidate_keys:
                return joint_index
        for link_name, joint_index in self.movable_joint_index_by_link_name.items():
            if _normalized_name(link_name) in candidate_keys:
                return joint_index

        movable_indices = set(self.movable_joint_index_by_name.values())
        leaves = sorted(movable_indices - self._movable_joint_parent_indices)
        if leaves:
            return leaves[-1]
        return sorted(movable_indices)[-1] if movable_indices else None

    def _user_to_model_q(self, q_user: Sequence[float]) -> np.ndarray:
        q_arr = np.asarray(q_user, dtype=float).reshape(-1)
        if q_arr.shape[0] != len(self.sdk_joint_names):
            raise ValueError(f"关节数量不对：需要 {len(self.sdk_joint_names)} 个，实际收到 {q_arr.shape[0]} 个。")
        return np.asarray(q_arr + self.model_offsets_rad, dtype=float)

    def _model_to_user_q(self, q_model: Sequence[float]) -> np.ndarray:
        q_arr = np.asarray(q_model, dtype=float).reshape(-1)
        if q_arr.shape[0] != len(self.sdk_joint_names):
            raise ValueError(f"关节数量不对：需要 {len(self.sdk_joint_names)} 个，实际收到 {q_arr.shape[0]} 个。")
        return np.asarray(q_arr - self.model_offsets_rad, dtype=float)

    def _clip_user_q(self, q_user: Sequence[float]) -> np.ndarray:
        q_arr = np.asarray(q_user, dtype=float).reshape(len(self.sdk_joint_names))
        for idx, (lower, upper) in enumerate(self.ordered_joint_user_limits):
            q_arr[idx] = float(np.clip(q_arr[idx], lower, upper))
        return q_arr

    def _check_user_limits(self, q_user: Sequence[float]) -> None:
        q_arr = np.asarray(q_user, dtype=float).reshape(len(self.sdk_joint_names))
        for idx, value in enumerate(q_arr):
            lower, upper = self.ordered_joint_user_limits[idx]
            if float(value) < lower - 1e-9 or float(value) > upper + 1e-9:
                name = self.sdk_joint_names[idx]
                raise ValueError(
                    f"IK/FK 关节角超出 URDF 范围：{name}={math.degrees(float(value)):.2f} 度，"
                    f"允许范围 [{math.degrees(lower):.2f}, {math.degrees(upper):.2f}] 度。"
                )

    def _reset_joint_state_model(self, q_model: Sequence[float]) -> None:
        q_arr = np.asarray(q_model, dtype=float).reshape(len(self.ordered_joint_indices))
        for idx, joint_index in enumerate(self.ordered_joint_indices):
            _pb.resetJointState(
                self._robot_id,
                int(joint_index),
                float(q_arr[idx]),
                physicsClientId=self._client_id,
            )


运动学模型 = KinematicsModel


def 打印_json(payload: Mapping[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


__all__ = [
    "JOINT_NAME_ALIASES",
    "KinematicsModel",
    "PYBULLET_AVAILABLE",
    "SDK_JOINT_NAMES",
    "YAML_AVAILABLE",
    "创建运动学模型",
    "加载运动学配置",
    "打印_json",
    "运动学模型",
]
