# Development Board Data Synchronization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make GitHub the single code/template baseline while keeping real calibration, poses, actions, and machine tuning local to the development board and copying verified daily snapshots to this Mac.

**Architecture:** Add one shared local-overlay configuration API and route Vision, Web, GUI, and real-control loaders through it. Stop tracking live hardware data, retain non-runnable examples, and add a manifest-based board snapshot tool plus a Mac pull/verification tool. Reconcile the board by preserving its current state outside Git, replacing its duplicate history with `origin/main`, and restoring only ignored local data.

**Tech Stack:** Python 3.11, PyYAML, Git, SSH, rsync, cron on Ubuntu, launchd on macOS, existing `momo_rebot` environment.

## Global Constraints

- Do not execute real robot movement during migration or verification.
- Never overwrite or delete `真实舵机控制/标定文件.json` without two verified copies.
- Do not use `git reset --hard` or `git checkout --` on the board.
- Preserve the board's current commit and dirty state through a backup branch, patch, untracked archive, and repository-external snapshot.
- GitHub contains defaults and examples only; live calibration, poses, actions, local overrides, and runtime state remain untracked.
- Local configuration precedence is base file, then sibling `*.local.yaml`, then environment/session overrides.
- Board and Mac retain 30 days of successful snapshots and at least one successful snapshot.
- Board-to-Mac synchronization is pull-only from the Mac; the board receives no Mac credential.

---

### Task 1: Shared Local Configuration Overlay

**Files:**
- Modify: `通用_io.py:20-110`
- Modify: `测试公共控制桥接_helpers.py:77-90`

**Interfaces:**
- Produces: `local_override_path(path: str | Path) -> Path`
- Produces: `read_structured_with_local(path: str | Path) -> dict[str, Any]`
- Produces: `read_config_with_local(path: str | Path, **extra: Any) -> dict[str, Any]`
- Produces: `read_structured_section_with_local(path: str | Path, section: str) -> dict[str, Any]`
- Produces: `update_local_structured_section(path: str | Path, section: str, value: Mapping[str, Any]) -> dict[str, Any]`

- [ ] **Step 1: Add failing overlay tests**

Add imports and assertions to `测试公共控制桥接_helpers.py`:

```python
from 通用_io import (
    local_override_path,
    read_config_with_local,
    read_structured_section_with_local,
    read_structured_with_local,
    update_local_structured_section,
)


def test_local_config_overlay() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = root / "配置.yaml"
        local = root / "配置.local.yaml"
        base.write_text("camera:\n  index: 0\n  width: 640\nfollow:\n  gain: 4.8\n", encoding="utf-8")
        local.write_text("camera:\n  index: 2\nfollow:\n  gain: 1.0\n", encoding="utf-8")
        assert local_override_path(base) == local
        merged = read_structured_with_local(base)
        assert merged["camera"] == {"index": 2, "width": 640}
        assert merged["follow"]["gain"] == 1.0
        assert read_structured_section_with_local(base, "camera") == {"index": 2, "width": 640}
        configured = read_config_with_local(base)
        assert configured["_config_path"] == str(base.resolve())


def test_local_update_does_not_modify_base() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = root / "配置.yaml"
        base.write_text("motion:\n  hz: 20\n", encoding="utf-8")
        original = base.read_text(encoding="utf-8")
        update_local_structured_section(base, "motion", {"hz": 60})
        assert base.read_text(encoding="utf-8") == original
        assert read_structured_with_local(base)["motion"]["hz"] == 60


def test_invalid_local_config_reports_path() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        base = root / "配置.yaml"
        local = root / "配置.local.yaml"
        base.write_text("motion:\n  hz: 20\n", encoding="utf-8")
        local.write_text("motion: [\n", encoding="utf-8")
        try:
            read_structured_with_local(base)
        except Exception as exc:
            assert str(local) in str(exc)
        else:
            raise AssertionError("invalid local YAML must fail")
```

Call the three tests from the file's existing main test sequence.

- [ ] **Step 2: Run the tests and verify they fail**

Run:

