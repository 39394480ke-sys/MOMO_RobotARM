from __future__ import annotations

import 运动学测试路径_test_paths  # noqa: F401

from URDF检查_urdf_inspector import 检查URDF
from 运动学模型_kinematics_model import 打印_json


if __name__ == "__main__":
    result = 检查URDF()
    打印_json(result)
    raise SystemExit(0 if result.get("ok") else 1)
