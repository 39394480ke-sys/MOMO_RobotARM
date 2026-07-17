# 阶段十：语音 Agent / 对话控制系统

本阶段给“我的机械臂控制项目”增加语音交互能力：用户可以说话或输入文字，Agent 理解意图后调用安全工具，再由工具桥接到阶段八 Web API 控制机械臂。

阶段十不是新的机械臂控制层。它只做人机交互、STT、Agent 对话、工具调用和 TTS 播报。

## 和阶段八 API 的关系

正确链路是：

```text
用户语音 -> 录音 -> STT -> Agent -> 安全工具 -> 阶段八 Web API -> 已有控制能力 -> TTS 回复
```

阶段十所有机械臂动作都调用阶段八接口，例如：

- `GET /api/v1/robot/state`
- `POST /api/v1/motion/stop`
- `POST /api/v1/motion/gripper`
- `POST /api/v1/motion/joint-step`
- `POST /api/v1/actions/play`
- `POST /api/v1/follow/start`

## 为什么 Agent 不能直接控制舵机

Agent 的输出可能不稳定，不能让它直接写 Feetech 舵机、raw 值或执行任意 Python 控制机械臂。阶段八已经集中处理 dry-run、真实模式确认、标定、安全步长、动作回放和视觉跟随，所以阶段十必须通过阶段八 API 间接控制。

## STT / TTS / Agent backend / 工具调用

STT 是 Speech To Text，把录音转成文字。默认配置调用 HTTP STT 服务：`http://127.0.0.1:9000/v1/audio/transcriptions`。

TTS 是 Text To Speech，把 Agent 回复转成语音播放。默认配置调用 HTTP TTS 服务：`http://127.0.0.1:9001/v1/audio/speech`。

Agent backend 是负责理解用户意图的大模型服务。第一版实现了 OpenAI-compatible HTTP 接口：`POST /v1/chat/completions`。

工具调用是 Agent 不直接动机械臂，而是请求系统提供的安全工具，例如 `get_robot_state`、`stop_robot`、`rotate_joint`。工具再调用阶段八 Web API。

## 安装依赖

项目统一使用 `momo_rebot` 环境里的 Python：

```bash
mamba run -n momo_rebot python -V
mamba run -n momo_rebot python -m pip install requests pyyaml numpy sounddevice
```

如果 `sounddevice` 安装失败，文本 `ask` 和 `shell` 仍然可用，只是录音和播放不可用。

可选：

```bash
mamba run -n momo_rebot python -m pip install openai
```

当前实现直接用 `requests` 调 OpenAI-compatible HTTP，不强制依赖 `openai` SDK。

## 启动阶段八 API

先启动阶段八 Web 控制台：

```bash
cd 机械臂/Web控制台
mamba run -n momo_rebot python 启动Web服务.py
```

默认地址是：

```text
http://127.0.0.1:8010
```

如果阶段八没启动，工具会返回：

```text
机器人控制 API 不可用，请先启动阶段八 Web 服务。
```

## 启动阶段十

进入阶段十目录：

```bash
cd 机械臂/语音Agent
```

Shell 模式：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py shell
```

文本 ask：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py ask 帮我看看当前机械臂状态
```

语音单回合：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py voice
```

listen 长驻模式：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py listen --warmup
```

只播报一句话：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py say 欢迎来到展会现场
```

warmup：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py warmup
```

reset session：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py reset-session
```

禁用 TTS：

```bash
mamba run -n momo_rebot python 语音Agent主程序_main.py --no-tts ask 帮我看看当前机械臂状态
```

## Shell 命令

进入 shell 后可用：

```text
/voice
/say 文本
/session
/warmup
/reset
/tools
/quit
```

普通文本会直接发送给 Agent。

## 配置 OpenAI-compatible backend

编辑 `Agent配置.yaml`：

```yaml
agent:
  backend: openai_compatible

openai_compatible:
  api_base: https://api.siliconflow.cn/v1
  api_key: ${SILICONFLOW_API_KEY}
  model: THUDM/GLM-Z1-9B-0414
  temperature: 0.3
  max_tokens: 800
