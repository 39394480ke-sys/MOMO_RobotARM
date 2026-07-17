"""Agent 默认模板与开发板本机覆盖配置测试。"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from Agent测试路径_test_paths import agent_config_path, ensure_agent_test_paths

ensure_agent_test_paths()

from agent.配置_config import load_config


class AgentLocalConfigTest(unittest.TestCase):
    def test_local_config_deep_merges_before_environment_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "Agent配置.yaml"
            local = root / "Agent配置.local.yaml"
            base.write_text(
                yaml.safe_dump(
                    {
                        "agent": {"backend": "openai_compatible", "max_turns": 20},
                        "safety": {"allow_real_robot_tools": False, "allowed_tools": ["get_robot_state"]},
                    },
                    allow_unicode=True,
                ),
                encoding="utf-8",
            )
            local.write_text(
                yaml.safe_dump({"safety": {"allow_real_robot_tools": True}}, allow_unicode=True),
                encoding="utf-8",
            )

            config = load_config(base)

            self.assertTrue(config["safety"]["allow_real_robot_tools"])
            self.assertEqual(config["safety"]["allowed_tools"], ["get_robot_state"])
            self.assertEqual(config["agent"]["max_turns"], 20)
            self.assertEqual(config["_config_path"], str(base.resolve()))

    def test_invalid_local_config_reports_its_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            base = root / "Agent配置.yaml"
            local = root / "Agent配置.local.yaml"
            base.write_text("agent:\n  backend: openai_compatible\n", encoding="utf-8")
            local.write_text("safety: [\n", encoding="utf-8")

            with self.assertRaisesRegex(Exception, str(local).replace("[", "\\[")):
                load_config(base)

    def test_repository_template_keeps_real_tools_disabled(self) -> None:
        payload = yaml.safe_load(agent_config_path().read_text(encoding="utf-8"))

        self.assertFalse(payload["safety"]["allow_real_robot_tools"])


if __name__ == "__main__":
    unittest.main()
