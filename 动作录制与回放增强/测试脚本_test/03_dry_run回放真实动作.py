from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import create_dry_run_real_controller, load_config


config = load_config()
controller = create_dry_run_real_controller()
result = controller.connect()
print(result.消息)
player = SequencePlayer(controller, config)
path = BASE / "动作库" / "示例_录制动作.json"
sequence = player.load_sequence(path)
for pose in sequence["poses"]:
    print(f"pose {pose['index']} 将执行角度：{pose['replay_joint_targets_deg']}")
    print(f"pose {pose['index']} multi-turn raw：{pose['replay_multi_turn_continuous_raw']}")
player.play(sequence, speed=3.0)
