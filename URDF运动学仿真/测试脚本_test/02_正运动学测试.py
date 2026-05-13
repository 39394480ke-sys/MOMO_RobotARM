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
        outputs = []
        for name, joints_deg in [("home", [0, 0, 0, 0, 0]), ("展示姿态", [0, 25, 40, 10, 0])]:
            pose = model.forward([math.radians(value) for value in joints_deg])
            outputs.append({"名称": name, "joints_deg": dict(zip(SDK_JOINT_NAMES, joints_deg)), "tcp_pose": pose})
        打印_json({"ok": True, "results": outputs})
    except Exception as exc:
        打印_json({"ok": False, "错误": str(exc)})
        raise SystemExit(1)
    finally:
        if model is not None:
            model.close()
