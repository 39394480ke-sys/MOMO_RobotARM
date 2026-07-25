"""多圈关节映射检查。

只做角度到 raw 的转换测试，不写入舵机。
检查 J10-J15 是否按 signed absolute raw 处理，没有做 4096 包裹。
"""

from __future__ import annotations

import 真实测试路径_test_paths  # noqa: F401
from 真实路径工具_real_path_utils import real_config_path
from 真实配置加载_real_config_loader import load_real_config
from 角度映射_angle_mapper import (
    MULTI_TURN_ABSOLUTE_RAW_LIMIT,
    MULTI_TURN_JOINTS,
    joint_deg_to_goal_detail,
    joint_label,
    present_raw_to_joint_detail,
)


def main() -> None:
    config = load_real_config(real_config_path())
    joint_config_by_key = {
        str(joint["key"]): dict(joint)
        for joint in config.get("robot", {}).get("joints", [])
    }
    joint_scales = config.get("robot", {}).get("joint_scales", {})
    for joint_key, joint_config in joint_config_by_key.items():
        joint_config["joint_scale"] = float(joint_scales[joint_key])
    test_degrees = [-10.0, 0.0, 10.0, 30.0]
    runtime_state: dict[str, object] = {}
    observed_unwrapped_raw = False

    print("多圈关节映射检查，使用 synthetic V2 零点，不读取本机标定、不写入舵机。")
    for joint_key in MULTI_TURN_JOINTS:
        entry = {
            "id": int(joint_config_by_key[joint_key]["舵机ID"]),
            "模式": "多圈",
            "home_present_raw": 0,
            "phase": 28,
            "direction": 1,
        }
        joint_config = joint_config_by_key[joint_key]
        print(f"\n{joint_label(joint_key)} ({joint_key}) scale={joint_config['joint_scale']}")
        for target_deg in test_degrees:
            detail = joint_deg_to_goal_detail(
                joint_key,
                target_deg,
                joint_config,
                entry,
                runtime_state,
            )
            ok = abs(detail["goal_raw"]) <= MULTI_TURN_ABSOLUTE_RAW_LIMIT
            assert ok, detail
            reverse = present_raw_to_joint_detail(
                joint_key,
                detail["goal_raw"],
                joint_config,
                entry,
                runtime_state,
            )
            assert abs(float(reverse["joint_deg"]) - target_deg) <= 0.05, reverse
            observed_unwrapped_raw = observed_unwrapped_raw or abs(int(detail["goal_raw"])) > 4096
            print(
                f"  目标角度={target_deg:>6.1f} deg "
                f"reference_raw={detail['reference_raw']:>6} "
                f"relative_raw={detail['relative_raw']:>6} "
                f"goal_raw={detail['goal_raw']:>6} "
                f"是否超限={'否' if ok else '是'}"
            )
    assert observed_unwrapped_raw, "测试数据必须覆盖超过单圈 4096 raw 的映射。"


if __name__ == "__main__":
    main()
