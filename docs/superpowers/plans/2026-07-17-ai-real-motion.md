# AI Real Motion Confirmation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enable AI dialogue to propose and, only after explicit per-action confirmation, execute bounded real motions for J10-J15, the gripper, Home, action playback, and vision following.

**Architecture:** Keep the model on the proposal side of a two-phase boundary. A focused pending-action module normalizes and freezes tool arguments, while `WebControlService` owns live-state validation, confirmation, and in-process dispatch to the existing controller. The Web UI renders the server-issued action card and confirms by opaque action ID; repository configuration remains disabled by default and the development board enables the feature through an ignored local override.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, existing OpenAI-compatible Agent client, vanilla JavaScript/CSS, pytest/unittest, PyYAML, existing `momo_rebot` environment.

## Global Constraints

- J10 uses millimetres, supports relative and absolute motion, and its final target must be within `-50.0` to `50.0 mm`; one move has no delta limit.
- J11 uses degrees, supports relative and absolute motion, and its final target must be within `-180.0` to `180.0 degrees`; one move has no delta limit.
- J12-J15 use degrees, support relative motion only, and one move must be within `-3.0` to `3.0 degrees`; the AI layer adds no absolute range.
- All existing controller, calibration, and hardware protections remain active; the Agent never accepts raw servo values.
- Real motion requires one unexpired server-side pending action plus a matching opaque action ID; `确认执行` is the only text confirmation phrase.
- `stop_robot` and `stop_face_follow` execute immediately and invalidate pending actions.
- Pending actions expire after 30 seconds and are single-use. A J10 drift over `0.5 mm` or rotational drift over `0.5 degrees` invalidates confirmation.
- AI action playback always uses `loop=false`; AI joint motion uses `50%` speed.
- Keep `语音Agent/Agent配置.yaml` defaulting to `allow_real_robot_tools: false`; only ignored `Agent配置.local.yaml` enables real tools on the board.
- Preserve the user's existing uncommitted edits in `Web控制台/frontend/app.js`, `Web控制台/frontend/index.html`, and `Web控制台/测试脚本_test/test_快速控制关节单位.py`.
- Do not pull, reset, checkout, or broadly synchronize the dirty development-board repository. Back up board-local data and deploy only an explicit source-file list.
- Board deployment requires the snapshot and Mac-pull tasks in `docs/superpowers/plans/2026-07-16-board-data-sync.md` to be complete; this plan does not duplicate that independent backup subsystem.

---

### Task 1: Unit-Aware Agent Tool Contract And Local Configuration

**Files:**
- Modify: `语音Agent/agent/工具定义_robot_tools.py`
- Modify: `语音Agent/agent/安全策略_safety_policy.py`
- Modify: `语音Agent/agent/配置_config.py`
- Modify: `语音Agent/Agent配置.yaml`
- Modify: `语音Agent/prompts/system_prompt.md`
- Modify: `.gitignore`
- Create: `语音Agent/测试脚本_test/test_安全策略_real_motion.py`
- Create: `语音Agent/测试脚本_test/test_Agent本机配置.py`

**Interfaces:**
- Produces: tool `move_joint(joint_name: str, mode: "relative" | "absolute", value: float)`.
- Produces: `SafetyPolicy.validate_move_joint(arguments, current_joints) -> dict[str, Any]` returning `joint_name`, `mode`, `value`, `current_value`, `delta`, `target`, and `unit`.
- Produces: `load_config()` merged with sibling `Agent配置.local.yaml` before environment overrides.

- [ ] **Step 1: Write failing safety-policy tests**

Create table-driven tests that inject `allow_real_robot_tools=True` and assert the exact boundary behavior:

```python
def checked(joint: str, mode: str, value: float, current: float = 0.0):
    policy = SafetyPolicy({"safety": {"allow_real_robot_tools": True, "allowed_tools": ["move_joint"]}})
    return policy.validate_move_joint(
        {"joint_name": joint, "mode": mode, "value": value},
        {joint.lower(): current},
    )


def test_j10_and_j11_final_target_limits() -> None:
    assert checked("J10", "relative", 100.0, current=-50.0)["target"] == 50.0
    assert checked("J11", "absolute", -180.0)["target"] == -180.0
    for args in (("J10", "absolute", 50.01, 0.0), ("J11", "relative", 1.0, 180.0)):
        with pytest.raises(ValueError):
            checked(*args)


def test_j12_to_j15_are_relative_and_limited_to_three_degrees() -> None:
    for joint in ("J12", "J13", "J14", "J15"):
        assert checked(joint, "relative", 3.0)["delta"] == 3.0
        with pytest.raises(ValueError):
            checked(joint, "relative", 3.01)
        with pytest.raises(ValueError):
            checked(joint, "absolute", 0.0)
```

Also assert rejection of `NaN`, infinity, unknown joints, `raw`, `raw_value`, and `position_raw` anywhere in the arguments.

- [ ] **Step 2: Run the tests and verify failure**

```bash
mamba run -n momo_rebot python -m pytest 语音Agent/测试脚本_test/test_安全策略_real_motion.py -q
```

Expected: failure because `validate_move_joint` and the `move_joint` tool do not exist.

- [ ] **Step 3: Implement the unit-aware schema and validation**

Add `move_joint` to `robot_tool_specs()` with `additionalProperties: false`, keep `rotate_joint` as a compatibility-only schema, and implement validation using finite-number checks:

```python
JOINT_RULES = {
    "j10": {"unit": "mm", "modes": {"relative", "absolute"}, "minimum": -50.0, "maximum": 50.0},
    "j11": {"unit": "deg", "modes": {"relative", "absolute"}, "minimum": -180.0, "maximum": 180.0},
    "j12": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
    "j13": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
    "j14": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
    "j15": {"unit": "deg", "modes": {"relative"}, "max_delta": 3.0},
}

def validate_move_joint(self, arguments, current_joints):
    joint = normalize_joint_name(str(arguments.get("joint_name", "")))
    mode = str(arguments.get("mode", "relative")).lower()
    value = float(arguments["value"])
    if not math.isfinite(value):
        raise ValueError("关节运动数值必须是有限数字。")
    rule = JOINT_RULES[joint]
    if mode not in rule["modes"]:
        raise ValueError(f"{joint.upper()} 不支持 {mode} 模式。")
    current = float(current_joints[joint])
    target = value if mode == "absolute" else current + value
    delta = target - current
    if "max_delta" in rule and abs(delta) > rule["max_delta"]:
        raise ValueError(f"{joint.upper()} 单次运动不能超过 ±{rule['max_delta']}°。")
    if "minimum" in rule and not rule["minimum"] <= target <= rule["maximum"]:
        raise ValueError(f"{joint.upper()} 目标超出安全范围。")
    return {"joint_name": joint, "mode": mode, "value": value, "current_value": current,
            "delta": delta, "target": target, "unit": rule["unit"]}
```

Normalize legacy `rotate_joint(joint_name, delta_deg)` to relative `move_joint`; treat J10's legacy numeric value as millimetres and document that compatibility behavior.

- [ ] **Step 4: Add and test the ignored local Agent override**

Add `.gitignore` entry `语音Agent/Agent配置.local.yaml`. In `load_config`, merge the sibling file before environment values:

```python
from 通用_io import deep_merge, read_config, read_structured

config = read_config(config_path)
local_path = config_path.with_name(f"{config_path.stem}.local{config_path.suffix}")
if local_path.exists():
    config = deep_merge(config, read_structured(local_path))
    config["_config_path"] = str(config_path.resolve())
    config["_base_dir"] = str(config_path.resolve().parent)
```

The test creates temporary base/local YAML files, asserts nested merge behavior, asserts a malformed local file names its path, and asserts the repository template still has `allow_real_robot_tools: false`.

- [ ] **Step 5: Update prompt, run tests, and commit**

