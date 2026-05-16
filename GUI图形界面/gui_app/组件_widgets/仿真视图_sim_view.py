"""常驻 3D 机械臂视图。"""

from __future__ import annotations

import math
import sys
from pathlib import Path
from typing import Any

from PyQt5.QtCore import QPoint, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from gui_app.控制器桥接_controller_bridge import JOINT_ORDER


class _InteractiveRenderLabel(QLabel):
    def __init__(self, owner: "SimView"):
        super().__init__("正在加载 3D 视图...")
        self.owner = owner
        self.last_pos: QPoint | None = None
        self.setMouseTracking(True)
        self.setCursor(Qt.OpenHandCursor)

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.LeftButton:
            self.last_pos = event.pos()
            self.setCursor(Qt.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self.last_pos is not None and event.buttons() & Qt.LeftButton:
            delta = event.pos() - self.last_pos
            self.last_pos = event.pos()
            self.owner.rotate_camera(delta.x(), delta.y())
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        self.last_pos = None
        self.setCursor(Qt.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event) -> None:
        self.owner.zoom_camera(event.angleDelta().y())
        event.accept()

    def resizeEvent(self, event) -> None:
        self.owner.schedule_render(120)
        super().resizeEvent(event)


class SimView(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(0)

        viewport = QWidget()
        viewport.setObjectName("SimViewport")
        viewport_layout = QGridLayout(viewport)
        viewport_layout.setContentsMargins(0, 0, 0, 0)
        viewport_layout.setSpacing(0)
        self.label = _InteractiveRenderLabel(self)
        self.label.setAlignment(Qt.AlignCenter)
        self.label.setMinimumSize(260, 220)
        self.label.setStyleSheet("background: #f4f7fb; border: 1px solid #cfd7e2; border-radius: 6px; padding: 0;")
        self.label.setScaledContents(True)
        self.label.setWordWrap(True)
        viewport_layout.addWidget(self.label, 0, 0)

        toolbar_widget = QWidget()
        toolbar_widget.setObjectName("ViewportToolbar")
        toolbar = QVBoxLayout(toolbar_widget)
        toolbar.setContentsMargins(6, 6, 6, 6)
        toolbar.setSpacing(5)
        for text, slot in (
            ("↻", self.reset_camera),
            ("FRONT", self.front_camera),
            ("TOP", self.top_camera),
            ("SIDE", self.side_camera),
            ("FIT", self.fit_camera),
        ):
            button = QPushButton(text)
            button.setObjectName("ViewportToolButton")
            button.setToolTip({"↻": "重置视角", "FRONT": "正视", "TOP": "俯视", "SIDE": "侧视", "FIT": "适配模型"}[text])
            button.clicked.connect(slot)
            toolbar.addWidget(button)
        toolbar.addStretch(1)
        viewport_layout.addWidget(toolbar_widget, 0, 0, Qt.AlignRight | Qt.AlignTop)
        toolbar_widget.raise_()
        layout.addWidget(viewport, 1)

        self.model = None
        self.pb = None
        self.current_joints_deg = {joint: 0.0 for joint in JOINT_ORDER}
        self.current_tcp: dict[str, Any] | None = None
        self.target_tcp: dict[str, Any] | None = None
        self.target_label = ""
        self._debug_ids: list[int] = []
        self._marker_body_ids: list[int] = []
        self.camera_yaw_deg = -55.0
        self.camera_pitch_deg = 28.0
        self.camera_distance = 0.62
        self.camera_target = [0.0, 0.0, 0.16]
        self._last_view_matrix: list[float] | None = None
        self._last_projection_matrix: list[float] | None = None
        self._render_pending = False
        self._render_in_progress = False
        self.visual_warning = ""
        self._init_model()
        self.schedule_render(0)

    def _init_model(self) -> None:
        try:
            import pybullet as pybullet
            project_root = Path(__file__).resolve().parents[3]
            kinematics_path = str(project_root / "URDF运动学仿真")
            if kinematics_path not in sys.path:
                sys.path.insert(0, kinematics_path)
            from 运动学模型_kinematics_model import 创建运动学模型

            self.pb = pybullet
            self.model = 创建运动学模型(use_gui=False)
        except Exception as exc:
            self.model = None
            self.pb = None
            self.label.setText(f"3D 视图不可用：{exc}")

    def update_state(self, joints_deg: dict | None, tcp_pose: dict | None = None) -> None:
        if joints_deg:
            for joint in JOINT_ORDER:
                if joint in joints_deg:
                    self.current_joints_deg[joint] = float(joints_deg[joint])
        self.current_tcp = tcp_pose if isinstance(tcp_pose, dict) else None
        self.schedule_render(80)

    def set_target_pose(self, tcp_pose: dict | None, label: str = "目标末端") -> None:
        self.target_tcp = tcp_pose if isinstance(tcp_pose, dict) else None
        self.target_label = label
        self.schedule_render(20)

    def rotate_camera(self, dx: float, dy: float) -> None:
        self.camera_yaw_deg -= float(dx) * 0.45
        self.camera_pitch_deg = max(-75.0, min(75.0, self.camera_pitch_deg + float(dy) * 0.35))
        self.schedule_render(10)

    def zoom_camera(self, wheel_delta: float) -> None:
        factor = 0.95 if wheel_delta > 0 else 1.05
        self.camera_distance = max(0.22, min(1.6, self.camera_distance * factor))
        self.schedule_render(10)

    def schedule_render(self, delay_ms: int = 60) -> None:
        if self.model is None or self.pb is None:
            return
        if self._render_pending:
            return
        self._render_pending = True
        QTimer.singleShot(max(0, int(delay_ms)), self._render_scheduled)

    def _render_scheduled(self) -> None:
        self._render_pending = False
        self.render()

    def render(self) -> None:
        if self.model is None or self.pb is None:
            return
        if self._render_in_progress:
            self.schedule_render(120)
            return
        try:
            self._render_in_progress = True
            logical_width = max(320, self.label.width() or 420)
            logical_height = max(240, self.label.height() or 260)
            dpr = max(1.0, min(2.0, float(self.devicePixelRatioF())))
            render_scale = 1.5
            width = min(1500, max(640, int(logical_width * dpr * render_scale)))
            height = min(1100, max(480, int(logical_height * dpr * render_scale)))
            q_rad = self._visual_q_rad()
            self.current_tcp = self.model.forward(q_rad)
            self._draw_debug_items()

            view = self.pb.computeViewMatrix(
                cameraEyePosition=self._camera_eye(),
                cameraTargetPosition=self.camera_target,
                cameraUpVector=[0.0, 0.0, 1.0],
            )
            projection = self.pb.computeProjectionMatrixFOV(
                fov=45.0,
                aspect=float(width) / float(height),
                nearVal=0.01,
                farVal=4.0,
            )
            self._last_view_matrix = list(view)
            self._last_projection_matrix = list(projection)
            _, _, rgba, _, _ = self.pb.getCameraImage(
                width,
                height,
                viewMatrix=view,
                projectionMatrix=projection,
                renderer=self.pb.ER_BULLET_HARDWARE_OPENGL,
                physicsClientId=self.model._client_id,
            )
            image = QImage(bytes(rgba), width, height, QImage.Format_RGBA8888).copy()
            self._paint_overlay(image)
            pixmap = QPixmap.fromImage(image).scaled(
                self.label.size(),
                Qt.KeepAspectRatioByExpanding,
                Qt.SmoothTransformation,
            )
            self.label.setPixmap(pixmap)
        except Exception as exc:
            self.label.setText(f"3D 视图渲染失败：{exc}")
        finally:
            self._render_in_progress = False

    def _visual_q_rad(self) -> list[float]:
        q_rad = [math.radians(float(self.current_joints_deg.get(joint, 0.0))) for joint in JOINT_ORDER]
        limits = getattr(self.model, "ordered_joint_user_limits", None)
        names = getattr(self.model, "sdk_joint_names", JOINT_ORDER)
        if not limits:
            return q_rad

        clipped: list[float] = []
        warnings: list[str] = []
        for index, value in enumerate(q_rad):
            lower, upper = limits[index]
            safe_value = max(float(lower), min(float(upper), float(value)))
            clipped.append(safe_value)
            if abs(safe_value - float(value)) > math.radians(0.001):
                name = names[index] if index < len(names) else f"J{index + 1}"
                warnings.append(
                    f"{name} 显示值已夹到 URDF 范围 "
                    f"{math.degrees(safe_value):.2f} deg，实际 {math.degrees(float(value)):.2f} deg"
                )
        self.visual_warning = "；".join(warnings[:2])
        return clipped

    def _camera_eye(self) -> list[float]:
        yaw = math.radians(self.camera_yaw_deg)
        pitch = math.radians(self.camera_pitch_deg)
        horizontal = self.camera_distance * math.cos(pitch)
        return [
            self.camera_target[0] + horizontal * math.cos(yaw),
            self.camera_target[1] + horizontal * math.sin(yaw),
            self.camera_target[2] + self.camera_distance * math.sin(pitch),
        ]

    def _draw_debug_items(self) -> None:
        for item_id in self._debug_ids:
            try:
                self.pb.removeUserDebugItem(item_id, physicsClientId=self.model._client_id)
            except Exception:
                pass
        self._debug_ids = []
        for body_id in self._marker_body_ids:
            try:
                self.pb.removeBody(body_id, physicsClientId=self.model._client_id)
            except Exception:
                pass
        self._marker_body_ids = []

        cid = self.model._client_id
        self._add_floor_grid()
        axis_len = 0.28
        self._add_axis_body("x", axis_len, [1.0, 0.05, 0.03, 1.0])
        self._add_axis_body("y", axis_len, [0.05, 0.9, 0.08, 1.0])
        self._add_axis_body("z", axis_len, [0.08, 0.25, 1.0, 1.0])
        self._debug_ids.append(self.pb.addUserDebugLine([0, 0, 0], [axis_len, 0, 0], [1, 0.05, 0.03], 4, physicsClientId=cid))
        self._debug_ids.append(self.pb.addUserDebugLine([0, 0, 0], [0, axis_len, 0], [0.05, 0.9, 0.08], 4, physicsClientId=cid))
        self._debug_ids.append(self.pb.addUserDebugLine([0, 0, 0], [0, 0, axis_len], [0.08, 0.25, 1], 4, physicsClientId=cid))

        current_xyz = self._xyz(self.current_tcp)
        if current_xyz:
            marker = self.pb.createVisualShape(self.pb.GEOM_SPHERE, radius=0.018, rgbaColor=[1.0, 0.25, 0.05, 1.0], physicsClientId=cid)
            body = self.pb.createMultiBody(baseMass=0, baseVisualShapeIndex=marker, basePosition=current_xyz, physicsClientId=cid)
            self._marker_body_ids.append(body)
            self._debug_ids.append(self.pb.addUserDebugText("当前末端", current_xyz, [1.0, 0.25, 0.05], textSize=1.05, physicsClientId=cid))

        target_xyz = self._xyz(self.target_tcp)
        if target_xyz:
            marker = self.pb.createVisualShape(self.pb.GEOM_SPHERE, radius=0.016, rgbaColor=[0.0, 0.85, 1.0, 1.0], physicsClientId=cid)
            body = self.pb.createMultiBody(baseMass=0, baseVisualShapeIndex=marker, basePosition=target_xyz, physicsClientId=cid)
            self._marker_body_ids.append(body)
            self._debug_ids.append(self.pb.addUserDebugText(self.target_label or "目标末端", target_xyz, [0.0, 0.85, 1.0], textSize=1.05, physicsClientId=cid))
            if current_xyz:
                self._add_dashed_line(current_xyz, target_xyz, [0.25, 0.95, 1.0])

    def reset_camera(self) -> None:
        self.camera_yaw_deg = -55.0
        self.camera_pitch_deg = 28.0
        self.camera_distance = 0.62
        self.camera_target = [0.0, 0.0, 0.16]
        self.schedule_render(10)

    def front_camera(self) -> None:
        self.camera_yaw_deg = -90.0
        self.camera_pitch_deg = 8.0
        self.schedule_render(10)

    def top_camera(self) -> None:
        self.camera_yaw_deg = -90.0
        self.camera_pitch_deg = 75.0
        self.schedule_render(10)

    def side_camera(self) -> None:
        self.camera_yaw_deg = 0.0
        self.camera_pitch_deg = 10.0
        self.schedule_render(10)

    def fit_camera(self) -> None:
        self.camera_distance = 0.78
        self.camera_target = [0.0, 0.0, 0.18]
        self.schedule_render(10)

    def _add_dashed_line(self, start: list[float], end: list[float], color: list[float]) -> None:
        cid = self.model._client_id
        segments = 16
        for index in range(0, segments, 2):
            a = index / segments
            b = (index + 1) / segments
            p0 = [start[i] + (end[i] - start[i]) * a for i in range(3)]
            p1 = [start[i] + (end[i] - start[i]) * b for i in range(3)]
            self._debug_ids.append(self.pb.addUserDebugLine(p0, p1, color, 3, physicsClientId=cid))

    def _add_floor_grid(self) -> None:
        cid = self.model._client_id
        extent = 0.8
        step = 0.1
        count = int(round(extent / step))
        for index in range(-count, count + 1):
            value = round(index * step, 4)
            is_origin = index == 0
            color = [0.44, 0.51, 0.60] if is_origin else [0.68, 0.74, 0.82]
            width = 1.4 if is_origin else 0.8
            self._debug_ids.append(
                self.pb.addUserDebugLine(
                    [-extent, value, 0.001],
                    [extent, value, 0.001],
                    color,
                    width,
                    physicsClientId=cid,
                )
            )
            self._debug_ids.append(
                self.pb.addUserDebugLine(
                    [value, -extent, 0.001],
                    [value, extent, 0.001],
                    color,
                    width,
                    physicsClientId=cid,
                )
            )

    def _add_axis_body(self, axis: str, length: float, color: list[float]) -> None:
        cid = self.model._client_id
        radius = 0.006
        if axis == "x":
            position = [length / 2.0, 0.0, 0.0]
            tip = [length, 0.0, 0.0]
            orientation = self.pb.getQuaternionFromEuler([0.0, math.pi / 2.0, 0.0])
        elif axis == "y":
            position = [0.0, length / 2.0, 0.0]
            tip = [0.0, length, 0.0]
            orientation = self.pb.getQuaternionFromEuler([-math.pi / 2.0, 0.0, 0.0])
        else:
            position = [0.0, 0.0, length / 2.0]
            tip = [0.0, 0.0, length]
            orientation = [0.0, 0.0, 0.0, 1.0]

        shaft = self.pb.createVisualShape(
            self.pb.GEOM_CYLINDER,
            radius=radius,
            length=length,
            rgbaColor=color,
            physicsClientId=cid,
        )
        shaft_body = self.pb.createMultiBody(
            baseMass=0,
            baseVisualShapeIndex=shaft,
            basePosition=position,
            baseOrientation=orientation,
            physicsClientId=cid,
        )
        tip_shape = self.pb.createVisualShape(
            self.pb.GEOM_SPHERE,
            radius=radius * 2.0,
            rgbaColor=color,
            physicsClientId=cid,
        )
        tip_body = self.pb.createMultiBody(
            baseMass=0,
            baseVisualShapeIndex=tip_shape,
            basePosition=tip,
            physicsClientId=cid,
        )
        self._marker_body_ids.extend([shaft_body, tip_body])

    def _paint_overlay(self, image: QImage) -> None:
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing)
        self._paint_axis_labels(painter, image.width(), image.height())
        painter.setPen(QPen(Qt.white, 1))
        painter.drawText(10, 20, "拖动旋转视图，滚轮/触控板缩放")
        painter.drawText(10, 40, "橙点：当前末端  青点：计算目标")
        if self.visual_warning:
            painter.setPen(QPen(Qt.yellow, 1))
            painter.drawText(10, 60, self.visual_warning)
        painter.end()

    def _paint_axis_labels(self, painter: QPainter, width: int, height: int) -> None:
        if not self._last_view_matrix or not self._last_projection_matrix or self.pb is None:
            return
        axis_len = 0.28
        labels = [
            ("X", [axis_len + 0.04, 0.0, 0.02], QColor(220, 20, 20)),
            ("Y", [0.0, axis_len + 0.04, 0.02], QColor(20, 150, 40)),
            ("Z", [0.02, 0.0, axis_len + 0.04], QColor(35, 80, 230)),
        ]
        painter.setFont(QFont("Arial", 22, QFont.Bold))
        for text, world, color in labels:
            screen = self._world_to_screen(world, width, height)
            if screen is None:
                continue
            x, y = screen
            painter.setPen(QPen(Qt.white, 5))
            painter.drawText(x - 9, y + 8, text)
            painter.setPen(QPen(color, 2))
            painter.drawText(x - 9, y + 8, text)

    def _world_to_screen(self, world: list[float], width: int, height: int) -> tuple[int, int] | None:
        import numpy as np

        view = np.asarray(self._last_view_matrix, dtype=float).reshape(4, 4, order="F")
        projection = np.asarray(self._last_projection_matrix, dtype=float).reshape(4, 4, order="F")
        point = np.asarray([world[0], world[1], world[2], 1.0], dtype=float)
        clip = projection @ view @ point
        if abs(float(clip[3])) < 1e-8:
            return None
        ndc = clip[:3] / clip[3]
        if float(ndc[2]) < -1.0 or float(ndc[2]) > 1.0:
            return None
        x = int((float(ndc[0]) * 0.5 + 0.5) * width)
        y = int((1.0 - (float(ndc[1]) * 0.5 + 0.5)) * height)
        return x, y

    def _xyz(self, pose: dict[str, Any] | None) -> list[float] | None:
        if not isinstance(pose, dict):
            return None
        xyz = pose.get("xyz")
        if not isinstance(xyz, (list, tuple)) or len(xyz) < 3:
            return None
        return [float(xyz[0]), float(xyz[1]), float(xyz[2])]
