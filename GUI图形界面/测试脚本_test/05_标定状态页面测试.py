"""加载阶段四标定文件，输出标定完整性。"""

from __future__ import annotations

import json

from GUI测试路径_test_paths import GUI_ROOT as BASE_DIR

from GUI主程序_main import load_gui_config
from gui_app.控制器桥接_controller_bridge import ControllerBridge


bridge = ControllerBridge(load_gui_config(), BASE_DIR)
print(json.dumps(bridge.get_calibration_status(), ensure_ascii=False, indent=2))
