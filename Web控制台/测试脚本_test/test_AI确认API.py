"""AI 确认口令与 REST 路由测试。"""

from __future__ import annotations

import asyncio
import types
import unittest

from Web测试路径_test_paths import ensure_web_test_paths

ensure_web_test_paths()

from backend.agent_pending_action import PendingActionStore
from backend.schemas import AgentAskRequest, AgentPendingActionRequest, AgentToolProposalRequest
from backend.service import WebControlService
import backend.app as app_module


class FakeReply:
    text = "模型回复"
    session_id = "session-1"
    raw_payload = {}


class FakeAgentApp:
    def __init__(self) -> None:
        self.ask_count = 0

    def ask_text(self, content: str, speak: bool = False) -> FakeReply:
        self.ask_count += 1
        return FakeReply()


class AgentAskConfirmationTest(unittest.TestCase):
    def make_service(self) -> tuple[WebControlService, FakeAgentApp]:
        service = WebControlService.__new__(WebControlService)
        service._agent_pending = PendingActionStore()
        service._agent_demo_pending_action = None
        app = FakeAgentApp()
        service._get_agent_app = lambda force_new_session=False: app
        service._handle_agent_demo_message = lambda content: None
        service._handle_poster_demo_message = lambda content: None
        service._remember_error = lambda code, message: None
        return service, app

    def test_exact_confirmation_bypasses_model(self) -> None:
        service, app = self.make_service()
        calls = []
        service.agent_confirm_pending = lambda action_id: calls.append(action_id) or {"message": "已执行"}
        service._agent_pending.create("move_joint", {}, {"title": "移动"}, {"mode": "real", "connected": True, "joints": {}})
        action_id = service._agent_pending.current()["id"]

        result = service.agent_ask(AgentAskRequest(text="确认执行"))

        self.assertEqual(calls, [action_id])
        self.assertEqual(app.ask_count, 0)
        self.assertEqual(result["reply"], "已执行")

    def test_plain_confirmation_still_goes_to_model(self) -> None:
        service, app = self.make_service()

        service.agent_ask(AgentAskRequest(text="确认"))

        self.assertEqual(app.ask_count, 1)

    def test_exact_cancel_phrase_cancels_current_action(self) -> None:
        service, app = self.make_service()
        service._agent_pending.create("move_joint", {}, {"title": "移动"}, {"mode": "real", "connected": True, "joints": {}})

        result = service.agent_ask(AgentAskRequest(text="取消执行"))

        self.assertEqual(app.ask_count, 0)
        self.assertIsNone(service._agent_pending.current())
        self.assertIn("取消", result["reply"])


class FakeRouteService:
    def __init__(self) -> None:
        self.calls = []

    def agent_propose_tool(self, tool_name, arguments):
        self.calls.append(("propose", tool_name, arguments))
        return {"pending_action": {"id": "pending-action-1234567890"}}

    def agent_confirm_pending(self, action_id):
        self.calls.append(("confirm", action_id))
        return {"message": "confirmed"}

    def agent_cancel_pending(self, action_id):
        self.calls.append(("cancel", action_id))
        return {"message": "cancelled"}

    async def broadcast_state(self):
        return None


class AgentRouteTest(unittest.TestCase):
    def setUp(self) -> None:
        self.original_service = app_module.service
        self.fake = FakeRouteService()
        app_module.service = self.fake

    def tearDown(self) -> None:
        app_module.service = self.original_service

    def test_propose_confirm_and_cancel_routes(self) -> None:
        proposed = asyncio.run(app_module.agent_tool_propose(AgentToolProposalRequest(tool_name="move_joint", arguments={"value": 1})))
        confirmed = asyncio.run(app_module.agent_pending_confirm(AgentPendingActionRequest(action_id="pending-action-1234567890")))
        cancelled = asyncio.run(app_module.agent_pending_cancel(AgentPendingActionRequest(action_id="pending-action-1234567890")))

        self.assertTrue(proposed["ok"])
        self.assertTrue(confirmed["ok"])
        self.assertTrue(cancelled["ok"])
        self.assertEqual([call[0] for call in self.fake.calls], ["propose", "confirm", "cancel"])


if __name__ == "__main__":
    unittest.main()
