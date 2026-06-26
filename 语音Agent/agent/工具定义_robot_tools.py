"""提供给 Agent 的安全工具定义。"""

from __future__ import annotations

from typing import Any


ALLOWED_JOINT_NAMES = {
    "j10",
    "j11",
    "j12",
    "j13",
    "j14",
    "j15",
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "J10",
    "J11",
    "J12",
    "J13",
    "J14",
    "J15",
    "J1",
    "J2",
    "J3",
    "J4",
    "J5",
}

JOINT_ALIAS = {
    "J1": "j11",
    "J2": "j12",
    "J3": "j13",
    "J4": "j14",
    "J5": "j15",
    "J10": "j10",
    "J11": "j11",
    "J12": "j12",
    "J13": "j13",
    "J14": "j14",
    "J15": "j15",
    "shoulder_pan": "j11",
    "shoulder_lift": "j12",
    "elbow_flex": "j13",
    "wrist_flex": "j14",
    "wrist_roll": "j15",
}

SUPPORTED_BEHAVIORS = {"home", "open_gripper", "close_gripper"}


def robot_tool_specs() -> list[dict[str, Any]]:
    """OpenAI-compatible tools schema。"""

    return [
        {
            "type": "function",
            "function": {
                "name": "get_robot_state",
                "description": "查询机械臂当前模式、连接状态、关节角度、动作和 TCP 状态。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stop_robot",
                "description": "立即停止机械臂运动、动作回放或危险动作。用户说停、停止、别动、急停时优先调用。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "set_gripper",
                "description": "安全控制夹爪开合。open_ratio=0 表示关闭，1 表示完全打开。",
                "parameters": {
                    "type": "object",
                    "properties": {"open_ratio": {"type": "number", "minimum": 0.0, "maximum": 1.0}},
                    "required": ["open_ratio"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "rotate_joint",
                "description": "让导轨版机械臂 j10-j15 中某个关节小幅移动，delta_deg 必须在安全步长以内。j10 是底盘导轨，其余为旋转关节。",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "joint_name": {"type": "string", "enum": sorted(ALLOWED_JOINT_NAMES)},
                        "delta_deg": {"type": "number"},
                    },
                    "required": ["joint_name", "delta_deg"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "run_robot_behavior",
                "description": "执行内置安全行为，例如 home、open_gripper、close_gripper。",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string", "enum": sorted(SUPPORTED_BEHAVIORS)}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "play_action",
                "description": "播放阶段六动作库里的指定动作。",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}, "speed": {"type": "number"}, "loop": {"type": "boolean"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "start_face_follow",
                "description": "启动阶段九视觉跟随。默认 dry-run，不直接读取摄像头。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "stop_face_follow",
                "description": "停止阶段九视觉跟随。",
                "parameters": {"type": "object", "properties": {}, "additionalProperties": False},
            },
        },
    ]


def tool_names() -> list[str]:
    return [item["function"]["name"] for item in robot_tool_specs()]
