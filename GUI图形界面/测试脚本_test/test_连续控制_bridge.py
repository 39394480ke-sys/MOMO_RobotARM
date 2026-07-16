"""GUI 连续控制应使用轻量位置流。"""

from __future__ import annotations

import threading
import time
import types
import unittest

import yaml

from GUI测试路径_test_paths import GUI_ROOT
from gui_app.控制器桥接_controller_bridge import ControllerBridge


class FakeController:
    def __init__(self) -> None:
        self.connected = True
        self.target = 0.0
        self.stream_count = 0
        self.full_move_count = 0
        self.read_count = 0
        self.sync_count = 0

    def get_state(self) -> dict:
        self.read_count += 1
        return {
            "模式": "dry-run",
            "已连接": True,
            "关节角度": {"j10": 0.0, "j11": self.target, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0},
            "目标关节角度": {"j11": self.target},
            "目标raw": {},
        }

    def stream_joint_target(self, joint_key: str, target_deg: float):
        self.target = float(target_deg)
        self.stream_count += 1
        return types.SimpleNamespace(成功=True, 消息="已写入", 已写入=True, 目标raw=1234)

    def move_joints(self, targets: dict):
        self.full_move_count += 1
        return types.SimpleNamespace(成功=True, 消息="完整移动")

    def sync_after_joint_stream(self):
        self.sync_count += 1
        return types.SimpleNamespace(成功=True, 消息="已同步")


class GuiContinuousStreamTest(unittest.TestCase):
    def test_hold_uses_lightweight_stream_and_syncs_once(self) -> None:
        config = yaml.safe_load((GUI_ROOT / "GUI配置.yaml").read_text(encoding="utf-8"))
        bridge = ControllerBridge(config, base_dir=GUI_ROOT)
        bridge.mode = "dry_run"
        bridge.connected = True
        fake = FakeController()
        bridge.controller = fake
        result_box: list[dict] = []

        thread = threading.Thread(target=lambda: result_box.append(bridge.start_continuous_jog("j11", 1, 10.0)))
        thread.start()
        time.sleep(0.09)
        bridge.stop_continuous_jog()
        thread.join(timeout=1.0)

        self.assertFalse(thread.is_alive())
        self.assertTrue(result_box[0]["ok"], result_box[0])
        data = result_box[0]["data"]
        self.assertGreaterEqual(fake.stream_count, 3)
        self.assertEqual(fake.full_move_count, 0)
        self.assertEqual(fake.sync_count, 1)
        self.assertGreater(data["actual_update_hz"], 0.0)
        self.assertIn("skipped_tick_count", data)
        self.assertNotIn("horizon_s", data)


if __name__ == "__main__":
    unittest.main()
