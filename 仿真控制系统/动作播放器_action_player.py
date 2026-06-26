"""动作播放器。

动作是一串姿态。播放器只负责按顺序播放这些姿态，并在姿态之间做简单插值。
真正的角度合法性检查仍然交给 机械臂模型。
"""

from __future__ import annotations

import time
from json import JSONDecodeError
from pathlib import Path
from typing import Any, Callable

from 仿真路径工具_sim_path_utils import ensure_project_root_on_path

ensure_project_root_on_path()

from 机械臂模型_robot_arm import 操作结果
from 通用_io import list_json_stems, read_json_object, resolve_named_json_path


class 动作播放器:
    """按顺序播放动作库中的动作。"""

    def __init__(
        self,
        机械臂,
        动作目录: str | Path,
        默认等待秒: float = 0.15,
        默认插值步数: int = 5,
    ):
        self.机械臂 = 机械臂
        self.动作目录 = Path(动作目录)
        self.默认等待秒 = float(默认等待秒)
        self.默认插值步数 = max(1, int(默认插值步数))
        self.停止标记 = False
        self.动作目录.mkdir(parents=True, exist_ok=True)

    def 列出动作(self) -> list[str]:
        """列出动作目录里的所有 JSON 动作文件。"""

        return list_json_stems(self.动作目录)

    def 读取动作(self, 名称: str) -> dict[str, Any]:
        """读取一个动作 JSON。"""

        路径 = resolve_named_json_path(self.动作目录, 名称)
        if not 路径.exists():
            raise FileNotFoundError(f"没有找到动作：{名称}")

        try:
            动作 = read_json_object(路径)
        except JSONDecodeError as 错误:
            raise ValueError(f"动作文件 JSON 格式错误：{错误}") from 错误
        except ValueError as 错误:
            raise ValueError("动作文件最外层必须是 JSON 对象。") from 错误
        if "步骤" not in 动作 or not isinstance(动作["步骤"], list):
            raise ValueError("动作文件必须包含列表字段“步骤”。")

        return 动作

    def 播放动作(
        self,
        名称: str,
        打印回调: Callable[[str], None] | None = None,
        重复次数: int = 1,
    ) -> 操作结果:
        """读取并播放指定动作。"""

        self.停止标记 = False
        try:
            动作 = self.读取动作(名称)
        except (FileNotFoundError, ValueError) as 错误:
            return 操作结果(False, str(错误))

        步骤列表 = 动作["步骤"]
        if not 步骤列表:
            return 操作结果(False, f"动作“{名称}”没有任何步骤。")

        for 第几轮 in range(max(1, 重复次数)):
            for 步骤序号, 步骤 in enumerate(步骤列表, start=1):
                if self.停止标记:
                    return 操作结果(False, "动作已停止。")

                结果 = self.播放单个姿态(步骤)
                if not 结果.成功:
                    return 操作结果(False, f"动作“{名称}”第 {步骤序号} 步失败：{结果.消息}")

                if 打印回调 is not None:
                    步骤名称 = 步骤.get("名称", f"第{步骤序号}步")
                    打印回调(f"  已执行：{步骤名称}")

        return 操作结果(True, f"动作“{名称}”播放完成。")

    def 播放单个姿态(self, 姿态: dict[str, Any]) -> 操作结果:
        """把一个动作步骤插值播放到目标姿态。"""

        if not isinstance(姿态, dict):
            return 操作结果(False, "动作步骤必须是 JSON 对象。")

        目标角度 = 姿态.get("关节角度")
        if 目标角度 is None:
            return 操作结果(False, "动作步骤缺少“关节角度”。")

        try:
            目标角度 = [float(角度) for 角度 in 目标角度]
        except (TypeError, ValueError):
            return 操作结果(False, "动作步骤中的关节角度必须是数字。")

        当前状态 = self.机械臂.获取当前状态()
        当前角度 = [float(角度) for 角度 in 当前状态["关节角度"]]
        当前夹爪 = float(当前状态["夹爪"])

        if "夹爪" in 姿态:
            try:
                目标夹爪 = float(姿态["夹爪"])
            except (TypeError, ValueError):
                return 操作结果(False, "动作步骤中的夹爪开合值必须是数字。")
        else:
            目标夹爪 = 当前夹爪

        插值步数 = max(1, int(姿态.get("插值步数", self.默认插值步数)))
        等待秒 = float(姿态.get("等待秒", self.默认等待秒))

        for 当前步 in range(1, 插值步数 + 1):
            if self.停止标记:
                return 操作结果(False, "动作已停止。")

            比例 = 当前步 / 插值步数
            中间角度 = [
                起点 + (终点 - 起点) * 比例
                for 起点, 终点 in zip(当前角度, 目标角度)
            ]
            中间夹爪 = 当前夹爪 + (目标夹爪 - 当前夹爪) * 比例

            结果 = self.机械臂.移动到关节角度(中间角度)
            if not 结果.成功:
                return 结果

            夹爪结果 = self.机械臂.设置夹爪(中间夹爪)
            if not 夹爪结果.成功:
                return 夹爪结果

            if 等待秒 > 0:
                time.sleep(等待秒)

        return 操作结果(True, "单个姿态播放完成。")

    def 停止播放(self) -> None:
        """设置停止标记。第一版是同步播放，后续做 GUI 时可以继续扩展。"""

        self.停止标记 = True

    def 设置播放速度(self, 等待秒: float | None = None, 插值步数: int | None = None) -> 操作结果:
        """调整后续动作播放的默认速度。"""

        if 等待秒 is not None:
            if 等待秒 < 0:
                return 操作结果(False, "等待秒不能小于 0。")
            self.默认等待秒 = float(等待秒)

        if 插值步数 is not None:
            if 插值步数 < 1:
                return 操作结果(False, "插值步数必须大于等于 1。")
            self.默认插值步数 = int(插值步数)

        return 操作结果(True, "播放速度已更新。")
