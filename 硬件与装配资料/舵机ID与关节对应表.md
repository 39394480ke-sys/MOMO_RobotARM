# 舵机 ID 与关节对应表

本表必须与阶段四 `真实舵机控制/真实配置.yaml`、`真实舵机控制/标定工具_calibration_utils.py` 和 `真实舵机控制/角度映射_angle_mapper.py` 保持一致。

| 关节编号 | 内部 key | 中文名称 | 舵机 ID | 模式 | 是否多圈 | joint_scale | 标定零点字段 | 备注 |
|---|---|---|---:|---|---|---:|---|---|
| J1 | shoulder_pan | 底座旋转 | 1 | 单圈 | 否 | 1.0 | zero_present_raw | 单圈目标 raw 会包裹到 0-4095，并受 range_min/range_max 约束 |
| J2 | shoulder_lift | 肩部抬升 | 2 | 多圈 | 是 | -5.3 | home_present_raw | 多圈 absolute raw，phase=28 |
| J3 | elbow_flex | 肘部弯曲 | 3 | 多圈 | 是 | 5.6 | home_present_raw | 多圈 absolute raw，phase=28 |
| J4 | wrist_flex | 腕部俯仰 | 4 | 单圈 | 否 | -1.0 | zero_present_raw | 单圈目标 raw 会包裹到 0-4095，并受 range_min/range_max 约束 |
| J5 | wrist_roll | 腕部旋转 | 5 | 多圈 | 是 | 1.0 | home_present_raw | 多圈 absolute raw，phase=28 |
| J6 | gripper | 夹爪 | 6 | 夹爪 | 否 | - | range_min/range_max | 夹爪不进入 5 轴 IK，按开合范围控制 |

固定多圈关节：

```text
J2 shoulder_lift
J3 elbow_flex
J5 wrist_roll
```

固定协议参数：

```text
RAW_COUNTS_PER_REV = 4096
MULTI_TURN_PHASE_VALUE = 28
MULTI_TURN_ABSOLUTE_RAW_LIMIT = 30719
POSITION_MODE_VALUE = 0
```

CSV 版本见 `表格/舵机ID表.csv`。

