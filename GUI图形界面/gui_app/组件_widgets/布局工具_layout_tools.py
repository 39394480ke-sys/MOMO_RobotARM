"""GUI 布局创建小工具。"""

from __future__ import annotations

from PyQt5.QtWidgets import QFormLayout, QGridLayout, QHBoxLayout, QLayout, QVBoxLayout, QWidget


def _apply_layout_style(layout: QLayout, margins: tuple[int, int, int, int], spacing: int) -> None:
    layout.setContentsMargins(*margins)
    layout.setSpacing(int(spacing))


def make_vbox_layout(
    parent: QWidget | None = None,
    margins: tuple[int, int, int, int] = (12, 18, 12, 12),
    spacing: int = 8,
) -> QVBoxLayout:
    layout = QVBoxLayout(parent)
    _apply_layout_style(layout, margins, spacing)
    return layout


def make_hbox_layout(
    parent: QWidget | None = None,
    margins: tuple[int, int, int, int] = (0, 0, 0, 0),
    spacing: int = 8,
) -> QHBoxLayout:
    layout = QHBoxLayout(parent)
    _apply_layout_style(layout, margins, spacing)
    return layout


def make_form_layout(
    parent: QWidget | None = None,
    margins: tuple[int, int, int, int] = (12, 18, 12, 12),
    spacing: int = 8,
) -> QFormLayout:
    layout = QFormLayout(parent)
    _apply_layout_style(layout, margins, spacing)
    return layout


def make_grid_layout(
    parent: QWidget | None = None,
    margins: tuple[int, int, int, int] = (12, 18, 12, 12),
    spacing: int = 8,
) -> QGridLayout:
    layout = QGridLayout(parent)
    _apply_layout_style(layout, margins, spacing)
    return layout
