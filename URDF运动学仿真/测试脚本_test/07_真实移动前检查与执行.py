"""阶段五接阶段四：真实移动前检查与显式执行脚本。

默认只做检查，不移动真实舵机。

IK 检查模式：
    python URDF运动学仿真/测试脚本_test/07_真实移动前检查与执行.py --xyz 0.20 0.05 0.18

关节小步真实执行：
    python URDF运动学仿真/测试脚本_test/07_真实移动前检查与执行.py \
      --joint-delta-deg 0 0 2 0 0 0 \
      --execute-real \
      --i-understand-risk

IK 真实执行必须同时给两个参数：
    python URDF运动学仿真/测试脚本_test/07_真实移动前检查与执行.py \
      --xyz 0.20 0.05 0.18 \
      --execute-real \
      --i-understand-risk
"""

from __future__ import annotations

import argparse
import time


from 运动学测试路径_test_paths import create_temp_real_config, print_json

from 末端控制_cartesian_controller import 末端控制器
from 真实机械臂控制器_real_arm_controller import RealArmController
from 运动学模型_kinematics_model import SDK_JOINT_NAMES, 创建运动学模型


def 解析参数() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="真实移动前检查；必须显式确认才会真实执行")
    target_group = parser.add_mutually_exclusive_group(required=True)
    target_group.add_argument("--xyz", nargs=3, type=float, metavar=("X", "Y", "Z"), help="末端目标 xyz，走 IK")
    target_group.add_argument(
        "--joint-delta-deg",
        nargs=6,
        type=float,
        metavar=("J10", "J11", "J12", "J13", "J14", "J15"),
        help="从当前真实目标开始，每个关节小幅增量。J10 单位是 mm，其余关节单位是 deg。这个模式不走 IK。",
    )
    parser.add_argument("--rpy", nargs=3, type=float, default=None, metavar=("ROLL", "PITCH", "YAW"))
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--seed-home", action="store_true", help="IK 使用 [0,0,0,0,0,0] 作为种子，而不是当前真实关节目标")
    parser.add_argument("--seed-deg", nargs=6, type=float, default=None, metavar=("J10", "J11", "J12", "J13", "J14", "J15"))
    parser.add_argument("--hold-seconds", type=float, default=3.0, help="真实写入后保持连接等待的秒数")
    parser.add_argument("--disable-torque-on-exit", action="store_true", help="退出时关闭扭矩。默认不断扭矩，避免刚写入就掉力。")
    parser.add_argument("--execute-real", action="store_true", help="通过阶段四真实模式执行 move_joints")
    parser.add_argument("--i-understand-risk", action="store_true", help="确认你已清空机械臂周围并准备好断电/急停")
    return parser.parse_args()


def 打印安全清单() -> None:
    print("真实移动前请逐项确认：")
    print("  1. 机械臂周围没有人手、线缆、工具和障碍物。")
    print("  2. 阶段四标定文件是当前这台机械臂的标定文件。")
    print("  3. 阶段四单关节小幅移动已经测试过。")
    print("  4. 你已经先运行过 06_阶段五接阶段四dryrun测试.py。")
    print("  5. 你能立刻断电或执行急停。")
    print("  6. 本脚本仍然不会绕过阶段四安全检查。")


def 关节角度差报告(current_deg: dict[str, float], target_deg: dict[str, float]) -> dict[str, dict[str, float]]:
    report: dict[str, dict[str, float]] = {}
    for joint_key, target in target_deg.items():
        current = float(current_deg.get(joint_key, 0.0))
        report[joint_key] = {
            "current_deg": current,
            "target_deg": float(target),
            "delta_deg": float(target) - current,
        }
    return report


def 解析IK种子(args: argparse.Namespace) -> list[float] | None:
    if args.seed_deg is not None:
        return [float(value) for value in args.seed_deg]
    if args.seed_home:
        return [0.0, 0.0, 0.0, 0.0, 0.0, 0.0]
    return None


