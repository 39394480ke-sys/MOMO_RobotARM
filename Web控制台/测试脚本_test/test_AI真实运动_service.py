"""Web 服务中 AI 动作提议、二次确认与同进程执行测试。"""

from __future__ import annotations

import threading
import types
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
        self.gripper_values: list[float] = []
        self.home_precheck_count = 0
        self.home_count = 0
        self.play_calls: list[dict] = []
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
        if name != "挥手":
            return {"ok": False, "message": "动作不存在", "data": {}}
        return {"ok": True, "message": "动作", "data": {"name": name, "frames": [{}, {}, {}], "duration_sec": 2.0}}

    def play_action(self, name: str, speed: float, loop: bool) -> dict:
        self.play_calls.append({"name": name, "speed": speed, "loop": loop})
        return {"ok": True, "message": "播放完成", "data": {"name": name}}

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
    service._load_agent_config = lambda: {
        "robot_api": {"default_mode": "real"},
        "safety": {
            "allow_real_robot_tools": True,
            "allowed_tools": [
                "get_robot_state", "stop_robot", "stop_face_follow", "set_gripper", "move_joint",
                "rotate_joint", "run_robot_behavior", "play_action", "start_face_follow",
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

        self.assertEqual(bridge.moves, [{"j10": 40.0}])
        self.assertEqual(result["executed_action"]["status"], "executed")

    def test_confirmation_revalidates_relative_target_against_latest_state(self) -> None:
        service, bridge = make_service()
        proposal = service.agent_propose_tool("move_joint", {"joint_name": "J10", "mode": "relative", "value": 10.0})
        bridge.joints["j10"] = 0.5

        service.agent_confirm_pending(proposal["pending_action"]["id"])

        self.assertEqual(bridge.moves, [{"j10": 10.5}])

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

    def test_busy_action_rejects_new_increasing_risk_proposal(self) -> None:
        service, bridge = make_service()
        bridge.action_status = {"state": "playing", "name": "挥手"}

        with self.assertRaisesRegex(WebAPIError, "先停止") as error:
            service.agent_propose_tool("move_joint", {"joint_name": "J12", "mode": "relative", "value": 1.0})

        self.assertEqual(error.exception.code, "AGENT_MOTION_BUSY")

    def test_start_follow_uses_real_mode_after_confirmation(self) -> None:
        service, _bridge = make_service()
        requests = []
        service.start_follow = lambda request: requests.append(request) or {"message": "视觉跟随已启动"}

        proposal = service.agent_propose_tool("start_face_follow", {})
        service.agent_confirm_pending(proposal["pending_action"]["id"])

        self.assertEqual(len(requests), 1)
        self.assertFalse(requests[0].dry_run)

    def test_stop_invalidates_pending_action(self) -> None:
        service, _bridge = make_service()
        service.agent_propose_tool("move_joint", {"joint_name": "J12", "mode": "relative", "value": 1.0})

        service.stop()

        self.assertIsNone(service._agent_pending.current())


if __name__ == "__main__":
    unittest.main()
