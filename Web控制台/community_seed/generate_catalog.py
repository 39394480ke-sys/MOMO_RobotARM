"""生成 MOMO 开源社区演示目录。运行后写入同目录 catalog.json。"""

from __future__ import annotations

import json
from pathlib import Path


JOINTS = ("j10", "j11", "j12", "j13", "j14", "j15")
AUTHORS = (
    ("光场研究所", "@lightfield"), ("一格影像", "@oneframe"), ("产品镜头社", "@product-shot"),
    ("食刻 Studio", "@foodmoment"), ("美妆实验室", "@beauty-lab"), ("轨迹工坊", "@motion-craft"),
    ("北岸片场", "@northbank"), ("小满视觉", "@xiaoman"), ("台前幕后", "@onset"), ("MOMO 精选", "@momo-picks"),
)

ASSETS = [
    ("action", "口红 360 环绕", "美妆", "口红环绕", "围绕口红完成一圈均匀的英雄镜头，适合金属和镜面包装。", ["口红", "环绕", "高光"], 5),
    ("pose", "粉底液英雄位", "美妆", "粉底英雄位", "略低机位配合瓶身正面标签，保留肩部高光空间。", ["粉底", "定帧", "棚拍"], 1),
    ("action", "香水高光扫拍", "美妆", "香水扫光", "从瓶肩滑向标签的慢速侧向扫拍。", ["香水", "扫拍", "玻璃"], 4),
    ("pose", "眼影盘俯拍构图", "美妆", "眼影俯拍", "适合眼影盘和刷具平铺的轻俯拍机位。", ["眼影", "俯拍", "平铺"], 1),
    ("action", "护肤瓶缓慢推近", "美妆", "护肤推近", "正面缓慢推近并轻微抬升，突出泵头与品牌字样。", ["护肤", "推近", "广告"], 4),
    ("pose", "咖啡杯侧逆光", "食品饮品", "咖啡侧逆光", "留出蒸汽和杯把空间的侧逆光构图。", ["咖啡", "饮品", "逆光"], 1),
    ("action", "汉堡层次展示", "食品饮品", "汉堡层次", "低机位横移并微抬镜头，依次展示食材层次。", ["汉堡", "横移", "餐饮"], 4),
    ("pose", "甜点俯拍留白", "食品饮品", "甜点俯拍", "为餐盘、餐具和标题文字保留均衡留白。", ["甜点", "俯拍", "菜单"], 1),
    ("action", "气泡饮料瓶环绕", "食品饮品", "饮料环绕", "半环绕配合轻推近，适合透明瓶身和气泡饮料。", ["饮料", "环绕", "清爽"], 5),
    ("pose", "零食袋正面定帧", "食品饮品", "零食定帧", "包装正面不变形的电商定帧姿态。", ["零食", "包装", "电商"], 1),
    ("action", "耳机盒开箱轨迹", "电商产品", "耳机开箱", "从包装俯视切入产品正面，适合开箱转场。", ["耳机", "开箱", "科技"], 4),
    ("action", "手表弧线运镜", "电商产品", "手表弧线", "围绕表盘完成短弧线，保持刻度和表冠清晰。", ["手表", "弧线", "微距"], 5),
    ("action", "鞋款侧面扫拍", "电商产品", "鞋款扫拍", "沿鞋身侧面匀速平移，适合纹理与轮廓展示。", ["鞋履", "平移", "纹理"], 4),
    ("pose", "首饰微距姿态", "电商产品", "首饰微距", "轻俯视的微距机位，避开镜头倒影。", ["首饰", "微距", "质感"], 1),
    ("pose", "科技产品中心位", "电商产品", "科技中心位", "适合键盘、掌机和桌面设备的对称中心构图。", ["科技", "中心构图", "桌面"], 1),
    ("action", "包装盒三段式展示", "电商产品", "包装三段式", "正面、侧面和顶部三个观察角度平滑衔接。", ["包装", "三段式", "电商"], 5),
    ("pose", "半身采访机位", "人物拍摄", "采访机位", "保留眼神方向与头顶空间的半身采访构图。", ["采访", "半身", "人物"], 1),
    ("pose", "人脸自然视角", "人物拍摄", "人脸视角", "接近眼平的自然人像机位，适合短视频口播。", ["人像", "口播", "眼平"], 1),
    ("action", "桌面讲解跟拍", "人物拍摄", "桌面讲解", "在人物与桌面产品之间平滑切换焦点位置。", ["讲解", "桌面", "跟拍"], 4),
    ("action", "人物出场跟随", "人物拍摄", "人物出场", "人物从画外进入时完成短距离横移与回中。", ["人物", "出场", "回中"], 5),
    ("action", "轨道左至右平移", "创意运镜", "轨道平移", "通用匀速轨道平移，可用于片头、转场和空间建立。", ["轨道", "平移", "通用"], 4),
    ("action", "桌面 180 度环绕", "创意运镜", "桌面环绕", "适合小型主体的半圆环绕轨迹，起止点稳定。", ["180度", "环绕", "桌面"], 5),
    ("pose", "低机位推近起点", "创意运镜", "低机位起点", "低机位推近镜头的安全起始姿态。", ["低机位", "起点", "戏剧感"], 1),
    ("action", "俯视下降揭示", "创意运镜", "俯视下降", "由高位俯视缓慢下降，逐步揭示主体和场景。", ["俯视", "下降", "揭示"], 5),
]


