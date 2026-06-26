# 机械臂小宠物生活周报

这个模块把机械臂当作桌面小宠物摄像头：机械臂和阶段九视觉服务只负责提供画面与视觉状态，电脑端脚本负责生成生活日报/周报。

## 运行前提

先启动阶段九视觉服务：

```bash
cd ../视觉识别与跟随
python3 视觉主程序_main.py service
```

默认读取：

```text
http://127.0.0.1:8000/health
http://127.0.0.1:8000/latest
http://127.0.0.1:8000/frame.jpg
```

## 生成周报

```bash
python3 生成生活周报.py --range week --out reports
```

生成日报：

```bash
python3 生成生活周报.py --range day --out reports
```

带手动备注：

```bash
python3 生成生活周报.py --range week --out reports --notes 我的备注.txt
```

备注文件每行一条，会写入报告的“手动备注”部分。

## 安全边界

- 本模块只读取阶段九视觉服务。
- 不调用 `/api/v1/motion/*`。
- 不写舵机 raw 值。
- 不自动发布到小红书或任何外部平台。
- 真实跟随如果需要启用，仍必须走阶段八 Web API 和原有安全确认。

## 离线测试

```bash
python3 测试脚本_test/01_周报生成dry_run测试.py
```
