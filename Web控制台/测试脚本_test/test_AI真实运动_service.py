"""Web 服务中 AI 动作提议、二次确认与同进程执行测试。"""

from __future__ import annotations

import threading
import unittest

from Web测试路径_test_paths import ensure_web_test_paths

ensure_web_test_paths()

from backend.agent_pending_action import PendingActionStore
from backend.errors import WebAPIError
from backend.service import WebControlService


class NullLogger:
    def log(self, *args, **kwargs) -> None:
        return None


class FakeBridge:
    mode = "real"

    def __init__(self) -> None:
        self.connected = True
        self.joints = {"j10": 0.0, "j11": 0.0, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0}
        self.moves: list[dict[str, float]] = []
        self.single_moves: list[dict[str, float]] = []
        self.partial_moves: list[dict[str, float]] = []
        self.gripper_values: list[float] = []
        self.home_precheck_count = 0
        self.home_count = 0
        self.play_calls: list[dict] = []
        self.pose_calls: list[str] = []
        self.stop_count = 0
        self.action_status = {"state": "idle", "name": ""}
        self.gripper_available = True

    def is_connected(self) -> bool:
        return self.connected

    def get_state(self) -> dict:
        return {"ok": True, "message": "状态", "data": {"mode": self.mode, "connected": self.connected, "joints_deg": dict(self.joints)}}

    get_cached_state = get_state

    def move_joints(self, targets: dict[str, float]) -> dict:
        self.moves.append(dict(targets))
        self.joints.update(targets)
        return {"ok": True, "message": "已移动", "data": {"targets_deg": dict(targets)}}

    def move_single_joint_target(self, joint_key: str, target: float) -> dict:
        self.single_moves.append({joint_key: target})
        self.joints[joint_key] = target
        return {"ok": True, "message": "单关节已移动", "data": {"targets_deg": {joint_key: target}}}

    def move_partial_joint_targets(self, targets: dict[str, float]) -> dict:
        self.partial_moves.append(dict(targets))
        self.joints.update(targets)
        return {"ok": True, "message": "批量关节已移动", "data": {"targets_deg": dict(targets)}}

    def set_gripper(self, open_ratio: float) -> dict:
        if not self.gripper_available:
            return {"ok": False, "message": "夹爪未安装或未标定", "data": {}}
        self.gripper_values.append(open_ratio)
        return {"ok": True, "message": "夹爪完成", "data": {"open_ratio": open_ratio}}

    def get_calibration_status(self) -> dict:
        raw_items = {"gripper": {"range_min": 100, "range_max": 200}} if self.gripper_available else {}
        return {"ok": True, "message": "标定", "data": {"calibration": {"raw_items": raw_items}}}

    def home_precheck(self) -> dict:
        self.home_precheck_count += 1
        return {"ok": True, "message": "Home 预检通过", "data": {"targets_deg": {key: 0.0 for key in self.joints}}}

    def home(self) -> dict:
        self.home_count += 1
        return {"ok": True, "message": "已回 Home", "data": {}}

    def get_action(self, name: str) -> dict:
        if name not in {"挥手", "0726 演示"}:
            return {"ok": False, "message": "动作不存在", "data": {}}
        return {"ok": True, "message": "动作", "data": {"name": name, "frames": [{}, {}, {}], "duration_sec": 2.0}}

    def list_actions(self) -> dict:
        return {
            "ok": True,
            "message": "动作列表",
            "data": {"actions": [{"name": "挥手"}, {"name": "0726 演示"}]},
        }

    def play_action(self, name: str, speed: float, loop: bool) -> dict:
        self.play_calls.append({"name": name, "speed": speed, "loop": loop})
        return {"ok": True, "message": "播放完成", "data": {"name": name}}

    def list_poses(self) -> dict:
        return {
            "ok": True,
            "message": "姿态列表",
            "data": {
                "poses": [
                    {
                        "name": "展示位",
                        "description": "面向观众",
                        "pose": {"关节角度": [5.0, 10.0, 1.0, 2.0, 3.0, 4.0]},
                    }
                ]
            },
        }

    def get_pose(self, name: str) -> dict:
        if name != "展示位":
            return {"ok": False, "message": "姿态不存在", "data": {}}
        return {
            "ok": True,
            "message": "姿态详情",
            "data": {
                "name": name,
                "description": "面向观众",
                "pose": {"关节角度": [5.0, 10.0, 1.0, 2.0, 3.0, 4.0]},
            },
        }

    def goto_pose(self, name: str) -> dict:
        self.pose_calls.append(name)
        return {"ok": True, "message": "姿态已执行", "data": {"name": name}}

    def stop_action(self) -> dict:
        self.action_status = {"state": "idle", "name": ""}
        return {"ok": True, "message": "动作停止", "data": {}}

    def stop(self) -> dict:
        self.stop_count += 1
        return {"ok": True, "message": "已停止", "data": {}}


