from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from 动作录制器_action_recorder import ActionRecorder
from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, build_empty_sequence, load_config


class GripperSpyController(SimulatedStage6Controller):
    def __init__(self):
        super().__init__()
        self.gripper_calls = []

    def set_gripper(self, open_value):
        self.gripper_calls.append(float(open_value))
        return super().set_gripper(open_value)


config = load_config()
controller = GripperSpyController()
recorder = ActionRecorder(controller, config)
sequence = build_empty_sequence("夹爪测试", source="test", config=config)
for index, value in enumerate([10, 80], start=1):
    controller.set_gripper(value)
    sequence["poses"].append(recorder.capture_current_pose(index=index))
sequence["pose_count"] = len(sequence["poses"])
player = SequencePlayer(controller, config)
player.play(sequence, speed=5.0)
print(f"set_gripper 调用：{controller.gripper_calls}")
assert controller.gripper_calls[-2:] == [10.0, 80.0]
