"""部分关节目标不得把未指定关节隐式补零。"""

from __future__ import annotations

import unittest

from Web测试路径_test_paths import WEB_ROOT  # noqa: F401
from backend.controller_bridge import ControllerBridge


class FakeController:
    def __init__(self) -> None:
        self.received: dict[str, float] | None = None

    def move_joints(self, targets: dict[str, float]) -> dict:
        self.received = dict(targets)
        return {"ok": True, "message": "ok", "data": {}}


class PartialJointTargetSafetyTest(unittest.TestCase):
    def test_partial_mapping_only_reaches_the_requested_joint(self) -> None:
        bridge = object.__new__(ControllerBridge)
        bridge.mode = "real"
        bridge.controller = FakeController()
        bridge._ensure_connected_for_motion = lambda: None
        bridge._ensure_controller = lambda: None
        bridge._log = lambda *args, **kwargs: None

        result = bridge.move_joints({"j12": 7.0})

        self.assertTrue(result["ok"])
        self.assertEqual(bridge.controller.received, {"j12": 7.0})


if __name__ == "__main__":
    unittest.main()
