"""MOMO 本地社区的种子内容与用户状态存储。"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import re
import threading
from typing import Any, Iterable, Mapping
from uuid import UUID, uuid4

from 通用_io import atomic_write_json, read_json_object, read_json_object_or_default


COMMUNITY_SCHEMA_VERSION = "momo_community_v1"
COMMUNITY_KINDS = {"action", "pose"}
COMMUNITY_CATEGORIES = ("美妆", "食品饮品", "电商产品", "人物拍摄", "创意运镜")
V2_JOINTS = ("j10", "j11", "j12", "j13", "j14", "j15")
SAFE_NAME_PATTERN = re.compile(r"^[^/\\\x00]{1,64}$")


class CommunityStoreError(ValueError):
    pass


class CommunityItemNotFoundError(CommunityStoreError):
    pass


def normalize_asset_name(name: str) -> str:
    normalized = str(name).strip()
    if not normalized:
        raise CommunityStoreError("资产名称不能为空。")
    if normalized.lower().endswith(".json"):
        raise CommunityStoreError("资产名称无需包含 .json 后缀。")
    if not SAFE_NAME_PATTERN.fullmatch(normalized) or normalized in {".", ".."}:
        raise CommunityStoreError("资产名称不能包含路径字符，且不能超过 64 个字符。")
    return normalized


def validate_media_id(media_id: str) -> str:
    value = str(media_id or "").strip()
    if not value:
        return ""
    try:
        return str(UUID(value))
    except (TypeError, ValueError, AttributeError) as exc:
        raise CommunityStoreError("Camera Hub 素材 ID 不合法。") from exc


def validate_community_payload(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
    normalized_kind = str(kind).strip().lower()
    if normalized_kind not in COMMUNITY_KINDS:
        raise CommunityStoreError("社区资产类型必须是 action 或 pose。")
    if not isinstance(payload, Mapping):
        raise CommunityStoreError("社区资产载荷必须是对象。")
    result = deepcopy(dict(payload))
    if normalized_kind == "action":
        if result.get("schema_version") != "arm_replay_sequence_v1":
            raise CommunityStoreError("动作格式不是 arm_replay_sequence_v1。")
        if result.get("robot_variant", "V2") != "V2":
            raise CommunityStoreError("社区首版只支持 V2 机械臂动作。")
        poses = result.get("poses")
        if not isinstance(poses, list) or not poses:
            raise CommunityStoreError("动作必须至少包含一个姿态。")
        for index, pose in enumerate(poses, 1):
            targets = pose.get("joint_targets_deg") if isinstance(pose, Mapping) else None
            if not isinstance(targets, Mapping) or set(targets) != set(V2_JOINTS):
                raise CommunityStoreError(f"动作第 {index} 个姿态必须包含 J10-J15 六关节目标。")
            try:
                pose["joint_targets_deg"] = {joint: float(targets[joint]) for joint in V2_JOINTS}
            except (TypeError, ValueError) as exc:
                raise CommunityStoreError(f"动作第 {index} 个姿态关节数据不合法。") from exc
        result["robot_variant"] = "V2"
        return result

    joints = result.get("关节角度")
    if not isinstance(joints, list) or len(joints) != 6:
        raise CommunityStoreError("姿态必须包含六个关节角度。")
    try:
        result["关节角度"] = [float(value) for value in joints]
        result["夹爪"] = float(result.get("夹爪", 50.0))
    except (TypeError, ValueError) as exc:
        raise CommunityStoreError("姿态关节角度或夹爪数据不合法。") from exc
    return result


class CommunityStore:
    def __init__(self, seed_catalog_path: str | Path, runtime_dir: str | Path, local_author: str = "MOMO Studio"):
        self.seed_catalog_path = Path(seed_catalog_path).resolve()
        self.runtime_dir = Path(runtime_dir).resolve()
        self.posts_dir = self.runtime_dir / "posts"
        self.state_path = self.runtime_dir / "state.json"
        self.local_author = str(local_author).strip() or "MOMO Studio"
        self._lock = threading.RLock()

    def list_items(
        self,
        *,
        query: str = "",
        kind: str = "all",
        category: str = "all",
        sort: str = "popular",
        favorite_only: bool = False,
    ) -> dict[str, Any]:
        with self._lock:
            state = self._read_state()
            items = [self._public_item(item, state) for item in self._all_items()]
            query_text = str(query).strip().casefold()
            if query_text:
                items = [item for item in items if query_text in self._search_text(item)]
            if kind in COMMUNITY_KINDS:
                items = [item for item in items if item["kind"] == kind]
            if category in COMMUNITY_CATEGORIES:
                items = [item for item in items if item["category"] == category]
            if favorite_only:
                items = [item for item in items if item["favorite"]]
            if sort == "latest":
                items.sort(key=lambda item: (item.get("created_at", ""), item["id"]), reverse=True)
            else:
                items.sort(key=self._popular_score, reverse=True)
            return {"items": items, "stats": self._stats(items=self._all_items(), state=state)}

    def get_public(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            return self._public_item(self.get_raw(item_id), self._read_state(), include_detail=True)

    def get_raw(self, item_id: str) -> dict[str, Any]:
        normalized_id = str(item_id).strip()
        for item in self._all_items():
            if item.get("id") == normalized_id:
                return deepcopy(item)
        raise CommunityItemNotFoundError(f"社区资产不存在：{item_id}")

    def publish(
        self,
        *,
        kind: str,
        source_name: str,
        title: str,
        category: str,
        description: str,
        tags: Iterable[str],
        payload: Mapping[str, Any],
        media: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_kind = str(kind).strip().lower()
        normalized_title = normalize_asset_name(title)
        normalized_source = normalize_asset_name(source_name)
        if category not in COMMUNITY_CATEGORIES:
            raise CommunityStoreError("请选择有效的社区分类。")
        normalized_payload = validate_community_payload(normalized_kind, payload)
        normalized_tags = []
        for value in tags:
            tag = str(value).strip()
            if tag and tag not in normalized_tags:
                normalized_tags.append(tag[:18])
        now = datetime.now(timezone.utc).isoformat()
        item = {
            "schema_version": COMMUNITY_SCHEMA_VERSION,
            "id": str(uuid4()),
            "kind": normalized_kind,
            "title": normalized_title,
            "source_name": normalized_source,
            "category": category,
            "description": str(description).strip()[:400],
            "tags": normalized_tags[:5],
            "author": {"name": self.local_author, "handle": "@momo-studio", "accent": "#176b5b"},
            "robot_variant": "V2",
            "created_at": now,
            "base_likes": 0,
            "base_comments": 0,
            "base_downloads": 0,
            "cover_url": self._fallback_cover(category),
            "media": dict(media or {}),
            "payload": normalized_payload,
            "user_published": True,
        }
        with self._lock:
            self.posts_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_json(self.posts_dir / f"{item['id']}.json", item)
            return self._public_item(item, self._read_state(), include_detail=True)

    def set_favorite(self, item_id: str, favorite: bool) -> dict[str, Any]:
        with self._lock:
            item = self.get_raw(item_id)
            state = self._read_state()
            favorites = set(state.get("favorites", []))
            if favorite:
                favorites.add(item_id)
            else:
                favorites.discard(item_id)
            state["favorites"] = sorted(favorites)
            self._write_state(state)
            return self._public_item(item, state)

    def record_import(self, item_id: str) -> dict[str, Any]:
        with self._lock:
            item = self.get_raw(item_id)
            state = self._read_state()
            imports = dict(state.get("imports", {}))
            imports[item_id] = int(imports.get(item_id, 0)) + 1
            state["imports"] = imports
            self._write_state(state)
            return self._public_item(item, state)

    def _all_items(self) -> list[dict[str, Any]]:
        seeds = self._read_seed_items()
        posts: list[dict[str, Any]] = []
        if self.posts_dir.exists():
            for path in sorted(self.posts_dir.glob("*.json")):
                try:
                    posts.append(self._validate_item(read_json_object(path)))
                except Exception:
                    continue
        return seeds + posts

    def _read_seed_items(self) -> list[dict[str, Any]]:
        payload = read_json_object(self.seed_catalog_path)
        if payload.get("schema_version") != COMMUNITY_SCHEMA_VERSION:
            raise CommunityStoreError("社区种子目录版本不受支持。")
        items = payload.get("items", [])
        if not isinstance(items, list):
            raise CommunityStoreError("社区种子 items 必须是列表。")
        return [self._validate_item(item) for item in items]

    def _validate_item(self, item: Mapping[str, Any]) -> dict[str, Any]:
        result = deepcopy(dict(item))
        if result.get("schema_version") != COMMUNITY_SCHEMA_VERSION:
            raise CommunityStoreError("社区条目版本不受支持。")
        result["kind"] = str(result.get("kind", "")).lower()
        result["title"] = normalize_asset_name(result.get("title", ""))
        result["source_name"] = normalize_asset_name(result.get("source_name", result["title"]))
        if result.get("category") not in COMMUNITY_CATEGORIES:
            raise CommunityStoreError("社区条目分类不合法。")
        result["payload"] = validate_community_payload(result["kind"], result.get("payload", {}))
        result["robot_variant"] = "V2"
        return result

    def _read_state(self) -> dict[str, Any]:
        state = read_json_object_or_default(self.state_path, {"favorites": [], "imports": {}})
        state.setdefault("favorites", [])
        state.setdefault("imports", {})
        return state

    def _write_state(self, state: Mapping[str, Any]) -> None:
        atomic_write_json(self.state_path, dict(state))

    def _public_item(self, item: Mapping[str, Any], state: Mapping[str, Any], include_detail: bool = False) -> dict[str, Any]:
        result = {key: deepcopy(value) for key, value in item.items() if key != "payload"}
        item_id = str(item.get("id"))
        result["favorite"] = item_id in set(state.get("favorites", []))
        result["download_count"] = int(item.get("base_downloads", 0)) + int(state.get("imports", {}).get(item_id, 0))
        result["like_count"] = int(item.get("base_likes", 0))
        result["comment_count"] = int(item.get("base_comments", 0))
        result["summary"] = self._payload_summary(str(item.get("kind")), item.get("payload", {}))
        if include_detail:
            result["safety_note"] = "加入本机资产库后仍需通过机械臂现有连接确认、限位和停止机制。"
        return result

    def _stats(self, *, items: list[dict[str, Any]], state: Mapping[str, Any]) -> dict[str, Any]:
        return {
            "asset_count": len(items),
            "creator_count": len({str(item.get("author", {}).get("handle", "")) for item in items}),
            "reuse_count": sum(int(item.get("base_downloads", 0)) for item in items) + sum(int(value) for value in state.get("imports", {}).values()),
            "favorite_count": len(state.get("favorites", [])),
            "node": "local",
        }

    @staticmethod
    def _payload_summary(kind: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        if kind == "pose":
            joints = [round(float(value), 2) for value in payload.get("关节角度", [])]
            return {"joint_count": len(joints), "joints_deg": joints, "gripper": payload.get("夹爪", 50)}
        poses = payload.get("poses", []) if isinstance(payload, Mapping) else []
        duration = 0.0
        for pose in poses if isinstance(poses, list) else []:
            if isinstance(pose, Mapping):
                duration += float(pose.get("duration_sec", 0.0) or 0.0) + float(pose.get("hold_sec", 0.0) or 0.0)
        ranges: dict[str, list[float]] = {}
        for joint in ("j10", "j11", "j12", "j13", "j14", "j15"):
            values = [
                float(pose.get("joint_targets_deg", {}).get(joint, 0.0))
                for pose in poses
                if isinstance(pose, Mapping) and isinstance(pose.get("joint_targets_deg"), Mapping)
            ]
            if values:
                ranges[joint] = [round(min(values), 1), round(max(values), 1)]
        return {"pose_count": len(poses), "duration_sec": round(duration, 2), "joint_ranges_deg": ranges}

    @staticmethod
    def _search_text(item: Mapping[str, Any]) -> str:
        values = [item.get("title"), item.get("description"), item.get("category"), item.get("kind")]
        values.extend(item.get("tags", []))
        values.extend(item.get("author", {}).values())
        return " ".join(str(value) for value in values).casefold()

    @staticmethod
    def _popular_score(item: Mapping[str, Any]) -> tuple[int, str]:
        score = int(item.get("download_count", 0)) * 3 + int(item.get("like_count", 0)) * 2 + int(item.get("comment_count", 0))
        return score, str(item.get("created_at", ""))

    @staticmethod
    def _fallback_cover(category: str) -> str:
        index = COMMUNITY_CATEGORIES.index(category) + 1 if category in COMMUNITY_CATEGORIES else 1
        return f"/static/assets/community/cover-{index:02d}.jpg"
