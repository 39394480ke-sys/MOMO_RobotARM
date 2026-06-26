# 阶段五：URDF / 运动学 / 3D 仿真

这个阶段给前面的机械臂项目增加“模型和运动学”能力：

- 用 URDF 描述机械臂结构。
- 用 PyBullet 做 FK 正运动学和 IK 逆运动学。
- 支持用末端坐标 xyz/rpy 控制机械臂。
- 支持 base 坐标系和 tool 坐标系下的增量移动。
- 支持一个简单的 PyBullet 3D 查看窗口。
- 不直接控制真实舵机。

## 为什么前面阶段没用 URDF

阶段三只做“逻辑角度仿真”，重点是姿态、动作库和安全范围。
阶段四才开始接真实舵机，重点是标定、角度映射、安全检查和 dry-run。

URDF 属于“机械结构和空间位置计算”。如果太早引入，会让基础控制和真实舵机标定变复杂。所以阶段五才加入。

## URDF 是什么

URDF 是机器人描述文件。它描述：

- 机器人有哪些 link，也就是机械零件。
- 机器人有哪些 joint，也就是关节。
- 每个关节的父子关系、位置、旋转轴和角度范围。
- 每个 link 对应的 STL mesh 模型。

本阶段使用第三方来源的 `soarmoce_urdf.urdf` 和 STL 文件，没有重新编写 URDF。发布前需要核验这些模型文件的许可证、署名要求和再分发限制；如果要做完全自有版本，需要重新建模并替换 URDF/STL。

## FK 正运动学是什么

FK 的输入是 6 个用户目标值（j10 为 mm，其余为 deg），输出是末端的位置和姿态：

```text
关节角度 -> 末端 xyz/rpy
```

运行：

```bash
cd URDF运动学仿真
python3 正运动学_fk.py --joints-deg 0 0 20 30 10 0
```

## IK 逆运动学是什么

IK 的输入是目标末端位置，输出是一组能到达该位置的关节角度：

```text
目标 xyz/rpy -> 关节角度
```

运行：

```bash
python3 逆运动学_ik.py --xyz 0.20 0.05 0.18
python3 逆运动学_ik.py --xyz 0.20 0.05 0.18 --rpy 0 0 0
```

如果误差超过 `运动学配置.yaml` 里的 `max_ee_pos_err_m`，脚本会返回失败，不会假装成功。

## target_frame / Link_6 是什么

`target_frame` 是 FK/IK 计算时使用的末端坐标系。

本项目基于通用运动学流程，使用：

```yaml
target_frame: Link_6
```

也就是说，阶段五把新 URDF 里的 `Link_6` 当作主要末端，不把 gripper 放进 6 关节 IK 主链路。

## 为什么 SDK 关节名和 URDF 关节名要映射

上层控制器使用 SDK 关节名：

```text
j10, j11, j12, j13, j14, j15
```

URDF 里的实际 joint 名是：

```text
j10, j11, j12, j13, j14, j15
```

所以新版配置里是直接映射，同时保留旧名字别名：

```yaml
joint_name_aliases:
  j10: j10
  j11: j11
  shoulder_pan: j11
```

这样上层仍然按固定 SDK 顺序控制，底层 FK/IK 再映射到 URDF。

## base 坐标系和 tool 坐标系

`base` 坐标系是机器人底座坐标系。`增量 base 0.01 0 0` 表示沿底座 x 方向移动 1 cm。

`tool` 坐标系是当前末端自己的坐标系。`增量 tool 0.01 0 0` 表示沿末端当前朝向的 x 方向移动 1 cm。

## 打开 3D 仿真

如果只是检查 URDF 外观、旋转视角、缩放模型，推荐直接用 VS Code 的 `URDF Visualizer: 预览 URDF/Xacro` 打开：

```text
URDF运动学仿真/urdf/soarmoce_urdf.urdf
```

这个 URDF 里的 STL 路径是 `../meshes/*.STL`，从 `urdf/` 目录下打开时可以正确找到模型文件。

PyBullet 查看器更适合做 FK / IK 和动作播放验证：

```bash
python3 3D仿真_pybullet_viewer.py
```

命令示例：

```text
状态
移动 0 0 20 30 10 0
播放动作 挥手
末端
退出
```

这个查看器只加载 URDF，不连接真实舵机。部分 macOS / Metal 版本的 PyBullet 不能稳定读取 GUI 滑块；如果窗口提示滑块不可用，就用 `移动 ...` 或 `播放动作 ...` 命令控制。

## 中文主程序

```bash
python3 运动学主程序_main.py
```

可用命令：

