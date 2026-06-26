"""不需要摄像头的 ndx / ndy 计算测试。"""

from __future__ import annotations

import json

from 视觉测试路径_test_paths import VISION_ROOT as BASE_DIR

from vision.偏移计算_offset_calculator import OffsetCalculator
from 视觉主程序_main import load_config


def main() -> None:
    config = load_config(BASE_DIR / "视觉配置.yaml")
    calculator = OffsetCalculator(config.get("target", {}))
    samples = [
        ("center", [320, 201.6]),
        ("right_up", [440, 171.6]),
        ("left_down", [240, 260]),
    ]
    for name, center in samples:
        result = calculator.calculate(640, 480, center)
        print(name)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