```bash
mamba run -n momo_rebot python 测试公共控制桥接_helpers.py
```

Expected: import failure for `local_override_path` or another new overlay function.

- [ ] **Step 3: Implement the shared overlay API**

Add to `通用_io.py`:

```python
def local_override_path(path: str | Path) -> Path:
    source = Path(path)
    return source.with_name(f"{source.stem}.local{source.suffix}")


def read_structured_with_local(path: str | Path) -> dict[str, Any]:
    source = Path(path)
    base = read_structured(source)
    override_path = local_override_path(source)
    if not override_path.exists():
        return base
    try:
        override = read_structured(override_path)
    except Exception as exc:
        raise ValueError(f"本机配置读取失败：{override_path}: {exc}") from exc
    return deep_merge(base, override)


def read_config_with_local(path: str | Path, **extra: Any) -> dict[str, Any]:
    source = Path(path).resolve()
    return attach_config_metadata(source, read_structured_with_local(source), **extra)


def read_structured_section_with_local(path: str | Path, section: str) -> dict[str, Any]:
    data = read_structured_with_local(path)
    value = data.get(section, {})
    return dict(value) if isinstance(value, Mapping) else {}


def update_local_structured_section(path: str | Path, section: str, value: Mapping[str, Any]) -> dict[str, Any]:
    target = local_override_path(path)
    local_data = read_structured(target) if target.exists() else {}
    previous = local_data.get(section, {})
    local_data[str(section)] = deep_merge(previous if isinstance(previous, Mapping) else {}, value)
    write_structured(target, local_data)
    return read_structured_with_local(path)
```

- [ ] **Step 4: Run shared tests**

Run:

```bash
mamba run -n momo_rebot python 测试公共控制桥接_helpers.py
```

Expected: all shared helper assertions pass.

- [ ] **Step 5: Commit the shared API**

```bash
git add 通用_io.py 测试公共控制桥接_helpers.py
git commit -m "feat: add local configuration overlays"
```

---

### Task 2: Route Runtime Configuration Through Local Overlays

**Files:**
- Modify: `视觉识别与跟随/视觉主程序_main.py:15-35`
- Modify: `GUI图形界面/GUI主程序_main.py:12-15`
- Modify: `GUI图形界面/gui_app/视觉配置工具_vision_config_utils.py:12-28`
- Modify: `Web控制台/backend/app.py:56-89`
- Modify: `Web控制台/backend/service.py:42,893-966,1413-1435`
- Modify: `真实舵机控制/标定工具_calibration_utils.py:23,49-60`
- Modify: `真实舵机控制/真实机械臂控制器_real_arm_controller.py:730-744`
- Test: `系统集成/测试脚本_test/01_配置加载测试.py`
- Test: `Web控制台/测试脚本_test/test_连续控制_service.py`

**Interfaces:**
- Consumes: Task 1 overlay functions.
- Produces: Vision/Web/GUI/real-control effective configs with identical merge precedence.
- Produces: Web follow and motion settings persisted only to sibling local files.

- [ ] **Step 1: Add failing entrypoint tests**

Extend `系统集成/测试脚本_test/01_配置加载测试.py` with temporary base/local configs and assert:

```python
assert load_vision_config(temp_vision_root)["camera"]["camera_index"] == 2
assert load_web_config(temp_web_path)["motion"]["continuous_update_hz"] == 60.0
```

Extend `Web控制台/测试脚本_test/test_连续控制_service.py` so a temporary `Web配置.yaml` remains byte-identical after `_persist_motion_tuning`, while `Web配置.local.yaml` contains the saved `motion` section.

- [ ] **Step 2: Run targeted tests and verify failure**

```bash
mamba run -n momo_rebot python 系统集成/测试脚本_test/01_配置加载测试.py
mamba run -n momo_rebot python Web控制台/测试脚本_test/test_连续控制_service.py
```

Expected: local values are ignored or base configuration is modified.

- [ ] **Step 3: Replace configuration reads**

Apply these replacements:

