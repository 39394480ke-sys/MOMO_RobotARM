# 阶段四：真实舵机控制系统

本目录是在阶段三“仿真控制系统”基础上扩展出来的真实舵机控制层。阶段三没有被重写，姿态库和动作库仍然放在 `../仿真控制系统/姿态管理/`，阶段四通过统一接口复用它们。

## 1. 阶段四目标

阶段四增加真实舵机控制能力，同时保留 dry-run 检查模式。

核心能力：

- 读取真实舵机 `Present_Position` raw。
- 把 raw 转换成上层逻辑角度。
- 把逻辑角度转换成舵机 `Goal_Position` raw。
- 区分单圈和多圈关节。
- 支持夹爪预留 ID 16。
- 支持安全检查、急停和保持当前位置。
- 默认 `dry_run: true`，不真实写入舵机。

## 2. 和阶段三的关系

阶段三只保存仿真状态：`关节角度` 和 `夹爪`。

阶段四新增真实控制器，但姿态数组顺序仍然固定为：

```text
j10, j11, j12, j13, j14, j15
J10_底盘导轨, J11_底座旋转, J12_肩部抬升, J13_肘部弯曲, J14_腕部俯仰, J15_腕部旋转
```

`真实主程序_main.py` 会复用阶段三的：

- `姿态管理_pose_manager.py`
- `动作播放器_action_player.py`
- `姿态库.json`
- `动作库/*.json`

## 3. 仿真模式、dry-run、真实模式

仿真模式：阶段三系统，只改电脑里的角度状态，不知道真实舵机 raw。

dry-run：阶段四默认模式，会执行真实映射和安全检查，但不访问真实硬件，不写舵机。程序会打印如果是真实模式将写入的 `goal_raw`。

真实模式：`dry_run: false` 后使用 `lerobot.motors.feetech.FeetechMotorsBus` 连接真实 STS3215 舵机并写入 `Goal_Position`。

真实硬件依赖请安装到专用 mamba 环境，避免污染系统 Python：

```bash
mamba create -n momo_rebot python=3.11 -y
mamba activate momo_rebot
python -m pip install lerobot feetech-servo-sdk pyserial pyyaml
```

dry-run 主程序不需要这些依赖。标定程序和真实控制需要这些依赖。

## 4. 为什么真实控制需要标定

真实舵机只知道 raw 位置，不知道“底座旋转 0 度”是什么意思。标定文件记录每个关节的舵机 ID、零点、方向、限位和多圈 home raw。

没有标定，程序不能知道：

- 哪个舵机对应哪个关节。
- 逻辑 0 度对应哪个 raw。
- 角度增加时 raw 应该增加还是减少。
- 单圈关节能安全移动到哪些 raw 范围。
- 多圈关节的 signed absolute raw 参考点在哪里。

安全原则：没有完整标定，不允许真实移动。

`connect()` 只读取被忽略的 `标定/current.local.json`，不会重新标定，不会要求用户
移动机械臂，也不会覆盖 `home_present_raw / zero_present_raw`。仓库中的
`标定/v1.example.json` 和 `标定/v2.example.json` 只是结构模板，绝不能用于真机。

标定必须在 `_meta.robot_variant` 携带准确型号。只有该字段与当前型号完全匹配的
标定才能进入真机路径；字段缺失、未知值或型号不匹配时，只允许仿真或 `dry_run` 预览。

## 5. 什么是 raw 值

raw 是舵机内部位置计数值。SOARM MOCE 使用的 STS3215 舵机一圈为：

```text
4096 raw = 360 度
```

单圈 raw 范围是 `0-4095`。多圈模式下使用 signed absolute raw，安全范围默认是：

```text
-30719 到 30719
```

## 6. 什么是逻辑角度

逻辑角度是上层控制使用的关节角度，单位是度。例如：

```text
移动 0 0 20 30 10 0
```

表示按固定顺序移动：

```text
J10=0mm, J11=0deg, J12=20deg, J13=30deg, J14=10deg, J15=0deg
```

逻辑角度到 raw 必须使用 SOARM MOCE 的 joint_scales：

```text
j11: 5.0
j12: -28.0
j13: 14.0
j14: 1.0
j15: 1.0
```

