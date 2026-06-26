"""阶段七 GUI 主程序。"""

from __future__ import annotations

import sys

from gui_app.path_utils import GUI_ROOT as BASE_DIR, ensure_project_root_on_path

ensure_project_root_on_path()


def load_gui_config() -> dict:
    from 通用_io import read_config

    return read_config(BASE_DIR / "GUI配置.yaml")


def main() -> int:
    try:
        from PyQt5.QtWidgets import QApplication
    except Exception as exc:
        print(f"PyQt5 未安装，无法启动 GUI：{exc}")
        print("请在 momo_rebot 环境安装：mamba install -n momo_rebot pyqt")
        print("如果 mamba 没找到包，可用：mamba run -n momo_rebot python -m pip install PyQt5")
        return 1

    from gui_app.主题_theme import build_stylesheet
    from gui_app.主窗口_main_window import MainWindow
    from gui_app.控制器桥接_controller_bridge import ControllerBridge

    config = load_gui_config()
    app = QApplication(sys.argv)
    app.setStyleSheet(build_stylesheet())
    bridge = ControllerBridge(config, BASE_DIR)
    bridge.set_mode(str(config.get("app", {}).get("default_mode", "dry_run")))
    window = MainWindow(bridge, config)
    window.show()
    return app.exec_()


if __name__ == "__main__":
    raise SystemExit(main())