def make_service() -> tuple[WebControlService, FakeBridge]:
    service = WebControlService.__new__(WebControlService)
    bridge = FakeBridge()
    service.config = {"safety": {"real_mode_requires_confirm": False}}
    service.confirm_text = "我确认机械臂周围安全"
    service.bridge = bridge
    service._lock = threading.RLock()
    service._agent_pending = PendingActionStore()
    service._action_thread = None
    service._follow_controller = None
    service._continuous_jog_thread = None
    service._continuous_jog_stop = threading.Event()
    service._continuous_jog_status = {"running": False}
    service.logger = NullLogger()
    service.recent_error = None
    service._agent_app = None
    service._agent_demo_pending_action = None
    service._subject_lock_controller = None
    service.subject_lock_profiles = lambda: [
        {
            "profile_id": "环绕_001",
            "name": "环绕主体",
            "rail": {"start_mm": -20.0, "end_mm": 20.0, "requested_speed_mm_s": 2.0},
            "validation": {"valid": True},
            "calibration_point_count": 11,
        }
    ]
    service.subject_lock_profile = lambda profile_id: {
        "profile_id": profile_id,
        "name": "环绕主体",
        "rail": {"start_mm": -20.0, "end_mm": 20.0, "requested_speed_mm_s": 2.0},
        "validation": {"valid": True},
        "calibration_points": [{}] * 11,
    }
    service.subject_lock_calls = []
    service.subject_lock_move_to_start = lambda profile_id, _request: service.subject_lock_calls.append(
        ("move_to_start", profile_id)
    ) or {"message": "正在回到轨迹起点。"}
    service.subject_lock_play = lambda profile_id, _request: service.subject_lock_calls.append(
        ("play", profile_id)
    ) or {"message": "主体锁定轨迹已启动。"}
    service._load_agent_config = lambda: {
        "robot_api": {"default_mode": "real"},
        "safety": {
            "allow_real_robot_tools": True,
            "allowed_tools": [
                "get_robot_state", "stop_robot", "stop_face_follow", "set_gripper", "move_joint",
                "rotate_joint", "run_robot_behavior", "play_action", "goto_pose",
                "run_subject_lock_profile", "start_face_follow",
            ],
        },
    }
    service.follow_status = lambda: {"running": False, "effective_config": {"pan_joint": "j11", "tilt_joint": "j13"}}
    return service, bridge