```python
# Vision standalone
from 通用_io import env_int, env_value, read_structured_with_local
config = read_structured_with_local(config_path)

# GUI main
from 通用_io import read_config_with_local
return read_config_with_local(BASE_DIR / "GUI配置.yaml")

# GUI vision utility
from 通用_io import read_config_with_local, read_structured_section_with_local
return read_config_with_local(Path(vision_root) / "视觉配置.yaml")
return read_structured_section_with_local(Path(vision_root) / "视觉配置.yaml", section)

# Web app
from 通用_io import env_int, env_value, read_config_with_local
config = read_config_with_local(config_path)

# Real calibration and controller loaders
from 通用_io import env_value, read_structured_with_local
config = read_structured_with_local(config_path)
```

- [ ] **Step 4: Persist Web changes to local files**

In `Web控制台/backend/service.py`:

```python
from 通用_io import (
    read_json_object,
    read_structured_section_with_local,
    update_local_structured_section,
)
```

Use `read_structured_section_with_local` for effective reads. In `set_follow_config`, pass only the normalized request `payload` to:

```python
effective = update_local_structured_section(config_path, "follow", payload)
follow = dict(effective.get("follow", {}))
```

In `_persist_motion_tuning`, replace `update_structured_section` with:

```python
update_local_structured_section(path, "motion", persisted_motion)
```

Return local file paths in `saved`, using `local_override_path(path)`.

- [ ] **Step 5: Run targeted and existing follow tests**

```bash
mamba run -n momo_rebot python 系统集成/测试脚本_test/01_配置加载测试.py
mamba run -n momo_rebot python Web控制台/测试脚本_test/test_连续控制_service.py
mamba run -n momo_rebot python 视觉识别与跟随/测试脚本_test/05_dry_run视觉跟随测试.py
```

Expected: all pass, base files remain unchanged, and effective values include local overrides.

- [ ] **Step 6: Commit runtime overlay integration**

```bash
git add 通用_io.py 视觉识别与跟随 GUI图形界面 Web控制台 真实舵机控制 系统集成/测试脚本_test/01_配置加载测试.py
git commit -m "feat: keep machine tuning in local configs"
```

---

### Task 3: Separate Templates From Live Robot Data

**Files:**
- Modify: `.gitignore`
- Create: `真实舵机控制/标定文件.example.json`
- Delete from Git tracking: `真实舵机控制/标定文件.json`
- Create: `仿真控制系统/姿态管理/姿态库.example.json`
- Delete from Git tracking: `仿真控制系统/姿态管理/姿态库.json`
- Create: `仿真控制系统/姿态管理/动作库_示例/挥手.json`
- Delete from Git tracking: `仿真控制系统/姿态管理/动作库/挥手.json`
- Create: `动作录制与回放增强/录制记录/recorded_pose_sequence.example.json`
- Delete from Git tracking: `动作录制与回放增强/录制记录/recorded_pose_sequence.json`
- Modify: `动作录制与回放增强/动作文件管理_action_library.py:31-85`
- Modify: `动作录制与回放增强/动作录制器_action_recorder.py:78-80`
- Modify: `仿真控制系统/姿态管理/姿态管理_pose_manager.py:24-100`
- Test: `动作录制与回放增强/测试脚本_test/08_现场数据写前备份测试.py`

**Interfaces:**
- Produces: `backup_before_replace(path: str | Path, backup_dir: str | Path | None = None) -> Path | None` in `通用_io.py`.
- Live files retain their existing runtime paths but are ignored by Git.
- Example calibration is never loaded automatically.

- [ ] **Step 1: Add failing write-before-replace tests**

Create `动作录制与回放增强/测试脚本_test/08_现场数据写前备份测试.py` to save the same pose, action, and recording twice in a temporary directory and assert the previous JSON appears in a sibling `历史备份_backups` directory before the new content replaces it.

Core assertion:

```python
backups = list((target.parent / "历史备份_backups").glob(f"{target.stem}_backup_*.json"))
assert len(backups) == 1
assert json.loads(backups[0].read_text(encoding="utf-8")) == first_payload
```

