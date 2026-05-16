# 阶段九：视觉识别与视觉跟随

阶段九给机械臂增加“看见目标”的能力：摄像头采集画面，人脸检测找到目标，计算目标中心相对画面期望中心的偏移，再经过平滑和死区判断，最后生成很小的关节步进建议。

视觉模块不直接控制舵机。真正的机械臂动作仍然走阶段八 Web API，再由阶段八进入阶段四真实控制器和安全检查。

## 视觉链路

```text
摄像头画面
  -> 人脸/手势检测
  -> 目标中心点
  -> ndx / ndy 偏移
  -> 平滑滤波和死区判断
  -> 小幅 joint-step 意图
  -> 阶段八 API
  -> 阶段四安全控制器
```

## 基本概念

人脸中心点是检测框的中心。例如人脸框是 `[x, y, w, h]`，中心就是 `[x + w/2, y + h/2]`。

`ndx` 和 `ndy` 是归一化偏移。`ndx > 0` 表示目标在画面右边，`ndx < 0` 表示目标在画面左边；`ndy > 0` 表示目标在画面下方，`ndy < 0` 表示目标在画面上方。归一化后，不同分辨率下的偏移量比较稳定。

死区是“偏移很小时不动”的范围。人脸已经接近期望中心时，如果还继续下发动作，机械臂会来回抖动，所以死区内不会生成跟随动作。

平滑滤波使用 EMA：新结果占一部分，旧结果占一部分。这样画面中的检测抖动不会直接变成舵机抖动。

视觉系统不能直接控制舵机，因为摄像头检测可能丢帧、误检或抖动。所有动作必须走阶段八 API 或阶段四控制器，让已有的安全确认、步长限制、急停和 dry-run 机制继续生效。

## 安装依赖

```bash
pip install opencv-contrib-python numpy pyyaml fastapi uvicorn
```

手势识别是可选功能：

```bash
pip install mediapipe
```

人脸检测权重需要放在：

```text
weights/face_detection_yunet_2023mar.onnx
```

手势识别模型需要放在：

```text
weights/gesture_recognizer.task
```

如果权重不存在，程序不会崩溃，会在 `/latest` 和终端里显示中文提示。

## 运行摄像头预览

```bash
cd 机械臂/视觉识别与跟随
python 视觉主程序_main.py preview
```

按 `q` 退出。

## 运行人脸检测

```bash
python 视觉主程序_main.py detect
```

画面会显示人脸框、目标中心、期望中心、偏移箭头、`ndx / ndy`、手势和 FPS。

## 启动视觉服务

```bash
python 视觉主程序_main.py service
```

也可以指定地址和端口：

```bash
python 视觉主程序_main.py --service --host 127.0.0.1 --port 8000
```

## 查看接口

健康检查：

```text
http://127.0.0.1:8000/health
```

最新视觉结果：

```text
http://127.0.0.1:8000/latest
```

最新可视化画面：

```text
http://127.0.0.1:8000/frame.jpg
```

WebSocket 推送：

```text
ws://127.0.0.1:8000/ws/stream
```

推送格式：

```json
{
  "type": "vision",
  "data": {
    "detected": true,
    "offset": {"ndx": 0.03, "ndy": -0.02},
    "smoothed_offset": {"ndx": 0.02, "ndy": -0.01}
  }
}
```

## dry-run 视觉跟随

默认跟随是 dry-run，只计算应该发出的关节步进，不调用真实机械臂：

```bash
python 视觉主程序_main.py follow
```

如果要让跟随控制器调用阶段八 API，需要先启动阶段八 Web 控制台，并显式加参数：

```bash
python 视觉主程序_main.py follow --execute-api
```

它只会调用：

```text
POST http://127.0.0.1:8010/api/v1/motion/joint-step
```

不会直接写舵机。

## 手势识别

```bash
python 视觉主程序_main.py gesture
```

第一版只识别手势，不默认执行真实动作。可识别手势用于后续扩展：

- `Open_Palm`：停止
- `Closed_Fist`：闭合夹爪
- `Thumb_Up`：播放动作
- `Pointing_Up`：回家

## 阶段八 follow 接口

阶段八 Web API 增加：

```text
GET  /api/v1/follow/status
POST /api/v1/follow/start
POST /api/v1/follow/stop
```

示例：

```bash
curl -X POST http://127.0.0.1:8010/api/v1/follow/start \
  -H 'Content-Type: application/json' \
  -d '{"latest_url":"http://127.0.0.1:8000/latest","dry_run":true}'
```

`dry_run: true` 时只计算命令，不调用 `/motion/joint-step`。要实际通过阶段八 API 下发小步进，需要设置 `dry_run: false`，并确保阶段八已经连接到 `dry_run` 或经过确认的 `real` 模式。

## 常见错误

摄像头打不开：检查摄像头是否被其他软件占用，或修改 `视觉配置.yaml` 里的 `camera_index`。

YuNet 权重缺失：把 `face_detection_yunet_2023mar.onnx` 放进 `weights/`。缺失时服务仍可启动，但人脸检测不可用。

OpenCV 没有 `FaceDetectorYN`：安装 `opencv-contrib-python`，不要只安装 `opencv-python`。

`mediapipe` 未安装：手势识别不可用，但人脸检测和视觉服务仍然可用。

阶段八 API 没启动：`follow --execute-api` 会请求失败。先运行 `Web控制台/启动Web服务.py`。

目标抖动：增大 `smoothing.alpha` 的平滑效果，或适当增大 `dead_zone_x / dead_zone_y`。

目标丢失：`detected=false` 时跟随控制器不会继续下发动作；请检查光线、人脸是否在画面内、权重文件是否存在。
