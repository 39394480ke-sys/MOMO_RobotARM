from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 打印_json


def run_delta(model, current_rad, frame: str):
    current_pose = model.forward(current_rad)
    target_xyz, target_rpy = model.compose_delta_target(
        current_xyz=current_pose["xyz"],
        current_rpy=current_pose["rpy"],
        delta_xyz=[0.01, 0.0, 0.0],
        delta_rpy=[0.0, 0.0, 0.0],
        frame=frame,
    )
    ik = model.inverse(target_xyz=target_xyz, target_rpy=None, seed_q_user=current_rad)
    return {
        "frame": frame,
        "current_pose": current_pose,
        "target_pose": {"xyz": target_xyz, "rpy": target_rpy},
        "ik_solution_deg": {
            name: math.degrees(float(ik["q_user_rad"][idx]))
            for idx, name in enumerate(SDK_JOINT_NAMES)
        },
        "ik": ik,
    }


if __name__ == "__main__":
    model = None
    try:
        model = 创建运动学模型(use_gui=False)
        home = [0.0] * len(SDK_JOINT_NAMES)
        打印_json({"ok": True, "results": [run_delta(model, home, "base"), run_delta(model, home, "tool")]})
    except Exception as exc:
        打印_json({"ok": False, "错误": str(exc)})
        raise SystemExit(1)
    finally:
        if model is not None:
            model.close()
