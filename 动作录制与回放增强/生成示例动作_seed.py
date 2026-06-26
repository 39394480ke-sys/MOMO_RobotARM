"""生成阶段六示例动作文件。"""

from __future__ import annotations

from pathlib import Path

from 动作录制器_action_recorder import ActionRecorder
from 动作工具_common import SimulatedStage6Controller, append_sequence_pose, build_empty_sequence, load_config
from 通用_io import write_json


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
        append_sequence_pose(sequence, pose)
    return sequence


def main() -> None:
    base = Path(__file__).resolve().parent / "动作库"
    base.mkdir(parents=True, exist_ok=True)
    actions = {
        "挥手_增强.json": make_sequence(
            "挥手_增强",
            [
                {"j10": 0, "j11": 0, "j12": 20, "j13": 30, "j14": 10, "j15": -25},
                {"j10": 0, "j11": 0, "j12": 20, "j13": 30, "j14": 10, "j15": -5},
                {"j10": 0, "j11": 0, "j12": 20, "j13": 30, "j14": 10, "j15": -20},
            ],
            [60, 60, 60],
        ),
        "展示动作_增强.json": make_sequence(
            "展示动作_增强",
            [
                {"j10": 0, "j11": 0, "j12": 0, "j13": 0, "j14": 0, "j15": 0},
                {"j10": 0, "j11": 20, "j12": 25, "j13": 35, "j14": -10, "j15": -15},
            ],
            [50, 80],
        ),
        "示例_录制动作.json": make_sequence(
            "示例录制动作",
            [
                {"j10": 0, "j11": 0, "j12": 0, "j13": 0, "j14": 0, "j15": 0},
                {"j10": 0, "j11": -15, "j12": 15, "j13": 25, "j14": 5, "j15": -10},
            ],
            [0, 50],
        ),
    }
    for filename, payload in actions.items():
        write_json(base / filename, payload)
        print(base / filename)


if __name__ == "__main__":
    main()
