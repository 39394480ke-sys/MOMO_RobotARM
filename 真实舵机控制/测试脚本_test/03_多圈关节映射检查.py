"""多圈关节映射检查。

只做角度到 raw 的转换测试，不写入舵机。
检查 J2/J3/J5 是否按 signed absolute raw 处理，没有做 4096 包裹。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 真实机械臂控制器_real_arm_controller import RealArmController
from 角度映射_angle_mapper import MULTI_TURN_ABSOLUTE_RAW_LIMIT, MULTI_TURN_JOINTS, joint_deg_to_goal_detail, joint_label


def main() -> None:
    controller = RealArmController(ROOT / "真实配置.yaml")
    test_degrees = [-10.0, 0.0, 10.0, 30.0]

    print("多圈关节映射检查，不写入舵机。")
    for joint_key in MULTI_TURN_JOINTS:
        entry = controller.calibration_manager.get(joint_key)
        joint_config = controller.joint_config_by_key[joint_key]
        print(f"\n{joint_label(joint_key)} ({joint_key}) scale={joint_config['joint_scale']} home={entry.get('home_present_raw')}")
        for target_deg in test_degrees:
            detail = joint_deg_to_goal_detail(
                joint_key,
                target_deg,
                joint_config,
                entry,
                controller.runtime_state,
            )
            ok = abs(detail["goal_raw"]) <= MULTI_TURN_ABSOLUTE_RAW_LIMIT
            print(
                f"  目标角度={target_deg:>6.1f} deg "
                f"relative_raw={detail['relative_raw']:>6} "
                f"goal_raw={detail['goal_raw']:>6} "
                f"是否超限={'否' if ok else '是'}"
            )


if __name__ == "__main__":
    main()
