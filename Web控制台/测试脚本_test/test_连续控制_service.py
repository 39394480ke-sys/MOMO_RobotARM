"""Web 连续控制的轻量桥接与缓存状态测试。"""

from __future__ import annotations

import threading
import time
import types
import unittest
import tempfile
from pathlib import Path

import yaml

from Web测试路径_test_paths import WEB_ROOT
from backend.controller_bridge import ControllerBridge
from backend.schemas import ContinuousJogStartRequest, MotionTuningRequest
from backend.service import WebControlService


class FakeRealController:
    def __init__(self) -> None:
        self.connected = True
        self.stream_count = 0
        self.read_count = 0
        self.sync_count = 0

    def stream_joint_target(self, joint_key: str, target_deg: float, max_target_lead: float | None = None):
        self.stream_count += 1
        return types.SimpleNamespace(成功=True, 消息="已写入", 已写入=True, 目标raw=1234)

    def stream_joint_targets(self, targets_deg: dict[str, float]):
        self.stream_count += 1
        return types.SimpleNamespace(
            成功=True,
            消息="批量已写入",
            已写入关节=tuple(targets_deg),
            目标raw={joint: 1234 for joint in targets_deg},
        )

    def get_cached_state(self) -> dict:
        return self._state()

    def get_state(self) -> dict:
        self.read_count += 1
        return self._state()

    def sync_after_joint_stream(self):
        self.sync_count += 1
        return types.SimpleNamespace(成功=True, 消息="已同步")

    @staticmethod
    def _state() -> dict:
        return {
            "模式": "dry-run",
            "已连接": True,
            "关节角度": {"j10": 0.0, "j11": 1.25, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0},
            "目标关节角度": {"j11": 1.25},
            "目标raw": {"j11": 1234},
        }


class WebBridgeContinuousStreamTest(unittest.TestCase):
    def setUp(self) -> None:
        config = yaml.safe_load((WEB_ROOT / "Web配置.yaml").read_text(encoding="utf-8"))
        self.bridge = ControllerBridge(config, base_dir=WEB_ROOT)
        self.bridge.mode = "dry_run"
        self.bridge.connected = True
        self.fake = FakeRealController()
        self.bridge.controller = self.fake

    def test_stream_target_uses_lightweight_controller_api(self) -> None:
        result = self.bridge.stream_single_joint_target("j11", 1.25)

        self.assertTrue(result["ok"], result)
        self.assertTrue(result["data"]["write_performed"])
        self.assertEqual(self.fake.stream_count, 1)
        self.assertEqual(self.fake.read_count, 0)

    def test_batch_stream_uses_lightweight_controller_without_state_read(self) -> None:
        result = self.bridge.stream_joint_targets({"j11": 1.0, "j13": -1.0})

        self.assertTrue(result["ok"], result)
        self.assertEqual(set(result["data"]["written_joints"]), {"j11", "j13"})
        self.assertEqual(self.fake.stream_count, 1)
        self.assertEqual(self.fake.read_count, 0)

    def test_cached_state_and_finish_sync_do_not_use_full_move(self) -> None:
        cached = self.bridge.get_cached_state()
        synced = self.bridge.sync_after_joint_stream()

        self.assertTrue(cached["ok"], cached)
        self.assertAlmostEqual(cached["data"]["joints_deg"]["j11"], 1.25)
        self.assertTrue(synced["ok"], synced)
        self.assertEqual(self.fake.read_count, 0)
        self.assertEqual(self.fake.sync_count, 1)

    def test_legacy_horizon_request_is_ignored(self) -> None:
        request = MotionTuningRequest(continuous_update_hz=50.0, continuous_target_horizon_s=0.5)

        payload = request.model_dump(exclude_none=True) if hasattr(request, "model_dump") else request.dict(exclude_none=True)
        self.assertNotIn("continuous_target_horizon_s", payload)


class AliveThread:
    @staticmethod
    def is_alive() -> bool:
        return True


class CachedBridge:
    def __init__(self) -> None:
        self.cached_count = 0
        self.read_count = 0

    def get_cached_state(self) -> dict:
        self.cached_count += 1
        return {"ok": True, "message": "缓存", "data": {"joints_deg": {"j11": 2.0}}}

    def get_state(self) -> dict:
        self.read_count += 1
        return {"ok": True, "message": "真实", "data": {"joints_deg": {"j11": 1.0}}}


class WebServiceCachedStateTest(unittest.TestCase):
    def test_state_poll_uses_cached_target_while_jog_is_running(self) -> None:
        service = WebControlService.__new__(WebControlService)
        service._lock = threading.RLock()
        service.bridge = CachedBridge()
        service._continuous_jog_status = {"running": True}
        service._continuous_jog_thread = AliveThread()

        state = service.get_robot_state()

        self.assertEqual(state["joints_deg"]["j11"], 2.0)
        self.assertEqual(service.bridge.cached_count, 1)
        self.assertEqual(service.bridge.read_count, 0)

    def test_motion_tuning_save_removes_horizon_and_preserves_unrelated_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            web_dir = root / "Web控制台"
            gui_dir = root / "GUI图形界面"
            web_dir.mkdir()
            gui_dir.mkdir()
            for path in (web_dir / "Web配置.yaml", gui_dir / "GUI配置.yaml"):
                path.write_text(
                    yaml.safe_dump(
                        {
                            "motion": {
                                "continuous_update_hz": 50.0,
                                "continuous_target_horizon_s": 0.25,
                                "default_cartesian_step_mm": 5.0,
                            }
                        },
                        allow_unicode=True,
                    ),
                    encoding="utf-8",
                )
            service = WebControlService.__new__(WebControlService)
            service.base_dir = web_dir

            saved = service._persist_motion_tuning({"continuous_update_hz": 50.0})

            self.assertEqual(len(saved), 2)
            for path in (web_dir / "Web配置.yaml", gui_dir / "GUI配置.yaml"):
                motion = yaml.safe_load(path.read_text(encoding="utf-8"))["motion"]
                self.assertNotIn("continuous_target_horizon_s", motion)
                self.assertEqual(motion["default_cartesian_step_mm"], 5.0)


