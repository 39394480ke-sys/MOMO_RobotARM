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
    assert all(abs(float(item["delta_deg"])) <= 0.25 for item in manual_commands), f"框选主体单步应限制在 0.25 deg 内，实际：{manual_commands}"
    manual_second = manual_controller.step_once()
    print(json.dumps(manual_second, ensure_ascii=False, indent=2))
    assert not manual_second["commands"], f"框选主体连续两帧应被节流，实际：{manual_second['commands']}"

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
    print("dry-run 视觉跟随测试通过：普通跟随不动 J10，导轨运镜会追加 J10。")


if __name__ == "__main__":
    main()
