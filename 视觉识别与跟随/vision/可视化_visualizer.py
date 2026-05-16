"""视觉调试画面绘制。"""

from __future__ import annotations

from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


class Visualizer:
    def draw(self, frame: Any, result: dict[str, Any]) -> Any:
        if frame is None or cv2 is None:
            return frame
        canvas = frame.copy()
        faces = result.get("faces", []) or []
        target = result.get("target_face")
        target_bbox = target.get("bbox") if isinstance(target, dict) else None

        for face in faces:
            bbox = face.get("bbox", [0, 0, 0, 0])
            x, y, w, h = [int(round(float(v))) for v in bbox[:4]]
            color = (0, 210, 255) if bbox == target_bbox else (80, 220, 80)
            cv2.rectangle(canvas, (x, y), (x + w, y + h), color, 2)
            cx, cy = [int(round(float(v))) for v in face.get("center", [x + w / 2, y + h / 2])[:2]]
            cv2.circle(canvas, (cx, cy), 4, color, -1)
            cv2.putText(canvas, f"{face.get('score', 0):.2f}", (x, max(18, y - 6)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)

        offset = result.get("offset", {}) or {}
        desired = offset.get("desired_center")
        target_center = offset.get("target_center")
        if desired:
            dcx, dcy = [int(round(float(v))) for v in desired[:2]]
            cv2.drawMarker(canvas, (dcx, dcy), (255, 120, 40), cv2.MARKER_CROSS, 24, 2)
            cv2.circle(canvas, (dcx, dcy), 8, (255, 120, 40), 1)
        if target_center and desired:
            tcx, tcy = [int(round(float(v))) for v in target_center[:2]]
            dcx, dcy = [int(round(float(v))) for v in desired[:2]]
            cv2.arrowedLine(canvas, (dcx, dcy), (tcx, tcy), (255, 255, 0), 2, tipLength=0.18)

        gesture = result.get("gesture", {}) or {}
        fps = float(result.get("fps", 0.0) or 0.0)
        lines = [
            f"detected: {bool(result.get('detected'))}",
            f"ndx: {float(offset.get('ndx', 0.0)):.3f}  ndy: {float(offset.get('ndy', 0.0)):.3f}",
            f"dir: {(result.get('direction') or {}).get('combined', 'center')}",
            f"gesture: {gesture.get('stable') or gesture.get('raw') or '-'}",
            f"fps: {fps:.1f}",
        ]
        y = 24
        for line in lines:
            cv2.putText(canvas, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (20, 20, 20), 3)
            cv2.putText(canvas, line, (12, y), cv2.FONT_HERSHEY_SIMPLEX, 0.58, (255, 255, 255), 1)
            y += 24
        return canvas


def make_placeholder_frame(message: str = "camera unavailable", width: int = 640, height: int = 480) -> Any | None:
    if cv2 is None:
        return None
    try:
        import numpy as np  # type: ignore

        frame = np.zeros((int(height), int(width), 3), dtype=np.uint8)
        frame[:] = (35, 35, 35)
        cv2.putText(frame, message[:60], (30, int(height) // 2), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (230, 230, 230), 2)
        return frame
    except Exception:
        return None
