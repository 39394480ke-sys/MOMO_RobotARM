# 机械臂导轨版使用教程（URDF / GUI / Web）

本文档对应当前双型号结构。默认型号是 V2；V1 仅用于兼容已有模型、标定和动作。

## 1. 选择机器人型号

型号配置是硬件映射和模型路径的权威来源：

| 型号 | 配置 | URDF | TCP |
|---|---|---|---|
| V1 | `配置/robot_v1.yaml` | `URDF运动学仿真/urdf/v1/soarmoce_urdf.urdf` | `Link_6` |
| V2（默认） | `配置/robot_v2.yaml` | `URDF运动学仿真/urdf/v2/soarmoce_urdf.urdf` | `Link_7` |

V1 mesh 位于 `URDF运动学仿真/meshes/v1/`，V2 mesh 位于
`URDF运动学仿真/meshes/v2/`。不要把两个型号的 URDF、mesh、标定或动作混用。

默认 V2 由受版本控制的安全基线选择。临时切换型号时，在被 Git 忽略的
`真实舵机控制/真实配置.local.yaml` 中写：

```yaml
robot:
  variant: V1
```

只允许精确的 `V1` 或 `V2`。环境变量不提供型号选择接口。

配置按下列顺序合并，后者优先：

1. 受版本控制的 `真实舵机控制/真实配置.yaml`
2. 被 Git 忽略的 `真实舵机控制/真实配置.local.yaml`
3. 由 `robot.variant` 选中的 `配置/robot_v1.yaml` 或 `配置/robot_v2.yaml`
4. 运行参数环境变量：`ARM_ROBOT_PORT`、`ARM_SERVO_BACKEND`、`ARM_REAL_DRY_RUN`

profile 会强制写回关节、传动、限位和 raw 可达关节等硬件权威字段，因此本地覆盖
不能修改这些字段。受版本控制的默认配置保持串口为空且 `dry_run: true`。实际串口、
现场标定和其他机器相关值只能写入被忽略的本地配置或运行参数环境变量，不能提交。

## 2. V2 关节

| key | 舵机 ID | 机构 | GUI/Web 单位 |
|---|---:|---|---|
| `j10` | 10 | 线性导轨 | mm |
| `j11` | 11 | 底座旋转，1:5 | deg |
| `j12` | 12 | 肩部抬升，1:28 | deg |
| `j13` | 13 | 肘部弯曲，1:14 | deg |
| `j14` | 14 | 腕部俯仰，1:1 | deg |
| `j15` | 15 | 腕部旋转，1:1 | deg |
| `gripper` | 16 | 可选夹爪 | % |

主关节顺序固定为 `j10, j11, j12, j13, j14, j15`。V2 的 J12/J13 属于
`raw_reachable_joints`：有效逻辑范围必须由当前 Home、传动映射和绝对 raw 上限
`±30719` 动态计算，不能只采用静态配置限位，也不能绕过此检查。

## 3. 仿真、GUI 与 Web

先在仓库根目录检查当前型号的 URDF：

```bash
mamba run -n momo_rebot python URDF运动学仿真/URDF检查_urdf_inspector.py
```

启动 GUI：

```bash
cd GUI图形界面
mamba run -n momo_rebot python GUI主程序_main.py
```

启动 Web 控制台：

```bash
cd Web控制台
mamba run -n momo_rebot python 启动Web服务.py
```

浏览器打开 `http://127.0.0.1:8010/web/`。GUI 和 Web 首次操作均保持
`dry_run`；J10 的数值单位为毫米，J11-J15 为输出端角度。

## 4. 标定和动作兼容门

真实标定只使用被忽略的 `真实舵机控制/标定/current.local.json`。仓库中的
`标定/v1.example.json` 和 `标定/v2.example.json` 只是结构模板，绝不能用于真机。

标定文件必须在 `_meta.robot_variant` 写准确型号；动作文件必须在顶层
`robot_variant` 写准确型号。只有相应字段与当前型号完全匹配的文件才能进入真机路径；
字段缺失、未知值或型号不匹配时，只允许仿真或 `dry_run` 预览。不要为了通过检查而
改写旧文件的型号。

## 5. 真机验收边界

本教程不授权任何硬件动作。每一个实际硬件阶段都必须单独、明确批准，并严格按以下
顺序进行：

1. ping
2. 只读 raw
3. 建立并核对机械零位
4. 单关节微小运动
5. 停止并关闭扭矩
6. 低速多关节运动

任何阶段失败都应停止，不得跳级。详细清单见
[`docs/V2真机验收.md`](docs/V2真机验收.md)。本轮文档更新没有连接、读取或驱动真实硬件。
