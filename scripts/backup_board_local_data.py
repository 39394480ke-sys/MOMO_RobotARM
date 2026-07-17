#!/usr/bin/env python3
"""Create checksum-verified snapshots of board-local robot data."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable


BACKUP_PATHS = (
    "GUI图形界面/GUI配置.local.yaml",
    "Web控制台/Web配置.local.yaml",
    "真实舵机控制/真实配置.local.yaml",
    "真实舵机控制/标定文件.json",
    "真实舵机控制/标定备份_backups",
    "视觉识别与跟随/视觉配置.local.yaml",
    "语音Agent/Agent配置.local.yaml",
    "仿真控制系统/姿态管理/姿态库.json",
    "仿真控制系统/姿态管理/动作库",
    "动作录制与回放增强/动作库",
    "动作录制与回放增强/录制记录",
    "视觉识别与跟随/runtime/cinematic_director_projects",
    "视觉识别与跟随/runtime/cinematic_records",
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_calibration(project_root: Path) -> None:
    path = project_root / "真实舵机控制" / "标定文件.json"
    if not path.is_file():
        return
    data = json.loads(path.read_text(encoding="utf-8"))
    missing = [f"j{index}" for index in range(10, 16) if f"j{index}" not in data]
    if missing:
        raise ValueError(f"calibration is missing required joints: {', '.join(missing)}")


def _copy_selected(project_root: Path, partial: Path, paths: Iterable[str]) -> None:
    for relative in paths:
        source = project_root / relative
        if not source.exists():
            continue
        destination = partial / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, destination, symlinks=True)
        else:
            shutil.copy2(source, destination, follow_symlinks=False)


def _manifest_files(snapshot_dir: Path) -> list[dict[str, object]]:
    entries = []
    for path in sorted(item for item in snapshot_dir.rglob("*") if item.is_file() and item.name != "manifest.json"):
        entries.append({
            "path": path.relative_to(snapshot_dir).as_posix(),
            "size": path.stat().st_size,
            "sha256": _sha256(path),
        })
    return entries


def create_snapshot(project_root: Path, backup_root: Path, now: datetime) -> Path:
    project_root = project_root.expanduser().resolve()
    backup_root = backup_root.expanduser().resolve()
    _validate_calibration(project_root)
    created = _utc(now)
    stamp = created.strftime("%Y%m%dT%H%M%S.%fZ")
    snapshots = backup_root / "snapshots"
    snapshots.mkdir(parents=True, exist_ok=True)
    partial = snapshots / f".partial-{stamp}"
    destination = snapshots / stamp
    if partial.exists() or destination.exists():
        raise FileExistsError(f"snapshot already exists: {destination}")
    partial.mkdir()
    try:
        _copy_selected(project_root, partial, BACKUP_PATHS)
        manifest = {
            "schema_version": 1,
            "created_at": created.isoformat().replace("+00:00", "Z"),
            "project_root": str(project_root),
            "files": _manifest_files(partial),
        }
        (partial / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        verify_snapshot(partial)
        partial.rename(destination)
        return destination
    except Exception:
        shutil.rmtree(partial, ignore_errors=True)
        raise


def verify_snapshot(snapshot_dir: Path) -> None:
    snapshot_dir = snapshot_dir.expanduser().resolve()
    manifest_path = snapshot_dir / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"manifest is missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("files"), list):
        raise ValueError(f"invalid snapshot manifest: {manifest_path}")
    for entry in manifest["files"]:
        relative = str(entry.get("path", ""))
        path = snapshot_dir / relative
        if not path.is_file():
            raise ValueError(f"snapshot file is missing: {relative}")
        if path.stat().st_size != int(entry.get("size", -1)):
            raise ValueError(f"size mismatch: {relative}")
        if _sha256(path) != entry.get("sha256"):
            raise ValueError(f"checksum mismatch: {relative}")


def prune_snapshots(snapshot_root: Path, retention_days: int, now: datetime) -> list[Path]:
    snapshot_root = snapshot_root.expanduser().resolve()
    if not snapshot_root.is_dir():
        return []
    successful: list[tuple[datetime, Path]] = []
    for directory in snapshot_root.iterdir():
        if not directory.is_dir() or directory.name.startswith(".partial-") or not (directory / "manifest.json").is_file():
            continue
        try:
            verify_snapshot(directory)
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(manifest["created_at"]).replace("Z", "+00:00"))
            successful.append((_utc(created), directory))
        except (ValueError, KeyError, json.JSONDecodeError):
            continue
    if not successful:
        return []
    newest = max(successful, key=lambda item: item[0])[1]
    cutoff = _utc(now) - timedelta(days=max(0, retention_days))
    removed = []
    for created, directory in successful:
        if directory != newest and created < cutoff:
            shutil.rmtree(directory)
            removed.append(directory)
    return removed


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--backup-root", type=Path, default=Path.home() / "MOMO_RobotARM-local-backups")
    parser.add_argument("--retention-days", type=int, default=30)
    args = parser.parse_args()
    now = datetime.now(timezone.utc)
    snapshot = create_snapshot(args.project_root, args.backup_root, now)
    removed = prune_snapshots(args.backup_root / "snapshots", args.retention_days, now)
    print(json.dumps({"snapshot": str(snapshot), "pruned": [str(path) for path in removed]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
