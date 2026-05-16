# STEP / STL / URDF 对应关系

三类文件用途不同：

```text
STEP：工程 CAD 模型，适合修改结构
STL：网格模型，适合 3D 显示和打印
URDF：机器人结构描述，适合仿真和运动学
```

当前仓库已确认存在 `URDF运动学仿真/meshes/*.STL` 和 `URDF运动学仿真/urdf/soarmoce_urdf.urdf`。未确认 STEP 文件，因此 STEP 一列写“待确认”。

| 部件 | STEP 文件 | STL / mesh 文件 | URDF link 名称 | 备注 |
|---|---|---|---|---|
| 底座 | 待确认 | `URDF运动学仿真/meshes/base.STL` | `base` | 已在 URDF 中引用 |
| 肩部 | 待确认 | `URDF运动学仿真/meshes/shoulder.STL` | `shoulder` | J1 child link |
| 肩抬升/大臂 | 待确认 | `URDF运动学仿真/meshes/shoulder_lift.STL` | `shoulder_lift` | J2 child link |
| 肘部 | 待确认 | `URDF运动学仿真/meshes/elbow.STL` | `elbow` | J3 child link |
| 腕部俯仰 | 待确认 | `URDF运动学仿真/meshes/wrist.STL` | `wrist` | J4 child link |
| 腕部旋转 | 待确认 | `URDF运动学仿真/meshes/wrist_roll.STL` | `wrist_roll` | J5 child link，也是当前 end_link |
| 夹爪 | 待确认 | `URDF运动学仿真/meshes/gripper.STL` | `gripper` | J6/夹爪 link |

URDF 关节名称和阶段四内部 key 的对应：

| 阶段四内部 key | URDF joint 名称 | URDF child link |
|---|---|---|
| shoulder_pan | `shoulder` | `shoulder` |
| shoulder_lift | `shoulder_lift` | `shoulder_lift` |
| elbow_flex | `elbow` | `elbow` |
| wrist_flex | `wrist` | `wrist` |
| wrist_roll | `wrist_roll` | `wrist_roll` |
| gripper | `gripper` | `gripper` |