公式：

```text
motor_deg = joint_deg * joint_scale
relative_raw = motor_deg / 360.0 * 4096
```

## 7. 什么是多圈模式

多圈模式允许舵机位置超过单圈 `0-4095`。目标 raw 不做 4096 取模，而是：

```text
goal_raw = home_present_raw + relative_raw
```

并检查是否在 `-30719 到 30719`。

V2 还把 J12/J13 声明为 `raw_reachable_joints`。它们的有效逻辑范围根据当前 Home、
传动映射和绝对 raw 上限 `±30719` 动态计算；静态关节配置不能放宽该范围，调用方也
不得绕过。

## 8. 为什么 J10-J15 要特殊处理

SOARM MOCE 中固定多圈关节是：

```text
J10 j10 = 底盘导轨
J11 j11 = 底座旋转，1:5 行星减速
J12 j12 = 肩部抬升
J13 j13 = 肘部弯曲
J14 j14 = 腕部俯仰，直连 1:1
J15 j15 = 腕部旋转
```

它们不能按单圈 `raw % 4096` 处理。否则机械臂可能选择错误的一圈，真实移动方向和距离会不符合预期。

夹爪如果接入，仍然按单圈范围处理。

## 9. 启动步骤

### 配置与型号

默认型号是 V2。`配置/robot_v1.yaml` 对应 V1，`配置/robot_v2.yaml` 对应 V2。
配置按以下顺序加载：

1. 受版本控制的 `真实配置.yaml`
2. 被 Git 忽略的 `真实配置.local.yaml`
3. 由合并后 `robot.variant` 选中的权威型号 profile
4. 运行参数环境变量

默认 V2 由受控基线选择。临时选择 V1/V2 时，在被忽略的 `真实配置.local.yaml`
设置 `robot.variant`；环境变量不提供型号选择，只能通过 `ARM_ROBOT_PORT`、
`ARM_SERVO_BACKEND` 和 `ARM_REAL_DRY_RUN` 覆盖运行参数。受控默认保持
`transport.port: ""` 和 `dry_run: true`。profile 中的关节、传动、限位和 raw 可达
关节等硬件字段具有更高优先级，不能被本地文件覆盖。

```bash
cd <repository-root>/真实舵机控制
python 真实主程序_main.py
```

启动后建议先执行：

```text
帮助
标定状态
连接
状态
移动 0 0 10 10 0 0
移动单关节 2 2
微调 2 1
微调 2 -1
夹爪 50
急停
断开
退出
```

默认 `dry_run: true`，不会真实写入舵机。

命令区别：

- `移动单关节 1 5` 是绝对目标，表示第 1 个关节 `j10/J10` 导轨移动到 5 mm。
- `微调 2 1` 是相对目标，表示第 2 个关节 `j11/J11` 在当前角度基础上增加 1 度。
- `微调 2 -1` 是相对目标，表示第 2 个关节 `j11/J11` 在当前角度基础上减少 1 度。

连续小步测试真实舵机时建议使用 `微调`，不要重复输入同一个绝对角度。

如果要真实连接硬件，请先进入专用环境：

```bash
mamba activate momo_rebot
cd 机械臂/真实舵机控制
python 真实主程序_main.py
```

## 10. 安全检查清单

关闭 dry-run 前必须确认：

- 串口 `transport.port` 正确。
- 舵机 ID：J10-J15 为 10-15，夹爪预留为 16。
- 标定文件中的零点正确。
- 单圈关节 `range_min/range_max` 正确。
- 多圈关节 `home_present_raw` 正确。
- `joint_scales` 没有改错，特别是 `j12=-28.0`、`j13=14.0`；J14 的反向保留在标定 `direction=-1`。
- 机械臂周围没有人和障碍物。
- 电源稳定，随时可以断电。

## 11. 第一次真机测试流程

1. 确认机械臂断开负载或处于安全位置
2. 确认电源稳定
3. 确认串口正确
4. 保持 `dry_run: true`
5. 运行读取状态脚本
6. 运行多圈映射检查
7. 运行单关节 dry-run 小幅移动
8. 确认 `goal_raw` 合理
9. 再考虑关闭 dry-run
10. 每次只测试一个关节
11. 角度不超过 2-5 度
12. 随时准备断电

