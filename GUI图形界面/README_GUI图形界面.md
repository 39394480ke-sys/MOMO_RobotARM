# 阶段七：GUI 图形界面控制台

本阶段新增一个桌面 GUI，目标是把前面阶段的连接、状态、关节控制、姿态、动作、运动学、标定和日志组织成一个面向真实硬件调试的操作台。

GUI 不是新的控制内核。它只调用 `ControllerBridge`，再由桥接层调用阶段三仿真控制器、阶段四真实控制器、阶段五运动学控制器和阶段六动作回放器。

## 为什么 GUI 不能直接控制舵机

真实舵机控制已经在阶段四里实现了 dry-run、标定、安全检查、角度到 raw 映射、多圈关节处理和 Feetech/LeRobot 驱动。GUI 如果直接写舵机，会绕过这些安全逻辑，容易把错误角度、错误零点或错误多圈状态写到硬件上。

所以阶段七遵守一条规则：GUI 只做操作台，所有真实硬件动作仍然通过阶段四真实控制器执行。

## 三种模式

- 仿真模式：只使用阶段三电脑里的机械臂模型，不连接真实硬件。
- dry-run 模式：使用阶段四真实控制器的 dry-run 驱动，默认模式，不真实写舵机。
- 真实模式：连接真实硬件。切换、连接、移动、播放动作和执行 IK 前都要输入安全确认文本。

安全确认文本：

```text
我确认机械臂周围安全
```

## 安装依赖

本项目统一使用 `arm_rebot` 环境里的 Python：

```bash
mamba run -n arm_rebot python -V
```

当前推荐先检查依赖：

```bash
mamba run -n arm_rebot python - <<'PY'
for name in ["PyQt5", "pybullet", "yaml", "numpy"]:
    try:
        __import__(name)
        print(name, "OK")
    except Exception as exc:
        print(name, "MISSING", exc)
PY
```

如果 `PyQt5` 缺失，请安装：

```bash
mamba install -n arm_rebot pyqt
```

如果 mamba 源里没有合适包，可改用：

```bash
mamba run -n arm_rebot python -m pip install PyQt5
```

`pybullet` 在 `arm_rebot` 环境中可用时，阶段五 FK/IK 和 3D 视图能力会正常启用。`lerobot` 缺失时，dry-run 可以继续；真实模式可能不可用。

## 启动 GUI

在本项目根目录下运行：

```bash
cd GUI图形界面
mamba run -n arm_rebot python GUI主程序_main.py
```

启动后默认是 dry-run，不会自动连接真实硬件。

## 设置页面

设置页负责模式、串口、配置路径和连接管理。

常用按钮：

- 连接：按当前模式创建控制器并连接。
- 断开：断开当前控制器。
- 刷新状态：读取当前控制器状态。
- 检查依赖：检查 PyQt5、pyyaml、numpy、pybullet、lerobot。
- 检查标定：读取阶段四标定文件并显示完整性。

真实模式必须二次确认，否则不能进入或连接。

## 快速控制页面

快速控制页对应 快速移动逻辑。

页面包含：

- J1 底座旋转
- J2 肩部抬升
- J3 肘部弯曲
- J4 腕部俯仰
- J5 腕部旋转
- 关节步长 0.5 / 1 / 2 / 5 度
- 夹爪滑条、张开夹爪、闭合夹爪
- Home、刷新状态、急停
- TCP 末端位姿
- 3D 仿真视图占位或 PyBullet 状态显示

点击 `+` 或 `-` 会调用：

```python
bridge.move_joint_delta(joint_key, delta_deg)
```

真实模式下最大步长默认限制为 2 度。

## 姿态页面

姿态页读取阶段三姿态库：

```text
../仿真控制系统/姿态管理/姿态库.json
```

支持：

- 刷新姿态列表
- 保存当前姿态
- 前往选中姿态
- 删除选中姿态
- 查看姿态详情

真实模式前往姿态需要安全确认。dry-run 只执行 dry-run 控制器流程。

## 动作页面

动作页集成阶段六动作库：

```text
../动作录制与回放增强/动作库
```

支持：

- 显示动作列表
- 显示 pose_count、gripper、tcp_pose、multi_turn_state 摘要
- 播放、暂停、继续、停止
- 删除动作
- 显示录制/示教提示

第一版 GUI 不直接启动录制和示教程序，仍建议使用阶段六脚本录制动作。

## 运动学页面

运动学页集成阶段五：

- 输入 5 个关节角度计算 FK。
- 输入 x/y/z 和可选 rpy 计算 IK。
- IK 结果先显示，不自动执行。
- 点击“执行 IK 结果”才会调用 `bridge.move_joints()`。
- 支持 base/tool 末端增量移动。

真实模式执行 IK 或末端移动必须安全确认。

## 标定页面

标定页读取阶段四标定文件，显示：

- 标定文件路径
- 文件是否存在
- 是否允许真实移动
- 每个关节的 id、模式、zero/home raw、range、phase

第一版 GUI 不直接运行标定程序，只提示命令：

```bash
mamba run -n arm_rebot python ../真实舵机控制/标定程序_calibrate.py
mamba run -n arm_rebot python ../真实舵机控制/标定应用_apply_calibration.py
```

## 日志页面

GUI 日志使用 JSONL 格式：

```text
GUI图形界面/运行日志/gui_runtime.log
```

日志页可以刷新日志、清空视图、显示日志文件路径。清空视图不会删除日志文件。

## 常见错误

### PyQt5 未安装

现象：GUI 无法启动。

处理：

```bash
mamba install -n arm_rebot pyqt
```

如果 mamba 安装不成功：

```bash
mamba run -n arm_rebot python -m pip install PyQt5
```

### pybullet 未安装

现象：3D 仿真视图显示“PyBullet 未安装”，FK/IK 不可用。

处理：

```bash
mamba install -n arm_rebot pybullet
```

不安装 pybullet 不会影响 GUI 主窗口启动。

### lerobot 未安装

dry-run 可以继续。真实模式如果阶段四驱动依赖 lerobot，则不能连接真实硬件。

### 标定文件缺失

真实模式不允许移动。请先运行阶段四标定程序。

### 串口错误

检查设置页串口，确认设备路径正确，例如：

```text
/dev/tty.usbmodem5B141127021
```

### GUI 卡住

真实连接、移动和动作播放已经通过后台线程执行。若仍卡住，通常是底层驱动或系统串口调用长时间不返回，需要先用阶段四测试脚本排查。

### 真实模式无法启用

常见原因：

- 未输入正确安全确认文本。
- 标定文件不完整。
- lerobot 或 Feetech 驱动依赖缺失。
- 串口错误或硬件未上电。