class AgentRealMotionServiceTest(unittest.TestCase):
    def test_move_proposal_does_not_touch_controller_until_confirmation(self) -> None:
        service, bridge = make_service()

        proposal = service.agent_propose_tool("move_joint", {"joint_name": "J10", "mode": "relative", "value": 40.0})

        action = proposal["pending_action"]
        self.assertEqual(action["summary"]["unit"], "mm")
        self.assertEqual(action["summary"]["target"], 40.0)
        self.assertEqual(bridge.moves, [])

        result = service.agent_confirm_pending(action["id"])

        self.assertEqual(bridge.single_moves, [{"j10": 40.0}])
        self.assertEqual(bridge.moves, [])
        self.assertEqual(result["executed_action"]["status"], "executed")

    def test_confirmation_revalidates_relative_target_against_latest_state(self) -> None:
        service, bridge = make_service()
        proposal = service.agent_propose_tool("move_joint", {"joint_name": "J10", "mode": "relative", "value": 10.0})
        bridge.joints["j10"] = 0.5

        service.agent_confirm_pending(proposal["pending_action"]["id"])

        self.assertEqual(bridge.single_moves, [{"j10": 10.5}])
        self.assertEqual(bridge.moves, [])

    def test_real_tools_must_be_locally_enabled_and_connected(self) -> None:
        service, bridge = make_service()
        service._load_agent_config = lambda: {
            "robot_api": {"default_mode": "real"},
            "safety": {"allow_real_robot_tools": False, "allowed_tools": ["move_joint"]},
        }
        with self.assertRaisesRegex(WebAPIError, "禁止"):
            service.agent_propose_tool("move_joint", {"joint_name": "J12", "mode": "relative", "value": 1.0})

        service, bridge = make_service()
        bridge.connected = False
        with self.assertRaisesRegex(WebAPIError, "连接"):
            service.agent_propose_tool("move_joint", {"joint_name": "J12", "mode": "relative", "value": 1.0})

    def test_home_runs_precheck_before_card_and_again_on_confirmation(self) -> None:
        service, bridge = make_service()

        proposal = service.agent_propose_tool("run_robot_behavior", {"name": "home"})
        self.assertEqual(bridge.home_precheck_count, 1)

        service.agent_confirm_pending(proposal["pending_action"]["id"])

        self.assertEqual(bridge.home_precheck_count, 2)
        self.assertEqual(bridge.home_count, 1)

    def test_gripper_is_rejected_before_card_when_unavailable(self) -> None:
        service, bridge = make_service()
        bridge.gripper_available = False

        with self.assertRaisesRegex(WebAPIError, "夹爪未安装或未标定"):
            service.agent_propose_tool("set_gripper", {"open_ratio": 1.0})

    def test_open_gripper_behavior_normalizes_to_gripper_tool(self) -> None:
        service, bridge = make_service()

        proposal = service.agent_propose_tool("run_robot_behavior", {"name": "open_gripper"})
        self.assertEqual(proposal["pending_action"]["tool_name"], "set_gripper")
        service.agent_confirm_pending(proposal["pending_action"]["id"])

        self.assertEqual(bridge.gripper_values, [1.0])

    def test_action_playback_is_existing_and_never_loops(self) -> None:
        service, bridge = make_service()

        proposal = service.agent_propose_tool("play_action", {"name": "挥手", "speed": 1.5, "loop": True})
        self.assertFalse(proposal["pending_action"]["arguments"]["loop"])
        service.agent_confirm_pending(proposal["pending_action"]["id"])
        service._action_thread.join(timeout=1.0)

        self.assertEqual(bridge.play_calls, [{"name": "挥手", "speed": 1.5, "loop": False}])

    def test_legacy_agent_demo_execution_only_creates_standard_confirmation(self) -> None:
        service, bridge = make_service()
        service.config["agent_demo"] = {
            "enabled": True,
            "trigger_text": "生成轨迹",
            "execute_texts": ["执行"],
            "action_name": "挥手",
            "speed": 1.25,
        }

        service._handle_agent_demo_message("生成轨迹")
        result = service._handle_agent_demo_message("执行")

        self.assertIsNotNone(result)
        self.assertEqual(result["pending_action"]["tool_name"], "play_action")
        self.assertEqual(result["pending_action"]["arguments"], {"name": "挥手", "speed": 1.25, "loop": False})
        self.assertEqual(bridge.play_calls, [])

    def test_home_remains_a_deterministic_safety_command(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_direct_command("请回 home")

        self.assertEqual(result["pending_action"]["tool_name"], "run_robot_behavior")
        self.assertEqual(result["pending_action"]["arguments"]["name"], "home")

    def test_joint_motion_falls_through_to_model_semantics(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_direct_command("让j11转动正三度")

        self.assertIsNone(result)

    def test_action_playback_falls_through_to_model_semantics(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_direct_command("执行动作：0726 演示")

        self.assertIsNone(result)

    def test_semantic_action_name_resolves_against_library_after_model_understands_request(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "tool_name": "play_action",
                "arguments": {"name": "0726演示"},
                "missing": [],
                "confidence": 0.98,
                "source_text": "能不能执行那个动作？0726演示。",
                "evidence": {"action": "0726演示"},
            }
        )

        self.assertEqual(result["pending_action"]["tool_name"], "play_action")
        self.assertEqual(result["pending_action"]["arguments"]["name"], "0726 演示")

    def test_semantic_action_misclassified_as_behavior_is_grounded_to_action_library(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "tool_name": "run_robot_behavior",
                "arguments": {"name": "0726演示"},
                "missing": [],
                "confidence": 0.98,
                "source_text": "能不能执行那个动作0726演示。",
                "evidence": {"action": "0726演示"},
            }
        )

        self.assertEqual(result["pending_action"]["tool_name"], "play_action")
        self.assertEqual(result["pending_action"]["arguments"]["name"], "0726 演示")

    def test_semantic_read_tools_return_real_libraries_without_confirmation(self) -> None:
        service, _bridge = make_service()
        cases = [
            ("list_actions", "0726 演示", "actions", 0.99),
            ("list_poses", "展示位", "poses", 0.0),
            ("list_subject_lock_profiles", "环绕主体", "subject_lock_profiles", 0.99),
        ]

        for tool_name, expected_text, payload_key, confidence in cases:
            result = service._handle_agent_semantic_intent(
                {
                    "kind": "command",
                    "tool_name": tool_name,
                    "arguments": {},
                    "missing": [],
                    "confidence": confidence,
                    "source_text": "读取库内容",
                    "evidence": {},
                }
            )

            self.assertIn(expected_text, result["reply"])
            self.assertIn(payload_key, result["raw_payload"])
            self.assertNotIn("pending_action", result)

    def test_semantic_pose_execution_creates_card_and_runs_only_after_confirmation(self) -> None:
        service, bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "tool_name": "goto_pose",
                "arguments": {"name": "展示位"},
                "missing": [],
                "confidence": 0.99,
                "source_text": "执行姿态展示位",
                "evidence": {"pose": "展示位"},
            }
        )

        action = result["pending_action"]
        self.assertEqual(action["tool_name"], "goto_pose")
        self.assertEqual(action["summary"]["pose_name"], "展示位")
        self.assertEqual(bridge.pose_calls, [])

        service.agent_confirm_pending(action["id"])

        self.assertEqual(bridge.pose_calls, ["展示位"])

    def test_semantic_subject_lock_profile_creates_card_for_each_safe_step(self) -> None:
        service, _bridge = make_service()

        for operation, expected_call in (("move_to_start", "move_to_start"), ("play", "play")):
            result = service._handle_agent_semantic_intent(
                {
                    "kind": "command",
                    "tool_name": "run_subject_lock_profile",
                    "arguments": {"name": "环绕主体", "operation": operation},
                    "missing": [],
                    "confidence": 0.99,
                    "source_text": f"{operation} 环绕主体",
                    "evidence": {"profile": "环绕主体"},
                }
            )

            action = result["pending_action"]
            self.assertEqual(action["tool_name"], "run_subject_lock_profile")
            self.assertEqual(action["arguments"]["profile_id"], "环绕_001")
            self.assertEqual(action["summary"]["profile_name"], "环绕主体")
            service.agent_confirm_pending(action["id"])

            self.assertEqual(service.subject_lock_calls[-1], (expected_call, "环绕_001"))

    def test_direct_stop_follow_is_immediate_and_never_creates_pending_action(self) -> None:
        service, _bridge = make_service()
        service.stop_follow = lambda: {"message": "视觉跟随已停止。"}

        result = service._handle_agent_direct_command("停止视觉跟随")

        self.assertEqual(result["reply"], "视觉跟随已停止。")
        self.assertNotIn("pending_action", result)

    def test_non_command_still_falls_through_to_model(self) -> None:
        service, _bridge = make_service()
        self.assertIsNone(service._handle_agent_direct_command("解释一下 J12 是做什么的"))

    def test_semantic_intent_creates_the_same_safe_pending_action(self) -> None:
        service, bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "tool_name": "move_joint",
                "arguments": {"joint_name": "j12", "mode": "relative", "value": 1.0},
                "missing": [],
                "confidence": 0.98,
                "source_text": "j12 正转 1 度",
                "evidence": {"joint": "j12", "direction_or_target": "正转", "value": "1", "unit": "度"},
            }
        )

        self.assertEqual(result["pending_action"]["tool_name"], "move_joint")
        self.assertEqual(bridge.single_moves, [])

    def test_semantic_model_cannot_invent_a_number_for_vague_language(self) -> None:
        service, bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "tool_name": "move_joint",
                "arguments": {"joint_name": "j12", "mode": "relative", "value": 1.0},
                "missing": [],
                "confidence": 1.0,
                "source_text": "让肩部抬一点",
                "evidence": {"joint": "j12", "direction_or_target": "抬", "value": "一点", "unit": ""},
            }
        )

        self.assertIn("具体", result["reply"])
        self.assertNotIn("要操作的关节", result["reply"])
        self.assertNotIn("pending_action", result)
        self.assertEqual(bridge.single_moves, [])

    def test_semantic_ambiguity_only_asks_for_missing_information(self) -> None:
        service, bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "clarify",
                "tool_name": "move_joint",
                "arguments": {"joint_name": "j12", "mode": "relative"},
                "missing": ["value"],
                "reply": "请说明 J12 要正转多少度。",
                "confidence": 0.96,
            }
        )

        self.assertIn("多少度", result["reply"])
        self.assertNotIn("pending_action", result)
        self.assertEqual(bridge.moves, [])
        self.assertEqual(bridge.single_moves, [])

    def test_ambiguous_combined_command_rejects_the_whole_plan(self) -> None:
        service, bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "clarify",
                "execution_mode": "simultaneous",
                "actions": [
                    {
                        "tool_name": "move_joint",
                        "arguments": {"joint_name": "j10", "mode": "absolute", "value": 30},
                        "missing": [],
                        "evidence": {"joint": "j10", "direction_or_target": "运动到", "value": "30", "unit": "mm"},
                    },
                    {
                        "tool_name": "move_joint",
                        "arguments": {"joint_name": "j11", "mode": "relative", "value": 30},
                        "missing": ["direction"],
                        "evidence": {"joint": "j11", "direction_or_target": "", "value": "30", "unit": "度"},
                    },
                ],
                "missing": ["actions[1].direction"],
                "reply": "J10 的目标已明确；请说明 J11 是正转 30 度还是反转 30 度。",
                "confidence": 0.99,
                "source_text": "同时让 j10 运动到 30mm，j11 转动 30 度",
            }
        )

        self.assertIn("J11", result["reply"])
        self.assertNotIn("pending_action", result)
        self.assertIsNone(service._agent_pending.current())
        self.assertEqual(bridge.partial_moves, [])

    def test_server_rejects_combined_relative_move_without_a_direction_even_if_model_calls_it_command(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "execution_mode": "simultaneous",
                "actions": [
                    {
                        "tool_name": "move_joint",
                        "arguments": {"joint_name": "j10", "mode": "absolute", "value": 30},
                        "missing": [],
                        "evidence": {"joint": "j10", "direction_or_target": "运动到", "value": "30", "unit": "mm"},
                    },
                    {
                        "tool_name": "move_joint",
                        "arguments": {"joint_name": "j11", "mode": "relative", "value": 30},
                        "missing": [],
                        "evidence": {"joint": "j11", "direction_or_target": "转动", "value": "30", "unit": "度"},
                    },
                ],
                "missing": [],
                "reply": "",
                "confidence": 1.0,
                "source_text": "同时让 j10 运动到 30mm，j11 转动 30 度",
            }
        )

        self.assertIn("正反方向", result["reply"])
        self.assertNotIn("pending_action", result)

    def test_complete_combined_command_creates_one_plan_and_executes_partial_targets(self) -> None:
        service, bridge = make_service()

        result = service._handle_agent_semantic_intent(
            {
                "kind": "command",
                "execution_mode": "simultaneous",
                "actions": [
                    {
                        "tool_name": "move_joint",
                        "arguments": {"joint_name": "j10", "mode": "absolute", "value": 30},
                        "missing": [],
                        "evidence": {"joint": "j10", "direction_or_target": "运动到", "value": "30", "unit": "mm"},
                    },
                    {
                        "tool_name": "move_joint",
                        "arguments": {"joint_name": "j11", "mode": "relative", "value": 30},
                        "missing": [],
                        "evidence": {"joint": "j11", "direction_or_target": "正转", "value": "30", "unit": "度"},
                    },
                ],
                "missing": [],
                "reply": "",
                "confidence": 0.99,
                "source_text": "同时让 j10 运动到 30mm，j11 正转 30 度",
            }
        )

        action = result["pending_action"]
        self.assertEqual(action["tool_name"], "move_joint_plan")
        self.assertEqual([item["joint"] for item in action["summary"]["items"]], ["J10", "J11"])
        self.assertEqual(bridge.partial_moves, [])

        service.agent_confirm_pending(action["id"])

        self.assertEqual(bridge.partial_moves, [{"j10": 30.0, "j11": 30.0}])
        self.assertEqual(bridge.moves, [])
        self.assertEqual(bridge.single_moves, [])
        self.assertEqual(bridge.joints["j12"], 0.0)

    def test_only_home_uses_the_direct_standard_pending_store(self) -> None:
        service, _bridge = make_service()

        result = service._handle_agent_direct_command("回 Home")

        action = result["pending_action"]
        self.assertEqual(action["tool_name"], "run_robot_behavior")
        service.agent_cancel_pending(action["id"])

    def test_busy_action_rejects_new_increasing_risk_proposal(self) -> None:
        service, bridge = make_service()
        bridge.action_status = {"state": "playing", "name": "挥手"}

        with self.assertRaisesRegex(WebAPIError, "先停止") as error:
            service.agent_propose_tool("move_joint", {"joint_name": "J12", "mode": "relative", "value": 1.0})

        self.assertEqual(error.exception.code, "AGENT_MOTION_BUSY")

    def test_start_follow_uses_real_mode_after_confirmation(self) -> None:
        service, _bridge = make_service()
        requests = []
        service.follow_status = lambda: {
            "running": False,
            "latest_url": "http://camera.local:8000/latest",
            "robot_api_base": "http://127.0.0.1:8010",
            "effective_config": {
                "pan_joint": "j11",
                "tilt_joint": "j13",
                "enabled_follow_joints": ["j11", "j13"],
                "pan_gain_deg_per_norm": 1.0,
                "tilt_gain_deg_per_norm": 1.0,
                "max_pan_step_deg": 2.0,
                "max_tilt_step_deg": 2.0,
            },
        }
        service.start_follow = lambda request: requests.append(request) or {"message": "视觉跟随已启动"}

        proposal = service.agent_propose_tool("start_face_follow", {})
        service.agent_confirm_pending(proposal["pending_action"]["id"])

        self.assertEqual(len(requests), 1)
        self.assertFalse(requests[0].dry_run)
        self.assertEqual(requests[0].latest_url, "http://camera.local:8000/latest")
        self.assertEqual(requests[0].enabled_follow_joints, ["j11", "j13"])
        self.assertEqual(requests[0].pan_gain, 1.0)

    def test_stop_invalidates_pending_action(self) -> None:
        service, _bridge = make_service()
        service.agent_propose_tool("move_joint", {"joint_name": "J12", "mode": "relative", "value": 1.0})

        service.stop()

        self.assertIsNone(service._agent_pending.current())


if __name__ == "__main__":
    unittest.main()
