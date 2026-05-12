"""读取舵机状态测试。

默认使用 真实配置.yaml 中的 dry_run 设置。
dry_run=true 时只读取 Mock 状态，不访问真实硬件。
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from 真实机械臂控制器_real_arm_controller import RealArmController
from 角度映射_angle_mapper import JOINT_ORDER, MULTI_TURN_JOINTS, joint_label


def main() -> None:
    controller = RealArmController(ROOT / "真实配置.yaml")
    result = controller.connect()
    print(result.消息)
    if not result.成功:
        return

    state = controller.get_state()
    print("\n所有关节 raw 与逻辑角度：")
    for joint_key in JOINT_ORDER:
        print(
            f"{joint_label(joint_key)} ({joint_key}) "
            f"raw={state['raw_present_position'].get(joint_key)} "
            f"deg={state['关节角度'].get(joint_key, 0.0):.2f}"
        )

    print("\n多圈状态：")
    for joint_key in MULTI_TURN_JOINTS:
        item = state["multi_turn_state"].get(joint_key, {})
        print(
            f"{joint_label(joint_key)} ({joint_key}) "
            f"home={item.get('home_present_raw')} "
            f"current={item.get('current_raw')} "
            f"relative={item.get('relative_raw')} "
            f"deg={item.get('joint_deg', 0.0):.2f}"
        )

    print(controller.disconnect().消息)


if __name__ == "__main__":
    main()
