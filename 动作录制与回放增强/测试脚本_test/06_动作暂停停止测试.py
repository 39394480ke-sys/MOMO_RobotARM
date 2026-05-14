from pathlib import Path
import sys
import threading
import time

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from 动作录制器_action_recorder import ActionRecorder
from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, build_empty_sequence, load_config


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
    {"shoulder_pan": 0, "shoulder_lift": 0, "elbow_flex": 0, "wrist_flex": 0, "wrist_roll": 0},
    {"shoulder_pan": 30, "shoulder_lift": 30, "elbow_flex": 30, "wrist_flex": 30, "wrist_roll": 30},
    {"shoulder_pan": -30, "shoulder_lift": -30, "elbow_flex": -30, "wrist_flex": -30, "wrist_roll": -30},
]
for index, target in enumerate(targets, start=1):
    controller.move_joints(target)
    pose = recorder.capture_current_pose(index=index)
    pose["duration_sec"] = 1.0
    sequence["poses"].append(pose)
sequence["pose_count"] = len(sequence["poses"])

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
