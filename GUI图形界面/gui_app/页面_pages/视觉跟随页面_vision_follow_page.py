"""视觉识别与跟随页面。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import (
    QCheckBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSlider,
    QVBoxLayout,
    QWidget,
)


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

    def __init__(self, project_root: str | Path, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.vision_root = self.project_root / "视觉识别与跟随"
        self.config = self._load_vision_config()
        self.engine: Any | None = None
        self.vision_running = False
        self.follow_running = False
        self.command_in_flight = False
        self._pan_active = False
        self._tilt_active = False
        self.last_command: dict[str, Any] | None = None

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(16)

        left = QVBoxLayout()
        left.setSpacing(10)
        self.image_label = QLabel("视觉画面未启动")
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

        self.right_panel = QWidget()
        self.right_panel.setMinimumWidth(320)
        self.right_panel.setMaximumWidth(360)
        self.right_panel.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        right = QVBoxLayout(self.right_panel)
        right.setContentsMargins(0, 0, 0, 0)
        right.setSpacing(10)
        status_box = QGroupBox("跟随概览")
        status_layout = QGridLayout(status_box)
        status_layout.setContentsMargins(12, 18, 12, 12)
        status_layout.setSpacing(8)
        self.status_labels: dict[str, QLabel] = {}
        status_titles = {
            "vision": "视觉",
            "follow": "跟随",
            "detected": "识别",
            "fps": "帧率",
            "direction": "方向",
            "dead_zone": "死区",
            "ndx": "水平偏移",
            "ndy": "垂直偏移",
        }
        for index, key in enumerate(("vision", "follow", "detected", "fps", "direction", "dead_zone", "ndx", "ndy")):
            title = QLabel(status_titles[key])
            title.setObjectName("PathName")
            value = QLabel("--")
            value.setObjectName("StatusPill")
            self.status_labels[key] = value
            status_layout.addWidget(title, index // 2, (index % 2) * 2)
            status_layout.addWidget(value, index // 2, (index % 2) * 2 + 1)
        right.addWidget(status_box)

        config_box = QGroupBox("跟随参数")
        config_layout = QVBoxLayout(config_box)
        config_layout.setContentsMargins(12, 18, 12, 12)
        config_layout.setSpacing(10)
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
        right.addWidget(config_box)

        command_box = QGroupBox("最近命令")
        command_layout = QGridLayout(command_box)
        command_layout.setContentsMargins(12, 18, 12, 12)
        command_layout.setSpacing(8)
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
        self._update_status_labels({})

    def start_vision(self) -> None:
        if self.vision_running:
            return
        try:
            vision_root_text = str(self.vision_root)
            if vision_root_text not in sys.path:
                sys.path.insert(0, vision_root_text)
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
        self._update_status_labels({})

    def start_follow(self) -> None:
        if not self.vision_running:
            self.start_vision()
        self.follow_running = True
        self.command_in_flight = False
        self._pan_active = False
        self._tilt_active = False

    def stop_follow(self) -> None:
        self.follow_running = False
        self.command_in_flight = False
        self._pan_active = False
        self._tilt_active = False

    def set_follow_result(self, result: dict[str, Any]) -> None:
        self.command_in_flight = False
        self.last_command = result

    def is_real_execute_enabled(self) -> bool:
        return self.execute_checkbox.isChecked()

    def _tick(self) -> None:
        if self.engine is None:
            return
        result = self.engine.get_latest_result()
        frame = self.engine.get_latest_frame()
        if frame is not None:
            self._show_frame(frame)
        self._update_status_labels(result)
        commands = self._build_follow_commands(result) if self.follow_running else []
        if commands and not self.command_in_flight:
            self.command_in_flight = True
            self.follow_commands_requested.emit(commands)
        self._show_detail(result, commands)

    def _show_frame(self, frame: Any) -> None:
        try:
            import cv2  # type: ignore
            import numpy as np  # type: ignore

            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            rgb = np.ascontiguousarray(rgb)
            height, width, channels = rgb.shape
            qimage = QImage(rgb.data, width, height, channels * width, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage.copy())
            self.image_label.setPixmap(pixmap.scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception as exc:
            self.image_label.setText(f"画面显示失败：{exc}")

    def _update_status_labels(self, result: dict[str, Any]) -> None:
        offset = result.get("offset", {}) if result else {}
        direction = result.get("direction", {}) if result else {}
        self.status_labels["vision"].setText("运行" if self.vision_running else "停止")
        self.status_labels["follow"].setText("运行" if self.follow_running else "停止")
        self.status_labels["detected"].setText("是" if result and result.get("detected", False) else ("否" if result else "--"))
        self.status_labels["fps"].setText(f"{float(result.get('fps', 0.0)):.1f}" if result else "--")
        self.status_labels["direction"].setText(self._direction_text(str(direction.get("combined", "--"))))
        self.status_labels["dead_zone"].setText("是" if result and offset.get("in_dead_zone", True) else ("否" if result else "--"))
        self.status_labels["ndx"].setText(f"{float(offset.get('ndx', 0.0)):.4f}" if result else "--")
        self.status_labels["ndy"].setText(f"{float(offset.get('ndy', 0.0)):.4f}" if result else "--")

    def _show_detail(self, result: dict[str, Any], commands: list[dict[str, Any]]) -> None:
        if commands:
            joints = ", ".join(str(item.get("joint_key", "")) for item in commands)
            deltas = ", ".join(f"{float(item.get('delta_deg', 0.0)):+.3f}°" for item in commands)
            self._set_command_status("待执行", joints, deltas, "等待执行")
            return
        if self.last_command:
            data = self.last_command.get("data", {}) if isinstance(self.last_command.get("data"), dict) else {}
            responses = data.get("responses", []) if isinstance(data.get("responses"), list) else []
            if responses:
                ok_count = sum(1 for item in responses if item.get("ok"))
                joints = ", ".join(str(cmd.get("joint_key", "")) for cmd in data.get("commands", []))
                deltas = ", ".join(f"{float(cmd.get('delta_deg', 0.0)):+.3f}°" for cmd in data.get("commands", []))
                self._set_command_status("已完成", joints or "--", deltas or "--", f"{ok_count}/{len(responses)} 成功")
            else:
                self._set_command_status("已完成" if self.last_command.get("ok") else "错误", "--", "--", str(self.last_command.get("message", "--")))
            return
        message = str(result.get("message", "--")) if result else "--"
        self._set_command_status("空闲", "--", "--", message)

    def _set_command_status(self, action: str, joint: str, delta: str, result: str) -> None:
        self.command_labels["action"].setText(action)
        self.command_labels["joint"].setText(joint)
        self.command_labels["delta"].setText(delta)
        self.command_labels["result"].setText(result)

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
        if not result.get("detected", False):
            self._pan_active = False
            self._tilt_active = False
            return []
        smoothed = result.get("smoothed_offset") or {}
        if not smoothed.get("valid", False):
            return []
        ndx = float(smoothed.get("ndx", 0.0))
        ndy = float(smoothed.get("ndy", 0.0))
        commands: list[dict[str, Any]] = []
        pan = self._axis_step(
            ndx,
            active_attr="_pan_active",
            gain=self.pan_gain_input.value(),
            sign=float(self._follow_cfg().get("pan_sign", 1.0)),
            dead=float(self._follow_cfg().get("pan_dead_zone_norm", 0.03)),
            resume=float(self._follow_cfg().get("pan_resume_zone_norm", 0.05)),
            min_step=float(self._follow_cfg().get("min_pan_step_deg", 0.5)),
            min_zone=float(self._follow_cfg().get("pan_min_step_zone_norm", 0.12)),
            max_step=self.max_pan_step_input.value(),
        )
        if pan is not None:
            commands.append({"joint_key": str(self._follow_cfg().get("pan_joint", "shoulder_pan")), "delta_deg": pan})
        tilt = self._axis_step(
            ndy,
            active_attr="_tilt_active",
            gain=self.tilt_gain_input.value(),
            sign=float(self._follow_cfg().get("tilt_sign", -1.0)),
            dead=float(self._follow_cfg().get("tilt_dead_zone_norm", 0.035)),
            resume=float(self._follow_cfg().get("tilt_resume_zone_norm", 0.055)),
            min_step=float(self._follow_cfg().get("min_tilt_step_deg", 0.5)),
            min_zone=float(self._follow_cfg().get("tilt_min_step_zone_norm", 0.12)),
            max_step=self.max_tilt_step_input.value(),
        )
        if tilt is not None:
            commands.append({"joint_key": str(self._follow_cfg().get("tilt_joint", "elbow_flex")), "delta_deg": tilt})
        return commands

    def _axis_step(self, norm_value: float, *, active_attr: str, gain: float, sign: float, dead: float, resume: float, min_step: float, min_zone: float, max_step: float) -> float | None:
        active = bool(getattr(self, active_attr))
        abs_norm = abs(float(norm_value))
        if active:
            if abs_norm <= dead:
                setattr(self, active_attr, False)
                return None
        else:
            if abs_norm < resume:
                return None
            setattr(self, active_attr, True)
        raw = float(norm_value) * float(gain) * float(sign)
        if abs(raw) <= 1e-9:
            return None
        step_abs = abs(raw)
        if abs_norm >= min_zone and min_step > 0:
            step_abs = max(step_abs, min_step)
        step_abs = min(step_abs, max_step)
        return round(step_abs if raw > 0 else -step_abs, 4)

    def _load_vision_config(self) -> dict[str, Any]:
        path = self.vision_root / "视觉配置.yaml"
        try:
            import yaml  # type: ignore

            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _follow_cfg(self) -> dict[str, Any]:
        follow = self.config.get("follow", {})
        return dict(follow) if isinstance(follow, dict) else {}
