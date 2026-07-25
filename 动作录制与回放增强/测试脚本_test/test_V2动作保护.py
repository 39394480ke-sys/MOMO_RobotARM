from __future__ import annotations

import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

TEST_DIR = Path(__file__).resolve().parent
ACTION_ROOT = TEST_DIR.parent
PROJECT_ROOT = ACTION_ROOT.parent
WEB_ROOT = PROJECT_ROOT / "Web控制台"
GUI_ROOT = PROJECT_ROOT / "GUI图形界面"
VISION_ROOT = PROJECT_ROOT / "视觉识别与跟随"
for import_path in (PROJECT_ROOT, ACTION_ROOT, WEB_ROOT, GUI_ROOT, VISION_ROOT):
    if str(import_path) not in sys.path:
        sys.path.insert(0, str(import_path))

from backend.controller_bridge import ControllerBridge as WebControllerBridge
from gui_app.控制器桥接_controller_bridge import ControllerBridge as GuiControllerBridge
from 控制桥接_common import (
    build_recording_sequence,
    load_action_library,
    load_action_recorder,
    load_sim_controller,
    load_sequence_player,
)
from 动作回放器_sequence_player import SequencePlayer
from 动作工具_common import (
    SCHEMA_VERSION,
    action_variant_report,
    build_empty_sequence,
    is_dry_run_controller,
)
from 动作录制器_action_recorder import ActionRecorder
from 动作文件管理_action_library import ActionLibrary
from 通用_io import read_structured
from 运镜导演_cinematic_director import CinematicDirector


JOINTS = [f"j{index}" for index in range(10, 16)]


def action_config(variant: str = "V2") -> dict[str, object]:
    return {
        "robot": {
            "variant": variant,
            "sdk_joint_names": list(JOINTS),
            "multi_turn_joints": list(JOINTS),
        },
        "files": {
            "action_library_dir": "actions",
            "record_dir": "recordings",
            "runtime_log": "runtime.log",
        },
        "recording": {"include_tcp_pose": False, "recorded_pose_duration_sec": 0.0},
        "playback": {
            "default_duration_sec": 0.0,
            "default_interval_sec": 0.0,
            "update_hz": 1.0,
            "continuous_interpolation_default": False,
            "synchronized_segment_timing": False,
            "return_to_first_pose_before_replay": False,
            "auto_duration_from_distance": False,
        },
        "safety": {
            "max_single_step_deg": 180.0,
            "real_mode_max_single_step_deg": 180.0,
            "require_confirm_before_real_replay": False,
        },
    }


def sequence_for(robot_variant: object = "V2") -> dict[str, object]:
    sequence = {
        "schema_version": SCHEMA_VERSION,
        "name": "synthetic-action",
        "joint_order": list(JOINTS),
        "poses": [
            {
                "index": 1,
                "joint_targets_deg": {joint: 0.0 for joint in JOINTS},
                "duration_sec": 0.0,
                "hold_sec": 0.0,
            }
        ],
    }
    if robot_variant is not None:
        sequence["robot_variant"] = robot_variant
    return sequence


class FakeController:
    def __init__(self, dry_run: bool):
        self._dry_run = dry_run
        self.moves: list[dict[str, float]] = []

    def is_dry_run(self) -> bool:
        return self._dry_run

    def get_state(self) -> dict[str, object]:
        return {"joint_state": {joint: 0.0 for joint in JOINTS}}

    def move_joints(self, target: dict[str, float], **kwargs: object) -> bool:
        self.moves.append(dict(target))
        return True


class MissingModeController:
    def __init__(self, mode: str | None = None):
        self.mode = mode
        self.moves: list[dict[str, float]] = []

    def get_state(self) -> dict[str, object]:
        return {"joint_state": {joint: 0.0 for joint in JOINTS}}

    def move_joints(self, target: dict[str, float], **kwargs: object) -> bool:
        self.moves.append(dict(target))
        return True


