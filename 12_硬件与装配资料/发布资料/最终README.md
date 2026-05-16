# 我的 MomoAgent 复刻项目

## 项目目标

本项目是一个学习型 MomoAgent / SOARM MOCE 复刻项目，目标是从仿真控制、真实舵机、URDF、动作录制、GUI、Web、视觉、语音 Agent 到系统集成，逐步搭建一套可理解、可运行、可扩展的机械臂系统。

本项目不是直接复制原项目，而是在理解原硬件逻辑和软件控制链路的基础上做学习复刻。真实机械臂控制有风险，默认使用 dry-run。

## 当前状态

已完成阶段三到阶段十二：

- 仿真控制系统。
- 真实 Feetech 舵机控制与标定。
- URDF / 运动学 / 3D 仿真。
- 动作录制与回放增强。
- GUI 图形界面。
- Web 控制台 / Quick Control API。
- 视觉识别与跟随。
- 语音 Agent。
- 系统集成 / 一键启动。
- 硬件与装配资料 / 项目文档收尾。

## 功能列表

- 5 轴机械臂逻辑关节控制：J1 到 J5。
- J6 夹爪控制。
- dry-run 安全模式。
- 真实 Feetech 舵机控制。
- 标定文件读取、检查和应用。
- URDF 正逆运动学和 3D 显示。
- 动作录制、动作回放和动作库。
- GUI 操作界面。
- Web API 和 WebSocket 状态。
- 摄像头视觉检测和跟随。
- 语音 Agent 工具桥接。
- 阶段十一一键启动和健康检查。
- 阶段十二硬件、装配、接线、标定、安全和发布资料。

## 项目结构

当前仓库使用中文阶段目录名：

| 阶段 | 当前目录 | 说明 |
|---|---|---|
| 01/02 | `机械臂基本概念` | 关节、安全、名词基础 |
| 03 | `仿真控制系统` | 仿真机械臂和姿态动作 |
| 04 | `真实舵机控制` | Feetech 舵机、标定、dry-run、真实控制 |
| 05 | `URDF运动学仿真` | URDF、FK、IK、3D 仿真 |
| 06 | `动作录制与回放增强` | 动作库、录制、回放、安全检查 |
| 07 | `GUI图形界面` | 图形控制界面 |
| 08 | `Web控制台` | Web API、前端控制台 |
| 09 | `视觉识别与跟随` | 摄像头、目标检测、跟随控制 |
| 10 | `语音Agent` | STT/TTS、Agent 工具调用 |
| 11 | `系统集成` | 一键启动、健康检查、统一日志 |
| 12 | `12_硬件与装配资料` | 硬件、装配、发布文档 |

## 快速开始

只跑仿真：

```bash
cd 仿真控制系统
python 主程序_main.py
```

跑 Web dry-run：

```bash
cd 系统集成
python 一键启动.py --mode dry_run
```

真实机械臂：

```bash
cd 系统集成
python 依赖检查.py
python 标定检查.py
python 一键启动.py --mode real
```

真实模式前必须完成标定、安全检查、电源检查、接线检查和首次小角度测试。

## 阶段说明

阶段三到阶段十一主要搭建软件能力。阶段十二把这些能力整理为可复刻资料包，说明硬件是什么、怎么装、怎么接线、怎么标定、怎么启动、怎么测试、怎么排查。

## 硬件说明

本项目沿用原 MomoAgent / SOARM MOCE 逻辑：

```text
J1 shoulder_pan    底座旋转    ID 1    单圈
J2 shoulder_lift   肩部抬升    ID 2    多圈
J3 elbow_flex      肘部弯曲    ID 3    多圈
J4 wrist_flex      腕部俯仰    ID 4    单圈
J5 wrist_roll      腕部旋转    ID 5    多圈
J6 gripper         夹爪        ID 6    单圈/夹爪
```

多圈关节固定为 `J2 / J3 / J5`。硬件规格未确认的部分在阶段十二文档中写为“待确认”。

## 软件说明

关键固定参数：

```yaml
shoulder_pan: 1.0
shoulder_lift: -5.3
elbow_flex: 5.6
wrist_flex: -1.0
wrist_roll: 1.0
```

```text
RAW_COUNTS_PER_REV = 4096
MULTI_TURN_PHASE_VALUE = 28
MULTI_TURN_ABSOLUTE_RAW_LIMIT = 30719
POSITION_MODE_VALUE = 0
```

Agent、GUI、Web、视觉都应该通过已有控制接口间接控制机械臂，不让 Agent 直接写 raw。

## 安全说明

- 默认 dry-run。
- 真实机械臂控制有风险。
- connect 不等于 calibrate。
- 标定文件必须存在且完整。
- 首次真实移动小于 2 度。
- 不多人同时控制硬件。
- 不让 Agent 直接写舵机 raw。
- 急停或断电手段必须可用。

## 如何运行仿真

```bash
cd 仿真控制系统
python 主程序_main.py
```

## 如何运行 dry-run

```bash
cd 系统集成
python 一键启动.py --mode dry_run
```

也可以在阶段四运行：

```bash
cd 真实舵机控制
python 测试脚本_test/04_dry_run移动测试.py
```

## 如何连接真实机械臂

1. 阅读 `12_硬件与装配资料/安全检查清单.md`。
2. 确认电源、接线、舵机 ID、标定文件。
3. 运行：

```bash
cd 系统集成
python 依赖检查.py
python 标定检查.py
python 一键启动.py --mode real
```

如果标定不完整，real 模式不应继续。

## 如何运行 Web

```bash
cd Web控制台
python 启动Web服务.py
```

或由阶段十一统一启动：

```bash
cd 系统集成
python 一键启动.py --mode dry_run
```

阶段十一启动器会默认启动 Web API，并打印 Web 控制台地址。

## 如何运行 GUI

```bash
cd GUI图形界面
python GUI主程序_main.py
```

## 如何运行视觉

```bash
cd 视觉识别与跟随
python 视觉主程序_main.py
```

真实跟随前必须先 dry-run，并确认 Web API 模式。

## 如何运行语音 Agent

```bash
cd 语音Agent
python 语音Agent主程序_main.py
```

语音 Agent 默认不应直接控制 raw，只通过工具桥接调用阶段八 API。

## 常见问题

- 串口找不到：检查 USB 数据线、串口名和 `SOARMMOCE_PORT`。
- 舵机无响应：检查外部舵机电源、总线方向、舵机 ID。
- 多圈关节跑飞：检查 J2/J3/J5 的 `home_present_raw` 和 `phase=28`。
- 标定文件缺失：运行阶段十一 `标定检查.py`，必要时运行阶段四标定程序。
- Agent 工具调用失败：先确认 Web API 正常，再检查 Agent 安全策略。

更多见 `12_硬件与装配资料/故障排查手册.md`。

## 后续计划

- 补齐原项目 STEP / 3MF / 打印参数来源。
- 补拍装配、接线、标定姿态照片。
- 补充真实硬件电源和螺丝规格。
- 增加发布版本号和变更记录。
- 完善真实机械臂长期稳定性测试。
