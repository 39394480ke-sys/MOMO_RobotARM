from __future__ import annotations

import 系统测试路径_test_paths  # noqa: F401

from integration.config_loader import load_config
from integration.dependency_checker import DependencyChecker


def main() -> int:
    result = DependencyChecker(load_config()).check_all()
    assert "required" in result
    assert "optional" in result
    assert isinstance(result["optional"], dict)
    missing_required = [name for name, ok in result["required"].items() if not ok]
    if missing_required:
        raise AssertionError(f"必需依赖缺失：{missing_required}")
    print("依赖检查测试通过。optional 不要求全部存在。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
