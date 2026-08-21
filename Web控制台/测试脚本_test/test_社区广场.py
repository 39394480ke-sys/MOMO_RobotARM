"""MOMO 本地社区存储、快照与前端契约测试。"""

from copy import deepcopy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import Web测试路径_test_paths  # noqa: F401

from backend.community_store import CommunityStore, CommunityStoreError, validate_media_id
from backend.errors import WebAPIError
from backend.schemas import CommunityImportRequest
from backend.service import WebControlService


WEB_ROOT = Path(__file__).resolve().parents[1]
SEED = WEB_ROOT / "community_seed" / "catalog.json"


class CommunityStoreTest(unittest.TestCase):
    def make_store(self, root: str) -> CommunityStore:
        return CommunityStore(SEED, Path(root) / "runtime")

    def test_seed_catalog_has_required_distribution_and_valid_payloads(self) -> None:
        with TemporaryDirectory() as root:
            data = self.make_store(root).list_items()
            self.assertEqual(len(data["items"]), 24)
            self.assertEqual(sum(item["kind"] == "action" for item in data["items"]), 14)
            self.assertEqual(sum(item["kind"] == "pose" for item in data["items"]), 10)
            counts = {category: sum(item["category"] == category for item in data["items"]) for category in ("美妆", "食品饮品", "电商产品", "人物拍摄", "创意运镜")}
            self.assertEqual(counts, {"美妆": 5, "食品饮品": 5, "电商产品": 6, "人物拍摄": 4, "创意运镜": 4})
            self.assertEqual(data["stats"]["creator_count"], 10)

    def test_search_filters_sort_and_favorite_persist(self) -> None:
        with TemporaryDirectory() as root:
            store = self.make_store(root)
            self.assertEqual(len(store.list_items(query="口红")["items"]), 1)
            self.assertTrue(all(item["kind"] == "pose" for item in store.list_items(kind="pose")["items"]))
            store.set_favorite("seed-01", True)
            self.assertEqual([item["id"] for item in store.list_items(favorite_only=True)["items"]], ["seed-01"])
            reloaded = self.make_store(root)
            self.assertTrue(reloaded.get_public("seed-01")["favorite"])

    def test_publish_is_independent_snapshot_and_import_count_persists(self) -> None:
        with TemporaryDirectory() as root:
            store = self.make_store(root)
            original = store.get_raw("seed-01")
            source = deepcopy(original["payload"])
            published = store.publish(
                kind="action", source_name="本机动作", title="我的环绕", category="美妆",
                description="离线快照", tags=["环绕"], payload=source,
            )
            source["poses"][0]["joint_targets_deg"]["j10"] = 999
            self.assertNotEqual(store.get_raw(published["id"])["payload"]["poses"][0]["joint_targets_deg"]["j10"], 999)
            store.record_import(published["id"])
            self.assertEqual(self.make_store(root).get_public(published["id"])["download_count"], 1)

    def test_rejects_broken_payload_and_invalid_media_id(self) -> None:
        with TemporaryDirectory() as root:
            store = self.make_store(root)
            broken = deepcopy(store.get_raw("seed-01")["payload"])
            del broken["poses"][0]["joint_targets_deg"]["j12"]
            with self.assertRaises(CommunityStoreError):
                store.publish(kind="action", source_name="坏动作", title="坏动作", category="美妆", description="", tags=[], payload=broken)
            with self.assertRaises(CommunityStoreError):
                validate_media_id("../../bad")

    def test_frontend_and_api_expose_complete_community_flow(self) -> None:
        app_js = (WEB_ROOT / "frontend" / "app.js").read_text(encoding="utf-8")
        html = (WEB_ROOT / "frontend" / "index.html").read_text(encoding="utf-8")
        backend = (WEB_ROOT / "backend" / "app.py").read_text(encoding="utf-8")
        self.assertIn('id="pageCommunity"', html)
        self.assertIn("data-action-share", app_js)
        self.assertIn("data-pose-share", app_js)
        self.assertIn("COMMUNITY_NAME_CONFLICT", app_js)
        self.assertIn('/api/v1/community/items/{item_id}/import', backend)
        covers = list((WEB_ROOT / "frontend" / "assets" / "community").glob("cover-*.jpg"))
        self.assertEqual(len(covers), 24)

    def test_service_imports_action_and_pose_without_motion(self) -> None:
        class Bridge:
            calls = []

            def import_action_asset(self, name, payload):
                self.calls.append(("action", name, payload))
                return {"ok": True, "message": "动作已导入", "data": {}}

            def import_pose_asset(self, name, payload):
                self.calls.append(("pose", name, payload))
                return {"ok": True, "message": "姿态已导入", "data": {}}

        with TemporaryDirectory() as root:
            service = WebControlService.__new__(WebControlService)
            service.community = self.make_store(root)
            service.bridge = Bridge()
            service.list_actions = lambda: {"actions": []}
            service.list_poses = lambda: {"poses": []}
            action = service.community_import("seed-01", CommunityImportRequest(target_name="社区动作"))
            pose = service.community_import("seed-02", CommunityImportRequest(target_name="社区姿态"))
            self.assertEqual((action["kind"], pose["kind"]), ("action", "pose"))
            self.assertEqual([call[:2] for call in service.bridge.calls], [("action", "社区动作"), ("pose", "社区姿态")])

    def test_service_import_conflict_never_calls_bridge(self) -> None:
        class Bridge:
            def import_action_asset(self, *_args):
                raise AssertionError("同名冲突时不应写入本机库")

        with TemporaryDirectory() as root:
            service = WebControlService.__new__(WebControlService)
            service.community = self.make_store(root)
            service.bridge = Bridge()
            service.list_actions = lambda: {"actions": [{"name": "口红 360 环绕"}]}
            service.list_poses = lambda: {"poses": []}
            with self.assertRaises(WebAPIError) as caught:
                service.community_import("seed-01", CommunityImportRequest())
            self.assertEqual(caught.exception.code, "COMMUNITY_NAME_CONFLICT")


if __name__ == "__main__":
    unittest.main()
