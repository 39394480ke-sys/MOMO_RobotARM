"""简单 PyBullet 3D 查看器。"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 打印_json


class PyBulletViewer:
    def __init__(self) -> None:
        self.model = 创建运动学模型(use_gui=True)
        self.current_joints_deg = [0.0 for _ in SDK_JOINT_NAMES]
        self.set_joints_deg(self.current_joints_deg)

    def close(self) -> None:
        self.model.close()

    def set_joints_deg(self, joints_deg: list[float]) -> dict[str, Any]:
        if len(joints_deg) != len(SDK_JOINT_NAMES):
            return {"ok": False, "错误": f"需要 {len(SDK_JOINT_NAMES)} 个关节角度。"}
        self.current_joints_deg = [float(value) for value in joints_deg]
        pose = self.model.forward([math.radians(value) for value in self.current_joints_deg])
        return {"ok": True, "joints_deg": dict(zip(SDK_JOINT_NAMES, self.current_joints_deg)), "tcp_pose": pose}

    def status(self) -> dict[str, Any]:
        pose = self.model.forward([math.radians(value) for value in self.current_joints_deg])
        return {"ok": True, "joints_deg": dict(zip(SDK_JOINT_NAMES, self.current_joints_deg)), "tcp_pose": pose}

    def play_action(self, name: str) -> dict[str, Any]:
        action_path = Path(__file__).resolve().parents[1] / "仿真控制系统" / "姿态管理" / "动作库" / f"{name}.json"
        if not action_path.exists():
            return {"ok": False, "错误": f"没有找到阶段三动作：{action_path}"}
        try:
            with action_path.open("r", encoding="utf-8") as file:
                action = json.load(file)
        except json.JSONDecodeError as exc:
            return {"ok": False, "错误": f"动作 JSON 格式错误：{exc}"}

        steps = action.get("步骤", [])
        if not isinstance(steps, list) or not steps:
            return {"ok": False, "错误": f"动作 {name} 没有步骤。"}

        for step in steps:
            target = step.get("关节角度") if isinstance(step, dict) else None
            if target is None:
                continue
            target = [float(value) for value in target[: len(SDK_JOINT_NAMES)]]
            interp_steps = max(1, int(step.get("插值步数", 8)))
            wait_s = float(step.get("等待秒", 0.08))
            start = list(self.current_joints_deg)
            for idx in range(1, interp_steps + 1):
                ratio = idx / interp_steps
                middle = [a + (b - a) * ratio for a, b in zip(start, target)]
                self.set_joints_deg(middle)
                time.sleep(max(0.0, wait_s))
        return {"ok": True, "message": f"动作 {name} 播放完成。", "state": self.status()}


def print_help() -> None:
    print("命令：")
    print("  状态")
    print("  移动 0 20 30 10 0")
    print("  播放动作 挥手")
    print("  末端")
    print("  退出")


def main() -> int:
    viewer: PyBulletViewer | None = None
    try:
        viewer = PyBulletViewer()
        print("PyBullet 3D 仿真已打开。这个窗口只显示 URDF，不连接真实舵机。")
        print_help()
        while True:
            text = input("3D> ").strip()
            if not text:
                continue
            parts = text.split()
            command = parts[0]
            if command in {"退出", "exit", "quit"}:
                break
            if command in {"帮助", "help"}:
                print_help()
            elif command == "状态":
                打印_json(viewer.status())
            elif command == "末端":
                打印_json(viewer.status().get("tcp_pose", {}))
            elif command == "移动":
                if len(parts) != 6:
                    print("移动命令需要 5 个角度，例如：移动 0 20 30 10 0")
                    continue
                打印_json(viewer.set_joints_deg([float(value) for value in parts[1:6]]))
            elif command == "播放动作":
                if len(parts) < 2:
                    print("请输入动作名，例如：播放动作 挥手")
                    continue
                打印_json(viewer.play_action(parts[1]))
            else:
                print("未知命令。输入“帮助”查看可用命令。")
        return 0
    except Exception as exc:
        print(str(exc))
        return 1
    finally:
        if viewer is not None:
            viewer.close()


if __name__ == "__main__":
    raise SystemExit(main())
