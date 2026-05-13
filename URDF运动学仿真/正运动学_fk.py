"""独立 FK 正运动学命令行工具。"""

from __future__ import annotations

import argparse
import math
from typing import Any

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 加载运动学配置, 打印_json


def 计算FK(joints_deg: list[float], use_gui: bool = False) -> dict[str, Any]:
    if len(joints_deg) != len(SDK_JOINT_NAMES):
        return {"ok": False, "错误": f"需要 {len(SDK_JOINT_NAMES)} 个关节角度。"}
    model = None
    try:
        model = 创建运动学模型(use_gui=use_gui)
        q_rad = [math.radians(float(value)) for value in joints_deg]
        fk = model.forward(q_rad)
        return {
            "ok": True,
            "input_joints_deg": {name: float(joints_deg[idx]) for idx, name in enumerate(SDK_JOINT_NAMES)},
            "tcp_pose": {
                "xyz_m": fk["xyz"],
                "rpy_rad": fk["rpy"],
            },
        }
    except Exception as exc:
        return {"ok": False, "错误": str(exc)}
    finally:
        if model is not None:
            model.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="URDF 正运动学 FK 测试")
    parser.add_argument("--joints-deg", nargs=5, type=float, required=True, metavar=("J1", "J2", "J3", "J4", "J5"))
    parser.add_argument("--gui", action="store_true", help="用 PyBullet GUI 打开模型")
    args = parser.parse_args()
    result = 计算FK(list(args.joints_deg), use_gui=bool(args.gui))
    if "_warning" in 加载运动学配置():
        result.setdefault("warnings", []).append(加载运动学配置()["_warning"])
    打印_json(result)
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
