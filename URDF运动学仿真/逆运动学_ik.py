"""独立 IK 逆运动学命令行工具。"""

from __future__ import annotations

import argparse
import math
from typing import Any

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 加载运动学配置, 打印_json


def _targets_to_model_q(values: list[float]) -> list[float]:
    return [float(value) / 1000.0 if SDK_JOINT_NAMES[idx] == "j10" else math.radians(float(value)) for idx, value in enumerate(values)]


def _model_q_to_targets(values: list[float]) -> dict[str, float]:
    return {
        name: float(values[idx]) * 1000.0 if name == "j10" else math.degrees(float(values[idx]))
        for idx, name in enumerate(SDK_JOINT_NAMES)
    }


def 计算IK(
    xyz: list[float],
    rpy: list[float] | None = None,
    seed_deg: list[float] | None = None,
    use_gui: bool = False,
) -> dict[str, Any]:
    config = 加载运动学配置()
    kinematics = config.get("kinematics", {})
    model = None
    try:
        model = 创建运动学模型(use_gui=use_gui)
        seed = seed_deg if seed_deg is not None else [0.0] * len(SDK_JOINT_NAMES)
        if len(seed) != len(SDK_JOINT_NAMES):
            return {"ok": False, "错误": f"--seed-deg 需要 {len(SDK_JOINT_NAMES)} 个角度。"}
        result = model.inverse(
            target_xyz=xyz,
            target_rpy=rpy,
            seed_q_user=_targets_to_model_q(seed),
            max_iters=int(kinematics.get("ik_max_iters", 200)),
            residual_threshold=max(1e-6, float(kinematics.get("ik_target_tol_m", 0.001)) * 0.5),
        )
        max_pos_err = float(kinematics.get("max_ee_pos_err_m", 0.03))
        orientation_tol = float(kinematics.get("ik_orientation_tol_rad", 0.02))
        ok = float(result["position_error_m"]) <= max_pos_err
        if rpy is not None and result["orientation_error_rad"] is not None:
            ok = ok and float(result["orientation_error_rad"]) <= orientation_tol
        output = {
            "ok": ok,
            "target_xyz_m": [float(value) for value in xyz],
            "target_rpy_rad": [float(value) for value in rpy] if rpy is not None else None,
            "solution_joints_deg": _model_q_to_targets(result["q_user_rad"]),
            "predicted_xyz_m": result["xyz"],
            "predicted_rpy_rad": result["rpy"],
            "position_error_m": result["position_error_m"],
            "orientation_error_rad": result["orientation_error_rad"],
            "backend": result["backend"],
        }
        if not ok:
            output["错误"] = (
                f"IK 误差过大，禁止执行。位置误差 {float(result['position_error_m']):.4f} m，"
                f"允许 {max_pos_err:.4f} m。"
            )
        return output
    except Exception as exc:
        return {"ok": False, "错误": str(exc)}
    finally:
        if model is not None:
            model.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="URDF 逆运动学 IK 测试")
    parser.add_argument("--xyz", nargs=3, type=float, required=True, metavar=("X", "Y", "Z"))
    parser.add_argument("--rpy", nargs=3, type=float, metavar=("ROLL", "PITCH", "YAW"))
    parser.add_argument("--seed-deg", nargs=6, type=float, metavar=("J10", "J11", "J12", "J13", "J14", "J15"))
    parser.add_argument("--gui", action="store_true", help="用 PyBullet GUI 打开模型")
    args = parser.parse_args()
    result = 计算IK(list(args.xyz), list(args.rpy) if args.rpy is not None else None, args.seed_deg, bool(args.gui))
    打印_json(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
