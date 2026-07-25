from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


KINEMATICS_ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = KINEMATICS_ROOT.parent
for import_path in (PROJECT_ROOT, KINEMATICS_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from URDF检查_urdf_inspector import 检查URDF
from 运动学模型_kinematics_model import 加载运动学配置


JOINTS = [f"j{index}" for index in range(10, 16)]


def write_real_config(root: Path, variant: str) -> Path:
    path = root / "真实配置.yaml"
    path.write_text(
        json.dumps(
            {
                "transport": {"port": "", "driver_backend": "sdk", "dry_run": True},
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
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class V2ModelTests(unittest.TestCase):
    def test_temp_v2_config_selects_link_7_chain_and_versioned_assets(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            real_path = write_real_config(Path(tmp), "V2")
            report = 检查URDF(real_config_path=real_path)

        self.assertTrue(report["ok"], report["errors"])
        self.assertEqual(report["target_frame"], "Link_7")
        self.assertEqual(
            [joint["name"] for joint in report["joints"]],
            ["J10", "J11", "J12", "J13", "J14", "J15"],
        )
        self.assertEqual(
            [joint["child"] for joint in report["joints"]],
            ["Link_2", "Link_3", "Link_4", "Link_5", "Link_6", "Link_7"],
        )
        self.assertEqual(
            [Path(path).name for path in report["meshes"]],
            [
                "Link_2.stl",
                "Link_3.stl",
                "Link_4.stl",
                "Link_5.stl",
                "Link_6.stl",
                "Link_7.stl",
                "base_link.stl",
            ],
        )
        self.assertEqual(report["missing_meshes"], [])

    def test_local_variant_selection_drives_kinematics_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {}, clear=True):
            root = Path(tmp)
            real_path = write_real_config(root, "V2")
            (root / "真实配置.local.yaml").write_text(
                "robot:\n  variant: V1\n",
                encoding="utf-8",
            )
            config = 加载运动学配置(real_config_path=real_path)

        self.assertEqual(config["robot"]["variant"], "V1")
        self.assertEqual(config["robot"]["urdf_path"], "urdf/v1/soarmoce_urdf.urdf")
        self.assertEqual(config["robot"]["target_frame"], "Link_6")
        self.assertEqual(
            config["robot"]["joint_scales"],
            {
                "j10": 1.0,
                "j11": 5.0,
                "j12": -5.3,
                "j13": 5.6,
                "j14": -1.0,
                "j15": 1.0,
            },
        )


if __name__ == "__main__":
    unittest.main()
