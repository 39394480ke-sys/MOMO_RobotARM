"""加载阶段六动作库，输出动作列表和摘要。"""

from __future__ import annotations

import json

from GUI测试路径_test_paths import GUI_ROOT as BASE_DIR

from GUI主程序_main import load_gui_config
from gui_app.控制器桥接_controller_bridge import ControllerBridge


bridge = ControllerBridge(load_gui_config(), BASE_DIR)
print(json.dumps(bridge.list_actions(), ensure_ascii=False, indent=2))
