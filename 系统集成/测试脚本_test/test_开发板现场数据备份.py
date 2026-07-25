from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backup_board_local_data import create_snapshot, prune_snapshots, verify_snapshot


class BoardBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name) / "project"
        self.backups = Path(self.tmp.name) / "backups"
        (self.root / "真实舵机控制").mkdir(parents=True)
        (self.root / "真实舵机控制" / "标定文件.json").write_text(
            json.dumps({f"j{i}": {"home_present_raw": i} for i in range(10, 16)}), encoding="utf-8"
        )
        (self.root / "语音Agent").mkdir()
        (self.root / "语音Agent" / "Agent配置.local.yaml").write_text("safety:\n  allow_real_robot_tools: true\n", encoding="utf-8")
        (self.root / "视觉识别与跟随" / "runtime").mkdir(parents=True)
        (self.root / "视觉识别与跟随" / "runtime" / "latest.jpg").write_bytes(b"skip")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_snapshot_is_verified_and_only_contains_selected_data(self) -> None:
        snapshot = create_snapshot(self.root, self.backups, datetime(2026, 7, 17, tzinfo=timezone.utc))
        verify_snapshot(snapshot)
        self.assertTrue((snapshot / "真实舵机控制" / "标定文件.json").is_file())
        self.assertTrue((snapshot / "语音Agent" / "Agent配置.local.yaml").is_file())
        self.assertFalse((snapshot / "视觉识别与跟随" / "runtime" / "latest.jpg").exists())
        manifest = json.loads((snapshot / "manifest.json").read_text(encoding="utf-8"))
        self.assertEqual([item["path"] for item in manifest["files"]], sorted(item["path"] for item in manifest["files"]))

        (snapshot / "语音Agent" / "Agent配置.local.yaml").write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "mismatch"):
            verify_snapshot(snapshot)

    def test_calibration_must_cover_all_motion_joints(self) -> None:
        path = self.root / "真实舵机控制" / "标定文件.json"
        path.write_text(json.dumps({"j10": {}}), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "j11"):
            create_snapshot(self.root, self.backups, datetime.now(timezone.utc))

    def test_snapshot_supports_new_and_legacy_calibration_paths(self) -> None:
        new_path = self.root / "真实舵机控制" / "标定" / "current.local.json"
        new_path.parent.mkdir()
        new_path.write_text(
            json.dumps({f"j{i}": {} for i in range(10, 16)}),
            encoding="utf-8",
        )

        snapshot = create_snapshot(self.root, self.backups, datetime.now(timezone.utc))

        self.assertTrue((snapshot / "真实舵机控制" / "标定" / "current.local.json").is_file())
        self.assertTrue((snapshot / "真实舵机控制" / "标定文件.json").is_file())

    def test_new_calibration_path_has_validation_priority(self) -> None:
        new_path = self.root / "真实舵机控制" / "标定" / "current.local.json"
        new_path.parent.mkdir()
        new_path.write_text(json.dumps({"j10": {}}), encoding="utf-8")

        with self.assertRaisesRegex(ValueError, "j11"):
            create_snapshot(self.root, self.backups, datetime.now(timezone.utc))

    def test_prune_ignores_partial_and_keeps_newest_successful_snapshot(self) -> None:
        now = datetime(2026, 7, 17, tzinfo=timezone.utc)
        old = create_snapshot(self.root, self.backups, now - timedelta(days=40))
        newest = create_snapshot(self.root, self.backups, now - timedelta(days=39))
        partial = self.backups / "snapshots" / ".partial-leftover"
        partial.mkdir(parents=True)

        removed = prune_snapshots(self.backups / "snapshots", 30, now)

        self.assertIn(old, removed)
        self.assertFalse(old.exists())
        self.assertTrue(newest.exists())
        self.assertTrue(partial.exists())


if __name__ == "__main__":
    unittest.main()
