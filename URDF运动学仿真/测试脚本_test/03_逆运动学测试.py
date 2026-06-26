from __future__ import annotations

import math

import 运动学测试路径_test_paths  # noqa: F401
from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 打印_json


def to_model_q(values: list[float]) -> list[float]:
    return [float(value) / 1000.0 if SDK_JOINT_NAMES[idx] == "j10" else math.radians(float(value)) for idx, value in enumerate(values)]


def from_model_q(values: list[float]) -> dict[str, float]:
    return {
        name: float(values[idx]) * 1000.0 if name == "j10" else math.degrees(float(values[idx]))
        for idx, name in enumerate(SDK_JOINT_NAMES)
    }


if __name__ == "__main__":
    model = None
    try:
        model = 创建运动学模型(use_gui=False)
        known_deg = [20, 0, 25, 40, 10, 0]
        fk = model.forward(to_model_q(known_deg))
        ik = model.inverse(target_xyz=fk["xyz"], target_rpy=None, seed_q_user=[0, 0, 0, 0, 0, 0])
        打印_json(
            {
                "ok": True,
                "known_joints_deg": dict(zip(SDK_JOINT_NAMES, known_deg)),
                "fk_pose": fk,
                "ik_solution_deg": from_model_q(ik["q_user_rad"]),
                "position_error_m": ik["position_error_m"],
                "ik": ik,
            }
        )
    except Exception as exc:
        打印_json({"ok": False, "错误": str(exc)})
        raise SystemExit(1)
    finally:
        if model is not None:
            model.close()
