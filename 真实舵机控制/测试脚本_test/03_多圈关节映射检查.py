"""多圈关节映射检查。

只做角度到 raw 的转换测试，不写入舵机。
检查 J10-J15 是否按 signed absolute raw 处理，没有做 4096 包裹。
"""

from __future__ import annotations

import 真实测试路径_test_paths  # noqa: F401
from 真实路径工具_real_path_utils import real_config_path
from 真实机械臂控制器_real_arm_controller import RealArmController
from 角度映射_angle_mapper import MULTI_TURN_ABSOLUTE_RAW_LIMIT, MULTI_TURN_JOINTS, joint_deg_to_goal_detail, joint_label


def main() -> None:
    controller = RealArmController(real_config_path())
    test_degrees = [-10.0, 0.0, 10.0, 30.0]

    print("多圈关节映射检查，不写入舵机。")
    for joint_key in MULTI_TURN_JOINTS:
        entry = controller.calibration_manager.get(joint_key)
        joint_config = controller.joint_config_by_key[joint_key]
        print(f"\n{joint_label(joint_key)} ({joint_key}) scale={joint_config['joint_scale']}")
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
                f"reference_raw={detail['reference_raw']:>6} "
                f"relative_raw={detail['relative_raw']:>6} "
                f"goal_raw={detail['goal_raw']:>6} "
                f"是否超限={'否' if ok else '是'}"
            )


if __name__ == "__main__":
    main()
