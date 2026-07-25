# STEP / STL / URDF 对应关系

STEP 用于可编辑 CAD，STL 用于网格显示或打印参考，URDF 用于结构、仿真和运动学。
仓库未确认可编辑 STEP，因此不要把 STL 当作 CAD 源文件。

## 型号资源

| 型号 | URDF | STL 目录 | 主链末端 |
|---|---|---|---|
| V1 | `URDF运动学仿真/urdf/v1/soarmoce_urdf.urdf` | `URDF运动学仿真/meshes/v1/` | `Link_6` |
| V2 | `URDF运动学仿真/urdf/v2/soarmoce_urdf.urdf` | `URDF运动学仿真/meshes/v2/` | `Link_7` |

V1 和 V2 的模型文件不能交叉引用。具体文件以对应 URDF 中的 `<mesh filename>`
为准；新增或替换结构件时，应同时检查 URDF 引用、模型单位、坐标原点和关节方向。

## V2 link / mesh

| URDF link | mesh |
|---|---|
| `base_link` | `URDF运动学仿真/meshes/v2/base_link.stl` |
| `Link_2` | `URDF运动学仿真/meshes/v2/Link_2.stl` |
| `Link_3` | `URDF运动学仿真/meshes/v2/Link_3.stl` |
| `Link_4` | `URDF运动学仿真/meshes/v2/Link_4.stl` |
| `Link_5` | `URDF运动学仿真/meshes/v2/Link_5.stl` |
| `Link_6` | `URDF运动学仿真/meshes/v2/Link_6.stl` |
| `Link_7` | `URDF运动学仿真/meshes/v2/Link_7.stl` |

主关节名称统一为 `j10` 到 `j15`。型号配置
`配置/robot_v1.yaml` 与 `配置/robot_v2.yaml` 是 URDF、关节映射和 target frame 的
权威来源。
