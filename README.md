# MOMO_ROBOTARM控制项目

这是一个学习型机械臂控制项目。项目从仿真开始，逐步扩展到真实 Feetech 舵机控制、URDF 运动学、动作录制、GUI、Web、视觉、语音 Agent、系统集成，最后在阶段十二补齐硬件与装配资料。

本项目包含自主编写的控制、标定、安全检查和集成代码；其中部分硬件参数、URDF/STL 资源和结构约定参考第三方 SOARM MOCE 资料。重新发布或商用前请核验第三方资料的许可证和署名要求。真实机械臂控制有风险，默认使用 dry-run。

## 快速入口

- 最终总 README：`硬件与装配资料/发布资料/最终README.md`
- 快速开始：`硬件与装配资料/发布资料/快速开始.md`
- 项目结构说明：`硬件与装配资料/发布资料/项目结构说明.md`
- 硬件装配资料：`硬件与装配资料/README_硬件与装配资料.md`
- 安全检查清单：`硬件与装配资料/安全检查清单.md`
- 故障排查手册：`硬件与装配资料/故障排查手册.md`
- 第三方来源说明：`THIRD_PARTY_NOTICES.md`

## 阶段目录

| 阶段 | 当前目录 |
|---|---|
| 阶段三 | `仿真控制系统` |
| 阶段四 | `真实舵机控制` |
| 阶段五 | `URDF运动学仿真` |
| 阶段六 | `动作录制与回放增强` |
| 阶段七 | `GUI图形界面` |
| 阶段八 | `Web控制台` |
| 阶段九 | `视觉识别与跟随` |
| 阶段十 | `语音Agent` |
| 阶段十一 | `系统集成` |
| 阶段十二 | `硬件与装配资料` |

## 固定硬件逻辑

```text
J1 shoulder_pan    底座旋转    舵机 ID 1    单圈
J2 shoulder_lift   肩部抬升    舵机 ID 2    多圈
J3 elbow_flex      肘部弯曲    舵机 ID 3    多圈
J4 wrist_flex      腕部俯仰    舵机 ID 4    单圈
J5 wrist_roll      腕部旋转    舵机 ID 5    多圈
J6 gripper         夹爪        舵机 ID 6    单圈/夹爪
```

多圈关节固定为 `J2 / J3 / J5`。

```yaml
shoulder_pan: 1.0
shoulder_lift: -5.3
elbow_flex: 5.6
wrist_flex: -1.0
wrist_roll: 1.0
```

## 最小运行

只跑仿真：

```bash
cd 仿真控制系统
python 主程序_main.py
```

跑系统 dry-run：

```bash
cd 系统集成
python 一键启动.py --mode dry_run
```

真实机械臂前先检查：

```bash
cd 系统集成
python 依赖检查.py
python 标定检查.py
```

真实模式必须先完成硬件安全检查、标定检查、电源和接线检查。connect 只读取标定文件，不等于重新标定。Agent、GUI、Web、视觉都不应绕过阶段四安全控制直接写舵机 raw。
