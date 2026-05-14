"""简单 PyBullet 3D 查看器。"""

from __future__ import annotations

import json
import math
import select
import sys
import time
from pathlib import Path
from typing import Any

from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型, 打印_json


class PyBulletViewer:
    def __init__(self) -> None:
        self.model = 创建运动学模型(use_gui=True)
        self.current_joints_deg = [0.0 for _ in SDK_JOINT_NAMES]
        self.slider_ids: list[int] = []
        self.sliders_enabled = False
        self._slider_warning_printed = False
        self._last_slider_read_s = 0.0
        self.last_slider_joints_deg = list(self.current_joints_deg)
        self.set_joints_deg(self.current_joints_deg)
        self._create_sliders()

    def close(self) -> None:
        self.model.close()

    def is_open(self) -> bool:
        return self.model.is_connected()

    def step(self) -> None:
        self.model.step_simulation()
        now_s = time.monotonic()
        if self.is_open() and self.sliders_enabled and now_s - self._last_slider_read_s >= 0.05:
            self._last_slider_read_s = now_s
            self._apply_slider_values()

    def _create_sliders(self) -> None:
        try:
            limits = self.model.joint_limits_report()
            for joint_name, start_deg in zip(SDK_JOINT_NAMES, self.current_joints_deg):
                joint_limits = limits[joint_name]
                lower_deg = max(-180.0, float(joint_limits["lower_deg"]))
                upper_deg = min(180.0, float(joint_limits["upper_deg"]))
                slider_id = self.model.add_debug_slider(joint_name, lower_deg, upper_deg, start_deg)
                self.slider_ids.append(slider_id)
            self.sliders_enabled = bool(self.slider_ids)
        except Exception as exc:
            self.slider_ids = []
            self.sliders_enabled = False
            print(f"提示：当前 PyBullet GUI 不支持关节滑块，已改用终端命令控制。原因：{exc}")

    def _apply_slider_values(self) -> None:
        if not self.slider_ids:
            return
        try:
            joints_deg = [self.model.read_debug_slider(slider_id) for slider_id in self.slider_ids]
        except Exception as exc:
            self.sliders_enabled = False
            if not self._slider_warning_printed:
                print(f"\n提示：读取 PyBullet 滑块失败，已关闭滑块控制。仍可用“移动 ...”命令。原因：{exc}")
                print("3D> ", end="", flush=True)
                self._slider_warning_printed = True
            return
        if any(abs(a - b) > 0.05 for a, b in zip(joints_deg, self.last_slider_joints_deg)):
            self.set_joints_deg(joints_deg)
            self.last_slider_joints_deg = list(joints_deg)

    def set_joints_deg(self, joints_deg: list[float]) -> dict[str, Any]:
        if len(joints_deg) != len(SDK_JOINT_NAMES):
            return {"ok": False, "错误": f"需要 {len(SDK_JOINT_NAMES)} 个关节角度。"}
        self.current_joints_deg = [float(value) for value in joints_deg]
        self.last_slider_joints_deg = list(self.current_joints_deg)
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
    print("窗口操作：鼠标拖拽旋转视角，滚轮缩放；如果 PyBullet 支持，右侧滑块可直接移动关节。")


def main() -> int:
    viewer: PyBulletViewer | None = None
    try:
        viewer = PyBulletViewer()
        print("PyBullet 3D 仿真已打开。这个窗口只显示 URDF，不连接真实舵机。")
        print_help()
        print("3D> ", end="", flush=True)
        while True:
            viewer.step()
            if not viewer.is_open():
                print("\nPyBullet 窗口已关闭。")
                break
            ready, _, _ = select.select([sys.stdin], [], [], 1.0 / 60.0)
            if not ready:
                continue
            text = sys.stdin.readline()
            if text == "":
                break
            text = text.strip()
            if not text:
                print("3D> ", end="", flush=True)
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
                    print("3D> ", end="", flush=True)
                    continue
                打印_json(viewer.play_action(parts[1]))
            else:
                print("未知命令。输入“帮助”查看可用命令。")
            print("3D> ", end="", flush=True)
        return 0
    except KeyboardInterrupt:
        print()
        return 0
    except Exception as exc:
        print(str(exc))
        return 1
    finally:
        if viewer is not None:
            viewer.close()


if __name__ == "__main__":
    raise SystemExit(main())
