"""主体锁定 Web API、委托和运动互斥测试。"""

from __future__ import annotations

import threading
import tempfile
import unittest
from pathlib import Path

from Web测试路径_test_paths import WEB_ROOT
from 控制桥接_common import ensure_import_paths
from backend.schemas import (
    SubjectLockCalibrationStartRequest,
    SubjectLockProfileActionRequest,
    SubjectLockValidateRequest,
)
from backend.service import WebControlService


class FakeSubjectLockController:
    def __init__(self) -> None:
        self.stopped: list[str] = []
        self.validated: list[tuple[str, float]] = []

    def get_status(self) -> dict:
        return {"running": False, "phase": "ready"}

    def list_profiles(self) -> list[dict]:
        return [{"profile_id": "toy", "schema": "subject_lock_v1"}]

    def load_profile(self, profile_id: str) -> dict:
        return {"profile_id": profile_id, "schema": "subject_lock_v1"}

    def validate_profile(self, profile_id: str, speed_mm_s: float) -> dict:
        self.validated.append((profile_id, speed_mm_s))
        return {"profile_id": profile_id, "validation": {"valid": True}}

    def request_stop(self, reason: str) -> None:
        self.stopped.append(reason)


class FakeBridge:
    mode = "dry_run"

    def __init__(self) -> None:
        self.cached_reads = 0
        self.full_reads = 0

    def get_cached_state(self) -> dict:
        self.cached_reads += 1
        return {"ok": True, "data": {"joints_deg": {"j10": 1.0, "j11": 2.0}}}

    def get_state(self) -> dict:
        self.full_reads += 1
        return {"ok": True, "data": {"joints_deg": {"j10": 1.0, "j11": 2.0}}}

    def validate_stream_joint_targets(self, targets: dict) -> dict:
        return {"ok": True, "data": {"targets_deg": targets}}


class SubjectLockWebTest(unittest.TestCase):
    def test_request_models_enforce_subject_lock_inputs(self) -> None:
        request = SubjectLockCalibrationStartRequest(name="toy", start_mm=-10, end_mm=10, speed_mm_s=2)
        self.assertEqual(request.speed_mm_s, 2)
        self.assertEqual(SubjectLockValidateRequest(speed_mm_s=3).speed_mm_s, 3)
        self.assertEqual(SubjectLockProfileActionRequest().confirm_text, "")

    def test_service_delegates_profile_queries_and_validation(self) -> None:
        service = WebControlService.__new__(WebControlService)
        service._subject_lock_controller = FakeSubjectLockController()

        self.assertEqual(service.subject_lock_status()["phase"], "ready")
        self.assertEqual(service.subject_lock_profiles()[0]["profile_id"], "toy")
        result = service.subject_lock_validate("toy", SubjectLockValidateRequest(speed_mm_s=4))
        self.assertTrue(result["validation"]["valid"])
        self.assertEqual(service._subject_lock_controller.validated, [("toy", 4.0)])

    def test_manual_motion_revokes_subject_lock_stream_owner(self) -> None:
        controller = FakeSubjectLockController()
        service = WebControlService.__new__(WebControlService)
        service._lock = threading.RLock()
        service.config = {"safety": {"real_mode_requires_confirm": False}}
        service.bridge = FakeBridge()
        service._action_thread = None
        service._continuous_jog_thread = None
        service._follow_controller = None
        service._subject_lock_controller = controller

        service._before_manual_motion("")

        self.assertIsNone(service._subject_lock_controller)
        self.assertEqual(controller.stopped, ["manual_motion"])

    def test_state_poll_uses_cached_targets_during_subject_lock_stream(self) -> None:
        bridge = FakeBridge()
        controller = FakeSubjectLockController()
        controller.get_status = lambda: {"running": True, "phase": "playing"}
        service = WebControlService.__new__(WebControlService)
        service._lock = threading.RLock()
        service.bridge = bridge
        service._continuous_jog_status = {"running": False}
        service._continuous_jog_thread = None
        service._subject_lock_controller = controller

        service.get_robot_state()

        self.assertEqual(bridge.cached_reads, 1)
        self.assertEqual(bridge.full_reads, 0)

    def test_app_exposes_all_subject_lock_routes(self) -> None:
        source = (WEB_ROOT / "backend" / "app.py").read_text(encoding="utf-8")
        for route in (
            "/api/v1/subject-lock/status",
            "/api/v1/subject-lock/profiles",
            "/api/v1/subject-lock/calibration/start",
            "/api/v1/subject-lock/calibration/stop",
            "/api/v1/subject-lock/playback/stop",
        ):
            self.assertIn(route, source)

    def test_subject_lock_uses_independent_40hz_not_follow_frequency(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ensure_import_paths([WEB_ROOT.parent / "视觉识别与跟随"])
            service = WebControlService.__new__(WebControlService)
            service._subject_lock_controller = None
            service.base_dir = Path(directory) / "Web控制台"
            service.base_dir.mkdir()
            service.bridge = FakeBridge()
            service.vision_latest = lambda: {}
            service._follow_initial_state = lambda: {"j10": 0.0, "j11": 0.0}
            service._load_vision_follow_config = lambda _root: {"control_update_hz": 60.0}

            controller = service._get_subject_lock_controller()

            self.assertEqual(controller.config["control_update_hz"], 40.0)


if __name__ == "__main__":
    unittest.main()
