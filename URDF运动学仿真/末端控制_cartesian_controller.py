"""末端笛卡尔控制器。

这个模块只负责：
目标末端位姿 -> IK -> 调用已有控制器 move_joints / 移动到关节角度。

它不直接调用舵机驱动，也不写真实舵机寄存器。
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Sequence

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, KinematicsModel, 加载运动学配置


class CartesianController:
    def __init__(
        self,
        arm_controller: Any,
        kinematics_model: KinematicsModel,
        joint_names: Sequence[str] | None = None,
        controller_unit: str = "deg",
        dry_run: bool = True,
    ) -> None:
        self.arm_controller = arm_controller
        self.kinematics_model = kinematics_model
        self.joint_names = list(joint_names or SDK_JOINT_NAMES)
        self.controller_unit = str(controller_unit or "deg").lower()
        self.dry_run = bool(dry_run)
        self.config = 加载运动学配置()

    def get_current_joints_deg(self) -> list[float]:
        controller = self.arm_controller

        if hasattr(controller, "get_state"):
            state = controller.get_state()
            angles = state.get("关节角度") if isinstance(state, dict) else None
            if isinstance(angles, dict):
                return [float(angles.get(name, 0.0)) for name in self.joint_names]
            if isinstance(angles, list):
                return [float(value) for value in angles[: len(self.joint_names)]]

        if hasattr(controller, "获取当前状态"):
            state = controller.获取当前状态()
            angles = state.get("关节角度") if isinstance(state, dict) else None
            if isinstance(angles, list):
                return [float(value) for value in angles[: len(self.joint_names)]]

        current_joint_deg = getattr(controller, "current_joint_deg", None)
        if isinstance(current_joint_deg, dict):
            return [float(current_joint_deg.get(name, 0.0)) for name in self.joint_names]

        current_angles = getattr(controller, "当前角度", None)
        if isinstance(current_angles, list):
            return [float(value) for value in current_angles[: len(self.joint_names)]]

        return [0.0 for _ in self.joint_names]

    def get_end_effector_pose(self) -> dict[str, list[float]]:
        q_rad = [math.radians(value) for value in self.get_current_joints_deg()]
        return self.kinematics_model.forward(q_rad)

    def move_pose(
        self,
        xyz: Sequence[float],
        rpy: Sequence[float] | None = None,
        duration: float = 1.0,
        wait: bool = True,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        config = self.config.get("kinematics", {})
        seed_q = [math.radians(value) for value in self.get_current_joints_deg()]
        ik = self.kinematics_model.inverse(
            target_xyz=xyz,
            target_rpy=rpy,
            seed_q_user=seed_q,
            max_iters=int(config.get("ik_max_iters", 200)),
            residual_threshold=max(1e-6, float(config.get("ik_target_tol_m", 0.001)) * 0.5),
        )
        max_pos_err = float(config.get("max_ee_pos_err_m", 0.03))
        orientation_tol = float(config.get("ik_orientation_tol_rad", 0.02))
        if float(ik["position_error_m"]) > max_pos_err:
            return {
                "ok": False,
                "错误": f"IK 位置误差过大：{float(ik['position_error_m']):.4f} m > {max_pos_err:.4f} m，禁止执行。",
                "ik": ik,
            }
        if rpy is not None and ik["orientation_error_rad"] is not None:
            if float(ik["orientation_error_rad"]) > orientation_tol:
                return {
                    "ok": False,
                    "错误": (
                        f"IK 姿态误差过大：{float(ik['orientation_error_rad']):.4f} rad "
                        f"> {orientation_tol:.4f} rad，禁止执行。"
                    ),
                    "ik": ik,
                }

        target_deg = {
            name: math.degrees(float(ik["q_user_rad"][idx]))
            for idx, name in enumerate(self.joint_names)
        }
        should_dry_run = self.dry_run if dry_run is None else bool(dry_run)
        output: dict[str, Any] = {
            "ok": True,
            "dry_run": should_dry_run,
            "target_xyz_m": [float(value) for value in xyz],
            "target_rpy_rad": [float(value) for value in rpy] if rpy is not None else None,
            "target_joints_deg": target_deg,
            "ik": ik,
        }
        if should_dry_run:
            output["message"] = "dry-run：只计算 IK，不调用已有控制器移动。"
            return output

        move_result = self._call_move_joints(target_deg, duration=duration, wait=wait)
        output["move_result"] = move_result
        output["ok"] = self._result_ok(move_result)
        return output

    def move_delta(
        self,
        dx: float = 0.0,
        dy: float = 0.0,
        dz: float = 0.0,
        drx: float = 0.0,
        dry: float = 0.0,
        drz: float = 0.0,
        frame: str = "base",
        duration: float = 1.0,
        wait: bool = True,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        current_pose = self.get_end_effector_pose()
        target_xyz, target_rpy = self.kinematics_model.compose_delta_target(
            current_xyz=current_pose["xyz"],
            current_rpy=current_pose["rpy"],
            delta_xyz=[dx, dy, dz],
            delta_rpy=[drx, dry, drz],
            frame=frame,
        )
        constrain_orientation = any(abs(float(value)) > 1e-12 for value in (drx, dry, drz))
        result = self.move_pose(
            target_xyz,
            rpy=target_rpy if constrain_orientation else None,
            duration=duration,
            wait=wait,
            dry_run=dry_run,
        )
        result["action"] = "move_delta"
        result["frame"] = "tool" if str(frame).strip().lower() == "tool" else "base"
        result["current_pose"] = current_pose
        result["target_pose"] = {"xyz": target_xyz, "rpy": target_rpy}
        return result

    def move_tcp(
        self,
        x: float,
        y: float,
        z: float,
        rpy: Sequence[float] | None = None,
        frame: str = "base",
        duration: float = 1.0,
        wait: bool = True,
        dry_run: bool | None = None,
    ) -> dict[str, Any]:
        frame_norm = "tool" if str(frame).strip().lower() == "tool" else "base"
        if frame_norm == "tool":
            delta_rpy = list(rpy) if rpy is not None else [0.0, 0.0, 0.0]
            return self.move_delta(
                dx=x,
                dy=y,
                dz=z,
                drx=float(delta_rpy[0]),
                dry=float(delta_rpy[1]),
                drz=float(delta_rpy[2]),
                frame="tool",
                duration=duration,
                wait=wait,
                dry_run=dry_run,
            )
        return self.move_pose([x, y, z], rpy=rpy, duration=duration, wait=wait, dry_run=dry_run)

    def _call_move_joints(self, target_deg: dict[str, float], duration: float, wait: bool) -> Any:
        controller = self.arm_controller
        if hasattr(controller, "move_joints"):
            try:
                return controller.move_joints(target_deg, duration=duration, wait=wait)
            except TypeError:
                return controller.move_joints(target_deg)

        values = [float(target_deg[name]) for name in self.joint_names]
        if hasattr(controller, "移动到关节角度"):
            return controller.移动到关节角度(values)

        raise AttributeError("已有控制器没有 move_joints() 或 移动到关节角度() 方法。")

    @staticmethod
    def _result_ok(result: Any) -> bool:
        if isinstance(result, dict):
            if "ok" in result:
                return bool(result["ok"])
            if "成功" in result:
                return bool(result["成功"])
        if hasattr(result, "成功"):
            return bool(result.成功)
        return True


末端控制器 = CartesianController
