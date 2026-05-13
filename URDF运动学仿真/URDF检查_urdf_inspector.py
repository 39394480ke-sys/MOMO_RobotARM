"""URDF 检查工具。"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from 运动学模型_kinematics_model import (
    JOINT_NAME_ALIASES,
    SDK_JOINT_NAMES,
    加载运动学配置,
    解析资源路径,
)


def 检查URDF(config_path: str | Path | None = None) -> dict[str, Any]:
    base_dir = Path(__file__).resolve().parent
    config = 加载运动学配置(config_path)
    robot = config.get("robot", {})
    urdf_path = 解析资源路径(robot.get("urdf_path", "urdf/soarmoce_urdf.urdf"), base_dir)
    sdk_joint_names = list(robot.get("sdk_joint_names", SDK_JOINT_NAMES))
    joint_name_aliases = dict(robot.get("joint_name_aliases", JOINT_NAME_ALIASES))
    target_frame = str(robot.get("target_frame", "wrist_roll"))

    report: dict[str, Any] = {
        "ok": False,
        "urdf_path": str(urdf_path),
        "links": [],
        "joints": [],
        "revolute_joints": [],
        "sdk_joint_mapping": {},
        "target_frame": target_frame,
        "missing_meshes": [],
        "errors": [],
        "warnings": [],
    }
    if "_warning" in config:
        report["warnings"].append(config["_warning"])

    if not urdf_path.exists():
        report["errors"].append(f"URDF 文件不存在：{urdf_path}")
        return report

    try:
        root = ET.parse(urdf_path).getroot()
    except ET.ParseError as exc:
        report["errors"].append(f"URDF XML 解析失败：{exc}")
        return report

    links = [element.attrib.get("name", "") for element in root.findall("link")]
    joints: list[dict[str, Any]] = []
    revolute_joints: list[str] = []
    for element in root.findall("joint"):
        name = element.attrib.get("name", "")
        joint_type = element.attrib.get("type", "")
        parent = element.find("parent")
        child = element.find("child")
        entry = {
            "name": name,
            "type": joint_type,
            "parent": parent.attrib.get("link", "") if parent is not None else "",
            "child": child.attrib.get("link", "") if child is not None else "",
        }
        joints.append(entry)
        if joint_type == "revolute":
            revolute_joints.append(name)

    report["links"] = links
    report["joints"] = joints
    report["revolute_joints"] = revolute_joints

    joint_names = {joint["name"] for joint in joints}
    link_names = set(links)
    for sdk_name in sdk_joint_names:
        urdf_name = str(joint_name_aliases.get(sdk_name, sdk_name))
        report["sdk_joint_mapping"][sdk_name] = urdf_name
        if urdf_name not in joint_names:
            report["errors"].append(f"SDK 关节 {sdk_name} 映射到 {urdf_name}，但 URDF 中没有这个 joint。")

    if target_frame not in link_names and target_frame not in joint_names:
        report["errors"].append(f"target_frame={target_frame} 不在 URDF link/joint 中。")

    mesh_paths: list[Path] = []
    for mesh in root.findall(".//mesh"):
        filename = str(mesh.attrib.get("filename", "")).strip()
        if not filename:
            continue
        if filename.startswith("package://") or filename.startswith("pkg://"):
            report["warnings"].append(f"mesh 使用包路径，当前检查不会解析：{filename}")
            continue
        mesh_paths.append((urdf_path.parent / filename).resolve())

    missing_meshes = sorted({str(path) for path in mesh_paths if not path.exists()})
    report["missing_meshes"] = missing_meshes
    if missing_meshes:
        report["errors"].append(f"有 {len(missing_meshes)} 个 mesh 文件不存在。")

    report["ok"] = not report["errors"]
    return report


def main() -> int:
    report = 检查URDF()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
