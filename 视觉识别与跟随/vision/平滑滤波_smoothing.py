"""EMA 平滑滤波。"""

from __future__ import annotations

import time
from typing import Any


class OffsetSmoother:
    def __init__(self, config: dict[str, Any]):
        self.config = dict(config or {})
        self.enabled = bool(self.config.get("enabled", True))
        self.alpha = float(self.config.get("alpha", 0.35))
        self.lost_target_keep_sec = float(self.config.get("lost_target_keep_sec", 0.8))
        self.previous: dict[str, float] | None = None
        self.last_seen_at = 0.0

    def update(self, offset: dict[str, Any] | None) -> dict[str, Any]:
        now = time.time()
        if not offset or not offset.get("valid", False):
            if self.previous is not None and now - self.last_seen_at <= self.lost_target_keep_sec:
                return {"valid": False, "ndx": round(self.previous["ndx"], 6), "ndy": round(self.previous["ndy"], 6), "kept": True}
            self.reset()
            return {"valid": False, "ndx": 0.0, "ndy": 0.0, "kept": False}

        current = {"ndx": float(offset.get("ndx", 0.0)), "ndy": float(offset.get("ndy", 0.0))}
        self.last_seen_at = now

        if not self.enabled or self.previous is None:
            self.previous = current
        else:
            alpha = max(0.0, min(1.0, self.alpha))
            self.previous = {
                "ndx": alpha * current["ndx"] + (1.0 - alpha) * self.previous["ndx"],
                "ndy": alpha * current["ndy"] + (1.0 - alpha) * self.previous["ndy"],
            }

        return {"valid": True, "ndx": round(self.previous["ndx"], 6), "ndy": round(self.previous["ndy"], 6), "kept": False}

    def reset(self) -> None:
        self.previous = None
        self.last_seen_at = 0.0
