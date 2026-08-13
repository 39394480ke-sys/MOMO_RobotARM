"""动作卡片应显示回放估时，而不是只累计姿态停留时间。"""

import unittest

import 动作测试路径_test_paths  # noqa: F401

from 动作工具_common import estimate_sequence_duration, summarize_sequence_payload


class ActionEstimatedDurationTest(unittest.TestCase):
    def test_zero_recorded_duration_uses_real_minimum_and_distance(self) -> None:
        sequence = {
            "joint_order": ["j10", "j11"],
            "playback": {"default_duration_sec": 1.5, "default_interval_sec": 0.3},
            "poses": [
                {"duration_sec": 0.0, "hold_sec": 0.3, "joint_targets_deg": {"j10": -50, "j11": 0}},
                {"duration_sec": 0.0, "hold_sec": 0.3, "joint_targets_deg": {"j10": 50, "j11": 0}},
            ],
        }
        playback = {
            "real_mode_min_duration_sec": 2.0,
            "joint_speed_limits": {"j10": 20.0, "j11": 45.0},
        }

        self.assertAlmostEqual(estimate_sequence_duration(sequence, playback), 7.6)
        summary = summarize_sequence_payload(sequence, playback)
        self.assertEqual(summary["总时长"], 7.6)
        self.assertIn("不含前往首帧", summary["时长说明"])


if __name__ == "__main__":
    unittest.main()
