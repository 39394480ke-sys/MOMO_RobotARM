from pathlib import Path
import tempfile

import 动作测试路径_test_paths  # noqa: F401

from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, load_config
from 动作测试工具_test_utils import make_test_sequence
from 通用_io import write_json


controller = SimulatedStage6Controller()
controller.connect()
config = load_config()
player = SequencePlayer(controller, config)
with tempfile.TemporaryDirectory() as tmp:
    path = Path(tmp) / "recorded_pose_sequence.json"
    write_json(path, make_test_sequence("仿真回放测试"))
    sequence = player.load_sequence(path)
    for pose in sequence["poses"]:
        print(f"pose {pose['index']} 目标角度：{pose['joint_targets_deg']}")
    ok = player.play(sequence)
    assert ok is True
print("仿真动作回放测试通过")
