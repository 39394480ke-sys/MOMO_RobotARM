"""完整 move_joints dry-run 测试。"""

from __future__ import annotations

import 真实测试路径_test_paths  # noqa: F401
from 真实路径工具_real_path_utils import real_config_path
from 真实机械臂控制器_real_arm_controller import RealArmController


def main() -> None:
    controller = RealArmController(real_config_path())
    controller.set_dry_run(True, persist=False)
    result = controller.connect()
    print(result.消息)
    if not result.成功:
        return

    target = {
        "j10": 0.0,  # J10_底盘导轨，单位 mm
        "j11": 0.0,  # J11_底座旋转
        "j12": 10.0, # J12_肩部抬升，多圈
        "j13": 10.0, # J13_肘部弯曲，多圈
        "j14": 0.0,  # J14_腕部俯仰
        "j15": 0.0,  # J15_腕部旋转，多圈
    }
    print("\n执行完整 dry-run 移动测试：")
    print(controller.move_joints(target).消息)
    print(controller.set_gripper(50).消息)
    print(controller.disconnect().消息)


if __name__ == "__main__":
    main()
