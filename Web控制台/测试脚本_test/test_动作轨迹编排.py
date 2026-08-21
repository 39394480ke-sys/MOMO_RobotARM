"""动作关键帧编排的素材、快照、预览与前端契约测试。"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from pydantic import ValidationError

import Web测试路径_test_paths  # noqa: F401

from backend.action_composer import ActionComposer, ActionComposerError
from backend.schemas import ActionComposerPreviewRequest, ActionComposerSaveRequest


WEB_ROOT = Path(__file__).resolve().parents[1]
JOINTS = ["j10", "j11", "j12", "j13", "j14", "j15"]


def targets(start: float) -> dict[str, float]:
    return {joint: start + index for index, joint in enumerate(JOINTS)}


class FakeLibrary:
    def __init__(self, root: Path):
        self.root = root
        self.config = {
            "robot": {"variant": "V1", "sdk_joint_names": list(JOINTS)},
            "files": {"action_library_dir": str(root), "runtime_log": "runtime.log"},
            "playback": {
                "default_duration_sec": 1.5,
                "default_interval_sec": 0.0,
                "auto_duration_from_distance": True,
                "joint_speed_limits": {joint: 100.0 for joint in JOINTS},
                "real_mode_min_duration_sec": 2.0,
            },
        }
        self.actions = {
            "V1环绕": {
                "schema_version": "arm_replay_sequence_v1",
                "robot_variant": "V1",
                "name": "V1环绕",
                "joint_order": list(JOINTS),
                "poses": [
                    {
                        "name": "left",
                        "duration_sec": 0.4,
                        "hold_sec": 0.0,
                        "joint_targets_deg": targets(1),
                        "raw_present_position": {"j10": 999},
                        "replay_multi_turn_continuous_raw": {"j10": 888},
                    },
                    {"name": "right", "duration_sec": 0.5, "hold_sec": 0.0, "joint_targets_deg": targets(20)},
                ],
            },
            "V2动作": {
                "schema_version": "arm_replay_sequence_v1",
                "robot_variant": "V2",
                "name": "V2动作",
                "joint_order": list(JOINTS),
                "poses": [{"name": "v2", "joint_targets_deg": targets(30)}],
            },
        }

    def list_actions(self):
        return sorted(self.actions)

    def load_action(self, name):
        if name not in self.actions:
            raise FileNotFoundError(name)
        payload = deepcopy(self.actions[name])
        actual = payload.get("robot_variant")
        payload["_robot_variant_preview"] = {
            "匹配": actual == "V1",
            "问题": f"动作型号不匹配：{actual}",
        }
        return payload

    def action_path(self, name):
        return self.root / f"{name}.json"

    def save_action(self, name, payload):
        self.actions[name] = deepcopy(payload)
        path = self.action_path(name)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return path


class FakePoseManager:
    def __init__(self):
        self.poses = {
            "中景": {"关节角度": list(targets(7).values()), "夹爪": 60, "说明": "历史姿态"},
            "V2姿态": {"关节角度": list(targets(50).values()), "robot_variant": "V2"},
        }

    def 列出姿态(self):
        return sorted(self.poses)

    def 获取姿态(self, name):
        value = self.poses.get(name)
        return deepcopy(value) if value is not None else None


class FakeModel:
    def __init__(self):
        self.closed = False

    def forward(self, q):
        return {"xyz": [float(q[0]), 0.1, 0.2], "rpy": [0.0, 0.0, 0.0]}

    def close(self):
        self.closed = True


class FakeBridge:
    def __init__(self, root: Path):
        self.library = FakeLibrary(root)
        self.poses = FakePoseManager()
        self.model = FakeModel()

    def _get_action_library(self):
        return self.library

    def _get_pose_manager(self):
        return self.poses

    def create_preview_kinematics_model(self):
        return self.model, ""


class UnavailablePreviewBridge(FakeBridge):
    def create_preview_kinematics_model(self):
        return None, "PyBullet 未安装"


class ActionComposerTest(unittest.TestCase):
    def make_request(self, save: bool = False):
        cls = ActionComposerSaveRequest if save else ActionComposerPreviewRequest
        payload = {
            "description": "A-B-A 测试",
            "entry_duration_sec": 2.0,
            "frames": [
                {"source_kind": "action", "source_name": "V1环绕", "source_frame_index": 0, "duration_sec": 0.5, "hold_sec": 0.1},
                {"source_kind": "pose", "source_name": "中景", "duration_sec": 0.6, "hold_sec": 0.2},
                {"source_kind": "action", "source_name": "V1环绕", "source_frame_index": 0, "duration_sec": 0.7, "hold_sec": 0.3},
            ],
        }
        if save:
            payload["name"] = "新轨迹"
        return cls(**payload)

    def test_sources_only_expose_current_variant_and_assume_legacy_pose(self) -> None:
        with TemporaryDirectory() as root:
            composer = ActionComposer(FakeBridge(Path(root)))
            sources = composer.sources()
            self.assertEqual([item["name"] for item in sources["actions"]], ["V1环绕"])
            self.assertEqual([item["name"] for item in sources["poses"]], ["中景"])
            self.assertTrue(sources["poses"][0]["legacy_variant_assumed"])

    def test_duplicate_reorder_snapshot_drops_raw_and_survives_source_delete(self) -> None:
        with TemporaryDirectory() as root:
            bridge = FakeBridge(Path(root))
            composer = ActionComposer(bridge)
            result = composer.save(self.make_request(save=True))
            saved = deepcopy(bridge.library.actions[result["name"]])

            self.assertEqual([pose["joint_targets_deg"]["j10"] for pose in saved["poses"]], [1.0, 7.0, 1.0])
            self.assertEqual([pose["index"] for pose in saved["poses"]], [1, 2, 3])
            self.assertFalse(any("raw_present_position" in pose for pose in saved["poses"]))
            self.assertFalse(any("replay_multi_turn_continuous_raw" in pose for pose in saved["poses"]))
            self.assertEqual(saved["cinematic"], {"pass_through": True, "honor_keyframe_holds": True})
            self.assertTrue(saved["playback"]["position_before_replay"])
            self.assertEqual(saved["playback"]["entry_duration_sec"], 2.0)

            del bridge.library.actions["V1环绕"]
            del bridge.poses.poses["中景"]
            self.assertEqual(saved["poses"][1]["joint_targets_deg"]["j10"], 7.0)

    def test_preview_uses_safety_duration_and_never_overwrites(self) -> None:
        with TemporaryDirectory() as root:
            bridge = FakeBridge(Path(root))
            composer = ActionComposer(bridge)
            preview = composer.create_preview(self.make_request())
            self.assertEqual(preview["frame_count"], 3)
            self.assertTrue(all(segment["duration_sec"] >= 2.0 for segment in preview["segments"]))
            self.assertGreater(preview["total_duration_sec"], 4.0)

            composer.save(self.make_request(save=True))
            with self.assertRaises(ActionComposerError) as caught:
                composer.save(self.make_request(save=True))
            self.assertEqual(caught.exception.code, "ACTION_NAME_CONFLICT")

    def test_missing_or_incompatible_sources_are_rejected(self) -> None:
        with TemporaryDirectory() as root:
            composer = ActionComposer(FakeBridge(Path(root)))
            request = self.make_request()
            request.frames[0].source_name = "V2动作"
            with self.assertRaises(ActionComposerError) as caught:
                composer.create_preview(request)
            self.assertEqual(caught.exception.code, "ACTION_COMPOSER_VARIANT_MISMATCH")

    def test_deleted_and_corrupt_sources_are_rejected(self) -> None:
        with TemporaryDirectory() as root:
            bridge = FakeBridge(Path(root))
            composer = ActionComposer(bridge)
            request = self.make_request()
            request.frames[0].source_name = "已删除动作"
            with self.assertRaises(ActionComposerError) as missing:
                composer.create_preview(request)
            self.assertEqual(missing.exception.code, "ACTION_COMPOSER_SOURCE_MISSING")

            request = self.make_request()
            del bridge.library.actions["V1环绕"]["poses"][0]["joint_targets_deg"]["j15"]
            with self.assertRaises(ActionComposerError) as corrupt:
                composer.create_preview(request)
            self.assertEqual(corrupt.exception.code, "ACTION_COMPOSER_INVALID_FRAME")

    def test_request_schema_rejects_short_or_illegal_timing(self) -> None:
        payload = self.make_request().model_dump()
        payload["frames"] = payload["frames"][:1]
        with self.assertRaises(ValidationError):
            ActionComposerPreviewRequest(**payload)

        payload = self.make_request().model_dump()
        payload["frames"][1]["duration_sec"] = 0.0
        with self.assertRaises(ValidationError):
            ActionComposerPreviewRequest(**payload)

    def test_expired_and_unavailable_preview_errors_are_explicit(self) -> None:
        with TemporaryDirectory() as root:
            composer = ActionComposer(FakeBridge(Path(root)), preview_ttl_sec=30.0)
            preview = composer.create_preview(self.make_request())
            composer._sessions[preview["preview_id"]].created_at = 0.0
            with self.assertRaises(ActionComposerError) as expired:
                composer.render_preview(preview["preview_id"], 0.0, 640, 420)
            self.assertEqual(expired.exception.code, "ACTION_COMPOSER_PREVIEW_EXPIRED")

        with TemporaryDirectory() as root:
            composer = ActionComposer(UnavailablePreviewBridge(Path(root)))
            with self.assertRaises(ActionComposerError) as unavailable:
                composer.create_preview(self.make_request())
            self.assertEqual(unavailable.exception.code, "ACTION_COMPOSER_PREVIEW_UNAVAILABLE")

    def test_frontend_and_api_expose_complete_composer_flow(self) -> None:
        app_js = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        html = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        backend = (WEB_ROOT / "backend" / "app.py").read_text(encoding="utf-8")
        self.assertIn('id="pageComposer"', html)
        self.assertIn('id="composerTimeline"', html)
        self.assertIn("data-composer-duplicate", app_js)
        self.assertIn("handleComposerDrop", app_js)
        self.assertIn("Math.max(0, (now - state.composer.previewStartedAt) / 1000)", app_js)
        self.assertIn("t: safeElapsed.toFixed(3)", app_js)
        self.assertIn("/api/v1/action-composer/preview", backend)
        self.assertIn("/api/v1/action-composer/save", backend)


if __name__ == "__main__":
    unittest.main()
