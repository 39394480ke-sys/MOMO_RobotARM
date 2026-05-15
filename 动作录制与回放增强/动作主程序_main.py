"""阶段六中文命令行入口。"""

from __future__ import annotations

import argparse
import shlex
import threading
from pathlib import Path

from 动作文件管理_action_library import ActionLibrary
from 动作录制器_action_recorder import ActionRecorder
from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import SimulatedStage6Controller, create_dry_run_real_controller, create_real_controller, load_config, resolve_stage6_path


HELP_TEXT = """命令：
帮助
动作列表
动作摘要 动作名称
录制 动作名称 姿态数量
示教录制 动作名称 姿态数量
播放 动作名称
循环播放 动作名称
暂停
继续
停止
删除动作 动作名称
复制动作 原名称 新名称
导出动作 动作名称 路径
导入动作 路径
退出"""


def main() -> None:
    parser = argparse.ArgumentParser(description="阶段六动作录制与回放增强系统")
    parser.add_argument(
        "--mode",
        choices=["仿真", "dry-run", "真实"],
        default="仿真",
        help="控制器模式。默认仿真；dry-run 使用阶段四 Mock 驱动；真实会连接真实机械臂。",
    )
    args = parser.parse_args()

    config = load_config()
    if args.mode == "dry-run":
        controller = create_dry_run_real_controller()
    elif args.mode == "真实":
        print("警告：真实模式会连接并可能移动真实机械臂。回放动作前仍需要二次确认。")
        controller = create_real_controller()
    else:
        controller = SimulatedStage6Controller()
    print(controller.connect().消息)
    library = ActionLibrary(config)
    recorder = ActionRecorder(controller, config)
    player = SequencePlayer(controller, config)
    play_thread: threading.Thread | None = None

    print("阶段六动作录制与回放增强系统。输入“帮助”查看命令。默认仿真 / dry-run，不会真实移动机械臂。")
    while True:
        try:
            line = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            player.stop()
            break
        if not line:
            continue
        try:
            parts = shlex.split(line)
        except ValueError as error:
            print(f"命令格式错误：{error}")
            continue
        command = parts[0]

        try:
            if command == "帮助":
                print(HELP_TEXT)
            elif command == "动作列表":
                actions = library.list_actions()
                print("动作：" + ("、".join(actions) if actions else "暂无动作"))
            elif command == "动作摘要":
                if len(parts) < 2:
                    print("请提供动作名称。")
                    continue
                summary = library.summarize_action(parts[1])
                for key, value in summary.items():
                    print(f"{key}：{value}")
            elif command in ("录制", "示教录制"):
                if len(parts) < 3:
                    print("用法：录制 动作名称 姿态数量")
                    continue
                name = parts[1]
                count = int(parts[2])
                output = library.action_path(name)
                wait = command == "示教录制"
                recorder.record_pose_sequence(count, output, wait_for_enter=wait)
                print(f"已保存动作：{output}")
            elif command in ("播放", "循环播放"):
                if len(parts) < 2:
                    print("请提供动作名称。")
                    continue
                sequence = library.load_action(parts[1])
                loop = command == "循环播放"

                def run_play() -> None:
                    try:
                        player.play(sequence, loop=loop)
                    except Exception as error:
                        print(f"播放失败：{error}")

                play_thread = threading.Thread(target=run_play, daemon=True)
                play_thread.start()
            elif command == "暂停":
                player.pause()
                print("已暂停。")
            elif command == "继续":
                player.resume()
                print("已继续。")
            elif command == "停止":
                player.stop()
                print("已停止。")
            elif command == "删除动作":
                if len(parts) < 2:
                    print("请提供动作名称。")
                    continue
                library.delete_action(parts[1])
                print("已删除。")
            elif command == "复制动作":
                if len(parts) < 3:
                    print("用法：复制动作 原名称 新名称")
                    continue
                library.copy_action(parts[1], parts[2])
                print("已复制。")
            elif command == "导出动作":
                if len(parts) < 3:
                    print("用法：导出动作 动作名称 路径")
                    continue
                target = resolve_stage6_path(parts[2])
                library.export_action(parts[1], target)
                print(f"已导出：{target}")
            elif command == "导入动作":
                if len(parts) < 2:
                    print("用法：导入动作 路径")
                    continue
                path = Path(parts[1])
                library.import_action(path)
                print("已导入。")
            elif command == "退出":
                player.stop()
                if play_thread and play_thread.is_alive():
                    play_thread.join(timeout=1.0)
                break
            else:
                print("未知命令。输入“帮助”查看命令。")
        except FileNotFoundError as error:
            print(str(error))
        except ValueError as error:
            print(f"动作格式不对或参数错误：{error}")
        except Exception as error:
            print(f"执行失败：{error}")


if __name__ == "__main__":
    main()
