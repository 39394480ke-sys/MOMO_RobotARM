from 动作测试路径_test_paths import ACTION_ROOT

from 动作录制器_action_recorder import ActionRecorder
from 动作工具_common import SimulatedStage6Controller, load_config


controller = SimulatedStage6Controller()
controller.connect()
config = load_config()
recorder = ActionRecorder(controller, config)
output = ACTION_ROOT / "录制记录" / "recorded_pose_sequence.json"
sequence = recorder.record_pose_sequence(2, output, wait_for_enter=False)
print(f"已保存：{output}")
print(f"pose_count={sequence['pose_count']}")
