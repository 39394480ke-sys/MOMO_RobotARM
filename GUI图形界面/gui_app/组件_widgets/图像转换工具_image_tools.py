"""GUI 图像转换小工具。"""

from __future__ import annotations

from typing import Any

from PyQt5.QtGui import QImage, QPixmap


def bgr_frame_to_pixmap(frame: Any) -> tuple[QPixmap, tuple[int, int]]:
    """将 OpenCV BGR 帧转换为 QPixmap，并返回 ``(width, height)``。"""
    import cv2  # type: ignore
    import numpy as np  # type: ignore

    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    rgb = np.ascontiguousarray(rgb)
    height, width, channels = rgb.shape
    image = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888).copy()
    return QPixmap.fromImage(image), (int(width), int(height))
