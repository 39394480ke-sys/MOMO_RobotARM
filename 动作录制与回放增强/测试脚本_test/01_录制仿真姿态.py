from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from 动作录制器_action_recorder import ActionRecorder
from 动作工具_common import SimulatedStage6Controller, load_config


controller = SimulatedStage6Controller()
controller.connect()
config = load_config()
recorder = ActionRecorder(controller, config)
output = BASE / "录制记录" / "recorded_pose_sequence.json"
sequence = recorder.record_pose_sequence(2, output, wait_for_enter=False)
print(f"已保存：{output}")
print(f"pose_count={sequence['pose_count']}")