The prompt must state J10 millimetres, J11/J12-J15 degrees, absolute/relative support, and that motion tools only create pending actions. Run:

```bash
mamba run -n momo_rebot python -m pytest \
  语音Agent/测试脚本_test/test_安全策略_real_motion.py \
  语音Agent/测试脚本_test/test_Agent本机配置.py -q
```

Expected: all tests pass. Commit only the listed files:

```bash
git add .gitignore 语音Agent/Agent配置.yaml 语音Agent/prompts/system_prompt.md \
  语音Agent/agent/工具定义_robot_tools.py 语音Agent/agent/安全策略_safety_policy.py \
  语音Agent/agent/配置_config.py 语音Agent/测试脚本_test/test_安全策略_real_motion.py \
  语音Agent/测试脚本_test/test_Agent本机配置.py
git commit -m "feat: define safe AI joint motion contract"
```

---

### Task 2: Pending-Action State Machine

**Files:**
- Create: `Web控制台/backend/agent_pending_action.py`
- Create: `Web控制台/测试脚本_test/test_AI待确认动作.py`

**Interfaces:**
- Produces: `PendingActionStore(ttl_sec=30.0, clock=time.time)`.
- Produces: `create(tool_name, arguments, summary, state_snapshot) -> dict[str, Any]`.
- Produces: `current() -> dict[str, Any] | None`, `consume(action_id, current_snapshot) -> dict[str, Any]`, and `invalidate(reason) -> dict[str, Any] | None`.
- Snapshot format: `{"mode": str, "connected": bool, "joints": dict[str, float]}`.

- [ ] **Step 1: Write failing state-machine tests**

Use a mutable fake clock and assert creation, replacement, expiry, wrong-ID rejection, single use, mode/connection invalidation, and joint drift:

```python
now = [100.0]
store = PendingActionStore(clock=lambda: now[0])
action = store.create("move_joint", {"joint_name": "j10"}, {"title": "移动 J10"}, snapshot(j10=0.0))
assert action["expires_at"] == 130.0
now[0] = 131.0
assert store.current() is None

action = store.create("move_joint", {"joint_name": "j11"}, {}, snapshot(j11=0.0))
with pytest.raises(PendingActionError) as error:
    store.consume(action["id"], snapshot(j11=0.51))
assert error.value.code == "AGENT_PENDING_STATE_CHANGED"
```

- [ ] **Step 2: Run the test and verify import failure**

```bash
mamba run -n momo_rebot python -m pytest Web控制台/测试脚本_test/test_AI待确认动作.py -q
```

Expected: module import failure.

- [ ] **Step 3: Implement the state machine**

Use `secrets.token_urlsafe(24)` for IDs, store only one action, return defensive deep copies, and calculate remaining time in `current()`. `consume` must mark the action consumed before returning it so execution failure cannot reuse the ID. Compare only the action's relevant joint for joint motion, all displayed joints for Home, and mode/connection for every action.

Define stable errors:

```python
class PendingActionError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code

PENDING_NOT_FOUND = "AGENT_PENDING_NOT_FOUND"
PENDING_EXPIRED = "AGENT_PENDING_EXPIRED"
PENDING_ID_MISMATCH = "AGENT_PENDING_ID_MISMATCH"
PENDING_STATE_CHANGED = "AGENT_PENDING_STATE_CHANGED"
```

- [ ] **Step 4: Run tests and commit**

```bash
mamba run -n momo_rebot python -m pytest Web控制台/测试脚本_test/test_AI待确认动作.py -q
git add Web控制台/backend/agent_pending_action.py Web控制台/测试脚本_test/test_AI待确认动作.py
git commit -m "feat: add AI pending action state machine"
```

Expected: all pending-action tests pass before commit.

---

### Task 3: Web Service Proposal, Confirmation, And In-Process Dispatch

**Files:**
- Modify: `Web控制台/backend/schemas.py`
- Modify: `Web控制台/backend/service.py`
- Create: `Web控制台/测试脚本_test/test_AI真实运动_service.py`