```

`THUDM/GLM-Z1-9B-0414` 是 SiliconFlow 免费模型，支持工具调用。先在终端设置环境变量：

```bash
export SILICONFLOW_API_KEY="你的 SiliconFlow API Key"
```

模型支持标准 tool calling 时，客户端会按 OpenAI tools 格式调用工具。模型不支持时，也可以输出 JSON：

```json
{
  "reply": "我会帮你停止机械臂。",
  "tool_calls": [
    {"name": "stop_robot", "arguments": {}}
  ]
}
```

## Nanobot / OpenClaw 预留

`Agent配置.yaml` 已预留：

```yaml
nanobot:
  enabled: false
  source_dir: ../external/nanobot
  tool_mode: bridge_only

openclaw:
  enabled: false
  command: openclaw
```

当前版本只提供清晰错误提示。后续接入时仍然必须 `bridge_only`，只能通过阶段十工具桥接调用阶段八 API。

## 安全规则

- 默认 `dry_run`。
- Agent 不直接控制舵机。
- Agent 不写 raw 值。
- Agent 不执行任意代码。
- Web 内嵌 Agent 直接调用同进程控制服务；独立 Agent 通过阶段八 API 提议动作。
- `stop_robot`、`stop_face_follow` 和 `get_robot_state` 是立即执行的减险/只读工具。
- 其他真实工具先生成 30 秒有效的动作卡，显示当前值、变化量、目标值、单位和速度。
- 用户点击“确认执行”或输入完整口令 `确认执行` 后，服务端重新读取状态并执行；普通“确认”“好的”不执行。
- 每条待确认动作只能使用一次。切换模式、断开连接、急停、状态漂移或生成新动作都会使旧动作失效。
- J10 单位为毫米，支持相对/绝对运动，目标限制为 `-50 mm` 到 `50 mm`，单次位移不限。
- J11 单位为度，支持相对/绝对运动，目标限制为 `-180°` 到 `180°`，单次角度不限。
- J12-J15 只允许相对运动，单次最多 `±3°`；底层控制器和硬件保护继续生效。
- `set_gripper.open_ratio` 必须在 0 到 1。
- 夹爪未安装或未标定时拒绝创建动作。
- `play_action` 只能播放动作库里存在的动作，AI 对话固定只播放一次，不循环。
- 真实模式下 Agent 默认禁止移动工具，除非配置显式开启。
- 用户说“停”“停止”“别动”“急停”时优先停止机械臂。

GitHub 中的 `Agent配置.yaml` 必须保持真实工具关闭。开发板使用被 Git 忽略的 `Agent配置.local.yaml` 开启：

```yaml
safety:
  allow_real_robot_tools: true
```

本机覆盖文件与模板递归合并，环境变量仍具有最高优先级。关闭本机开关并重启 Web 服务即可回到只读 AI。

## 常见错误

sounddevice 不可用：录音或 TTS 播放会提示不可用。安装 `sounddevice`，或使用 `--no-tts` 和文本 ask。

STT 服务不可用：`voice` 会提示 STT 服务不可用。检查 `stt.url` 对应服务是否启动。

TTS 服务不可用：文本结果仍会正常打印，只会显示 TTS 播放警告。

独立 Agent 找不到阶段八 API：工具调用会提示“机器人控制 API 不可用，请先启动阶段八 Web 服务”。Web 控制台内嵌 Agent 不再通过 localhost 回调自身。

模型不支持 tool calling：让模型按 README 中的 JSON 格式输出 `reply` 和 `tool_calls`。

工具调用参数错误：安全策略会拒绝，例如 J10/J11 目标越界、J12-J15 单次超过 3 度、夹爪参数越界、未知工具或动作库中不存在动作。

## 测试脚本

```bash
mamba run -n momo_rebot python 测试脚本_test/01_文本ask测试.py
mamba run -n momo_rebot python 测试脚本_test/02_录音测试.py
mamba run -n momo_rebot python 测试脚本_test/03_STT测试.py
mamba run -n momo_rebot python 测试脚本_test/04_TTS测试.py
mamba run -n momo_rebot python 测试脚本_test/05_工具桥接dry_run测试.py
ARM_MOCK_STT_TEXT=请查询机械臂状态 mamba run -n momo_rebot python 测试脚本_test/06_语音回合测试.py
```
