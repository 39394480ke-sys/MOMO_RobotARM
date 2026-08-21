from __future__ import annotations

import json
import math
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REAL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REAL_ROOT.parent
for path in (PROJECT_ROOT, REAL_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from 安全检查_safety_checker import SafetyChecker
from 真实机械臂控制器_real_arm_controller import RealArmController
from 真实配置加载_real_config_loader import load_real_config
from 角度映射_angle_mapper import (
    MULTI_TURN_ABSOLUTE_RAW_LIMIT,
    effective_joint_limits,
    joint_deg_to_goal_detail,
    multi_turn_absolute_raw_bounds,
    present_raw_to_joint_detail,
    raw_reachable_joint_limits,
    relative_raw_to_joint_deg,
)


JOINTS = [f"j{index}" for index in range(10, 16)]


def write_real_config(root: Path, variant: str) -> Path:
    path = root / f"real_{variant.lower()}.yaml"
    path.write_text(
        json.dumps(
            {
                "transport": {
                    "port": "",
                    "driver_backend": "sdk",
                    "dry_run": True,
                },
                "robot": {
                    "variant": variant,
                    "joint_order": list(JOINTS),
                    "joints": [
                        {
                            "key": joint,
                            "舵机ID": int(joint[1:]),
                            "模式": "多圈",
                            "默认角度": 0,
                            "最小角度": -999,
                            "最大角度": 999,
                        }
                        for joint in JOINTS
                    ],
                },
                "calibration": {"path": "calibration.json"},
                "files": {"runtime_state": "runtime.json"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class SyntheticCalibrationManager:
    def __init__(self, entries: dict[str, dict[str, object]]) -> None:
        self.entries = entries

    def has(self, joint_key: str) -> bool:
        return joint_key in self.entries

    def get(self, joint_key: str) -> dict[str, object]:
        return self.entries[joint_key]


class ProfileReachableSafetyTests(unittest.TestCase):
    def test_profiles_mark_only_selected_canonical_joints_raw_reachable(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant, expected in (("V1", set()), ("V2", {"j12", "j13"})):
                with self.subTest(variant=variant), patch.dict(os.environ, {}, clear=True):
                    config = load_real_config(write_real_config(root, variant))

                by_key = {joint["key"]: joint for joint in config["robot"]["joints"]}
                self.assertEqual(
                    {joint for joint in JOINTS if by_key[joint]["raw_reachable"]},
                    expected,
                )
                self.assertTrue(
                    all(
                        by_key[joint]["raw_reachable"]
                        == (joint in config["robot"]["raw_reachable_joints"])
                        for joint in JOINTS
                    )
                )

    def test_v1_and_v2_reduced_joint_ratios_round_trip_with_signed_scales(self) -> None:
        expected_scales = {
            "V1": {"j12": -5.3, "j13": 5.6},
            "V2": {"j12": -28.0, "j13": 14.0},
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant in ("V1", "V2"):
                with patch.dict(os.environ, {}, clear=True):
                    config = load_real_config(write_real_config(root, variant))
                for joint in ("j12", "j13"):
                    for direction in (-1, 1):
                        with self.subTest(variant=variant, joint=joint, direction=direction):
                            scale = config["robot"]["joint_scales"][joint]
                            self.assertEqual(scale, expected_scales[variant][joint])
                            joint_config = {"joint_scale": scale}
                            entry = {
                                "模式": "多圈",
                                "home_present_raw": 1234,
                                "direction": direction,
                            }
                            detail = joint_deg_to_goal_detail(
                                joint,
                                8.0,
                                joint_config,
                                entry,
                            )
                            round_trip = present_raw_to_joint_detail(
                                joint,
                                detail["goal_raw"],
                                joint_config,
                                entry,
                            )
                            self.assertAlmostEqual(round_trip["joint_deg"], 8.0, delta=0.05)
                            expected_sign = math.copysign(1, scale * direction)
                            self.assertEqual(
                                math.copysign(1, detail["relative_raw"]),
                                expected_sign,
                            )

    def test_raw_reachable_limits_handle_asymmetric_bounds_scale_and_direction(self) -> None:
        expected = (-35.15625, 17.578125)
        self.assertEqual(
            multi_turn_absolute_raw_bounds(),
            (-MULTI_TURN_ABSOLUTE_RAW_LIMIT, MULTI_TURN_ABSOLUTE_RAW_LIMIT),
        )
        self.assertEqual(
            multi_turn_absolute_raw_bounds(
                {"raw_absolute_bounds": [-99999, 99999]}
            ),
            (-MULTI_TURN_ABSOLUTE_RAW_LIMIT, MULTI_TURN_ABSOLUTE_RAW_LIMIT),
        )
        for scale, direction in ((-10.0, 1), (10.0, -1)):
            with self.subTest(scale=scale, direction=direction):
                actual = raw_reachable_joint_limits(
                    scale,
                    direction,
                    reference_raw=1000,
                    raw_bounds=(-1000, 5000),
                )
                self.assertAlmostEqual(actual[0], expected[0], places=8)
                self.assertAlmostEqual(actual[1], expected[1], places=8)

    def test_effective_limits_are_profile_driven_and_intersect_mechanical_range(self) -> None:
        entry = {"模式": "多圈", "home_present_raw": 1000, "direction": 1}
        raw_limited = {
            "最小角度": -100,
            "最大角度": 100,
            "joint_scale": -10.0,
            "raw_reachable": True,
            "raw_absolute_bounds": [-1000, 5000],
        }
        dynamic = effective_joint_limits("j15", raw_limited, entry)
        self.assertAlmostEqual(dynamic[0], -35.15625, places=8)
        self.assertAlmostEqual(dynamic[1], 17.578125, places=8)

        intersected = effective_joint_limits(
            "j15",
            {**raw_limited, "最小角度": -20, "最大角度": 10},
            entry,
        )
        self.assertEqual(intersected, (-20.0, 10.0))

        profile_disabled = effective_joint_limits(
            "j12",
            {**raw_limited, "raw_reachable": False},
            entry,
        )
        self.assertEqual(profile_disabled, (-100.0, 100.0))

    def test_safety_checker_uses_profile_driven_effective_limits(self) -> None:
        entry = {
            "模式": "多圈",
            "home_present_raw": 1000,
            "direction": 1,
        }
        manager = SyntheticCalibrationManager({"j15": entry})
        checker = SafetyChecker({"transport": {"dry_run": True}}, manager)
        joint_config = {
            "最小角度": -100,
            "最大角度": 100,
            "joint_scale": -10.0,
            "raw_reachable": True,
            "raw_absolute_bounds": [-1000, 5000],
        }

        self.assertTrue(checker.check_joint_angle("j15", 17.0, joint_config).成功)
        rejected = checker.check_joint_angle("j15", 18.0, joint_config)
        self.assertFalse(rejected.成功)
        self.assertIn("有效范围", rejected.消息)

    def test_goal_raw_and_controller_validation_enforce_both_absolute_boundaries(self) -> None:
        entry = {
            "模式": "多圈",
            "home_present_raw": 0,
            "direction": 1,
        }
        manager = SyntheticCalibrationManager({"j15": entry})
        checker = SafetyChecker({"transport": {"dry_run": True}}, manager)
        joint_config = {
            "最小角度": -3000,
            "最大角度": 3000,
            "joint_scale": 1.0,
            "raw_reachable": False,
        }

        for boundary in (-MULTI_TURN_ABSOLUTE_RAW_LIMIT, MULTI_TURN_ABSOLUTE_RAW_LIMIT):
            with self.subTest(boundary=boundary):
                self.assertTrue(
                    checker.check_goal_raw(
                        "j15",
                        boundary,
                        entry,
                        joint_config=joint_config,
                    ).成功
                )
                outside = boundary + (-1 if boundary < 0 else 1)
                self.assertFalse(
                    checker.check_goal_raw(
                        "j15",
                        outside,
                        entry,
                        joint_config=joint_config,
                    ).成功
                )

        controller = object.__new__(RealArmController)
        controller.connected = True
        controller.config = {"transport": {"dry_run": True}}
        controller.joint_config_by_key = {"j15": joint_config}
        controller.calibration_manager = manager
        controller.safety_checker = checker
        controller.runtime_state = {}

        for boundary in (-MULTI_TURN_ABSOLUTE_RAW_LIMIT, MULTI_TURN_ABSOLUTE_RAW_LIMIT):
            with self.subTest(controller_boundary=boundary):
                target = relative_raw_to_joint_deg("j15", boundary, 1.0, 1)
                accepted = controller.validate_stream_joint_targets({"j15": target})
                self.assertTrue(accepted.成功, accepted.消息)
                self.assertEqual(accepted.目标raw["j15"], boundary)

                outside_target = relative_raw_to_joint_deg(
                    "j15",
                    boundary + (-1 if boundary < 0 else 1),
                    1.0,
                    1,
                )
                rejected = controller.validate_stream_joint_targets({"j15": outside_target})
                self.assertFalse(rejected.成功)
                self.assertIn("absolute raw", rejected.消息)


if __name__ == "__main__":
    unittest.main()