**Interfaces:**
- Produces: `AgentToolProposalRequest(tool_name: str, arguments: dict[str, Any])`.
- Produces: `AgentPendingActionRequest(action_id: str)`.
- Produces: `WebControlService.agent_propose_tool(tool_name, arguments) -> dict[str, Any]`.
- Produces: `WebControlService.agent_confirm_pending(action_id) -> dict[str, Any]` and `agent_cancel_pending(action_id) -> dict[str, Any]`.

- [ ] **Step 1: Write failing service tests with a fake bridge**

Construct `WebControlService.__new__`, inject a fake real connected bridge and `PendingActionStore`, and assert:

```python
proposal = service.agent_propose_tool("move_joint", {"joint_name": "J10", "mode": "relative", "value": 40})
assert proposal["pending_action"]["summary"]["target"] == 40.0
assert bridge.moves == []

result = service.agent_confirm_pending(proposal["pending_action"]["id"])
assert bridge.moves == [{"j10": 40.0}]
assert result["executed_action"]["status"] == "executed"
```

Cover J10/J11 bounds, J12-J15 3-degree limit, no controller call before confirmation, Home precheck twice, missing action, forced non-loop playback, unavailable gripper, real follow using `dry_run=false`, concurrency rejection, and stop invalidation.

- [ ] **Step 2: Run tests and verify failure**

```bash
mamba run -n momo_rebot python -m pytest Web控制台/测试脚本_test/test_AI真实运动_service.py -q
```

Expected: proposal and confirmation methods do not exist.

- [ ] **Step 3: Add proposal creation and summaries**

Initialize `self._agent_pending = PendingActionStore(ttl_sec=30.0)`. `agent_propose_tool` must run `SafetyPolicy.check`, read `get_robot_state()`, reject when real tools are disabled, disconnected, an action is playing, or follow is running, then create summaries with these exact display fields:

```python
{"title": "移动 J10", "joint": "J10", "mode": "relative", "current": 0.0,
 "delta": 40.0, "target": 40.0, "unit": "mm", "speed_percent": 50}
```

For Home attach `home_precheck`; for an action attach name, speed, `loop=False`, frame count and duration when available; for follow attach mode, `dry_run`, effective joints, gains and step limits. Gripper proposal calls calibration/status data and rejects when the bridge reports it unavailable.

Normalize `run_robot_behavior(open_gripper)` to `set_gripper(open_ratio=1.0)` and `run_robot_behavior(close_gripper)` to `set_gripper(open_ratio=0.0)` before creating the card; only `run_robot_behavior(home)` remains a Home proposal.

Add `pending_action=self._agent_pending.current()` to `agent_status()` so a page refresh can restore the active card and its server-calculated remaining time.

- [ ] **Step 4: Add confirm/cancel and dispatch**

Inside `self._lock`, consume the pending action after a fresh state read, rerun safety validation, and dispatch frozen arguments:

```python
if tool == "move_joint":
    return self.move_joints(MoveJointsRequest(
        targets_deg={args["joint_name"]: args["target"]},
        speed_percent=50,
        confirm_text=self.confirm_text,
    ))
if tool == "run_robot_behavior":
    self.home_precheck()
    return self.home(HomeRequest(speed_percent=50, confirm_text=self.confirm_text))
if tool == "play_action":
    return self.play_action(PlayActionRequest(
        name=args["name"], speed=args["speed"], loop=False, confirm_text=self.confirm_text))
if tool == "start_face_follow":
    return self.start_follow(FollowStartRequest(confirm_text=self.confirm_text))
```

Use `set_gripper` for gripper actions. Map `PendingActionError.code` to `WebAPIError`. `stop()`, `stop_follow()`, `disconnect()`, `set_mode()`, and `agent_reset_session()` invalidate pending actions. Change AI concurrency behavior from silently stopping the current task to `AGENT_MOTION_BUSY`; do not alter manual-control behavior outside Agent paths.

- [ ] **Step 5: Replace the embedded self-HTTP bridge**

