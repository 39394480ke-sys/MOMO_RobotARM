from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PROFILE_DIR = PROJECT_ROOT / "配置"
KINEMATICS_DIR = PROJECT_ROOT / "URDF运动学仿真"
ACTION_DIR = PROJECT_ROOT / "动作录制与回放增强"
INTEGRATION_DIR = PROJECT_ROOT / "系统集成"
GUI_DIR = PROJECT_ROOT / "GUI图形界面"
WEB_DIR = PROJECT_ROOT / "Web控制台"
REAL_DIR = PROJECT_ROOT / "真实舵机控制"
for path in (PROJECT_ROOT, KINEMATICS_DIR, ACTION_DIR, INTEGRATION_DIR, GUI_DIR, WEB_DIR, REAL_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from 动作工具_common import load_config as load_action_config
from integration.config_loader import ConfigLoader
from URDF检查_urdf_inspector import 检查URDF
from 运动学模型_kinematics_model import 创建运动学模型, 加载运动学配置
from 真实配置加载_real_config_loader import load_real_config
from 真实机械臂控制器_real_arm_controller import RealArmController
from 通用_io import read_structured
from 控制桥接_common import (
    build_recording_sequence,
    load_action_library,
    load_action_recorder,
    load_kinematics_model,
    load_sequence_player,
    targets_to_kinematics_q,
)


JOINTS = ["j10", "j11", "j12", "j13", "j14", "j15"]
LIMITS = {
    "j10": [-360.0, 360.0],
    "j11": [-360.0, 360.0],
    "j12": [-360.0, 360.0],
    "j13": [-360.0, 360.0],
    "j14": [-360.0, 360.0],
    "j15": [-360.0, 360.0],
}
EXPECTED = {
    "V1": {
        "name": "soarmmoce_with_linear_rail",
        "urdf": "urdf/v1/soarmoce_urdf.urdf",
        "target": "Link_6",
        "kinematics": {"j10": 1.0, "j11": 1.0, "j12": -1.0, "j13": 1.0, "j14": -1.0, "j15": 1.0},
        "hardware": {"j10": 28.8, "j11": 5.0, "j12": -5.3, "j13": 5.6, "j14": 1.0, "j15": 1.0},
        "raw_reachable": [],
    },
    "V2": {
        "name": "momo_robot_arm_v2",
        "urdf": "urdf/v2/soarmoce_urdf.urdf",
        "target": "Link_7",
        "kinematics": {joint: 1.0 for joint in JOINTS},
        "hardware": {"j10": 28.8, "j11": 5.0, "j12": -28.0, "j13": 14.0, "j14": 1.0, "j15": 1.0},
        "raw_reachable": ["j12", "j13"],
    },
}
EXPECTED_MESHES = {
    "V1": [
        "Link_1.stl",
        "Link_2.stl",
        "Link_3.stl",
        "Link_4.stl",
        "Link_5.stl",
        "Link_6.stl",
        "base_link.stl",
    ],
    "V2": [
        "Link_2.stl",
        "Link_3.stl",
        "Link_4.stl",
        "Link_5.stl",
        "Link_6.stl",
        "Link_7.stl",
        "base_link.stl",
    ],
}


def write_real_config(path: Path, variant: str | None) -> Path:
    robot: dict[str, object] = {
        "joint_order": list(JOINTS),
        "joints": [
            {
                "key": joint,
                "舵机ID": int(joint[1:]),
                "模式": "多圈",
                "默认角度": 0,
                "最小角度": -999,
                "最大角度": 999,
            }
            for joint in JOINTS
        ],
    }
    if variant is not None:
        robot["variant"] = variant
    path.write_text(
        json.dumps(
            {
                "transport": {"port": "", "driver_backend": "sdk", "dry_run": True},
                "robot": robot,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return path


class RobotProfileTests(unittest.TestCase):
    def test_profile_files_have_complete_valid_schema(self) -> None:
        for variant in ("V1", "V2"):
            with self.subTest(variant=variant):
                path = PROFILE_DIR / f"robot_{variant.lower()}.yaml"
                self.assertTrue(path.is_file(), path)
                profile = read_structured(path)
                self.assertEqual(profile["robot"]["variant"], variant)
                self.assertEqual(profile["robot"]["name"], EXPECTED[variant]["name"])
                self.assertEqual(profile["kinematics"]["urdf_path"], EXPECTED[variant]["urdf"])
                self.assertEqual(profile["kinematics"]["target_frame"], EXPECTED[variant]["target"])
                self.assertEqual(profile["kinematics"]["joint_scales"], EXPECTED[variant]["kinematics"])
                self.assertEqual(profile["hardware"]["joint_scales"], EXPECTED[variant]["hardware"])
                self.assertEqual(profile["hardware"]["joint_limits"], LIMITS)
                self.assertEqual(profile["hardware"]["raw_reachable_joints"], EXPECTED[variant]["raw_reachable"])

    def test_profile_loader_accepts_only_exact_known_variants(self) -> None:
        from 机器人配置_profile_loader import load_robot_profile

        for variant in ("V1", "V2"):
            with self.subTest(variant=variant):
                profile = load_robot_profile(variant)
                self.assertEqual(profile["robot"]["variant"], variant)
                self.assertEqual(profile["robot"]["name"], EXPECTED[variant]["name"])
                self.assertEqual(profile["kinematics"]["urdf_path"], EXPECTED[variant]["urdf"])
                self.assertEqual(profile["kinematics"]["target_frame"], EXPECTED[variant]["target"])
                self.assertEqual(profile["kinematics"]["joint_scales"], EXPECTED[variant]["kinematics"])
                self.assertEqual(profile["hardware"]["joint_scales"], EXPECTED[variant]["hardware"])
                self.assertEqual(profile["hardware"]["joint_limits"], LIMITS)
                self.assertEqual(profile["hardware"]["raw_reachable_joints"], EXPECTED[variant]["raw_reachable"])
        for invalid in (None, "", "v1", "v2", "V3", " V2 "):
            with self.subTest(invalid=invalid), self.assertRaisesRegex(ValueError, "variant"):
                load_robot_profile(invalid)

    def test_real_loader_applies_local_variant_then_profile_authority_then_transport_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = write_real_config(root / "真实配置.yaml", "V2")
            (root / "真实配置.local.yaml").write_text(
                json.dumps(
                    {
                        "robot": {
                            "variant": "V1",
                            "name": "forged",
                            "joint_scales": {joint: 999 for joint in JOINTS},
                            "关节减速比_joint_scales": {joint: 888 for joint in JOINTS},
                            "raw_reachable_joints": list(JOINTS),
                            "joints": [
                                {"key": joint, "最小角度": -1, "最大角度": 1}
                                for joint in JOINTS
                            ],
                        },
                        "hardware": {
                            "joint_scales": {joint: 777 for joint in JOINTS},
                            "joint_limits": {joint: [-2, 2] for joint in JOINTS},
                            "raw_reachable_joints": list(JOINTS),
                        },
                        "transport": {"port": "/tmp/local-port"},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            environment = {
                "ARM_ROBOT_PORT": "/tmp/env-port",
                "ARM_SERVO_BACKEND": "lerobot",
                "ARM_REAL_DRY_RUN": "true",
                "ARM_ROBOT_VARIANT": "V2",
            }

            with patch.dict(os.environ, environment, clear=True):
                config = load_real_config(config_path)

            expected = EXPECTED["V1"]
            self.assertEqual(config["robot"]["variant"], "V1")
            self.assertEqual(config["robot"]["name"], expected["name"])
            self.assertEqual(config["robot"]["joint_scales"], expected["hardware"])
            self.assertEqual(config["robot"]["关节减速比_joint_scales"], expected["hardware"])
            self.assertEqual(config["robot"]["joint_limits"], LIMITS)
            self.assertEqual(config["robot"]["raw_reachable_joints"], [])
            self.assertEqual(config["hardware"]["joint_scales"], expected["hardware"])
            self.assertEqual(config["hardware"]["joint_limits"], LIMITS)
            self.assertEqual(config["hardware"]["raw_reachable_joints"], [])
            self.assertEqual(
                {joint["key"]: [joint["最小角度"], joint["最大角度"]] for joint in config["robot"]["joints"]},
                LIMITS,
            )
            self.assertEqual(config["transport"]["port"], "/tmp/env-port")
            self.assertEqual(config["transport"]["driver_backend"], "lerobot")
            self.assertTrue(config["transport"]["dry_run"])

    def test_missing_or_invalid_effective_real_variant_is_rejected(self) -> None:
        for variant in (None, "", "v2", "V3"):
            with self.subTest(variant=variant), tempfile.TemporaryDirectory() as tmp:
                config_path = write_real_config(Path(tmp) / "真实配置.yaml", variant)
                with patch.dict(os.environ, {}, clear=True), self.assertRaisesRegex(ValueError, "variant"):
                    load_real_config(config_path)

    def test_local_cannot_remove_or_truncate_canonical_joint_entries(self) -> None:
        overrides = (
            {"robot": {"joints": []}},
            {
                "robot": {
                    "joints": [
                        {
                            "key": "j12",
                            "舵机ID": 99,
                            "模式": "单圈",
                            "最小角度": -1,
                            "最大角度": 1,
                        }
                    ]
                }
            },
        )
        for override in overrides:
            with self.subTest(override=override), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                config_path = write_real_config(root / "真实配置.yaml", "V2")
                (root / "真实配置.local.yaml").write_text(
                    json.dumps(override, ensure_ascii=False),
                    encoding="utf-8",
                )

                with patch.dict(os.environ, {"ARM_REAL_DRY_RUN": "true"}, clear=True):
                    config = load_real_config(config_path)
                    controller = RealArmController(config_path)

                self.assertEqual(config["robot"]["joint_order"], JOINTS)
                self.assertEqual([joint["key"] for joint in config["robot"]["joints"]], JOINTS)
                by_key = {joint["key"]: joint for joint in config["robot"]["joints"]}
                self.assertEqual(by_key["j12"]["舵机ID"], 12)
                self.assertEqual(by_key["j12"]["模式"], "多圈")
                self.assertEqual(
                    [by_key["j12"]["最小角度"], by_key["j12"]["最大角度"]],
                    LIMITS["j12"],
                )
                self.assertEqual(
                    [by_key["j14"]["最小角度"], by_key["j14"]["最大角度"]],
                    LIMITS["j14"],
                )
                self.assertEqual(by_key["j14"]["舵机ID"], 14)
                self.assertEqual(
                    [
                        controller.joint_config_by_key["j12"]["最小角度"],
                        controller.joint_config_by_key["j12"]["最大角度"],
                    ],
                    LIMITS["j12"],
                )
                self.assertEqual(
                    [
                        controller.joint_config_by_key["j14"]["最小角度"],
                        controller.joint_config_by_key["j14"]["最大角度"],
                    ],
                    LIMITS["j14"],
                )

    def test_four_loaders_share_the_same_selected_variant(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_path = write_real_config(root / "真实配置.yaml", "V1")
            system_path = root / "总配置.yaml"
            system_path.write_text(
                "hardware:\n"
                f"  real_config_path: {real_path}\n",
                encoding="utf-8",
            )
            with patch.dict(os.environ, {}, clear=True):
                real = load_real_config(real_path)
                kinematics = 加载运动学配置(real_config_path=real_path)
                action = load_action_config(real_config_path=real_path)
                integration = ConfigLoader(system_path).load()

            self.assertEqual(real["robot"]["variant"], "V1")
            self.assertEqual(kinematics["robot"]["variant"], "V1")
            self.assertEqual(kinematics["robot"]["name"], EXPECTED["V1"]["name"])
            self.assertEqual(kinematics["robot"]["urdf_path"], EXPECTED["V1"]["urdf"])
            self.assertEqual(kinematics["robot"]["target_frame"], EXPECTED["V1"]["target"])
            self.assertEqual(kinematics["robot"]["joint_scales"], EXPECTED["V1"]["kinematics"])
            self.assertEqual(kinematics["kinematics"]["joint_scales"], EXPECTED["V1"]["kinematics"])
            self.assertEqual(action["robot"]["variant"], "V1")
            self.assertEqual(action["hardware"]["robot_variant"], "V1")
            self.assertEqual(integration["robot"]["variant"], "V1")
            self.assertEqual(integration["hardware"]["robot_variant"], "V1")

    def test_tracked_real_config_has_safe_v2_baseline(self) -> None:
        raw = read_structured(REAL_DIR / "真实配置.yaml")
        self.assertEqual(raw["robot"]["variant"], "V2")
        self.assertEqual(raw["transport"]["port"], "")
        self.assertTrue(raw["transport"]["dry_run"])
        self.assertNotIn("joint_scales", raw["robot"])
        self.assertNotIn("关节减速比_joint_scales", raw["robot"])

    def test_inspector_parses_both_profile_urdfs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant in ("V1", "V2"):
                with self.subTest(variant=variant):
                    real_path = write_real_config(root / f"real_{variant}.yaml", variant)
                    report = 检查URDF(real_config_path=real_path)
                    self.assertTrue(report["ok"], report["errors"])
                    self.assertEqual(report["target_frame"], EXPECTED[variant]["target"])
                    self.assertEqual(
                        Path(report["urdf_path"]).as_posix(),
                        (KINEMATICS_DIR / EXPECTED[variant]["urdf"]).as_posix(),
                    )
                    self.assertEqual([Path(path).name for path in report["meshes"]], EXPECTED_MESHES[variant])
                    self.assertEqual(report["missing_meshes"], [])

    def test_v1_scales_transform_round_trip_limits_and_fk_ik_while_v2_is_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for variant in ("V1", "V2"):
                with self.subTest(variant=variant):
                    real_path = write_real_config(root / f"real_{variant}.yaml", variant)
                    model = 创建运动学模型(real_config_path=real_path, use_gui=False)
                    try:
                        expected_scales = EXPECTED[variant]["kinematics"]
                        self.assertEqual(
                            model.joint_scales.tolist(),
                            [expected_scales[joint] for joint in JOINTS],
                        )
                        q_user = [0.01, 0.05, -0.04, 0.03, -0.02, 0.01]
                        expected_model = [
                            q_user[index] * expected_scales[joint] + model.model_offsets_rad[index]
                            for index, joint in enumerate(JOINTS)
                        ]
                        q_model = model._user_to_model_q(q_user)
                        for actual, expected in zip(q_model, expected_model):
                            self.assertAlmostEqual(actual, expected, places=9)
                        for actual, expected in zip(model._model_to_user_q(q_model), q_user):
                            self.assertAlmostEqual(actual, expected, places=9)

                        for index, (model_lower, model_upper) in enumerate(model.ordered_joint_model_limits):
                            scale = expected_scales[JOINTS[index]]
                            offset = model.model_offsets_rad[index]
                            expected_user = sorted(
                                ((model_lower - offset) / scale, (model_upper - offset) / scale)
                            )
                            actual_user = model.ordered_joint_user_limits[index]
                            self.assertAlmostEqual(actual_user[0], expected_user[0], places=7)
                            self.assertAlmostEqual(actual_user[1], expected_user[1], places=7)

                        pose = model.forward(q_user)
                        solved = model.inverse(
                            pose["xyz"],
                            target_rpy=pose["rpy"],
                            seed_q_user=q_user,
                        )
                        self.assertLess(solved["position_error_m"], 0.005)
                        self.assertLess(solved["orientation_error_rad"], 0.005)
                        for index, value in enumerate(solved["q_user_rad"]):
                            lower, upper = model.ordered_joint_user_limits[index]
                            self.assertGreaterEqual(value, lower)
                            self.assertLessEqual(value, upper)
                        if variant == "V2":
                            for actual, expected in zip(q_model, q_user):
                                self.assertAlmostEqual(actual, expected, places=9)
                    finally:
                        model.close()

    def test_relative_real_config_paths_and_common_helpers_select_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_dir = root / "configs"
            config_dir.mkdir()
            real_path = write_real_config(root / "real.yaml", "V1")
            action_path = config_dir / "actions.yaml"
            kinematics_path = config_dir / "kinematics.yaml"
            action_path.write_text("{}\n", encoding="utf-8")
            kinematics_path.write_text("{}\n", encoding="utf-8")
            relative_real_path = Path("../real.yaml")

            with patch.dict(os.environ, {}, clear=True):
                action_config = load_action_config(action_path, real_config_path=relative_real_path)
                kinematics_config = 加载运动学配置(
                    kinematics_path,
                    real_config_path=relative_real_path,
                )
                library = load_action_library(action_path, real_config_path=relative_real_path)
                player = load_sequence_player(
                    object(),
                    action_path,
                    real_config_path=relative_real_path,
                )
                recorder = load_action_recorder(
                    object(),
                    action_path,
                    real_config_path=relative_real_path,
                )
                sequence = build_recording_sequence(
                    "profile-path",
                    "test",
                    action_path,
                    real_config_path=relative_real_path,
                )
                model, error = load_kinematics_model(
                    kinematics_path,
                    real_config_path=relative_real_path,
                )

            self.assertEqual(action_config["robot"]["variant"], "V1")
            self.assertEqual(kinematics_config["robot"]["variant"], "V1")
            self.assertEqual(library.config["robot"]["variant"], "V1")
            self.assertEqual(player.config["robot"]["variant"], "V1")
            self.assertEqual(recorder.config["robot"]["variant"], "V1")
            self.assertEqual(sequence["joint_order"], JOINTS)
            self.assertEqual(error, "")
            self.assertIsNotNone(model)
            try:
                self.assertEqual(model.joint_scales.tolist(), [EXPECTED["V1"]["kinematics"][joint] for joint in JOINTS])
            finally:
                if model is not None:
                    model.close()

    def test_action_recorder_computes_tcp_with_selected_profile(self) -> None:
        class FakeController:
            def __init__(self, joints: dict[str, float]) -> None:
                self.joints = joints

            def get_state(self) -> dict[str, object]:
                return {
                    "joints_deg": self.joints,
                    "raw_present_position": {},
                    "gripper": {"available": False},
                }

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            action_path = root / "actions.yaml"
            real_v1_path = write_real_config(root / "real_v1.yaml", "V1")
            real_v2_path = write_real_config(root / "real_v2.yaml", "V2")
            action_path.write_text("{}\n", encoding="utf-8")
            joint_targets = {
                "j10": 18.0,
                "j11": 12.0,
                "j12": -16.0,
                "j13": 21.0,
                "j14": -9.0,
                "j15": 7.0,
            }
            q = targets_to_kinematics_q(joint_targets)
            recorded_poses: dict[str, dict[str, list[float]]] = {}

            for variant, real_path in (("V1", real_v1_path), ("V2", real_v2_path)):
                recorder = load_action_recorder(
                    FakeController(joint_targets),
                    action_path,
                    real_config_path=real_path,
                )
                recorded = recorder.capture_current_pose()
                model = 创建运动学模型(use_gui=False, real_config_path=real_path)
                try:
                    expected = model.forward(q)
                finally:
                    model.close()

                self.assertEqual(recorder.real_config_path, real_path.resolve())
                for component in ("xyz", "rpy"):
                    for actual, wanted in zip(recorded["tcp_pose"][component], expected[component]):
                        self.assertAlmostEqual(actual, wanted, places=9)
                recorded_poses[variant] = recorded["tcp_pose"]

            self.assertNotEqual(recorded_poses["V1"]["xyz"], recorded_poses["V2"]["xyz"])

    def test_sim_view_and_switcher_use_custom_v1_real_config(self) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt5.QtWidgets import QApplication
        from gui_app.组件_widgets import 仿真视图_sim_view as sim_view_module
        from gui_app.组件_widgets.检查器视图切换器_inspector_view_switcher import (
            InspectorViewSwitcher,
        )

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real_path = write_real_config(root / "real_v1.yaml", "V1").resolve()

            application = QApplication.instance() or QApplication([])
            view = sim_view_module.SimView(real_config_path=real_path)
            view._init_model()
            try:
                self.assertEqual(view.model.target_frame, "Link_6")
                self.assertEqual(
                    view.model.urdf_path,
                    (KINEMATICS_DIR / EXPECTED["V1"]["urdf"]).resolve(),
                )
                self.assertEqual(
                    view.model.joint_scales.tolist(),
                    [1.0, 1.0, -1.0, 1.0, -1.0, 1.0],
                )
                self.assertEqual(len(view.model.ordered_joint_user_limits), 6)
                self.assertAlmostEqual(
                    view.model.ordered_joint_user_limits[1][1],
                    3.14159,
                    places=7,
                )
                self.assertAlmostEqual(
                    view.model.ordered_joint_user_limits[2][0],
                    -3.14159,
                    places=7,
                )
            finally:
                view.model.close()
                view.close()
                application.processEvents()

            switcher = InspectorViewSwitcher(root, real_config_path=real_path)
            simulated_widget = sim_view_module.QWidget()
            with patch.object(
                sim_view_module,
                "SimView",
                return_value=simulated_widget,
            ) as sim_view_cls:
                self.assertIs(switcher._ensure_sim_view(), simulated_widget)
            sim_view_cls.assert_called_once_with(real_config_path=real_path)
            simulated_widget.close()
            switcher.close()

    def test_gui_and_web_bridges_forward_real_config_to_all_profile_helpers(self) -> None:
        import gui_app.控制器桥接_controller_bridge as gui_module
        from backend import controller_bridge as web_module

        for module, bridge_class, label in (
            (gui_module, gui_module.ControllerBridge, "gui"),
            (web_module, web_module.ControllerBridge, "web"),
        ):
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                real_path = write_real_config(root / "real.yaml", "V1")
                action_path = root / "actions.yaml"
                kinematics_path = root / "kinematics.yaml"
                sim_path = root / "sim.yaml"
                for path in (action_path, kinematics_path, sim_path):
                    path.write_text("{}\n", encoding="utf-8")
                real_path = real_path.resolve()
                action_path = action_path.resolve()
                kinematics_path = kinematics_path.resolve()
                sim_path = sim_path.resolve()
                config = {
                    "app": {"default_mode": "dry_run", "log_path": f"{label}.txt"},
                    "controller": {
                        "real_config_path": str(real_path),
                        "action_config_path": str(action_path),
                        "kinematics_config_path": str(kinematics_path),
                        "sim_config_path": str(sim_path),
                    },
                }
                bridge = bridge_class(config, root)
                bridge.controller = object()

                with patch.object(module, "load_action_library", return_value=object()) as load_library:
                    bridge._get_action_library()
                    load_library.assert_called_once_with(action_path, real_config_path=real_path)

                with patch.object(module, "load_sequence_player", return_value=Mock()) as load_player:
                    bridge.sequence_player = None
                    bridge._get_sequence_player()
                    self.assertEqual(load_player.call_args.args[:2], (bridge.controller, action_path))
                    self.assertEqual(load_player.call_args.kwargs["real_config_path"], real_path)

                with patch.object(module, "load_kinematics_model", return_value=(object(), "")) as load_model:
                    bridge.kinematics_model = None
                    bridge._get_kinematics_model()
                    load_model.assert_called_once_with(kinematics_path, real_config_path=real_path)

                empty_sequence = {"poses": []}
                with (
                    patch.object(module, "build_recording_sequence", return_value=empty_sequence) as build_sequence,
                    patch.object(bridge, "_ensure_controller"),
                    patch.object(bridge, "_log"),
                ):
                    bridge.start_action_recording("profile-path")
                    build_sequence.assert_called_once_with(
                        "profile-path",
                        f"{label}_record",
                        action_path,
                        real_config_path=real_path,
                    )

                fake_recorder = Mock()
                fake_recorder.capture_current_pose.return_value = {"name": "pose_1"}
                bridge.recording_sequence = {"poses": []}
                with (
                    patch.object(module, "load_action_recorder", return_value=fake_recorder) as load_recorder,
                    patch.object(bridge, "_ensure_controller"),
                    patch.object(bridge, "_log"),
                ):
                    bridge.capture_recording_pose()
                    load_recorder.assert_called_once_with(
                        bridge.controller,
                        action_path,
                        real_config_path=real_path,
                    )


if __name__ == "__main__":
    unittest.main()
