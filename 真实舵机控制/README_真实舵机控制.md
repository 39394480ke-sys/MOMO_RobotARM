# 阶段四：真实舵机控制系统

本目录是在阶段三“仿真控制系统”基础上扩展出来的真实舵机控制层。阶段三没有被重写，姿态库和动作库仍然放在 `../仿真控制系统/姿态管理/`，阶段四通过统一接口复用它们。

## 1. 阶段四目标

阶段四增加真实舵机控制能力，同时保留 dry-run 检查模式。

核心能力：

- 读取真实舵机 `Present_Position` raw。
- 把 raw 转换成上层逻辑角度。
- 把逻辑角度转换成舵机 `Goal_Position` raw。
- 区分单圈和多圈关节。
- 支持夹爪 ID 6。
- 支持安全检查、急停和保持当前位置。
- 默认 `dry_run: true`，不真实写入舵机。

## 2. 和阶段三的关系

阶段三只保存仿真状态：`关节角度` 和 `夹爪`。

阶段四新增真实控制器，但姿态数组顺序仍然固定为：

```text
shoulder_pan, shoulder_lift, elbow_flex, wrist_flex, wrist_roll
J1_底座旋转, J2_肩部抬升, J3_肘部弯曲, J4_腕部俯仰, J5_腕部旋转
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
mamba create -n arm_rebot python=3.11 -y
mamba activate arm_rebot
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

`connect()` 每次只读取 `标定文件.json`，不会重新标定，不会要求用户移动机械臂，也不会覆盖 `home_present_raw / zero_present_raw`。如果零点不对，请退出主程序后运行 `标定程序_calibrate.py`。

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
移动 0 20 30 10 0
```

表示按固定顺序移动：

```text
J1=0, J2=20, J3=30, J4=10, J5=0
```

逻辑角度到 raw 必须使用 SOARM MOCE 的 joint_scales：

```text
shoulder_pan: 1.0
shoulder_lift: -5.3
elbow_flex: 5.6
wrist_flex: -1.0
wrist_roll: 1.0
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

## 8. 为什么 J2/J3/J5 要特殊处理

SOARM MOCE 中固定多圈关节是：

```text
J2 shoulder_lift = 肩部抬升
J3 elbow_flex = 肘部弯曲
J5 wrist_roll = 腕部旋转
```

它们不能按单圈 `raw % 4096` 处理。否则机械臂可能选择错误的一圈，真实移动方向和距离会不符合预期。

单圈关节固定为：

```text
J1 shoulder_pan = 底座旋转
J4 wrist_flex = 腕部俯仰
```

## 9. 启动步骤

```bash
cd 机械臂/真实舵机控制
python 真实主程序_main.py
```

启动后建议先执行：

```text
帮助
标定状态
连接
状态
移动 0 10 10 0 0
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

- `移动单关节 1 1` 是绝对角度，表示 J1 移动到 1 度。
- `微调 1 1` 是相对角度，表示 J1 在当前角度基础上增加 1 度。
- `微调 1 -1` 是相对角度，表示 J1 在当前角度基础上减少 1 度。

连续小步测试真实舵机时建议使用 `微调`，不要重复输入同一个绝对角度。

如果要真实连接硬件，请先进入专用环境：

```bash
mamba activate arm_rebot
cd 机械臂/真实舵机控制
python 真实主程序_main.py
```

## 10. 安全检查清单

关闭 dry-run 前必须确认：

- 串口 `transport.port` 正确。
- 舵机 ID：J1-J5 为 1-5，夹爪为 6。
- 标定文件中的零点正确。
- 单圈关节 `range_min/range_max` 正确。
- 多圈关节 `home_present_raw` 正确。
- `joint_scales` 没有改错，特别是 `shoulder_lift=-5.3` 和 `wrist_flex=-1.0`。
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
= 使用这些驱动库连接舵机，读取/写入寄存器，生成 标定文件.json

真实控制器
= 每次连接时读取 标定文件.json，然后控制机械臂
```

重新标定：

```bash
mamba activate arm_rebot
cd 机械臂/真实舵机控制
python 标定程序_calibrate.py
```

常用参数：

```bash
python 标定程序_calibrate.py --dry-run
python 标定程序_calibrate.py --apply-registers
python 标定程序_calibrate.py --output 标定文件.json
python 标定程序_calibrate.py --port /dev/tty.usbmodemXXXX
```

只应用已有标定，不重新生成标定文件：

```bash
mamba activate arm_rebot
cd 机械臂/真实舵机控制
python 标定应用_apply_calibration.py
python 标定应用_apply_calibration.py --port /dev/tty.usbmodemXXXX
python 标定应用_apply_calibration.py --calibration 标定文件.json
```

`标定应用_apply_calibration.py` 只把已有标定文件中的寄存器配置写入舵机，不重新读取 `home_present_raw`，不重新计算 `zero_present_raw`，不重新记录 `range_min/range_max`，不修改标定文件内容。

## 13. 标定文件说明

`标定文件.json` 是当前机械臂标定文件的初始模板。

重要说明：

- 这些值来自当前硬件标定记录。
- 不保证适合每一台机械臂。
- 真机移动前仍然要确认自己的机械臂零点、方向、限位。
- `dry_run: true` 时不会真的写舵机。
- 把 `dry_run` 改成 `false` 前，必须确认串口、ID、零点、方向、限位都正确。
- 新标定程序生成的文件会包含 `_meta`，记录 bounded single-turn 和 absolute raw 关节说明。

真实零点来自标定文件：

- 单圈：`zero_present_raw`
- 多圈：`home_present_raw`

不要把 `sim_joint_offsets_deg` 或模型显示 offset 当成真实舵机零点。

## 14. 多圈和单圈标定逻辑

多圈关节 J2/J3/J5：

```text
shoulder_lift, elbow_flex, wrist_roll
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

单圈关节 J1/J4/夹爪：

```text
shoulder_pan, wrist_flex, gripper
```

标定程序优先复用已有完整单圈标定。用户输入 `c` 才重新记录 `zero_present_raw / range_min / range_max`。

## 15. 常见错误说明

`尚未连接。请先输入：连接`：移动前必须先连接驱动。dry-run 也需要连接 Mock 驱动。

`标定不完整，禁止真实移动`：关闭 dry-run 后，标定字段缺失或模式不对时会禁止移动。

`角度超出范围`：目标逻辑角度超过 `真实配置.yaml` 中的关节范围。

`单圈目标 raw 超出标定范围`：J1/J4 或夹爪目标 raw 超过 `range_min/range_max`。

`多圈目标 raw 超出 signed absolute raw 安全范围`：J2/J3/J5 目标 raw 超过 `-30719 到 30719`。

`真实模式需要安装 lerobot 和 feetech-servo-sdk`：默认 dry-run 不需要这两个依赖；真实连接硬件时需要在 `arm_rebot` 环境中安装。

`缺少标定文件或标定不完整，请先运行 标定程序_calibrate.py`：真实模式 connect 前会检查标定完整性；dry-run 可以继续做映射检查。