class ThrowingModeController(MissingModeController):
    def is_dry_run(self) -> bool:
        raise RuntimeError("mode unavailable")


class V2ActionProtectionTests(unittest.TestCase):
    def test_only_trusted_producers_stamp_active_variant_and_generic_save_preserves_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = action_config("V2")
            sequence = build_empty_sequence("recorded", config=config)
            sequence["poses"] = sequence_for()["poses"]
            self.assertEqual(sequence["robot_variant"], "V2")

            library = ActionLibrary(config=config, library_dir=root / "actions")
            exact_path = library.save_action("exact", sequence)
            self.assertEqual(read_structured(exact_path)["robot_variant"], "V2")

            for name, variant in (("missing", None), ("mismatch", "V1"), ("unknown", "V3")):
                source = sequence_for(variant)
                saved_path = library.save_action(name, source)
                self.assertEqual(read_structured(saved_path).get("robot_variant"), variant)
                controller = FakeController(dry_run=False)
                player = SequencePlayer(controller, config)
                loaded = library.load_action(name)
                with self.assertRaises(ValueError):
                    player.play(loaded)
                self.assertEqual(controller.moves, [])

            recorder = ActionRecorder(FakeController(dry_run=True), config)
            direct_path = root / "direct.json"
            recorder.save_sequence(sequence_for(None), direct_path)
            self.assertEqual(read_structured(direct_path)["robot_variant"], "V2")
            with self.assertRaisesRegex(ValueError, "不匹配"):
                recorder.save_sequence(sequence_for("V1"), root / "wrong-direct.json")

            single_path = root / "single.json"
            recorded = recorder.record_pose_sequence(1, single_path, wait_for_enter=False)
            self.assertEqual(recorded["robot_variant"], "V2")
            self.assertEqual(read_structured(single_path)["robot_variant"], "V2")

            imported_source = root / "legacy-import.json"
            imported_source.write_text(json.dumps(sequence_for("V1"), ensure_ascii=False), encoding="utf-8")
            imported_path = library.import_action(imported_source)
            self.assertEqual(read_structured(imported_path)["robot_variant"], "V1")

            director = CinematicDirector(root)
            cinematic = director.build_action_payload(
                "cinematic-v1",
                {"director_keyframes": []},
                {"key_points": []},
                config=action_config("V1"),
            )
            self.assertEqual(cinematic["robot_variant"], "V1")

    def test_real_replay_matrix_rejects_before_any_controller_movement(self) -> None:
        cases = (
            ("exact", "V2", True, ""),
            ("mismatch", "V1", False, "不匹配"),
            ("missing", None, False, "缺少"),
            ("unknown", "V3", False, "未知"),
        )
        for name, variant, allowed, message in cases:
            with self.subTest(case=name):
                controller = FakeController(dry_run=False)
                player = SequencePlayer(controller, action_config("V2"))
                sequence = sequence_for(variant)
                if allowed:
                    self.assertTrue(player.play(sequence))
                    self.assertTrue(controller.moves)
                else:
                    with self.assertRaisesRegex(ValueError, message):
                        player.play(sequence)
                    self.assertEqual(controller.moves, [])

    def test_dry_run_loads_all_variants_as_labeled_preview_without_rewriting(self) -> None:
        cases = (
            ("exact", "V2", "exact"),
            ("mismatch", "V1", "mismatch"),
            ("missing", None, "missing"),
            ("unknown", "V3", "unknown"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            library = ActionLibrary(config=action_config("V2"), library_dir=root)
            player = SequencePlayer(FakeController(dry_run=True), action_config("V2"))
            for name, variant, status in cases:
                with self.subTest(case=name):
                    path = root / f"{name}.json"
                    original = sequence_for(variant)
                    path.write_text(json.dumps(original, ensure_ascii=False), encoding="utf-8")
                    loaded = library.load_action(name)
                    self.assertEqual(loaded["_robot_variant_preview"]["状态"], status)
                    self.assertEqual(loaded.get("robot_variant"), variant)
                    self.assertEqual(read_structured(path), original)
                    self.assertTrue(player.play(loaded))
                    self.assertEqual(player.last_variant_report["状态"], status)

    def test_real_load_sequence_rejects_variant_before_replay(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "legacy.json"
            path.write_text(json.dumps(sequence_for(None), ensure_ascii=False), encoding="utf-8")
            controller = FakeController(dry_run=False)
            player = SequencePlayer(controller, action_config("V2"))
            with self.assertRaisesRegex(ValueError, "缺少"):
                player.load_sequence(path)
            self.assertEqual(controller.moves, [])

    def test_replay_mode_detection_fails_closed_except_explicit_preview_modes(self) -> None:
        unsafe_controllers = (
            MissingModeController(),
            MissingModeController(mode="mystery"),
            ThrowingModeController(mode="simulation"),
        )
        for controller in unsafe_controllers:
            with self.subTest(controller=type(controller).__name__, mode=controller.mode):
                self.assertFalse(is_dry_run_controller(controller))
                player = SequencePlayer(controller, action_config("V2"))
                with self.assertRaisesRegex(ValueError, "不匹配"):
                    player.play(sequence_for("V1"))
                self.assertEqual(controller.moves, [])

        explicit_sim = MissingModeController(mode="simulation")
        self.assertTrue(is_dry_run_controller(explicit_sim))
        self.assertTrue(SequencePlayer(explicit_sim, action_config("V2")).play(sequence_for("V1")))
        self.assertTrue(explicit_sim.moves)

    def test_production_sim_controller_explicitly_allows_variant_preview(self) -> None:
        controller = load_sim_controller(PROJECT_ROOT / "仿真控制系统" / "配置_config.yaml")
        self.assertIs(controller.is_simulation, True)
        self.assertTrue(is_dry_run_controller(controller))
        player = SequencePlayer(controller, action_config("V2"))
        self.assertTrue(player.play(sequence_for("V1")))
        self.assertEqual(player.last_variant_report["状态"], "mismatch")

    def test_action_variant_report_requires_known_active_and_action_variants(self) -> None:
        self.assertEqual(action_variant_report(sequence_for("V2"), action_config("V2"))["状态"], "exact")
        self.assertEqual(action_variant_report(sequence_for("V1"), action_config("V2"))["状态"], "mismatch")
        self.assertEqual(action_variant_report(sequence_for(None), action_config("V2"))["状态"], "missing")
        self.assertEqual(action_variant_report(sequence_for("V3"), action_config("V2"))["状态"], "unknown")
        with self.assertRaisesRegex(ValueError, "V1.*V2"):
            build_empty_sequence("bad-active", config=action_config("V3"))

    def test_common_gui_web_helpers_propagate_active_profile_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_path = root / "real.json"
            real_path.write_text(
                json.dumps(
                    {
                        "transport": {"dry_run": True, "port": ""},
                        "robot": {"variant": "V1", "joints": []},
                    }
                ),
                encoding="utf-8",
            )
            action_path = ACTION_ROOT / "动作配置.yaml"

            sequence = build_recording_sequence(
                "bridge-record",
                "test",
                action_path,
                real_config_path=real_path,
            )
            self.assertEqual(sequence["robot_variant"], "V1")

            controller = FakeController(dry_run=True)
            library = load_action_library(action_path, real_config_path=real_path)
            player = load_sequence_player(controller, action_path, real_config_path=real_path)
            recorder = load_action_recorder(controller, action_path, real_config_path=real_path)
            self.assertEqual(library.config["robot"]["variant"], "V1")
            self.assertEqual(player.config["robot"]["variant"], "V1")
            self.assertEqual(recorder.config["robot"]["variant"], "V1")

            gui_bridge = GuiControllerBridge.__new__(GuiControllerBridge)
            gui_bridge.io_lock = threading.RLock()
            gui_bridge.recording_sequence = None
            gui_bridge.recording_name = ""
            gui_bridge.recording_source = "gui_record"
            gui_bridge._resolve_config = lambda key: action_path if key == "action_config_path" else real_path
            gui_bridge._ensure_controller = lambda: None
            gui_bridge._log = lambda *args, **kwargs: None
            gui_bridge._exception = lambda message, exc: {"ok": False, "message": f"{message}：{exc}"}
            gui_result = gui_bridge.start_action_recording("gui-v1")
            self.assertTrue(gui_result["ok"], gui_result)
            self.assertEqual(gui_bridge.recording_sequence["robot_variant"], "V1")
            self.assertEqual(gui_result["data"]["recording"]["robot_variant"], "V1")

            web_bridge = WebControllerBridge.__new__(WebControllerBridge)
            web_bridge.recording_sequence = None
            web_bridge.recording_name = ""
            web_bridge.recording_source = "web_record"
            web_bridge._resolve_config = lambda key: action_path if key == "action_config_path" else real_path
            web_bridge._ensure_controller = lambda: None
            web_bridge._set_action_status = lambda *args: None
            web_bridge._log = lambda *args, **kwargs: None
            web_bridge._exception = lambda message, exc: {"ok": False, "message": f"{message}：{exc}"}
            web_result = web_bridge.start_action_recording("web-v1")
            self.assertTrue(web_result["ok"], web_result)
            self.assertEqual(web_bridge.recording_sequence["robot_variant"], "V1")
            self.assertEqual(web_result["data"]["recording"]["robot_variant"], "V1")

    def test_web_bridge_validates_action_before_connected_motion_guard(self) -> None:
        bridge = WebControllerBridge.__new__(WebControllerBridge)
        events: list[str] = []
        bridge.controller = FakeController(dry_run=False)
        bridge.action_status = {"state": "idle", "name": "", "message": "", "started_at": None}
        bridge.last_error = ""
        bridge._ensure_controller = lambda: events.append("controller")
        bridge._get_action_library = lambda: object()
        bridge._get_sequence_player = lambda: object()
        bridge._ensure_connected_for_motion = lambda: events.append("connected_guard")
        bridge._set_action_status = lambda *args: events.append(f"status:{args[0]}")
        bridge._log = lambda *args, **kwargs: None
        bridge._exception = lambda message, exc: {"ok": False, "message": f"{message}：{exc}"}

        with patch(
            "backend.controller_bridge.load_action_for_replay",
            side_effect=lambda *args, **kwargs: events.append("variant_guard") or sequence_for("V2"),
        ), patch(
            "backend.controller_bridge.play_loaded_action",
            side_effect=lambda *args, **kwargs: events.append("play") or True,
        ):
            result = bridge.play_action("demo")

        self.assertTrue(result["ok"], result)
        self.assertLess(events.index("variant_guard"), events.index("connected_guard"))
        self.assertLess(events.index("connected_guard"), events.index("play"))

    def test_tracked_legacy_actions_are_explicitly_marked_v1(self) -> None:
        paths = (
            ACTION_ROOT / "动作库_测试备份_不要真实运行" / "我的测试动作.json",
            ACTION_ROOT / "动作库_示例备份_不要真实运行" / "展示动作_增强.json",
            ACTION_ROOT / "动作库_示例备份_不要真实运行" / "挥手_增强.json",
            ACTION_ROOT / "动作库_示例备份_不要真实运行" / "示例_录制动作.json",
            ACTION_ROOT / "录制记录" / "recorded_pose_sequence.json",
        )
        for path in paths:
            with self.subTest(path=path.name):
                payload = read_structured(path)
                self.assertEqual(payload["robot_variant"], "V1")
                self.assertEqual(payload["schema_version"], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
