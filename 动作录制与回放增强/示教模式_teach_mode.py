"""阶段六示教录制入口。"""

from __future__ import annotations

import argparse
from pathlib import Path

from 动作录制器_action_recorder import ActionRecorder
from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, create_dry_run_real_controller, is_real_mode_controller, load_config, resolve_stage6_path


def main() -> None:
    parser = argparse.ArgumentParser(description="阶段六示教录制")
    parser.add_argument("--pose-count", type=int, default=2, help="录制姿态数量")
    parser.add_argument("--output", default="动作库/我的动作.json", help="输出动作 JSON")
    parser.add_argument("--real", action="store_true", help="使用阶段四真实控制器。默认不启用")
    parser.add_argument("--replay-after-record", action="store_true", help="录制后立即回放")
    args = parser.parse_args()

    config = load_config()
    output = resolve_stage6_path(args.output)

    if args.real:
        print("警告：真实示教涉及真实机械臂。请扶住机械臂，确认急停和断电方式可用。")
        controller = create_dry_run_real_controller()
        result = controller.connect()
        print(result.消息)
        if is_real_mode_controller(controller):
            answer = input("是否释放扭矩用于手动摆姿态？输入 yes 才会尝试 disable torque：").strip().lower()
            if answer == "yes" and hasattr(controller, "driver"):
                try:
                    controller.driver.disable_torque()
                    print("已尝试释放扭矩。摆姿态时请始终扶住机械臂。")
                except Exception as error:
                    print(f"释放扭矩失败：{error}")
    else:
        controller = SimulatedStage6Controller()
        print(controller.connect().消息)

    recorder = ActionRecorder(controller, config)
    sequence = recorder.record_pose_sequence(args.pose_count, output, wait_for_enter=True)
    print(f"动作已保存：{output}")

    if args.replay_after_record:
        if is_real_mode_controller(controller):
            print("真实模式不会自动快速回放，请在确认安全后使用动作主程序播放。")
        else:
            player = SequencePlayer(controller, config)
            player.play(sequence)

    if args.real:
        relock = input("结束示教。是否重新上锁/保持扭矩？输入 yes 尝试保持当前位置：").strip().lower()
        if relock == "yes" and hasattr(controller, "stop"):
            print(controller.stop().消息)


if __name__ == "__main__":
    main()
