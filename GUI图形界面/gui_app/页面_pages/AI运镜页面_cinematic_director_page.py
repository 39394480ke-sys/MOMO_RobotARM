"""AI 摄影导演式运镜页面。"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import (
    QCheckBox,
    QFileDialog,
    QGroupBox,
    QLabel,
    QLineEdit,
    QPushButton,
    QTabWidget,
    QTextEdit,
    QWidget,
)

from gui_app.AI运镜文本格式化_cinematic_text_format import (
    format_cinematic_analysis,
    format_cinematic_keyframes,
    format_cinematic_trajectory,
)
from gui_app.结果格式化_result_format import result_data, result_message
from gui_app.组件_widgets.布局工具_layout_tools import make_form_layout, make_grid_layout, make_hbox_layout, make_vbox_layout
from gui_app.组件_widgets.数值输入工具_spinbox_tools import make_double_spin, make_int_spin


class CinematicDirectorPage(QWidget):
    latest_record_requested = pyqtSignal()
    rehearsal_start_requested = pyqtSignal(dict)
    rehearsal_playback_requested = pyqtSignal(dict)
    rehearsal_clear_requested = pyqtSignal()
    rehearsal_save_requested = pyqtSignal()
    rehearsal_load_requested = pyqtSignal()
    analyze_requested = pyqtSignal(str, str)
    keyframes_requested = pyqtSignal(str, int, int)
    generate_action_requested = pyqtSignal(str, str)
    play_action_requested = pyqtSignal(str)

    def __init__(self, project_root: str | Path, parent=None):
        super().__init__(parent)
        self.project_root = Path(project_root).resolve()
        self.current_project_path = ""
        self.generated_action_name = ""

        layout = make_vbox_layout(self, margins=(14, 14, 14, 14), spacing=10)

        header = make_hbox_layout()
        self.project_label = QLabel("项目：未生成")
        self.project_label.setObjectName("StatusPill")
        self.stage_label = QLabel("阶段：待试拍分析")
        self.stage_label.setObjectName("ReadyPill")
        header.addWidget(self.project_label, 2)
        header.addWidget(self.stage_label, 1)
        layout.addLayout(header)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_capture_tab(), "试拍")
        self.tabs.addTab(self._build_analysis_tab(), "分析")
        self.tabs.addTab(self._build_keyframes_tab(), "关键帧")
        self.tabs.addTab(self._build_trajectory_tab(), "轨迹/执行")
        layout.addWidget(self.tabs, 1)

    def _build_capture_tab(self) -> QWidget:
        page = QWidget()
        layout = self._tab_layout(page)

        source_box = QGroupBox("试拍数据")
        form = make_form_layout(source_box)
        self.record_input = QLineEdit()
        self.record_input.setPlaceholderText("cinematic_rehearsal_*.json，同步关节状态来自这里")
        self.video_input = QLineEdit()
        self.video_input.setPlaceholderText("可选：试拍视频文件，用于画面清晰度/光流分析")

        record_row = make_hbox_layout()
        self.latest_record_button = QPushButton("加载最新试拍记录")
        self.choose_record_button = QPushButton("选择记录")
        record_row.addWidget(self.record_input, 1)
        record_row.addWidget(self.latest_record_button)
        record_row.addWidget(self.choose_record_button)

        video_row = make_hbox_layout()
        self.choose_video_button = QPushButton("选择视频")
        video_row.addWidget(self.video_input, 1)
        video_row.addWidget(self.choose_video_button)

        form.addRow("同步记录", record_row)
        form.addRow("试拍视频", video_row)
        layout.addWidget(source_box)

        rail_box = QGroupBox("导轨试拍")
        rail_layout = make_grid_layout(rail_box)
        self.rail_enabled_checkbox = QCheckBox("启用 J10 自动扫轨")
        self.rail_enabled_checkbox.setChecked(True)
        self.rail_start_input = make_double_spin(-140.0, 140.0, -40.0, 0.5, suffix=" mm", minimum_height=30)
        self.rail_end_input = make_double_spin(-140.0, 140.0, 40.0, 0.5, suffix=" mm", minimum_height=30)
        self.rail_speed_input = make_double_spin(0.2, 80.0, 5.0, 0.5, suffix=" mm/s", minimum_height=30)
        rail_layout.addWidget(self.rail_enabled_checkbox, 0, 0, 1, 2)
        for row, (title, widget) in enumerate((("起点", self.rail_start_input), ("终点", self.rail_end_input), ("速度", self.rail_speed_input)), start=1):
            rail_layout.addWidget(QLabel(title), row, 0)
            rail_layout.addWidget(widget, row, 1)
        layout.addWidget(rail_box)

        two_step_box = QGroupBox("两步运镜采样")
        two_layout = make_grid_layout(two_step_box)
        self.sample_interval_input = make_double_spin(0.05, 2.0, 0.12, 0.01, suffix=" s", minimum_height=30)
        self.playback_smooth_input = make_double_spin(0.0, 0.95, 0.55, 0.05, minimum_height=30)
        self.playback_speed_input = make_double_spin(0.2, 3.0, 1.0, 0.1, suffix=" x", minimum_height=30)
        self.max_comp_input = make_double_spin(0.2, 12.0, 4.0, 0.1, suffix="°", minimum_height=30)
        self.offset_stop_input = make_double_spin(0.05, 1.0, 0.65, 0.05, minimum_height=30)
        self.playback_hz_input = make_double_spin(5.0, 30.0, 20.0, 1.0, suffix=" Hz", minimum_height=30)
        self.ease_sec_input = make_double_spin(0.0, 3.0, 0.8, 0.1, suffix=" s", minimum_height=30)
        self.min_rail_step_input = make_double_spin(0.05, 5.0, 0.25, 0.05, suffix=" mm", minimum_height=30)
        for row, (title, widget) in enumerate(
            (
                ("采样间隔", self.sample_interval_input),
                ("平滑强度", self.playback_smooth_input),
                ("回放倍率", self.playback_speed_input),
                ("最大补偿", self.max_comp_input),
                ("偏移阈值", self.offset_stop_input),
                ("回放频率", self.playback_hz_input),
                ("缓入缓出", self.ease_sec_input),
                ("最小步长", self.min_rail_step_input),
            )
        ):
            two_layout.addWidget(QLabel(title), row // 2, (row % 2) * 2)
            two_layout.addWidget(widget, row // 2, (row % 2) * 2 + 1)
        layout.addWidget(two_step_box)

        self.start_rehearsal_button = QPushButton("试拍开始")
        self.start_rehearsal_button.setObjectName("PrimaryButton")
        self.rehearsal_playback_button = QPushButton("试拍回放")
        self.rehearsal_clear_button = QPushButton("清除记录")
        self.rehearsal_save_button = QPushButton("保存记录")
        self.rehearsal_load_button = QPushButton("加载记录")
        layout.addLayout(
            self._button_row(
                self.start_rehearsal_button,
                self.rehearsal_playback_button,
                self.rehearsal_clear_button,
                self.rehearsal_save_button,
                self.rehearsal_load_button,
            )
        )

        self.analyze_button = QPushButton("分析试拍")
        self.analyze_button.setObjectName("PrimaryButton")
        layout.addWidget(self.analyze_button)
        layout.addStretch(1)

        self.latest_record_button.clicked.connect(self.latest_record_requested.emit)
        self.choose_record_button.clicked.connect(self._choose_record)
        self.choose_video_button.clicked.connect(self._choose_video)
        self.start_rehearsal_button.clicked.connect(lambda: self.rehearsal_start_requested.emit(self.cinematic_settings()))
        self.rehearsal_playback_button.clicked.connect(lambda: self.rehearsal_playback_requested.emit(self.cinematic_settings()))
        self.rehearsal_clear_button.clicked.connect(self.rehearsal_clear_requested.emit)
        self.rehearsal_save_button.clicked.connect(self.rehearsal_save_requested.emit)
        self.rehearsal_load_button.clicked.connect(self.rehearsal_load_requested.emit)
        self.analyze_button.clicked.connect(lambda: self.analyze_requested.emit(self.record_input.text(), self.video_input.text()))
        return page

    def cinematic_settings(self) -> dict[str, Any]:
        return {
            "rail": {
                "enabled": self.rail_enabled_checkbox.isChecked(),
                "start_mm": self.rail_start_input.value(),
                "end_mm": self.rail_end_input.value(),
                "speed_mm_s": self.rail_speed_input.value(),
            },
            "two_step": {
                "sample_interval_sec": self.sample_interval_input.value(),
                "playback_smooth": self.playback_smooth_input.value(),
                "playback_speed_scale": self.playback_speed_input.value(),
                "max_compensation_deg": self.max_comp_input.value(),
                "offset_stop_norm": self.offset_stop_input.value(),
                "playback_hz": self.playback_hz_input.value(),
                "ease_sec": self.ease_sec_input.value(),
                "min_rail_step_mm": self.min_rail_step_input.value(),
            },
        }

    def _build_analysis_tab(self) -> QWidget:
        page = QWidget()
        layout = self._tab_layout(page)
        self.analysis_text = QTextEdit()
        self.analysis_text.setObjectName("DetailText")
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setPlainText("等待试拍分析。")
        layout.addWidget(self.analysis_text, 1)
        return page

    def _build_keyframes_tab(self) -> QWidget:
        page = QWidget()
        layout = self._tab_layout(page)
        controls = make_hbox_layout()
        self.min_keyframes_spin = make_int_spin(3, 8, 3)
        self.max_keyframes_spin = make_int_spin(3, 8, 8)
        self.keyframes_button = QPushButton("生成导演关键帧")
        self.keyframes_button.setObjectName("PrimaryButton")
        controls.addWidget(QLabel("最少"))
        controls.addWidget(self.min_keyframes_spin)
        controls.addWidget(QLabel("最多"))
        controls.addWidget(self.max_keyframes_spin)
        controls.addStretch(1)
        controls.addWidget(self.keyframes_button)
        layout.addLayout(controls)
        self.keyframes_text = QTextEdit()
        self.keyframes_text.setObjectName("DetailText")
        self.keyframes_text.setReadOnly(True)
        self.keyframes_text.setPlainText("等待关键帧生成。")
        layout.addWidget(self.keyframes_text, 1)
        self.keyframes_button.clicked.connect(
            lambda: self.keyframes_requested.emit(
                self.current_project_path,
                self.min_keyframes_spin.value(),
                self.max_keyframes_spin.value(),
            )
        )
        return page

    def _build_trajectory_tab(self) -> QWidget:
        page = QWidget()
        layout = self._tab_layout(page)
        form = make_form_layout(margins=(0, 0, 0, 0))
        self.action_name_input = QLineEdit()
        self.action_name_input.setPlaceholderText("例如：AI运镜_产品展示_01")
        form.addRow("动作名称", self.action_name_input)
        layout.addLayout(form)

        self.generate_action_button = QPushButton("生成动作库动作")
        self.generate_action_button.setObjectName("PrimaryButton")
        self.play_action_button = QPushButton("dry-run/当前模式播放")
        self.play_action_button.setObjectName("WarningButton")
        self.play_action_button.setEnabled(False)
        layout.addLayout(self._button_row(self.generate_action_button, self.play_action_button, stretch=True))

        self.trajectory_text = QTextEdit()
        self.trajectory_text.setObjectName("DetailText")
        self.trajectory_text.setReadOnly(True)
        self.trajectory_text.setPlainText("等待轨迹生成。")
        layout.addWidget(self.trajectory_text, 1)

        self.generate_action_button.clicked.connect(lambda: self.generate_action_requested.emit(self.current_project_path, self.action_name_input.text()))
        self.play_action_button.clicked.connect(lambda: self.play_action_requested.emit(self.generated_action_name))
        return page

    def _tab_layout(self, page: QWidget):
        return make_vbox_layout(page, margins=(8, 10, 8, 8), spacing=10)

    def _button_row(self, *buttons: QPushButton, stretch: bool = False):
        row = make_hbox_layout()
        for button in buttons:
            row.addWidget(button)
        if stretch:
            row.addStretch(1)
        return row

    def set_latest_record(self, result: dict[str, Any]) -> None:
        if result.get("ok"):
            path = str(result_data(result).get("record_path", ""))
            self.record_input.setText(path)
        self.show_result(result)

    def set_project_result(self, result: dict[str, Any]) -> None:
        self.show_result(result)
        data = result_data(result)
        project = data.get("project") if isinstance(data.get("project"), dict) else {}
        project_path = str(data.get("project_path", self.current_project_path) or "")
        if project_path:
            self.current_project_path = project_path
            self.project_label.setText(f"项目：{Path(project_path).name}")
        stage = str(project.get("workflow_stage") or "--")
        self.stage_label.setText(f"阶段：{stage}")

        if "motion_analysis" in project:
            self.analysis_text.setPlainText(format_cinematic_analysis(project))
            self.tabs.setCurrentIndex(1)
        if "director_keyframes" in project:
            self.keyframes_text.setPlainText(format_cinematic_keyframes(project.get("director_keyframes", [])))
            self.tabs.setCurrentIndex(2)
        generated = project.get("generated_action") if isinstance(project.get("generated_action"), dict) else {}
        if generated:
            self.generated_action_name = str(generated.get("name", ""))
            self.play_action_button.setEnabled(bool(self.generated_action_name))
            self.trajectory_text.setPlainText(format_cinematic_trajectory(project))
            self.tabs.setCurrentIndex(3)

    def show_result(self, result: dict[str, Any]) -> None:
        if not result:
            return
        message = result_message(result)
        if not result.get("ok", False):
            self.stage_label.setText("阶段：错误")
            self.analysis_text.setPlainText(message)

    def _choose_record(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择试拍记录", str(self.project_root), "JSON (*.json)")
        if path:
            self.record_input.setText(path)

    def _choose_video(self) -> None:
        path, _filter = QFileDialog.getOpenFileName(self, "选择试拍视频", str(self.project_root), "Video (*.mp4 *.mov *.avi *.mkv);;All Files (*)")
        if path:
            self.video_input.setText(path)
