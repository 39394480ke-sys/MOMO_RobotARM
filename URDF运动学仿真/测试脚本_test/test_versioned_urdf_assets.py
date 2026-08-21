from __future__ import annotations

import hashlib
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


KINEMATICS_ROOT = Path(__file__).resolve().parents[1]
EXPECTED_URDF_CONTENT_HASHES = {
    "v1": "1678172c914c4d6b63178b1ff92ce8de5a86378d27fe4ee17a7edde220e3fe1e",
    "v2": "7940164342c4c11e92eae8ea7b3fd4bd611dce2781b905f5e2bdb69ab03f3a7a",
}
EXPECTED_MESH_HASHES = {
    "v1": {
        "base_link.stl": "26873eb3e28a18b1fd2fdd111475e0a8c3dd843a52b935fba746ae32f3370be4",
        "Link_1.stl": "1b7dbfd8407bc9eb1f636f955701240b481afb200f02135684a695cd2e7088c0",
        "Link_2.stl": "7e9a1721ef0248e6ebabd274135491bcef292414fcde52398fe7db7e7b39450e",
        "Link_3.stl": "1dfa561185bb49d238cf71f53c723e2ae9e226f25247e3c427861528ed7b8a80",
        "Link_4.stl": "c719094564620b0b3d8c09bb360763209b626bcdde07472fb3581456c5cc2f99",
        "Link_5.stl": "4a875bf77cc71866d23ad13e24ce5d1865d97cfc951a622f8f6898ae53fcc67b",
        "Link_6.stl": "7c6d45ffafe235ba5b5853e5917fd9e9ca77700fb0092ad12ecb715e64ef8114",
    },
    "v2": {
        "base_link.stl": "8de59b1b2fa2207dcaa1427bf9ba5dcead9fcfc8d1ed520808fa6e2d6d482e67",
        "Link_2.stl": "5ac523cd4723055d38320b83c2a70b72b8233cafd141f97ad0cf1109fe4f3e17",
        "Link_3.stl": "fc2f2cea3ff5f1449a9d5c495eaccdb2cce86b0d276790a255a753ba712099dd",
        "Link_4.stl": "7c3252133180f772479de3af81b7b027877bdc87ee2e1c51ac160f6f217c5c62",
        "Link_5.stl": "375155bf0f47ff4f0a363709cc841f971d0611c04a6101ce8c68934211ba9526",
        "Link_6.stl": "4046d2513ee572b286ac226d1297aac9ca5d150e3c0718674403b7b089bfe996",
        "Link_7.stl": "a75abef799eec297d9d9bde8b81b9aec006060f594a7b5a4fcfb339b6d2447cc",
    },
}


class VersionedUrdfAssetsTest(unittest.TestCase):
    def load_version(self, version: str) -> tuple[Path, ET.Element]:
        urdf_path = KINEMATICS_ROOT / "urdf" / version / "soarmoce_urdf.urdf"
        self.assertTrue(urdf_path.is_file(), f"missing {version} URDF: {urdf_path}")
        return urdf_path, ET.parse(urdf_path).getroot()

    def test_full_urdf_content_matches_preserved_authority(self) -> None:
        for version, expected_digest in EXPECTED_URDF_CONTENT_HASHES.items():
            with self.subTest(version=version):
                urdf_path, _ = self.load_version(version)
                normalized = urdf_path.read_text(encoding="utf-8").replace(
                    f"../../meshes/{version}/",
                    "__MESH_PREFIX__/",
                )
                digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
                self.assertEqual(digest, expected_digest)

    def test_each_version_references_its_preserved_meshes(self) -> None:
        for version, expected_hashes in EXPECTED_MESH_HASHES.items():
            with self.subTest(version=version):
                urdf_path, robot = self.load_version(version)
                mesh_filenames = {
                    mesh.attrib["filename"] for mesh in robot.findall(".//mesh")
                }
                expected_filenames = {
                    f"../../meshes/{version}/{name}" for name in expected_hashes
                }
                self.assertEqual(mesh_filenames, expected_filenames)

                for filename in mesh_filenames:
                    mesh_path = (urdf_path.parent / filename).resolve()
                    self.assertTrue(mesh_path.is_file(), f"missing mesh: {mesh_path}")
                    digest = hashlib.sha256(mesh_path.read_bytes()).hexdigest()
                    self.assertEqual(digest, expected_hashes[mesh_path.name])

    def test_each_version_has_six_movable_joints_and_expected_tip(self) -> None:
        expected_tips = {"v1": "Link_6", "v2": "Link_7"}
        for version, expected_tip in expected_tips.items():
            with self.subTest(version=version):
                _, robot = self.load_version(version)
                movable_joints = [
                    joint
                    for joint in robot.findall("joint")
                    if joint.attrib.get("type") != "fixed"
                ]
                self.assertEqual(len(movable_joints), 6)

                parent_links = {
                    joint.find("parent").attrib["link"] for joint in movable_joints
                }
                child_links = {
                    joint.find("child").attrib["link"] for joint in movable_joints
                }
                self.assertEqual(child_links - parent_links, {expected_tip})

    def test_v2_j11_axis_matches_real_positive_rotation(self) -> None:
        _, robot = self.load_version("v2")
        j11 = next(joint for joint in robot.findall("joint") if joint.attrib.get("name") == "J11")
        self.assertEqual(j11.find("axis").attrib["xyz"], "0 0 -1")

    def test_v1_and_v2_are_distinct_assets(self) -> None:
        v1_path, v1_robot = self.load_version("v1")
        v2_path, v2_robot = self.load_version("v2")

        self.assertNotEqual(v1_path.read_bytes(), v2_path.read_bytes())
        self.assertNotEqual(v1_robot.attrib["name"], v2_robot.attrib["name"])
        self.assertNotEqual(
            set(EXPECTED_MESH_HASHES["v1"].values()),
            set(EXPECTED_MESH_HASHES["v2"].values()),
        )

    def test_unversioned_authority_is_removed_but_legacy_meshes_remain(self) -> None:
        self.assertFalse(
            (KINEMATICS_ROOT / "urdf" / "soarmoce_urdf.urdf").exists()
        )
        for name in {
            "base_link.stl",
            "Link_1.stl",
            "Link_2.stl",
            "Link_3.stl",
            "Link_4.stl",
            "Link_5.stl",
            "Link_6.stl",
            "Link_7.stl",
        }:
            self.assertFalse((KINEMATICS_ROOT / "meshes" / name).exists())

        for name in {
            "base.STL",
            "elbow.STL",
            "gripper.STL",
            "shoulder.STL",
            "shoulder_lift.STL",
            "wrist.STL",
            "wrist_roll.STL",
        }:
            self.assertTrue((KINEMATICS_ROOT / "meshes" / name).is_file())


if __name__ == "__main__":
    unittest.main()
