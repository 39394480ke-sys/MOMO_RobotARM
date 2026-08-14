"""动作库与姿态库改名功能。"""

from pathlib import Path
from tempfile import TemporaryDirectory
import json
import sys
import unittest

import Web测试路径_test_paths  # noqa: F401

PROJECT_ROOT = Path(__file__).resolve().parents[2]
for module_dir in (
    PROJECT_ROOT / "动作录制与回放增强",
    PROJECT_ROOT / "仿真控制系统",
    PROJECT_ROOT / "仿真控制系统" / "姿态管理",
):
    if str(module_dir) not in sys.path:
        sys.path.insert(0, str(module_dir))

from backend.schemas import RenameLibraryItemRequest
from 动作文件管理_action_library import ActionLibrary
from 姿态管理_pose_manager import 姿态管理器


WEB_ROOT = Path(__file__).resolve().parents[1]


class LibraryRenameTest(unittest.TestCase):
    def test_pose_rename_persists_and_rejects_collision(self) -> None:
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "poses.json"
            path.write_text(json.dumps({"旧姿态": {"关节角度": [0] * 6}, "已有姿态": {"关节角度": [1] * 6}}), encoding="utf-8")
            manager = 姿态管理器(path)

            self.assertTrue(manager.重命名姿态("旧姿态", "新姿态"))
            self.assertIsNone(manager.获取姿态("旧姿态"))
            self.assertIsNotNone(manager.获取姿态("新姿态"))
            self.assertIn("新姿态", json.loads(path.read_text(encoding="utf-8")))
            with self.assertRaises(FileExistsError):
                manager.重命名姿态("新姿态", "已有姿态")

    def test_action_rename_does_not_overwrite_existing_action(self) -> None:
        with TemporaryDirectory() as temp_dir:
            library_dir = Path(temp_dir)
            (library_dir / "旧动作.json").write_text("{}", encoding="utf-8")
            (library_dir / "已有动作.json").write_text('{"keep": true}', encoding="utf-8")
            library = ActionLibrary(config={"files": {"action_library_dir": str(library_dir)}}, library_dir=library_dir)

            renamed = library.rename_action("旧动作", "新动作")
            self.assertEqual(renamed.name, "新动作.json")
            self.assertFalse((library_dir / "旧动作.json").exists())
            with self.assertRaises(FileExistsError):
                library.rename_action("新动作", "已有动作")
            self.assertEqual(json.loads((library_dir / "已有动作.json").read_text(encoding="utf-8")), {"keep": True})
            with self.assertRaises(ValueError):
                library.rename_action("新动作", "带后缀.json")

    def test_api_schema_and_frontend_expose_rename(self) -> None:
        self.assertEqual(RenameLibraryItemRequest(new_name="新名称").new_name, "新名称")
        app = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        html = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        backend = (WEB_ROOT / "backend" / "app.py").read_text(encoding="utf-8")

        self.assertIn("data-pose-rename", app)
        self.assertIn("data-action-rename", app)
        self.assertIn('id="libraryRenameDialog"', html)
        self.assertIn('/api/v1/poses/{name}/rename', backend)
        self.assertIn('/api/v1/actions/{name}/rename', backend)


if __name__ == "__main__":
    unittest.main()
