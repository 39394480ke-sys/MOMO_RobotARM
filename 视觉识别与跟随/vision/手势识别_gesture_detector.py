"""可选 MediaPipe 手势识别。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import cv2  # type: ignore
except Exception:  # pragma: no cover
    cv2 = None  # type: ignore


class GestureDetector:
    def __init__(self, config: dict[str, Any], base_dir: str | Path | None = None):
        self.config = dict(config or {})
        self.base_dir = Path(base_dir or ".").resolve()
        self.enabled = bool(self.config.get("enabled", True))
        self.backend = str(self.config.get("backend", "mediapipe"))
        self.model_path = self._resolve_path(str(self.config.get("model_path", "weights/gesture_recognizer.task")))
        self.required_stable_frames = int(self.config.get("stable_frames", 4))
        self.recognizer: Any | None = None
        self.mp: Any | None = None
        self.available = False
        self.last_error = ""
        self._last_raw = ""
        self._same_count = 0
        self._stable = ""
        self._init_recognizer()

    def detect(self, frame: Any) -> dict[str, Any]:
        if not self.enabled:
            return self._unavailable("手势识别已在配置中关闭。")
        if not self.available or self.recognizer is None or self.mp is None:
            return self._unavailable(self.last_error)
        if cv2 is None:
            return self._unavailable("OpenCV 未安装，无法转换手势识别画面。")
        try:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            image = self.mp.Image(image_format=self.mp.ImageFormat.SRGB, data=rgb)
            result = self.recognizer.recognize(image)
            raw = ""
            confidence = 0.0
            if result.gestures and result.gestures[0]:
                category = result.gestures[0][0]
                raw = str(category.category_name)
                confidence = float(category.score)
            stable = self._update_stable(raw)
            return {
                "available": True,
                "raw": raw,
                "stable": stable,
                "confidence": round(confidence, 4),
                "stable_frames": self._same_count if raw else 0,
                "message": "",
            }
        except Exception as exc:
            return {
                "available": True,
                "raw": "",
                "stable": self._stable,
                "confidence": 0.0,
                "stable_frames": self._same_count,
                "message": f"手势识别失败：{exc}",
            }

    def _init_recognizer(self) -> None:
        if not self.enabled:
            self.last_error = "手势识别已关闭。"
            return
        if self.backend != "mediapipe":
            self.last_error = f"未知手势识别后端：{self.backend}"
            return
        try:
            import mediapipe as mp  # type: ignore

            if not self.model_path.exists():
                self.last_error = f"MediaPipe 手势模型不存在：{self.model_path}。手势功能不可用，但人脸检测不受影响。"
                return
            BaseOptions = mp.tasks.BaseOptions
            GestureRecognizer = mp.tasks.vision.GestureRecognizer
            GestureRecognizerOptions = mp.tasks.vision.GestureRecognizerOptions
            VisionRunningMode = mp.tasks.vision.RunningMode
            options = GestureRecognizerOptions(
                base_options=BaseOptions(model_asset_path=str(self.model_path)),
                running_mode=VisionRunningMode.IMAGE,
            )
            self.recognizer = GestureRecognizer.create_from_options(options)
            self.mp = mp
            self.available = True
            self.last_error = ""
        except ImportError as exc:
            self.last_error = f"mediapipe 未安装，手势识别不可用。请执行：pip install mediapipe。原始错误：{exc}"
        except Exception as exc:
            self.last_error = f"MediaPipe 手势识别初始化失败：{exc}"

    def _update_stable(self, raw: str) -> str:
        if not raw:
            self._last_raw = ""
            self._same_count = 0
            self._stable = ""
            return ""
        if raw == self._last_raw:
            self._same_count += 1
        else:
            self._last_raw = raw
            self._same_count = 1
        if self._same_count >= self.required_stable_frames:
            self._stable = raw
        return self._stable

    def _unavailable(self, message: str) -> dict[str, Any]:
        return {
            "available": False,
            "raw": "",
            "stable": "",
            "confidence": 0.0,
            "stable_frames": 0,
            "message": message or "手势识别不可用。",
        }

    def _resolve_path(self, value: str) -> Path:
        path = Path(value)
        if path.is_absolute():
            return path
        return self.base_dir / path
