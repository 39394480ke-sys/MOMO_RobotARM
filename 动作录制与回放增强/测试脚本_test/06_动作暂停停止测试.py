import threading
import time

import 动作测试路径_test_paths  # noqa: F401

from 动作录制器_action_recorder import ActionRecorder
from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, append_sequence_pose, build_empty_sequence, load_config


class SlowController(SimulatedStage6Controller):
    def __init__(self):
        super().__init__()
        self.move_count = 0

    def move_joints(self, target_deg_by_joint, multi_turn_targets_continuous_raw=None):
        self.move_count += 1
        return super().move_joints(target_deg_by_joint, multi_turn_targets_continuous_raw)


config = load_config()
controller = SlowController()
recorder = ActionRecorder(controller, config)
sequence = build_empty_sequence("暂停停止测试", source="test", config=config)
targets = [
    {"j10": 0, "j11": 0, "j12": 0, "j13": 0, "j14": 0, "j15": 0},
    {"j10": 5, "j11": 30, "j12": 30, "j13": 30, "j14": 30, "j15": 30},
    {"j10": -5, "j11": -30, "j12": -30, "j13": -30, "j14": -30, "j15": -30},
]
for index, target in enumerate(targets, start=1):
    controller.move_joints(target)
    pose = recorder.capture_current_pose(index=index)
    pose["duration_sec"] = 1.0
    append_sequence_pose(sequence, pose)

player = SequencePlayer(controller, config)
thread = threading.Thread(target=lambda: player.play(sequence, speed=1.0), daemon=True)
thread.start()
time.sleep(0.2)
player.pause()
paused_count = controller.move_count
time.sleep(0.2)
assert controller.move_count == paused_count
player.resume()
time.sleep(0.2)
player.stop()
stopped_count = controller.move_count
thread.join(timeout=2.0)
time.sleep(0.2)
assert controller.move_count == stopped_count
print("暂停 / 继续 / 停止测试通过")
