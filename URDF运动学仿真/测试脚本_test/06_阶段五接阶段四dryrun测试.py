"""阶段五接阶段四 dry-run 集成测试。

用途：
1. 使用阶段五 URDF / IK 计算目标关节角。
2. 把 IK 结果交给阶段四 RealArmController.move_joints。
3. 强制阶段四保持 dry-run，不写真实舵机。

运行位置建议在项目根目录：
    mamba activate arm_rebot
    python URDF运动学仿真/测试脚本_test/06_阶段五接阶段四dryrun测试.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any


项目根目录 = Path(__file__).resolve().parents[2]
URDF目录 = 项目根目录 / "URDF运动学仿真"
真实控制目录 = 项目根目录 / "真实舵机控制"
sys.path.insert(0, str(URDF目录))
sys.path.insert(0, str(真实控制目录))

from 末端控制_cartesian_controller import 末端控制器
from 真实机械臂控制器_real_arm_controller import RealArmController
from 运动学模型_kinematics_model import 创建运动学模型


def 打印_json(payload: Any) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))


def 创建临时真实配置(dry_run: bool) -> Path:
    source = 真实控制目录 / "真实配置.yaml"
    with source.open("r", encoding="utf-8") as file:
        config = json.load(file)
    config.setdefault("transport", {})["dry_run"] = bool(dry_run)
    temp_dir = Path(tempfile.mkdtemp(prefix="stage5_stage4_dryrun_"))
    temp_path = temp_dir / "真实配置_临时dryrun.json"
    with temp_path.open("w", encoding="utf-8") as file:
        json.dump(config, file, ensure_ascii=False, indent=2)
        file.write("\n")
    return temp_path


def 解析参数() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="阶段五 IK -> 阶段四 dry-run move_joints 集成测试")
    parser.add_argument(
        "--xyz",
        nargs=3,
        type=float,
        default=[-0.0200, -0.0257 , 0.3512],
        metavar=("X", "Y", "Z"),
        help="默认目标来自 FK 姿态 [0, 20, 30, 10, 0]，通常能通过阶段四安全范围。",
    )
    parser.add_argument("--rpy", nargs=3, type=float, default=None, metavar=("ROLL", "PITCH", "YAW"))
    parser.add_argument("--duration", type=float, default=1.0)
    parser.add_argument("--no-connect", action="store_true", help="只初始化控制器和 IK，不连接阶段四 dry-run 驱动")
    return parser.parse_args()


def main() -> int:
    args = 解析参数()
    真实控制器 = None
    运动学 = None

    try:
        临时配置 = 创建临时真实配置(dry_run=True)
        真实控制器 = RealArmController(临时配置)
        print(f"[安全] 已使用临时阶段四配置强制 dry-run：{临时配置}")

        if not args.no_connect:
            connect_result = 真实控制器.connect()
            print(f"[阶段四] 连接结果：{connect_result.消息}")
            if not connect_result.成功:
                打印_json({"ok": False, "步骤": "阶段四 dry-run connect", "错误": connect_result.消息})
                return 1

        运动学 = 创建运动学模型(use_gui=False)
        末端 = 末端控制器(
            arm_controller=真实控制器,
            kinematics_model=运动学,
            dry_run=False,
        )

        print("[阶段五] 开始 move_pose：目标 xyz/rpy -> IK -> 阶段四 move_joints。")
        result = 末端.move_pose(
            xyz=args.xyz,
            rpy=args.rpy,
            duration=float(args.duration),
            wait=True,
        )
        打印_json(result)
        return 0 if result.get("ok") else 1
    except Exception as exc:
        打印_json({"ok": False, "错误": str(exc)})
        return 1
    finally:
        if 运动学 is not None:
            运动学.close()
        if 真实控制器 is not None and getattr(真实控制器, "connected", False):
            print(f"[阶段四] 断开：{真实控制器.disconnect().消息}")


if __name__ == "__main__":
    raise SystemExit(main())
