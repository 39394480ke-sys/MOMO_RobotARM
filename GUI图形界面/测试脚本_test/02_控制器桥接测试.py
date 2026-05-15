"""ControllerBridge 基础测试，默认 dry-run。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[1]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from GUI主程序_main import load_gui_config
from gui_app.控制器桥接_controller_bridge import ControllerBridge


bridge = ControllerBridge(load_gui_config(), BASE_DIR)
print(json.dumps(bridge.set_mode("dry_run"), ensure_ascii=False, indent=2))
print(json.dumps(bridge.connect(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.get_state(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.home(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.stop(), ensure_ascii=False, indent=2))
print(json.dumps(bridge.disconnect(), ensure_ascii=False, indent=2))