`_create_agent_tool_bridge` directly returns state/stop/stop-follow results and routes every increasing-risk tool to `service.agent_propose_tool`. It must never instantiate `RobotToolBridge` inside the Web process and never auto-fill confirmation text.

- [ ] **Step 6: Run service tests and commit**

```bash
mamba run -n momo_rebot python -m pytest \
  Web控制台/测试脚本_test/test_AI待确认动作.py \
  Web控制台/测试脚本_test/test_AI真实运动_service.py -q
git add Web控制台/backend/schemas.py Web控制台/backend/service.py \
  Web控制台/测试脚本_test/test_AI真实运动_service.py
git commit -m "feat: gate AI motion behind server confirmation"
```

Expected: no motion call occurs before confirmation and all service tests pass.

---

### Task 4: Agent And REST Integration

**Files:**
- Modify: `语音Agent/agent/OpenAI兼容客户端_openai_client.py`
- Modify: `语音Agent/agent/工具桥接_tool_bridge.py`
- Modify: `Web控制台/backend/app.py`
- Create: `语音Agent/测试脚本_test/test_待确认工具结果.py`
- Create: `Web控制台/测试脚本_test/test_AI确认API.py`

**Interfaces:**
- `POST /api/v1/agent/tool/propose` consumes `AgentToolProposalRequest` and returns a pending action.
- `POST /api/v1/agent/pending/confirm` and `/cancel` consume `AgentPendingActionRequest`.
- `POST /api/v1/agent/ask` returns optional `pending_action` alongside existing fields.

- [ ] **Step 1: Write failing Agent and API tests**

Assert that a tool bridge result containing `pending_action` is returned to the caller immediately rather than sent back to the model for another tool round. Assert exact `确认执行` in `agent_ask` calls confirmation without contacting the model, while `确认` does not. Use FastAPI's test client or direct async route calls to verify confirm/cancel response envelopes and stable error codes.

- [ ] **Step 2: Run tests and verify failure**

```bash
mamba run -n momo_rebot python -m pytest \
  语音Agent/测试脚本_test/test_待确认工具结果.py \
  Web控制台/测试脚本_test/test_AI确认API.py -q
```

- [ ] **Step 3: Preserve pending-action payloads in Agent replies**

When a tool result includes `result.pending_action`, return a deterministic reply and raw payload without giving the model a chance to execute or mutate it:

```python
pending = result.get("result", {}).get("pending_action")
if pending:
    return AgentReply(
        text=str(pending["summary"]["confirmation_text"]),
        session_id=self.session["session_id"],
        raw_payload={"pending_action": pending, "tool_result": result},
    )
```

`agent_ask` copies `reply.raw_payload["pending_action"]` to the top-level response. It intercepts exact `确认执行` for confirmation and exact `取消执行` for cancellation; all other text follows the normal Agent path. If one model response contains multiple increasing-risk tool calls, stop processing immediately after the first pending action and do not create or execute later calls from that response.

- [ ] **Step 4: Make standalone tools propose through Web API**

Keep direct HTTP only for independently run Agent processes. `get_robot_state`, `stop_robot`, and `stop_face_follow` retain their reducing-risk endpoints; all other tools post `{tool_name, arguments}` to `/api/v1/agent/tool/propose`. Delete `_confirm_if_real()` and never place configured confirmation text in a model-originated request.

- [ ] **Step 5: Add routes, run tests, and commit**

Add the three routes to `app.py`; confirmation broadcasts state, proposal/cancel do not need a robot-state broadcast. Run the two new tests plus the existing dry-run bridge test in a locally started test service, then commit:

```bash
git add 语音Agent/agent/OpenAI兼容客户端_openai_client.py 语音Agent/agent/工具桥接_tool_bridge.py \
  Web控制台/backend/app.py 语音Agent/测试脚本_test/test_待确认工具结果.py \
  Web控制台/测试脚本_test/test_AI确认API.py
git commit -m "feat: expose confirmed AI motion workflow"
```

---

