from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


REAL_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = REAL_ROOT.parent
for import_path in (PROJECT_ROOT, REAL_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

import 诊断舵机总线_diagnose_bus as diagnostic
from 安全检查_safety_checker import SafetyChecker
from 标定管理_calibration_manager import CalibrationManager
from 真实配置加载_real_config_loader import load_real_config


JOINTS = [f"j{index}" for index in range(10, 16)]


def write_real_config(root: Path, variant: str = "V2") -> Path:
    path = root / "真实配置.yaml"
    path.write_text(
        json.dumps(
            {
                "transport": {
                    "port": "",
                    "driver_backend": "sdk",
                    "baudrate": 1_000_000,
                    "dry_run": True,
                    "gripper_available": False,
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
                        }
                        for joint in JOINTS
                    ],
                },
                "calibration": {"path": "标定/current.local.json"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


def write_calibration(root: Path, variant: str, home_raw: int = 0) -> Path:
    path = root / "标定" / "current.local.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, object] = {
        "_meta": {"robot_variant": variant, "gripper_available": False},
    }
    for index in range(10, 16):
        payload[f"j{index}"] = {
            "id": index,
            "模式": "多圈",
            "home_present_raw": home_raw,
            "phase": 28,
            "direction": -1 if index == 14 else 1,
        }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def diagnostic_args(config_path: Path) -> argparse.Namespace:
    return argparse.Namespace(
        config=str(config_path),
        port=["/dev/fake-servo"],
        all_ports=False,
        include_gripper=False,
        no_gripper=True,
    )


class ReadOnlyBus:
    def __init__(self) -> None:
        self.reads: list[tuple[str, str]] = []
        self.writes: list[tuple[object, ...]] = []
        self.disconnects = 0

    def read(self, register_name: str, joint_name: str, normalize: bool = False) -> int:
        self.reads.append((register_name, joint_name))
        values = {
            "Present_Position": 1234,
            "Present_Voltage": 121,
            "Present_Temperature": 34,
        }
        return values[register_name]

    def write(self, *args: object, **kwargs: object) -> None:
        self.writes.append(args)

    def disable_torque(self) -> None:
        self.writes.append(("disable_torque",))

    def disconnect(self) -> None:
        self.disconnects += 1


class V2SafetyConfigurationTests(unittest.TestCase):
    def test_diagnostic_rejects_variant_mismatch_before_bus_io(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            config_path = write_real_config(root, "V2")
            write_calibration(root, "V1")
            with (
                patch.object(diagnostic, "parse_args", return_value=diagnostic_args(config_path)),
                patch.object(diagnostic, "try_port") as try_port,
                self.assertRaisesRegex(ValueError, "不匹配"),
            ):
                diagnostic.main()

        try_port.assert_not_called()

    def test_diagnostic_health_reads_position_voltage_temperature_with_zero_writes(self) -> None:
        bus = ReadOnlyBus()
        with patch.object(diagnostic, "connect_feetech_bus", return_value=bus):
            success = diagnostic.try_port("/dev/fake-servo", include_gripper=False)

        self.assertTrue(success)
        self.assertEqual(len(bus.reads), len(JOINTS) * 3)
        self.assertEqual(
            bus.reads[:3],
            [
                ("Present_Position", "j10"),
                ("Present_Voltage", "j10"),
                ("Present_Temperature", "j10"),
            ],
        )
        self.assertEqual(bus.writes, [])
        self.assertEqual(bus.disconnects, 1)

    def test_profile_driven_dynamic_limit_uses_temp_v2_home(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            config_path = write_real_config(root, "V2")
            calibration_path = write_calibration(root, "V2", home_raw=20_000)
            config = load_real_config(config_path)
            manager = CalibrationManager(calibration_path, config)
            checker = SafetyChecker(config, manager)

        j12 = next(item for item in config["robot"]["joints"] if item["key"] == "j12")
        j12 = {**j12, "joint_scale": config["robot"]["joint_scales"]["j12"]}
        self.assertTrue(checker.check_joint_angle("j12", 10.0, j12).成功)
        rejected = checker.check_joint_angle("j12", -45.0, j12)
        self.assertFalse(rejected.成功)
        self.assertIn("有效范围", rejected.消息)


if __name__ == "__main__":
    unittest.main()
