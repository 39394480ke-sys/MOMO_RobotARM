from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, load_config


controller = SimulatedStage6Controller()
controller.connect()
config = load_config()
player = SequencePlayer(controller, config)
path = BASE / "录制记录" / "recorded_pose_sequence.json"
sequence = player.load_sequence(path)
for pose in sequence["poses"]:
    print(f"pose {pose['index']} 目标角度：{pose['joint_targets_deg']}")
player.play(sequence)
