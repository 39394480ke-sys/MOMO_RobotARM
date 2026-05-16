"""运行阶段四标定检查。"""

from __future__ import annotations

import json

from integration.calibration_checker import CalibrationChecker
from integration.config_loader import load_config


def main() -> int:
    result = CalibrationChecker(load_config()).check()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not result.get("ok"):
        print("请运行：")
        print("python ../真实舵机控制/标定程序_calibrate.py")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