def pose_payload(index: int) -> dict:
    joints = [round(((index * (axis + 3) * 7) % 54) - 27 + (8 if axis == 2 else 0), 1) for axis in range(6)]
    return {"关节角度": joints, "夹爪": 50, "说明": "V2 社区精选安全构图姿态。"}


def action_payload(title: str, index: int, frame_count: int) -> dict:
    frames = []
    for frame in range(frame_count):
        progress = frame / max(1, frame_count - 1)
        targets = {}
        for axis, joint in enumerate(JOINTS):
            base = ((index * (axis + 2) * 5) % 44) - 22
            sweep = (progress - 0.5) * (18 if axis in (0, 1) else 10)
            targets[joint] = round(base + sweep, 2)
        frames.append({
            "index": frame + 1,
            "name": f"pose_{frame + 1}",
            "duration_sec": 0.0 if frame == 0 else round(1.25 + (frame % 2) * 0.25, 2),
            "hold_sec": 0.25,
            "joint_targets_deg": targets,
            "replay_joint_targets_deg": dict(targets),
        })
    return {
        "schema_version": "arm_replay_sequence_v1", "robot_variant": "V2", "name": title,
        "description": "MOMO 开源社区 V2 精选动作。", "created_at": "2026-08-01 10:00:00",
        "source": "community_seed", "joint_order": list(JOINTS), "pose_count": len(frames),
        "playback": {"default_duration_sec": 1.5, "default_interval_sec": 0.25}, "poses": frames,
    }


def build_catalog() -> dict:
    items = []
    for index, (kind, title, category, source, description, tags, frames) in enumerate(ASSETS, 1):
        author_name, handle = AUTHORS[(index - 1) % len(AUTHORS)]
        payload = action_payload(title, index, frames) if kind == "action" else pose_payload(index)
        items.append({
            "schema_version": "momo_community_v1", "id": f"seed-{index:02d}", "kind": kind,
            "title": title, "source_name": source, "category": category, "description": description,
            "tags": tags, "author": {"name": author_name, "handle": handle, "accent": "#176b5b"},
            "robot_variant": "V2", "created_at": f"2026-07-{(index % 27) + 1:02d}T10:00:00+08:00",
            "base_likes": 48 + index * 13, "base_comments": 4 + index % 12, "base_downloads": 36 + index * 17,
            "cover_url": f"/static/assets/community/cover-{index:02d}.jpg", "media": {},
            "payload": payload, "user_published": False,
        })
    return {"schema_version": "momo_community_v1", "items": items}


if __name__ == "__main__":
    target = Path(__file__).with_name("catalog.json")
    target.write_text(json.dumps(build_catalog(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target)