def main() -> int:
    args = 解析参数()
    真实控制器 = None
    运动学 = None
    execute_real = bool(args.execute_real and args.i_understand_risk)

    if args.execute_real and not args.i_understand_risk:
        print_json({"ok": False, "错误": "你加了 --execute-real，但没有加 --i-understand-risk，禁止真实移动。"})
        return 1

    打印安全清单()
    if execute_real:
        print("[模式] 真实执行模式：将临时切换阶段四真实模式，并通过阶段四 move_joints 执行。")
    else:
        print("[模式] 检查模式：只计算目标，不连接真实舵机，不移动。")

    try:
        临时配置 = create_temp_real_config(dry_run=not execute_real, prefix="stage5_stage4_real_")
        真实控制器 = RealArmController(临时配置)
        运动学 = 创建运动学模型(use_gui=False)

        # 纯 IK 检查模式不连接阶段四，不写舵机。
        if not execute_real:
            if args.joint_delta_deg is not None:
                print_json(
                    {
                        "ok": True,
                        "真实执行": False,
                        "模式": "joint_delta_check",
                        "joint_delta_deg": dict(zip(SDK_JOINT_NAMES, [float(v) for v in args.joint_delta_deg])),
                        "说明": "关节增量模式需要连接真实控制器读取当前位置；这里只检查参数格式。",
                    }
                )
                return 0
            末端 = 末端控制器(
                arm_controller=真实控制器,
                kinematics_model=运动学,
                dry_run=True,
            )
            result = 末端.move_pose(
                xyz=args.xyz,
                rpy=args.rpy,
                duration=float(args.duration),
                wait=True,
                seed_joints_deg=解析IK种子(args),
            )
            result["真实执行"] = False
            result["下一步"] = (
                "确认 target_joints_deg 和 IK 误差合理后，先运行 06 dry-run 集成测试；"
                "最后才考虑加 --execute-real --i-understand-risk。"
            )
            print_json(result)
            return 0 if result.get("ok") else 1

        print(f"[阶段四] 使用临时真实模式配置：{临时配置}")

        connect_result = 真实控制器.connect()
        print(f"[阶段四] 连接结果：{connect_result.消息}")
        if not connect_result.成功:
            print_json({"ok": False, "步骤": "阶段四真实 connect", "错误": connect_result.消息})
            return 1
        before_state = 真实控制器.get_state()
        print("[阶段四] 移动前状态：")
        print_json(before_state)

        current_angles = before_state.get("关节角度", {}) if isinstance(before_state, dict) else {}
        if not isinstance(current_angles, dict):
            print_json({"ok": False, "错误": "无法读取当前关节角度，禁止真实移动。"})
            return 1

        if args.joint_delta_deg is not None:
            requested_delta = [float(value) for value in args.joint_delta_deg]
            target_joints_deg = {
                joint_key: float(current_angles.get(joint_key, 0.0)) + requested_delta[idx]
                for idx, joint_key in enumerate(SDK_JOINT_NAMES)
            }
            delta_report = 关节角度差报告(current_angles, target_joints_deg)
            move_result = 真实控制器.move_joints(target_joints_deg)
            result = {
                "ok": bool(getattr(move_result, "成功", False)),
                "模式": "joint_delta",
                "真实执行": True,
                "target_joints_deg": target_joints_deg,
                "joint_delta_deg": delta_report,
                "说明": "已移除 5 度变化硬保护；仍会经过阶段四角度范围和标定 raw 安全检查。",
                "move_result": move_result,
            }
        else:
            末端 = 末端控制器(
                arm_controller=真实控制器,
                kinematics_model=运动学,
                dry_run=True,
            )
            result = 末端.move_pose(
                xyz=args.xyz,
                rpy=args.rpy,
                duration=float(args.duration),
                wait=True,
                seed_joints_deg=解析IK种子(args),
            )
            result["真实执行"] = True
            result["joint_delta_deg"] = 关节角度差报告(
                current_angles,
                result.get("target_joints_deg", {}),
            )
            result["说明"] = "已移除 5 度变化硬保护；仍会经过阶段四角度范围和标定 raw 安全检查。"
            if result.get("ok"):
                move_result = 真实控制器.move_joints(result.get("target_joints_deg", {}))
                result["move_result"] = move_result
                result["ok"] = bool(getattr(move_result, "成功", False))
        print_json(result)

        wait_seconds = max(0.0, float(args.hold_seconds))
        if result.get("ok") and wait_seconds > 0:
            print(f"[阶段四] 已写入目标，保持连接等待 {wait_seconds:.1f} 秒，让舵机有时间运动。")
            time.sleep(wait_seconds)
            after_state = 真实控制器.get_state()
            print("[阶段四] 等待后状态：")
            print_json(after_state)
        elif not result.get("ok"):
            print("[阶段四] 移动失败，阶段四没有写入舵机目标；不会等待舵机运动。")
        return 0 if result.get("ok") else 1
    except Exception as exc:
        print_json({"ok": False, "错误": str(exc)})
        return 1
    finally:
        if 运动学 is not None:
            运动学.close()
        if 真实控制器 is not None and getattr(真实控制器, "connected", False):
            print(f"[阶段四] 断开：{真实控制器.disconnect(disable_torque=bool(args.disable_torque_on_exit)).消息}")


if __name__ == "__main__":
    raise SystemExit(main())
