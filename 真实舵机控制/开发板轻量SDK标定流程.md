# 开发板轻量 SDK 标定流程

本文档用于 Ubuntu ARM64 开发板路线。开发板默认使用轻量 `scservo_sdk / feetech-servo-sdk` 标定工具，不依赖 `lerobot`、`torch`，也不污染系统 Python。

## 基本原则

- 系统 Python 不跑项目；进入 `momo_rebot` 环境后再执行命令。
- 标定工具只读取 `Present_Position` 并更新 `标定文件.json`。
- 当前角度标定不写 `Goal_Position`，不移动舵机。
- 断电重接不会自动把当前姿态当零位；只有你明确运行标定工具时，才会更新逻辑角度与 raw 的对应关系。

## 环境准备

```bash
cd ~/MOMO_RobotARM
source ~/miniforge3/etc/profile.d/conda.sh
conda activate momo_rebot
```

确认串口和总线只读可见：

```bash
python 真实舵机控制/诊断舵机总线_lightweight_sdk.py \
  --port /dev/momo-servo \
  --no-gripper
```

成功时应读到 ID `10-15` 的 `Present_Position`。

## 推荐：批量当前角度标定

当机械臂已经摆在一个你知道逻辑角度的姿态时，使用批量工具一次修多个关节：

```bash
python 真实舵机控制/标定当前角度_calibrate_current_angle.py \
  --port /dev/momo-servo \
  --joint-angle j12=30 \
  --joint-angle j13=-15 \
  --joint-angle j14=0
```

含义是：

- 读取每个关节当前 `Present_Position`。
- 你告诉程序“当前物理姿态应该是多少逻辑角度”。
- 程序反算并更新对应关节的 `home_present_raw`。
- 保存前自动备份旧 `标定文件.json`。

例如 J12 当前实际应该是 `30°`，不是把 J12 强行设为 `0°`：

```bash
python 真实舵机控制/标定当前角度_calibrate_current_angle.py \
  --port /dev/momo-servo \
  --joint-angle j12=30
```

## 兼容：单关节当前角度标定

旧参数仍可用：

```bash
python 真实舵机控制/标定当前角度_calibrate_current_angle.py \
  --port /dev/momo-servo \
  --joint j12 \
  --angle 30
```

## Web 标定页

Web 控制台也走同一条轻量 SDK 逻辑：

- 单关节接口：`POST /api/v1/robot/calibration/current-angle`
- 批量接口：`POST /api/v1/robot/calibration/current-angles`

Web 页面默认仍保持 dry-run；写真实标定文件时需要安全确认文本。

## 不推荐在开发板优先使用的旧流程

`标定程序_calibrate.py` 是完整标定脚本，历史上依赖真实舵机后端和 `lerobot`。ARM 开发板上不优先使用它作为第一路线。

开发板优先顺序：

1. 只读总线诊断。
2. 轻量 SDK 当前角度标定。
3. Web 标定页批量修正。
4. J12 等越界关节修正后再做真实动作测试。

