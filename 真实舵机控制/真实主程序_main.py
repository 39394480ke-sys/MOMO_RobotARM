"""我的MomoAgent真实舵机控制系统入口。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from 真实机械臂控制器_real_arm_controller import RealArmController, 操作结果
from 角度映射_angle_mapper import JOINT_ORDER, MULTI_TURN_JOINTS, joint_label


当前目录 = Path(__file__).resolve().parent
仿真目录 = (当前目录 / "../仿真控制系统").resolve()
if str(仿真目录) not in sys.path:
    sys.path.insert(0, str(仿真目录))

try:
    from 动作播放器_action_player import 动作播放器
    from 姿态管理.姿态管理_pose_manager import 姿态管理器
except Exception:
    动作播放器 = None
    姿态管理器 = None


def 主函数() -> None:
    """程序入口。"""

    try:
        控制器 = RealArmController(当前目录 / "真实配置.yaml")
        姿态管理, 动作播放 = 创建阶段三复用模块(控制器)
    except Exception as 错误:
        print(f"启动失败：{错误}")
        sys.exit(1)

    打印欢迎信息(控制器)

    while True:
        try:
            输入内容 = input("\n请输入命令 > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n收到退出信号。")
            if 控制器.connected:
                print(控制器.disconnect().消息)
            break

        if not 输入内容:
            continue

        try:
            是否退出 = 处理命令(输入内容, 控制器, 姿态管理, 动作播放)
        except Exception as 错误:
            print(f"命令执行异常：{错误}")
            是否退出 = False

        if 是否退出:
            break


def 创建阶段三复用模块(控制器: RealArmController):
    """复用阶段三姿态库和动作播放器。"""

    files = 控制器.config.get("files", {})
    pose_path = (当前目录 / files.get("stage3_pose_library", "../仿真控制系统/姿态管理/姿态库.json")).resolve()
    action_dir = (当前目录 / files.get("stage3_action_dir", "../仿真控制系统/姿态管理/动作库")).resolve()

    姿态管理 = None
    动作播放 = None
    if 姿态管理器 is not None:
        姿态管理 = 姿态管理器(pose_path)
    else:
        print("提示：未能加载阶段三姿态管理模块，前往姿态命令不可用。")

    if 动作播放器 is not None:
        默认等待秒 = 0.25 if not 控制器.is_dry_run() else 0.12
        动作播放 = 动作播放器(控制器, action_dir, 默认等待秒=默认等待秒, 默认插值步数=8)
    else:
        print("提示：未能加载阶段三动作播放器模块，播放动作命令不可用。")

    return 姿态管理, 动作播放


def 处理命令(
    输入内容: str,
    控制器: RealArmController,
    姿态管理: Any,
    动作播放: Any,
) -> bool:
    """解析并执行一行命令。返回 True 表示退出程序。"""

    片段 = 输入内容.split()
    命令 = 标准化命令(片段[0])
    参数 = 片段[1:]

    if 命令 == "帮助":
        打印帮助()
        return False

    if 命令 == "连接":
        结果 = 控制器.connect()
        print(结果.消息)
        if 结果.成功:
            打印状态(控制器)
        return False

    if 命令 == "状态":
        打印状态(控制器)
        return False

    if 命令 == "标定状态":
        打印标定状态(控制器.calibration_report())
        return False

    if 命令 == "标定说明":
        打印标定说明()
        return False

    if 命令 == "应用标定":
        打印应用标定提示()
        return False

    if 命令 == "移动":
        执行移动(参数, 控制器)
        return False

    if 命令 == "移动单关节":
        执行移动单关节(参数, 控制器)
        return False

    if 命令 == "微调":
        执行微调(参数, 控制器)
        return False

    if 命令 == "夹爪":
        执行夹爪(参数, 控制器)
        return False

    if 命令 == "张开夹爪":
        打印结果(控制器.张开夹爪())
        return False

    if 命令 == "闭合夹爪":
        打印结果(控制器.闭合夹爪())
        return False

    if 命令 == "回家":
        打印结果(控制器.move_home())
        return False

    if 命令 == "急停":
        打印结果(控制器.stop())
        return False

    if 命令 == "dryrun":
        执行dryrun(参数, 控制器)
        return False

    if 命令 == "前往姿态":
        执行前往姿态(参数, 控制器, 姿态管理)
        return False

    if 命令 == "播放动作":
        执行播放动作(参数, 控制器, 动作播放)
        return False

    if 命令 == "姿态列表":
        if 姿态管理 is None:
            print("姿态管理模块不可用。")
        else:
            打印名称列表("姿态列表", 姿态管理.列出姿态())
        return False

    if 命令 == "动作列表":
        if 动作播放 is None:
            print("动作播放器不可用。")
        else:
            打印名称列表("动作列表", 动作播放.列出动作())
        return False

    if 命令 == "保存姿态":
        执行保存姿态(参数, 控制器, 姿态管理)
        return False

    if 命令 == "断开":
        print(控制器.disconnect().消息)
        return False

    if 命令 == "退出":
        if 控制器.connected:
            print(控制器.disconnect().消息)
        print("已退出真实舵机控制系统。")
        return True

    print(f"未知命令：{片段[0]}")
    print("输入“帮助”查看命令。")
    return False


def 标准化命令(命令: str) -> str:
    """命令别名归一。"""

    aliases = {
        "help": "帮助",
        "帮助": "帮助",
        "connect": "连接",
        "连接": "连接",
        "state": "状态",
        "状态": "状态",
        "calibration": "标定状态",
        "标定状态": "标定状态",
        "标定说明": "标定说明",
        "应用标定": "应用标定",
        "移动": "移动",
        "move": "移动",
        "移动单关节": "移动单关节",
        "move-one": "移动单关节",
        "微调": "微调",
        "相对移动": "微调",
        "jog": "微调",
        "jog-one": "微调",
        "夹爪": "夹爪",
        "gripper": "夹爪",
        "张开夹爪": "张开夹爪",
        "open-gripper": "张开夹爪",
        "闭合夹爪": "闭合夹爪",
        "close-gripper": "闭合夹爪",
        "回家": "回家",
        "home": "回家",
        "急停": "急停",
        "stop": "急停",
        "dryrun": "dryrun",
        "dry-run": "dryrun",
        "前往姿态": "前往姿态",
        "goto-pose": "前往姿态",
        "播放动作": "播放动作",
        "play-action": "播放动作",
        "姿态列表": "姿态列表",
        "动作列表": "动作列表",
        "保存姿态": "保存姿态",
        "断开": "断开",
        "disconnect": "断开",
        "退出": "退出",
        "exit": "退出",
        "quit": "退出",
    }
    return aliases.get(命令, 命令)


def 执行移动(参数: list[str], 控制器: RealArmController) -> None:
    """执行：移动 0 20 30 10 0。"""

    if len(参数) != 5:
        print("移动失败：格式应为：移动 角度1 角度2 角度3 角度4 角度5")
        print("顺序固定：J1_底座旋转 J2_肩部抬升 J3_肘部弯曲 J4_腕部俯仰 J5_腕部旋转")
        return
    try:
        angles = [float(value) for value in 参数]
    except ValueError:
        print("移动失败：角度必须是数字。示例：移动 0 20 30 10 0")
        return

    target = {joint_key: angles[index] for index, joint_key in enumerate(JOINT_ORDER)}
    打印结果(控制器.move_joints(target))


def 执行移动单关节(参数: list[str], 控制器: RealArmController) -> None:
    """执行：移动单关节 2 2。"""

    if len(参数) != 2:
        print("移动单关节失败：格式应为：移动单关节 关节编号 目标绝对角度")
        print("注意：这是绝对角度，不是相对加减。连续小步移动请用：微调 关节编号 增量角度")
        return
    try:
        joint_no = int(参数[0])
        target_deg = float(参数[1])
    except ValueError:
        print("移动单关节失败：关节编号必须是整数，角度必须是数字。")
        return
    if joint_no < 1 or joint_no > len(JOINT_ORDER):
        print("移动单关节失败：关节编号必须是 1 到 5。")
        return

    joint_key = JOINT_ORDER[joint_no - 1]
    print(f"移动单关节是绝对角度命令：{joint_label(joint_key)} 将移动到 {target_deg:.2f} 度。")
    打印结果(控制器.move_joint(joint_key, target_deg))


def 执行微调(参数: list[str], 控制器: RealArmController) -> None:
    """执行：微调 1 1，表示 J1 在当前角度基础上加 1 度。"""

    if len(参数) != 2:
        print("微调失败：格式应为：微调 关节编号 增量角度")
        print("示例：微调 1 1 表示 J1 当前角度 +1 度；微调 1 -1 表示 J1 当前角度 -1 度。")
        return
    try:
        joint_no = int(参数[0])
        delta_deg = float(参数[1])
    except ValueError:
        print("微调失败：关节编号必须是整数，增量角度必须是数字。")
        return
    if joint_no < 1 or joint_no > len(JOINT_ORDER):
        print("微调失败：关节编号必须是 1 到 5。")
        return
    joint_key = JOINT_ORDER[joint_no - 1]
    打印结果(控制器.jog_joint(joint_key, delta_deg))


def 执行夹爪(参数: list[str], 控制器: RealArmController) -> None:
    """执行夹爪命令。"""

    if len(参数) != 1:
        print("夹爪命令格式：夹爪 0-100，或：夹爪 张开，夹爪 闭合")
        return
    value = 参数[0]
    if value in {"张开", "打开", "open"}:
        打印结果(控制器.张开夹爪())
        return
    if value in {"闭合", "关闭", "close"}:
        打印结果(控制器.闭合夹爪())
        return
    try:
        打印结果(控制器.set_gripper(float(value)))
    except ValueError:
        print("夹爪命令失败：请输入 0 到 100 的数字。")


def 执行dryrun(参数: list[str], 控制器: RealArmController) -> None:
    """执行 dryrun 开/关。"""

    if len(参数) != 1 or 参数[0] not in {"开", "关", "on", "off", "true", "false"}:
        print("dryrun 命令格式：dryrun 开 或 dryrun 关")
        return

    开启 = 参数[0] in {"开", "on", "true"}
    if not 开启:
        print("警告：关闭 dry-run 后会控制真实机械臂。")
        确认 = input("如确认机械臂周围安全，请输入：我确认机械臂周围安全\n确认 > ").strip()
        if 确认 != "我确认机械臂周围安全":
            print("确认文本不匹配，保持 dry-run 开启。")
            return

        标定报告 = 控制器.calibration_report()
        if not 标定报告["允许真机移动"]:
            print("标定不完整，禁止关闭 dry-run。请先执行“标定状态”查看缺失字段。")
            return

    print(控制器.set_dry_run(开启).消息)


def 执行前往姿态(参数: list[str], 控制器: RealArmController, 姿态管理: Any) -> None:
    """执行：前往姿态 姿态名称。"""

    if 姿态管理 is None:
        print("前往姿态失败：阶段三姿态管理模块不可用。")
        return
    if not 参数:
        print("前往姿态失败：请提供姿态名称。示例：前往姿态 初始姿态")
        return
    name = " ".join(参数)
    pose = 姿态管理.获取姿态(name)
    if pose is None:
        print(f"前往姿态失败：没有找到姿态“{name}”。")
        return
    打印结果(控制器.apply_pose(pose))


def 执行播放动作(参数: list[str], 控制器: RealArmController, 动作播放: Any) -> None:
    """执行：播放动作 动作名称。"""

    if 动作播放 is None:
        print("播放动作失败：阶段三动作播放器不可用。")
        return
    if not 参数:
        print("播放动作失败：请提供动作名称。示例：播放动作 挥手")
        return

    if not 控制器.is_dry_run():
        动作播放.设置播放速度(等待秒=0.25, 插值步数=10)
        print("真实模式下动作播放已自动降速。")

    name = " ".join(参数)
    print(f"开始播放动作：{name}")
    result = 动作播放.播放动作(name, 打印回调=print)
    打印结果(result)


def 执行保存姿态(参数: list[str], 控制器: RealArmController, 姿态管理: Any) -> None:
    """保存当前姿态到阶段三姿态库。"""

    if 姿态管理 is None:
        print("保存姿态失败：阶段三姿态管理模块不可用。")
        return
    if not 参数:
        print("保存姿态失败：请提供姿态名称。")
        return
    name = " ".join(参数)
    姿态管理.保存姿态(name, 控制器.获取当前状态(), 说明="真实控制系统保存的姿态。")
    print(f"保存成功：{name}")


def 打印状态(控制器: RealArmController) -> None:
    """打印当前逻辑角度、raw 和多圈状态。"""

    state = 控制器.get_state()
    if "错误" in state:
        print(state["错误"])
        return

    print("\n当前状态：")
    print(f"模式：{state['模式']}，已连接：{state['已连接']}")
    print("关节角度与 raw：")
    for joint_key in JOINT_ORDER:
        angle = state.get("关节角度", {}).get(joint_key, 0.0)
        raw = state.get("raw_present_position", {}).get(joint_key, "未读取")
        print(f"  {joint_label(joint_key)} ({joint_key})：{angle:.2f} 度，raw={raw}")

    print("多圈状态：")
    multi_turn_state = state.get("multi_turn_state", {})
    for joint_key in MULTI_TURN_JOINTS:
        item = multi_turn_state.get(joint_key)
        if not item:
            print(f"  {joint_label(joint_key)} ({joint_key})：未读取")
            continue
        print(
            f"  {item['show_name']} ({joint_key})：home={item['home_present_raw']} "
            f"current={item['current_raw']} relative={item['relative_raw']} "
            f"joint_deg={item['joint_deg']:.2f} goal={item['goal_raw']}"
        )

    gripper = state.get("夹爪", {})
    if gripper:
        print(f"夹爪：{gripper.get('open_value', 0.0):.1f}% raw={gripper.get('present_raw', '未读取')}")


def 打印标定状态(report: dict[str, Any]) -> None:
    """打印标定文件报告。"""

    print("\n标定状态：")
    print(f"标定文件：{report['标定文件']}")
    print(f"文件存在：{'是' if report.get('是否存在') else '否'}")
    print(f"允许真机移动：{'是' if report['允许真机移动'] else '否'}")
    if report.get("标定说明"):
        print(f"标定说明：{report['标定说明']}")
    if report.get("_meta"):
        meta = report["_meta"]
        print(f"生成脚本：{meta.get('script', '未知')}")
        print(f"单圈有限位关节：{', '.join(meta.get('bounded_single_turn_joints', []))}")
        print(f"多圈 absolute raw 关节：{', '.join(meta.get('absolute_raw_joints', []))}")
    for joint_key, item in report["项目"].items():
        status = "完整" if item["完整"] else "不完整"
        print(f"  {item['show_name']} ({joint_key})：{status}")
        for issue in item["问题"]:
            print(f"    - {issue}")
        if item["缺失字段"]:
            print(f"    - 缺失字段：{', '.join(item['缺失字段'])}")


def 打印标定说明() -> None:
    """打印标定程序说明。"""

    print(
        """
