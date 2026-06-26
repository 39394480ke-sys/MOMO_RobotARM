"""公共控制桥接 helper 纯逻辑测试。

不访问摄像头、Web 服务或真实舵机；用于保护 GUI/Web/视觉共享逻辑。
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
GUI_ROOT = PROJECT_ROOT / "GUI图形界面"
VISION_ROOT = PROJECT_ROOT / "视觉识别与跟随"
WEB_ROOT = PROJECT_ROOT / "Web控制台"
AGENT_ROOT = PROJECT_ROOT / "语音Agent"
INTEGRATION_ROOT = PROJECT_ROOT / "系统集成"
REAL_ROOT = PROJECT_ROOT / "真实舵机控制"
ACTION_ROOT = PROJECT_ROOT / "动作录制与回放增强"
KINEMATICS_ROOT = PROJECT_ROOT / "URDF运动学仿真"
SIM_ROOT = PROJECT_ROOT / "仿真控制系统"

for root in (
    GUI_ROOT,
    VISION_ROOT,
    WEB_ROOT,
    AGENT_ROOT,
    INTEGRATION_ROOT,
    REAL_ROOT,
    ACTION_ROOT,
    KINEMATICS_ROOT,
    SIM_ROOT,
):
    root_text = str(root)
    if root_text not in sys.path:
        sys.path.insert(0, root_text)

from 控制桥接_common import (
    DEFAULT_MOTION_TUNING,
    RailSweepPlanner,
    api_error_info,
    build_exception_context,
    build_motion_progress_payload,
    clamp01,
    clamp_percent,
    clamp_range,
    clamp_symmetric,
    cinematic_real_speed_percent,
    compute_axis_step,
    eased_end_progress,
    compute_tcp_pose_payload,
    extract_joints_from_state,
    extract_gripper_open_percent,
    make_config_resolver,
    motion_speed_scale,
    normalize_robot_state_payload,
    normalize_gripper_state,
    normalize_joint_targets,
    normalize_motion_tuning,
    normalize_motion_speed_percent,
    normalize_multi_turn_state,
    normalize_playback_speed,
    normalize_raw_present_position,
    read_smoothed_offset,
    resolve_calibration_file_path,
    safe_call_callback,
    smoothstep01,
    state_tcp_pose,
    unwrap_vision_payload,
    unwrap_api_data,
    vision_target_guard,
)
from gui_app.AI运镜运行时_cinematic_runtime import CinematicRehearsalRuntime
from 通用路径 import ensure_parent_dirs as ensure_common_parent_dirs
from 通用路径 import ensure_paths_on_sys_path, resolve_under_base
from 通用_io import (
    attach_config_metadata,
    atomic_write_json,
    log_event_json_line,
    parse_json_line,
    read_config,
    read_structured,
    tail_lines,
    write_json,
    write_text,
)
from vision.结果存储_result_store import ResultStore
from vision.路径工具_path_utils import ensure_parent_dirs, ensure_project_root_on_path, resolve_vision_path
from backend.logger import JsonLineLogger
from backend.path_utils import ensure_project_root_on_path as ensure_web_project_root_on_path
from backend.state_manager import SessionStateManager
from agent.path_utils import (
    AGENT_ROOT as RESOLVED_AGENT_ROOT,
    ensure_project_root_on_path as ensure_agent_project_root_on_path,
    resolve_agent_path,
)
from agent.会话管理_session_manager import SessionManager
from agent.日志_logger import AgentLogger
from gui_app.path_utils import ensure_project_root_on_path as ensure_gui_project_root_on_path
from integration.config_loader import ConfigLoader
from integration.log_manager import LogManager
from integration.mode_manager import ModeManager
from integration.path_utils import (
    INTEGRATION_DIR as RESOLVED_INTEGRATION_DIR,
    ensure_project_root_on_path as ensure_integration_project_root_on_path,
    resolve_integration_path,
)
from integration.runtime_state import RuntimeState
from 标定管理_calibration_manager import CalibrationManager
from 真实路径工具_real_path_utils import (
    REAL_CONTROL_DIR,
    ensure_project_root_on_path as ensure_real_project_root_on_path,
    resolve_real_path,
)
from 角度映射_angle_mapper import joint_deg_to_goal_detail, present_raw_to_joint_detail
from 动作日志_motion_logger import MotionLogger
from 动作工具_common import DEFAULT_JOINT_SPEED_LIMITS
from 动作工具_common import load_config as load_action_config
from 动作工具_common import normalize_joint_targets as normalize_action_joint_targets
from 动作工具_common import normalize_gripper_state as normalize_action_gripper_state
from 动作工具_common import normalize_multi_turn_state as normalize_action_multi_turn_state
from 动作工具_common import normalize_playback_speed as normalize_action_playback_speed
from 动作工具_common import normalize_raw_present_position as normalize_action_raw_present_position
from 动作工具_common import state_joint_targets as action_state_joint_targets
from 动作工具_common import summarize_sequence_payload
from 动作文件管理_action_library import ActionLibrary
from 动作回放器_sequence_player import SequencePlayer
from 动作路径工具_motion_path_utils import (
    ACTION_ROOT as RESOLVED_ACTION_ROOT,
    ensure_project_root_on_path as ensure_action_project_root_on_path,
    resolve_action_path,
)
from 运动学模型_kinematics_model import 加载运动学配置, 解析资源路径
from 运动学路径工具_kinematics_path_utils import (
    KINEMATICS_ROOT as RESOLVED_KINEMATICS_ROOT,
    ensure_project_root_on_path as ensure_kinematics_project_root_on_path,
    resolve_kinematics_path,
)
from 仿真路径工具_sim_path_utils import (
    SIM_ROOT as RESOLVED_SIM_ROOT,
    ensure_project_root_on_path as ensure_sim_project_root_on_path,
    resolve_sim_path,
)
from 动作播放器_action_player import 动作播放器
from 姿态管理.姿态管理_pose_manager import 姿态管理器
from 机械臂模型_robot_arm import 机械臂模型


def test_axis_step() -> None:
    cases = [
        (0.01, False, None, False),
        (0.05, False, 0.24, True),
        (0.02, True, None, False),
        (0.2, True, 0.96, True),
        (-0.2, False, -0.96, True),
    ]
    for norm, active, expected_step, expected_active in cases:
        step, next_active = compute_axis_step(
            norm,
            active=active,
            gain=4.8,
            sign=1.0,
            dead=0.03,
            resume=0.05,
            min_step=0.5,
            min_zone=0.12,
            max_step=3.0,
        )
        assert step == expected_step and next_active is expected_active, (norm, active, step, next_active)


def test_clamp_helpers() -> None:
    assert clamp01(-0.5) == 0.0
    assert clamp01(0.25) == 0.25
    assert clamp01(1.5) == 1.0
    assert clamp_range(8.0, 0.0, 5.0) == 5.0
    assert clamp_range(-1.0, 0.0, 5.0) == 0.0
    assert clamp_range(3.0, 5.0, 0.0) == 3.0
    assert clamp_symmetric(7.0, 2.5) == 2.5
    assert clamp_symmetric(-7.0, 2.5) == -2.5
    assert clamp_symmetric(1.0, -2.5) == 1.0
    assert clamp_percent(-1.0) == 0.0
    assert clamp_percent(42.5) == 42.5
    assert clamp_percent(120.0) == 100.0


def test_motion_tuning_normalization_helpers() -> None:
    defaults = normalize_motion_tuning()
    assert defaults["default_speed_percent"] == DEFAULT_MOTION_TUNING["default_speed_percent"]
    assert defaults["quick_step_frames"] == DEFAULT_MOTION_TUNING["quick_step_frames"]
    assert defaults["jog_direction_overrides"] == {joint: 1 for joint in ("j10", "j11", "j12", "j13", "j14", "j15")}
    assert normalize_motion_speed_percent("bad") == DEFAULT_MOTION_TUNING["default_speed_percent"]
    assert normalize_motion_speed_percent(5) == 10.0
    assert normalize_motion_speed_percent(150) == 100.0
    assert motion_speed_scale(25) == 0.25
    assert motion_speed_scale(5) == 0.1
    assert cinematic_real_speed_percent(10) == 20.0
    assert cinematic_real_speed_percent(80) == 35.0
    assert normalize_playback_speed("bad") == 1.0
    assert normalize_playback_speed(0.01) == 0.1
    assert normalize_playback_speed(9.0) == 3.0
    assert normalize_playback_speed(1.25) == 1.25
    assert normalize_action_playback_speed(9.0) == 3.0

    normalized = normalize_motion_tuning(
        {
            "default_speed_percent": 5,
            "quick_step_duration_s": "99",
            "quick_step_frames": "500",
            "continuous_update_hz": "bad",
            "continuous_target_horizon_s": -1,
            "playback_update_hz": 100,
            "jog_direction_overrides": {"J10": "-1", "j11": "反", "j12": "reverse", "j13": 1},
        },
        {"quick_step_frames": 8},
    )
    assert normalized["default_speed_percent"] == 10.0
    assert normalized["quick_step_duration_s"] == 10.0
    assert normalized["quick_step_frames"] == 8
    assert normalized["continuous_update_hz"] == DEFAULT_MOTION_TUNING["continuous_update_hz"]
    assert normalized["continuous_target_horizon_s"] == 0.0
    assert normalized["playback_update_hz"] == 60.0
    assert normalized["jog_direction_overrides"] == {
        "j10": -1,
        "j11": -1,
        "j12": -1,
        "j13": 1,
        "j14": 1,
        "j15": 1,
    }


def test_joint_target_normalization_helpers() -> None:
    assert normalize_joint_targets({"J11": 12.0, "j10": 3.0})["j11"] == 12.0
    assert normalize_joint_targets([1, 2, 3]) == {
        "j10": 1.0,
        "j11": 2.0,
        "j12": 3.0,
        "j13": 0.0,
        "j14": 0.0,
        "j15": 0.0,
    }
    try:
        normalize_joint_targets({"unknown": 1.0})
    except ValueError as exc:
        assert "未知关节" in str(exc)
    else:
        raise AssertionError("公共关节归一化应默认拒绝未知关节")

    action_targets = normalize_action_joint_targets({"unknown": 9.0, "J12": 7.0})
    assert action_targets["j12"] == 7.0
    assert "unknown" not in action_targets
    assert normalize_action_joint_targets([10, 20, 30, 40, 50]) == {
        "j10": 0.0,
        "j11": 10.0,
        "j12": 20.0,
        "j13": 30.0,
        "j14": 40.0,
        "j15": 50.0,
    }


def test_state_joint_extraction_helpers() -> None:
    assert extract_joints_from_state({"joints_deg": {"J11": 2.0}})["j11"] == 2.0
    assert extract_joints_from_state({"关节角度": [1.0, 2.0]}) == {
        "j10": 1.0,
        "j11": 2.0,
        "j12": 0.0,
        "j13": 0.0,
        "j14": 0.0,
        "j15": 0.0,
    }
    action_state = action_state_joint_targets(
        {"joint_state": {"J12": 7.0, "unknown": 99.0}, "joints_deg": {"j12": 1.0}},
        ["j10", "j11", "j12", "j13", "j14", "j15"],
    )
    assert action_state["j12"] == 7.0
    assert "unknown" not in action_state


def test_gripper_state_normalization_helpers() -> None:
    assert extract_gripper_open_percent({"open_ratio": 0.42}) == 42.0
    assert extract_gripper_open_percent({"open_percent": 125.0}) == 100.0
    assert extract_gripper_open_percent(-20.0) == 0.0

    percent = normalize_gripper_state({"gripper": {"open_percent": 37.5, "present_raw": 1234.4}})
    assert percent == {"available": True, "present_raw": 1234, "open_percent": 38, "open_ratio": 0.375}

    ratio = normalize_gripper_state({"gripper_state": {"open_ratio": 0.42}})
    assert ratio == {"available": True, "open_ratio": 0.42, "open_percent": 42}

    assert normalize_gripper_state({"夹爪": 55}) == {"available": True, "open_ratio": 0.55, "open_percent": 55}
    assert normalize_gripper_state({"gripper": {"available": False}}) == {"available": False}
    assert normalize_gripper_state({"gripper": "bad"}) == {"available": False}
    assert normalize_action_gripper_state({"gripper": {"open_ratio": 0.5}}) == {"available": True, "open_ratio": 0.5, "open_percent": 50}

    with tempfile.TemporaryDirectory() as tmp:
        real_config = Path(tmp) / "真实配置.yaml"
        real_config.write_text("transport:\n  gripper_available: true\n", encoding="utf-8")
        payload = normalize_robot_state_payload(
            {"joints_deg": {"j11": 1.0}, "gripper_state": {"open_ratio": 0.25}},
            "dry_run",
            True,
            real_config,
            include_gripper_state=True,
            include_open_ratio=True,
        )
        assert payload["gripper"]["open_percent"] == 25.0
        assert payload["gripper"]["open_ratio"] == 0.25


def test_multi_turn_state_normalization_helpers() -> None:
    state = {
        "multi_turn_state": {
            "j10": {"home_present_raw": 100, "present_raw": 120, "relative_raw": 20, "goal_raw": 121},
            "j11": {"startup_raw": 200, "current_raw": 260, "continuous_raw": 60, "motor_deg": 5.0},
            "j12": "bad",
        }
    }
    normalized = normalize_multi_turn_state(state, ["j10", "j11", "j12"])
    assert normalized["j10"]["startup_raw"] == 100
    assert normalized["j10"]["current_raw"] == 120
    assert normalized["j10"]["continuous_raw"] == 20
    assert normalized["j10"]["relative_raw"] == 20
    assert normalized["j11"]["continuous_raw"] == 60
    assert normalized["j12"] == {
        "startup_raw": None,
        "current_raw": None,
        "continuous_raw": 0,
        "relative_raw": 0,
        "motor_deg": None,
        "joint_deg": None,
        "goal_raw": None,
    }
    assert normalize_action_multi_turn_state(state, ["j10"]) == {"j10": normalized["j10"]}


def test_raw_present_position_normalization_helpers() -> None:
    normalized = normalize_raw_present_position({"j10": 100.2, "j11": "200.6", "j12": None})
    assert normalized == {"j10": 100, "j11": 201}
    assert normalize_raw_present_position([("j13", 300.4), ("j14", None)]) == {"j13": 300}
    assert normalize_raw_present_position(None) is None
    assert normalize_raw_present_position(["bad"]) is None
    assert normalize_action_raw_present_position({"j10": 1.4}) == {"j10": 1}


def test_motion_progress_payload_helper() -> None:
    payload = build_motion_progress_payload({"j11": "2.5"}, "unit", frame_index=3)
    assert payload == {
        "source": "unit",
        "targets_deg": {"j11": 2.5},
        "frame_index": 3,
    }


def test_sequence_player_uses_normalized_playback_speed() -> None:
    player = SequencePlayer(object(), {"robot": {"sdk_joint_names": ["j10", "j11", "j12", "j13", "j14", "j15"]}, "files": {"runtime_log": "运行日志/test_motion_runtime.log"}, "playback": {"auto_duration_from_distance": False}})
    assert player._duration({"duration_sec": 3.0}, 99.0, current={}, targets={}) == 1.0
    assert player._hold_duration({"hold_sec": 0.9}, {}, 99.0) == 0.3


def test_sequence_player_default_joint_speed_limits_are_shared() -> None:
    assert load_action_config()["playback"]["joint_speed_limits"] == DEFAULT_JOINT_SPEED_LIMITS
    player = SequencePlayer(object(), {"robot": {"sdk_joint_names": ["j10", "j11", "j12", "j13", "j14", "j15"]}, "files": {"runtime_log": "运行日志/test_motion_runtime.log"}, "playback": {"auto_duration_from_distance": True, "joint_speed_limits": {}}})
    assert player._distance_based_duration({"j10": 0.0, "j15": 0.0}, {"j10": 40.0, "j15": 30.0}) == 2.0


def test_action_sequence_summary_helper() -> None:
    sequence = {
        "name": "summary-demo",
        "created_at": "now",
        "poses": [
            {
                "duration_sec": 1.2,
                "hold_sec": 0.3,
                "raw_present_position": {"j10": 1},
                "tcp_pose": {"xyz": [1, 2, 3]},
                "gripper": {"available": True},
                "multi_turn_state": {"j10": {"continuous_raw": 1}},
            },
            {"duration_sec": 2.0, "hold_sec": 0.0, "tcp_pose": {"xyz": [4, 5, 6]}},
        ],
    }
    summary = summarize_sequence_payload(sequence)
    assert summary["动作名称"] == "summary-demo"
    assert summary["pose_count"] == 2
    assert summary["总时长"] == 3.5
    assert summary["是否包含 raw"] is True
    assert summary["是否包含 tcp_pose"] is True
    assert summary["是否包含 gripper"] is True
    assert summary["是否包含 multi_turn_state"] is True
    assert summary["末端轨迹点数"] == 2
    assert summary["末端轨迹起点"] == [1, 2, 3]
    assert summary["末端轨迹终点"] == [4, 5, 6]
    with tempfile.TemporaryDirectory() as tmp:
        library = ActionLibrary(config={"files": {"action_library_dir": tmp}}, library_dir=tmp)
        assert library.summarize_action(sequence) == summary


def test_tcp_pose_payload_helper() -> None:
    approx = compute_tcp_pose_payload(None, {"j10": 100.0, "j11": 10.0})
    assert approx["tcp_pose"]["source"] == "approximate_fk_without_stage5"
    assert len(approx["tcp_pose"]["xyz"]) == 3

    class FakeKinematicsModel:
        def forward(self, q_values: list[float]) -> dict[str, object]:
            assert len(q_values) == 6
            assert abs(q_values[0] - 0.1) < 1e-9
            return {"xyz": [1, 2, 3], "rpy": [0, 0, 0]}

    exact = compute_tcp_pose_payload(FakeKinematicsModel(), {"j10": 100.0, "j11": 10.0})
    assert exact["tcp_pose"] == {"xyz": [1, 2, 3], "rpy": [0, 0, 0], "source": "stage5_fk"}


def test_safe_callback_helper() -> None:
    seen: list[dict[str, object]] = []
    assert safe_call_callback(seen.append, {"ok": True}) is True
    assert seen == [{"ok": True}]
    assert safe_call_callback(None, {"ignored": True}) is False

    def raises(_payload: object) -> None:
        raise RuntimeError("boom")

    assert safe_call_callback(raises, {"ok": False}) is False


def test_exception_context_helper() -> None:
    exc = ValueError("bad value")
    plain = build_exception_context("处理失败", exc)
    assert plain["last_error"] == "bad value"
    assert plain["message"] == "处理失败：bad value"
    assert plain["error"] == "bad value"
    assert "ValueError: bad value" in plain["traceback"]

    typed = build_exception_context("处理失败", exc, include_type=True)
    assert typed["error"] == "ValueError: bad value"


def test_motion_easing_helpers() -> None:
    assert smoothstep01(-1.0) == 0.0
    assert smoothstep01(0.0) == 0.0
    assert smoothstep01(0.5) == 0.5
    assert smoothstep01(1.0) == 1.0
    assert smoothstep01(2.0) == 1.0

    values = [eased_end_progress(index / 10.0, 2.0, 0.4) for index in range(11)]
    assert values[0] == 0.0
    assert values[-1] == 1.0
    assert all(values[index] <= values[index + 1] for index in range(len(values) - 1))
    assert abs(values[2] + values[8] - 1.0) < 1e-9
    assert eased_end_progress(0.25, 2.0, 0.0) == 0.25


def test_target_guard() -> None:
    cases = [
        ({"detected": False}, "no_target"),
        ({"has_target": False, "tracking_state": "lost"}, "target_lost"),
        ({"detected": True, "tracking_state": "lost"}, "target_lost"),
        ({"detected": True, "bbox": [0, 0, 10, 30]}, "target_too_small"),
        ({"detected": True, "target": {"bbox": ["bad"]}}, "invalid_target_bbox"),
        ({"detected": True, "bbox": [0, 0, 30, 30]}, None),
    ]
    for payload, expected in cases:
        guard = vision_target_guard(payload)
        action = None if guard is None else guard["action"]
        assert action == expected, (payload, guard, expected)


def test_smoothed_offset() -> None:
    assert read_smoothed_offset({"smoothed_offset": {"valid": True, "ndx": "0.2", "ndy": "-0.1"}}) == (0.2, -0.1)
    assert read_smoothed_offset({"smoothed_offset": {"valid": False, "ndx": 1, "ndy": 1}}) is None
    assert read_smoothed_offset({}) is None


def test_vision_payload_unwrap() -> None:
    raw = {"detected": True, "x": 1}
    wrapped = {"ok": True, "data": {"detected": False, "x": 2}}
    error = {"ok": False, "error": {"code": "BAD"}}
    assert unwrap_vision_payload(raw) == raw
    assert unwrap_vision_payload(wrapped) == {"detected": False, "x": 2}
    assert unwrap_vision_payload(error) == error


def test_api_payload_helpers() -> None:
    assert unwrap_api_data({"ok": True, "data": {"value": 1}}) == {"value": 1}
    assert unwrap_api_data({"ok": True, "data": [1, 2]}) == {"value": [1, 2]}
    info = api_error_info(
        {"ok": False, "data": {"context": 1}, "error": {"code": "BAD", "message": "坏请求"}},
        "fallback",
    )
    assert info == {"code": "BAD", "message": "坏请求", "data": {"context": 1}}
    try:
        unwrap_api_data({"ok": False, "error": {"message": "失败"}})
    except ValueError as exc:
        assert str(exc) == "失败"
    else:
        raise AssertionError("unwrap_api_data 应在 API 失败时抛出 ValueError")


def test_state_tcp_pose_helper() -> None:
    joints = {"j10": 0.0, "j11": 0.0, "j12": 0.0, "j13": 0.0, "j14": 0.0, "j15": 0.0}
    approx = state_tcp_pose(None, joints)
    assert approx["source"] == "approximate_fk_without_stage5"

    class FakeModel:
        def forward(self, _q_values: list[float]) -> dict[str, object]:
            return {"xyz": [1, 2, 3], "rpy": [0, 0, 0]}

    cached = state_tcp_pose(FakeModel(), joints)
    assert cached["xyz"] == [1, 2, 3]
    assert cached["source"] == "stage5_fk_cached"


def test_rail_sweep_planner() -> None:
    planner = RailSweepPlanner(
        {"enabled": True, "joint": "j10", "start_mm": -2, "end_mm": 2, "speed_mm_s": 20},
        virtual_pos_mm=-2,
        running=True,
        phase="seek_start",
    )
    assert planner.command(default_dt_sec=0.1) == [{"joint_key": "j10", "delta_deg": 2.0, "kind": "rail_cinematic"}]
    assert planner.phase == "sweep"

    planner = RailSweepPlanner(
        {"enabled": True, "start_mm": 0, "end_mm": 1, "speed_mm_s": 10, "bounce": False},
        virtual_pos_mm=1,
        running=True,
        phase="sweep",
    )
    assert planner.step(default_dt_sec=0.1) is None
    assert planner.phase == "finished"
    assert planner.running is False


def test_cinematic_runtime_preserves_capture_direction() -> None:
    runtime = CinematicRehearsalRuntime(
        PROJECT_ROOT,
        lambda: {
            "follow": {
                "rail_cinematic": {"enabled": True, "start_mm": 20.0, "end_mm": -20.0, "speed_mm_s": 20.0},
                "two_step_cinematic": {
                    "sample_interval_sec": 0.1,
                    "playback_smooth": 0.0,
                    "playback_speed_scale": 1.0,
                    "max_compensation_deg": 0.0,
                    "offset_stop_norm": 0.65,
                    "playback_hz": 10.0,
                    "ease_sec": 0.2,
                    "min_rail_step_mm": 2.0,
                },
            }
        },
    )
    record = {
        "rail": {"start_mm": 20.0, "end_mm": -20.0, "speed_mm_s": 20.0},
        "follow_joints": ["j11"],
        "samples": [
            {"timestamp": 1.0, "j10_mm": 20.0, "ndx": 0.0, "ndy": 0.0, "joints_deg": {"j11": 10.0}},
            {"timestamp": 2.0, "j10_mm": 10.0, "ndx": 0.0, "ndy": 0.0, "joints_deg": {"j11": 20.0}},
            {"timestamp": 3.0, "j10_mm": 12.0, "ndx": 0.0, "ndy": 0.0, "joints_deg": {"j11": 99.0}},
            {"timestamp": 4.0, "j10_mm": -20.0, "ndx": 0.0, "ndy": 0.0, "joints_deg": {"j11": 30.0}},
        ],
    }
    dense = runtime.build_playback_plan(record, {"selected_joints": ["j11"], "signs": {"j11": 1.0}})
    assert dense[0]["targets_deg"]["j10"] == 20.0
    assert dense[-1]["targets_deg"]["j10"] == -20.0
    assert dense[0]["targets_deg"]["j11"] == 10.0
    assert dense[-1]["targets_deg"]["j11"] == 30.0
    assert all(dense[index]["targets_deg"]["j10"] >= dense[index + 1]["targets_deg"]["j10"] for index in range(len(dense) - 1))


def test_event_json_line_keeps_motion_log_shape() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "motion.log"
        log_event_json_line(path, "play_start", action_name="demo", ok=True)
        payload = json.loads(path.read_text(encoding="utf-8").strip())
    assert set(payload) == {"time", "event", "action_name", "ok"}
    assert payload["event"] == "play_start"
    assert payload["action_name"] == "demo"
    assert payload["ok"] is True


def test_common_io_helpers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        json_path = root / "nested" / "config.json"
        write_json(json_path, {"name": "demo", "nested": {"ok": True}})
        loaded = read_structured(json_path)
        assert loaded == {"name": "demo", "nested": {"ok": True}}

        yaml_path = root / "config.yaml"
        yaml_path.write_text("name: yaml-demo\nnested:\n  ok: true\n", encoding="utf-8")
        yaml_loaded = read_structured(yaml_path)
        assert yaml_loaded == {"name": "yaml-demo", "nested": {"ok": True}}

        meta = attach_config_metadata(yaml_path, yaml_loaded, _project_root=PROJECT_ROOT, custom_flag=True)
        assert meta["_config_path"] == str(yaml_path.resolve())
        assert meta["_base_dir"] == str(root.resolve())
        assert meta["_project_root"] == str(PROJECT_ROOT)
        assert meta["custom_flag"] is True

        loaded_config = read_config(yaml_path, _project_root=PROJECT_ROOT)
        assert loaded_config["_config_path"] == str(yaml_path.resolve())
        assert loaded_config["_project_root"] == str(PROJECT_ROOT)

        atomic_path = root / "state" / "runtime.json"
        atomic_write_json(atomic_path, {"running": False})
        assert read_structured(atomic_path) == {"running": False}

        log_path = root / "runtime" / "logs" / "demo.log"
        write_text(log_path, "\n".join(f"line-{index}" for index in range(5)) + "\n")
        assert tail_lines(log_path, 3) == ["line-2", "line-3", "line-4"]
        assert tail_lines(root / "missing.log", 3) == []
        assert tail_lines(log_path, 0) == []

    assert parse_json_line('{"ok": true}') == {"ok": True}
    assert parse_json_line("[1, 2, 3]") is None
    assert parse_json_line("not json") is None


def test_common_path_helpers() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp).resolve()
        a_path = root / "a"
        b_path = root / "b"
        resolved = ensure_paths_on_sys_path([a_path, b_path])
        assert resolved == (a_path, b_path)
        assert sys.path.index(str(a_path)) < sys.path.index(str(b_path))
        assert resolve_under_base("nested/file.txt", root) == root / "nested/file.txt"

        target = root / "created" / "child" / "file.txt"
        ensure_common_parent_dirs(target)
        assert target.parent.exists()


def test_config_resolver_helper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config = {"controller": {"main_config": "missing.yaml"}}
        fallback = root / "fallback.yaml"
        fallback.write_text("ok: true\n", encoding="utf-8")
        resolver = make_config_resolver(config, root, "Unit", require_exists=True)
        assert resolver("main_config", ["fallback.yaml"]) == fallback.resolve()
        try:
            resolver("missing_key")
        except KeyError as exc:
            assert "controller.missing_key" in str(exc)
        else:
            raise AssertionError("缺失 controller key 应抛出 KeyError")


def test_calibration_path_resolver_helper() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config_path = root / "真实配置.yaml"
        config_path.write_text("calibration:\n  path: nested/calibration.json\n", encoding="utf-8")
        assert resolve_calibration_file_path(config_path) == (root / "nested" / "calibration.json").resolve()

        absolute = root / "abs_calibration.json"
        assert resolve_calibration_file_path(config_path, {"calibration": {"path": str(absolute)}}) == absolute


def test_vision_path_resolver() -> None:
    base = PROJECT_ROOT / "视觉识别与跟随"
    assert resolve_vision_path("weights/demo.task", base) == (base / "weights/demo.task").resolve()
    assert resolve_vision_path(base / "runtime/latest_result.json", PROJECT_ROOT) == (base / "runtime/latest_result.json").resolve()
    assert ensure_project_root_on_path() == PROJECT_ROOT
    with tempfile.TemporaryDirectory() as tmp:
        nested = Path(tmp) / "a" / "b" / "latest.json"
        ensure_parent_dirs(nested)
        assert nested.parent.exists()
        store = ResultStore({"latest_result_path": "runtime/latest.json", "latest_frame_path": "runtime/latest.jpg"}, tmp)
        assert store.latest_result_path == (Path(tmp) / "runtime/latest.json").resolve()
        assert store.latest_frame_path == (Path(tmp) / "runtime/latest.jpg").resolve()


def test_web_backend_path_and_state_helpers() -> None:
    assert ensure_web_project_root_on_path() == PROJECT_ROOT
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        logger = JsonLineLogger(root / "logs" / "web.log")
        logger.log("info", "unit_test", "ok", value=1)
        assert (root / "logs" / "web.log").exists()
        state = SessionStateManager(root / "state" / "session.json")
        initial = state.get()
        assert initial["mode"] == "dry_run"
        assert initial["connected"] is False
        assert state.mark_connected("dry_run")["connected"] is True
        assert state.mark_disconnected()["connected"] is False


def test_gui_path_helper() -> None:
    assert ensure_gui_project_root_on_path() == PROJECT_ROOT


def test_agent_path_logger_and_session_helpers() -> None:
    assert RESOLVED_AGENT_ROOT == AGENT_ROOT
    assert ensure_agent_project_root_on_path() == PROJECT_ROOT
    assert resolve_agent_path("prompts/system_prompt.md") == (AGENT_ROOT / "prompts/system_prompt.md").resolve()
    with tempfile.TemporaryDirectory() as tmp:
        config = {"_base_dir": tmp, "agent": {"backend": "openai_compatible", "max_turns": 2}}
        logger = AgentLogger(config)
        logger.log("info", "unit_test", "ok", value=1)
        assert (Path(tmp) / "runtime/logs/agent_runtime.log").exists()

        manager = SessionManager(config)
        session = manager.load_session(force_new=True)
        assert session["backend"] == "openai_compatible"
        session["messages"] = [{"role": "user", "content": str(index)} for index in range(8)]
        assert len(manager.trim_history(session["messages"])) == 4
        manager.save_session(session)
        assert (Path(tmp) / "runtime/sessions/agent_session_state.json").exists()


def test_integration_path_config_and_state_helpers() -> None:
    assert RESOLVED_INTEGRATION_DIR == INTEGRATION_ROOT
    assert ensure_integration_project_root_on_path() == PROJECT_ROOT
    assert resolve_integration_path("总配置.yaml") == (INTEGRATION_ROOT / "总配置.yaml").resolve()
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        config_path = root / "总配置.json"
        config_path.write_text(
            json.dumps(
                {
                    "project": {"name": "unit", "default_mode": "dry_run"},
                    "logging": {
                        "system_log": "runtime/logs/system.log",
                        "state_file": "runtime/state/system_state.json",
                    },
                    "services": {},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        config = ConfigLoader(config_path).load()
        assert config["_project_root"] == str(PROJECT_ROOT)
        assert (root / "runtime/logs").exists()

        logger = LogManager(config)
        logger.log_info("unit_test", "ok", value=1)
        assert (root / "runtime/logs/system.log").exists()

        state = RuntimeState(config)
        assert state.load()["mode"] == "dry_run"
        assert ModeManager(config).set_mode("simulation")["mode"] == "sim"
        assert RuntimeState(config).load()["mode"] == "sim"


def test_real_control_path_mapping_and_calibration_helpers() -> None:
    assert REAL_CONTROL_DIR == REAL_ROOT
    assert ensure_real_project_root_on_path() == PROJECT_ROOT
    assert resolve_real_path("真实配置.yaml") == (REAL_ROOT / "真实配置.yaml").resolve()

    joint_config = {"joint_scale": 5.0}
    calibration = {"模式": "多圈", "home_present_raw": 1000, "phase": 28, "direction": 1}
    detail = joint_deg_to_goal_detail("j11", 10.0, joint_config, calibration, {})
    assert detail["goal_raw"] == 1569
    reverse = present_raw_to_joint_detail("j11", detail["goal_raw"], joint_config, calibration, {})
    assert abs(reverse["joint_deg"] - 10.001953125) < 1e-9

    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "calibration.json"
        path.write_text(
            json.dumps(
                {
                    "j10": {"id": 10, "模式": "多圈", "home_present_raw": 0, "phase": 28, "direction": 1},
                    "j11": {"id": 11, "模式": "多圈", "home_present_raw": 0, "phase": 28, "direction": 1},
                    "j12": {"id": 12, "模式": "多圈", "home_present_raw": 0, "phase": 28, "direction": 1},
                    "j13": {"id": 13, "模式": "多圈", "home_present_raw": 0, "phase": 28, "direction": 1},
                    "j14": {
                        "id": 14,
                        "模式": "单圈",
                        "zero_present_raw": 2048,
                        "range_min": 1000,
                        "range_max": 3000,
                        "direction": 1,
                    },
                    "j15": {"id": 15, "模式": "多圈", "home_present_raw": 0, "phase": 28, "direction": 1},
                    "_meta": {"gripper_available": False},
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        manager = CalibrationManager(path, {"transport": {"gripper_available": False}})
        report = manager.calibration_report()
        assert report["允许真机移动"] is True
        assert manager.get("j11")["id"] == 11


def test_action_path_and_logger_helpers() -> None:
    assert RESOLVED_ACTION_ROOT == ACTION_ROOT
    assert ensure_action_project_root_on_path() == PROJECT_ROOT
    assert resolve_action_path("动作库/demo.json") == (ACTION_ROOT / "动作库/demo.json").resolve()
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "logs" / "motion.log"
        MotionLogger(path).log("unit_test", ok=True)
        payload = json.loads(path.read_text(encoding="utf-8").strip())
        assert payload["event"] == "unit_test"
        assert payload["ok"] is True


def test_kinematics_path_and_config_helpers() -> None:
    assert RESOLVED_KINEMATICS_ROOT == KINEMATICS_ROOT
    assert ensure_kinematics_project_root_on_path() == PROJECT_ROOT
    assert resolve_kinematics_path("urdf/soarmoce_urdf.urdf") == (KINEMATICS_ROOT / "urdf/soarmoce_urdf.urdf").resolve()
    assert 解析资源路径("urdf/soarmoce_urdf.urdf") == (KINEMATICS_ROOT / "urdf/soarmoce_urdf.urdf").resolve()
    config = 加载运动学配置(KINEMATICS_ROOT / "运动学配置.yaml")
    assert config["robot"]["sdk_joint_names"] == ["j10", "j11", "j12", "j13", "j14", "j15"]
    assert config["robot"]["target_frame"] == "Link_6"


def test_sim_path_pose_and_action_helpers() -> None:
    assert RESOLVED_SIM_ROOT == SIM_ROOT
    assert ensure_sim_project_root_on_path() == PROJECT_ROOT
    assert resolve_sim_path("配置_config.yaml") == (SIM_ROOT / "配置_config.yaml").resolve()

    config = {
        "关节": [
            {"名称": "J10_底盘导轨", "默认角度": 0, "最小角度": -100, "最大角度": 100},
            {"名称": "J11_底座旋转", "默认角度": 0, "最小角度": -180, "最大角度": 180},
            {"名称": "J12_肩部抬升", "默认角度": 0, "最小角度": -90, "最大角度": 90},
            {"名称": "J13_肘部弯曲", "默认角度": 0, "最小角度": -120, "最大角度": 120},
            {"名称": "J14_腕部俯仰", "默认角度": 0, "最小角度": -90, "最大角度": 90},
            {"名称": "J15_腕部旋转", "默认角度": 0, "最小角度": -180, "最大角度": 180},
        ],
        "夹爪": {"默认开合": 50, "最小开合": 0, "最大开合": 100},
    }
    robot = 机械臂模型(config)
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        poses = 姿态管理器(root / "poses.json", 默认姿态={"初始姿态": {"关节角度": [0, 0, 0, 0, 0, 0], "夹爪": 50}})
        assert poses.获取姿态("初始姿态")["关节角度"] == [0, 0, 0, 0, 0, 0]
        poses.保存姿态("展示", {"关节角度": [0, 0, 10, 20, 0, 0], "夹爪": 60})
        assert "展示" in poses.列出姿态()

        action_dir = root / "actions"
        action_dir.mkdir()
        (action_dir / "demo.json").write_text(
            json.dumps(
                {
                    "名称": "demo",
                    "步骤": [
                        {"名称": "pose1", "关节角度": [0, 0, 10, 20, 0, 0], "夹爪": 55, "插值步数": 1, "等待秒": 0}
                    ],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        result = 动作播放器(robot, action_dir).播放动作("demo")
        assert result.成功 is True
        state = robot.获取当前状态()
        assert state["关节角度"] == [0, 0, 10, 20, 0, 0]
        assert state["夹爪"] == 55


def main() -> None:
    test_axis_step()
    test_clamp_helpers()
    test_motion_tuning_normalization_helpers()
    test_joint_target_normalization_helpers()
    test_state_joint_extraction_helpers()
    test_gripper_state_normalization_helpers()
    test_multi_turn_state_normalization_helpers()
    test_raw_present_position_normalization_helpers()
    test_motion_progress_payload_helper()
    test_sequence_player_uses_normalized_playback_speed()
    test_sequence_player_default_joint_speed_limits_are_shared()
    test_action_sequence_summary_helper()
    test_tcp_pose_payload_helper()
    test_safe_callback_helper()
    test_exception_context_helper()
    test_motion_easing_helpers()
    test_target_guard()
    test_smoothed_offset()
    test_vision_payload_unwrap()
    test_api_payload_helpers()
    test_state_tcp_pose_helper()
    test_rail_sweep_planner()
    test_cinematic_runtime_preserves_capture_direction()
    test_event_json_line_keeps_motion_log_shape()
    test_common_io_helpers()
    test_common_path_helpers()
    test_config_resolver_helper()
    test_calibration_path_resolver_helper()
    test_vision_path_resolver()
    test_web_backend_path_and_state_helpers()
    test_gui_path_helper()
    test_agent_path_logger_and_session_helpers()
    test_integration_path_config_and_state_helpers()
    test_real_control_path_mapping_and_calibration_helpers()
    test_action_path_and_logger_helpers()
    test_kinematics_path_and_config_helpers()
    test_sim_path_pose_and_action_helpers()
    print("公共控制桥接 helper 测试通过。")


if __name__ == "__main__":
    main()
