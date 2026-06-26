"""标定状态页面。"""

from __future__ import annotations

from gui_app.path_utils import PROJECT_ROOT, ensure_project_root_on_path

ensure_project_root_on_path()

from 通用_io import read_json_object_or_default, read_text

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget


class CalibrationPage(QWidget):
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 14)
        layout.setSpacing(12)
        self.path_label = QLabel("标定文件：--")
        self.path_label.setObjectName("PathLabel")
        self.status_label = QLabel("完整性：未知")
        self.status_label.setObjectName("StatusPill")
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["关节", "ID", "模式", "零点原始值", "Home 原始值", "最小范围", "最大范围", "相位"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.refresh_button = QPushButton("刷新标定状态")
        self.refresh_button.setObjectName("PrimaryButton")
        self.guide_button = QPushButton("标定向导")
        self.help_button = QPushButton("打开标定说明")
        self.command_button = QPushButton("显示终端命令")
        self.command_text = QTextEdit()
        self.command_text.setObjectName("ResultText")
        self.command_text.setReadOnly(True)
        self.command_text.setPlainText(
            "标定操作涉及真实硬件移动，当前 GUI 仅展示状态与说明。\n\n"
            "推荐流程：\n"
            "1. 阅读标定说明。\n"
            "2. 在安全环境中运行标定程序。\n"
            "3. 回到本页刷新标定状态。"
        )
        layout.addWidget(self.path_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.guide_button)
        layout.addWidget(self.help_button)
        layout.addWidget(self.command_button)
        layout.addWidget(self.command_text)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.guide_button.clicked.connect(self._show_calibration_guide)
        self.help_button.clicked.connect(self._show_calibration_help)
        self.command_button.clicked.connect(self._show_calibration_commands)

    def _show_calibration_guide(self) -> None:
        self.command_text.setPlainText(
            "GUI 标定向导\n\n"
            "阶段 1：准备\n"
            "- 连接真实模式，确认串口正确。\n"
            "- 确认机械臂供电稳定，关节附近无遮挡。\n\n"
            "阶段 2：检查\n"
            "- 点击“刷新标定状态”，确认标定文件存在。\n"
            "- 表格里每个关节都应该有 ID、模式、零点、Home、范围。\n\n"
            "阶段 3：执行标定\n"
            "- 当前 GUI 不直接驱动完整标定流程，避免误写真实舵机寄存器。\n"
            "- 点击“显示终端命令”，在终端执行标定程序。\n\n"
            "阶段 4：验证\n"
            "- 标定程序完成后回到 GUI，点击“刷新标定状态”。\n"
            "- 状态显示“完整”后，再进行 Home、单关节小步进和 IK 测试。"
        )

    def _show_calibration_help(self) -> None:
        path = PROJECT_ROOT / "真实舵机控制" / "标定说明.md"
        if not path.exists():
            self.command_text.setPlainText(f"未找到标定说明：{path}")
            return
        text = read_text(path, errors="replace")
        self.command_text.setPlainText(f"标定说明：{path}\n\n{text}")

    def _show_calibration_commands(self) -> None:
        calibrate = PROJECT_ROOT / "真实舵机控制" / "标定程序_calibrate.py"
        apply = PROJECT_ROOT / "真实舵机控制" / "标定应用_apply_calibration.py"
        self.command_text.setPlainText(
            "标定终端命令\n\n"
            "1. 运行完整标定程序：\n"
            f"mamba run -n momo_rebot python \"{calibrate}\"\n\n"
            "2. 应用已有标定文件：\n"
            f"mamba run -n momo_rebot python \"{apply}\"\n\n"
            "3. 回到 GUI 后点击“刷新标定状态”。"
        )

    def set_status(self, report: dict) -> None:
        calibration = report.get("calibration", report)
        self.path_label.setText(f"标定文件：{calibration.get('标定文件', '--')}")
        allow = bool(calibration.get("允许真机移动"))
        exists = bool(calibration.get("是否存在"))
        self.status_label.setText(f"完整性：{'完整' if allow else '不完整'} | 文件存在：{exists} | 是否允许真实移动：{allow}")
        self.status_label.setObjectName("ReadyPill" if allow else "ErrorPill")
        self.status_label.style().unpolish(self.status_label)
        self.status_label.style().polish(self.status_label)
        items = calibration.get("项目", {})
        calibration_entries = self._load_calibration_entries(calibration)
        self.table.setRowCount(len(items))
        for row, (joint, item) in enumerate(items.items()):
            entry = calibration_entries.get(joint, {})
            values = [
                item.get("show_name", joint),
                entry.get("id", ""),
                entry.get("模式", ""),
                entry.get("zero_present_raw", ""),
                entry.get("home_present_raw", ""),
                entry.get("range_min", ""),
                entry.get("range_max", ""),
                entry.get("phase", ""),
            ]
            for col, value in enumerate(values):
                table_item = QTableWidgetItem(str(value))
                if col in (5, 6):
                    try:
                        number = float(value)
                        if abs(number) > 360:
                            table_item.setBackground(QColor("#fee2e2"))
                            table_item.setForeground(QColor("#991b1b"))
                    except Exception:
                        pass
                self.table.setItem(row, col, table_item)
        self.table.resizeColumnsToContents()

    def _load_calibration_entries(self, calibration: dict) -> dict[str, dict]:
        path_text = calibration.get("标定文件")
        if not path_text:
            return {}
        try:
            payload = read_json_object_or_default(path_text)
        except Exception:
            return {}
        return {str(key): value for key, value in payload.items() if isinstance(value, dict)} if isinstance(payload, dict) else {}
