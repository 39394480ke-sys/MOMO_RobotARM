"""AI 真实关节运动的单位与安全边界测试。"""

from __future__ import annotations

import math
import unittest

from Agent测试路径_test_paths import ensure_agent_test_paths

ensure_agent_test_paths()

from agent.安全策略_safety_policy import SafetyPolicy
from agent.工具定义_robot_tools import robot_tool_specs


class RealMotionSafetyPolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.policy = SafetyPolicy(
            {
                "safety": {
                    "allow_real_robot_tools": True,
                    "allowed_tools": ["move_joint", "rotate_joint"],
                }
            }
        )

    def checked(self, joint: str, mode: str, value: float, current: float = 0.0) -> dict:
        return self.policy.validate_move_joint(
            {"joint_name": joint, "mode": mode, "value": value},
            {joint.lower(): current},
        )

    def test_move_joint_schema_is_unit_aware(self) -> None:
        specs = {item["function"]["name"]: item["function"] for item in robot_tool_specs()}

        move = specs["move_joint"]
        self.assertEqual(set(move["parameters"]["required"]), {"joint_name", "mode", "value"})
        self.assertEqual(move["parameters"]["properties"]["mode"]["enum"], ["relative", "absolute"])
        self.assertFalse(move["parameters"]["additionalProperties"])

    def test_j10_accepts_long_move_when_final_target_is_inside_range(self) -> None:
        result = self.checked("J10", "relative", 100.0, current=-50.0)

        self.assertEqual(result["unit"], "mm")
        self.assertEqual(result["target"], 50.0)
        self.assertEqual(result["delta"], 100.0)

    def test_j10_rejects_target_outside_range(self) -> None:
        with self.assertRaisesRegex(ValueError, "J10.*安全范围"):
            self.checked("J10", "absolute", 50.01)

    def test_j11_accepts_large_move_and_rejects_outside_range(self) -> None:
        result = self.checked("J11", "relative", 360.0, current=-180.0)
        self.assertEqual(result["target"], 180.0)
        self.assertEqual(result["unit"], "deg")

        with self.assertRaisesRegex(ValueError, "J11.*安全范围"):
            self.checked("J11", "relative", 0.1, current=180.0)

    def test_j12_to_j15_only_allow_relative_three_degree_moves(self) -> None:
        for joint in ("J12", "J13", "J14", "J15"):
            with self.subTest(joint=joint):
                self.assertEqual(self.checked(joint, "relative", 3.0)["delta"], 3.0)
                self.assertEqual(self.checked(joint, "relative", -3.0)["delta"], -3.0)
                with self.assertRaisesRegex(ValueError, "单次运动"):
                    self.checked(joint, "relative", 3.01)
                with self.assertRaisesRegex(ValueError, "不支持 absolute"):
                    self.checked(joint, "absolute", 0.0)

    def test_non_finite_and_raw_values_are_rejected(self) -> None:
        for value in (math.nan, math.inf, -math.inf):
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "有限数字"):
                self.checked("J12", "relative", value)

        for raw_key in ("raw", "raw_value", "position_raw"):
            with self.subTest(raw_key=raw_key), self.assertRaisesRegex(ValueError, "raw"):
                self.policy.validate_move_joint(
                    {"joint_name": "J12", "mode": "relative", "value": 1.0, raw_key: 123},
                    {"j12": 0.0},
                )

    def test_legacy_rotate_joint_normalizes_to_relative_move(self) -> None:
        result = self.policy.validate_move_joint(
            {"joint_name": "J10", "delta_deg": 20.0},
            {"j10": 10.0},
            legacy=True,
        )

        self.assertEqual(result["mode"], "relative")
        self.assertEqual(result["unit"], "mm")
        self.assertEqual(result["target"], 30.0)


if __name__ == "__main__":
    unittest.main()
