"""Agent 遇到真实动作提议时立即返回待确认卡。"""

from __future__ import annotations

import types
import unittest

from Agent测试路径_test_paths import ensure_agent_test_paths

ensure_agent_test_paths()

from agent.OpenAI兼容客户端_openai_client import OpenAICompatibleAgentClient
from agent.工具桥接_tool_bridge import RobotToolBridge


class PendingBridge:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute(self, name: str, arguments: dict) -> dict:
        self.calls.append((name, arguments))
        return {
            "ok": True,
            "result": {
                "pending_action": {
                    "id": "pending-action-1234567890",
                    "summary": {
                        "title": "移动 J12",
                        "confirmation_text": "J12 将移动 1°。请确认机械臂周围安全后执行。",
                    },
                }
            },
        }


class PendingToolResultTest(unittest.TestCase):
    def test_client_stops_after_first_pending_action(self) -> None:
        client = OpenAICompatibleAgentClient.__new__(OpenAICompatibleAgentClient)
        client.config = {"nanobot": {"max_tool_iterations": 12}}
        client.agent_cfg = {}
        client.backend_cfg = {"model": "test", "temperature": 0.0, "max_tokens": 100}
        client.system_prompt = "test"
        client.session = {"session_id": "session-1", "messages": []}
        client.tool_bridge = PendingBridge()
        client._post_chat = types.MethodType(
            lambda self, payload: {
                "choices": [
                    {
                        "message": {
                            "content": "",
                            "tool_calls": [
                                {"id": "one", "type": "function", "function": {"name": "move_joint", "arguments": '{"joint_name":"J12","mode":"relative","value":1}'}},
                                {"id": "two", "type": "function", "function": {"name": "move_joint", "arguments": '{"joint_name":"J13","mode":"relative","value":1}'}},
                            ],
                        }
                    }
                ]
            },
            client,
        )

        reply = client._run_chat_with_tools()

        self.assertEqual(len(client.tool_bridge.calls), 1)
        self.assertEqual(reply.raw_payload["pending_action"]["summary"]["title"], "移动 J12")
        self.assertIn("请确认", reply.text)

    def test_standalone_motion_bridge_posts_proposal_without_confirmation_text(self) -> None:
        bridge = RobotToolBridge.__new__(RobotToolBridge)
        calls: list[tuple[str, dict]] = []
        bridge._post = lambda path, payload: calls.append((path, payload)) or {"pending_action": {"id": "x"}}

        result = bridge._dispatch("move_joint", {"joint_name": "j12", "mode": "relative", "value": 1.0})

        self.assertEqual(result["pending_action"]["id"], "x")
        self.assertEqual(calls[0][0], "/api/v1/agent/tool/propose")
        self.assertEqual(calls[0][1]["tool_name"], "move_joint")
        self.assertNotIn("confirm_text", str(calls[0][1]))

    def test_stop_follow_remains_immediate(self) -> None:
        bridge = RobotToolBridge.__new__(RobotToolBridge)
        calls: list[tuple[str, dict]] = []
        bridge._post = lambda path, payload: calls.append((path, payload)) or {"message": "stopped"}

        bridge._dispatch("stop_face_follow", {})

        self.assertEqual(calls, [("/api/v1/follow/stop", None)])


if __name__ == "__main__":
    unittest.main()