```text
检查URDF
正解 0 0 20 30 10 0
逆解 0.20 0.05 0.18
逆解带姿态 0.20 0.05 0.18 0 0 0
末端
增量 base 0.01 0 0
增量 tool 0.01 0 0
打开3D
退出
```

## 和阶段三/四控制器集成

阶段五提供 `末端控制_cartesian_controller.py`：

```python
from 运动学模型_kinematics_model import 创建运动学模型
from 末端控制_cartesian_controller import 末端控制器

kin = 创建运动学模型(use_gui=False)
cart = 末端控制器(已有控制器, kin, dry_run=True)
result = cart.move_pose([0.20, 0.05, 0.18])
```

链路是：

```text
move_pose
  -> IK
  -> move_joints
  -> 阶段三仿真 / 阶段四 dry-run / 阶段四真实控制
```

如果已有控制器是阶段四 `RealArmController`，会调用它自己的 `move_joints(dict)`，保留标定和安全检查。

如果已有控制器是阶段三 `机械臂模型`，会调用它已有的 `移动到关节角度(list)`。

## 为什么阶段五不直接写舵机

真实舵机通信属于阶段四职责。阶段四已经有：

- dry-run
- 标定文件
- 角度映射
- raw 范围检查
- 安全检查
- 舵机驱动

阶段五如果直接写舵机，就会绕过这些安全逻辑。所以阶段五只算 IK 目标角度，再交给已有控制器执行。

## 常见错误

### pybullet 未安装

现象：

```text
当前环境没有安装 pybullet。
请运行：
pip install pybullet
```

解决：

```bash
pip install numpy pybullet pyyaml
```

### URDF 找不到

检查 `运动学配置.yaml`：

```yaml
urdf_path: urdf/soarmoce_urdf.urdf
```

并确认文件存在。

### mesh 找不到

运行：

```bash
python3 URDF检查_urdf_inspector.py
```

看 `missing_meshes` 字段。URDF 里 STL 路径是相对 `urdf/` 目录的 `../meshes/...`。

### IK 无解

目标点可能超出机械臂可达范围。先用 FK 看几个已知姿态的末端位置，再选择接近这些位置的目标点。

### 末端误差过大

IK 可能找到一个近似解，但误差超过配置：

```yaml
max_ee_pos_err_m: 0.03
```

这种情况脚本会返回失败，末端控制器不会调用 `move_joints`。

## 测试脚本

```bash
python3 测试脚本_test/01_检查URDF.py
python3 测试脚本_test/02_正运动学测试.py
python3 测试脚本_test/03_逆运动学测试.py
python3 测试脚本_test/04_末端增量移动测试.py
python3 测试脚本_test/05_3D仿真显示测试.py
python3 测试脚本_test/06_阶段五接阶段四dryrun测试.py
python3 测试脚本_test/07_真实移动前检查与执行.py --xyz -0.01829269342124462 -0.09768977761268616 0.1212569996714592
```

## 阶段五接阶段四 dry-run

先激活项目环境，并站在项目根目录：

```bash
mamba activate momo_rebot
cd "/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/机械臂"
```

运行：

```bash
python URDF运动学仿真/测试脚本_test/06_阶段五接阶段四dryrun测试.py
```

这个脚本会：

```text
阶段五 IK
  -> 阶段四 RealArmController.move_joints
  -> 阶段四 dry-run MockServoDriver
```

它会创建临时阶段四配置，强制 `dry_run=true`，不会修改 `真实舵机控制/真实配置.yaml`，也不会访问真实舵机。

默认目标点来自 FK 姿态 `[0, 0, 20, 30, 10, 0]`，通常能通过阶段四安全范围。你也可以传自己的目标：

```bash
python URDF运动学仿真/测试脚本_test/06_阶段五接阶段四dryrun测试.py --xyz 0.20 0.05 0.18
```

如果阶段四报角度超范围，例如某个关节超出配置安全范围，说明这个目标点不适合直接执行，需要换更安全的 xyz。

## 真实移动前检查和执行

先只检查，不移动：

```bash
python URDF运动学仿真/测试脚本_test/07_真实移动前检查与执行.py \
  --xyz -0.01829269342124462 -0.09768977761268616 0.1212569996714592
```

检查模式只计算 IK 和目标角度，不连接真实舵机。

确认已经完成阶段四标定、单关节小幅移动、06 dry-run 集成测试后，才可以真实执行：

```bash
python URDF运动学仿真/测试脚本_test/07_真实移动前检查与执行.py \
  --xyz -0.01829269342124462 -0.09768977761268616 0.1212569996714592 \
  --execute-real \
  --i-understand-risk
```

真实执行时脚本仍然只调用阶段四 `move_joints()`，不会绕过阶段四的标定、安全检查和角度映射。
