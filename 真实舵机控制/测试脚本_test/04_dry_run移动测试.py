"""完整 move_joints dry-run 测试。"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 真实机械臂控制器_real_arm_controller import RealArmController


def main() -> None:
    controller = RealArmController(ROOT / "真实配置.yaml")
    controller.set_dry_run(True, persist=False)
    result = controller.connect()
    print(result.消息)
    if not result.成功:
        return

    target = {
        "shoulder_pan": 0.0,    # J1_底座旋转
        "shoulder_lift": 10.0,  # J2_肩部抬升，多圈
        "elbow_flex": 10.0,     # J3_肘部弯曲，多圈
        "wrist_flex": 0.0,      # J4_腕部俯仰
        "wrist_roll": 0.0,      # J5_腕部旋转，多圈
    }
    print("\n执行完整 dry-run 移动测试：")
    print(controller.move_joints(target).消息)
    print(controller.set_gripper(50).消息)
    print(controller.disconnect().消息)


if __name__ == "__main__":
    main()
