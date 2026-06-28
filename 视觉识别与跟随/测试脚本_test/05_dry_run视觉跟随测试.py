"""使用模拟 latest payload 计算 joint-step，不调用真实机械臂。"""

from __future__ import annotations

import json

from 视觉测试路径_test_paths import VISION_ROOT as BASE_DIR

from vision.视觉跟随_controller import VisionFollowController
from 视觉主程序_main import load_config


def main() -> None:
    config = load_config(BASE_DIR / "视觉配置.yaml")
    payload = {
        "detected": True,
        "smoothed_offset": {"valid": True, "ndx": 0.2, "ndy": -0.2},
        "offset": {"in_dead_zone": False},
    }
    controller = VisionFollowController(config, latest_provider=lambda: payload, dry_run=True)
    result = controller.step_once()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    assert result["dry_run"] is True
    assert result["commands"], "应该生成至少一个 joint-step 命令"
    joints = {item["joint_key"] for item in result["commands"]}
    assert "j10" not in joints, "普通视觉跟随不应该控制 J10 导轨"
    assert {"j11", "j13"}.issubset(joints), f"普通视觉跟随应控制 J11/J13，实际：{joints}"
    face_pan_steps = [abs(float(item["delta_deg"])) for item in result["commands"] if item["joint_key"] == "j11"]
    assert face_pan_steps and face_pan_steps[0] > 0.25, f"人脸跟随不应套用框选主体保守上限，实际：{face_pan_steps}"

    manual_payload = {
        "detected": True,
        "has_target": True,
        "target_source": "manual_tracker",
        "tracking_state": "tracking",
        "target": {"source": "manual_tracker", "bbox": [100, 100, 80, 120]},
        "smoothed_offset": {"valid": True, "ndx": 0.2, "ndy": -0.2},
        "offset": {"in_dead_zone": False},
    }
    manual_controller = VisionFollowController(config, latest_provider=lambda: manual_payload, dry_run=True)
    manual_first = manual_controller.step_once()
    print(json.dumps(manual_first, ensure_ascii=False, indent=2))
    manual_commands = manual_first["commands"]
    assert manual_commands, "框选主体第一帧应该生成保守跟随命令"
    manual_pan_steps = [abs(float(item["delta_deg"])) for item in manual_commands if item["joint_key"] == "j11"]
    assert manual_pan_steps and manual_pan_steps[0] > 0.25, f"框选主体应尊重界面步径参数，不应被硬限制到 0.25 deg，实际：{manual_commands}"
    manual_second = manual_controller.step_once()
    print(json.dumps(manual_second, ensure_ascii=False, indent=2))
    assert not manual_second["commands"], f"框选主体连续两帧应被节流，实际：{manual_second['commands']}"

    speed_config = json.loads(json.dumps(config, ensure_ascii=False))
    speed_follow = speed_config.setdefault("follow", {})
    speed_follow.update(
        {
            "enabled_follow_joints": ["j11"],
            "pan_gain_deg_per_norm": 4.8,
            "max_pan_step_deg": 5.0,
            "min_pan_step_deg": 0.0,
            "pan_min_step_zone_norm": 1.0,
            "manual_tracker_profile": {
                "dead_zone_norm": 0.06,
                "resume_zone_norm": 0.10,
                "gain_scale": 1.0,
                "max_step_deg": 0.0,
                "min_step_deg": -1.0,
                "min_step_zone_norm": -1.0,
            },
        }
    )
    slow_config = json.loads(json.dumps(speed_config, ensure_ascii=False))
    slow_config["follow"]["speed_percent"] = 30
    fast_config = json.loads(json.dumps(speed_config, ensure_ascii=False))
    fast_config["follow"]["speed_percent"] = 100
    slow_step = VisionFollowController(slow_config, latest_provider=lambda: manual_payload, dry_run=True).step_once()["commands"][0]["delta_deg"]
    fast_step = VisionFollowController(fast_config, latest_provider=lambda: manual_payload, dry_run=True).step_once()["commands"][0]["delta_deg"]
    assert abs(float(fast_step)) > abs(float(slow_step)), f"速度百分比应缩放视觉补偿步径，slow={slow_step}, fast={fast_step}"

    rail_config = json.loads(json.dumps(config, ensure_ascii=False))
    rail_config.setdefault("follow", {})["rail_cinematic"] = {
        "enabled": True,
        "joint": "j10",
        "start_mm": -140,
        "end_mm": 140,
        "speed_mm_s": 30.0,
        "bounce": False,
    }
    rail_controller = VisionFollowController(rail_config, latest_provider=lambda: payload, dry_run=True)
    rail_result = rail_controller.step_once()
    print(json.dumps(rail_result, ensure_ascii=False, indent=2))
    rail_joints = {item["joint_key"] for item in rail_result["commands"]}
    assert "j10" in rail_joints, "开启导轨运镜后应该生成 J10 小步进"
    assert {"j11", "j13"}.issubset(rail_joints), f"导轨运镜不应替代 J11/J13 人脸跟随，实际：{rail_joints}"
    print("dry-run 视觉跟随测试通过：参数、速度缩放、框选节流和导轨运镜正常。")


if __name__ == "__main__":
    main()
