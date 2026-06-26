import 动作测试路径_test_paths  # noqa: F401

from 动作工具_common import MULTI_TURN_JOINTS
from 动作测试工具_test_utils import make_test_sequence


sequence = make_test_sequence("多圈关节检查测试")
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
