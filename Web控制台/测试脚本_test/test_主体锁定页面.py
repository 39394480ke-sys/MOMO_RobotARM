"""主体锁定运镜 Web 页面结构与调用路径测试。"""

from __future__ import annotations

import unittest

from Web测试路径_test_paths import WEB_ROOT


class SubjectLockPageTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.js = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")

    def test_replaces_old_ai_director_controls(self) -> None:
        self.assertIn('data-page="cinematic">主体锁定运镜', self.html)
        for old_id in ("analyzeCinematicBtn", "keyframesCinematicBtn", "cinematicRecordPath", "cinematicProjectPath"):
            self.assertNotIn(f'id="{old_id}"', self.html)

    def test_exposes_complete_subject_lock_workflow(self) -> None:
        for element_id in (
            "cameraHubSubjectLink",
            "subjectLockName",
            "subjectLockStartMm",
            "subjectLockEndMm",
            "subjectLockSpeedMmS",
            "subjectLockPlaybackSpeedMmS",
            "startSubjectLockCalibrationBtn",
            "validateSubjectLockBtn",
            "moveSubjectLockToStartBtn",
            "playSubjectLockBtn",
            "stopSubjectLockBtn",
            "subjectLockProfilesList",
            "subjectLockCurve",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_live_preview_and_drag_selection_moved_to_camera_hub(self) -> None:
        self.assertNotIn('id="subjectLockPreviewFrame"', self.html)
        self.assertNotIn('id="visionPreviewFrame"', self.html)
        self.assertNotIn("/api/v1/vision/frame.jpg?t=", self.js)
        self.assertNotIn("setInterval(refreshVisionPreview", self.js)
        self.assertNotIn("renderVisionPreviewUrl", self.js)
        self.assertIn('id="cameraHubFollowLink"', self.html)
        self.assertIn('id="cameraHubSubjectLink"', self.html)

    def test_camera_hub_links_use_loaded_public_config(self) -> None:
        self.assertIn("updateCameraHubLinks();", self.js)
        self.assertIn("state.config?.camera_hub?.public_port || 8020", self.js)
        self.assertIn('["#cameraHubFollowLink", "#cameraHubSubjectLink", "#cameraHubSettingsLink"]', self.js)
        self.assertNotIn("`${location.protocol}//${location.hostname || \"127.0.0.1\"}:8020/`", self.js)

    def test_visual_status_refreshes_manually_and_at_low_frequency(self) -> None:
        self.assertIn('$("#refreshFollowBtn").addEventListener("click", refreshFollowPageStatus);', self.js)
        self.assertIn('$("#refreshSubjectLockBtn").addEventListener("click", refreshSubjectLockPageStatus);', self.js)
        self.assertIn("window.setInterval(refreshActiveVisionStatus, 2000)", self.js)
        self.assertIn("if (followActive) requests.push(refreshVisionProxyStatus());", self.js)
        self.assertIn("if (subjectLockActive) requests.push(refreshSubjectLockTargetState());", self.js)

    def test_frontend_uses_only_new_subject_lock_api(self) -> None:
        self.assertIn("/api/v1/subject-lock/calibration/start", self.js)
        self.assertIn("/api/v1/subject-lock/profiles/", self.js)
        self.assertNotIn('getJson("/api/v1/cinematic/status"', self.js)

    def test_page_names_the_two_controlled_joints(self) -> None:
        self.assertIn("J10 导轨 + J11 水平旋转 + J13 竖直俯仰", self.html)

    def test_failed_validation_is_not_mislabeled_as_speed_only(self) -> None:
        self.assertIn('needs_speed: "检查未通过"', self.js)
        self.assertNotIn('needs_speed: "速度超限"', self.js)

    def test_playback_speed_is_revalidated_before_play(self) -> None:
        self.assertIn("function subjectLockPlaybackSpeed()", self.js)
        self.assertIn("const speedMmS = subjectLockPlaybackSpeed();", self.js)
        self.assertIn("SUBJECT_LOCK_SPEED_UNSAFE", self.js)


if __name__ == "__main__":
    unittest.main()
