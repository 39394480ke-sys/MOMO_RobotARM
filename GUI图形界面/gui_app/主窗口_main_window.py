"""阶段七主窗口。"""

from __future__ import annotations

from typing import Callable

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from gui_app.后台任务_worker import ActionPlayWorker, CalibrationStatusWorker, ConnectWorker, MoveWorker, StatePollWorker
from gui_app.状态_store import AppStore
from gui_app.组件_widgets.安全确认对话框_safety_dialog import ask_safety_confirm
from gui_app.组件_widgets.状态栏_status_bar import GlobalStatusBar
from gui_app.页面_pages.动作页面_action_page import ActionPage
from gui_app.页面_pages.姿态页面_pose_page import PosePage
from gui_app.页面_pages.快速控制页面_quick_control_page import QuickControlPage
from gui_app.页面_pages.日志页面_log_page import LogPage
from gui_app.页面_pages.标定页面_calibration_page import CalibrationPage
from gui_app.页面_pages.设置页面_settings_page import SettingsPage
from gui_app.页面_pages.运动学页面_kinematics_page import KinematicsPage


class MainWindow(QMainWindow):
    def __init__(self, bridge, config: dict, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.config = config
        self.store = AppStore()
        self.workers = []
        self.polling = False

        self.setWindowTitle(str(config.get("app", {}).get("title", "我的 MomoAgent GUI 控制台")))
        self.resize(1180, 760)
        self._build_ui()
        self._connect_signals()
        self._setup_timer()
        self._refresh_all_lists()
        self.update_header()

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)

        top = QFrame()
        top.setObjectName("TopBar")
        top_layout = QHBoxLayout(top)
        self.title_label = QLabel(str(self.config.get("app", {}).get("title", "我的 MomoAgent GUI 控制台")))
        self.title_label.setObjectName("TitleLabel")
        self.mode_label = QLabel("模式：dry-run")
        self.conn_label = QLabel("连接：未连接")
        self.error_label = QLabel("")
        self.stop_button = QPushButton("急停")
        self.stop_button.setObjectName("DangerButton")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_label)
        top_layout.addWidget(self.conn_label)
        top_layout.addWidget(self.error_label)
        top_layout.addWidget(self.stop_button)

        body = QWidget()
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setFixedWidth(150)
        self.stack = QStackedWidget()

        self.settings_page = SettingsPage(self.bridge)
        self.quick_page = QuickControlPage()
        self.pose_page = PosePage()
        self.action_page = ActionPage()
        self.kinematics_page = KinematicsPage()
        self.calibration_page = CalibrationPage()
        self.log_page = LogPage(self.bridge.log_path)

        pages = [
            ("设置", self.settings_page),
            ("快速控制", self.quick_page),
            ("姿态", self.pose_page),
            ("动作", self.action_page),
            ("运动学", self.kinematics_page),
            ("标定", self.calibration_page),
            ("日志", self.log_page),
        ]
        for title, page in pages:
            self.nav.addItem(QListWidgetItem(title))
            self.stack.addWidget(page)
        self.nav.setCurrentRow(0)

        body_layout.addWidget(self.nav)
        body_layout.addWidget(self.stack, 1)
        root_layout.addWidget(top)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)

        self.status_bar = GlobalStatusBar()
        self.setStatusBar(self.status_bar)

    def _connect_signals(self) -> None:
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.stop_button.clicked.connect(self._stop_now)

        self.settings_page.mode_change_requested.connect(self._set_mode)
        self.settings_page.connect_requested.connect(self._connect_controller)
        self.settings_page.disconnect_requested.connect(self._disconnect_controller)
        self.settings_page.refresh_requested.connect(self._poll_state_once)
        self.settings_page.dependency_check_requested.connect(lambda: self._handle_result(self.bridge.check_dependencies()))
        self.settings_page.calibration_check_requested.connect(self._refresh_calibration)

        self.quick_page.joint_delta_requested.connect(lambda joint, delta: self._run_move(lambda: self.bridge.move_joint_delta(joint, delta)))
        self.quick_page.gripper_requested.connect(lambda value: self._run_move(lambda: self.bridge.set_gripper(value)))
        self.quick_page.home_requested.connect(lambda: self._run_move(self.bridge.home))
        self.quick_page.stop_requested.connect(self._stop_now)
        self.quick_page.refresh_requested.connect(self._poll_state_once)

        self.pose_page.refresh_requested.connect(self._refresh_poses)
        self.pose_page.save_requested.connect(lambda name: self._handle_result_and_refresh(self.bridge.save_pose(name), self._refresh_poses))
        self.pose_page.goto_requested.connect(lambda name: self._run_dangerous(lambda: self.bridge.goto_pose(name), "真实模式前往姿态"))
        self.pose_page.delete_requested.connect(lambda name: self._handle_result_and_refresh(self.bridge.delete_pose(name), self._refresh_poses))

        self.action_page.refresh_requested.connect(self._refresh_actions)
        self.action_page.play_requested.connect(lambda name: self._run_action(name))
        self.action_page.pause_requested.connect(lambda: self._handle_result(self.bridge.pause_action()))
        self.action_page.resume_requested.connect(lambda: self._handle_result(self.bridge.resume_action()))
        self.action_page.stop_requested.connect(lambda: self._handle_result(self.bridge.stop_action()))
        self.action_page.delete_requested.connect(lambda name: self._handle_result_and_refresh(self.bridge.delete_action(name), self._refresh_actions))

        self.kinematics_page.fk_requested.connect(lambda joints: self.kinematics_page.show_result(self.bridge.compute_fk(joints)))
        self.kinematics_page.ik_requested.connect(lambda xyz, rpy: self.kinematics_page.show_result(self.bridge.compute_ik(xyz, rpy)))
        self.kinematics_page.execute_ik_requested.connect(lambda targets: self._run_dangerous(lambda: self.bridge.move_joints(targets), "真实模式执行 IK"))
        self.kinematics_page.delta_requested.connect(lambda dx, dy, dz, frame: self._run_dangerous(lambda: self.bridge.move_delta(dx, dy, dz, frame), "真实模式末端移动"))
        self.kinematics_page.refresh_tcp_requested.connect(lambda: self.kinematics_page.show_result(self.bridge.get_tcp_pose()))

        self.calibration_page.refresh_requested.connect(self._refresh_calibration)

    def _setup_timer(self) -> None:
        self.timer = QTimer(self)
        self.timer.setInterval(int(self.config.get("app", {}).get("refresh_interval_ms", 200)))
        self.timer.timeout.connect(self._poll_state_once)
        self.timer.start()

    def _set_mode(self, mode: str) -> None:
        if mode == "real" and self.config.get("safety", {}).get("real_mode_requires_confirm", True):
            if not ask_safety_confirm(self, self._confirm_text(), "切换真实模式"):
                self.settings_page.set_mode(self.bridge.get_mode())
                return
        result = self.bridge.set_mode(mode)
        if not result.get("ok"):
            self.settings_page.set_mode(self.bridge.get_mode())
        self.quick_page.set_real_mode(mode == "real", float(self.config.get("safety", {}).get("max_real_step_deg", 2.0)))
        self._handle_result(result)

    def _connect_controller(self) -> None:
        self.bridge.set_serial_port(self.settings_page.port_input.text())
        if self.bridge.get_mode() == "real" and not ask_safety_confirm(self, self._confirm_text(), "连接真实硬件"):
            return
        self._run_worker(ConnectWorker(self.bridge.connect), disable=[self.settings_page.connect_button])

    def _disconnect_controller(self) -> None:
        self._handle_result(self.bridge.disconnect())
        self.update_header()

    def _run_move(self, task: Callable[[], dict]) -> None:
        self._run_dangerous(task, "真实模式移动")

    def _run_dangerous(self, task: Callable[[], dict], title: str) -> None:
        if self.bridge.get_mode() == "real" and not ask_safety_confirm(self, self._confirm_text(), title):
            return
        self._run_worker(MoveWorker(task))

    def _run_action(self, name: str) -> None:
        if self.bridge.get_mode() == "real" and not ask_safety_confirm(self, self._confirm_text(), "真实模式播放动作"):
            return
        self._run_worker(ActionPlayWorker(self.bridge.play_action, name), disable=[self.action_page.play_button, self.action_page.delete_button])

    def _refresh_calibration(self) -> None:
        self._run_worker(CalibrationStatusWorker(self.bridge.get_calibration_status))

    def _poll_state_once(self) -> None:
        if self.polling:
            return
        self.polling = True
        worker = StatePollWorker(self.bridge.get_state)
        worker.finished_result.connect(self._state_received)
        worker.error_result.connect(self._state_error)
        worker.finished.connect(lambda: setattr(self, "polling", False))
        self.workers.append(worker)
        worker.start()

    def _state_received(self, result: dict) -> None:
        data = result.get("data", {})
        self.store.set_state_payload(data)
        self.quick_page.update_state(data)
        self.update_header()

    def _state_error(self, result: dict) -> None:
        self.store.update_from_result(result)
        self.update_header()

    def _refresh_poses(self) -> None:
        result = self.bridge.list_poses()
        if result.get("ok"):
            self.pose_page.set_poses(result.get("data", {}).get("poses", []))
        self._handle_result(result)

    def _refresh_actions(self) -> None:
        result = self.bridge.list_actions()
        if result.get("ok"):
            self.action_page.set_actions(result.get("data", {}).get("actions", []))
        self._handle_result(result)

    def _refresh_all_lists(self) -> None:
        self._refresh_poses()
        self._refresh_actions()
        self._refresh_calibration()

    def _stop_now(self) -> None:
        self._handle_result(self.bridge.stop())

    def _run_worker(self, worker, disable: list[QPushButton] | None = None) -> None:
        disabled = disable or []
        for button in disabled:
            button.setEnabled(False)
        worker.finished_result.connect(self._handle_result)
        worker.error_result.connect(self._handle_result)
        worker.finished.connect(lambda: [button.setEnabled(True) for button in disabled])
        worker.finished.connect(self.update_header)
        self.workers.append(worker)
        worker.start()

    def _handle_result_and_refresh(self, result: dict, refresh: Callable[[], None]) -> None:
        self._handle_result(result)
        refresh()

    def _handle_result(self, result: dict) -> None:
        self.store.update_from_result(result)
        self.settings_page.show_result(result)
        self.log_page.append_result(result)
        if result.get("data", {}).get("calibration"):
            self.calibration_page.set_status(result["data"])
            self.store.gui_state.calibration_ok = bool(result["data"]["calibration"].get("允许真机移动"))
        self.log_page.refresh()
        self.update_header()

    def update_header(self) -> None:
        state = self.store.gui_state
        mode = self.bridge.get_mode()
        state.mode = mode
        state.connected = self.bridge.is_connected()
        state.action_status = self.bridge.action_status
        mode_text = {"simulation": "仿真", "dry_run": "dry-run", "real": "真实"}.get(mode, mode)
        self.mode_label.setText(f"模式：{mode_text}")
        self.conn_label.setText(f"连接：{'已连接' if state.connected else '未连接'}")
        self.error_label.setText(f"错误：{state.last_error}" if state.last_error else "")
        self.status_bar.update_status(mode, state.connected, state.calibration_ok, state.action_status, state.last_error)

    def _confirm_text(self) -> str:
        return str(self.config.get("safety", {}).get("real_move_confirm_text", "我确认机械臂周围安全"))