- [ ] **Step 2: Run the new test and verify failure**

```bash
mamba run -n momo_rebot python 动作录制与回放增强/测试脚本_test/08_现场数据写前备份测试.py
```

Expected: no historical backup exists.

- [ ] **Step 3: Add the shared pre-write backup helper**

Add to `通用_io.py`:

```python
def backup_before_replace(path: str | Path, backup_dir: str | Path | None = None) -> Path | None:
    source = Path(path)
    if not source.exists() or not source.is_file():
        return None
    directory = Path(backup_dir) if backup_dir else source.parent / "历史备份_backups"
    directory.mkdir(parents=True, exist_ok=True)
    target = timestamped_json_path(directory, f"{source.stem}_backup")
    counter = 1
    while target.exists():
        target = target.with_name(f"{target.stem}_{counter}{target.suffix}")
        counter += 1
    import shutil

    shutil.copy2(source, target)
    return target
```

Call it immediately before `atomic_write_json` in pose, action-library, and recorder save paths.

- [ ] **Step 4: Replace tracked live files with examples and ignores**

Add these rules to `.gitignore`:

```gitignore
*.local.yaml
*.local.yml
真实舵机控制/标定文件.json
真实舵机控制/标定备份_backups/
仿真控制系统/姿态管理/姿态库.json
仿真控制系统/姿态管理/动作库/
动作录制与回放增强/动作库/
动作录制与回放增强/录制记录/*
Web控制台/runtime/
视觉识别与跟随/runtime/
!动作录制与回放增强/录制记录/*.example.json
```

Create examples from current schemas. Set calibration `home_present_raw` and `home_present_wrapped_raw` to `0`, add `"template": true` under `_meta`, and do not copy current real board values into the example.

Remove only from Git tracking while leaving local working copies available until deployment:

```bash
git rm --cached 真实舵机控制/标定文件.json
git rm --cached 仿真控制系统/姿态管理/姿态库.json
git rm --cached 仿真控制系统/姿态管理/动作库/挥手.json
git rm --cached 动作录制与回放增强/录制记录/recorded_pose_sequence.json
```

- [ ] **Step 5: Verify ignore and template behavior**

```bash
git check-ignore -v \
  真实舵机控制/标定文件.json \
  仿真控制系统/姿态管理/姿态库.json \
  仿真控制系统/姿态管理/动作库/现场动作.json \
  Web控制台/runtime/state/session_state.json
git check-ignore 真实舵机控制/标定文件.example.json && exit 1 || true
mamba run -n momo_rebot python 动作录制与回放增强/测试脚本_test/08_现场数据写前备份测试.py
```

Expected: live files are ignored, example files are not ignored, and backup tests pass.

- [ ] **Step 6: Commit data ownership changes**

```bash
git add .gitignore 通用_io.py 真实舵机控制 仿真控制系统/姿态管理 动作录制与回放增强
git commit -m "feat: separate robot templates from live data"
```

---

### Task 4: Board Snapshot Creation and Retention

**Files:**
- Create: `scripts/backup_board_local_data.py`
- Create: `scripts/install_board_backup_cron.sh`
- Create: `系统集成/测试脚本_test/test_开发板现场数据备份.py`
- Modify: `docs/README.md`

**Interfaces:**
- Produces: `create_snapshot(project_root: Path, backup_root: Path, now: datetime) -> Path`
- Produces: `verify_snapshot(snapshot_dir: Path) -> None`
- Produces: `prune_snapshots(snapshot_root: Path, retention_days: int, now: datetime) -> list[Path]`
- CLI defaults: project root from script parent, backup root `$HOME/MOMO_RobotARM-local-backups`, retention 30 days.

- [ ] **Step 1: Write failing snapshot tests**

Create temporary project data containing local configs, calibration, pose, action, cinematic project, and excluded log/latest-frame files. Assert the snapshot contains only important files, `manifest.json` has relative path/size/SHA-256 entries, verification passes, a changed file fails verification, incomplete temporary snapshots are ignored, and pruning retains the newest successful snapshot.

- [ ] **Step 2: Run and verify failure**

