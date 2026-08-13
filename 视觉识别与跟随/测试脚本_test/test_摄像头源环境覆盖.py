"""Camera Hub RTSP 环境覆盖测试。"""

from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from 视觉测试路径_test_paths import VISION_ROOT  # noqa: F401
from vision import 摄像头_source as source_module
from vision.摄像头_source import VideoSource
from 视觉主程序_main import load_config


CAMERA_HUB_URL = "rtsp://127.0.0.1:8554/armcam-analysis"
PROJECT_ROOT = VISION_ROOT.parent


class FakeCapture:
    def __init__(self, *, opened: bool = True, reads: list[object] | None = None):
        self.opened = opened
        self.reads = list(reads or [])
        self.released = False
        self.properties: list[tuple[object, object]] = []

    def isOpened(self) -> bool:
        return self.opened and not self.released

    def set(self, key: object, value: object) -> bool:
        self.properties.append((key, value))
        return True

    def read(self):
        result = self.reads.pop(0) if self.reads else (False, None)
        if isinstance(result, Exception):
            raise result
        return result

    def release(self) -> None:
        self.released = True


class FakeCv2:
    CAP_PROP_BUFFERSIZE = 1
    CAP_PROP_FRAME_WIDTH = 2
    CAP_PROP_FRAME_HEIGHT = 3
    CAP_PROP_FPS = 4
    ROTATE_180 = 5
    CAP_FFMPEG = 6
    CAP_PROP_OPEN_TIMEOUT_MSEC = 7
    CAP_PROP_READ_TIMEOUT_MSEC = 8

    def __init__(
        self,
        captures: list[FakeCapture] | None = None,
        open_error: Exception | None = None,
        rotate_error: Exception | None = None,
    ):
        self.captures = list(captures or [])
        self.open_error = open_error
        self.rotate_error = rotate_error
        self.sources: list[object] = []
        self.capture_args: list[tuple[object, ...]] = []

    def VideoCapture(self, source: object, *args: object) -> FakeCapture:
        self.sources.append(source)
        self.capture_args.append(tuple(args))
        if self.open_error is not None:
            raise self.open_error
        return self.captures.pop(0)

    def rotate(self, frame: object, mode: object) -> object:
        if self.rotate_error is not None:
            raise self.rotate_error
        return frame


class StreamingCapture(FakeCapture):
    def __init__(self, interval_sec: float = 0.002):
        super().__init__(opened=True)
        self.interval_sec = interval_sec
        self.counter = 0

    def read(self):
        time.sleep(self.interval_sec)
        if self.released:
            return False, None
        self.counter += 1
        return True, f"frame-{self.counter}"


class BlockingCapture(FakeCapture):
    def __init__(self):
        super().__init__(opened=True)
        self.entered = threading.Event()
        self.unblocked = threading.Event()

    def read(self):
        self.entered.set()
        self.unblocked.wait(timeout=2.0)
        return False, None

    def release(self) -> None:
        super().release()
        self.unblocked.set()


