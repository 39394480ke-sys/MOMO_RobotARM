"""GUI 主题样式。"""

from __future__ import annotations


def build_stylesheet() -> str:
    return """
    QMainWindow, QWidget {
        background: #f6f7f9;
        color: #1f2933;
        font-family: "PingFang SC", "Microsoft YaHei", Arial;
        font-size: 13px;
    }
    QFrame#TopBar {
        background: #ffffff;
        border-bottom: 1px solid #d8dee6;
    }
    QLabel#TitleLabel {
        font-size: 18px;
        font-weight: 700;
    }
    QPushButton {
        background: #ffffff;
        border: 1px solid #c7d0da;
        border-radius: 6px;
        padding: 6px 10px;
    }
    QPushButton:hover {
        background: #eef4fb;
    }
    QPushButton:disabled {
        color: #9aa5b1;
        background: #edf0f3;
    }
    QPushButton#DangerButton {
        background: #c62828;
        color: white;
        border: 1px solid #a51f1f;
        font-weight: 700;
    }
    QPushButton#PrimaryButton {
        background: #1769aa;
        color: white;
        border: 1px solid #145a92;
    }
    QListWidget, QTextEdit, QPlainTextEdit, QTableWidget, QLineEdit, QComboBox, QDoubleSpinBox, QSpinBox {
        background: #ffffff;
        border: 1px solid #cfd7e2;
        border-radius: 5px;
        padding: 4px;
    }
    QListWidget#NavList {
        background: #25313f;
        color: #e8edf3;
        border: none;
        padding: 6px;
        font-size: 14px;
    }
    QListWidget#NavList::item {
        padding: 10px 12px;
        border-radius: 5px;
    }
    QListWidget#NavList::item:selected {
        background: #3f5166;
    }
    QGroupBox {
        border: 1px solid #d4dce6;
        border-radius: 7px;
        margin-top: 10px;
        padding: 10px;
        background: #ffffff;
        font-weight: 600;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 4px;
    }
    """