标定说明：
  重新标定请退出当前程序后运行：
    mamba activate momo_rebot
    cd 真实舵机控制
    python 标定程序_calibrate.py

  只应用已有标定请运行：
    mamba activate momo_rebot
    cd 真实舵机控制
    python 标定应用_apply_calibration.py

区别：
  dry-run：不需要真实依赖，不连接硬件。
  标定程序：需要真实依赖和硬件，读取/写入寄存器，生成 标定文件.json。
  真实控制：需要真实依赖和硬件，每次 connect() 只读取 标定文件.json，不重新标定。
""".strip()
    )


def 打印应用标定提示() -> None:
    """为了安全，主程序内不直接应用标定。"""

    print(
        """
应用标定需要退出当前交互控制程序后单独运行：
  mamba activate momo_rebot
  cd 真实舵机控制
  python 标定应用_apply_calibration.py

该脚本会把已有 标定文件.json 中的寄存器配置写入真实舵机。
第一版不在交互控制过程中直接应用标定，避免误操作。
""".strip()
    )


def 打印名称列表(title: str, names: list[str]) -> None:
    """打印名称列表。"""

    print(f"\n{title}：")
    if not names:
        print("  暂无")
        return
    for name in names:
        print(f"  - {name}")


def 打印结果(result: 操作结果) -> None:
    """统一打印执行结果。"""

    print(result.消息)


def 打印欢迎信息(控制器: RealArmController) -> None:
    """打印启动信息。"""

    print("欢迎使用 我的MomoAgent真实舵机控制系统")
    print(f"当前模式：{'dry-run' if 控制器.is_dry_run() else '真实模式'}")
    print("警告：真实模式会控制机械臂，请确认机械臂周围安全")
    print("输入 帮助 查看命令")


def 打印帮助() -> None:
    """打印帮助。"""

    print(
        """
可用命令：
  帮助
  连接
  状态
  标定状态
  标定说明
  应用标定
  移动 0 20 30 10 0
  移动单关节 2 2      # 绝对角度：J2 移动到 2 度
  微调 2 1             # 相对角度：J2 在当前角度基础上 +1 度
  微调 2 -1            # 相对角度：J2 在当前角度基础上 -1 度
  夹爪 50
  张开夹爪
  闭合夹爪
  回家
  急停
  dryrun 开
  dryrun 关
  前往姿态 初始姿态
  播放动作 挥手
  姿态列表
  动作列表
  保存姿态 A姿态
  断开
  退出

关节顺序固定：
  J1 shoulder_pan  = 底座旋转
  J2 shoulder_lift = 肩部抬升，多圈
  J3 elbow_flex    = 肘部弯曲，多圈
  J4 wrist_flex    = 腕部俯仰
  J5 wrist_roll    = 腕部旋转，多圈
""".strip()
    )


if __name__ == "__main__":
    主函数()
