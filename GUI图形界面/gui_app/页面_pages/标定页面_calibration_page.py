"""标定状态页面。"""

from __future__ import annotations

from pathlib import Path

from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QLabel, QPushButton, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget


class CalibrationPage(QWidget):
    refresh_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        self.path_label = QLabel("标定文件：--")
        self.status_label = QLabel("完整性：未知")
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(["关节", "id", "模式", "zero_present_raw", "home_present_raw", "range_min", "range_max", "phase"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.refresh_button = QPushButton("刷新标定状态")
        self.help_button = QPushButton("打开标定说明")
        self.command_text = QTextEdit()
        self.command_text.setReadOnly(True)
        self.command_text.setPlainText(
            "第一版 GUI 不直接运行标定程序。\n\n"
            "请在终端运行：\n"
            "mamba run -n momo_rebot python ../真实舵机控制/标定程序_calibrate.py\n"
            "mamba run -n momo_rebot python ../真实舵机控制/标定应用_apply_calibration.py"
        )
        layout.addWidget(self.path_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.table, 1)
        layout.addWidget(self.refresh_button)
        layout.addWidget(self.help_button)
        layout.addWidget(self.command_text)
        self.refresh_button.clicked.connect(self.refresh_requested.emit)
        self.help_button.clicked.connect(self._show_calibration_help)

    def _show_calibration_help(self) -> None:
        path = Path(__file__).resolve().parents[3] / "真实舵机控制" / "标定说明.md"
        if not path.exists():
            self.command_text.setPlainText(f"未找到标定说明：{path}")
            return
        text = path.read_text(encoding="utf-8", errors="replace")
        self.command_text.setPlainText(f"标定说明：{path}\n\n{text}")

    def set_status(self, report: dict) -> None:
        calibration = report.get("calibration", report)
        self.path_label.setText(f"标定文件：{calibration.get('标定文件', '--')}")
        allow = bool(calibration.get("允许真机移动"))
        exists = bool(calibration.get("是否存在"))
        self.status_label.setText(f"完整性：{'完整' if allow else '不完整'} | 文件存在：{exists} | 是否允许真实移动：{allow}")
        items = calibration.get("项目", {})
        self.table.setRowCount(len(items))
        for row, (joint, item) in enumerate(items.items()):
            entry = {}
            try:
                path_text = calibration.get("标定文件")
                if path_text:
                    import json
                    from pathlib import Path

                    payload = json.loads(Path(path_text).read_text(encoding="utf-8")) if Path(path_text).exists() else {}
                    entry = payload.get(joint, {}) if isinstance(payload, dict) else {}
            except Exception:
                entry = {}
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
                self.table.setItem(row, col, QTableWidgetItem(str(value)))
