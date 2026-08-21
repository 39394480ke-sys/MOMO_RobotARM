from __future__ import annotations

import argparse
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DIR = Path(__file__).resolve().parent
REAL_ROOT = TEST_DIR.parent
PROJECT_ROOT = REAL_ROOT.parent
for import_path in (PROJECT_ROOT, REAL_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import 标定应用_apply_calibration as apply_calibration
import 标定当前角度_calibrate_current_angle as current_angle
import 标定程序_calibrate as calibration_program
import 诊断舵机总线_lightweight_sdk as lightweight_diagnostic
from 标定管理_calibration_manager import CALIBRATION_FORMAT_VERSION, CalibrationManager
from 通用_io import read_structured


def config_for(variant: str = "V2") -> dict[str, object]:
    return {
        "transport": {
            "port": "/dev/fake-servo",
            "baudrate": 1_000_000,
            "dry_run": True,
            "gripper_available": False,
        },
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


def calibration_payload(meta: dict[str, object] | None) -> dict[str, object]:
    payload: dict[str, object] = {}
    if meta is not None:
        payload["_meta"] = {"gripper_available": False, **meta}
    for index in range(10, 16):
        payload[f"j{index}"] = {
            "id": index,
            "模式": "多圈",
            "home_present_raw": 0,
            "phase": 28,
            "direction": -1 if index == 14 else 1,
        }
    return payload


def write_calibration(root: Path, meta: dict[str, object] | None) -> Path:
    path = root / "calibration.json"
    path.write_text(
        json.dumps(calibration_payload(meta), ensure_ascii=False),
        encoding="utf-8",
    )
    return path


class FakeWriteBus:
    def __init__(self) -> None:
        self.writes: list[tuple[str, str, int]] = []
        self.disconnects = 0

    def write(self, register: str, joint: str, value: int, normalize: bool = False) -> None:
        self.writes.append((register, joint, value))

    def disable_torque(self) -> None:
        pass

    def disconnect(self) -> None:
        self.disconnects += 1


class CalibrationHardwareEntryGuardTests(unittest.TestCase):
    def test_apply_rejects_invalid_variant_before_connect_or_register_write(self) -> None:
        cases = (
            ("mismatch", {"robot_variant": "V1"}, "不匹配"),
            ("missing", {}, "缺少 robot_variant"),
            ("unknown", {"robot_variant": "V3"}, "未知"),
            ("template", {"robot_variant": "V2", "template": True}, "模板"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, meta, message in cases:
                with self.subTest(case=name):
                    path = write_calibration(root, meta)
                    connect_count = 0

                    def forbidden_connect(*args: object, **kwargs: object) -> FakeWriteBus:
                        nonlocal connect_count
                        connect_count += 1
                        return FakeWriteBus()

                    args = argparse.Namespace(
                        config=str(root / "real.json"),
                        port="/dev/fake-servo",
                        calibration=str(path),
                        yes=True,
                    )
                    with (
                        patch.object(apply_calibration, "parse_args", return_value=args),
                        patch.object(apply_calibration, "load_config", return_value=config_for()),
                        patch.object(apply_calibration, "connect_feetech_bus", side_effect=forbidden_connect),
                        self.assertRaisesRegex(ValueError, message),
                    ):
                        apply_calibration.main()
                    self.assertEqual(connect_count, 0)

    def test_apply_exact_variant_enters_fake_bus_and_writes_only_fake_registers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_calibration(root, {"robot_variant": "V2"})
            bus = FakeWriteBus()
            args = argparse.Namespace(
                config=str(root / "real.json"),
                port="/dev/fake-servo",
                calibration=str(path),
                yes=True,
            )
            with (
                patch.object(apply_calibration, "parse_args", return_value=args),
                patch.object(apply_calibration, "load_config", return_value=config_for()),
                patch.object(apply_calibration, "connect_feetech_bus", return_value=bus) as connect,
            ):
                apply_calibration.main()

            connect.assert_called_once()
            self.assertEqual(len(bus.writes), 30)
            self.assertEqual(bus.disconnects, 1)

    def test_apply_rejects_incomplete_exact_calibration_before_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_calibration(root, {"robot_variant": "V2"})
            payload = read_structured(path)
            payload["j15"].pop("phase")
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            args = argparse.Namespace(
                config=str(root / "real.json"),
                port="/dev/fake-servo",
                calibration=str(path),
                yes=True,
            )
            with (
                patch.object(apply_calibration, "parse_args", return_value=args),
                patch.object(apply_calibration, "load_config", return_value=config_for()),
                patch.object(apply_calibration, "connect_feetech_bus") as connect,
                self.assertRaisesRegex(ValueError, "j15|J15"),
            ):
                apply_calibration.main()
            connect.assert_not_called()

    def test_current_angle_rejects_invalid_variant_before_read_or_file_write(self) -> None:
        cases = (
            ("mismatch", {"robot_variant": "V1"}, "不匹配"),
            ("missing", {}, "缺少 robot_variant"),
            ("template", {"robot_variant": "V2", "template": True}, "模板"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, meta, message in cases:
                with self.subTest(case=name):
                    path = write_calibration(root, meta)
                    original = path.read_bytes()
                    config = config_for()
                    config["calibration"] = {"path": str(path)}
                    args = self.current_angle_args(root)
                    read_count = 0

                    def forbidden_read(*args: object, **kwargs: object) -> dict[str, int]:
                        nonlocal read_count
                        read_count += 1
                        return {"j12": 4096}

                    with (
                        patch.object(current_angle, "parse_args", return_value=args),
                        patch.object(current_angle, "load_config", return_value=config),
                        patch.object(current_angle, "read_present_raws", side_effect=forbidden_read),
                        self.assertRaisesRegex(ValueError, message),
                    ):
                        current_angle.main()

                    self.assertEqual(read_count, 0)
                    self.assertEqual(path.read_bytes(), original)
                    self.assertFalse((root / "标定备份_backups").exists())

    def test_current_angle_exact_variant_uses_fake_read_and_unified_save_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_calibration(root, {"robot_variant": "V2"})
            config = config_for()
            config["calibration"] = {"path": str(path)}
            args = self.current_angle_args(root)
            with (
                patch.object(current_angle, "parse_args", return_value=args),
                patch.object(current_angle, "load_config", return_value=config),
                patch.object(current_angle, "read_present_raws", return_value={"j12": 4096}) as read,
            ):
                current_angle.main()

            read.assert_called_once()
            saved = read_structured(path)
            self.assertEqual(saved["_meta"]["robot_variant"], "V2")
            self.assertEqual(saved["_meta"]["format_version"], CALIBRATION_FORMAT_VERSION)
            self.assertEqual(saved["_meta"]["updated_by"], Path(current_angle.__file__).name)
            self.assertNotEqual(saved["j12"]["home_present_raw"], 0)

    def test_current_angle_rejects_invalid_selected_joint_before_hardware_read(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_calibration(root, {"robot_variant": "V2"})
            payload = read_structured(path)
            payload["j12"]["phase"] = None
            path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            config = config_for()
            config["calibration"] = {"path": str(path)}
            with (
                patch.object(current_angle, "parse_args", return_value=self.current_angle_args(root)),
                patch.object(current_angle, "load_config", return_value=config),
                patch.object(current_angle, "read_present_raws") as read,
                self.assertRaisesRegex(ValueError, "phase"),
            ):
                current_angle.main()
            read.assert_not_called()

    def test_calibration_program_rejects_mismatched_reuse_before_connect(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = write_calibration(root, {"robot_variant": "V1"})
            args = argparse.Namespace(
                config=str(root / "real.json"),
                port="/dev/fake-servo",
                output=str(output),
                dry_run=False,
                apply_registers=False,
                recalibrate_single=False,
                yes=True,
            )
            with (
                patch.object(calibration_program, "parse_args", return_value=args),
                patch.object(calibration_program, "load_config", return_value=config_for()),
                patch.object(calibration_program, "connect_optional_gripper_bus") as connect,
                self.assertRaisesRegex(ValueError, "不匹配"),
            ):
                calibration_program.main()
            connect.assert_not_called()

    def test_lightweight_diagnostic_rejects_mismatched_calibration_before_bus_io(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = write_calibration(root, {"robot_variant": "V1"})
            config = config_for()
            config["calibration"] = {"path": str(path)}
            args = argparse.Namespace(
                config=str(root / "real.json"),
                port=["/dev/fake-servo"],
                all_ports=False,
                baudrate=None,
                include_gripper=False,
                no_gripper=True,
            )
            with (
                patch.object(lightweight_diagnostic, "parse_args", return_value=args),
                patch.object(lightweight_diagnostic, "load_config", return_value=config),
                patch.object(lightweight_diagnostic, "try_port") as try_port,
                self.assertRaisesRegex(ValueError, "不匹配"),
            ):
                lightweight_diagnostic.main()
            try_port.assert_not_called()

    def test_example_reports_invalid_placeholders_without_raising(self) -> None:
        for variant in ("V1", "V2"):
            with self.subTest(variant=variant):
                manager = CalibrationManager(
                    REAL_ROOT / "标定" / f"{variant.lower()}.example.json",
                    config_for(variant),
                )
                report = manager.calibration_report()
                self.assertFalse(report["允许真机移动"])
                issues = [
                    issue
                    for joint_report in report["项目"].values()
                    for issue in joint_report["问题"]
                ]
                self.assertTrue(any("phase" in issue and "整数" in issue for issue in issues))
                self.assertTrue(any("id" in issue and "整数" in issue for issue in issues))
                self.assertTrue(any("direction" in issue for issue in issues))
                self.assertTrue(any("home_present_raw" in issue and "整数" in issue for issue in issues))

    @staticmethod
    def current_angle_args(root: Path) -> argparse.Namespace:
        return argparse.Namespace(
            config=str(root / "real.json"),
            port="/dev/fake-servo",
            baudrate=None,
            joint=None,
            angle=None,
            joint_angle=["j12=10"],
            dry_run=False,
            yes=True,
        )


if __name__ == "__main__":
    unittest.main()
