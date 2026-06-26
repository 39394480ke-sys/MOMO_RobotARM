"""右侧检查器：3D 仿真视图 / 摄像头画面切换。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from gui_app.path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from gui_app.组件_widgets.图像转换工具_image_tools import bgr_frame_to_pixmap
from gui_app.组件_widgets.布局工具_layout_tools import make_hbox_layout


class CameraPreview(QWidget):
    """轻量摄像头预览，只采集画面，不启动视觉识别模型。"""

    def __init__(self, project_root: Path, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.vision_root = self.project_root / "视觉识别与跟随"
        self.video_source: Any | None = None
        self._running = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.image_label = QLabel("摄像头未打开")
        self.image_label.setObjectName("CameraPreviewLabel")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(260, 220)
        self.image_label.setScaledContents(False)
        self.image_label.setWordWrap(True)
        layout.addWidget(self.image_label, 1)

        controls = make_hbox_layout()
        self.open_button = QPushButton("打开摄像头")
        self.close_button = QPushButton("关闭")
        self.open_button.setObjectName("PrimaryButton")
        self.close_button.setObjectName("SecondaryButton")
        controls.addWidget(self.open_button)
        controls.addWidget(self.close_button)
        layout.addLayout(controls)

        self.timer = QTimer(self)
        self.timer.setInterval(33)
        self.timer.timeout.connect(self._read_frame)
        self.open_button.clicked.connect(self.start)
        self.close_button.clicked.connect(self.stop)

    def start(self) -> None:
        if self._running:
            return
        try:
            source_cls = self._video_source_class()
            config = self._load_camera_config()
            self.video_source = source_cls(config, self.vision_root)
            if not self.video_source.open():
                self.image_label.setText(str(getattr(self.video_source, "last_error", "摄像头打开失败。")))
                self.video_source = None
                return
            self._running = True
            self.timer.start()
            self._read_frame()
        except Exception as exc:
            self.image_label.setText(f"摄像头打开失败：{exc}")
            self.video_source = None
            self._running = False
            self.timer.stop()

    def stop(self) -> None:
        self.timer.stop()
        self._running = False
        if self.video_source is not None:
            try:
                self.video_source.close()
            except Exception:
                pass
        self.video_source = None
        self.image_label.setText("摄像头未打开")
        self.image_label.setPixmap(QPixmap())

    def _read_frame(self) -> None:
        if self.video_source is None:
            return
        ok, frame, error = self.video_source.read()
        if not ok or frame is None:
            self.image_label.setText(error or "读取摄像头画面失败。")
            self.timer.stop()
            self._running = False
            return
        try:
            pixmap, _frame_size = bgr_frame_to_pixmap(frame)
            self.image_label.setPixmap(
                pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
        except Exception as exc:
            self.image_label.setText(f"画面转换失败：{exc}")

    def _video_source_class(self) -> Any:
        from 控制桥接_common import ensure_import_paths

        ensure_import_paths([self.vision_root])
        from vision.摄像头_source import VideoSource

        return VideoSource

    def _load_camera_config(self) -> dict[str, Any]:
        from gui_app.视觉配置工具_vision_config_utils import load_vision_section

        return load_vision_section(self.vision_root, "camera")


class InspectorViewSwitcher(QWidget):
    """主窗口右下角常驻视图容器。"""

    def __init__(self, project_root: Path, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root)
        self.sim_view: QWidget | None = None
        self.camera_preview: CameraPreview | None = None
        self._current_view = "sim"
        self._pending_joints_deg: dict[str, float] = {}
        self._pending_tcp_pose: dict[str, Any] | None = None
        self._pending_target_pose: dict[str, Any] | None = None
        self._pending_target_label = "目标"
        self._state_dirty = False
        self._target_dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        toolbar = QWidget()
        toolbar.setObjectName("InspectorViewToolbar")
        toolbar_layout = make_hbox_layout(toolbar, margins=(8, 6, 8, 6), spacing=6)
        self.sim_button = QPushButton("仿真视图")
        self.camera_button = QPushButton("摄像头画面")
        for button in (self.sim_button, self.camera_button):
            button.setCheckable(True)
            button.setObjectName("InspectorViewTab")
            toolbar_layout.addWidget(button)
        toolbar_layout.addStretch(1)
        layout.addWidget(toolbar)

        self.stack = QStackedWidget()
        self.sim_placeholder = self._placeholder("3D 仿真视图待加载")
        self.camera_placeholder = self._placeholder("摄像头画面待打开")
        self.stack.addWidget(self.sim_placeholder)
        self.stack.addWidget(self.camera_placeholder)
        layout.addWidget(self.stack, 1)

        self.sim_button.clicked.connect(lambda: self.set_view("sim"))
        self.camera_button.clicked.connect(lambda: self.set_view("camera"))
        self.stack.setCurrentWidget(self.sim_placeholder)
        self.sim_button.setChecked(True)
        self.camera_button.setChecked(False)

    def set_view(self, view: str) -> None:
        self._current_view = "camera" if view == "camera" else "sim"
        if view == "camera":
            camera_preview = self._ensure_camera_preview()
            self.stack.setCurrentWidget(camera_preview)
            self.sim_button.setChecked(False)
            self.camera_button.setChecked(True)
            camera_preview.start()
            return
        sim_view = self._ensure_sim_view()
        self.stack.setCurrentWidget(sim_view)
        self.sim_button.setChecked(True)
        self.camera_button.setChecked(False)
        if self.camera_preview is not None:
            self.camera_preview.stop()
        self._flush_sim_state()

    def stop_camera(self) -> None:
        if self.camera_preview is not None:
            self.camera_preview.stop()

    def update_state(self, joints_deg: dict[str, float], tcp_pose: dict[str, Any] | None = None) -> None:
        self._pending_joints_deg = dict(joints_deg or {})
        self._pending_tcp_pose = tcp_pose if isinstance(tcp_pose, dict) else None
        self._state_dirty = True
        if self.sim_view is not None:
            self._flush_sim_state()

    def set_target_pose(self, pose: dict[str, Any] | None, label: str = "目标") -> None:
        self._pending_target_pose = pose if isinstance(pose, dict) else None
        self._pending_target_label = label
        self._target_dirty = True
        if self._current_view == "sim":
            self._ensure_sim_view()
            self._flush_sim_state()

    def _ensure_sim_view(self) -> QWidget:
        if self.sim_view is None:
            from gui_app.组件_widgets.仿真视图_sim_view import SimView

            self.sim_view = SimView()
            self.stack.addWidget(self.sim_view)
        return self.sim_view

    def _ensure_camera_preview(self) -> CameraPreview:
        if self.camera_preview is None:
            self.camera_preview = CameraPreview(self.project_root)
            self.stack.addWidget(self.camera_preview)
        return self.camera_preview

    def _flush_sim_state(self) -> None:
        if self.sim_view is None:
            return
        if self._state_dirty:
            self.sim_view.update_state(self._pending_joints_deg, self._pending_tcp_pose)  # type: ignore[attr-defined]
            self._state_dirty = False
        if self._target_dirty:
            self.sim_view.set_target_pose(self._pending_target_pose, self._pending_target_label)  # type: ignore[attr-defined]
            self._target_dirty = False

    def _placeholder(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setAlignment(Qt.AlignCenter)
        label.setObjectName("CameraPreviewLabel")
        label.setMinimumSize(260, 220)
        label.setWordWrap(True)
        return label
