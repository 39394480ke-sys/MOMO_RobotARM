"""使用模拟 latest payload 计算 joint-step，不调用真实机械臂。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

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
    print("dry-run 视觉跟随测试通过：没有调用真实机械臂。")


if __name__ == "__main__":
    main()
