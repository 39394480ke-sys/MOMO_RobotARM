from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

TEST_DIR = Path(__file__).resolve().parent
REAL_ROOT = TEST_DIR.parent
PROJECT_ROOT = REAL_ROOT.parent
for import_path in (PROJECT_ROOT, REAL_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from V2真机验收_v2_acceptance import build_preflight_report
from 安全检查_safety_checker import SafetyChecker
from 标定管理_calibration_manager import CALIBRATION_FORMAT_VERSION, CalibrationManager
from 标定程序_calibrate import build_dry_run_preview, build_meta
from 真实机械臂控制器_real_arm_controller import RealArmController
from 系统集成.integration.calibration_checker import CalibrationChecker
from 通用_io import read_structured


def config_for(variant: str, *, dry_run: bool) -> dict[str, object]:
    return {
        "transport": {"dry_run": dry_run, "port": "", "gripper_available": False},
        "robot": {
            "variant": variant,
            "joint_order": [f"j{index}" for index in range(10, 16)],
            "joint_scales": {
                "j10": 28.8,
                "j11": 5.0,
                "j12": -28.0 if variant == "V2" else -1.0,
                "j13": 14.0 if variant == "V2" else 1.0,
                "j14": 1.0,
                "j15": 1.0,
            },
            "joints": [
                {
                    "key": f"j{index}",
                    "舵机ID": index,
                    "模式": "多圈",
                    "默认角度": 0,
                    "最小角度": -180,
                    "最大角度": 180,
                }
                for index in range(10, 16)
            ],
        },
    }


def complete_calibration(meta: dict[str, object] | None) -> dict[str, object]:
    payload: dict[str, object] = {}
    if meta is not None:
        payload["_meta"] = {"gripper_available": False, **meta}
    for index in range(10, 16):
        payload[f"j{index}"] = {
            "id": index,
            "模式": "多圈",
            "home_present_raw": 1048 if index == 10 else 0,
            "phase": 28,
            "direction": -1 if index == 14 else 1,
        }
    return payload


class CalibrationVariantValidationTests(unittest.TestCase):
    def write_calibration(self, root: Path, meta: dict[str, object] | None) -> Path:
        path = root / "calibration.json"
        path.write_text(
            json.dumps(complete_calibration(meta), ensure_ascii=False),
            encoding="utf-8",
        )
        return path

    def test_real_load_requires_known_exact_non_template_variant(self) -> None:
        cases = (
            ("exact", {"robot_variant": "V2"}, None),
            ("mismatch", {"robot_variant": "V1"}, "不匹配"),
            ("missing", {}, "缺少 robot_variant"),
            ("unknown", {"robot_variant": "V3"}, "未知"),
            ("template", {"robot_variant": "V2", "template": True}, "模板"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, meta, error in cases:
                with self.subTest(case=name):
                    path = self.write_calibration(root, meta)
                    if error is None:
                        manager = CalibrationManager(path, config_for("V2", dry_run=False))
                        self.assertTrue(manager.variant_report()["匹配"])
                    else:
                        with self.assertRaisesRegex(ValueError, error):
                            CalibrationManager(path, config_for("V2", dry_run=False))

    def test_dry_run_loads_legacy_and_other_variants_only_as_preview(self) -> None:
        cases = (
            ("exact", {"robot_variant": "V2"}, True),
            ("mismatch", {"robot_variant": "V1"}, False),
            ("missing", {}, False),
            ("unknown", {"robot_variant": "V3"}, False),
            ("legacy", None, False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, meta, exact in cases:
                with self.subTest(case=name):
                    manager = CalibrationManager(
                        self.write_calibration(root, meta),
                        config_for("V2", dry_run=True),
                    )
                    report = manager.variant_report()
                    self.assertEqual(report["匹配"], exact)
                    self.assertTrue(report["允许预览"])
                    self.assertFalse(report["当前模式允许真实执行"])
                    self.assertTrue(
                        SafetyChecker(manager.config, manager)
                        .check_calibration_for_move(["j12"])
                        .成功
                    )

    def test_unknown_active_variant_cannot_be_saved_or_used_for_real(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_calibration(Path(tmp), {"robot_variant": "V2"})
            with self.assertRaisesRegex(ValueError, "robot.variant.*V1.*V2"):
                CalibrationManager(path, config_for("V3", dry_run=False))

            manager = CalibrationManager(path, config_for("V3", dry_run=True))
            with self.assertRaisesRegex(ValueError, "robot.variant.*V1.*V2"):
                manager.save()

    def test_save_rejects_mismatch_and_generated_metadata_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = self.write_calibration(root, {"robot_variant": "V1"})
            manager = CalibrationManager(path, config_for("V2", dry_run=True))
            with self.assertRaisesRegex(ValueError, "不匹配"):
                manager.save()

            exact_path = self.write_calibration(root, {"robot_variant": "V2"})
            exact_manager = CalibrationManager(exact_path, config_for("V2", dry_run=True))
            exact_manager.save()
            saved_meta = read_structured(exact_path)["_meta"]
            self.assertEqual(saved_meta["format_version"], CALIBRATION_FORMAT_VERSION)
            self.assertIsInstance(saved_meta["generated_at_unix_s"], float)
            self.assertRegex(str(saved_meta["generated_at_utc"]), r"Z$")

            meta = build_meta(config_for("V2", dry_run=True), include_gripper=False)
            self.assertEqual(meta["robot_variant"], "V2")
            self.assertEqual(meta["format_version"], CALIBRATION_FORMAT_VERSION)
            self.assertIsInstance(meta["generated_at_unix_s"], float)
            self.assertRegex(str(meta["generated_at_utc"]), r"Z$")
            self.assertIn("J13 为 1:14", meta["notes"]["absolute_raw"])

            preview = build_dry_run_preview(
                complete_calibration({"robot_variant": "V1"}),
                config_for("V2", dry_run=True),
                include_gripper=False,
            )
            self.assertEqual(preview["_meta"]["robot_variant"], "V1")
            self.assertEqual(preview["_meta"]["preview_for_robot_variant"], "V2")
            self.assertEqual(preview["_meta"]["source_robot_variant"], "V1")
            self.assertEqual(preview["_meta"]["purpose"], "dry_run_preview")
            self.assertTrue(preview["_meta"]["template"])

    def test_examples_are_explicit_templates_and_never_real_calibration(self) -> None:
        for variant in ("V1", "V2"):
            with self.subTest(variant=variant):
                path = REAL_ROOT / "标定" / f"{variant.lower()}.example.json"
                payload = read_structured(path)
                meta = payload["_meta"]
                self.assertEqual(meta["robot_variant"], variant)
                self.assertEqual(meta["format_version"], CALIBRATION_FORMAT_VERSION)
                self.assertTrue(meta["template"])
                with self.assertRaisesRegex(ValueError, "模板"):
                    CalibrationManager(path, config_for(variant, dry_run=False))

    def test_tracked_default_stays_safe_and_live_calibration_is_ignored(self) -> None:
        config = read_structured(REAL_ROOT / "真实配置.yaml")
        self.assertTrue(config["transport"]["dry_run"])
        self.assertEqual(config["transport"]["port"], "")
        self.assertEqual(config["calibration"]["path"], "标定/current.local.json")
        self.assertNotIn(".example.", config["calibration"]["path"])
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("*.local.json", gitignore)

    def test_integration_checker_uses_the_same_active_variant(self) -> None:
        cases = (
            ({"robot_variant": "V2"}, True),
            ({"robot_variant": "V1"}, False),
            ({}, False),
            ({"robot_variant": "V3"}, False),
            ({"robot_variant": "V2", "template": True}, False),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for meta, expected in cases:
                with self.subTest(meta=meta):
                    path = self.write_calibration(root, meta)
                    report = CalibrationChecker(
                        {
                            "_base_dir": str(root),
                            "robot": {"variant": "V2"},
                            "hardware": {
                                "robot_variant": "V2",
                                "calibration_path": str(path),
                            },
                        }
                    ).check()
                    self.assertEqual(report["real_mode_allowed"], expected, report["errors"])
                    self.assertEqual(report["robot_variant"], "V2")

    def test_controller_reloads_and_rejects_mismatched_variant_before_connecting(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            calibration_path = self.write_calibration(root, {"robot_variant": "V1"})
            config = config_for("V2", dry_run=True)
            config["calibration"] = {"path": str(calibration_path)}
            config["files"] = {"runtime_state": str(root / "runtime.json")}
            config_path = root / "real.json"
            config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")

            controller = RealArmController(config_path)
            controller.set_dry_run(False, persist=False)
            result = controller.connect()

            self.assertFalse(result.成功)
            self.assertIn("V1", result.消息)
            self.assertIn("V2", result.消息)
            self.assertFalse(controller.connected)

    def test_v2_acceptance_output_is_a_read_only_validated_plan(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = self.write_calibration(
                Path(tmp),
                {
                    "robot_variant": "V2",
                    "format_version": CALIBRATION_FORMAT_VERSION,
                    "generated_at_unix_s": 1.0,
                },
            )
            report = build_preflight_report(config_for("V2", dry_run=True), path)
            self.assertEqual(report["mode"], "read_only_plan")
            self.assertTrue(report["plan_valid"])
            self.assertTrue(report["staged_plan_ready"])
            self.assertFalse(report["hardware_writes"])
            self.assertFalse(report["approved_for_hardware_execution"])
            self.assertTrue(report["requires_explicit_real_approval"])
            self.assertEqual(report["robot_variant"], "V2")

            unsafe_config = config_for("V2", dry_run=True)
            unsafe_config["robot"]["joints"][-1]["默认角度"] = 180
            unsafe_report = build_preflight_report(unsafe_config, path)
            self.assertFalse(unsafe_report["plan_valid"])
            self.assertFalse(unsafe_report["staged_plan_ready"])
            self.assertIn("j15", unsafe_report["plan_errors"][0])

            with self.assertRaisesRegex(ValueError, "只支持 V2"):
                build_preflight_report(config_for("V1", dry_run=True), path)


if __name__ == "__main__":
    unittest.main()
