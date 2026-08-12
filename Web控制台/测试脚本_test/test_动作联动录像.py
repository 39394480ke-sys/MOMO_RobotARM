"""动作播放与 Camera Hub 录像生命周期测试。"""

from __future__ import annotations

import threading
import unittest

from Web测试路径_test_paths import ensure_web_test_paths

ensure_web_test_paths()

from backend.schemas import PlayActionRequest
from backend.service import WebControlService


class NullLogger:
    def log(self, *args, **kwargs) -> None:
        return None


class ActionBridge:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.action_status = {"state": "idle", "name": ""}

    def play_action(self, name: str, speed: float, loop: bool, on_first_pose_ready=None) -> dict:
        self.events.append("position_first_pose")
        if on_first_pose_ready is not None:
            on_first_pose_ready()
        self.events.append("play_action_frames")
        self.action_status = {"state": "idle", "name": name, "message": "完成"}
        return {"ok": True, "message": "完成", "data": {"name": name}}

    def stop_action(self) -> dict:
        self.action_status = {"state": "stopped", "name": ""}
        return {"ok": True, "message": "停止", "data": {}}


def make_service(events: list[str]) -> WebControlService:
    service = WebControlService.__new__(WebControlService)
    service.config = {
        "camera_hub": {
            "enabled": True,
            "record_with_actions": True,
            "preroll_sec": 0,
            "public_port": 8020,
        }
    }
    service.bridge = ActionBridge(events)
    service._lock = threading.RLock()
    service._action_thread = None
    service._action_video = None
    service.logger = NullLogger()
    service.recent_error = None
    service._before_manual_motion = lambda _confirm: None
    service.stop_continuous_jog = lambda join_timeout=0.2: None
    return service


class ActionCameraRecordingTest(unittest.TestCase):
    def test_recording_wraps_action_and_exposes_ready_video(self) -> None:
        events: list[str] = []
        service = make_service(events)

        def camera_post(path: str) -> dict:
            events.append(path)
            if path.endswith("/start"):
                return {"id": "video-123", "created_at": "2026-08-12T00:00:00Z"}
            return {
                "id": "video-123",
                "duration_sec": 2.5,
                "download_name": "recording.mp4",
                "content_url": "/api/v1/media/video-123/content",
            }

        service._camera_hub_post = camera_post

        response = service.play_action(PlayActionRequest(name="挥手", record_video=True))
        service._action_thread.join(timeout=1.0)

        self.assertEqual(
            events,
            [
                "position_first_pose",
                "/api/v1/recordings/start",
                "play_action_frames",
                "/api/v1/recordings/stop",
            ],
        )
        self.assertIn(response["video_recording"]["state"], {"positioning", "recording", "finalizing", "ready"})
        video = service.current_action_status()["video_recording"]
        self.assertEqual(video["state"], "ready")
        self.assertEqual(video["media_id"], "video-123")
        self.assertEqual(video["camera_hub_path"], "/?media=video-123")

    def test_recording_can_be_disabled_for_one_playback(self) -> None:
        events: list[str] = []
        service = make_service(events)
        service._camera_hub_post = lambda _path: self.fail("Camera Hub should not be called")

        service.play_action(PlayActionRequest(name="挥手", record_video=False))
        service._action_thread.join(timeout=1.0)

        self.assertEqual(events, ["position_first_pose", "play_action_frames"])
        self.assertNotIn("video_recording", service.current_action_status())

    def test_camera_start_failure_stops_after_first_pose(self) -> None:
        events: list[str] = []
        service = make_service(events)

        def fail_start(_path: str) -> dict:
            raise RuntimeError("offline")

        service._camera_hub_post = fail_start

        service.play_action(PlayActionRequest(name="挥手", record_video=True))
        service._action_thread.join(timeout=1.0)

        self.assertEqual(events, ["position_first_pose"])
        self.assertEqual(service.current_action_status()["video_recording"]["state"], "error")


if __name__ == "__main__":
    unittest.main()
