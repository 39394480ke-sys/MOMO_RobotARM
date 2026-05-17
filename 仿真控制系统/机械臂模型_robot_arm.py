"""仿真机械臂模型。

这个模块只负责“电脑里的机械臂状态”：
- 保存当前逻辑关节角度
- 保存当前夹爪开合值
- 检查目标角度是否在配置范围内
- 更新仿真状态

注意：这里不控制真实舵机，也不把逻辑角度转换成舵机原始值。
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class 操作结果:
    """统一返回给主程序的执行结果。"""

    成功: bool
    消息: str


class 机械臂模型:
    """保存和更新仿真机械臂的当前状态。"""

    def __init__(self, 配置: dict[str, Any]):
        self.配置 = 配置
        self.关节配置 = 配置.get("关节", [])
        self.夹爪配置 = 配置.get("夹爪", {})

        if not self.关节配置:
            raise ValueError("配置中没有找到关节列表。")

        self.关节名称 = [关节.get("名称", f"关节{序号 + 1}") for 序号, 关节 in enumerate(self.关节配置)]
        self.当前角度 = [float(关节.get("默认角度", 0)) for 关节 in self.关节配置]
        self.默认角度 = list(self.当前角度)
        self.当前夹爪 = float(self.夹爪配置.get("默认开合", 50))

        检查结果 = self.检查关节角度(self.当前角度)
        if not 检查结果.成功:
            raise ValueError(f"默认关节角度不合法：{检查结果.消息}")

        夹爪检查 = self.检查夹爪开合(self.当前夹爪)
        if not 夹爪检查.成功:
            raise ValueError(f"默认夹爪开合不合法：{夹爪检查.消息}")

    def 获取当前状态(self) -> dict[str, Any]:
        """返回当前状态的副本，避免外部代码直接修改内部状态。"""

        return {
            "关节角度": list(self.当前角度),
            "夹爪": self.当前夹爪,
        }

    def 获取详细状态(self) -> dict[str, Any]:
        """返回带关节名称的状态，方便主程序打印。"""

        return {
            "关节": [
                {
                    "编号": 序号 + 1,
                    "名称": self.关节名称[序号],
                    "角度": self.当前角度[序号],
                    "最小角度": float(关节.get("最小角度", -180)),
                    "最大角度": float(关节.get("最大角度", 180)),
                    "模式": 关节.get("模式", "单圈"),
                }
                for 序号, 关节 in enumerate(self.关节配置)
            ],
            "夹爪": self.当前夹爪,
            "夹爪最小": float(self.夹爪配置.get("最小开合", 0)),
            "夹爪最大": float(self.夹爪配置.get("最大开合", 100)),
        }

    def 检查关节角度(self, 目标角度: list[float]) -> 操作结果:
        """检查一整组逻辑关节角度是否安全。"""

        if len(目标角度) != len(self.关节配置):
            return 操作结果(
                False,
                f"角度数量不对：需要 {len(self.关节配置)} 个，实际收到 {len(目标角度)} 个。",
            )

        for 序号, 角度 in enumerate(目标角度):
            关节 = self.关节配置[序号]
            名称 = 关节.get("名称", f"关节{序号 + 1}")
            最小角度 = float(关节.get("最小角度", -180))
            最大角度 = float(关节.get("最大角度", 180))

            if 角度 < 最小角度 or 角度 > 最大角度:
                return 操作结果(
                    False,
                    f"{名称} 的角度 {格式化数值(角度)} 超出范围 "
                    f"[{格式化数值(最小角度)}, {格式化数值(最大角度)}]。",
                )

        return 操作结果(True, "关节角度合法。")

    def 移动到关节角度(self, 目标角度: list[float]) -> 操作结果:
        """检查并移动到一组目标逻辑关节角度。"""

        检查结果 = self.检查关节角度(目标角度)
        if not 检查结果.成功:
            return 检查结果

        self.当前角度 = [float(角度) for 角度 in 目标角度]
        return 操作结果(True, "移动成功。")

    def 移动单个关节(self, 关节编号: int, 目标角度: float) -> 操作结果:
        """只移动一个关节。关节编号从 1 开始。"""

        if 关节编号 < 1 or 关节编号 > len(self.关节配置):
            return 操作结果(False, f"关节编号必须在 1 到 {len(self.关节配置)} 之间。")

        新角度 = list(self.当前角度)
        新角度[关节编号 - 1] = float(目标角度)
        return self.移动到关节角度(新角度)

    def 检查夹爪开合(self, 开合值: float) -> 操作结果:
        """检查夹爪开合值是否在允许范围内。"""

        最小开合 = float(self.夹爪配置.get("最小开合", 0))
        最大开合 = float(self.夹爪配置.get("最大开合", 100))
        if 开合值 < 最小开合 or 开合值 > 最大开合:
            return 操作结果(
                False,
                f"夹爪开合值 {格式化数值(开合值)} 超出范围 "
                f"[{格式化数值(最小开合)}, {格式化数值(最大开合)}]。",
            )

        return 操作结果(True, "夹爪开合值合法。")

    def 设置夹爪(self, 开合值: float) -> 操作结果:
        """设置夹爪开合值。0 通常表示闭合，100 通常表示张开。"""

        检查结果 = self.检查夹爪开合(开合值)
        if not 检查结果.成功:
            return 检查结果

        self.当前夹爪 = float(开合值)
        return 操作结果(True, f"夹爪已设置为 {格式化数值(self.当前夹爪)}。")

    def 张开夹爪(self) -> 操作结果:
        """把夹爪设置为配置中的张开值。"""

        return self.设置夹爪(float(self.夹爪配置.get("张开值", 100)))

    def 闭合夹爪(self) -> 操作结果:
        """把夹爪设置为配置中的闭合值。"""

        return self.设置夹爪(float(self.夹爪配置.get("闭合值", 0)))

    def 回到默认姿态(self) -> 操作结果:
        """回到配置中的默认姿态，保持夹爪当前开合。"""

        角度结果 = self.移动到关节角度(list(self.默认角度))
        if not 角度结果.成功:
            return 角度结果

        return 操作结果(True, "已回到默认姿态。")

    def 应用姿态(self, 姿态: dict[str, Any]) -> 操作结果:
        """把姿态数据应用到机械臂模型。"""

        姿态副本 = deepcopy(姿态)
        目标角度 = 姿态副本.get("关节角度")
        if 目标角度 is None:
            return 操作结果(False, "姿态缺少“关节角度”。")

        try:
            数字角度 = [float(角度) for 角度 in 目标角度]
        except (TypeError, ValueError):
            return 操作结果(False, "姿态中的关节角度必须是数字。")

        移动结果 = self.移动到关节角度(数字角度)
        if not 移动结果.成功:
            return 移动结果

        if "夹爪" in 姿态副本:
            try:
                夹爪值 = float(姿态副本["夹爪"])
            except (TypeError, ValueError):
                return 操作结果(False, "姿态中的夹爪开合值必须是数字。")

            夹爪结果 = self.设置夹爪(夹爪值)
            if not 夹爪结果.成功:
                return 夹爪结果

        return 操作结果(True, "姿态应用成功。")


def 格式化数值(数值: float) -> str:
    """打印状态时去掉没有必要的小数点。"""

    if float(数值).is_integer():
        return str(int(数值))
    return f"{数值:.2f}".rstrip("0").rstrip(".")