### Task 5: AI Pending-Action Card In The Web UI

**Files:**
- Modify carefully, preserving existing edits: `Web控制台/frontend/app.js`
- Modify: `Web控制台/frontend/styles.css`
- Modify carefully, preserving existing edits: `Web控制台/frontend/index.html`
- Create: `Web控制台/测试脚本_test/test_AI动作确认界面.py`

**Interfaces:**
- Consumes: top-level `pending_action` from Agent ask/status and confirm/cancel endpoints.
- Produces: action-card UI with `pending`, `executing`, `executed`, `cancelled`, `expired`, and `invalidated` states.

- [ ] **Step 1: Write failing static UI tests**

Assert `app.js` contains `renderAgentPendingAction`, `confirmAgentPendingAction`, `cancelAgentPendingAction`, and the exact endpoints. Assert button labels are `确认执行` and `取消`, no `window.confirm` is used for this workflow, and J10 summary formatting uses `mm` while other joints use `°`.

- [ ] **Step 2: Run the UI test and verify failure**

```bash
mamba run -n momo_rebot python -m pytest Web控制台/测试脚本_test/test_AI动作确认界面.py -q
```

- [ ] **Step 3: Merge the pending card into the existing chat renderer**

Extend message records with an optional `pendingAction`. Render semantic rows for action, current, delta, target, speed and expiry. Use icon-free text buttons because these are explicit commands, keep card radius at `8px` or less, and disable both buttons during a request. A one-second timer updates remaining seconds and marks a local card expired at zero; the server remains authoritative.

```javascript
async function confirmAgentPendingAction(actionId) {
  setPendingActionState(actionId, "executing");
  try {
    const data = await postJson("/api/v1/agent/pending/confirm", { action_id: actionId }, { timeout: 70000 });
    setPendingActionState(actionId, "executed", data.message || "动作已执行");
    await Promise.allSettled([refreshSession(), refreshState(), loadActions(), refreshFollow()]);
  } catch (error) {
    setPendingActionState(actionId, "invalidated", error.message || String(error));
  }
}
```

`sendAgentMessage` attaches `data.pending_action` to the AI message. Reset, stop, mode changes and a newly received pending action invalidate older visible cards.

- [ ] **Step 4: Add responsive styles and update asset version**

Use a full-width compact card inside the message content, a two-column key/value grid that collapses to one column on narrow screens, fixed-height action buttons, and no nested panel/card styling. Update the existing script cache suffix without removing the user's `j10-mm` change.

- [ ] **Step 5: Run UI tests and commit only merged files**

```bash
mamba run -n momo_rebot python -m pytest \
  Web控制台/测试脚本_test/test_AI动作确认界面.py \
  Web控制台/测试脚本_test/test_快速控制关节单位.py -q
git diff --check
git add Web控制台/frontend/app.js Web控制台/frontend/styles.css Web控制台/frontend/index.html \
  Web控制台/测试脚本_test/test_AI动作确认界面.py \
  Web控制台/测试脚本_test/test_快速控制关节单位.py
git commit -m "feat: add AI motion confirmation card"
```

Before staging, verify the diff still contains the user's J10 millimetre readout and cache-version update.

---

### Task 6: Regression, Browser, And Dry-Run Verification

**Files:**
- Modify if assertions need correction: tests created in Tasks 1-5 only.
- Modify: `语音Agent/README_语音Agent.md`

**Interfaces:**
- Produces: documented operator flow and evidence that no real motion occurs during Mac verification.

- [ ] **Step 1: Run Python compilation and focused suites**

```bash
mamba run -n momo_rebot python -m py_compile \
  语音Agent/agent/安全策略_safety_policy.py \
  语音Agent/agent/工具桥接_tool_bridge.py \
  语音Agent/agent/OpenAI兼容客户端_openai_client.py \
  Web控制台/backend/agent_pending_action.py \
  Web控制台/backend/service.py Web控制台/backend/schemas.py Web控制台/backend/app.py
mamba run -n momo_rebot python -m pytest \
  语音Agent/测试脚本_test/test_*.py Web控制台/测试脚本_test/test_*.py -q
```

