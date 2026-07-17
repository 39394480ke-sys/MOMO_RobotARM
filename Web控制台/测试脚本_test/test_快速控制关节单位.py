"""Web 快速控制按关节类型显示位置单位。"""

import json
from pathlib import Path
import subprocess
import unittest


WEB_ROOT = Path(__file__).resolve().parents[1]


class QuickControlJointUnitTest(unittest.TestCase):
    def test_j10_uses_mm_and_rotary_joints_use_degrees(self) -> None:
        app_path = WEB_ROOT / "frontend" / "app.js"
        script = f"""
const fs = require("fs");
const vm = require("vm");
const sandbox = {{ document: {{ addEventListener() {{}} }} }};
vm.createContext(sandbox);
vm.runInContext(fs.readFileSync({json.dumps(str(app_path))}, "utf8"), sandbox);
process.stdout.write(JSON.stringify({{
  j10: sandbox.formatJointReadout("j10", 12.5),
  j11: sandbox.formatJointReadout("j11", -8.25),
  missingJ10: sandbox.formatJointReadout("j10", undefined),
}}));
"""
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, check=False)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {"j10": "12.50 mm", "j11": "-8.25°", "missingJ10": "-- mm"})

    def test_frontend_asset_version_is_updated(self) -> None:
        index = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        self.assertIn('/static/app.js?v=20260716-continuous-follow-subject-lock', index)


if __name__ == "__main__":
    unittest.main()
