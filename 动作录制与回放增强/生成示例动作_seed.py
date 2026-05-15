"""生成阶段六示例动作文件。"""

from __future__ import annotations

from pathlib import Path

from 动作录制器_action_recorder import ActionRecorder
from 动作工具_common import SimulatedStage6Controller, build_empty_sequence, load_config, write_json


def make_sequence(name: str, targets: list[dict[str, float]], grippers: list[int]) -> dict:
    config = load_config()
    controller = SimulatedStage6Controller()
    recorder = ActionRecorder(controller, config)
    sequence = build_empty_sequence(name=name, description=f"{name} 示例动作", source="stage6_seed", config=config)
    for index, target in enumerate(targets, start=1):
        controller.move_joints(target)
        controller.set_gripper(grippers[index - 1])
        pose = recorder.capture_current_pose(index=index, name=f"pose_{index}")
        pose["duration_sec"] = 1.5
        pose["hold_sec"] = 0.3
        sequence["poses"].append(pose)
    sequence["pose_count"] = len(sequence["poses"])
    return sequence


def main() -> None:
    base = Path(__file__).resolve().parent / "动作库"
    base.mkdir(parents=True, exist_ok=True)
    actions = {
        "挥手_增强.json": make_sequence(
            "挥手_增强",
            [
                {"shoulder_pan": 0, "shoulder_lift": 20, "elbow_flex": 30, "wrist_flex": 10, "wrist_roll": -25},
                {"shoulder_pan": 0, "shoulder_lift": 20, "elbow_flex": 30, "wrist_flex": 10, "wrist_roll": -5},
                {"shoulder_pan": 0, "shoulder_lift": 20, "elbow_flex": 30, "wrist_flex": 10, "wrist_roll": -20},
            ],
            [60, 60, 60],
        ),
        "展示动作_增强.json": make_sequence(
            "展示动作_增强",
            [
                {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0, "wrist_flex": 0, "wrist_roll": 0},
                {"shoulder_pan": 20, "shoulder_lift": 25, "elbow_flex": 35, "wrist_flex": -10, "wrist_roll": -15},
            ],
            [50, 80],
        ),
        "示例_录制动作.json": make_sequence(
            "示例录制动作",
            [
                {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0, "wrist_flex": 0, "wrist_roll": 0},
                {"shoulder_pan": -15, "shoulder_lift": 15, "elbow_flex": 25, "wrist_flex": 5, "wrist_roll": -10},
            ],
            [0, 50],
        ),
    }
    for filename, payload in actions.items():
        write_json(base / filename, payload)
        print(base / filename)


if __name__ == "__main__":
    main()