```bash
mamba run -n momo_rebot python 系统集成/测试脚本_test/test_开发板现场数据备份.py
```

Expected: `scripts.backup_board_local_data` cannot be imported.

- [ ] **Step 3: Implement snapshot creation**

Use these exact source paths in `backup_board_local_data.py`:

```python
BACKUP_PATHS = (
    "GUI图形界面/GUI配置.local.yaml",
    "Web控制台/Web配置.local.yaml",
    "真实舵机控制/真实配置.local.yaml",
    "真实舵机控制/标定文件.json",
    "真实舵机控制/标定备份_backups",
    "视觉识别与跟随/视觉配置.local.yaml",
    "仿真控制系统/姿态管理/姿态库.json",
    "仿真控制系统/姿态管理/动作库",
    "动作录制与回放增强/动作库",
    "动作录制与回放增强/录制记录",
    "视觉识别与跟随/runtime/cinematic_director_projects",
    "视觉识别与跟随/runtime/cinematic_records",
)
```

Copy into `<backup_root>/snapshots/.partial-<timestamp>`, write `manifest.json`, verify every checksum, then rename to `<timestamp>`. The manifest must include `schema_version`, UTC `created_at`, absolute `project_root`, and sorted `files` entries. Refuse to finish a snapshot if calibration exists but any of `j10` through `j15` is absent.

- [ ] **Step 4: Add idempotent cron installation**

`install_board_backup_cron.sh` must preserve unrelated crontab entries and replace only lines between:

```text
# BEGIN MOMO ROBOTARM BACKUP
# END MOMO ROBOTARM BACKUP
```

Install this daily command at 03:15 and run one snapshot immediately:

```cron
15 3 * * * /home/fibo/miniforge3/bin/python /home/fibo/MOMO_RobotARM/scripts/backup_board_local_data.py >> /home/fibo/MOMO_RobotARM-local-backups/backup.log 2>&1
```

- [ ] **Step 5: Run snapshot tests and a local temporary smoke test**

```bash
mamba run -n momo_rebot python 系统集成/测试脚本_test/test_开发板现场数据备份.py
tmpdir="$(mktemp -d)"
mamba run -n momo_rebot python scripts/backup_board_local_data.py --project-root "$PWD" --backup-root "$tmpdir" --retention-days 30
find "$tmpdir/snapshots" -maxdepth 2 -type f -name manifest.json -print
rm -rf "$tmpdir"
```

Expected: tests pass and exactly one completed snapshot manifest is printed.

- [ ] **Step 6: Commit board backup tooling**

```bash
git add scripts/backup_board_local_data.py scripts/install_board_backup_cron.sh 系统集成/测试脚本_test/test_开发板现场数据备份.py docs/README.md
git commit -m "feat: back up development board data"
```

---

### Task 5: Mac Pull, Verification, and LaunchAgent

**Files:**
- Create: `scripts/pull_board_backups_to_mac.py`
- Create: `scripts/com.momo.robotarm.backup.plist.example`
- Create: `scripts/install_mac_backup_launch_agent.sh`
- Create: `系统集成/测试脚本_test/test_Mac拉取开发板备份.py`
- Modify: `docs/README.md`

**Interfaces:**
- Produces: `pull_snapshots(host: str, remote_root: str, local_root: Path) -> None`
- Consumes: Task 4 `verify_snapshot` and `prune_snapshots`.
- CLI defaults: host `fibo@qcs6490-odk.local`, remote root `/home/fibo/MOMO_RobotARM-local-backups`, local root `~/MOMO_RobotARM-backups/qcs6490-odk`, retention 30 days.

- [ ] **Step 1: Write failing pull tests**

Mock `subprocess.run` to assert SSH is called with `BatchMode=yes`, rsync uses `--partial` without `--delete`, completed snapshots are verified, checksum failure returns nonzero, and SSH failure leaves existing local snapshots untouched.

- [ ] **Step 2: Run and verify failure**

```bash
mamba run -n momo_rebot python 系统集成/测试脚本_test/test_Mac拉取开发板备份.py
```

