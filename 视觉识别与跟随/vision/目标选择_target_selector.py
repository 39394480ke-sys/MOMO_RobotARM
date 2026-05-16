"""视觉目标选择。"""

from __future__ import annotations

from typing import Any


class TargetSelector:
    def __init__(self, config: dict[str, Any]):
        self.config = dict(config or {})
        self.strategy = str(self.config.get("selection_strategy", "largest_face"))

    def select(self, faces: list[dict[str, Any]]) -> dict[str, Any]:
        if not faces:
            return {
                "detected": False,
                "target_face": None,
                "selection_strategy": self.strategy,
                "message": "没有检测到人脸。",
            }

        if self.strategy != "largest_face":
            # 第一版只实现 largest_face，其他策略先退回最大人脸。
            strategy = "largest_face"
        else:
            strategy = self.strategy

        target = max(faces, key=lambda item: float(item.get("area", 0.0)))
        return {
            "detected": True,
            "target_face": target,
            "selection_strategy": strategy,
            "message": "已选择面积最大的人脸。",
        }
