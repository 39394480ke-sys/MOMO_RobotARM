from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 打印_json


if __name__ == "__main__":
    model = None
    try:
        model = 创建运动学模型(use_gui=False)
        known_deg = [0, 25, 40, 10, 0]
        known_rad = [math.radians(value) for value in known_deg]
        fk = model.forward(known_rad)
        ik = model.inverse(target_xyz=fk["xyz"], target_rpy=None, seed_q_user=[0, 0, 0, 0, 0])
        打印_json(
            {
                "ok": True,
                "known_joints_deg": dict(zip(SDK_JOINT_NAMES, known_deg)),
                "fk_pose": fk,
                "ik_solution_deg": {
                    name: math.degrees(float(ik["q_user_rad"][idx]))
                    for idx, name in enumerate(SDK_JOINT_NAMES)
                },
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
