"""AI 待确认动作的过期、单次消费和状态漂移测试。"""

from __future__ import annotations

import unittest

from Web测试路径_test_paths import ensure_web_test_paths

ensure_web_test_paths()

from backend.agent_pending_action import PendingActionError, PendingActionStore


def snapshot(**joints: float) -> dict:
    return {"mode": "real", "connected": True, "joints": joints}


class PendingActionStoreTest(unittest.TestCase):
    def setUp(self) -> None:
        self.now = [100.0]
        self.store = PendingActionStore(ttl_sec=30.0, clock=lambda: self.now[0])

    def test_create_exposes_expiry_and_defensive_copy(self) -> None:
        action = self.store.create(
            "move_joint",
            {"joint_name": "j10", "target": 20.0},
            {"title": "移动 J10"},
            snapshot(j10=0.0),
        )

        self.assertEqual(action["expires_at"], 130.0)
        self.assertEqual(action["status"], "pending")
        self.assertGreaterEqual(len(action["id"]), 24)
        action["arguments"]["target"] = 99.0
        self.assertEqual(self.store.current()["arguments"]["target"], 20.0)

    def test_new_action_replaces_old_action(self) -> None:
        first = self.store.create("move_joint", {"joint_name": "j10"}, {}, snapshot(j10=0.0))
        second = self.store.create("move_joint", {"joint_name": "j11"}, {}, snapshot(j11=0.0))

        self.assertNotEqual(first["id"], second["id"])
        with self.assertRaises(PendingActionError) as error:
            self.store.consume(first["id"], snapshot(j10=0.0))
        self.assertEqual(error.exception.code, "AGENT_PENDING_ID_MISMATCH")

    def test_action_expires_after_thirty_seconds(self) -> None:
        self.store.create("move_joint", {"joint_name": "j10"}, {}, snapshot(j10=0.0))
        self.now[0] = 131.0

        self.assertIsNone(self.store.current())
        with self.assertRaises(PendingActionError) as error:
            self.store.consume("missing", snapshot(j10=0.0))
        self.assertEqual(error.exception.code, "AGENT_PENDING_EXPIRED")

    def test_wrong_id_does_not_consume_current_action(self) -> None:
        action = self.store.create("move_joint", {"joint_name": "j10"}, {}, snapshot(j10=0.0))

        with self.assertRaises(PendingActionError) as error:
            self.store.consume("wrong-id", snapshot(j10=0.0))

        self.assertEqual(error.exception.code, "AGENT_PENDING_ID_MISMATCH")
        self.assertEqual(self.store.current()["id"], action["id"])

    def test_action_is_single_use_even_if_execution_later_fails(self) -> None:
        action = self.store.create("move_joint", {"joint_name": "j12"}, {}, snapshot(j12=0.0))

        consumed = self.store.consume(action["id"], snapshot(j12=0.0))

        self.assertEqual(consumed["status"], "executed")
        with self.assertRaises(PendingActionError) as error:
            self.store.consume(action["id"], snapshot(j12=0.0))
        self.assertEqual(error.exception.code, "AGENT_PENDING_NOT_FOUND")

    def test_mode_connection_and_joint_drift_invalidate_action(self) -> None:
        cases = [
            ({"mode": "dry_run", "connected": True, "joints": {"j11": 0.0}}, "控制模式"),
            ({"mode": "real", "connected": False, "joints": {"j11": 0.0}}, "连接状态"),
            (snapshot(j11=0.51), "位置已变化"),
        ]
        for current, message in cases:
            with self.subTest(message=message):
                store = PendingActionStore(clock=lambda: 100.0)
                action = store.create("move_joint", {"joint_name": "j11"}, {}, snapshot(j11=0.0))
                with self.assertRaisesRegex(PendingActionError, message) as error:
                    store.consume(action["id"], current)
                self.assertEqual(error.exception.code, "AGENT_PENDING_STATE_CHANGED")

    def test_j10_uses_half_millimetre_drift_tolerance(self) -> None:
        action = self.store.create("move_joint", {"joint_name": "j10"}, {}, snapshot(j10=0.0))

        self.store.consume(action["id"], snapshot(j10=0.5))

    def test_home_compares_every_snapshotted_joint(self) -> None:
        action = self.store.create("run_robot_behavior", {"name": "home"}, {}, snapshot(j10=0.0, j12=1.0))

        with self.assertRaises(PendingActionError):
            self.store.consume(action["id"], snapshot(j10=0.0, j12=1.51))

    def test_joint_plan_compares_every_planned_joint(self) -> None:
        action = self.store.create(
            "move_joint_plan",
            {"moves": [{"joint_name": "j10"}, {"joint_name": "j11"}]},
            {},
            snapshot(j10=0.0, j11=0.0, j12=8.0),
        )

        with self.assertRaisesRegex(PendingActionError, "J11 位置已变化"):
            self.store.consume(action["id"], snapshot(j10=0.0, j11=0.51, j12=99.0))

    def test_invalidate_removes_current_action(self) -> None:
        self.store.create("move_joint", {"joint_name": "j10"}, {}, snapshot(j10=0.0))

        invalidated = self.store.invalidate("emergency_stop")

        self.assertEqual(invalidated["status"], "invalidated")
        self.assertEqual(invalidated["reason"], "emergency_stop")
        self.assertIsNone(self.store.current())


if __name__ == "__main__":
    unittest.main()
