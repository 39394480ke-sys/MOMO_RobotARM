"""阶段七主窗口。"""

from __future__ import annotations

import json
from typing import Callable

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import QApplication, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QMainWindow, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout, QWidget

from gui_app.后台任务_worker import ActionPlayWorker, CalibrationStatusWorker, ConnectWorker, MoveWorker, StatePollWorker
from gui_app.状态_store import AppStore
from gui_app.组件_widgets.仿真视图_sim_view import SimView
from gui_app.组件_widgets.状态栏_status_bar import GlobalStatusBar
from gui_app.页面_pages.动作页面_action_page import ActionPage
from gui_app.页面_pages.姿态页面_pose_page import PosePage
from gui_app.页面_pages.快速控制页面_quick_control_page import QuickControlPage
from gui_app.页面_pages.日志页面_log_page import LogPage
from gui_app.页面_pages.标定页面_calibration_page import CalibrationPage
from gui_app.页面_pages.设置页面_settings_page import SettingsPage
from gui_app.页面_pages.视觉跟随页面_vision_follow_page import VisionFollowPage
from gui_app.页面_pages.运动学页面_kinematics_page import KinematicsPage


class MainWindow(QMainWindow):
    motion_progress_received = pyqtSignal(dict)

    def __init__(self, bridge, config: dict, parent=None):
        super().__init__(parent)
        self.bridge = bridge
        self.config = config
        self.store = AppStore()
        self.workers = []
        self.polling = False
        self.motion_busy = False
        self.motion_queue: list[tuple[Callable[[], dict], str, Callable[[dict], None] | None, Callable[[], None] | None]] = []
        self.pending_kinematic_targets: dict | None = None
        self.continuous_move_busy = False
        self.ui_state = self._load_ui_state()

        self.setWindowTitle(str(config.get("app", {}).get("title", "我的机械臂 GUI 控制台")))
        self._apply_initial_window_geometry()
        self._build_ui()
        self._connect_signals()
        self.motion_progress_received.connect(self._motion_progress_received)
        self.bridge.set_motion_update_callback(lambda payload: self.motion_progress_received.emit(payload))
        self._apply_saved_ui_state()
        self._setup_timer()
        self._refresh_all_lists()
        self.update_header()

    def _apply_initial_window_geometry(self) -> None:
        saved_geometry = self.ui_state.get("geometry")
        if isinstance(saved_geometry, list) and len(saved_geometry) == 4:
            try:
                x, y, width, height = [int(value) for value in saved_geometry]
                self.setMinimumSize(760, 480)
                self.setGeometry(x, y, max(760, width), max(480, height))
                return
            except Exception:
                pass
        screen = QApplication.primaryScreen()
        if screen is None:
            self.resize(1180, 760)
            self.setMinimumSize(760, 480)
            return

        available = screen.availableGeometry()
        width = min(1280, max(900, int(available.width() * 0.86)))
        height = min(820, max(600, int(available.height() * 0.82)))
        width = min(width, available.width() - 40)
        height = min(height, available.height() - 40)
        x = available.x() + max(20, (available.width() - width) // 2)
        y = available.y() + max(20, (available.height() - height) // 2)

        self.setMinimumSize(min(760, width), min(480, height))
        self.setGeometry(x, y, width, height)

    def _build_ui(self) -> None:
        root = QWidget()
        root_layout = QVBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        top = QFrame()
        top.setObjectName("TopBar")
        top_layout = QHBoxLayout(top)
        top_layout.setContentsMargins(12, 8, 12, 8)
        top_layout.setSpacing(8)
        self.title_label = QLabel("机械臂 GUI 控制台")
        self.title_label.setObjectName("TitleLabel")
        self.mode_label = QLabel("● 模式: dry-run")
        self.mode_label.setObjectName("StatusPill")
        self.conn_label = QLabel("● 链路: 未连接")
        self.conn_label.setObjectName("StatusPill")
        self.error_label = QLabel("SYSTEM READY")
        self.error_label.setObjectName("ReadyPill")
        self.speed_label = QLabel("速度")
        self.speed_label.setObjectName("SpeedLabel")
        self.speed_spin = QSpinBox()
        self.speed_spin.setRange(10, 100)
        self.speed_spin.setSingleStep(5)
        self.speed_spin.setValue(int(float(self.ui_state.get("speed_percent", self.config.get("motion", {}).get("default_speed_percent", 50)))))
        self.speed_spin.setSuffix("%")
        self.speed_spin.setMinimumWidth(92)
        self.speed_spin.setMinimumHeight(30)
        self.bridge.set_motion_speed_percent(self.speed_spin.value())
        self.home_button = QPushButton("Home 回零")
        self.home_button.setObjectName("PrimaryButton")
        self.release_torque_button = QPushButton("释放力矩")
        self.release_torque_button.setObjectName("WarningButton")
        self.stop_button = QPushButton("EMERGENCY STOP")
        self.stop_button.setObjectName("DangerButton")
        top_layout.addWidget(self.title_label)
        top_layout.addStretch(1)
        top_layout.addWidget(self.mode_label)
        top_layout.addWidget(self.conn_label)
        top_layout.addWidget(self.error_label)
        top_layout.addWidget(self.speed_label)
        top_layout.addWidget(self.speed_spin)
        top_layout.addWidget(self.home_button)
        top_layout.addWidget(self.release_torque_button)
        top_layout.addWidget(self.stop_button)

        body = QWidget()
        body.setObjectName("MainBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(0)
        self.nav = QListWidget()
        self.nav.setObjectName("NavList")
        self.nav.setFixedWidth(150)
        self.stack = QStackedWidget()
        self.stack.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.stack.setMinimumWidth(280)

        self.settings_page = SettingsPage(self.bridge)
        self.quick_page = QuickControlPage()
        self.pose_page = PosePage()
        self.action_page = ActionPage()
        self.kinematics_page = KinematicsPage()
        self.calibration_page = CalibrationPage()
        self.vision_follow_page = VisionFollowPage(self.bridge.project_root)
        self.log_page = LogPage(self.bridge.log_path)
        self.log_page.setObjectName("PersistentLogPanel")
        self.log_page.setMinimumWidth(260)
        self.persistent_sim_view = SimView()
        self.persistent_sim_view.setObjectName("PersistentSimView")
        self.persistent_sim_view.setMinimumHeight(240)

        pages = [
            ("⚙ 设置", self.settings_page, (560, 380)),
            ("🕹 快速控制", self.quick_page, (620, 580)),
            ("🔖 姿态", self.pose_page, (600, 420)),
            ("▶ 动作", self.action_page, (600, 420)),
            ("📐 运动学", self.kinematics_page, (620, 520)),
            ("🎯 标定", self.calibration_page, (620, 500)),
            ("👁 视觉跟随", self.vision_follow_page, (860, 620)),
        ]
        for title, page, minimum_size in pages:
            self.nav.addItem(QListWidgetItem(title))
            self.stack.addWidget(self._make_scroll_page(page, minimum_size[0], minimum_size[1]))
        self.nav.setCurrentRow(int(self.ui_state.get("nav_index", 0)))

        self.content_splitter = QSplitter()
        self.content_splitter.setObjectName("ContentSplitter")
        self.content_splitter.setOpaqueResize(False)
        self.content_splitter.setHandleWidth(6)
        self.content_splitter.addWidget(self.stack)
        self.right_splitter = QSplitter()
        self.right_splitter.setOrientation(Qt.Vertical)
        self.right_splitter.setObjectName("RightInspectorSplitter")
        self.right_splitter.setMinimumWidth(280)
        self.right_splitter.setOpaqueResize(False)
        self.right_splitter.setHandleWidth(6)
        self.right_splitter.addWidget(self.log_page)
        self.right_splitter.addWidget(self.persistent_sim_view)
        self.right_splitter.setStretchFactor(0, 2)
        self.right_splitter.setStretchFactor(1, 3)
        self.right_splitter.setSizes(self.ui_state.get("right_splitter_sizes", [300, 460]))
        self.right_splitter.setChildrenCollapsible(False)
        self.content_splitter.addWidget(self.right_splitter)
        self.content_splitter.setStretchFactor(0, 4)
        self.content_splitter.setStretchFactor(1, 2)
        self.content_splitter.setSizes(self.ui_state.get("content_splitter_sizes", [1040, 520]))
        self.content_splitter.setChildrenCollapsible(False)

        body_layout.addWidget(self.nav)
        body_layout.addWidget(self.content_splitter, 1)
        root_layout.addWidget(top)
        root_layout.addWidget(body, 1)
        self.setCentralWidget(root)

        self.status_bar = GlobalStatusBar()
        self.setStatusBar(self.status_bar)

    def _make_scroll_page(self, page: QWidget, minimum_width: int, minimum_height: int) -> QScrollArea:
        page.setMinimumSize(minimum_width, minimum_height)
        page.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        scroll = QScrollArea()
        scroll.setObjectName("PageScrollArea")
        scroll.setWidget(page)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        return scroll

    def _ui_state_path(self):
        return self.bridge.base_dir / "运行日志" / "gui_ui_state.json"

    def _load_ui_state(self) -> dict:
        path = self.config.get("app", {}).get("ui_state_path")
        state_path = self.bridge._resolve_gui_path(path) if path else self.bridge.base_dir / "运行日志" / "gui_ui_state.json"
        try:
            data = json.loads(state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _apply_saved_ui_state(self) -> None:
        port = self.ui_state.get("serial_port")
        if port:
            self.settings_page.port_input.setText(str(port))
        mode = self.ui_state.get("mode")
        if mode in {"simulation", "dry_run", "real"}:
            self.settings_page.set_mode(str(mode))
            self.bridge.set_mode(str(mode))
            self.quick_page.set_real_mode(mode == "real", float(self.config.get("safety", {}).get("max_real_step_deg", 2.0)))

    def _save_ui_state(self) -> None:
        payload = {
            "mode": self.bridge.get_mode(),
            "serial_port": self.settings_page.port_input.text(),
            "speed_percent": self.speed_spin.value(),
            "nav_index": self.nav.currentRow(),
            "geometry": [self.x(), self.y(), self.width(), self.height()],
            "content_splitter_sizes": self.content_splitter.sizes(),
            "right_splitter_sizes": self.right_splitter.sizes(),
        }
        path = self._ui_state_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def closeEvent(self, event) -> None:
        self._save_ui_state()
        super().closeEvent(event)

    def _connect_signals(self) -> None:
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)
        self.speed_spin.valueChanged.connect(lambda value: self._handle_result(self.bridge.set_motion_speed_percent(value)))
        self.home_button.clicked.connect(lambda: self._run_move(self.bridge.home))
        self.release_torque_button.clicked.connect(self._release_torque)
        self.stop_button.clicked.connect(self._stop_now)

        self.settings_page.mode_change_requested.connect(self._set_mode)
        self.settings_page.connect_requested.connect(self._connect_controller)
        self.settings_page.disconnect_requested.connect(self._disconnect_controller)
        self.settings_page.refresh_requested.connect(self._poll_state_once)
        self.settings_page.dependency_check_requested.connect(lambda: self._handle_result(self.bridge.check_dependencies()))
        self.settings_page.calibration_check_requested.connect(self._refresh_calibration)

        self.quick_page.joint_delta_requested.connect(lambda joint, delta: self._run_move(lambda: self.bridge.move_joint_delta(joint, delta)))
        self.quick_page.continuous_delta_requested.connect(self._run_continuous_move)
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
        self.action_page.record_start_requested.connect(self._start_action_recording)
        self.action_page.teach_start_requested.connect(self._start_teach_recording)
        self.action_page.capture_pose_requested.connect(self._capture_action_recording_pose)
        self.action_page.save_recording_requested.connect(self._save_action_recording)
        self.action_page.cancel_recording_requested.connect(self._cancel_action_recording)

        self.kinematics_page.fk_requested.connect(self._compute_fk)
        self.kinematics_page.ik_requested.connect(self._compute_ik)
        self.kinematics_page.delta_requested.connect(self._compute_delta)
        self.kinematics_page.refresh_tcp_requested.connect(lambda: self.kinematics_page.show_result(self.bridge.get_tcp_pose()))
        self.kinematics_page.execute_result_requested.connect(self._execute_kinematic_result)

        self.calibration_page.refresh_requested.connect(self._refresh_calibration)
        self.vision_follow_page.follow_commands_requested.connect(self._run_vision_follow_commands)

    def _setup_timer(self) -> None:
        self.timer = QTimer(self)
        self.timer.setInterval(int(self.config.get("app", {}).get("refresh_interval_ms", 200)))
        self.timer.timeout.connect(self._poll_state_once)
        self.timer.start()

    def _set_mode(self, mode: str) -> None:
        result = self.bridge.set_mode(mode)
        if not result.get("ok"):
            self.settings_page.set_mode(self.bridge.get_mode())
        self.quick_page.set_real_mode(mode == "real", float(self.config.get("safety", {}).get("max_real_step_deg", 2.0)))
        self._handle_result(result)

    def _connect_controller(self) -> None:
        self.bridge.set_serial_port(self.settings_page.port_input.text())
        self._run_worker(ConnectWorker(self.bridge.connect), disable=[self.settings_page.connect_button])

    def _disconnect_controller(self) -> None:
        self._handle_result(self.bridge.disconnect())
        self.update_header()

    def _run_move(self, task: Callable[[], dict]) -> None:
        self._run_dangerous(task, "真实模式移动")

    def _run_continuous_move(self, joint: str, delta: float) -> None:
        if self.continuous_move_busy:
            return
        self.continuous_move_busy = True
        self._run_dangerous(
            lambda: self.bridge.move_joint_delta(joint, delta),
            "真实模式连续移动",
            on_finished=lambda: setattr(self, "continuous_move_busy", False),
            queue_if_busy=False,
        )

    def _run_vision_follow_commands(self, commands: list) -> None:
        if not commands:
            self.vision_follow_page.set_follow_result({"ok": True, "message": "无视觉跟随命令。"})
            return
        if self.vision_follow_page.is_real_execute_enabled() and (self.bridge.get_mode() != "real" or not self.bridge.is_connected()):
            self.vision_follow_page.set_follow_result({"ok": False, "message": "真实视觉跟随需要先在设置页连接真实模式。", "data": {"commands": commands}})
            return
        if self.motion_busy:
            self.vision_follow_page.set_follow_result({"ok": False, "message": "上一条运动尚未完成，本次视觉跟随命令已跳过。", "data": {"commands": commands}})
            return
        task = lambda: self.bridge.move_follow_steps(commands) if self.vision_follow_page.is_real_execute_enabled() else {"ok": True, "message": "视觉跟随 dry-run。", "data": {"commands": commands}}
        self._run_dangerous(task, "视觉跟随步进", on_result=self.vision_follow_page.set_follow_result, queue_if_busy=False)

    def _run_dangerous(
        self,
        task: Callable[[], dict],
        title: str,
        on_result: Callable[[dict], None] | None = None,
        on_finished: Callable[[], None] | None = None,
        queue_if_busy: bool = True,
    ) -> None:
        if self.motion_busy:
            if on_finished is not None:
                on_finished()
            if queue_if_busy and len(self.motion_queue) < 10:
                self.motion_queue.append((task, title, on_result, None))
                self._handle_result({"ok": True, "message": f"运动命令已排队：{title}", "data": {"queue_size": len(self.motion_queue)}})
            elif queue_if_busy:
                self._handle_result({"ok": False, "message": "运动队列已满，请稍后再试。"})
            return
        self._run_worker(MoveWorker(task), on_result=on_result, on_finished=on_finished)

    def _run_action(self, name: str) -> None:
        self._run_worker(ActionPlayWorker(self.bridge.play_action, name), disable=[self.action_page.play_button, self.action_page.delete_button])

    def _start_action_recording(self, name: str) -> None:
        self._handle_result(self.bridge.start_action_recording(name))

    def _start_teach_recording(self, name: str) -> None:
        self._run_worker(MoveWorker(lambda: self.bridge.start_teach_recording(name)))

    def _capture_action_recording_pose(self) -> None:
        self._run_worker(MoveWorker(self.bridge.capture_recording_pose), disable=[self.action_page.capture_button])

    def _save_action_recording(self) -> None:
        self._handle_result_and_refresh(self.bridge.save_recording_action(), self._refresh_actions)

    def _cancel_action_recording(self) -> None:
        self._handle_result(self.bridge.cancel_recording_action())

    def _refresh_calibration(self) -> None:
        self._run_worker(CalibrationStatusWorker(self.bridge.get_calibration_status))

    def _poll_state_once(self) -> None:
        if self.polling or self.motion_busy:
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
        self.persistent_sim_view.update_state(data.get("joints_deg", {}), data.get("tcp_pose"))
        self.update_header()

    def _state_error(self, result: dict) -> None:
        self.store.update_from_result(result)
        self.update_header()

    def _motion_progress_received(self, payload: dict) -> None:
        targets = payload.get("targets_deg", {})
        if not isinstance(targets, dict):
            return
        self.quick_page.update_state({"joints_deg": targets})
        self.persistent_sim_view.update_state(targets)

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

    def _release_torque(self) -> None:
        self._run_dangerous(self.bridge.release_torque, "真实模式释放力矩")

    def _compute_fk(self, joints: list) -> None:
        result = self.bridge.compute_fk(joints)
        self.kinematics_page.show_result(result)
        if result.get("ok"):
            self._set_pending_kinematic_result(result, result.get("data", {}).get("tcp_pose"), "FK 目标")

    def _compute_ik(self, xyz: list, rpy: object) -> None:
        result = self.bridge.compute_ik(xyz, rpy)
        self.kinematics_page.show_result(result)
        if result.get("ok"):
            ik = result.get("data", {}).get("ik", {})
            self._set_pending_kinematic_result(result, {"xyz": ik.get("xyz"), "rpy": ik.get("rpy")}, "IK 目标")

    def _compute_delta(self, dx: float, dy: float, dz: float, frame: str) -> None:
        result = self.bridge.compute_delta(dx, dy, dz, frame)
        self.kinematics_page.show_result(result)
        if result.get("ok"):
            self._set_pending_kinematic_result(result, result.get("data", {}).get("target_tcp_pose"), "增量目标")

    def _set_pending_kinematic_result(self, result: dict, target_pose: dict | None, label: str) -> None:
        targets = result.get("data", {}).get("target_joints_deg")
        if targets:
            self.pending_kinematic_targets = targets
            self.kinematics_page.set_execute_available(True)
        if target_pose:
            self.persistent_sim_view.set_target_pose(target_pose, label)

    def _execute_kinematic_result(self) -> None:
        if not self.pending_kinematic_targets:
            self.kinematics_page.show_result({"ok": False, "message": "没有可执行的计算结果。请先计算 FK、IK 或末端增量。"})
            return
        self.kinematics_page.show_result({"ok": True, "message": "正在执行最后一次计算结果..."})
        self._run_dangerous(
            lambda: self.bridge.move_joints_smooth(self.pending_kinematic_targets or {}, label="执行运动学结果"),
            "真实模式执行运动学结果",
            on_result=self._kinematic_execution_finished,
        )

    def _kinematic_execution_finished(self, result: dict) -> None:
        self.kinematics_page.show_result(result)
        if result.get("ok"):
            self.pending_kinematic_targets = None
            self.kinematics_page.set_execute_available(False)
            self.persistent_sim_view.set_target_pose(None)
            self._poll_state_once()

    def _run_worker(
        self,
        worker,
        disable: list[QPushButton] | None = None,
        on_result: Callable[[dict], None] | None = None,
        on_finished: Callable[[], None] | None = None,
    ) -> None:
        disabled = disable or []
        is_move_worker = isinstance(worker, (MoveWorker, ActionPlayWorker))
        if is_move_worker:
            self.motion_busy = True
        for button in disabled:
            button.setEnabled(False)
        worker.finished_result.connect(self._handle_result)
        worker.error_result.connect(self._handle_result)
        if on_result is not None:
            worker.finished_result.connect(on_result)
            worker.error_result.connect(on_result)
        worker.finished.connect(lambda: [button.setEnabled(True) for button in disabled])
        if on_finished is not None:
            worker.finished.connect(on_finished)
        if is_move_worker:
            worker.finished.connect(self._motion_worker_finished)
        worker.finished.connect(self.update_header)
        self.workers.append(worker)
        worker.start()

    def _motion_worker_finished(self) -> None:
        self.motion_busy = False
        QTimer.singleShot(80, self._poll_state_once)
        if not self.motion_queue:
            return
        task, title, on_result, on_finished = self.motion_queue.pop(0)
        QTimer.singleShot(30, lambda: self._run_dangerous(task, title, on_result=on_result, on_finished=on_finished, queue_if_busy=False))

    def _handle_result_and_refresh(self, result: dict, refresh: Callable[[], None]) -> None:
        self._handle_result(result)
        refresh()

    def _handle_result(self, result: dict) -> None:
        self.store.update_from_result(result)
        self.settings_page.show_result(result)
        self.log_page.append_result(result)
        targets = result.get("data", {}).get("targets_deg")
        if isinstance(targets, dict):
            self.quick_page.update_state({"joints_deg": targets})
            self.persistent_sim_view.update_state(targets)
        if result.get("data", {}).get("calibration"):
            self.calibration_page.set_status(result["data"])
            self.store.gui_state.calibration_ok = bool(result["data"]["calibration"].get("允许真机移动"))
        recording = result.get("data", {}).get("recording")
        if isinstance(recording, dict):
            self.action_page.set_recording_status(recording)
        self.log_page.refresh()
        self.update_header()

    def update_header(self) -> None:
        state = self.store.gui_state
        mode = self.bridge.get_mode()
        state.mode = mode
        state.connected = self.bridge.is_connected()
        state.action_status = self.bridge.action_status
        mode_text = {"simulation": "仿真", "dry_run": "dry-run", "real": "真实"}.get(mode, mode)
        mode_dot = {"simulation": "●", "dry_run": "●", "real": "●"}.get(mode, "●")
        self.mode_label.setText(f"{mode_dot} 模式: {mode_text}")
        self.conn_label.setText(f"● 链路: {'已连接' if state.connected else '未连接'}")
        self.error_label.setText(f"错误: {state.last_error}" if state.last_error else "SYSTEM READY")
        self.error_label.setObjectName("ErrorPill" if state.last_error else "ReadyPill")
        self.error_label.style().unpolish(self.error_label)
        self.error_label.style().polish(self.error_label)
        self.status_bar.update_status(mode, state.connected, state.calibration_ok, state.action_status, state.last_error)
