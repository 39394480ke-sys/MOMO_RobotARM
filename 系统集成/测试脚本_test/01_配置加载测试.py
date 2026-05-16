from __future__ import annotations

import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE_DIR))

from integration.config_loader import load_config, resolve_path


def main() -> int:
    config = load_config()
    assert config["project"]["name"] == "我的MomoAgent复刻"
    missing = []
    for key, path in config.get("paths", {}).items():
        resolved = resolve_path(path, BASE_DIR)
        if not resolved.exists():
            missing.append(f"{key}: {resolved}")
    for service in config.get("services", {}).values():
        cwd = resolve_path(service["cwd"], BASE_DIR)
        if not cwd.exists():
            missing.append(f"{service['name']} cwd: {cwd}")
    if missing:
        raise AssertionError("路径不存在：\n" + "\n".join(missing))
    print("配置加载测试通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

