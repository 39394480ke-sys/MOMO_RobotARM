"""运行依赖检查并给出建议。"""

from __future__ import annotations

import json

from integration.config_loader import load_config
from integration.dependency_checker import DependencyChecker


SUGGESTIONS = {
    "PyQt5": "缺少 PyQt5：如果要运行 GUI，请安装 pip install PyQt5",
    "lerobot": "缺少 lerobot：dry-run 可用，真实硬件不可用",
    "feetech-servo-sdk": "缺少 feetech-servo-sdk：dry-run 可用，真实硬件不可用",
    "opencv-contrib-python": "缺少 opencv-contrib-python：如果要运行视觉服务，请安装 pip install opencv-contrib-python",
    "sounddevice": "缺少 sounddevice：如果要运行语音录放，请安装 pip install sounddevice",
    "mediapipe": "缺少 mediapipe：如果要运行手势识别，请安装 pip install mediapipe",
    "pybullet": "缺少 pybullet：如果要运行 3D 仿真，请安装 pip install pybullet",
}


def main() -> int:
    result = DependencyChecker(load_config()).check_all()
    print(json.dumps(result, ensure_ascii=False, indent=2))
    missing_required = [name for name, ok in result["required"].items() if not ok]
    missing_optional = [name for name, ok in result["optional"].items() if not ok]
    for name in missing_required + missing_optional:
        print(SUGGESTIONS.get(name, f"缺少 {name}：请按该模块 README 安装。"))
    return 0 if not missing_required else 1


if __name__ == "__main__":
    raise SystemExit(main())

