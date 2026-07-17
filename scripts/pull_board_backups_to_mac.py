#!/usr/bin/env python3
"""Mirror completed board snapshots to macOS and verify every checksum."""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.backup_board_local_data import prune_snapshots, verify_snapshot
except ModuleNotFoundError:
    from backup_board_local_data import prune_snapshots, verify_snapshot


def pull_snapshots(
    host: str,
    remote_root: str,
    local_root: Path,
    *,
    retention_days: int = 30,
    now: datetime | None = None,
) -> None:
    local_root = local_root.expanduser().resolve()
    snapshots = local_root / "snapshots"
    ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host]
    remote_snapshots = f"{remote_root.rstrip('/')}/snapshots"
    remote_backup_command = [
        "/home/fibo/miniforge3/bin/python",
        "/home/fibo/MOMO_RobotARM/scripts/backup_board_local_data.py",
        "--project-root",
        "/home/fibo/MOMO_RobotARM",
        "--backup-root",
        remote_root.rstrip("/"),
        "--retention-days",
        str(retention_days),
    ]
    subprocess.run(ssh + [shlex.join(remote_backup_command)], check=True)
    subprocess.run(ssh + [f"test -d {shlex.quote(remote_snapshots)}"], check=True)
    snapshots.mkdir(parents=True, exist_ok=True)
    rsync = [
        "rsync",
        "-a",
        "--partial",
        "--prune-empty-dirs",
        f"{host}:{remote_snapshots}/",
        str(snapshots) + "/",
    ]
    subprocess.run(rsync, check=True)
    for manifest in sorted(snapshots.glob("*/manifest.json")):
        verify_snapshot(manifest.parent)
    prune_snapshots(snapshots, retention_days, now or datetime.now(timezone.utc))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="fibo@qcs6490-odk.local")
    parser.add_argument("--remote-root", default="/home/fibo/MOMO_RobotARM-local-backups")
    parser.add_argument("--local-root", type=Path, default=Path.home() / "MOMO_RobotARM-backups" / "qcs6490-odk")
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()
    pull_snapshots(
        args.host,
        args.remote_root,
        args.local_root,
        retention_days=args.retention_days,
    )
    print(json.dumps({"local_root": str(args.local_root.expanduser().resolve()), "verified": True}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
