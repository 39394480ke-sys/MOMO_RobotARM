from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.backup_board_local_data import create_snapshot
from scripts.pull_board_backups_to_mac import pull_snapshots


class MacPullBackupTest(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.project = Path(self.tmp.name) / "project"
        calibration = self.project / "真实舵机控制" / "标定" / "current.local.json"
        calibration.parent.mkdir(parents=True)
        calibration.write_text(json.dumps({f"j{i}": {} for i in range(10, 16)}), encoding="utf-8")
        self.local = Path(self.tmp.name) / "local"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_uses_batch_ssh_and_non_destructive_partial_rsync(self) -> None:
        create_snapshot(self.project, self.local, datetime.now(timezone.utc))
        with patch("scripts.pull_board_backups_to_mac.subprocess.run") as run:
            pull_snapshots("fibo@board.local", "/remote/backups", self.local)

        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn("BatchMode=yes", commands[0])
        self.assertIn("backup_board_local_data.py", commands[0][-1])
        self.assertEqual(commands[1][-2:], ["fibo@board.local", "test -d /remote/backups/snapshots"])
        self.assertIn("--partial", commands[2])
        self.assertNotIn("--delete", commands[2])

    def test_checksum_failure_is_reported(self) -> None:
        snapshot = create_snapshot(self.project, self.local, datetime.now(timezone.utc))
        calibration = snapshot / "真实舵机控制" / "标定" / "current.local.json"
        calibration.write_text("changed", encoding="utf-8")
        with patch("scripts.pull_board_backups_to_mac.subprocess.run"):
            with self.assertRaisesRegex(ValueError, "mismatch"):
                pull_snapshots("fibo@board.local", "/remote/backups", self.local)

    def test_ssh_failure_leaves_existing_snapshots_untouched(self) -> None:
        snapshot = create_snapshot(self.project, self.local, datetime.now(timezone.utc))
        with patch(
            "scripts.pull_board_backups_to_mac.subprocess.run",
            side_effect=subprocess.CalledProcessError(255, ["ssh"]),
        ):
            with self.assertRaises(subprocess.CalledProcessError):
                pull_snapshots("fibo@board.local", "/remote/backups", self.local)
        self.assertTrue(snapshot.is_dir())


if __name__ == "__main__":
    unittest.main()