测试脚本：

```bash
python 测试脚本_test/01_读取舵机状态.py
python 测试脚本_test/03_多圈关节映射检查.py
python 测试脚本_test/02_单关节小幅移动.py
python 测试脚本_test/04_dry_run移动测试.py
```

## 12. 真实依赖、标定程序和应用标定

详细依赖说明见：

- `依赖安装说明.md`
- `标定说明.md`

关系说明：

```text
lerobot / feetech-servo-sdk
= 用来和飞特 Feetech 舵机通信的驱动库

标定程序_calibrate.py
= 经现场批准后使用驱动库连接舵机，并生成本地标定

真实控制器
= 每次连接时读取 标定/current.local.json，然后控制机械臂
```

以下标定和寄存器命令会接触真实硬件，只有在 `docs/V2真机验收.md` 对应阶段获得
单独明确批准后才可执行；本轮文档更新没有执行它们。先用 `--dry-run` 验证参数：

```bash
mamba activate momo_rebot
cd <repository-root>/真实舵机控制
python 标定程序_calibrate.py --dry-run
```

已批准真实阶段中的输出路径必须是被忽略的本地文件：

```bash
python 标定程序_calibrate.py --output 标定/current.local.json
```

`标定应用_apply_calibration.py` 会写舵机寄存器，也必须单独批准。它只应用已有标定，
不重新读取 Home，不重新计算零点或范围，也不修改标定文件。

## 13. 标定文件说明

`标定/current.local.json` 是当前机械臂的实际标定文件，默认被 Git 忽略。

重要说明：

- example 文件仅说明结构，不包含可用于真机的现场事实。
- 每台机械臂必须建立自己的本地标定。
- 真机移动前仍然要确认自己的机械臂零点、方向、限位。
- `dry_run: true` 时不会真的写舵机。
- 把 `dry_run` 改成 `false` 前，必须确认串口、ID、零点、方向、限位都正确。
- 新标定程序生成的文件会包含 `_meta`，记录 bounded single-turn 和 absolute raw 关节说明。

真实零点来自标定文件：

- 单圈：`zero_present_raw`
- 多圈：`home_present_raw`

不要把 `sim_joint_offsets_deg` 或模型显示 offset 当成真实舵机零点。

## 14. 多圈和单圈标定逻辑

多圈关节 J10-J15：

```text
j10, j11, j12, j13, j14, j15
```

标定程序会使用：

```text
Operating_Mode = 0
Homing_Offset = 0
Phase = 28
Min_Position_Limit = 0
Max_Position_Limit = 0
```

并把当前 `Present_Position` 作为 `home_present_raw`。多圈目标 raw 后续不做 4096 包裹。

单圈关节：夹爪：

```text
gripper
```

J11 为 1:5，J12 为 -1:28，J13 为 1:14，J14/J15 为直连 1:1。旧标定不能
通过手工改型号继续使用；只允许在仿真或 `dry_run` 中预览，再按现场审批流程重新标定。

夹爪单圈标定才会使用 `zero_present_raw / range_min / range_max`。

## 15. 常见错误说明

`尚未连接。请先输入：连接`：移动前必须先连接驱动。dry-run 也需要连接 Mock 驱动。

`标定不完整，禁止真实移动`：关闭 dry-run 后，标定字段缺失或模式不对时会禁止移动。

`角度超出范围`：目标逻辑角度超过 `真实配置.yaml` 中的关节范围。

`单圈目标 raw 超出标定范围`：夹爪目标 raw 超过 `range_min/range_max`。

`多圈目标 raw 超出 signed absolute raw 安全范围`：J10-J15 目标 raw 超过 `-30719 到 30719`。

`真实模式需要安装 lerobot 和 feetech-servo-sdk`：默认 dry-run 不需要这两个依赖；真实连接硬件时需要在 `momo_rebot` 环境中安装。

`缺少标定文件或标定不完整`：真实模式 connect 前会检查
`标定/current.local.json` 的完整性和型号；dry-run 可以继续做映射检查。
