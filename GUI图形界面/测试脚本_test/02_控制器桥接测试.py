"""ControllerBridge 基础测试，默认 dry-run。"""

from __future__ import annotations

import json

from GUI测试路径_test_paths import GUI_ROOT as BASE_DIR

from GUI主程序_main import load_gui_config
from gui_app.控制器桥接_controller_bridge import ControllerBridge


bridge = ControllerBridge(load_gui_config(), BASE_DIR)
print(json.dumps(bridge.set_mode("dry_run"), ensure_ascii=False, indent=2))
print(json.dumps(bridge.connect(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.get_state(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.home(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.stop(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.disconnect(), ensure_ascii=False, indent=2))