Expected: pull module import fails.

- [ ] **Step 3: Implement pull and verification**

Use commands equivalent to:

```python
ssh = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", host]
rsync = [
    "rsync", "-a", "--partial", "--prune-empty-dirs",
    f"{host}:{remote_root.rstrip('/')}/snapshots/",
    str(local_root / "snapshots") + "/",
]
```

First verify SSH and the remote snapshots directory, then rsync, verify every local directory containing `manifest.json`, prune verified snapshots older than 30 days, and never pass `--delete`.

- [ ] **Step 4: Implement LaunchAgent installation**

The plist must use label `com.momo.robotarm.backup`, `RunAtLoad=true`, a daily `StartCalendarInterval` at 03:45, and log files under `~/Library/Logs/MOMORobotArmBackup/`. The installer expands the current home/project paths into `~/Library/LaunchAgents/com.momo.robotarm.backup.plist`, validates it with `plutil -lint`, then uses:

```bash
launchctl bootout "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.momo.robotarm.backup.plist" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$HOME/Library/LaunchAgents/com.momo.robotarm.backup.plist"
launchctl kickstart -k "gui/$(id -u)/com.momo.robotarm.backup"
```

- [ ] **Step 5: Run tests and a manual SSH dry run**

```bash
mamba run -n momo_rebot python 系统集成/测试脚本_test/test_Mac拉取开发板备份.py
ssh -o BatchMode=yes -o ConnectTimeout=5 fibo@qcs6490-odk.local 'echo ok'
```

Expected: tests pass and SSH prints `ok`.

- [ ] **Step 6: Commit Mac backup tooling**

```bash
git add scripts/pull_board_backups_to_mac.py scripts/com.momo.robotarm.backup.plist.example scripts/install_mac_backup_launch_agent.sh 系统集成/测试脚本_test/test_Mac拉取开发板备份.py docs/README.md
git commit -m "feat: mirror board backups to macOS"
```

---

### Task 6: Repository Verification and Publication

**Files:**
- Modify as required by failures from Tasks 1-5 only.

**Interfaces:**
- Produces: a tested GitHub baseline that can be deployed without live data.

- [ ] **Step 1: Run static validation**

```bash
mamba run -n momo_rebot python -m py_compile \
  通用_io.py \
  Web控制台/backend/app.py \
  Web控制台/backend/service.py \
  GUI图形界面/GUI主程序_main.py \
  GUI图形界面/gui_app/视觉配置工具_vision_config_utils.py \
  视觉识别与跟随/视觉主程序_main.py \
  真实舵机控制/标定工具_calibration_utils.py \
  真实舵机控制/真实机械臂控制器_real_arm_controller.py \
  scripts/backup_board_local_data.py \
  scripts/pull_board_backups_to_mac.py
git diff --check
```

Expected: no output from `git diff --check`; compilation exits zero.

- [ ] **Step 2: Run the focused regression suite**

```bash
mamba run -n momo_rebot python 测试公共控制桥接_helpers.py
mamba run -n momo_rebot python 系统集成/测试脚本_test/01_配置加载测试.py
mamba run -n momo_rebot python Web控制台/测试脚本_test/test_连续控制_service.py
mamba run -n momo_rebot python 视觉识别与跟随/测试脚本_test/05_dry_run视觉跟随测试.py
mamba run -n momo_rebot python 动作录制与回放增强/测试脚本_test/08_现场数据写前备份测试.py
mamba run -n momo_rebot python 系统集成/测试脚本_test/test_开发板现场数据备份.py
mamba run -n momo_rebot python 系统集成/测试脚本_test/test_Mac拉取开发板备份.py
```

Expected: all scripts pass.

- [ ] **Step 3: Confirm repository ownership rules**

```bash
git ls-files | rg '标定文件\.json$|姿态库\.json$|/动作库/|/runtime/' && exit 1 || true
git ls-files | rg '标定文件\.example\.json$|姿态库\.example\.json$|动作库_示例'
git status --short --branch
```

