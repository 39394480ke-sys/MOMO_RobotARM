"""视觉识别与跟随页面。"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from gui_app.path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from PyQt5.QtCore import QPoint, QRect, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from 控制桥接_common import FOLLOW_JOINT_AXES as COMMON_FOLLOW_JOINT_AXES, compute_axis_step, read_smoothed_offset, vision_target_guard
from gui_app.运动文本格式化_motion_text_format import format_motion_value
from gui_app.结果格式化_result_format import result_data, result_message
from gui_app.组件_widgets.图像转换工具_image_tools import bgr_frame_to_pixmap
from gui_app.组件_widgets.布局工具_layout_tools import make_grid_layout, make_vbox_layout
from gui_app.视觉配置工具_vision_config_utils import load_vision_config


class SelectableImageLabel(QLabel):
    selection_finished = pyqtSignal(QRect)

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.selection_enabled = False
        self._dragging = False
        self._start = QPoint()
        self._end = QPoint()

    def set_selection_enabled(self, enabled: bool) -> None:
        self.selection_enabled = bool(enabled)
        self._dragging = False
        self._start = QPoint()
        self._end = QPoint()
        self.setCursor(Qt.CrossCursor if self.selection_enabled else Qt.ArrowCursor)
        self.update()

    def mousePressEvent(self, event):  # type: ignore[no-untyped-def]
        if self.selection_enabled and event.button() == Qt.LeftButton:
            self._dragging = True
            self._start = event.pos()
            self._end = event.pos()
            self.update()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # type: ignore[no-untyped-def]
        if self.selection_enabled and self._dragging:
            self._end = event.pos()
            self.update()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):  # type: ignore[no-untyped-def]
        if self.selection_enabled and self._dragging and event.button() == Qt.LeftButton:
            self._dragging = False
            self._end = event.pos()
            rect = QRect(self._start, self._end).normalized()
            self.update()
            if rect.width() >= 8 and rect.height() >= 8:
                self.selection_finished.emit(rect)
            return
        super().mouseReleaseEvent(event)

    def paintEvent(self, event):  # type: ignore[no-untyped-def]
        super().paintEvent(event)
        if self.selection_enabled and (self._dragging or not self._start.isNull()):
            rect = QRect(self._start, self._end).normalized()
            if rect.width() > 0 and rect.height() > 0:
                painter = QPainter(self)
                painter.setRenderHint(QPainter.Antialiasing)
                painter.setPen(QPen(QColor(56, 189, 248), 2, Qt.SolidLine))
                painter.fillRect(rect, QColor(56, 189, 248, 36))
                painter.drawRect(rect)


class ParameterSlider(QWidget):
    """Touch-friendly numeric slider with a compact value label."""

    def __init__(self, label: str, minimum: float, maximum: float, value: float, step: float, suffix: str = "", parent=None):
        super().__init__(parent)
        self.minimum = float(minimum)
        self.maximum = float(maximum)
        self.step = float(step)
        self.suffix = suffix
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        self.title_label = QLabel(label)
        self.title_label.setObjectName("PathName")
        self.value_label = QLabel()
        self.value_label.setObjectName("StatusPill")
        row.addWidget(self.title_label)
        row.addStretch(1)
        row.addWidget(self.value_label)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, int(round((self.maximum - self.minimum) / self.step)))
        self.slider.setSingleStep(1)
        self.slider.setPageStep(2)
        self.slider.setMinimumHeight(30)
        layout.addLayout(row)
        layout.addWidget(self.slider)
        self.slider.valueChanged.connect(self._update_label)
        self.set_value(value)

    def value(self) -> float:
        return self.minimum + float(self.slider.value()) * self.step

    def set_value(self, value: float) -> None:
        clamped = max(self.minimum, min(self.maximum, float(value)))
        self.slider.setValue(int(round((clamped - self.minimum) / self.step)))
        self._update_label()

    def _update_label(self) -> None:
        value = self.value()
        self.value_label.setText(f"{value:.2f}{self.suffix}")


class VisionFollowPage(QWidget):
    follow_commands_requested = pyqtSignal(list)
    FOLLOW_JOINT_AXES = COMMON_FOLLOW_JOINT_AXES

    def __init__(self, project_root: str | Path, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.vision_root = self.project_root / "视觉识别与跟随"
        self.config = self._load_vision_config()
        self.engine: Any | None = None
        self.vision_running = False
        self.follow_running = False
        self.command_in_flight = False
        self.latest_robot_state: dict[str, Any] = {}
        self.last_command: dict[str, Any] | None = None
        self._selecting_target = False
        self._last_frame_size: tuple[int, int] | None = None
        self._last_tick_at = 0.0
        self._control_interval_ms = 0.0
        self._skipped_command_count = 0
        self._cinematic_runtime: Any | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.image_label = SelectableImageLabel("视觉画面未启动")
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(360, 270)
        self.image_label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.image_label.setStyleSheet("background: #0b1020; color: #cbd5e1; border: 1px solid #1f2937; border-radius: 8px;")
        left.addWidget(self.image_label, 1)

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.start_vision_button = QPushButton("打开摄像头")
        self.start_vision_button.setObjectName("PrimaryButton")
        self.stop_vision_button = QPushButton("关闭摄像头")
        self.start_follow_button = QPushButton("开始跟随")
        self.start_follow_button.setObjectName("PrimaryButton")
        self.stop_follow_button = QPushButton("停止跟随")
        for button in (self.start_vision_button, self.stop_vision_button, self.start_follow_button, self.stop_follow_button):
            button_row.addWidget(button)
        left.addLayout(button_row)

        target_button_row = QHBoxLayout()
        target_button_row.setSpacing(8)
        self.select_target_button = QPushButton("框选主体")
        self.select_target_button.setObjectName("PrimaryButton")
        self.reset_target_button = QPushButton("取消锁定")
        self.face_mode_button = QPushButton("人脸跟随")
        for button in (self.select_target_button, self.reset_target_button, self.face_mode_button):
            target_button_row.addWidget(button)
        left.addLayout(target_button_row)

        self.right_panel = QWidget()
        self.right_panel.setMinimumWidth(320)
        self.right_panel.setMaximumWidth(360)
        self.right_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right = make_vbox_layout(self.right_panel, margins=(0, 0, 0, 0), spacing=10)
        status_box = QGroupBox("跟随概览")
        status_layout = make_grid_layout(status_box)
        self.status_labels: dict[str, QLabel] = {}
        status_titles = {
            "vision": "视觉",
            "follow": "跟随",
            "detected": "识别",
            "fps": "帧率",
            "direction": "方向",
            "dead_zone": "死区",
            "target": "目标",
            "tracking": "跟踪",
            "ndx": "水平偏移",
            "ndy": "垂直偏移",
            "rail": "导轨",
            "control": "周期",
            "skips": "跳过",
            "samples": "采样",
        }
        for index, key in enumerate(("vision", "follow", "detected", "fps", "direction", "dead_zone", "target", "tracking", "ndx", "ndy", "rail", "control", "skips", "samples")):
            title = QLabel(status_titles[key])
            title.setObjectName("PathName")
            value = QLabel("--")
            value.setObjectName("StatusPill")
            self.status_labels[key] = value
            status_layout.addWidget(title, index // 2, (index % 2) * 2)
            status_layout.addWidget(value, index // 2, (index % 2) * 2 + 1)
        right.addWidget(status_box)

        config_box = QGroupBox("跟随参数")
        config_layout = make_vbox_layout(config_box, spacing=10)
        follow_cfg = self._follow_cfg()
        self.execute_checkbox = QCheckBox("连接真实模式时执行真实移动")
        self.execute_checkbox.setChecked(True)
        self.pan_gain_input = ParameterSlider("水平增益", 0.5, 12.0, float(follow_cfg.get("pan_gain_deg_per_norm", 4.8)), 0.1)
        self.tilt_gain_input = ParameterSlider("垂直增益", 0.5, 12.0, float(follow_cfg.get("tilt_gain_deg_per_norm", 4.8)), 0.1)
        self.max_pan_step_input = ParameterSlider("水平最大步进", 0.2, 5.0, float(follow_cfg.get("max_pan_step_deg", 3.0)), 0.1, "°")
        self.max_tilt_step_input = ParameterSlider("垂直最大步进", 0.2, 5.0, float(follow_cfg.get("max_tilt_step_deg", 3.0)), 0.1, "°")
        config_layout.addWidget(self.execute_checkbox)
        config_layout.addWidget(self.pan_gain_input)
        config_layout.addWidget(self.tilt_gain_input)
        config_layout.addWidget(self.max_pan_step_input)
        config_layout.addWidget(self.max_tilt_step_input)

        follow_joint_box = QGroupBox("参与跟随关节")
        follow_joint_layout = make_grid_layout(follow_joint_box)
        self.follow_joint_checks: dict[str, QCheckBox] = {}
        enabled_joints = self._enabled_follow_joints()
        for index, joint in enumerate(("j11", "j12", "j13", "j14", "j15")):
            axis_text = "水平" if self.FOLLOW_JOINT_AXES[joint] == "pan" else "垂直"
            checkbox = QCheckBox(f"{joint.upper()} {axis_text}")
            checkbox.setChecked(joint in enabled_joints)
            self.follow_joint_checks[joint] = checkbox
            follow_joint_layout.addWidget(checkbox, index // 2, index % 2)
        config_layout.addWidget(follow_joint_box)
        right.addWidget(config_box)

        command_box = QGroupBox("最近命令")
        command_layout = make_grid_layout(command_box)
        self.command_labels: dict[str, QLabel] = {}
        command_titles = {
            "action": "状态",
            "joint": "关节",
            "delta": "步进",
            "result": "结果",
        }
        for index, key in enumerate(("action", "joint", "delta", "result")):
            title = QLabel(command_titles[key])
            title.setObjectName("PathName")
            value = QLabel("--")
            value.setObjectName("StatusPill")
            value.setWordWrap(True)
            self.command_labels[key] = value
            command_layout.addWidget(title, index, 0)
            command_layout.addWidget(value, index, 1)
        right.addWidget(command_box)
        right.addStretch(1)

        layout.addLayout(left, 1)
        layout.addWidget(self.right_panel, 0)

        self.timer = QTimer(self)
        self.timer.setInterval(80)
        self.timer.timeout.connect(self._tick)
        self.start_vision_button.clicked.connect(self.start_vision)
        self.stop_vision_button.clicked.connect(self.stop_vision)
        self.start_follow_button.clicked.connect(self.start_follow)
        self.stop_follow_button.clicked.connect(self.stop_follow)
        self.select_target_button.clicked.connect(self.enable_target_selection)
        self.reset_target_button.clicked.connect(self.reset_manual_target)
        self.face_mode_button.clicked.connect(self.reset_manual_target)
        self.image_label.selection_finished.connect(self._finish_target_selection)
        self._update_status_labels({})

    def start_vision(self) -> None:
        if self.vision_running:
            return
        try:
            from 控制桥接_common import ensure_import_paths

            ensure_import_paths([self.vision_root])
            from vision.视觉引擎_vision_engine import VisionEngine

            self.config = self._load_vision_config()
            self.engine = VisionEngine(self.config, self.vision_root)
            self.engine.start()
            self.vision_running = True
            self.timer.start()
        except Exception as exc:
            self._set_command_status("错误", "--", "--", f"启动视觉失败：{exc}")

    def stop_vision(self) -> None:
        self.stop_follow()
        if self.engine is not None:
            try:
                self.engine.stop()
            except Exception:
                pass
        self.engine = None
        self.vision_running = False
        self.timer.stop()
        self.image_label.setText("视觉画面未启动")
        self.image_label.set_selection_enabled(False)
        self._selecting_target = False
        self._update_status_labels({})

    def enable_target_selection(self) -> None:
        if not self.vision_running:
            self.start_vision()
        if self.engine is None:
            self._set_command_status("错误", "--", "--", "视觉未启动，无法框选主体")
            return
        self._selecting_target = True
        self.image_label.set_selection_enabled(True)
        self._set_command_status("框选中", "--", "--", "在画面上拖拽矩形框")

    def reset_manual_target(self) -> None:
        self._selecting_target = False
        self.image_label.set_selection_enabled(False)
        if self.engine is None:
            return
        try:
            result = self.engine.reset_manual_target()
            self._set_command_status("已取消", "--", "--", result_message(result, "已取消锁定"))
        except Exception as exc:
            self._set_command_status("错误", "--", "--", f"取消锁定失败：{exc}")

    def _finish_target_selection(self, display_rect: QRect) -> None:
        self._selecting_target = False
        self.image_label.set_selection_enabled(False)
        if self.engine is None or self._last_frame_size is None:
            self._set_command_status("错误", "--", "--", "没有可用画面，无法框选")
            return
        bbox = self._map_display_rect_to_frame_rect(display_rect)
        if bbox is None:
            self._set_command_status("错误", "--", "--", "框选区域不在画面内")
            return
        try:
            result = self.engine.select_manual_target(bbox)
        except Exception as exc:
            result = {"ok": False, "message": f"框选失败：{exc}"}
        self._set_command_status("已锁定" if result.get("ok") else "错误", "--", str(bbox), result_message(result, "--"))

    def start_follow(self) -> None:
        if not self.vision_running:
            self.start_vision()
        self.timer.setInterval(80)
        self.follow_running = True
        self.command_in_flight = False
        runtime = self._peek_cinematic_runtime()
        if runtime is not None:
            runtime.start_follow(self._live_rail_mm())

    def stop_follow(self) -> None:
        self.follow_running = False
        self.command_in_flight = False
        self.timer.setInterval(80)
        runtime = self._peek_cinematic_runtime()
        if runtime is not None:
            runtime.stop()

    def start_rehearsal(self) -> None:
        if not self.vision_running:
            self.start_vision()
        self.timer.setInterval(80)
        self.follow_running = True
        self.command_in_flight = False
        self._reset_follow_joint_activity()
        self._get_cinematic_runtime().start_rehearsal(self._live_rail_mm())
        self._set_command_status("试拍中", "J10", "--", "正在记录视觉误差曲线")

    def apply_cinematic_settings(self, settings: dict[str, Any]) -> None:
        self._get_cinematic_runtime().apply_settings(settings)

    def start_playback(self) -> None:
        runtime = self._get_cinematic_runtime()
        ok, message = runtime.start_playback(self._cinematic_context())
        if not ok:
            self._set_command_status("错误", "--", "--", message)
            return
        self.timer.setInterval(runtime.playback_interval_ms())
        self.timer.start()
        self.follow_running = True
        self.command_in_flight = False
        self._set_command_status("回放中", "--", message, "按试拍采样轨迹回放，不启用视觉纠偏")

    def clear_cinematic_record(self) -> None:
        ok, message = self._get_cinematic_runtime().clear_record()
        self._set_command_status("已清除" if ok else "错误", "--", "--", message)

    def save_cinematic_record(self) -> None:
        ok, message = self._get_cinematic_runtime().save_record()
        self._set_command_status("已保存" if ok else "错误", "--", "--", message)

    def load_latest_cinematic_record(self) -> None:
        ok, message = self._get_cinematic_runtime().load_latest_record()
        self._set_command_status("已加载" if ok else "错误", "--", "--", message)

    def set_follow_result(self, result: dict[str, Any]) -> None:
        self.command_in_flight = False
        self.last_command = result
        if result.get("action") == "busy_skip":
            self._skipped_command_count += 1
            return
        runtime = self._peek_cinematic_runtime()
        if runtime is not None and not result.get("ok", False) and self._result_mentions_joint(result, "j10"):
            runtime.mark_rail_error(result_message(result, "J10 命令失败"))
            if runtime.mode in {"rehearsal", "playback"}:
                self.follow_running = False

    def update_robot_state(self, state: dict[str, Any]) -> None:
        self.latest_robot_state = dict(state or {})

    def is_real_execute_enabled(self) -> bool:
        return self.execute_checkbox.isChecked()

    def _tick(self) -> None:
        runtime = self._peek_cinematic_runtime()
        mode = runtime.mode if runtime is not None else "follow"
        if self.engine is None and not (self.follow_running and mode == "playback"):
            return
        now = time.monotonic()
        if self._last_tick_at > 0:
            self._control_interval_ms = 0.8 * self._control_interval_ms + 0.2 * ((now - self._last_tick_at) * 1000.0) if self._control_interval_ms > 0 else (now - self._last_tick_at) * 1000.0
        self._last_tick_at = now
        result: dict[str, Any] = {}
        if self.engine is not None:
            result = self.engine.get_latest_result()
            frame = self.engine.get_latest_frame()
            if frame is not None:
                self._show_frame(frame)
        self._update_status_labels(result)
        commands: list[dict[str, Any]] = []
        if self.follow_running and not self.command_in_flight:
            if mode == "playback":
                commands = self._build_playback_commands()
            else:
                commands = self._build_follow_commands(result)
                if mode == "rehearsal" and runtime is not None:
                    sampled, sample_message = runtime.record_sample(result, self.latest_robot_state)
                    if sampled and sample_message:
                        self._set_command_status("偏移过大", "--", sample_message, "试拍继续记录，请降低导轨速度或增益")
                    if runtime.rail_phase == "finished":
                        ok, message, _path = runtime.finalize_rehearsal_record(self._cinematic_context())
                        self.follow_running = False
                        self._set_command_status("试拍完成" if ok else "错误", "--", message.split(" ", 1)[0] if ok else "--", message)
                        commands = []
        elif self.follow_running and self.command_in_flight:
            self._skipped_command_count += 1
        if commands and not self.command_in_flight:
            self.command_in_flight = True
            self.follow_commands_requested.emit(commands)
        self._show_detail(result, commands)

    def _show_frame(self, frame: Any) -> None:
        try:
            pixmap, frame_size = bgr_frame_to_pixmap(frame)
            self._last_frame_size = frame_size
            self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as exc:
            self.image_label.setText(f"画面显示失败：{exc}")

    def _map_display_rect_to_frame_rect(self, rect: QRect) -> tuple[int, int, int, int] | None:
        if self._last_frame_size is None:
            return None
        pixmap = self.image_label.pixmap()
        if pixmap is None or pixmap.isNull():
            return None
        frame_w, frame_h = self._last_frame_size
        shown_w = pixmap.width()
        shown_h = pixmap.height()
        offset_x = (self.image_label.width() - shown_w) / 2.0
        offset_y = (self.image_label.height() - shown_h) / 2.0
        x1 = (float(rect.left()) - offset_x) * frame_w / max(1.0, float(shown_w))
        y1 = (float(rect.top()) - offset_y) * frame_h / max(1.0, float(shown_h))
        x2 = (float(rect.right()) - offset_x) * frame_w / max(1.0, float(shown_w))
        y2 = (float(rect.bottom()) - offset_y) * frame_h / max(1.0, float(shown_h))

        x1 = max(0.0, min(float(frame_w - 1), x1))
        y1 = max(0.0, min(float(frame_h - 1), y1))
        x2 = max(0.0, min(float(frame_w - 1), x2))
        y2 = max(0.0, min(float(frame_h - 1), y2))
        x = int(round(min(x1, x2)))
        y = int(round(min(y1, y2)))
        w = int(round(abs(x2 - x1)))
        h = int(round(abs(y2 - y1)))
        if w < 8 or h < 8:
            return None
        return x, y, w, h

    def _update_status_labels(self, result: dict[str, Any]) -> None:
        offset = result.get("offset", {}) if result else {}
        direction = result.get("direction", {}) if result else {}
        self.status_labels["vision"].setText("运行" if self.vision_running else "停止")
        self.status_labels["follow"].setText("运行" if self.follow_running else "停止")
        self.status_labels["detected"].setText("是" if result and result.get("detected", False) else ("否" if result else "--"))
        self.status_labels["fps"].setText(f"{float(result.get('fps', 0.0)):.1f}" if result else "--")
        self.status_labels["direction"].setText(self._direction_text(str(direction.get("combined", "--"))))
        self.status_labels["dead_zone"].setText("是" if result and offset.get("in_dead_zone", True) else ("否" if result else "--"))
        self.status_labels["target"].setText(str(result.get("target_source", "--")) if result else "--")
        self.status_labels["tracking"].setText(str(result.get("tracking_state", "--")) if result else "--")
        self.status_labels["ndx"].setText(f"{float(offset.get('ndx', 0.0)):.4f}" if result else "--")
        self.status_labels["ndy"].setText(f"{float(offset.get('ndy', 0.0)):.4f}" if result else "--")
        runtime = self._peek_cinematic_runtime()
        self.status_labels["rail"].setText(runtime.rail_status_text(follow_running=self.follow_running, latest_robot_state=self.latest_robot_state) if runtime is not None else "--")
        self.status_labels["control"].setText(f"{self._control_interval_ms:.0f} ms" if self._control_interval_ms > 0 else "--")
        self.status_labels["skips"].setText(str(self._skipped_command_count))
        self.status_labels["samples"].setText(runtime.sample_status_text() if runtime is not None else "--")

    def _show_detail(self, result: dict[str, Any], commands: list[dict[str, Any]]) -> None:
        if commands:
            joints = ", ".join(str(item.get("joint_key", "")) for item in commands)
            deltas = ", ".join(self._format_command_delta(item) for item in commands)
            self._set_command_status("待执行", joints, deltas, "等待执行")
            return
        if self.last_command:
            data = result_data(self.last_command)
            responses = data.get("responses", []) if isinstance(data.get("responses"), list) else []
            if responses:
                ok_count = sum(1 for item in responses if item.get("ok"))
                joints = ", ".join(str(cmd.get("joint_key", "")) for cmd in data.get("commands", []))
                deltas = ", ".join(self._format_command_delta(cmd) for cmd in data.get("commands", []))
                self._set_command_status("已完成", joints or "--", deltas or "--", f"{ok_count}/{len(responses)} 成功")
            else:
                if self.last_command.get("action") == "busy_skip":
                    self._set_command_status("已跳过", "--", "--", result_message(self.last_command, "--"))
                else:
                    self._set_command_status("已完成" if self.last_command.get("ok") else "错误", "--", "--", result_message(self.last_command, "--"))
            return
        message = result_message(result, "--") if result else "--"
        self._set_command_status("空闲", "--", "--", message)

    def _set_command_status(self, action: str, joint: str, delta: str, result: str) -> None:
        self.command_labels["action"].setText(action)
        self.command_labels["joint"].setText(joint)
        self.command_labels["delta"].setText(delta)
        self.command_labels["result"].setText(result)

    def _format_command_delta(self, command: dict[str, Any]) -> str:
        joint = str(command.get("joint_key", ""))
        unit = "mm" if joint == "j10" else "°"
        if "target_deg" in command:
            return format_motion_value(command.get("target_deg", 0.0), unit, prefix="->")
        return format_motion_value(command.get("delta_deg", 0.0), unit, signed=True)

    def _direction_text(self, direction: str) -> str:
        mapping = {
            "center": "居中",
            "left": "左",
            "right": "右",
            "up": "上",
            "down": "下",
            "left_up": "左上",
            "left_down": "左下",
            "right_up": "右上",
            "right_down": "右下",
            "--": "--",
        }
        return mapping.get(direction, direction)

    def _build_follow_commands(self, result: dict[str, Any]) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        guard = vision_target_guard(
            result,
            min_width=float(self._follow_cfg().get("min_target_box_width", 20.0)),
            min_height=float(self._follow_cfg().get("min_target_box_height", 20.0)),
        )
        if guard is not None:
            self._reset_follow_joint_activity()
            return []
        else:
            offset = read_smoothed_offset(result)
            if offset is not None:
                ndx, ndy = offset
                commands.extend(self._build_selected_follow_joint_commands(ndx, ndy))
        runtime = self._peek_cinematic_runtime()
        if runtime is not None:
            commands.extend(runtime.build_rail_commands(timer_interval_ms=self.timer.interval(), latest_robot_state=self.latest_robot_state))
        return commands

    def _build_selected_follow_joint_commands(self, ndx: float, ndy: float) -> list[dict[str, Any]]:
        commands: list[dict[str, Any]] = []
        selected = self._selected_follow_joints()
        for joint, checkbox in self.follow_joint_checks.items():
            if joint not in selected:
                setattr(self, f"_follow_active_{joint}", False)
                continue
            axis = self.FOLLOW_JOINT_AXES[joint]
            if axis == "pan":
                step = self._axis_step(
                    ndx,
                    active_attr=f"_follow_active_{joint}",
                    gain=self.pan_gain_input.value(),
                    sign=self._follow_joint_sign(joint),
                    dead=float(self._follow_cfg().get("pan_dead_zone_norm", 0.03)),
                    resume=float(self._follow_cfg().get("pan_resume_zone_norm", 0.05)),
                    min_step=float(self._follow_cfg().get("min_pan_step_deg", 0.5)),
                    min_zone=float(self._follow_cfg().get("pan_min_step_zone_norm", 0.12)),
                    max_step=self.max_pan_step_input.value(),
                )
            else:
                step = self._axis_step(
                    ndy,
                    active_attr=f"_follow_active_{joint}",
                    gain=self.tilt_gain_input.value(),
                    sign=self._follow_joint_sign(joint),
                    dead=float(self._follow_cfg().get("tilt_dead_zone_norm", 0.035)),
                    resume=float(self._follow_cfg().get("tilt_resume_zone_norm", 0.055)),
                    min_step=float(self._follow_cfg().get("min_tilt_step_deg", 0.5)),
                    min_zone=float(self._follow_cfg().get("tilt_min_step_zone_norm", 0.12)),
                    max_step=self.max_tilt_step_input.value(),
                )
            if step is not None:
                commands.append({"joint_key": joint, "delta_deg": step, "kind": "vision_follow", "axis": axis})
        return commands

    def _reset_follow_joint_activity(self) -> None:
        for joint in self.FOLLOW_JOINT_AXES:
            setattr(self, f"_follow_active_{joint}", False)

    def _live_rail_mm(self) -> float:
        joints = self.latest_robot_state.get("joints_deg", {})
        if isinstance(joints, dict) and "j10" in joints:
            try:
                return float(joints["j10"])
            except (TypeError, ValueError):
                pass
        runtime = self._peek_cinematic_runtime()
        return float(runtime.rail_virtual_pos_mm) if runtime is not None else 0.0

    def _cinematic_context(self) -> dict[str, Any]:
        selected = self._selected_follow_joints()
        return {
            "selected_joints": sorted(selected),
            "signs": {joint: self._follow_joint_sign(joint) for joint in selected},
            "pan_gain": self.pan_gain_input.value(),
            "tilt_gain": self.tilt_gain_input.value(),
        }

    def _result_mentions_joint(self, result: dict[str, Any], joint: str) -> bool:
        data = result_data(result)
        commands = data.get("commands", []) if isinstance(data.get("commands"), list) else []
        if any(str(item.get("joint_key", "")) == joint for item in commands if isinstance(item, dict)):
            return True
        targets = data.get("targets_deg", {}) if isinstance(data.get("targets_deg"), dict) else {}
        if joint in targets:
            return True
        move_result = data.get("move_result", {}) if isinstance(data.get("move_result"), dict) else {}
        move_data = result_data(move_result)
        move_targets = move_data.get("targets_deg", {}) if isinstance(move_data.get("targets_deg"), dict) else {}
        return joint in move_targets

    def _build_playback_commands(self) -> list[dict[str, Any]]:
        runtime = self._get_cinematic_runtime()
        if runtime.playback_index >= len(runtime.playback_plan):
            self.follow_running = False
            total = len(runtime.playback_plan)
            self._set_command_status("回放完成", "--", f"{total}/{total}", "正式运镜完成")
            return []
        commands = runtime.build_playback_commands(self._selected_follow_joints())
        if runtime.playback_index < len(runtime.playback_plan):
            self.timer.setInterval(runtime.playback_interval_ms())
        return commands

    def _get_cinematic_runtime(self) -> Any:
        if self._cinematic_runtime is None:
            from gui_app.AI运镜运行时_cinematic_runtime import CinematicRehearsalRuntime

            self._cinematic_runtime = CinematicRehearsalRuntime(self.project_root, lambda: self.config)
        return self._cinematic_runtime

    def _peek_cinematic_runtime(self) -> Any | None:
        return self._cinematic_runtime

    def _axis_step(self, norm_value: float, *, active_attr: str, gain: float, sign: float, dead: float, resume: float, min_step: float, min_zone: float, max_step: float) -> float | None:
        step, next_active = compute_axis_step(
            norm_value,
            active=bool(getattr(self, active_attr, False)),
            gain=gain,
            sign=sign,
            dead=dead,
            resume=resume,
            min_step=min_step,
            min_zone=min_zone,
            max_step=max_step,
        )
        setattr(self, active_attr, next_active)
        return step

    def _load_vision_config(self) -> dict[str, Any]:
        return load_vision_config(self.vision_root)

    def _follow_cfg(self) -> dict[str, Any]:
        follow = self.config.get("follow", {})
        return dict(follow) if isinstance(follow, dict) else {}

    def _enabled_follow_joints(self) -> set[str]:
        raw = self._follow_cfg().get("enabled_follow_joints", ["j11", "j13"])
        if not isinstance(raw, (list, tuple, set)):
            raw = ["j11", "j13"]
        selected = {str(item).lower() for item in raw}
        return {joint for joint in selected if joint in self.FOLLOW_JOINT_AXES}

    def _selected_follow_joints(self) -> set[str]:
        return {joint for joint, checkbox in self.follow_joint_checks.items() if checkbox.isChecked()}

    def _follow_joint_sign(self, joint: str) -> float:
        signs = self._follow_cfg().get("follow_joint_signs", {})
        if isinstance(signs, dict) and joint in signs:
            return float(signs[joint])
        axis = self.FOLLOW_JOINT_AXES.get(joint, "pan")
        default_key = "pan_sign" if axis == "pan" else "tilt_sign"
        return float(self._follow_cfg().get(default_key, 1.0))
