from __future__ import annotations

import 系统测试路径_test_paths  # noqa: F401

from integration.config_loader import load_config, resolve_path
from integration.path_utils import INTEGRATION_DIR


def main() -> int:
    config = load_config()
    assert config["project"]["name"] == "我的机械臂控制项目"
    missing = []
    for key, path in config.get("paths", {}).items():
        resolved = resolve_path(path, INTEGRATION_DIR)
        if not resolved.exists():
            missing.append(f"{key}: {resolved}")
    for service in config.get("services", {}).values():
        cwd = resolve_path(service["cwd"], INTEGRATION_DIR)
        if not cwd.exists():
            missing.append(f"{service['name']} cwd: {cwd}")
    if missing:
        raise AssertionError("路径不存在：\n" + "\n".join(missing))
    print("配置加载测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
