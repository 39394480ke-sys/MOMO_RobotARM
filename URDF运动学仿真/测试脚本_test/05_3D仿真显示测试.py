from __future__ import annotations

import time

from importlib import import_module

import 运动学测试路径_test_paths  # noqa: F401


if __name__ == "__main__":
    viewer_module = import_module("3D仿真_pybullet_viewer")
    viewer = None
    try:
        viewer = viewer_module.PyBulletViewer()
        for joints in ([0, 0, 0, 0, 0, 0], [10, 0, 25, 40, 10, 0], [20, 15, 25, 40, -10, 0]):
            result = viewer.set_joints_deg(list(joints))
            print(result)
            time.sleep(1.0)
    except Exception as exc:
        print(f"错误：{exc}")
        raise SystemExit(1)
    finally:
        if viewer is not None:
            viewer.close()