Expected: no live files in the first search, examples in the second, and a clean worktree.

- [ ] **Step 4: Push the Mac baseline to GitHub**

```bash
GIT_TERMINAL_PROMPT=0 git push origin main
```

Expected: `main` advances successfully and `git status --short --branch` shows `main...origin/main` with no divergence.

---

### Task 7: Preserve and Reconcile the Development Board

**Files:**
- Board repository: `/home/fibo/MOMO_RobotARM`
- Board backup root: `/home/fibo/MOMO_RobotARM-local-backups`
- Mac backup root: `~/MOMO_RobotARM-backups/qcs6490-odk`

**Interfaces:**
- Consumes: published GitHub baseline and Tasks 4-5 tools.
- Produces: board `main == origin/main`, ignored board-local data restored, verified snapshots on board and Mac.

- [ ] **Step 1: Capture a repository-external pre-migration backup**

Run from the Mac:

```bash
ssh fibo@qcs6490-odk.local '
  set -eu
  cd /home/fibo/MOMO_RobotARM
  stamp=$(date +%Y%m%d-%H%M%S)
  root=/home/fibo/MOMO_RobotARM-local-backups/migration-$stamp
  mkdir -p "$root"
  git status --short --branch > "$root/git-status.txt"
  git log --oneline --decorate -20 > "$root/git-log.txt"
  git diff --binary > "$root/tracked-changes.patch"
  git ls-files --others --exclude-standard -z > "$root/untracked-files.zlist"
  tar --null -czf "$root/untracked-files.tar.gz" -T "$root/untracked-files.zlist"
  tar --ignore-failed-read -czf "$root/live-data.tar.gz" \
    真实舵机控制/标定文件.json \
    真实舵机控制/标定备份_backups \
    仿真控制系统/姿态管理/姿态库.json \
    仿真控制系统/姿态管理/动作库 \
    动作录制与回放增强/动作库 \
    动作录制与回放增强/录制记录 \
    视觉识别与跟随/runtime/cinematic_director_projects \
    视觉识别与跟随/runtime/cinematic_records
  cp -a 真实舵机控制/标定文件.json "$root/标定文件.json"
  test -s "$root/标定文件.json"
  test -s "$root/live-data.tar.gz"
  printf "%s\n" "$root"
'
```

Expected: prints a migration directory and every command exits zero.

- [ ] **Step 2: Verify J10-J15 in both calibration copies**

```bash
ssh fibo@qcs6490-odk.local '
  ~/miniforge3/bin/mamba run -n momo_rebot python - <<"PY"
import json
from pathlib import Path

path = Path("/home/fibo/MOMO_RobotARM/真实舵机控制/标定文件.json")
data = json.loads(path.read_text(encoding="utf-8"))
missing = [joint for joint in ("j10", "j11", "j12", "j13", "j14", "j15") if joint not in data]
assert not missing, missing
print(path, "ok")
PY
'
```

Expected: `标定文件.json ok`.

- [ ] **Step 3: Preserve the old Git state without changing files**

```bash
ssh fibo@qcs6490-odk.local '
  set -eu
  cd /home/fibo/MOMO_RobotARM
  for pattern in "python 启动Web服务.py" "python 视觉主程序_main.py service"; do
    pids=$(pgrep -f "$pattern" || true)
    if [ -n "$pids" ]; then kill $pids; fi
  done
  sleep 2
  stamp=$(date +%Y%m%d-%H%M%S)
  git branch "backup/board-pre-sync-$stamp"
  git stash push -u -m "pre-board-data-sync-$stamp"
  git fetch --prune origin
  git switch -c "codex/board-sync-$stamp" origin/main
  git branch -f main origin/main
  git switch main
  git status --short --branch
'
```

Expected: clean `main...origin/main`. The backup branch and stash remain available.

- [ ] **Step 4: Restore only local data and construct local overrides**

Restore actual data from the migration directory's `live-data.tar.gz`, not by applying the complete stash. Create:

