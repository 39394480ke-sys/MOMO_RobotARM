from __future__ import annotations

import types
import unittest

from Agent测试路径_test_paths import ensure_agent_test_paths

ensure_agent_test_paths()

from agent.OpenAI兼容客户端_openai_client import OpenAICompatibleAgentClient


class SemanticIntentTest(unittest.TestCase):
    def make_client(self, content: str) -> tuple[OpenAICompatibleAgentClient, list[dict]]:
        client = OpenAICompatibleAgentClient.__new__(OpenAICompatibleAgentClient)
        client.backend_cfg = {"model": "test-model"}
        client.agent_cfg = {"timeout_sec": 5}
        captured: list[dict] = []
        client._post_chat = types.MethodType(
            lambda self, payload: captured.append(payload) or {
                "choices": [{"message": {"content": content}}]
            },
            client,
        )
        return client, captured

    def test_model_converts_natural_language_to_structured_joint_command(self) -> None:
        client, captured = self.make_client(
            '{"kind":"command","tool_name":"move_joint","arguments":'
            '{"joint_name":"j12","mode":"relative","value":1.0},'
            '"missing":[],"reply":"","confidence":0.99}'
        )

        intent = client.interpret_robot_intent("j12 正转 1 度")

        self.assertEqual(intent["tool_name"], "move_joint")
        self.assertEqual(intent["arguments"]["value"], 1.0)
        self.assertEqual(captured[0]["response_format"], {"type": "json_object"})
        self.assertNotIn("tools", captured[0])

    def test_model_can_request_clarification_without_a_tool(self) -> None:
        client, _captured = self.make_client(
            '{"kind":"clarify","tool_name":"move_joint","arguments":'
            '{"joint_name":"j12","mode":"relative"},'
            '"missing":["value"],"reply":"请说明要旋转多少度。","confidence":0.96}'
        )

        intent = client.interpret_robot_intent("j12 正转度")

        self.assertEqual(intent["kind"], "clarify")
        self.assertEqual(intent["missing"], ["value"])
        self.assertIn("多少度", intent["reply"])


if __name__ == "__main__":
    unittest.main()
