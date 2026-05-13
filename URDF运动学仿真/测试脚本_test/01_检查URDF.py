from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from URDF检查_urdf_inspector import 检查URDF
from 运动学模型_kinematics_model import 打印_json


if __name__ == "__main__":
    result = 检查URDF()
    打印_json(result)
    raise SystemExit(0 if result.get("ok") else 1)