Expected: compilation succeeds and all discovered unit tests pass. Do not run microphone/STT/TTS interactive scripts as part of this suite.

- [ ] **Step 2: Start the Mac Web service in dry-run and test the API flow**

Use an unused port and a temporary Agent local override with real tools still false. Verify status query and stop are immediate; inject a test configuration with proposal permission in dry-run, request J12 `1°`, observe a pending action, cancel it, then repeat and confirm it. Confirm no real serial connection is opened.

- [ ] **Step 3: Verify the page at desktop and mobile widths**

Open the local Web page and capture screenshots at `1440x900` and `390x844`. Verify the action card is visible without overlapping chat input, long action names wrap, buttons do not shift layout, countdown updates, and confirm/cancel states remain readable.

- [ ] **Step 4: Document and commit**

Update the README with supported commands, exact confirmation phrase, boundaries, local override example, and emergency-stop behavior. Run `git diff --check`, then:

```bash
git add 语音Agent/README_语音Agent.md
git commit -m "docs: explain confirmed AI robot motion"
```

---

### Task 7: Board Backup, Limited Deployment, And Real Acceptance

**Files:**
- Board-local ignored file: `/home/fibo/MOMO_RobotARM/语音Agent/Agent配置.local.yaml`
- Mac backup destination: `~/MOMO_RobotARM-backups/qcs6490-odk/`
- Deploy: only source, test, template, prompt, and static files changed by Tasks 1-6.

**Interfaces:**
- Produces: board runtime with AI real tools enabled locally while GitHub template remains disabled.

- [ ] **Step 1: Preserve source and field data before deployment**

First complete Tasks 4 and 5 of `docs/superpowers/plans/2026-07-16-board-data-sync.md` so `scripts/backup_board_local_data.py`, the board cron job, `scripts/pull_board_backups_to_mac.py`, and the Mac LaunchAgent are installed and tested. Then verify SSH by mDNS, stop services that can write actions/config, create a timestamped repository-external source archive, run the field-data snapshot, pull the completed snapshot to this Mac, and verify its manifest/SHA-256. Abort if calibration, actions, vision configuration, or the snapshot manifest is missing. Do not alter the board Git history.

- [ ] **Step 2: Deploy an explicit file list**

Transfer only the files committed by this feature. Exclude `标定文件.json`, action/pose libraries, `*.local.yaml`, runtime state, logs, vision tuning, real hardware configuration, and recorded data. Run board-side `py_compile` for changed Python files and the new non-hardware unit tests.

- [ ] **Step 3: Create the board-local enablement file**

Write the ignored board-local file with no secrets:

```yaml
safety:
  allow_real_robot_tools: true
```

Restart the Web service, then verify `/api/v1/agent/status` reports real tools enabled and tool self-check passing. The tracked `Agent配置.yaml` must still report `false` in Git.

- [ ] **Step 4: Validate without servo movement first**

With the servo session disconnected, verify all six increasing-risk tools produce cards but confirmation fails with `REAL_SESSION_REQUIRED`. Verify `确认` does nothing, `确认执行` reaches the confirmation endpoint, expired/repeated IDs fail, and stop commands remain available.

- [ ] **Step 5: Perform supervised real acceptance in this order**

Clear the workspace and keep physical emergency stop available. Connect real mode at low speed, then test: immediate stop, J12 `+1°`, J10 within range, J11 within range, Home precheck/Home, one non-loop action, start vision follow, and immediate stop follow. Do not test by commanding physical boundary endpoints unless the present posture and cable clearance make that safe; boundary correctness is already covered by unit tests.

- [ ] **Step 6: Verify persistence and rollback**

Restart Web and confirm the ignored local override still enables the feature, field data is unchanged, and the Mac holds the pre-deploy snapshot. To roll back, set `allow_real_robot_tools: false` in the local override and restart; state queries and stop commands must remain usable.
