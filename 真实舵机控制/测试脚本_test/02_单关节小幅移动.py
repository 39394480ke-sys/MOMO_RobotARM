"""单关节小幅移动测试。

默认强制 dry-run，测试 J12_肩部抬升移动 2 度。
真实测试前请确认机械臂处于安全位置；首次真机测试每次只移动 2-5 度。
"""

from __future__ import annotations

import 真实测试路径_test_paths  # noqa: F401
from 真实路径工具_real_path_utils import real_config_path
from 真实机械臂控制器_real_arm_controller import RealArmController
from 角度映射_angle_mapper import joint_label


def main() -> None:
    controller = RealArmController(real_config_path())
    controller.set_dry_run(True, persist=False)
    result = controller.connect()
    print(result.消息)
    if not result.成功:
        return

    joint_key = "j12"  # J12_肩部抬升，多圈
    target_deg = 2.0
    print(f"\n风险提示：本脚本默认 dry-run，只测试 {joint_label(joint_key)} ({joint_key}) 小幅 {target_deg} 度映射。")
    move_result = controller.move_joint(joint_key, target_deg)
    print(move_result.消息)
    print(controller.disconnect().消息)


if __name__ == "__main__":
    main()
