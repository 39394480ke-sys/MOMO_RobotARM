# 机械臂导轨版使用教程（URDF / GUI / Web）

本文档对应当前“导轨 + 机械臂”版本。新的 URDF 已集成到 `URDF运动学仿真/urdf/soarmoce_urdf.urdf`，mesh 已放入 `URDF运动学仿真/meshes/`。

## 1. 当前关节和舵机编号

为了避开 Feetech 舵机出厂常见 ID 1、2，本项目从 10 开始编号。

| 逻辑 key | 显示名 | 舵机 ID | 机构 | GUI/Web 单位 | URDF joint |
|---|---:|---:|---|---|---|
| `j10` | J10 底盘导轨 | 10 | 16mm 外径、5mm 导程滚珠丝杠，舵机直连 | mm | prismatic |
| `j11` | J11 底座旋转 | 11 | 旋转关节 | deg | revolute |
| `j12` | J12 肩部抬升 | 12 | 旋转关节 | deg | revolute |
| `j13` | J13 肘部弯曲 | 13 | 旋转关节 | deg | revolute |
| `j14` | J14 腕部俯仰 | 14 | 旋转关节 | deg | revolute |
| `j15` | J15 腕部旋转 | 15 | 旋转关节 | deg | revolute |
| `gripper` | J16 夹爪预留 | 16 | 夹爪 | % | 不参与主 IK |

兼容说明：Web/GUI 桥接层仍能识别旧 key，例如 `shoulder_pan` 会自动映射到 `j11`，但新动作、新姿态和新配置建议统一使用 `j10` 到 `j15`。

## 2. 导轨换算

导轨是舵机直连滚珠丝杠，导程 5mm/rev。

```text
1 圈舵机 = 5 mm
1 mm = 360 / 5 = 72 deg 舵机转角
Feetech 4096 raw = 1 圈 = 5 mm
1 mm = 4096 / 5 = 819.2 raw
```

所以 `真实舵机控制/真实配置.yaml` 里：

```yaml
j10: 72.0
```

当前真实安全行程先设为 `-35mm` 到 `35mm`。原因是现有多圈 raw 安全上限是 `30719`，按 5mm/rev 约等于 37.5mm。URDF 仿真仍保留 `-100mm` 到 `100mm` 的导轨范围。

## 3. URDF 是否可用

已通过项目自带静态检查：

```bash
cd /Users/ke/Library/Mobile\ Documents/com~apple~CloudDocs/Code/机械臂
python3 URDF运动学仿真/URDF检查_urdf_inspector.py
```

检查结果包括：

- 7 个 link：`base_link` 到 `Link_6`
- 6 个可动 joint：`j10` 到 `j15`
- `j10` 是 prismatic 导轨
- `j11` 到 `j15` 是 revolute 旋转关节
- mesh 文件全部存在
- target frame 是 `Link_6`

注意：当前本机 `pybullet` 安装失败，所以还不能在这个 Python 环境里跑真实 PyBullet FK/IK 加载测试。静态 URDF/XML/mesh/映射检查已经通过。

## 4. GUI 控制端怎么用

启动：

```bash
cd GUI图形界面
python3 GUI主程序_main.py
```

推荐流程：

1. 先保持 `dry_run` 模式。
2. 打开“设置”页，确认模式、串口、依赖状态。
3. 打开“快速控制”页。
4. 点连接。
5. 用 J10-J15 行测试小步移动。

快速控制页单位：

- `j10` 显示和输入是 `mm`
- `j11-j15` 显示和输入是 `deg`
- 步进下拉里显示 `deg/mm`，意思是同一个数值：对 J10 是毫米，对旋转轴是角度

真实模式前必须做：

1. 把 `真实舵机控制/真实配置.yaml` 中串口改成当前设备。
2. 确认导轨舵机 ID 是 10，往上依次是 11 到 15。
3. 重新跑标定，至少要补齐 `j10` 标定。
4. 在 GUI 中先用 0.5 或 1 的小步测试。

## 5. Web 控制端怎么用

启动：

```bash
cd Web控制台
python3 启动Web服务.py
```

默认地址：

```text
http://127.0.0.1:8010
```

Web 页面会显示 J10-J15。操作建议：

1. 先点连接，使用默认 dry-run。
2. 在关节控制区测试 `j10` 小步，例如 1mm。
3. 在 FK/IK 区输入 6 个值，顺序是 `j10, j11, j12, j13, j14, j15`。
4. 末端笛卡尔 jog 会调用 IK，再输出目标关节。
5. 真实模式下需要确认文本：`我确认机械臂周围安全`。

Web API 常用接口：

```text
POST /api/v1/session/connect
POST /api/v1/motion/joint-step
POST /api/v1/motion/joints
POST /api/v1/kinematics/fk
POST /api/v1/kinematics/ik
POST /api/v1/session/stop
```

`joint-step` 字段名仍叫 `delta_deg`，这是历史接口名；对 `j10` 实际解释为 mm。

## 6. 标定和真实运行

现在标定文件已经迁移到 `j11-j15`，ID 已改为 11-15。`j10` 没有写入假标定项，真实模式下只要移动导轨就会被安全检查拦住，直到你完成导轨标定。

建议顺序：

```bash
cd 真实舵机控制
python3 诊断舵机总线_diagnose_bus.py
python3 标定程序_calibrate.py
python3 标定应用_apply_calibration.py
```

标定后检查：

```bash
cd 系统集成
python3 标定检查.py
```

真实测试建议：

1. 先 dry-run 移动 `j10 = 5mm`，应对应 `relative_raw = 4096`。
2. 再真实模式移动 `j10 = 1mm`。
3. 确认方向正确后再扩大到 5mm。
4. 不要一开始直接跑 ±35mm。

## 7. 维护注意

- 新动作文件的 `joint_order` 必须是 `j10-j15`。
- 旧动作文件仍是 5 轴，播放时会提示 joint_order 不匹配，这是为了防止错位播放。
- `j16` 目前只是夹爪预留 ID，夹爪在配置中仍使用 `gripper` key。
- 如果后续确认 Feetech 多圈 raw 可安全超过 30719，再扩大 `j10` 的真实行程范围。
