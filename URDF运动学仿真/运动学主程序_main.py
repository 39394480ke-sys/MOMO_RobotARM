"""阶段五中文交互入口。"""

from __future__ import annotations

import math
import subprocess
import sys
from pathlib import Path

from URDF检查_urdf_inspector import 检查URDF
from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 打印_json


def print_help() -> None:
    print("命令：")
    print("  帮助")
    print("  检查URDF")
    print("  正解 0 20 30 10 0")
    print("  逆解 0.20 0.05 0.18")
    print("  逆解带姿态 0.20 0.05 0.18 0 0 0")
    print("  末端")
    print("  增量 base 0.01 0 0")
    print("  增量 tool 0.01 0 0")
    print("  打开3D")
    print("  退出")


def main() -> int:
    model = None
    current_joints_deg = [0.0 for _ in SDK_JOINT_NAMES]
    print("阶段五：URDF / 运动学 / 3D 仿真系统。这里不连接真实舵机。")
    print_help()
    while True:
        try:
            text = input("运动学> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not text:
            continue
        parts = text.split()
        command = parts[0]
        try:
            if command in {"退出", "exit", "quit"}:
                break
            if command in {"帮助", "help"}:
                print_help()
            elif command == "检查URDF":
                打印_json(检查URDF())
            elif command == "打开3D":
                script = Path(__file__).resolve().parent / "3D仿真_pybullet_viewer.py"
                subprocess.Popen([sys.executable, str(script)])
                print("已启动 3D 仿真进程。")
            elif command == "正解":
                if len(parts) != 6:
                    print("正解需要 5 个角度，单位是度。")
                    continue
                current_joints_deg = [float(value) for value in parts[1:6]]
                model = model or 创建运动学模型(use_gui=False)
                pose = model.forward([math.radians(value) for value in current_joints_deg])
                打印_json({"ok": True, "joints_deg": dict(zip(SDK_JOINT_NAMES, current_joints_deg)), "tcp_pose": pose})
            elif command == "逆解":
                if len(parts) != 4:
                    print("逆解需要 xyz 三个数，单位是米。")
                    continue
                model = model or 创建运动学模型(use_gui=False)
                result = model.inverse(
                    target_xyz=[float(value) for value in parts[1:4]],
                    target_rpy=None,
                    seed_q_user=[math.radians(value) for value in current_joints_deg],
                )
                current_joints_deg = [math.degrees(float(value)) for value in result["q_user_rad"]]
                打印_json({"ok": True, "solution_joints_deg": dict(zip(SDK_JOINT_NAMES, current_joints_deg)), "ik": result})
            elif command == "逆解带姿态":
                if len(parts) != 7:
                    print("逆解带姿态需要 xyz+rpy 六个数，xyz 单位米，rpy 单位弧度。")
                    continue
                model = model or 创建运动学模型(use_gui=False)
                result = model.inverse(
                    target_xyz=[float(value) for value in parts[1:4]],
                    target_rpy=[float(value) for value in parts[4:7]],
                    seed_q_user=[math.radians(value) for value in current_joints_deg],
                )
                current_joints_deg = [math.degrees(float(value)) for value in result["q_user_rad"]]
                打印_json({"ok": True, "solution_joints_deg": dict(zip(SDK_JOINT_NAMES, current_joints_deg)), "ik": result})
            elif command == "末端":
                model = model or 创建运动学模型(use_gui=False)
                打印_json(model.forward([math.radians(value) for value in current_joints_deg]))
            elif command == "增量":
                if len(parts) not in {5, 8}:
                    print("增量格式：增量 base 0.01 0 0 或 增量 tool 0.01 0 0 0 0 0")
                    continue
                frame = parts[1]
                delta_xyz = [float(value) for value in parts[2:5]]
                delta_rpy = [0.0, 0.0, 0.0] if len(parts) == 5 else [float(value) for value in parts[5:8]]
                model = model or 创建运动学模型(use_gui=False)
                current_pose = model.forward([math.radians(value) for value in current_joints_deg])
                target_xyz, target_rpy = model.compose_delta_target(
                    current_xyz=current_pose["xyz"],
                    current_rpy=current_pose["rpy"],
                    delta_xyz=delta_xyz,
                    delta_rpy=delta_rpy,
                    frame=frame,
                )
                ik = model.inverse(
                    target_xyz=target_xyz,
                    target_rpy=target_rpy if any(abs(value) > 1e-12 for value in delta_rpy) else None,
                    seed_q_user=[math.radians(value) for value in current_joints_deg],
                )
                current_joints_deg = [math.degrees(float(value)) for value in ik["q_user_rad"]]
                打印_json(
                    {
                        "ok": True,
                        "frame": frame,
                        "target_pose": {"xyz": target_xyz, "rpy": target_rpy},
                        "solution_joints_deg": dict(zip(SDK_JOINT_NAMES, current_joints_deg)),
                        "ik": ik,
                    }
                )
            else:
                print("未知命令。输入“帮助”查看命令。")
        except Exception as exc:
            print(f"错误：{exc}")
    if model is not None:
        model.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
