"""OpenCV YuNet 人脸检测。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .路径工具_path_utils import resolve_vision_path

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


class FaceDetector:
    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.backend = str(self.config.get("face_backend", "opencv_yunet"))
        self.model_path = resolve_vision_path(
            str(self.config.get("face_model_path", "weights/face_detection_yunet_2023mar.onnx")),
            self.base_dir,
        )
        self.score_threshold = float(self.config.get("face_score_threshold", 0.75))
        self.nms_threshold = float(self.config.get("face_nms_threshold", 0.3))
        self.top_k = int(self.config.get("face_top_k", 5000))
        self.detector: Any | None = None
        self.input_size: tuple[int, int] | None = None
        self.available = False
        self.last_error = ""
        self._check_available()

    def detect(self, frame: Any) -> dict[str, Any]:
        if not self.available:
            return {"available": False, "error": self.last_error, "faces": []}
        if frame is None:
            return {"available": True, "error": "输入画面为空。", "faces": []}

        height, width = frame.shape[:2]
        try:
            self._ensure_detector(width, height)
            if self.detector is None:
                return {"available": False, "error": self.last_error, "faces": []}
            _ok, faces_raw = self.detector.detect(frame)
        except Exception as exc:
            self.last_error = f"YuNet 检测失败：{exc}"
            return {"available": False, "error": self.last_error, "faces": []}

        faces: list[dict[str, Any]] = []
        if faces_raw is None:
            return {"available": True, "error": "", "faces": faces}

        frame_area = max(1.0, float(width * height))
        for row in faces_raw:
            values = [float(v) for v in row.tolist()]
            x, y, w, h = values[:4]
            score = float(values[-1])
            x = max(0.0, min(float(width - 1), x))
            y = max(0.0, min(float(height - 1), y))
            w = max(0.0, min(float(width) - x, w))
            h = max(0.0, min(float(height) - y, h))
            area = float(w * h)
            faces.append(
                {
                    "bbox": [round(x, 2), round(y, 2), round(w, 2), round(h, 2)],
                    "center": [round(x + w / 2.0, 2), round(y + h / 2.0, 2)],
                    "score": round(score, 4),
                    "area": round(area, 2),
                    "area_ratio": round(area / frame_area, 6),
                }
            )
        return {"available": True, "error": "", "faces": faces}

    def _check_available(self) -> None:
        if cv2 is None:
            self.last_error = "OpenCV 未安装，请先执行：pip install opencv-contrib-python"
            self.available = False
            return
        if not hasattr(cv2, "FaceDetectorYN_create"):
            self.last_error = "当前 OpenCV 没有 FaceDetectorYN_create，请安装 opencv-contrib-python。"
            self.available = False
            return
        if not self.model_path.exists():
            self.last_error = f"YuNet 权重文件不存在：{self.model_path}。请放入 face_detection_yunet_2023mar.onnx。"
            self.available = False
            return
        self.available = True
        self.last_error = ""

    def _ensure_detector(self, width: int, height: int) -> None:
        input_size = (int(width), int(height))
        if self.detector is not None and self.input_size == input_size:
            return
        if cv2 is None:
            self.detector = None
            return
        try:
            self.detector = cv2.FaceDetectorYN_create(
                str(self.model_path),
                "",
                input_size,
                self.score_threshold,
                self.nms_threshold,
                self.top_k,
            )
        except TypeError:
            self.detector = cv2.FaceDetectorYN_create(
                model=str(self.model_path),
                config="",
                input_size=input_size,
                score_threshold=self.score_threshold,
                nms_threshold=self.nms_threshold,
                top_k=self.top_k,
            )
        self.input_size = input_size
