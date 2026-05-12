"""姿态管理器。

姿态管理只负责“存”和“取”：
- 从 JSON 文件加载姿态库
- 保存当前姿态到 JSON
- 根据名称读取姿态
- 删除姿态
- 列出姿态名称

它不检查角度是否合法，也不移动机械臂。
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any


class 姿态管理器:
    """管理多个命名姿态。"""

    def __init__(self, 姿态库路径: str | Path, 默认姿态: dict[str, Any] | None = None):
        self.姿态库路径 = Path(姿态库路径)
        self.默认姿态 = 默认姿态 or {}
        self.姿态库: dict[str, dict[str, Any]] = {}
        self.加载全部姿态()
        self.补齐默认姿态()

    def 加载全部姿态(self) -> dict[str, dict[str, Any]]:
        """从 JSON 文件加载姿态库。文件不存在时使用空库。"""

        if not self.姿态库路径.exists():
            self.姿态库 = {}
            return self.姿态库

        try:
            with self.姿态库路径.open("r", encoding="utf-8") as 文件:
                数据 = json.load(文件)
        except json.JSONDecodeError as 错误:
            raise ValueError(f"姿态库 JSON 格式错误：{错误}") from 错误

        if not isinstance(数据, dict):
            raise ValueError("姿态库文件的最外层必须是 JSON 对象。")

        self.姿态库 = 数据
        return self.姿态库

    def 保存全部姿态(self) -> None:
        """把当前姿态库写回 JSON 文件。"""

        self.姿态库路径.parent.mkdir(parents=True, exist_ok=True)
        with self.姿态库路径.open("w", encoding="utf-8") as 文件:
            json.dump(self.姿态库, 文件, ensure_ascii=False, indent=2)
            文件.write("\n")

    def 补齐默认姿态(self) -> None:
        """首次运行时写入配置中的默认姿态。"""

        有新增 = False
        for 名称, 姿态 in self.默认姿态.items():
            if 名称 not in self.姿态库:
                self.姿态库[名称] = self.整理姿态数据(姿态, 姿态.get("说明", "配置中的默认姿态。"))
                有新增 = True

        if 有新增:
            self.保存全部姿态()

    def 保存姿态(self, 名称: str, 状态: dict[str, Any], 说明: str = "") -> None:
        """保存一个命名姿态。同名姿态会被覆盖。"""

        名称 = 名称.strip()
        if not 名称:
            raise ValueError("姿态名称不能为空。")

        self.姿态库[名称] = self.整理姿态数据(状态, 说明)
        self.保存全部姿态()

    def 获取姿态(self, 名称: str) -> dict[str, Any] | None:
        """根据名称读取姿态。返回副本，避免外部直接改库。"""

        姿态 = self.姿态库.get(名称)
        if 姿态 is None:
            return None
        return deepcopy(姿态)

    def 删除姿态(self, 名称: str) -> bool:
        """删除一个姿态。存在并删除成功返回 True。"""

        if 名称 not in self.姿态库:
            return False

        del self.姿态库[名称]
        self.保存全部姿态()
        return True

    def 列出姿态(self) -> list[str]:
        """返回姿态名称列表。"""

        return sorted(self.姿态库.keys())

    @staticmethod
    def 整理姿态数据(状态: dict[str, Any], 说明: str = "") -> dict[str, Any]:
        """把不同来源的状态整理成统一 JSON 结构。"""

        if "关节角度" not in 状态:
            raise ValueError("姿态数据必须包含“关节角度”。")

        姿态 = {
            "关节角度": list(状态["关节角度"]),
            "夹爪": 状态.get("夹爪", 50),
            "说明": 说明 or 状态.get("说明", ""),
        }
        return 姿态