class NullLogger:
    def log(self, *args, **kwargs) -> None:
        return None


class StreamingBridge:
    mode = "dry_run"

    def __init__(self) -> None:
        self.target = 0.0
        self.stream_count = 0
        self.sync_count = 0
        self.max_target_leads: list[float | None] = []
        self.full_move_count = 0
        self.fail_after: int | None = None

    @staticmethod
    def is_connected() -> bool:
        return True

    def get_state(self) -> dict:
        return {"ok": True, "message": "状态", "data": {"joints_deg": {"j11": self.target}}}

    def get_cached_state(self) -> dict:
        return self.get_state()

    def stream_single_joint_target(
        self,
        joint_key: str,
        target_deg: float,
        max_target_lead: float | None = None,
    ) -> dict:
        self.target = float(target_deg)
        self.stream_count += 1
        self.max_target_leads.append(max_target_lead)
        if self.fail_after is not None and self.stream_count >= self.fail_after:
            return {"ok": False, "message": "模拟通信失败", "error": "模拟通信失败", "data": {}}
        return {
            "ok": True,
            "message": "流写入",
            "data": {"joint_key": joint_key, "target_deg": target_deg, "write_performed": True},
        }

    def move_single_joint_target(self, joint_key: str, target_deg: float) -> dict:
        self.full_move_count += 1
        return {"ok": True, "message": "完整移动", "data": {"target_deg": target_deg}}

    def sync_after_joint_stream(self) -> dict:
        self.sync_count += 1
        return {"ok": True, "message": "同步", "data": {}}


class WebServiceContinuousWorkerTest(unittest.TestCase):
    @staticmethod
    def make_service() -> WebControlService:
        service = WebControlService.__new__(WebControlService)
        service.config = {
            "safety": {"real_mode_requires_confirm": False, "max_manual_step_deg": 5.0},
            "motion": {"continuous_update_hz": 50.0},
        }
        service.bridge = StreamingBridge()
        service.logger = NullLogger()
        service._lock = threading.RLock()
        service._action_thread = None
        service._continuous_jog_thread = None
        service._continuous_jog_stop = threading.Event()
        service._continuous_jog_status = {"running": False}
        service.recent_error = None
        return service

    def test_worker_streams_lightweight_targets_and_syncs_once(self) -> None:
        service = self.make_service()

        service.start_continuous_jog(ContinuousJogStartRequest(joint_key="j11", direction=1, speed_deg_s=10.0))
        time.sleep(0.09)
        result = service.stop_continuous_jog(join_timeout=1.0)

        self.assertFalse(result["jog"]["running"])
        self.assertGreaterEqual(service.bridge.stream_count, 3)
        self.assertEqual(service.bridge.full_move_count, 0)
        self.assertTrue(all(lead == 0.3 for lead in service.bridge.max_target_leads))
        self.assertEqual(service.bridge.sync_count, 1)
        self.assertGreater(result["jog"]["actual_update_hz"], 0.0)
        self.assertIn("skipped_tick_count", result["jog"])
        self.assertIn("write_count", result["jog"])

    def test_target_lead_scales_with_requested_speed(self) -> None:
        slow = self.make_service()
        slow.start_continuous_jog(ContinuousJogStartRequest(joint_key="j11", direction=1, speed_deg_s=2.0))
        time.sleep(0.03)
        slow.stop_continuous_jog(join_timeout=1.0)

        fast = self.make_service()
        fast.start_continuous_jog(ContinuousJogStartRequest(joint_key="j11", direction=1, speed_deg_s=20.0))
        time.sleep(0.03)
        fast.stop_continuous_jog(join_timeout=1.0)

        self.assertTrue(all(lead == 0.06 for lead in slow.bridge.max_target_leads))
        self.assertTrue(all(lead == 0.6 for lead in fast.bridge.max_target_leads))

    def test_communication_failure_terminates_stream_and_still_syncs(self) -> None:
        service = self.make_service()
        service.bridge.fail_after = 2

        service.start_continuous_jog(ContinuousJogStartRequest(joint_key="j11", direction=1, speed_deg_s=10.0))
        service._continuous_jog_thread.join(timeout=1.0)
        status = service.continuous_jog_status()

        self.assertFalse(status["running"])
        self.assertIn("通信失败", status["message"])
        self.assertEqual(service.bridge.sync_count, 1)


if __name__ == "__main__":
    unittest.main()
