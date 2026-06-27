# 阶段八：Web 控制台 / Quick Control API

阶段八把前面阶段的能力统一成一个本地 FastAPI 服务和浏览器控制台。后续 GUI、视觉 Agent、语音 Agent、脚本都应该走同一个 HTTP API，避免多个模块同时抢占机械臂硬件。

## Web 控制台和 GUI 的区别

GUI 是本机图形程序，适合桌面直接操作。Web 控制台是本地 HTTP 服务，浏览器、脚本和后续 Agent 都可以访问同一套接口。

Web 前端不直接访问舵机。所有请求都先进入 FastAPI，再经过 `WebControlService`、`ControllerBridge`，最后调用阶段三/四/五/六已有控制器。

## 安装依赖

基础依赖：

```bash
pip install fastapi uvicorn pydantic pyyaml
```

可选依赖：

```bash
pip install numpy
```

真实硬件依赖仍属于阶段四：

```bash
pip install lerobot feetech-servo-sdk pyserial
```

dry-run 不需要 `lerobot`。只有切到真实模式并连接硬件时，才会检查真实硬件依赖。

## 启动服务

```bash
cd 机械臂/Web控制台
python 启动Web服务.py --host 127.0.0.1 --port 8010
```

也可以：

```bash
python 启动Web服务.py
python 启动Web服务.py --host 0.0.0.0 --port 8010
```

打开：

```text
http://127.0.0.1:8010/web/
```

默认模式是 `dry_run`，启动服务不会自动连接真实硬件。

## 模式说明

- `sim`：阶段三仿真模型，只更新电脑里的关节状态。
- `dry_run`：阶段四真实控制器的 Mock 驱动，会走标定、角度映射和安全检查，但不会写真实舵机。
- `real`：真实 Feetech / LeRobot 舵机控制。连接和危险动作必须输入安全确认：`我确认机械臂周围安全`。

## API 列表

基础：

```text
GET  /api/v1/health
GET  /api/v1/config
```

会话：

```text
GET  /api/v1/session/status
POST /api/v1/session/connect
POST /api/v1/session/disconnect
POST /api/v1/session/mode
```

机器人状态：

```text
GET /api/v1/robot/state
GET /api/v1/robot/calibration-status
GET /api/v1/robot/dependencies
GET /api/v1/robot/hardware-check
GET /api/v1/robot/joint-diagnostics?joint_key=j12
POST /api/v1/robot/calibration/current-angle
```

运动控制：

```text
POST /api/v1/motion/joint-step
GET  /api/v1/motion/tuning
POST /api/v1/motion/tuning
POST /api/v1/motion/tuning/reset
GET  /api/v1/motion/continuous-jog/status
POST /api/v1/motion/continuous-jog/start
POST /api/v1/motion/continuous-jog/stop
POST /api/v1/motion/move-joints
POST /api/v1/motion/cartesian-jog
POST /api/v1/motion/move-pose
POST /api/v1/motion/home
POST /api/v1/motion/stop
POST /api/v1/motion/gripper
```

姿态和动作：

```text
GET    /api/v1/poses
POST   /api/v1/poses/save
POST   /api/v1/poses/goto
DELETE /api/v1/poses/{name}

GET  /api/v1/actions
GET  /api/v1/actions/{name}
POST /api/v1/actions/play
POST /api/v1/actions/pause
POST /api/v1/actions/resume
POST /api/v1/actions/stop
```

WebSocket：

```text
WS /api/v1/ws/state
```

视觉跟随：

```text
GET  /api/v1/follow/status
POST /api/v1/follow/start
POST /api/v1/follow/stop
GET  /api/v1/vision/health
GET  /api/v1/vision/latest
GET  /api/v1/vision/frame.jpg
```

“视觉跟随”页的画面预览走 Web 后端代理 `/api/v1/vision/frame.jpg`，前端不再直接访问 `127.0.0.1:8000`。预览只读，不会向机械臂发送动作。

## WebSocket 状态推送

客户端连接后立即收到一次状态，之后约每 500ms 收到：

```json
{
  "type": "state",
  "timestamp": 1234567890.0,
  "data": {
    "session": {},
    "robot": {},
    "action": {},
    "error": null
  }
}
```

## 常用控制

关节微调：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/motion/joint-step \
  -H "Content-Type: application/json" \
  -d '{"joint_key":"j11","delta_deg":2,"speed_percent":50}'
```

夹爪：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/motion/gripper \
  -H "Content-Type: application/json" \
  -d '{"open_ratio":1.0}'
```

播放动作：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/actions/play \
  -H "Content-Type: application/json" \
  -d '{"name":"挥手_增强","speed":1.0,"loop":false}'
```

查看标定：

```bash
curl http://127.0.0.1:8010/api/v1/robot/calibration-status
```

J12 只读诊断：

```bash
curl 'http://127.0.0.1:8010/api/v1/robot/joint-diagnostics?joint_key=j12'
```

把 J12 当前真实姿态标记为指定逻辑角度，例如当前物理姿态应为 `30°`：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/robot/calibration/current-angle \
  -H "Content-Type: application/json" \
  -d '{"joint_key":"j12","current_angle_deg":30,"confirm_text":"我确认机械臂周围安全"}'
```

同等 CLI：

```bash
cd ~/MOMO_RobotARM
source ~/miniforge3/etc/profile.d/conda.sh
conda activate momo_rebot
python 真实舵机控制/标定当前角度_calibrate_current_angle.py \
  --port /dev/momo-servo \
  --joint-angle j12=30
```

一次修多个多圈关节：

```bash
python 真实舵机控制/标定当前角度_calibrate_current_angle.py \
  --port /dev/momo-servo \
  --joint-angle j10=0 \
  --joint-angle j11=0 \
  --joint-angle j12=30 \
  --joint-angle j13=-15 \
  --joint-angle j14=0 \
  --joint-angle j15=0
```

真实硬件只读检查：

```bash
curl http://127.0.0.1:8010/api/v1/robot/hardware-check
```

## 真实模式安全流程

1. 确认机械臂周围没有人、线缆、工具和易碰撞物。
2. 在设置页点击“真实硬件检查”，确认 `/dev/momo-servo`、CH343、依赖、标定和 ID `10-15` 都通过。
3. 在设置页选择 `真实` 并点击连接。
4. 输入：`我确认机械臂周围安全`。
5. J12 标定修正前不测试 J12；其余已验证关节可以按设置页限位做 `1°-3°` 单关节测试。
6. Home、动作库、多关节动作和视觉真实跟随仍放到单关节全部确认之后。

API 不接受 raw 舵机值，也不提供任意 Python 执行接口。真实动作都必须通过阶段四控制器的标定和安全检查。

## 常见错误

- 端口被占用：换端口启动，例如 `--port 8011`。
- FastAPI 未安装：在 `momo_rebot` 环境执行 `pip install fastapi uvicorn pydantic pyyaml`。
- 真实依赖缺失：ARM 开发板默认使用轻量 SDK，确认 `feetech-servo-sdk`、`pyserial`、`scservo_sdk` 可导入。
- 标定文件缺失：先运行阶段四标定程序。
- 串口错误：开发板检查 `.env` 里的 `ARM_ROBOT_PORT=/dev/momo-servo`。
- CH343 未加载：运行 `bash scripts/setup_qinheng_55d3_serial.sh`，并拔插控制板 USB。
- WebSocket 断开：前端会自动重连；也可以刷新页面。
- CORS 问题：默认前端和 API 同源访问 `http://127.0.0.1:8010/web/`，不要直接双击打开 HTML。
