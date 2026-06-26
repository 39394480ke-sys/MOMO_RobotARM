"""GUI 命名列表小工具。"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from typing import Any

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QListWidget, QMessageBox, QWidget


def set_named_payloads(
    list_widget: QListWidget,
    items: Iterable[Mapping[str, Any]],
    payload_getter: Callable[[Mapping[str, Any]], Any],
) -> dict[str, Any]:
    """用 ``name`` 字段填充列表，并返回 ``name -> payload`` 映射。"""
    previous = current_text(list_widget)
    payloads: dict[str, Any] = {}
    for item in items:
        name = str(item.get("name", "")).strip()
        if name:
            payloads[name] = payload_getter(item)
    names = sorted(payloads.keys())
    blocked = list_widget.blockSignals(True)
    try:
        list_widget.clear()
        list_widget.addItems(names)
        if previous in payloads:
            matches = list_widget.findItems(previous, Qt.MatchExactly)
            if matches:
                list_widget.setCurrentItem(matches[0])
        elif names:
            list_widget.setCurrentRow(0)
    finally:
        list_widget.blockSignals(blocked)
    return payloads


def current_text(list_widget: QListWidget) -> str:
    item = list_widget.currentItem()
    return item.text() if item is not None else ""


def emit_selected_text(list_widget: QListWidget, signal: Any) -> None:
    text = current_text(list_widget)
    if text:
        signal.emit(text)


def confirm_delete_selected(parent: QWidget, list_widget: QListWidget, noun: str, signal: Any) -> None:
    text = current_text(list_widget)
    if not text:
        return
    reply = QMessageBox.question(
        parent,
        f"确认删除{noun}",
        f"确定删除{noun}“{text}”？",
        QMessageBox.Yes | QMessageBox.No,
        QMessageBox.No,
    )
    if reply == QMessageBox.Yes:
        signal.emit(text)
