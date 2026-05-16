"""GUI 主题样式。"""

from __future__ import annotations


def build_stylesheet() -> str:
    return """
    QMainWindow, QWidget {
        background: #f4f6f9;
        color: #1f2933;
        font-family: "PingFang SC", "Microsoft YaHei", Arial;
        font-size: 13px;
    }
    QLabel {
        background: transparent;
    }
    QFrame#TopBar {
        background: #111827;
        border-bottom: 1px solid #253244;
    }
    QLabel#TitleLabel {
        background: transparent;
        color: #f3f4f6;
        font-size: 18px;
        font-weight: 700;
    }
    QLabel#PanelTitle {
        background: transparent;
        color: #111827;
        font-size: 16px;
        font-weight: 700;
    }
    QLabel#StatusPill {
        background: #1f2937;
        color: #f3f4f6;
        border: 1px solid #334155;
        border-radius: 6px;
        padding: 6px 9px;
        font-weight: 600;
    }
    QLabel#ReadyPill {
        background: #0f2f27;
        color: #a7f3d0;
        border: 1px solid #10b981;
        border-radius: 6px;
        padding: 6px 9px;
        font-weight: 700;
    }
    QLabel#ErrorPill {
        background: #3b1111;
        color: #fecaca;
        border: 1px solid #dc2626;
        border-radius: 6px;
        padding: 6px 9px;
        font-weight: 600;
    }
    QLabel#SpeedLabel {
        background: transparent;
        color: #cbd5e1;
        font-weight: 600;
    }
    QPushButton {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 7px 11px;
        min-height: 18px;
        font-weight: 600;
    }
    QPushButton:hover {
        background: #f1f7ff;
        border-color: #9db6d2;
    }
    QPushButton:pressed {
        background: #e5edf7;
    }
    QPushButton:disabled {
        color: #9aa5b1;
        background: #edf0f3;
    }
    QPushButton#DangerButton {
        background: #dc2626;
        color: white;
        border: 2px solid #991b1b;
        font-weight: 700;
    }
    QPushButton#DangerButton:hover {
        background: #c81035;
    }
    QPushButton#WarningButton {
        background: #f59e0b;
        color: #111827;
        border: 2px solid #b45309;
        font-weight: 700;
    }
    QPushButton#WarningButton:hover {
        background: #ffe8a8;
    }
    QPushButton#PrimaryButton {
        background: #1769aa;
        color: white;
        border: 1px solid #0d5f9a;
    }
    QPushButton#PrimaryButton:hover {
        background: #0b609d;
    }
    QPushButton#ExecuteButton {
        background: #00f0ff;
        color: #07111f;
        border: 2px solid #00a7c2;
        border-radius: 6px;
        padding: 10px 14px;
        font-size: 15px;
        font-weight: 800;
    }
    QPushButton#ExecuteButton:hover {
        background: #33f5ff;
        border-color: #008ca3;
    }
    QPushButton#ExecuteButton:disabled {
        background: #e3e8ef;
        color: #8a96a8;
        border: 1px solid #c4ccd7;
    }
    QPushButton#GhostButton {
        background: #eef2f6;
        color: #344054;
    }
    QPushButton#TinyButton {
        padding: 5px 8px;
        min-height: 16px;
        font-size: 12px;
    }
    QPushButton#JointStepButton {
        background: #ffffff;
        color: #1769aa;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        padding: 0;
        min-width: 42px;
        min-height: 20px;
        font-size: 14px;
        font-weight: 800;
    }
    QPushButton#JointStepButton:hover {
        background: #eff6ff;
        border-color: #1769aa;
    }
    QPushButton#SegmentButton {
        background: #eef2f6;
        color: #334155;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        padding: 5px 12px;
        min-height: 22px;
        font-weight: 700;
    }
    QPushButton#SegmentButton:checked {
        background: #1769aa;
        color: #ffffff;
        border-color: #0d5f9a;
    }
    QListWidget, QTextEdit, QPlainTextEdit, QTableWidget, QLineEdit, QComboBox {
        background: #ffffff;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 6px;
        selection-background-color: #1769aa;
        selection-color: white;
    }
    QComboBox, QLineEdit {
        min-height: 24px;
    }
    QSpinBox, QDoubleSpinBox {
        background: #ffffff;
        color: #111827;
        border: 1px solid #cbd5e1;
        border-radius: 6px;
        padding: 4px 26px 4px 8px;
        min-height: 26px;
        selection-background-color: #1769aa;
        selection-color: white;
    }
    QSpinBox:hover, QDoubleSpinBox:hover {
        border-color: #9db6d2;
    }
    QSpinBox:focus, QDoubleSpinBox:focus {
        border-color: #1769aa;
    }
    QSpinBox::up-button, QDoubleSpinBox::up-button {
        subcontrol-origin: border;
        subcontrol-position: top right;
        width: 20px;
        height: 13px;
        border: none;
        border-left: 1px solid #d7e0ea;
        border-top-right-radius: 5px;
        background: #edf2f7;
        margin: 1px 1px 0 0;
    }
    QSpinBox::down-button, QDoubleSpinBox::down-button {
        subcontrol-origin: border;
        subcontrol-position: bottom right;
        width: 20px;
        height: 13px;
        border: none;
        border-left: 1px solid #d7e0ea;
        border-top: 1px solid #d7e0ea;
        border-bottom-right-radius: 5px;
        background: #edf2f7;
        margin: 0 1px 1px 0;
    }
    QSpinBox::up-button:hover, QDoubleSpinBox::up-button:hover,
    QSpinBox::down-button:hover, QDoubleSpinBox::down-button:hover {
        background: #dbeafe;
    }
    QSpinBox::up-arrow, QDoubleSpinBox::up-arrow {
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-bottom: 5px solid #334155;
    }
    QSpinBox::down-arrow, QDoubleSpinBox::down-arrow {
        width: 0;
        height: 0;
        border-left: 4px solid transparent;
        border-right: 4px solid transparent;
        border-top: 5px solid #334155;
    }
    QSpinBox::up-button:disabled, QDoubleSpinBox::up-button:disabled,
    QSpinBox::down-button:disabled, QDoubleSpinBox::down-button:disabled {
        background: #eef2f6;
    }
    QListWidget#NavList {
        background: #111827;
        color: #dbe4ef;
        border: none;
        padding: 8px;
        font-size: 14px;
        font-weight: 650;
    }
    QListWidget#NavList::item {
        padding: 11px 10px;
        margin: 2px 0;
        border-radius: 6px;
    }
    QListWidget#NavList::item:selected {
        background: #1769aa;
        color: #ffffff;
    }
    QListWidget#NavList::item:hover {
        background: #23344a;
    }
    QWidget#PersistentLogPanel {
        background: #ffffff;
        border-left: 1px solid #d8dee6;
    }
    QScrollArea#PageScrollArea {
        background: #f4f6f9;
        border: none;
    }
    QScrollArea#PageScrollArea > QWidget > QWidget {
        background: #f4f6f9;
    }
    QWidget#SimViewport {
        background: #f4f7fb;
        border: none;
    }
    QWidget#ViewportToolbar {
        background: rgba(17, 24, 39, 150);
        border: 1px solid rgba(148, 163, 184, 130);
        border-radius: 6px;
    }
    QPushButton#ViewportToolButton {
        background: rgba(255, 255, 255, 220);
        color: #111827;
        border: 1px solid #cbd5e1;
        border-radius: 5px;
        padding: 3px 5px;
        min-width: 38px;
        min-height: 18px;
        font-size: 11px;
        font-weight: 800;
    }
    QPushButton#ViewportToolButton:hover {
        background: #dbeafe;
        border-color: #1769aa;
    }
    QTextEdit#LogText {
        background: #10151f;
        color: #e2e8f0;
        border: 1px solid #1e293b;
        font-family: "Menlo", "Monaco";
        font-size: 12px;
        line-height: 140%;
    }
    QTextEdit#ResultText {
        background: #111827;
        color: #d1fae5;
        border: 1px solid #243244;
        font-family: "Menlo", "Monaco";
        font-size: 12px;
    }
    QTextEdit#DetailText {
        background: #f8fafc;
        color: #1f2937;
        border: 1px solid #d7e0ea;
        border-radius: 6px;
        font-family: "Menlo", "Monaco";
        font-size: 12px;
        padding: 8px;
    }
    QLabel#PathLabel {
        background: transparent;
        color: #52616f;
        font-size: 12px;
    }
    QLineEdit#PathLabel {
        background: #f8fafc;
        color: #52616f;
        border: 1px solid #d7e0ea;
        font-size: 12px;
        font-family: "Menlo", "Monaco";
    }
    QLabel#PathName {
        color: #475569;
        font-weight: 700;
        min-width: 86px;
    }
    QLineEdit#PathField {
        background: #f8fafc;
        color: #334155;
        border: 1px solid #d7e0ea;
        border-radius: 5px;
        padding: 5px 7px;
        font-family: "Menlo", "Monaco";
        font-size: 12px;
    }
    QLabel#AngleReadout {
        background: #eef6ff;
        color: #0f5f96;
        border: 1px solid #bfd7ee;
        border-radius: 4px;
        padding: 4px 8px;
        font-family: "Menlo", "Monaco";
        font-size: 13px;
        font-weight: 700;
    }
    QWidget#TelemetryTile {
        background: #f8fafc;
        border: 1px solid #d7e0ea;
        border-radius: 6px;
    }
    QLabel#TelemetryName {
        color: #64748b;
        font-weight: 700;
    }
    QLabel#TelemetryValue {
        color: #0f766e;
        font-family: "Menlo", "Monaco";
        font-size: 13px;
        font-weight: 800;
    }
    QRadioButton {
        spacing: 7px;
        padding: 5px 8px;
        color: #1f2933;
        font-weight: 600;
    }
    QRadioButton::indicator {
        width: 14px;
        height: 14px;
    }
    QRadioButton::indicator:unchecked {
        border: 1px solid #94a3b8;
        border-radius: 7px;
        background: #ffffff;
    }
    QRadioButton::indicator:checked {
        border: 4px solid #1769aa;
        border-radius: 7px;
        background: #ffffff;
    }
    QWidget#ButtonTray {
        background: #f8fafc;
        border: 1px solid #e1e7ef;
        border-radius: 6px;
    }
    QWidget#PageCard, QFrame#PageCard {
        background: #ffffff;
        border: 1px solid #d7e0ea;
        border-radius: 6px;
    }
    QSplitter#ContentSplitter::handle {
        background: #d9e2ec;
        width: 3px;
    }
    QSplitter#ContentSplitter::handle:hover {
        background: #9fb0c2;
    }
    QSplitter#RightInspectorSplitter::handle {
        background: #d9e2ec;
        height: 3px;
    }
    QSplitter#RightInspectorSplitter::handle:hover {
        background: #9fb0c2;
    }
    QGroupBox {
        border: 1px solid #d7e0ea;
        border-radius: 6px;
        margin-top: 12px;
        padding: 10px;
        background: #ffffff;
        font-weight: 700;
        color: #111827;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 14px;
        padding: 0 6px;
        background: #ffffff;
    }
    QStatusBar {
        background: #111827;
        border-top: 1px solid #253244;
        color: #f8fafc;
        font-weight: 600;
    }
    QLabel#FooterStatusText {
        background: transparent;
        color: #f8fafc;
        font-size: 13px;
        font-weight: 800;
        padding: 0 8px;
    }
    QLabel#FooterLightOk {
        background: #10b981;
        border-radius: 6px;
        min-width: 12px;
        min-height: 12px;
        max-width: 12px;
        max-height: 12px;
    }
    QLabel#FooterLightWarn {
        background: #3b82f6;
        border-radius: 6px;
        min-width: 12px;
        min-height: 12px;
        max-width: 12px;
        max-height: 12px;
    }
    QLabel#FooterLightError {
        background: #dc2626;
        border-radius: 6px;
        min-width: 12px;
        min-height: 12px;
        max-width: 12px;
        max-height: 12px;
    }
    QScrollBar:vertical {
        background: transparent;
        width: 10px;
        margin: 2px;
    }
    QScrollBar::handle:vertical {
        background: #aebdcc;
        border-radius: 5px;
        min-height: 28px;
    }
    QScrollBar::handle:vertical:hover {
        background: #8798aa;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0;
        border: none;
        background: none;
    }
    QScrollBar:horizontal {
        background: transparent;
        height: 10px;
        margin: 2px;
    }
    QScrollBar::handle:horizontal {
        background: #aebdcc;
        border-radius: 5px;
        min-width: 28px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #8798aa;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0;
        border: none;
        background: none;
    }
    """
