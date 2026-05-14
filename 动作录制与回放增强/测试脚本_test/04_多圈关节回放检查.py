from pathlib import Path
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))

from 动作工具_common import MULTI_TURN_JOINTS, read_json


path = BASE / "动作库" / "示例_录制动作.json"
sequence = read_json(path)
ok = True
for pose in sequence["poses"]:
    replay = pose.get("replay_multi_turn_continuous_raw") or {}
    for joint in MULTI_TURN_JOINTS:
        value = replay.get(joint)
        if value is None:
            ok = False
            print(f"缺少 {joint} continuous_raw")
        else:
            print(f"pose {pose['index']} {joint} continuous_raw={value}")
            if abs(float(value)) > 4096 and float(value) % 4096 == 0:
                ok = False
                print(f"警告：{joint} 疑似被错误取模。")
print("检查通过" if ok else "检查失败")
raise SystemExit(0 if ok else 1)
