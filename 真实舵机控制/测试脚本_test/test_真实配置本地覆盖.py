from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

STAGE_DIR = Path(__file__).resolve().parents[1]
PROJECT_ROOT = STAGE_DIR.parent
for path in (PROJECT_ROOT, STAGE_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from 真实机械臂控制器_real_arm_controller import RealArmController, 读取配置
from 标定工具_calibration_utils import load_config as load_calibration_config
from 通用_io import read_structured


class RealConfigLocalOverrideTests(unittest.TestCase):
    def write_base_config(self, root: Path, **transport: object) -> Path:
        config_path = root / "真实配置.yaml"
        payload = {
            "transport": {
                "type": "serial",
                "port": "",
                "driver_backend": "sdk",
                "dry_run": True,
                "write_retries": 3,
                **transport,
            },
            "robot": {"variant": "V2", "joint_order": [], "joints": []},
            "files": {"runtime_state": "runtime/state.json"},
        }
        config_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return config_path

    def test_local_config_is_deep_merged_without_losing_base_siblings(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root)
            (root / "真实配置.local.yaml").write_text(
                json.dumps({"transport": {"port": "/tmp/local-servo", "dry_run": False}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = 读取配置(config_path)

            self.assertEqual(config["transport"]["port"], "/tmp/local-servo")
            self.assertFalse(config["transport"]["dry_run"])
            self.assertEqual(config["transport"]["driver_backend"], "sdk")
            self.assertEqual(config["transport"]["write_retries"], 3)

    def test_missing_local_config_keeps_safe_base_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            config_path = self.write_base_config(Path(tmp))

            with patch.dict(os.environ, {}, clear=True):
                config = 读取配置(config_path)

            self.assertEqual(config["transport"]["port"], "")
            self.assertTrue(config["transport"]["dry_run"])

    def test_locked_runtime_config_skips_stale_sibling_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root, runtime_mode_locked=True)
            (root / "真实配置.local.yaml").write_text(
                json.dumps({"transport": {"dry_run": False}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                config = 读取配置(config_path)

            self.assertTrue(config["transport"]["dry_run"])
            self.assertTrue(config["transport"]["runtime_mode_locked"])

    def test_environment_overrides_local_runtime_values(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root)
            (root / "真实配置.local.yaml").write_text(
                json.dumps(
                    {
                        "transport": {
                            "port": "/tmp/local-servo",
                            "driver_backend": "lerobot",
                            "dry_run": False,
                        }
                    }
                ),
                encoding="utf-8",
            )
            environment = {
                "ARM_ROBOT_PORT": "/tmp/env-servo",
                "ARM_SERVO_BACKEND": "sdk",
                "ARM_REAL_DRY_RUN": "true",
            }

            with patch.dict(os.environ, environment, clear=True):
                config = 读取配置(config_path)

            self.assertEqual(config["transport"]["port"], "/tmp/env-servo")
            self.assertEqual(config["transport"]["driver_backend"], "sdk")
            self.assertTrue(config["transport"]["dry_run"])

    def test_controller_and_calibration_tools_share_effective_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root)
            (root / "真实配置.local.yaml").write_text(
                json.dumps({"transport": {"port": "/tmp/shared-servo", "dry_run": False}}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                controller_config = 读取配置(config_path)
                calibration_config = load_calibration_config(config_path)

            self.assertEqual(calibration_config, controller_config)

    def test_persisted_dry_run_only_updates_local_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root)
            local_path = root / "真实配置.local.yaml"
            local_path.write_text("transport:\n  port: /tmp/local-servo\n", encoding="utf-8")
            original_base = config_path.read_bytes()

            with patch.dict(os.environ, {}, clear=True):
                controller = RealArmController(config_path)
                result = controller.set_dry_run(False, persist=True)

            self.assertTrue(result.成功)
            self.assertEqual(config_path.read_bytes(), original_base)
            local = read_structured(local_path)
            self.assertEqual(local, {"transport": {"port": "/tmp/local-servo", "dry_run": False}})

    def test_locked_runtime_mode_does_not_persist_or_lose_session_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root, runtime_mode_locked=True)
            local_path = root / "真实配置.local.yaml"
            local_path.write_text(
                json.dumps({"transport": {"port": "/tmp/stale-servo", "dry_run": False}}),
                encoding="utf-8",
            )
            original_local = local_path.read_bytes()

            with patch.dict(os.environ, {}, clear=True):
                controller = RealArmController(config_path)
                result = controller.set_dry_run(False, persist=True)
                controller._reload_config_and_calibration()

            self.assertTrue(result.成功)
            self.assertEqual(local_path.read_bytes(), original_local)
            self.assertFalse(controller.is_dry_run())
            self.assertIs(controller._dry_run_override, False)

    def test_example_calibration_is_never_loaded_as_runtime_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = self.write_base_config(root)
            examples = root / "标定"
            examples.mkdir()
            (examples / "v1.example.json").write_text(
                json.dumps({"template": "v1"}),
                encoding="utf-8",
            )
            (examples / "v2.example.json").write_text(
                json.dumps({"template": "v2"}),
                encoding="utf-8",
            )

            with patch.dict(os.environ, {}, clear=True):
                controller = RealArmController(config_path)

            self.assertEqual(
                controller.calibration_manager.path,
                (root / "标定" / "current.local.json").resolve(),
            )
            self.assertEqual(controller.calibration_manager.data, {})


if __name__ == "__main__":
    unittest.main()
