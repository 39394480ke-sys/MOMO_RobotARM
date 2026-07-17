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
            "subjectLockPreviewFrame",
            "subjectLockName",
            "subjectLockStartMm",
            "subjectLockEndMm",
            "subjectLockSpeedMmS",
            "startSubjectLockCalibrationBtn",
            "validateSubjectLockBtn",
            "moveSubjectLockToStartBtn",
            "playSubjectLockBtn",
            "stopSubjectLockBtn",
            "subjectLockProfilesList",
            "subjectLockCurve",
        ):
            self.assertIn(f'id="{element_id}"', self.html)

    def test_frontend_uses_only_new_subject_lock_api(self) -> None:
        self.assertIn("/api/v1/subject-lock/calibration/start", self.js)
        self.assertIn("/api/v1/subject-lock/profiles/", self.js)
        self.assertNotIn('getJson("/api/v1/cinematic/status"', self.js)

    def test_page_names_the_two_controlled_joints(self) -> None:
        self.assertIn("J10 导轨 + J11 底座旋转", self.html)

    def test_failed_validation_is_not_mislabeled_as_speed_only(self) -> None:
        self.assertIn('needs_speed: "检查未通过"', self.js)
        self.assertNotIn('needs_speed: "速度超限"', self.js)


if __name__ == "__main__":
    unittest.main()
