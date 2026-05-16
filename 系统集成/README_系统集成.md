# 阶段十一：系统集成 / 一键启动 / 统一运行时

阶段十一把前面独立能跑的模块组合成一个稳定系统：统一配置、统一启动、统一停止、统一健康检查、统一日志、统一状态文件，以及真实硬件模式的安全入口。

## 为什么需要系统集成

前面阶段分别实现了仿真控制、真实舵机控制、URDF/运动学、动作录制回放、GUI、Web API、视觉识别与跟随、语音 Agent。单独运行时每个模块都能完成自己的职责，但完整 MomoAgent 式系统需要一个统一运行时来决定启动顺序、服务归属、日志位置、故障定位和硬件安全策略。

## 各阶段关系

- 阶段三提供仿真控制。
- 阶段四提供真实舵机控制和标定。
- 阶段五提供 URDF、FK/IK 和 3D 仿真。
- 阶段六提供动作录制与回放。
- 阶段七提供 GUI。
- 阶段八 Web API 是统一机械臂控制入口。
- 阶段九视觉服务只提供识别结果，跟随控制通过 Web API 发指令。
- 阶段十语音 Agent 通过 Web API 调用机械臂工具。
- 阶段十一负责启动、停止、检查、日志和状态总览。

真实硬件只能有一个控制入口：阶段八 Web API。GUI、视觉和语音 Agent 都不应该直接连接 Feetech 舵机，否则会出现多个进程同时写串口、状态不同步、急停失效或动作互相覆盖的问题。

## 运行模式

- `sim`：仿真模式，不连接真实舵机。
- `dry_run`：真实参数 dry-run，走真实控制链路但不写舵机，默认模式。
- `real`：真实硬件模式，会写入 Feetech 舵机。

真实模式必须通过安全流程：检查 `lerobot`、`feetech-servo-sdk`、`pyserial`，检查串口，检查标定文件，检查 Web API 已启动，检查没有其他硬件会话，并输入确认文本：

```bash
我确认机械臂周围安全
```

## 安装依赖

统一使用 `momo_rebot` 环境里的 Python，不使用 `python3`：

```bash
cd 系统集成
bash scripts/bootstrap.sh
```

可选高级依赖：

```bash
bash scripts/bootstrap.sh --advanced
```

真实硬件依赖：

```bash
bash scripts/bootstrap.sh --real
```

## 一键启动

默认 dry-run：

```bash
mamba run -n momo_rebot python 一键启动.py
```

指定模式：

```bash
mamba run -n momo_rebot python 一键启动.py --mode dry_run
mamba run -n momo_rebot python 一键启动.py --mode sim
mamba run -n momo_rebot python 一键启动.py --mode real
```

可选组件：

```bash
mamba run -n momo_rebot python 一键启动.py --with-gui
mamba run -n momo_rebot python 一键启动.py --with-agent
mamba run -n momo_rebot python 一键启动.py --no-vision
```

启动成功后会打印：

```text
Web 控制台：http://127.0.0.1:8010/web/
视觉服务：http://127.0.0.1:8000/latest
当前模式：dry_run
```

也可以运行：

```bash
bash scripts/run_all.sh
```

## 一键停止

```bash
mamba run -n momo_rebot python 一键停止.py
bash scripts/stop_all.sh
```

停止流程会读取 `runtime/pids/*.pid`，先 `terminate`，超时后 `kill`，然后清理 pid 文件并更新 `runtime/state/system_state.json`。

## 查看状态

```bash
mamba run -n momo_rebot python 系统状态.py
```

输出当前模式、服务运行状态、Web/Vision health、标定状态、依赖状态、Web 地址和最近错误。

## 健康检查

```bash
mamba run -n momo_rebot python 健康检查.py
```

健康检查覆盖 Web API health、Vision health、Web session status、Web robot state、Vision latest、Agent 配置、GUI 配置和标定状态。服务未启动时会返回失败 JSON，但程序不会崩溃。

## 查看日志

```bash
mamba run -n momo_rebot python 日志查看.py
mamba run -n momo_rebot python 日志查看.py web_api --lines 200
mamba run -n momo_rebot python 日志查看.py vision --lines 200
```

系统日志使用 JSONL 格式写入 `runtime/logs/system.log`。服务日志分别写入：

- `runtime/logs/web.log`
- `runtime/logs/vision.log`
- `runtime/logs/agent.log`
- `runtime/logs/gui.log`

## 进入真实模式

```bash
mamba run -n momo_rebot python 一键启动.py --mode real
```

流程：

1. 检查 Python 版本。
2. 检查必需依赖。
3. 检查标定文件。
4. 启动 Web API。
5. 等待 Web API health。
6. 输入真实模式确认文本。
7. 检查真实依赖、串口、标定、硬件会话。
8. 通过 Web API 切换 real。
9. 启动视觉服务和可选 GUI/Agent。

## 常见错误

- 端口被占用：查看 `runtime/logs/web.log` 或 `runtime/logs/vision.log`，停止占用 8010/8000 的进程后重试。
- Web API 启动失败：运行 `python 依赖检查.py`，检查 `fastapi`、`uvicorn`、`pydantic`、`pyyaml`。
- Vision 服务启动失败：检查 `opencv-contrib-python` 和摄像头配置。
- 标定缺失：运行 `python ../真实舵机控制/标定程序_calibrate.py`。
- `lerobot` 缺失：dry-run 可用，真实硬件不可用；运行 `bash scripts/bootstrap.sh --real`。
- 串口错误：检查 `../真实舵机控制/真实配置.yaml` 中的 `transport.port`，并确认设备存在。
- pid 文件残留：运行 `python 一键停止.py`；若进程已不存在，系统会自动清理 pid。
- 多个进程抢硬件：只允许阶段八 Web API 持有真实硬件，停止其他直接连接 Feetech 舵机的脚本。

## Smoke Test

```bash
mamba run -n momo_rebot python 测试脚本_test/01_配置加载测试.py
mamba run -n momo_rebot python 测试脚本_test/02_依赖检查测试.py
mamba run -n momo_rebot python 测试脚本_test/03_健康检查测试.py
mamba run -n momo_rebot python 测试脚本_test/04_dry_run全链路测试.py
mamba run -n momo_rebot python 测试脚本_test/05_服务启动停止测试.py
```

