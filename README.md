# MOMO Robot Arm

MOMO Robot Arm 是一个导轨版机械臂控制项目，覆盖本地仿真、真实 Feetech 舵机控制、URDF 运动学、动作录制回放、GUI、Web 控制台、视觉跟随、语音 Agent 和系统集成。

这个仓库当前更接近“可运行的个人机器人系统”而不是通用库。真实硬件控制有风险，默认推荐从 `dry_run` 开始，确认标定、安全和急停手段后再进入真实模式。

## 当前硬件事实

当前代码和标定以 J10-J15 导轨版为准：

| key | 关节 | 舵机 ID | 说明 |
|---|---|---:|---|
| `j10` | J10 底盘导轨 | 10 | 线性导轨，GUI/Web 单位为 mm，多圈 |
| `j11` | J11 底座旋转 | 11 | 1:5 行星减速，GUI/Web 单位为输出端 deg，多圈 |
| `j12` | J12 肩部抬升 | 12 | 多圈 |
| `j13` | J13 肘部弯曲 | 13 | 多圈 |
| `j14` | J14 腕部俯仰 | 14 | 当前按多圈软件限位处理，直连 1:1 |
| `j15` | J15 腕部旋转 | 15 | 多圈 |
| `gripper` | J16 夹爪 | 16 | 可选夹爪，不参与主 IK 链 |

当前主关节顺序为：

```text
j10, j11, j12, j13, j14, j15
```

默认型号是 V2。型号与模型映射以 `配置/robot_v2.yaml` 为准；V1 兼容配置为
`配置/robot_v1.yaml`。V1 使用 `urdf/v1`、`meshes/v1` 和 `Link_6`，V2 使用
`urdf/v2`、`meshes/v2` 和 `Link_7`（路径均相对于 `URDF运动学仿真/`）。

真实配置加载顺序是：受版本控制的基础配置 → 被忽略的本地覆盖 → 权威型号 profile →
运行参数环境变量。通过本地 `真实配置.local.yaml` 的 `robot.variant` 选择型号；
环境变量不提供型号选择，只覆盖串口、驱动后端和 `dry_run`。profile 的硬件字段优先于
本地覆盖。受控默认必须保持串口为空且 `dry_run: true`。真实标定只使用被忽略的
`真实舵机控制/标定/current.local.json`；仓库里的 V1/V2 example 文件只是模板，
绝不能用于真机。

## 快速运行

推荐使用 `momo_rebot` 环境：

```bash
mamba run -n momo_rebot python --version
```

启动 Web 控制台，默认 `dry_run`：

```bash
cd Web控制台
mamba run -n momo_rebot python 启动Web服务.py
```

打开：

```text
http://127.0.0.1:8010/web/
```

启动 GUI：

```bash
cd GUI图形界面
mamba run -n momo_rebot python GUI主程序_main.py
```

检查 URDF：

```bash
mamba run -n momo_rebot python URDF运动学仿真/URDF检查_urdf_inspector.py
```

系统 dry-run：

```bash
cd 系统集成
mamba run -n momo_rebot python 一键启动.py --mode dry_run
```

真实模式前先检查：

```bash
cd 系统集成
mamba run -n momo_rebot python 依赖检查.py
mamba run -n momo_rebot python 标定检查.py
```

真实模式必须确认硬件装配、电源、接线、标定、运动空间和急停方式。`connect` 只读取标定文件，不等于重新标定。

## 项目结构

| 目录/文件 | 内容 |
|---|---|
| `仿真控制系统` | 基础仿真、姿态库和动作播放 |
| `真实舵机控制` | Feetech 舵机驱动、角度映射、标定和安全检查 |
| `URDF运动学仿真` | URDF、mesh、FK/IK、PyBullet 检查与显示 |
| `动作录制与回放增强` | 动作录制、插值、动作库和回放 |
| `GUI图形界面` | PyQt 桌面控制界面 |
| `Web控制台` | FastAPI 后端、本地 Web 前端、WebSocket 状态 |
| `视觉识别与跟随` | 摄像头、检测、目标选择、视觉跟随 |
| `语音Agent` | 语音输入输出、Agent 客户端、工具桥接 |
| `系统集成` | 一键启动、停止、健康检查、日志和运行状态 |
| `硬件与装配资料` | BOM、接线、装配、安全、维护和故障排查文档 |
| `机械臂基本概念` | 关节、安全和术语入门文档 |
| `docs/README.md` | 常用文档索引 |

顶层的 `通用_*.py`、`控制桥接_common.py` 等是当前各模块共享的本地工具代码。第一轮整理保留原路径，避免影响现有运行链路。

## 常用文档

- [文档索引](docs/README.md)
- [V2 真机验收门禁](docs/V2真机验收.md)
- [MOMO 智能摄影机械臂物联网系统研发流程图](docs/MOMO智能摄影机械臂物联网系统研发流程图.png)
- [系统整体框图与设计流程图](系统整体框图与设计流程图.md)
- [导轨版使用教程](机械臂导轨版使用教程_GUI_Web_URDF.md)
- [真实舵机控制说明](真实舵机控制/README_真实舵机控制.md)
- [Web 控制台说明](Web控制台/README_Web控制台.md)
- [GUI 图形界面说明](GUI图形界面/README_GUI图形界面.md)
- [硬件与装配资料](硬件与装配资料/README_硬件与装配资料.md)
- [第三方来源说明](THIRD_PARTY_NOTICES.md)

## 安全边界

- 默认使用 `dry_run`，先验证动作链路，再考虑真机。
- 真机移动前必须完成标定检查、电源和接线检查。
- 标定的 `_meta.robot_variant` 和动作顶层的 `robot_variant` 必须与当前型号完全一致；缺失、未知或不匹配时只允许仿真或 `dry_run` 预览。
- V2 J12/J13 的有效逻辑范围必须根据当前 Home 和绝对 raw 上限 `±30719` 动态计算，不能绕过。
- Web、GUI、视觉和语音 Agent 都应通过统一控制接口间接控制机械臂，不应绕过安全层直接写舵机 raw。
- 每个真实阶段都要单独明确批准，并按 ping → 只读 raw → 核对零位 → 单关节微动 → 停止/关闭扭矩 → 低速多关节的顺序进行。

## 开发说明

当前仓库保留中文阶段目录名，是为了不破坏已有脚本、导入路径和运行习惯。后续如果要进一步开源化，可以再单独规划 `src/` 化、统一测试入口、配置样例和 CI；这不属于第一轮门面整理范围。
