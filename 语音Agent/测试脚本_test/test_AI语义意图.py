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

    def test_model_preserves_every_action_in_a_combined_command(self) -> None:
        client, _captured = self.make_client(
            '{"kind":"command","execution_mode":"simultaneous","actions":['
            '{"tool_name":"move_joint","arguments":{"joint_name":"j10","mode":"absolute","value":30},'
            '"evidence":{"joint":"j10","direction_or_target":"运动到","value":"30","unit":"mm"}},'
            '{"tool_name":"move_joint","arguments":{"joint_name":"j11","mode":"relative","value":30},'
            '"evidence":{"joint":"j11","direction_or_target":"正转","value":"30","unit":"度"}}],'
            '"missing":[],"reply":"","confidence":0.99}'
        )

        intent = client.interpret_robot_intent("同时让 j10 运动到 30mm，j11 正转 30 度")

        self.assertEqual(intent["execution_mode"], "simultaneous")
        self.assertEqual([item["arguments"]["joint_name"] for item in intent["actions"]], ["j10", "j11"])
        self.assertEqual(intent["actions"][1]["evidence"]["direction_or_target"], "正转")

    def test_semantic_prompt_grants_read_only_library_tools_and_card_based_execution_tools(self) -> None:
        client, captured = self.make_client(
            '{"kind":"command","tool_name":"list_actions","arguments":{},'
            '"missing":[],"reply":"","confidence":0.99}'
        )

        intent = client.interpret_robot_intent("动作库里面有什么动作")

        prompt = captured[0]["messages"][0]["content"]
        self.assertEqual(intent["tool_name"], "list_actions")
        self.assertIn("list_actions", prompt)
        self.assertIn("list_poses", prompt)
        self.assertIn("list_subject_lock_profiles", prompt)
        self.assertIn("goto_pose", prompt)
        self.assertIn("run_subject_lock_profile", prompt)

    def test_empty_model_json_gets_a_focused_ai_semantic_retry(self) -> None:
        client = OpenAICompatibleAgentClient.__new__(OpenAICompatibleAgentClient)
        client.backend_cfg = {"model": "test-model"}
        client.agent_cfg = {"timeout_sec": 5}
        responses = iter(
            [
                {"choices": [{"message": {"content": "{}"}}]},
                {
                    "choices": [
                        {
                            "message": {
                                "content": (
                                    '{"kind":"command","tool_name":"list_actions","arguments":{},'
                                    '"missing":[],"reply":"","confidence":1.0}'
                                )
                            }
                        }
                    ]
                },
            ]
        )
        captured = []
        client._post_chat = types.MethodType(
            lambda self, payload: captured.append(payload) or next(responses),
            client,
        )

        intent = client.interpret_robot_intent("动作库里面有什么动作")

        self.assertEqual(intent["tool_name"], "list_actions")
        self.assertEqual(len(captured), 2)
        self.assertIn("只针对这句话", captured[1]["messages"][0]["content"])


if __name__ == "__main__":
    unittest.main()