class CameraSourceEnvironmentTest(unittest.TestCase):
    def test_environment_switches_physical_camera_to_camera_hub_rtsp(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = Path(temp_dir) / "vision.yaml"
            config_path.write_text(
                "camera:\n  source_type: camera\n  camera_index: 2\n  rtsp_url: ''\nservice:\n  port: 8000\n",
                encoding="utf-8",
            )
            environment = {
                "ARM_VISION_SOURCE_TYPE": "rtsp",
                "ARM_VISION_RTSP_URL": CAMERA_HUB_URL,
            }

            with patch.dict(os.environ, environment, clear=False):
                config = load_config(config_path)

        self.assertEqual(config["camera"]["source_type"], "rtsp")
        self.assertEqual(config["camera"]["rtsp_url"], CAMERA_HUB_URL)
        self.assertEqual(config["camera"]["camera_index"], 2)

    def test_env_example_exposes_camera_hub_defaults(self) -> None:
        example = PROJECT_ROOT / "系统集成" / "环境变量.env.example"
        active_lines = {
            line.strip()
            for line in example.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        }
        self.assertIn("ARM_VISION_SOURCE_TYPE=rtsp", active_lines)
        self.assertIn(f"ARM_VISION_RTSP_URL={CAMERA_HUB_URL}", active_lines)

    def test_rtsp_uses_url_and_missing_url_never_opens_camera_index(self) -> None:
        fake_cv2 = FakeCv2([FakeCapture(opened=True)])
        with patch.object(source_module, "cv2", fake_cv2):
            source = VideoSource({"source_type": "rtsp", "camera_index": 7, "rtsp_url": CAMERA_HUB_URL})
            self.assertTrue(source.open(), source.last_error)
            source.close()
        self.assertEqual(fake_cv2.sources, [CAMERA_HUB_URL])
        self.assertIsInstance(fake_cv2.sources[0], str)

        unopened_cv2 = FakeCv2()
        with patch.object(source_module, "cv2", unopened_cv2):
            missing = VideoSource({"source_type": "rtsp", "camera_index": 7, "rtsp_url": ""})
            self.assertFalse(missing.open())
        self.assertIn("rtsp_url", missing.last_error)
        self.assertEqual(unopened_cv2.sources, [])

    def test_legacy_device_and_file_sources_keep_their_types(self) -> None:
        device_cv2 = FakeCv2([FakeCapture(opened=True)])
        with patch.object(source_module, "cv2", device_cv2):
            device = VideoSource({"source_type": "device", "camera_index": "2", "width": 0, "height": 0, "fps": 0})
            self.assertTrue(device.open(), device.last_error)
        self.assertEqual(device_cv2.sources, [2])
        self.assertIsInstance(device_cv2.sources[0], int)

        with tempfile.TemporaryDirectory() as temp_dir:
            video_path = Path(temp_dir) / "clip.mp4"
            video_path.touch()
            file_cv2 = FakeCv2([FakeCapture(opened=True)])
            with patch.object(source_module, "cv2", file_cv2):
                file_source = VideoSource({"source_type": "file", "video_file": video_path.name}, temp_dir)
                self.assertTrue(file_source.open(), file_source.last_error)
            self.assertEqual(file_cv2.sources, [str(video_path.resolve())])

    def test_open_read_failure_and_reconnect_are_non_crashing(self) -> None:
        throwing_cv2 = FakeCv2(open_error=RuntimeError("backend unavailable"))
        with patch.object(source_module, "cv2", throwing_cv2):
            source = VideoSource({"source_type": "rtsp", "rtsp_url": CAMERA_HUB_URL})
            self.assertFalse(source.open())
            self.assertIn("backend unavailable", source.last_error)

        first = FakeCapture(opened=True, reads=[RuntimeError("stream interrupted")])
        second = StreamingCapture()
        reconnect_cv2 = FakeCv2([first, second])
        with patch.object(source_module, "cv2", reconnect_cv2):
            source = VideoSource(
                {
                    "source_type": "rtsp",
                    "rtsp_url": CAMERA_HUB_URL,
                    "read_timeout_msec": 300,
                    "reconnect_interval_sec": 0.01,
                }
            )
            self.assertTrue(source.open(), source.last_error)
            ok, frame, error = source.read()
            self.assertTrue(ok, error)
            self.assertTrue(str(frame).startswith("frame-"))
            self.assertTrue(first.released)
            source.close()
        self.assertEqual(reconnect_cv2.sources, [CAMERA_HUB_URL, CAMERA_HUB_URL])

    def test_rotate_failure_returns_read_error_and_can_reconnect(self) -> None:
        first = FakeCapture(opened=True, reads=[(True, "frame-1")])
        second = FakeCapture(opened=True, reads=[(True, "frame-2")])
        fake_cv2 = FakeCv2([first, second], rotate_error=RuntimeError("rotate failed"))
        with patch.object(source_module, "cv2", fake_cv2):
            source = VideoSource(
                {
                    "source_type": "rtsp",
                    "rtsp_url": CAMERA_HUB_URL,
                    "rotate_180": True,
                    "read_timeout_msec": 50,
                    "reconnect_interval_sec": 1.0,
                }
            )
            self.assertTrue(source.open(), source.last_error)
            ok, frame, error = source.read()
            self.assertFalse(ok)
            self.assertIsNone(frame)
            self.assertTrue(error)

            source.close()
            fake_cv2.rotate_error = None
            self.assertTrue(source.open(), source.last_error)
            self.assertEqual(source.read(), (True, "frame-2", ""))
            source.close()

    def test_rtsp_sets_low_latency_buffer_and_timeouts(self) -> None:
        capture = StreamingCapture()
        fake_cv2 = FakeCv2([capture])
        with patch.object(source_module, "cv2", fake_cv2):
            source = VideoSource(
                {
                    "source_type": "rtsp",
                    "rtsp_url": CAMERA_HUB_URL,
                    "open_timeout_msec": 700,
                    "read_timeout_msec": 300,
                }
            )
            self.assertTrue(source.open(), source.last_error)
            source.close()

        self.assertEqual(fake_cv2.capture_args[0], (fake_cv2.CAP_FFMPEG, [7, 700, 8, 300]))
        self.assertIn((fake_cv2.CAP_PROP_BUFFERSIZE, 1), capture.properties)
        self.assertIn((fake_cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 700), capture.properties)
        self.assertIn((fake_cv2.CAP_PROP_READ_TIMEOUT_MSEC, 300), capture.properties)

    def test_rtsp_slow_consumer_gets_latest_single_slot_frame(self) -> None:
        capture = StreamingCapture(interval_sec=0.001)
        fake_cv2 = FakeCv2([capture])
        with patch.object(source_module, "cv2", fake_cv2):
            source = VideoSource(
                {"source_type": "rtsp", "rtsp_url": CAMERA_HUB_URL, "read_timeout_msec": 300}
            )
            self.assertTrue(source.open(), source.last_error)
            ok, _frame, first_meta, error = source.read_with_metadata()
            self.assertTrue(ok, error)
            time.sleep(0.04)
            ok, _frame, second_meta, error = source.read_with_metadata()
            self.assertTrue(ok, error)
            source.close()

        self.assertGreater(second_meta["source_frame_id"], first_meta["source_frame_id"] + 5)
        self.assertGreater(second_meta["dropped_source_frames"], 0)
        self.assertEqual(source._latest_frame, None)

    def test_close_unblocks_reader_and_joins_thread(self) -> None:
        capture = BlockingCapture()
        fake_cv2 = FakeCv2([capture])
        with patch.object(source_module, "cv2", fake_cv2):
            source = VideoSource({"source_type": "rtsp", "rtsp_url": CAMERA_HUB_URL})
            self.assertTrue(source.open(), source.last_error)
            self.assertTrue(capture.entered.wait(timeout=0.2))
            source.close()

        self.assertTrue(capture.released)
        self.assertIsNone(source._reader_thread)


if __name__ == "__main__":
    unittest.main()
