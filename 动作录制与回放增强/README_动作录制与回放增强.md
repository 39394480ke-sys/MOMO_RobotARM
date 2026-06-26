# 阶段六：动作录制与回放增强系统

阶段六的目标是把动作文件从“几个角度点”升级成完整的“可回放记录”。它会保存关节角度、末端 TCP 位姿、舵机 raw 位置、多圈关节状态、夹爪状态和回放安全元数据，后面 GUI、Web、语音 Agent 都能直接调用。

## 运行环境

本项目统一使用你的 `momo_rebot` 环境里的 `python`。先激活环境，再进入阶段六目录：

```bash
mamba activate momo_rebot
cd "/Users/ke/Library/Mobile Documents/com~apple~CloudDocs/Code/机械臂/动作录制与回放增强"
python -V
```

看到 Python 3.11 之后再运行后面的命令。不要混用系统 Python 或单独写 `python3`，否则可能找不到 `pybullet`，导致 TCP 位姿只能走兜底计算。

## 姿态和动作的区别

姿态是某一瞬间机械臂的状态，比如 5 个关节角度加夹爪开合。动作是一串姿态，并且每个姿态有持续时间、停留时间和回放所需的安全信息。

## 阶段三和阶段六的区别

阶段三动作播放器主要播放 `关节角度` 和 `夹爪`，适合仿真入门。阶段六动作系统会保存 `joint_targets_deg`、`tcp_pose`、`raw_present_position`、`multi_turn_state`、`gripper`、`replay_joint_targets_deg` 和 `replay_multi_turn_continuous_raw`，适合真实机械臂和后续 Agent 调用。

## 什么是示教录制

示教录制就是把机械臂摆到一个姿态，按 Enter 保存一次；摆到下一个姿态，再按 Enter 保存。真实机械臂示教时要扶住机械臂，默认不会自动释放扭矩，除非用户确认。

## 为什么保存 raw_present_position

`raw_present_position` 是舵机直接读到的原始位置。它用于排查标定、角度映射和硬件状态问题。角度看起来一样时，raw 可以帮助判断舵机实际在哪个位置。

## 为什么 J10/J12/J13/J15 要保存 multi_turn_state

J10 底盘导轨、J12 肩部抬升、J13 肘部弯曲、J15 腕部旋转是多圈关节。多圈关节不能简单把 raw 对 4096 取模，否则可能回放到错误圈数。阶段六保存 continuous_raw，让支持该能力的阶段四控制器可以按原圈数回放。

## 为什么不能简单播放角度

真实机械臂有速度、限位、标定和多圈圈数问题。简单下发角度可能导致动作过快、跨越过大，或者多圈关节走错圈。阶段六回放前会打印摘要、检查格式、拆分大角度动作，真实模式还要求二次确认。

## 夹爪如何录制和回放

录制时会保存：

```json
{"available": true, "present_raw": 1450, "open_ratio": 0.5, "open_percent": 50}
```

回放时优先用 `open_percent` 或 `open_ratio` 调用 `controller.set_gripper()`。如果只有 raw 且控制器支持 `write_gripper_raw`，才尝试 raw 回放。控制器没有夹爪能力时只给警告，不中断整个动作。

## dry-run、仿真、真实模式

仿真模式只改变电脑里的机械臂状态。dry-run 使用阶段四控制器做映射和安全检查，但不写真实舵机。真实模式会移动机械臂，必须输入 `我确认机械臂周围安全` 才能回放。

## 如何录制动作

进入目录后运行：

```bash
python 动作主程序_main.py
```

默认是仿真模式。如果要走阶段四 dry-run 控制器，用：

```bash
python 动作主程序_main.py --mode dry-run
```

如果确实要连接真实机械臂，用：

```bash
python 动作主程序_main.py --mode 真实
```

真实模式播放动作前仍会要求输入 `我确认机械臂周围安全`。

输入：

```text
录制 测试动作 2
```

如果要手动摆姿态并按 Enter 记录，输入：

```text
示教录制 测试动作 2
```

也可以直接运行：

```bash
python 示教模式_teach_mode.py --pose-count 3 --output 动作库/我的动作.json
```

## 如何回放动作

在主程序中输入：

```text
动作列表
动作摘要 测试动作
播放 测试动作
```

循环播放：

```text
循环播放 测试动作
```

## 暂停、继续、停止

播放时可以输入：

```text
暂停
继续
停止
```

停止会立即停止阶段六继续下发后续姿态，并尽量调用控制器的 `stop()` 保持当前位置。

## 动作文件格式

动作文件 schema 是 `arm_replay_sequence_v1`。关键字段：

- `joint_targets_deg`：录制到的主要关节角度。
- `tcp_pose`：阶段五 FK 或控制器提供的末端位姿。
- `raw_present_position`：舵机 present raw，用于调试和必要时 raw 级回放。
- `multi_turn_state`：多圈关节的当前 raw、relative raw 和 continuous raw。
- `gripper`：夹爪状态，不可用时写 `{"available": false}`。
- `replay_joint_targets_deg`：安全处理后的回放角度。
- `replay_multi_turn_continuous_raw`：多圈关节回放所需 continuous raw，不做 4096 取模。

JSON 写入时使用 `ensure_ascii=False`，中文会正常显示。

## 常见错误

- 动作不存在：先输入 `动作列表` 确认名称。
- 动作格式不对：确认 `schema_version`、`joint_order` 和 `poses` 是否完整。
- 控制器不支持 continuous_raw：系统会降级为角度回放并打印警告。
- 夹爪不可用：系统跳过夹爪，不中断关节动作。
- 限位错误：停止播放，检查动作文件里的角度是否超出配置范围。

## 真实机械臂回放安全流程

1. 确认标定完整，机械臂周围没有障碍物。
2. 先用 dry-run 回放，查看目标角度和 raw。
3. 第一次真实回放建议只测 1 个 pose 或很小动作。
4. 真实模式必须输入 `我确认机械臂周围安全`。
5. 手放在急停或电源附近，发现异常立刻停止或断电。
6. 阶段六不会直接写 Feetech 舵机，真实动作必须通过阶段四控制器执行。
