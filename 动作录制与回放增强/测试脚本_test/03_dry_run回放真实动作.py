from pathlib import Path
import tempfile

import 动作测试路径_test_paths  # noqa: F401

from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import create_dry_run_real_controller, load_config
from 动作测试工具_test_utils import make_test_sequence
from 通用_io import write_json


config = load_config()
controller = create_dry_run_real_controller()
result = controller.connect()
print(result.消息)
assert result.成功
player = SequencePlayer(controller, config)
try:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "dry_run_real_sequence.json"
        write_json(path, make_test_sequence("真实dry-run回放测试"))
        sequence = player.load_sequence(path)
        for pose in sequence["poses"]:
            print(f"pose {pose['index']} 将执行角度：{pose['replay_joint_targets_deg']}")
            print(f"pose {pose['index']} multi-turn raw：{pose['replay_multi_turn_continuous_raw']}")
        ok = player.play(sequence, speed=3.0)
        assert ok is True
finally:
    controller.disconnect()
print("真实 dry-run 动作回放测试通过")