```yaml
# 视觉识别与跟随/视觉配置.local.yaml
camera:
  camera_index: 2
  width: 1280
  height: 720
follow:
  pan_sign: 1.0
  tilt_sign: 1.0
  pan_gain_deg_per_norm: 1.0
  tilt_gain_deg_per_norm: 1.0
```

```yaml
# 真实舵机控制/真实配置.local.yaml
transport:
  port: /dev/momo-servo
  driver_backend: sdk
```

Restore the saved `标定文件.json`, pose/action directories, and recorded/cinematic data. Extract board motion tuning from the saved patch into `Web配置.local.yaml` and `GUI配置.local.yaml`, using `continuous_update_hz: 60.0` and preserving the saved direction overrides.

- [ ] **Step 5: Confirm local data is ignored and code is clean**

```bash
ssh fibo@qcs6490-odk.local '
  cd /home/fibo/MOMO_RobotARM
  git check-ignore -v \
    真实舵机控制/标定文件.json \
    视觉识别与跟随/视觉配置.local.yaml \
    Web控制台/Web配置.local.yaml \
    GUI图形界面/GUI配置.local.yaml \
    仿真控制系统/姿态管理/姿态库.json
  git status --short --branch
'
```

Expected: all local files are ignored and status is clean `main...origin/main`.

- [ ] **Step 6: Install and execute board backup**

```bash
ssh fibo@qcs6490-odk.local '
  cd /home/fibo/MOMO_RobotARM
  bash scripts/install_board_backup_cron.sh
  ~/miniforge3/bin/mamba run -n momo_rebot python scripts/backup_board_local_data.py
'
```

Expected: one verified snapshot and the managed cron block are present.

- [ ] **Step 7: Run board-side non-motion verification**

```bash
ssh fibo@qcs6490-odk.local '
  cd /home/fibo/MOMO_RobotARM
  ~/miniforge3/bin/mamba run -n momo_rebot python -m py_compile \
    Web控制台/backend/service.py \
    Web控制台/backend/schemas.py \
    视觉识别与跟随/vision/视觉跟随_controller.py \
    scripts/backup_board_local_data.py
  ~/miniforge3/bin/mamba run -n momo_rebot python 视觉识别与跟随/测试脚本_test/05_dry_run视觉跟随测试.py
  ~/miniforge3/bin/mamba run -n momo_rebot python \
    真实舵机控制/诊断舵机总线_lightweight_sdk.py \
    --port /dev/momo-servo --no-gripper
'
```

Expected: compilation and dry-run pass; read-only scan detects IDs 10-15. Stop here on communication errors and do not send movement commands.

- [ ] **Step 8: Install Mac LaunchAgent and pull the first snapshot**

```bash
bash scripts/install_mac_backup_launch_agent.sh
mamba run -n momo_rebot python scripts/pull_board_backups_to_mac.py
launchctl print "gui/$(id -u)/com.momo.robotarm.backup" | sed -n '1,80p'
find "$HOME/MOMO_RobotARM-backups/qcs6490-odk/snapshots" -name manifest.json -print
```

Expected: LaunchAgent state is visible and at least one verified Mac manifest is printed.

- [ ] **Step 9: Restart services and confirm effective local configuration**

Restart the Web and vision services using the established `setsid -f` pattern, then verify:

```bash
curl -fsS http://qcs6490-odk.local:8010/api/v1/follow/config
curl -fsS http://qcs6490-odk.local:8000/status
curl -fsS http://qcs6490-odk.local:8000/latest
ssh fibo@qcs6490-odk.local 'cd /home/fibo/MOMO_RobotARM && git status --short --branch'
```

Expected: camera index 2, 1280x720 frames, J11/J13 follow joints, gain 1.0, follow stopped until explicitly started, and a clean board worktree.

---

## Plan Self-Review

- Every design requirement maps to Tasks 1-7.
- Live calibration is never generated from or replaced by the example.
- The board is backed up before any stash or branch change.
- Duplicate board commits are preserved but not pushed.
- Board sync does not use destructive reset or checkout commands.
- Mac synchronization never uses `rsync --delete`.
- Hardware verification is read-only and visual follow remains dry-run.
