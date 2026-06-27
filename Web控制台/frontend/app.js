const API_BASE = "";
const SAFE_TEXT = "我确认机械臂周围安全";
const JOINTS = [
  ["j10", "J10 底盘导轨"],
  ["j11", "J11 底座旋转"],
  ["j12", "J12 肩部抬升"],
  ["j13", "J13 肘部弯曲"],
  ["j14", "J14 腕部俯仰"],
  ["j15", "J15 腕部旋转"],
];
const CART_AXES = ["+X", "-X", "+Y", "-Y", "+Z", "-Z", "+RX", "-RX", "+RY", "-RY", "+RZ", "-RZ"];

const state = {
  config: null,
  session: { mode: "dry_run", connected: false },
  robot: null,
  logs: [],
  lastError: "",
  ws: null,
  wsOnline: false,
  pending: new Set(),
  lastIkTargets: null,
  follow: null,
  hardware: null,
  motionTuning: null,
  kinematicsStatus: null,
  recording: null,
  agent: null,
  agentMessages: [],
  lastAgentReply: null,
  cinematic: null,
  cinematicProject: null,
  cinematicProjectPath: "",
  cinematicGeneratedAction: "",
  visionLiveTimer: null,
  latestVision: null,
  visionMockActive: false,
  jointControlMode: "step",
  continuousJogActive: false,
  continuousJogStopping: false,
  continuousJogPointerId: null,
  continuousJogButton: null,
  j12Diagnostic: null,
  batchDiagnostics: null,
  modeSelectDirty: false,
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  $("#apiAddress").textContent = `API: ${location.origin}`;
  buildJointControls();
  buildJogDirectionOverrides();
  buildFkInputs();
  buildJogButtons();
  bindEvents();
  await loadConfig();
  await refreshAll();
  connectWebSocket();
}

function bindEvents() {
  $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.page)));
  $("#topStopBtn").addEventListener("click", stopNow);
  $("#quickStopBtn").addEventListener("click", stopNow);
  $("#refreshStateBtn").addEventListener("click", refreshState);
  $("#homeBtn").addEventListener("click", homeWithPrecheck);
  $("#jointStepModeBtn").addEventListener("click", () => setJointControlMode("step"));
  $("#jointContinuousModeBtn").addEventListener("click", () => setJointControlMode("continuous"));
  $("#gripperSlider").addEventListener("input", () => updateGripperLabel(Number($("#gripperSlider").value)));
  $("#gripperOpenBtn").addEventListener("click", () => setGripper(1));
  $("#gripperCloseBtn").addEventListener("click", () => setGripper(0));
  $("#gripperApplyBtn").addEventListener("click", () => setGripper(Number($("#gripperSlider").value) / 100));
  $("#savePoseBtn").addEventListener("click", savePose);
  $("#pauseActionBtn").addEventListener("click", () => postJsonLogged("/api/v1/actions/pause", {}));
  $("#resumeActionBtn").addEventListener("click", () => postJsonLogged("/api/v1/actions/resume", {}));
  $("#stopActionBtn").addEventListener("click", () => postJsonLogged("/api/v1/actions/stop", {}));
  $("#startRecordingBtn").addEventListener("click", startActionRecording);
  $("#captureRecordingBtn").addEventListener("click", captureActionRecording);
  $("#saveRecordingBtn").addEventListener("click", saveActionRecording);
  $("#cancelRecordingBtn").addEventListener("click", cancelActionRecording);
  $("#refreshFollowBtn").addEventListener("click", refreshFollow);
  $("#startFollowBtn").addEventListener("click", startFollow);
  $("#stopFollowBtn").addEventListener("click", stopFollow);
  $("#followLatestUrl").addEventListener("input", () => {
    $("#followLatestUrl").dataset.userEdited = "1";
    renderVisionPreviewUrl();
  });
  $("#refreshVisionPreviewBtn").addEventListener("click", refreshVisionPreview);
  $("#toggleVisionLiveBtn").addEventListener("click", toggleVisionLivePreview);
  $("#loadVisionMockBtn").addEventListener("click", loadVisionMock);
  $("#clearVisionMockBtn").addEventListener("click", clearVisionMock);
  $("#selectVisionTargetBtn").addEventListener("click", selectVisionTarget);
  $("#resetVisionTargetBtn").addEventListener("click", resetVisionTarget);
  $("#refreshVisionTargetBtn").addEventListener("click", refreshVisionTargetState);
  $("#visionPreviewFrame").addEventListener("load", () => renderVisionOverlay(state.latestVision));
  $("#visionPreviewFrame").addEventListener("click", handleVisionFrameClick);
  window.addEventListener("resize", () => renderVisionOverlay(state.latestVision));
  $("#refreshAgentBtn").addEventListener("click", loadAgentStatus);
  $("#sendAgentBtn").addEventListener("click", sendAgentMessage);
  $("#resetAgentBtn").addEventListener("click", resetAgentSession);
  $("#clearAgentChatBtn").addEventListener("click", clearAgentChat);
  $$(".agent-quick-btn").forEach((btn) => btn.addEventListener("click", () => useAgentPrompt(btn.dataset.agentPrompt || "")));
  $("#refreshCinematicBtn").addEventListener("click", loadCinematicStatus);
  $("#analyzeCinematicBtn").addEventListener("click", analyzeCinematicLatest);
  $("#keyframesCinematicBtn").addEventListener("click", generateCinematicKeyframes);
  $("#generateCinematicActionBtn").addEventListener("click", generateCinematicAction);
  $("#playCinematicActionBtn").addEventListener("click", playGeneratedCinematicAction);
  $("#cinematicRecordsList").addEventListener("click", handleCinematicRecordClick);
  $("#cinematicProjectsList").addEventListener("click", handleCinematicProjectClick);
  $("#agentInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendAgentMessage();
  });
  $("#kinRefreshBtn").addEventListener("click", refreshState);
  $("#kinStatusBtn").addEventListener("click", loadKinematicsStatus);
  $("#kinRenderBtn").addEventListener("click", refreshKinematicsRender);
  $("#fkBtn").addEventListener("click", computeFk);
  $("#ikBtn").addEventListener("click", computeIk);
  $("#executeIkBtn").addEventListener("click", executeIk);
  $("#refreshCalibrationBtn").addEventListener("click", loadCalibration);
  $("#j12DiagnoseBtn").addEventListener("click", diagnoseJ12);
  $("#j12ApplyCalibrationBtn").addEventListener("click", applyJ12Calibration);
  $("#batchDiagnoseBtn").addEventListener("click", diagnoseBatchCalibration);
  $("#fillBatchFromDiagnosisBtn").addEventListener("click", fillBatchCalibrationFromDiagnostics);
  $("#applyBatchCalibrationBtn").addEventListener("click", applyBatchCalibration);
  $("#refreshDepsBtn").addEventListener("click", loadDependencies);
  $("#refreshHardwareBtn").addEventListener("click", loadHardwareCheck);
  $("#saveMotionTuningBtn").addEventListener("click", saveMotionTuning);
  $("#resetMotionTuningBtn").addEventListener("click", resetMotionTuning);
  $("#modeSelect").addEventListener("change", () => {
    state.modeSelectDirty = true;
  });
  $("#connectBtn").addEventListener("click", connectSession);
  $("#disconnectBtn").addEventListener("click", disconnectSession);
  $("#switchModeBtn").addEventListener("click", switchMode);
  $("#clearLogBtn").addEventListener("click", clearLogs);
  $("#miniClearLogBtn").addEventListener("click", clearLogs);
  $("#copyErrorBtn").addEventListener("click", copyLastError);
  window.addEventListener("pointerup", stopContinuousJogFromPointer);
  window.addEventListener("pointercancel", stopContinuousJogFromPointer);
  window.addEventListener("blur", () => stopContinuousJog());
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) stopContinuousJog();
  });
}

async function requestJson(path, options = {}) {
  const timeout = options.timeout ?? 5000;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeout);
  try {
    const response = await fetch(API_BASE + path, {
      method: options.method || "GET",
      headers: { "Content-Type": "application/json" },
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });
    const payload = await response.json();
    if (!payload.ok) {
      const err = payload.error || { code: "HTTP_ERROR", message: `HTTP ${response.status}` };
      throw new ApiError(err.code, err.message);
    }
    return payload.data;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new ApiError("TIMEOUT", "请求超时。");
    }
    throw error;
  } finally {
    clearTimeout(timer);
  }
}

function getJson(path, options = {}) {
  return requestJson(path, options);
}

function postJson(path, body = {}, options = {}) {
  return requestJson(path, { ...options, method: "POST", body });
}

function deleteJson(path, options = {}) {
  return requestJson(path, { ...options, method: "DELETE" });
}

async function postJsonLogged(path, body = {}, options = {}) {
  return withPending(path, async () => {
    try {
      const data = await postJson(path, body, options);
      log("info", `${path} 成功`);
      await refreshState();
      return data;
    } catch (error) {
      showError(error);
      throw error;
    }
  });
}

async function loadConfig() {
  try {
    state.config = await getJson("/api/v1/config");
    renderConfig();
  } catch (error) {
    showError(error);
  }
}

async function refreshAll() {
  await Promise.allSettled([refreshSession(), refreshState(), refreshFollow(), loadMotionTuning(), loadKinematicsStatus(), loadPoses(), loadActions(), loadCalibration(), loadDependencies()]);
}

async function refreshSession() {
  try {
    state.session = await getJson("/api/v1/session/status");
    renderSession();
  } catch (error) {
    showError(error);
  }
}

async function refreshState() {
  try {
    state.robot = await getJson("/api/v1/robot/state");
    renderRobot();
  } catch (error) {
    showError(error);
  }
}

async function loadPoses() {
  try {
    const data = await getJson("/api/v1/poses");
    renderPoses(data.poses || []);
  } catch (error) {
    showError(error);
  }
}

async function loadActions() {
  try {
    const data = await getJson("/api/v1/actions");
    renderActions(data.actions || []);
    await loadRecordingStatus();
  } catch (error) {
    showError(error);
  }
}

async function loadRecordingStatus() {
  try {
    const data = await getJson("/api/v1/actions/recording/status");
    state.recording = data.recording || {};
    renderRecordingStatus();
  } catch (error) {
    showError(error);
  }
}

async function loadCalibration() {
  try {
    const data = await getJson("/api/v1/robot/calibration-status");
    renderCalibration(data.calibration || {});
  } catch (error) {
    showError(error);
  }
}

async function loadDependencies() {
  try {
    const data = await getJson("/api/v1/robot/dependencies");
    renderDependencies(data);
  } catch (error) {
    showError(error);
  }
}

async function loadHardwareCheck() {
  try {
    state.hardware = await getJson("/api/v1/robot/hardware-check", { timeout: 10000 });
    renderHardwareCheck();
  } catch (error) {
    showError(error);
  }
}

async function loadMotionTuning() {
  try {
    state.motionTuning = await getJson("/api/v1/motion/tuning");
    renderMotionTuning();
  } catch (error) {
    showError(error);
  }
}

async function loadKinematicsStatus() {
  try {
    state.kinematicsStatus = await getJson("/api/v1/kinematics/status", { timeout: 12000 });
    renderKinematicsStatus();
    refreshKinematicsRender();
  } catch (error) {
    showError(error);
  }
}

function refreshKinematicsRender() {
  const img = $("#kinRenderImage");
  const stateEl = $("#kinRenderState");
  stateEl.textContent = "刷新中";
  stateEl.className = "inline-status";
  img.onload = () => {
    stateEl.textContent = `已刷新 ${new Date().toLocaleTimeString()}`;
    stateEl.className = "inline-status ok-text";
  };
  img.onerror = () => {
    stateEl.textContent = "快照失败";
    stateEl.className = "inline-status bad-text";
  };
  img.src = `/api/v1/kinematics/render.jpg?width=960&height=640&t=${Date.now()}`;
}

async function refreshFollow() {
  try {
    state.follow = await getJson("/api/v1/follow/status");
    renderFollow();
  } catch (error) {
    showError(error);
  }
}

async function loadAgentStatus() {
  try {
    state.agent = await getJson("/api/v1/agent/status");
    renderAgentStatus();
  } catch (error) {
    showError(error);
  }
}

async function loadCinematicStatus() {
  try {
    state.cinematic = await getJson("/api/v1/cinematic/status", { timeout: 8000 });
    renderCinematicStatus();
    if (!$("#cinematicRecordPath").value && state.cinematic?.latest_record?.path) {
      $("#cinematicRecordPath").value = state.cinematic.latest_record.path;
    }
    if (!$("#cinematicProjectPath").value && state.cinematic?.latest_project?.path) {
      $("#cinematicProjectPath").value = state.cinematic.latest_project.path;
    }
    await loadCinematicProject();
  } catch (error) {
    showError(error);
  }
}

async function loadCinematicProject(projectPath = "") {
  const selectedPath = projectPath || $("#cinematicProjectPath").value.trim() || state.cinematic?.latest_project?.path || "";
  if (!selectedPath) {
    state.cinematicProject = null;
    state.cinematicProjectPath = "";
    renderCinematicProject(null);
    return;
  }
  try {
    const query = new URLSearchParams({ project_path: selectedPath });
    const data = await getJson(`/api/v1/cinematic/project?${query.toString()}`, { timeout: 8000 });
    state.cinematicProject = data.project || null;
    state.cinematicProjectPath = data.project_path || selectedPath;
    $("#cinematicProjectPath").value = state.cinematicProjectPath;
    renderCinematicProject(state.cinematicProject);
  } catch (error) {
    state.cinematicProject = null;
    state.cinematicProjectPath = "";
    renderCinematicProject(null);
    showError(error);
  }
}

async function analyzeCinematicLatest() {
  const recordPath = $("#cinematicRecordPath").value.trim() || state.cinematic?.latest_record?.path || "";
  if (!recordPath) {
    showError(new ApiError("NO_CINEMATIC_RECORD", "没有可分析的试拍记录。"));
    return;
  }
  try {
    const data = await postJson("/api/v1/cinematic/analyze", { record_path: recordPath }, { timeout: 30000 });
    $("#cinematicResultJson").textContent = JSON.stringify(summarizeCinematicResult(data), null, 2);
    state.cinematicProjectPath = data.project_path || "";
    if (state.cinematicProjectPath) $("#cinematicProjectPath").value = state.cinematicProjectPath;
    renderCinematicProject(data.project || null);
    await loadCinematicStatus();
    log("info", "AI 运镜试拍分析完成");
  } catch (error) {
    showError(error);
  }
}

async function generateCinematicKeyframes() {
  const projectPath = currentCinematicProjectPath();
  if (!projectPath) {
    showError(new ApiError("NO_CINEMATIC_PROJECT", "没有可生成关键帧的导演项目。"));
    return;
  }
  const minCount = clampInt(Number($("#cinematicMinKeyframes").value || 3), 3, 8);
  const maxCount = clampInt(Number($("#cinematicMaxKeyframes").value || 8), minCount, 8);
  try {
    const data = await postJson("/api/v1/cinematic/keyframes", { project_path: projectPath, min_count: minCount, max_count: maxCount }, { timeout: 30000 });
    $("#cinematicResultJson").textContent = JSON.stringify(summarizeCinematicResult(data), null, 2);
    state.cinematicProjectPath = data.project_path || projectPath;
    renderCinematicProject(data.project || null);
    await loadCinematicStatus();
    log("info", "AI 运镜关键帧已生成");
  } catch (error) {
    showError(error);
  }
}

async function generateCinematicAction() {
  const projectPath = currentCinematicProjectPath();
  if (!projectPath) {
    showError(new ApiError("NO_CINEMATIC_PROJECT", "没有可生成动作的导演项目。"));
    return;
  }
  try {
    const data = await postJson(
      "/api/v1/cinematic/generate-action",
      { project_path: projectPath, action_name: $("#cinematicActionName").value.trim() },
      { timeout: 30000 }
    );
    $("#cinematicResultJson").textContent = JSON.stringify(summarizeCinematicResult(data), null, 2);
    state.cinematicProjectPath = data.project_path || projectPath;
    state.cinematicGeneratedAction = data.action_name || data.project?.generated_action?.name || "";
    renderCinematicProject(data.project || null);
    await Promise.allSettled([loadCinematicStatus(), loadActions()]);
    log("info", "AI 运镜动作已生成");
  } catch (error) {
    showError(error);
  }
}

async function playGeneratedCinematicAction() {
  const name = state.cinematicGeneratedAction || state.cinematicProject?.generated_action?.name || "";
  if (!name) {
    showError(new ApiError("NO_CINEMATIC_ACTION", "当前导演项目还没有生成动作。"));
    return;
  }
  try {
    await playAction(name);
  } catch (error) {
    showError(error);
  }
}

function currentCinematicProjectPath() {
  return $("#cinematicProjectPath").value.trim() || state.cinematicProjectPath || state.cinematic?.latest_project?.path || "";
}

function clampInt(value, min, max) {
  if (!Number.isFinite(value)) return min;
  return Math.max(min, Math.min(max, Math.round(value)));
}

function handleCinematicRecordClick(event) {
  const row = event.target.closest("[data-cinematic-record-path]");
  if (!row) return;
  $("#cinematicRecordPath").value = row.dataset.cinematicRecordPath || "";
  log("info", `已选择试拍记录：${row.dataset.cinematicRecordName || ""}`);
}

function handleCinematicProjectClick(event) {
  const row = event.target.closest("[data-cinematic-project-path]");
  if (!row) return;
  const path = row.dataset.cinematicProjectPath || "";
  $("#cinematicProjectPath").value = path;
  loadCinematicProject(path);
}

function connectWebSocket() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${scheme}://${location.host}/api/v1/ws/state`);
  state.ws = ws;
  ws.onopen = () => {
    state.wsOnline = true;
    renderWs();
    log("info", "WebSocket 已连接");
  };
  ws.onmessage = (event) => {
    const msg = JSON.parse(event.data);
    if (msg.type === "state") {
      state.session = msg.data.session || state.session;
      state.robot = msg.data.robot || state.robot;
      if (msg.data.continuous_jog) renderContinuousJog(msg.data.continuous_jog);
      if (msg.data.error) state.lastError = msg.data.error.message || "";
      renderSession();
      renderRobot();
      renderWs();
    } else if (msg.type === "error") {
      showError(new ApiError("WS_ERROR", msg.message));
    }
  };
  ws.onclose = () => {
    state.wsOnline = false;
    renderWs();
    log("error", "WebSocket 已断开，准备重连");
    setTimeout(connectWebSocket, 1200);
  };
  ws.onerror = () => {
    state.wsOnline = false;
    renderWs();
  };
}

function buildJointControls() {
  const wrap = $("#jointControls");
  wrap.innerHTML = "";
  JOINTS.forEach(([key, label]) => {
    const row = document.createElement("div");
    row.className = "joint-row";
    row.innerHTML = `
      <span class="joint-name">${label}</span>
      <button data-joint="${key}" data-dir="-1">-</button>
      <span class="joint-value" id="joint-${key}">--°</span>
      <button data-joint="${key}" data-dir="1">+</button>
    `;
    wrap.appendChild(row);
  });
  wrap.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-joint]");
    if (!btn || state.jointControlMode !== "step") return;
    const step = selectedJointStep() * Number(btn.dataset.dir);
    jointStep(btn.dataset.joint, step);
  });
  wrap.addEventListener("pointerdown", (event) => {
    const btn = event.target.closest("button[data-joint]");
    if (!btn || state.jointControlMode !== "continuous") return;
    event.preventDefault();
    btn.setPointerCapture?.(event.pointerId);
    startContinuousJog(btn.dataset.joint, Number(btn.dataset.dir), event.pointerId, btn);
  });
}

function buildJogDirectionOverrides() {
  const wrap = $("#jogDirectionOverrides");
  if (!wrap) return;
  wrap.innerHTML = JOINTS.map(([key, label]) => `
    <label class="direction-field">
      <span>${escapeHtml(label)}</span>
      <select data-jog-direction="${key}">
        <option value="1">正常</option>
        <option value="-1">反向</option>
      </select>
    </label>
  `).join("");
}

function buildFkInputs() {
  const wrap = $("#fkInputs");
  wrap.innerHTML = JOINTS.map(([key, label]) => `<input id="fk-${key}" type="number" step="0.1" placeholder="${label}" />`).join("");
}

function buildJogButtons() {
  const wrap = $("#cartJogButtons");
  wrap.innerHTML = CART_AXES.map((axis) => `<button data-axis="${axis}">${axis}</button>`).join("");
  wrap.addEventListener("click", (event) => {
    const btn = event.target.closest("button[data-axis]");
    if (!btn) return;
    cartesianJog(btn.dataset.axis);
  });
}

function selectedJointStep() {
  let value = Number($("#jointStepSelect").value || 2);
  const realLimit = Number(state.config?.safety?.max_real_step_deg || 3);
  if ((state.session.mode || state.robot?.mode) === "real" && value > realLimit) {
    value = realLimit;
    $("#jointStepSelect").value = String(realLimit);
    log("info", `真实模式步长已限制为 ${realLimit} deg/mm`);
  }
  return value;
}

function setJointControlMode(mode) {
  state.jointControlMode = mode === "continuous" ? "continuous" : "step";
  $("#jointStepModeBtn").classList.toggle("active", state.jointControlMode === "step");
  $("#jointContinuousModeBtn").classList.toggle("active", state.jointControlMode === "continuous");
  $("#jointStepSelect").disabled = state.jointControlMode === "continuous";
  $("#continuousSpeedInput").disabled = state.jointControlMode !== "continuous";
  if (state.jointControlMode === "step") stopContinuousJog();
}

async function jointStep(jointKey, delta) {
  const speed = Number(state.motionTuning?.default_speed_percent || 50);
  const body = await withSafety({ joint_key: jointKey, delta_deg: delta, speed_percent: speed });
  if (!body) return;
  await postJsonLogged("/api/v1/motion/joint-step", body);
}

async function startContinuousJog(jointKey, direction, pointerId = null, button = null) {
  if (state.continuousJogActive || state.continuousJogStopping) await stopContinuousJog();
  const body = await withSafety({
    joint_key: jointKey,
    direction,
    speed_deg_s: Number($("#continuousSpeedInput").value || 5),
  });
  if (!body) return;
  try {
    state.continuousJogActive = true;
    state.continuousJogPointerId = pointerId;
    state.continuousJogButton = button;
    state.continuousJogButton?.classList.add("active-jog");
    renderContinuousJog({ running: true, joint_key: jointKey, speed_deg_s: body.speed_deg_s, update_hz: state.motionTuning?.continuous_update_hz });
    const data = await postJson("/api/v1/motion/continuous-jog/start", body);
    renderContinuousJog(data.jog || { running: true, joint_key: jointKey });
  } catch (error) {
    state.continuousJogActive = false;
    clearContinuousJogPointer();
    showError(error);
  }
}

async function stopContinuousJog() {
  if (!state.continuousJogActive || state.continuousJogStopping) return;
  state.continuousJogStopping = true;
  try {
    const data = await postJson("/api/v1/motion/continuous-jog/stop", {});
    renderContinuousJog(data.jog || { running: false });
    await refreshState();
  } catch (error) {
    showError(error);
  } finally {
    state.continuousJogActive = false;
    state.continuousJogStopping = false;
    clearContinuousJogPointer();
  }
}

function stopContinuousJogFromPointer(event) {
  if (!state.continuousJogActive) return;
  if (state.continuousJogPointerId !== null && event.pointerId !== state.continuousJogPointerId) return;
  stopContinuousJog();
}

function clearContinuousJogPointer() {
  try {
    state.continuousJogButton?.releasePointerCapture?.(state.continuousJogPointerId);
  } catch (_) {}
  state.continuousJogButton?.classList.remove("active-jog");
  state.continuousJogPointerId = null;
  state.continuousJogButton = null;
}

async function setGripper(openRatio) {
  if (state.robot?.gripper?.available === false) {
    showError(new ApiError("GRIPPER_UNAVAILABLE", "当前没有安装夹爪舵机。"));
    return;
  }
  updateGripperLabel(openRatio * 100);
  $("#gripperSlider").value = Math.round(openRatio * 100);
  const body = await withSafety({ open_ratio: openRatio, wait: true });
  if (!body) return;
  await postJsonLogged("/api/v1/motion/gripper", body);
}

async function postDanger(path, body) {
  const safe = await withSafety(body);
  if (!safe) return;
  await postJsonLogged(path, safe);
}

async function homeWithPrecheck() {
  try {
    const precheck = await getJson("/api/v1/motion/home-precheck", { timeout: 10000 });
    const messages = Array.isArray(precheck.messages) ? precheck.messages.filter(Boolean) : [];
    log(
      precheck.ok === false ? "error" : "info",
      `Home 预检查：${precheck.message || (precheck.ok === false ? "未通过" : "通过")}`
    );
    if (precheck.ok === false) {
      showError(new ApiError("HOME_PRECHECK_FAILED", messages.join("；") || "Home 预检查未通过。"));
      return;
    }
    await postDanger("/api/v1/motion/home", { speed_percent: 50 });
  } catch (error) {
    showError(error);
  }
}

async function savePose() {
  const name = $("#poseNameInput").value.trim();
  if (!name) {
    showError(new ApiError("BAD_INPUT", "请输入姿态名称。"));
    return;
  }
  try {
    await postJsonLogged("/api/v1/poses/save", { name, description: $("#poseDescInput").value.trim() });
    await loadPoses();
  } catch (_) {}
}

async function gotoPose(name) {
  const body = await withSafety({ name, speed_percent: 50 });
  if (!body) return;
  try {
    await postJsonLogged("/api/v1/poses/goto", body);
  } catch (_) {}
}

async function deletePose(name) {
  try {
    await withPending(`pose-${name}`, () => deleteJson(`/api/v1/poses/${encodeURIComponent(name)}`));
    $("#poseDetailName").textContent = "未选择";
    $("#poseDetailSummary").textContent = "请选择一个姿态。";
    $("#poseDetailResult").textContent = "";
    log("info", `已删除姿态：${name}`);
    await loadPoses();
  } catch (error) {
    showError(error);
  }
}

async function showPoseDetail(name) {
  try {
    const data = await getJson(`/api/v1/poses/${encodeURIComponent(name)}`);
    renderPoseDetail(name, data);
    log("info", `姿态详情已加载：${name}`);
  } catch (error) {
    showError(error);
  }
}

async function playAction(name) {
  const body = await withSafety({
    name,
    speed: Number($("#actionSpeed").value || 1),
    loop: $("#actionLoop").checked,
  });
  if (!body) return;
  await postJsonLogged("/api/v1/actions/play", body, { timeout: 10000 });
}

async function startActionRecording() {
  const fallback = `Web录制_${new Date().toTimeString().slice(0, 8).replaceAll(":", "")}`;
  const name = $("#recordingNameInput").value.trim() || fallback;
  const source = $("#recordingSourceSelect").value || "web_record";
  const body = await withSafety({ name, source }, source === "web_teach_mode");
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/actions/recording/start", body);
    state.recording = data.recording || {};
    renderRecordingStatus();
  } catch (_) {}
}

async function captureActionRecording() {
  const body = await withSafety({});
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/actions/recording/capture", body);
    state.recording = data.recording || {};
    renderRecordingStatus(data.pose || null);
  } catch (_) {}
}

async function saveActionRecording() {
  try {
    const data = await postJsonLogged("/api/v1/actions/recording/save", {});
    state.recording = data.recording || {};
    renderRecordingStatus();
    await loadActions();
  } catch (_) {}
}

async function cancelActionRecording() {
  try {
    const data = await postJsonLogged("/api/v1/actions/recording/cancel", {});
    state.recording = data.recording || {};
    renderRecordingStatus();
  } catch (_) {}
}

async function computeFk() {
  const joints = JOINTS.map(([key]) => Number($(`#fk-${key}`).value || state.robot?.joints_deg?.[key] || 0));
  try {
    const data = await postJson("/api/v1/kinematics/fk", { joints_deg: joints });
    $("#fkResult").textContent = JSON.stringify(data, null, 2);
    log("info", "FK 计算完成");
  } catch (error) {
    showError(error);
  }
}

async function computeIk() {
  const xyz = [Number($("#ikX").value), Number($("#ikY").value), Number($("#ikZ").value)];
  const rpyRaw = [$("#ikR").value, $("#ikP").value, $("#ikYaw").value];
  const hasRpy = rpyRaw.some((v) => v !== "");
  const rpy = hasRpy ? rpyRaw.map((v) => Number(v || 0)) : null;
  try {
    const data = await postJson("/api/v1/kinematics/ik", { xyz, rpy });
    state.lastIkTargets = data.target_joints_deg || null;
    $("#ikResult").textContent = JSON.stringify(data, null, 2);
    log("info", "IK 计算完成");
  } catch (error) {
    showError(error);
  }
}

async function executeIk() {
  if (!state.lastIkTargets) {
    showError(new ApiError("NO_IK", "请先计算 IK。"));
    return;
  }
  const body = await withSafety({ targets_deg: state.lastIkTargets, speed_percent: 50 });
  if (!body) return;
  await postJsonLogged("/api/v1/motion/move-joints", body);
}

async function cartesianJog(axis) {
  const body = await withSafety({
    axis,
    coord_frame: $("#jogFrame").value,
    step_dist_mm: Number($("#cartStepMm").value || 5),
    step_angle_deg: Number($("#cartStepDeg").value || 5),
    speed_percent: 50,
  });
  if (!body) return;
  await postJsonLogged("/api/v1/motion/cartesian-jog", body);
}

async function connectSession() {
  const mode = $("#modeSelect").value;
  const body = await withSafety({ mode }, mode === "real");
  if (!body) return;
  await postJsonLogged("/api/v1/session/connect", body);
  state.modeSelectDirty = false;
  await refreshSession();
}

async function disconnectSession() {
  await postJsonLogged("/api/v1/session/disconnect", {});
  state.modeSelectDirty = false;
  await refreshSession();
}

async function switchMode() {
  const mode = $("#modeSelect").value;
  const body = await withSafety({ mode }, mode === "real");
  if (!body) return;
  await postJsonLogged("/api/v1/session/mode", body);
  state.modeSelectDirty = false;
  await refreshSession();
}

async function startFollow() {
  const dryRun = $("#followDryRun").checked;
  const body = await withSafety(
    {
      latest_url: $("#followLatestUrl").value.trim() || "http://127.0.0.1:8000/latest",
      poll_interval: Number($("#followPollInterval").value || 0.05),
      speed_percent: Number($("#followSpeedPercent").value || 60),
      dry_run: dryRun,
      pan_joint: "j11",
      tilt_joint: "j13",
      rail_enabled: $("#railEnabled").checked,
      rail_start_mm: Number($("#railStartMm").value || -140),
      rail_end_mm: Number($("#railEndMm").value || 140),
      rail_speed_mm_s: Number($("#railSpeedMmS").value || 5),
    },
    !dryRun
  );
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/follow/start", body);
    state.follow = data.follow || null;
    renderFollow();
  } catch (_) {}
}

async function stopFollow() {
  try {
    const data = await postJsonLogged("/api/v1/follow/stop", {});
    state.follow = data.follow || null;
    renderFollow();
  } catch (_) {}
}

async function sendAgentMessage() {
  const input = $("#agentInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendAgentMessage("我", text, "user");
  $("#agentReplyDetail").textContent = "AI 正在处理...";
  $("#sendAgentBtn").disabled = true;
  try {
    const data = await postJson("/api/v1/agent/ask", { text, speak: false }, { timeout: 70000 });
    state.lastAgentReply = data;
    appendAgentMessage("AI", data.reply || data.message || "已完成。", "ai");
    renderAgentReplyDetail(data);
    log("info", "AI 对话完成");
  } catch (error) {
    appendAgentMessage("ERROR", error.message || String(error), "error");
    $("#agentReplyDetail").textContent = error.message || String(error);
    showError(error);
  } finally {
    $("#sendAgentBtn").disabled = false;
  }
}

async function resetAgentSession() {
  try {
    await postJson("/api/v1/agent/reset-session", {}, { timeout: 10000 });
    state.agentMessages = [];
    state.lastAgentReply = null;
    renderAgentMessages();
    $("#agentReplyDetail").textContent = "等待 AI 回复。";
    appendAgentMessage("SYSTEM", "AI 会话已重置。", "system");
  } catch (error) {
    showError(error);
  }
}

function clearAgentChat() {
  state.agentMessages = [];
  state.lastAgentReply = null;
  renderAgentMessages();
  $("#agentReplyDetail").textContent = "聊天记录已清空；后端会话未重置。";
}

function useAgentPrompt(text) {
  const input = $("#agentInput");
  input.value = text;
  input.focus();
}

async function stopNow() {
  try {
    await postJson("/api/v1/motion/stop", {});
    log("info", "急停请求已发送");
    await refreshState();
  } catch (error) {
    showError(error);
  }
}

async function withSafety(body, force = false) {
  const mode = state.session.mode || state.robot?.mode || $("#modeSelect")?.value;
  if (force || mode === "real") {
    return { ...body, confirm_text: SAFE_TEXT };
  }
  return body;
}

function renderConfig() {
  const cfg = state.config || {};
  const paths = cfg.controller || {};
  $("#configPaths").innerHTML = Object.entries(paths)
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`)
    .join("");
  const latestUrl = cfg.follow?.latest_url || "http://127.0.0.1:8000/latest";
  if ($("#followLatestUrl") && !$("#followLatestUrl").dataset.userEdited) {
    $("#followLatestUrl").value = latestUrl;
  }
  renderVisionPreviewUrl();
}

function renderSession() {
  const mode = state.session.mode || state.robot?.mode || "dry_run";
  const connected = Boolean(state.session.connected);
  $("#modePill").textContent = `模式 ${mode}`;
  $("#modePill").className = `status-pill ${mode === "real" ? "bad" : mode === "dry_run" ? "warn" : "good"}`;
  $("#connectionPill").textContent = connected ? "已连接" : "未连接";
  $("#connectionPill").className = `status-pill ${connected ? "good" : "warn"}`;
  if (!state.modeSelectDirty) {
    $("#modeSelect").value = mode;
  }
}

function renderWs() {
  $("#wsPill").textContent = state.wsOnline ? "WS 在线" : "WS 离线";
  $("#wsPill").className = `status-pill ${state.wsOnline ? "good" : "bad"}`;
}

function renderFollow() {
  const follow = state.follow || {};
  const rail = follow.rail || {};
  const last = follow.last_command || {};
  const commands = Array.isArray(last.commands) ? last.commands : [];
  $("#followRunning").textContent = follow.running ? "运行" : "停止";
  $("#followDryRunState").textContent = follow.dry_run === false ? "真实" : "dry-run";
  $("#followStepCount").textContent = String(follow.step_count ?? 0);
  $("#followRailState").textContent = rail.enabled
    ? `${rail.running ? "运行" : rail.phase || "停止"} ${formatNum(rail.virtual_pos_mm, 2)}mm`
    : "关闭";
  $("#followLastCommand").textContent = commands.length
    ? commands.map((cmd) => `${cmd.joint_key}:${formatNum(cmd.delta_deg, 2)}`).join(", ")
    : last.message || "--";
}

function renderAgentStatus() {
  const agent = state.agent || {};
  $("#agentStatusState").textContent = agent.available ? "可用" : "不可用";
  $("#agentStatusState").className = `status-pill ${agent.available ? "good" : "bad"}`;
  $("#agentBackend").textContent = agent.backend || "--";
  $("#agentModel").textContent = agent.model || "--";
  $("#agentApiBase").textContent = agent.api_base || "--";
  $("#agentRobotApi").textContent = agent.robot_api_base || "--";
  $("#agentSttUrl").textContent = agent.stt_url ? `${agent.stt_provider || "http"} ${agent.stt_url}` : "--";
  $("#agentTtsEnabled").textContent = agent.tts_enabled ? `开启 ${agent.tts_url || ""}` : "关闭";
  $("#agentMaxTurns").textContent = agent.max_turns ? String(agent.max_turns) : "--";
  $("#agentRealTools").textContent = agent.allow_real_robot_tools ? "允许" : "禁止";
  $("#agentRealTools").className = agent.allow_real_robot_tools ? "bad-text" : "ok-text";
  $("#agentToolsResult").textContent = JSON.stringify(
    {
      available: agent.available,
      backend: agent.backend,
      model: agent.model,
      allowed_tools: agent.allowed_tools || [],
      allow_real_robot_tools: Boolean(agent.allow_real_robot_tools),
      message: agent.message || "",
    },
    null,
    2
  );
}

function appendAgentMessage(role, text, kind) {
  state.agentMessages.push({ role, text, kind, time: new Date().toLocaleTimeString() });
  state.agentMessages = state.agentMessages.slice(-80);
  renderAgentMessages();
}

function renderAgentMessages() {
  $("#agentChatLog").innerHTML = state.agentMessages
    .map(
      (item) => `<div class="agent-message ${escapeAttr(item.kind)}">
        <strong>[${escapeHtml(item.role)}]</strong>
        <span>${escapeHtml(item.text).replace(/\n/g, "<br>")}</span>
      </div>`
    )
    .join("");
  $("#agentChatLog").scrollTop = $("#agentChatLog").scrollHeight;
}

function renderAgentReplyDetail(data) {
  $("#agentReplyDetail").textContent = JSON.stringify(
    {
      message: data.message || "",
      session_id: data.session_id || "",
      reply_chars: String(data.reply || "").length,
      raw_payload: data.raw_payload || {},
    },
    null,
    2
  );
}

function renderCinematicStatus() {
  const data = state.cinematic || {};
  $("#cinematicStatusState").textContent = data.available ? "可用" : "不可用";
  $("#cinematicStatusState").className = `status-pill ${data.available ? "good" : "bad"}`;
  $("#cinematicLatestRecord").textContent = data.latest_record?.name || "--";
  $("#cinematicLatestProject").textContent = data.latest_project?.name || "--";
  $("#cinematicRecordDir").textContent = shortPath(data.record_dir || "");
  $("#cinematicProjectDir").textContent = shortPath(data.project_dir || "");
  $("#cinematicConfigJson").textContent = JSON.stringify({ rail: data.rail || {}, two_step: data.two_step || {} }, null, 2);
  renderCinematicFileList("#cinematicRecordsList", data.records || [], "record");
  renderCinematicFileList("#cinematicProjectsList", data.projects || [], "project");
}

function renderCinematicProject(project) {
  const item = project || {};
  const stage = item.workflow_stage || "--";
  const generated = item.generated_action || {};
  state.cinematicGeneratedAction = project ? generated.name || state.cinematicGeneratedAction || "" : "";
  $("#cinematicProjectStage").textContent = project ? `阶段：${stage}${generated.name ? ` / 动作：${generated.name}` : ""}` : "未加载项目";
  $("#cinematicAnalysisText").textContent = item.motion_analysis ? formatCinematicAnalysis(item) : "等待试拍分析。";
  $("#cinematicKeyframesText").textContent = Array.isArray(item.director_keyframes) ? formatCinematicKeyframes(item.director_keyframes) : "等待关键帧生成。";
  $("#cinematicTrajectoryText").textContent = item.trajectory_plan || item.generated_action ? formatCinematicTrajectory(item) : "等待轨迹生成。";
}

function formatCinematicAnalysis(project) {
  const analysis = project.motion_analysis || {};
  const lines = ["视频运动质量分析", "", JSON.stringify(analysis.summary || {}, null, 2), "", "抖动区间"];
  for (const item of analysis.jitter_intervals || []) {
    lines.push(`- ${item.start_time}s -> ${item.end_time}s | frame ${item.start_frame}..${item.end_frame}`);
  }
  lines.push("", "稳定区间");
  for (const item of analysis.stable_intervals || []) {
    lines.push(`- ${item.start_time}s -> ${item.end_time}s | frame ${item.start_frame}..${item.end_frame}`);
  }
  lines.push("", "候选关键帧");
  for (const item of analysis.candidate_keyframes || []) {
    lines.push(`- frame ${item.frame_index} / ${item.time}s | score ${item.score}: ${item.reason}`);
  }
  return lines.join("\n");
}

function formatCinematicKeyframes(keyframes) {
  const lines = ["Keyframe List", ""];
  for (const item of keyframes || []) {
    if (!item || typeof item !== "object") continue;
    lines.push(
      `${item.id || "K?"}:`,
      `- time: ${item.time}s / frame ${item.frame_index}`,
      `- pose: ${JSON.stringify(item.pose || {})}`,
      `- composition: ${item.composition || ""}`,
      `- reason: ${item.reason || ""}`,
      `- dwell_time: ${item.dwell_time || 0}`,
      ""
    );
  }
  return lines.join("\n");
}

function formatCinematicTrajectory(project) {
  const trajectory = project.trajectory_plan || {};
  const generated = project.generated_action || {};
  return [
    "Trajectory",
    `- type: ${trajectory.type || "--"}`,
    `- action: ${generated.name || "--"} (${generated.pose_count || 0} points)`,
    `- action_path: ${generated.path || "--"}`,
    `- blending strategy: ${JSON.stringify(trajectory.blending_strategy || {})}`,
    `- speed profile: ${JSON.stringify(trajectory.speed_profile || {})}`,
    `- recommended execution: ${JSON.stringify(trajectory.recommended_execution || {})}`,
  ].join("\n");
}

function summarizeCinematicResult(data) {
  const project = data.project || {};
  const analysis = project.motion_analysis || {};
  return {
    message: data.message,
    project_path: data.project_path,
    action_name: data.action_name,
    action_path: data.action_path,
    pose_count: data.pose_count,
    workflow_stage: project.workflow_stage,
    summary: analysis.summary,
    keyframe_count: Array.isArray(data.keyframes) ? data.keyframes.length : Array.isArray(project.director_keyframes) ? project.director_keyframes.length : undefined,
    generated_action: project.generated_action,
  };
}

function renderCompactFileList(selector, items) {
  const wrap = $(selector);
  wrap.innerHTML = items.length
    ? items
        .map(
          (item) => `<div class="compact-list-row">
            <strong>${escapeHtml(item.name)}</strong>
            <span>${formatFileSize(item.size)} · ${new Date(Number(item.modified_at || 0) * 1000).toLocaleString()}</span>
          </div>`
        )
        .join("")
    : `<div class="empty-text">暂无文件</div>`;
}

function renderCinematicFileList(selector, items, kind) {
  const wrap = $(selector);
  wrap.innerHTML = items.length
    ? items
        .map((item) => {
          const attrs =
            kind === "record"
              ? `data-cinematic-record-path="${escapeAttr(item.path || "")}" data-cinematic-record-name="${escapeAttr(item.name || "")}"`
              : `data-cinematic-project-path="${escapeAttr(item.path || "")}" data-cinematic-project-name="${escapeAttr(item.name || "")}"`;
          return `<button class="compact-list-row compact-list-button" ${attrs}>
            <strong>${escapeHtml(item.name)}</strong>
            <span>${formatFileSize(item.size)} · ${new Date(Number(item.modified_at || 0) * 1000).toLocaleString()}</span>
          </button>`;
        })
        .join("")
    : `<div class="empty-text">暂无文件</div>`;
}

function refreshVisionPreview() {
  state.visionMockActive = false;
  const image = $("#visionPreviewFrame");
  const url = renderVisionPreviewUrl();
  if (!url) return;
  $("#visionPreviewState").textContent = "刷新中";
  image.onload = () => {
    $("#visionPreviewState").textContent = "已更新";
  };
  image.onerror = () => {
    $("#visionPreviewState").textContent = "无法读取视觉服务";
  };
  image.src = `${url}${url.includes("?") ? "&" : "?"}t=${Date.now()}`;
  refreshVisionProxyStatus();
}

function loadVisionMock() {
  state.visionMockActive = true;
  if (state.visionLiveTimer) {
    clearInterval(state.visionLiveTimer);
    state.visionLiveTimer = null;
    $("#toggleVisionLiveBtn").textContent = "开始实时刷新";
  }
  const latest = buildVisionMockLatest();
  const image = $("#visionPreviewFrame");
  image.onload = () => renderVisionOverlay(latest);
  image.src = buildVisionMockFrameDataUrl();
  $("#visionPreviewUrl").textContent = "mock://vision/latest";
  $("#visionPreviewState").textContent = "模拟目标已加载";
  $("#visionHealthState").textContent = "mock camera ok";
  $("#visionHealthState").className = "ok-text";
  $("#visionEngineState").textContent = "mock / camera 0 / frame 1";
  $("#visionEngineState").className = "ok-text";
  $("#visionLatestState").textContent = "检测到模拟目标";
  $("#visionLatestState").className = "ok-text";
  renderVisionTargetState({
    target_mode: "mock",
    tracking_state: "locked",
    target: latest.target,
  });
  renderVisionLatestDebug(latest);
}

function clearVisionMock() {
  state.visionMockActive = false;
  $("#visionPreviewState").textContent = "模拟已退出";
  refreshVisionPreview();
}

function toggleVisionLivePreview() {
  if (state.visionLiveTimer) {
    clearInterval(state.visionLiveTimer);
    state.visionLiveTimer = null;
    $("#toggleVisionLiveBtn").textContent = "开始实时刷新";
    $("#visionPreviewState").textContent = "实时刷新已停止";
    return;
  }
  refreshVisionPreview();
  state.visionLiveTimer = setInterval(refreshVisionPreview, 500);
  $("#toggleVisionLiveBtn").textContent = "停止实时刷新";
}

function renderVisionPreviewUrl() {
  const frameUrl = "/api/v1/vision/frame.jpg";
  $("#visionPreviewUrl").textContent = frameUrl || "--";
  return frameUrl;
}

function frameUrlFromLatest(latestUrl) {
  try {
    const url = new URL(latestUrl, location.origin);
    url.pathname = url.pathname.replace(/\/latest\/?$/, "/frame.jpg");
    url.search = "";
    return url.toString();
  } catch (_) {
    return "";
  }
}

async function refreshVisionProxyStatus() {
  try {
    const [health, latest, targetState, engineStatus] = await Promise.all([
      getJson("/api/v1/vision/health", { timeout: 3000 }),
      getJson("/api/v1/vision/latest", { timeout: 3000 }),
      getJson("/api/v1/vision/target/state", { timeout: 3000 }),
      getJson("/api/v1/vision/status", { timeout: 3000 }),
    ]);
    $("#visionHealthState").textContent = health.camera_available ? "camera ok" : health.running ? "running" : "未启动";
    $("#visionHealthState").className = health.camera_available ? "ok-text" : "bad-text";
    renderVisionEngineStatus(engineStatus);
    $("#visionLatestState").textContent = latest.detected ? "检测到目标" : latest.message || "未检测";
    $("#visionLatestState").className = latest.detected ? "ok-text" : "";
    renderVisionTargetState(targetState);
    renderVisionLatestDebug(latest);
  } catch (error) {
    $("#visionHealthState").textContent = "视觉服务不可用";
    $("#visionHealthState").className = "bad-text";
    $("#visionEngineState").textContent = "--";
    $("#visionLatestState").textContent = error.message || String(error);
    $("#visionLatestJson").textContent = "";
    state.latestVision = null;
    renderVisionOverlay(null);
  }
}

async function refreshVisionTargetState() {
  try {
    const targetState = await getJson("/api/v1/vision/target/state", { timeout: 3000 });
    renderVisionTargetState(targetState);
  } catch (error) {
    showError(error);
  }
}

function renderVisionTargetState(targetState) {
  const mode = targetState.target_mode || "--";
  const tracking = targetState.tracking_state || "--";
  const bbox = targetState.tracker_last_bbox || targetState.manual_reference_bbox || targetState.target?.bbox || null;
  $("#visionTargetToolState").textContent = Array.isArray(bbox)
    ? `目标 ${mode} / ${tracking} / bbox=${bbox.map((value) => formatNum(value, 0)).join(",")}`
    : `目标 ${mode} / ${tracking}`;
}

function renderVisionEngineStatus(status) {
  const running = status.running ? "running" : "stopped";
  const camera = status.camera || status.source || {};
  const cameraText = camera.available === false ? "camera unavailable" : camera.index != null ? `camera ${camera.index}` : "";
  const frameId = status.frame_id ?? status.latest_frame_id ?? "";
  $("#visionEngineState").textContent = [running, cameraText, frameId !== "" ? `frame ${frameId}` : ""].filter(Boolean).join(" / ");
  $("#visionEngineState").className = status.running ? "ok-text" : "bad-text";
}

async function selectVisionTarget() {
  try {
    const body = {
      x: Number($("#visionTargetX").value),
      y: Number($("#visionTargetY").value),
      w: Number($("#visionTargetW").value),
      h: Number($("#visionTargetH").value),
    };
    if (!Number.isFinite(body.x) || !Number.isFinite(body.y) || !Number.isFinite(body.w) || !Number.isFinite(body.h) || body.w < 1 || body.h < 1) {
      throw new ApiError("BAD_VISION_TARGET", "请输入有效的 x/y/w/h 像素框。");
    }
    const result = await postJson("/api/v1/vision/target/select", body);
    $("#visionTargetToolState").textContent = result.message || "手动目标已选择";
    await refreshVisionProxyStatus();
    refreshVisionPreview();
  } catch (error) {
    showError(error);
  }
}

async function resetVisionTarget() {
  try {
    const result = await postJson("/api/v1/vision/target/reset", {});
    $("#visionTargetToolState").textContent = result.message || "目标已重置";
    await refreshVisionProxyStatus();
    refreshVisionPreview();
  } catch (error) {
    showError(error);
  }
}

function renderVisionLatestDebug(latest) {
  state.latestVision = latest;
  const camera = latest.camera || {};
  const offset = latest.offset || {};
  const smoothed = latest.smoothed_offset || {};
  const direction = latest.direction || {};
  const detector = latest.detector || {};
  const bbox = latest.bbox || latest.target?.bbox || null;
  const center = latest.center || latest.target?.center || offset.target_center || null;
  const faces = Array.isArray(latest.faces) ? latest.faces : [];
  $("#visionFrameId").textContent = latest.frame_id != null ? String(latest.frame_id) : "--";
  $("#visionTrackingState").textContent = `${latest.target_source || "none"} / ${latest.tracking_state || "idle"}`;
  $("#visionFrameSize").textContent = camera.width && camera.height ? `${camera.width} x ${camera.height} @ ${formatNum(latest.fps, 1)}fps` : "--";
  $("#visionOffsetState").textContent = `ndx=${formatNum(offset.ndx, 4)}, ndy=${formatNum(offset.ndy, 4)} | smooth=${formatNum(smoothed.ndx, 4)},${formatNum(smoothed.ndy, 4)}`;
  $("#visionDirectionState").textContent = direction.combined || "--";
  $("#visionBboxState").textContent = Array.isArray(bbox) ? bbox.map((value) => formatNum(value, 1)).join(", ") : "--";
  $("#visionCenterState").textContent = Array.isArray(center) ? center.map((value) => formatNum(value, 1)).join(", ") : "--";
  $("#visionConfidenceState").textContent = formatNum(latest.confidence ?? 0, 3);
  $("#visionFacesState").textContent = `${faces.length}`;
  $("#visionDetectorState").textContent = detector.face_backend ? `${detector.face_backend}${detector.face_available === false ? " unavailable" : ""}` : "--";
  $("#visionLatestJson").textContent = JSON.stringify(
    {
      detected: latest.detected,
      target_source: latest.target_source,
      tracking_state: latest.tracking_state,
      target: latest.target,
      offset: latest.offset,
      smoothed_offset: latest.smoothed_offset,
      direction: latest.direction,
      gesture: latest.gesture,
      detector: latest.detector,
    },
    null,
    2
  );
  renderVisionOverlay(latest);
}

function buildVisionMockLatest() {
  const width = 1280;
  const height = 720;
  const bbox = [760, 210, 210, 260];
  const center = [bbox[0] + bbox[2] / 2, bbox[1] + bbox[3] / 2];
  const desired = [width * 0.5, height * 0.42];
  const dx = center[0] - desired[0];
  const dy = center[1] - desired[1];
  const ndx = dx / (width / 2);
  const ndy = dy / (height / 2);
  return {
    timestamp: Date.now() / 1000,
    frame_id: 1,
    detected: true,
    has_target: true,
    target_source: "mock",
    tracking_state: "locked",
    target: { bbox, center, area: bbox[2] * bbox[3], confidence: 0.92 },
    bbox,
    center,
    confidence: 0.92,
    faces: [{ bbox, center, area: bbox[2] * bbox[3], confidence: 0.92 }],
    offset: {
      dx,
      dy,
      ndx,
      ndy,
      desired_center: desired,
      target_center: center,
      in_dead_zone: Math.abs(ndx) < 0.02 && Math.abs(ndy) < 0.025,
      valid: true,
      dead_zone_x_norm: 0.02,
      dead_zone_y_norm: 0.025,
    },
    smoothed_offset: { ndx: ndx * 0.72, ndy: ndy * 0.72, valid: true, kept: false },
    direction: {
      horizontal: ndx > 0 ? "right" : ndx < 0 ? "left" : "center",
      vertical: ndy > 0 ? "down" : ndy < 0 ? "up" : "center",
      combined: "right-down",
    },
    gesture: { available: false, raw: "", stable: "", confidence: 0 },
    fps: 30,
    camera: { source_type: "mock", camera_index: 0, available: true, width, height },
    detector: { face_backend: "mock", face_available: true, face_error: "" },
    message: "模拟视觉目标。不会访问摄像头，也不会控制机械臂。",
  };
}

function buildVisionMockFrameDataUrl() {
  const svg = `
<svg xmlns="http://www.w3.org/2000/svg" width="1280" height="720" viewBox="0 0 1280 720">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#111827"/>
      <stop offset="1" stop-color="#1f2937"/>
    </linearGradient>
  </defs>
  <rect width="1280" height="720" fill="url(#bg)"/>
  <g opacity="0.35" stroke="#64748b" stroke-width="1">
    ${Array.from({ length: 16 }, (_, index) => `<line x1="${index * 80}" y1="0" x2="${index * 80}" y2="720"/>`).join("")}
    ${Array.from({ length: 9 }, (_, index) => `<line x1="0" y1="${index * 80}" x2="1280" y2="${index * 80}"/>`).join("")}
  </g>
  <rect x="760" y="210" width="210" height="260" rx="18" fill="#334155" stroke="#94a3b8" stroke-width="4"/>
  <circle cx="825" cy="295" r="18" fill="#e2e8f0"/>
  <circle cx="905" cy="295" r="18" fill="#e2e8f0"/>
  <path d="M820 390 Q865 430 920 390" fill="none" stroke="#e2e8f0" stroke-width="10" stroke-linecap="round"/>
  <text x="44" y="70" fill="#e5e7eb" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="32">Mock Vision Frame</text>
  <text x="44" y="116" fill="#94a3b8" font-family="-apple-system, BlinkMacSystemFont, Segoe UI, sans-serif" font-size="22">用于验证目标框、中心点、期望中心和死区叠加层</text>
</svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function renderVisionOverlay(latest) {
  const overlay = $("#visionOverlay");
  if (!overlay) return;
  overlay.replaceChildren();
  if (!latest) return;
  const rect = visionImageRect();
  const camera = latest.camera || {};
  const width = Number(camera.width || 0);
  const height = Number(camera.height || 0);
  if (!rect || width <= 0 || height <= 0) return;
  const sx = rect.width / width;
  const sy = rect.height / height;
  const toX = (x) => rect.x + Number(x || 0) * sx;
  const toY = (y) => rect.y + Number(y || 0) * sy;
  const make = (tag, attrs) => {
    const node = document.createElementNS("http://www.w3.org/2000/svg", tag);
    Object.entries(attrs).forEach(([key, value]) => node.setAttribute(key, String(value)));
    overlay.appendChild(node);
    return node;
  };
  const offset = latest.offset || {};
  const desired = offset.desired_center || latest.desired_center || null;
  const deadZoneX = Number(offset.dead_zone_x_norm ?? latest.dead_zone_x_norm ?? 0.02) * width;
  const deadZoneY = Number(offset.dead_zone_y_norm ?? latest.dead_zone_y_norm ?? 0.025) * height;
  if (Array.isArray(desired) && desired.length >= 2) {
    make("rect", {
      class: "dead-zone",
      x: toX(Number(desired[0]) - deadZoneX),
      y: toY(Number(desired[1]) - deadZoneY),
      width: Math.max(1, deadZoneX * 2 * sx),
      height: Math.max(1, deadZoneY * 2 * sy),
    });
    make("line", { class: "desired", x1: toX(desired[0]) - 12, y1: toY(desired[1]), x2: toX(desired[0]) + 12, y2: toY(desired[1]) });
    make("line", { class: "desired", x1: toX(desired[0]), y1: toY(desired[1]) - 12, x2: toX(desired[0]), y2: toY(desired[1]) + 12 });
  }
  const bbox = latest.bbox || latest.target?.bbox || null;
  if (Array.isArray(bbox) && bbox.length >= 4) {
    make("rect", {
      class: "bbox",
      x: toX(bbox[0]),
      y: toY(bbox[1]),
      width: Math.max(1, Number(bbox[2] || 0) * sx),
      height: Math.max(1, Number(bbox[3] || 0) * sy),
    });
  }
  const center = latest.center || latest.target?.center || offset.target_center || null;
  if (Array.isArray(center) && center.length >= 2) {
    make("circle", { class: "center", cx: toX(center[0]), cy: toY(center[1]), r: 5 });
  }
}

function visionImageRect() {
  const preview = $(".vision-preview");
  const img = $("#visionPreviewFrame");
  if (!preview || !img) return null;
  const parent = preview.getBoundingClientRect();
  const rect = img.getBoundingClientRect();
  if (!rect.width || !rect.height) return null;
  return {
    x: rect.left - parent.left,
    y: rect.top - parent.top,
    width: rect.width,
    height: rect.height,
  };
}

function handleVisionFrameClick(event) {
  const latest = state.latestVision || {};
  const camera = latest.camera || {};
  const width = Number(camera.width || 0);
  const height = Number(camera.height || 0);
  const rect = $("#visionPreviewFrame").getBoundingClientRect();
  if (width <= 0 || height <= 0 || !rect.width || !rect.height) return;
  const x = Math.round(((event.clientX - rect.left) / rect.width) * width);
  const y = Math.round(((event.clientY - rect.top) / rect.height) * height);
  const bbox = latest.bbox || latest.target?.bbox || null;
  const defaultW = Array.isArray(bbox) && bbox.length >= 4 ? Math.max(1, Math.round(Number(bbox[2]) || 80)) : 80;
  const defaultH = Array.isArray(bbox) && bbox.length >= 4 ? Math.max(1, Math.round(Number(bbox[3]) || 80)) : 80;
  $("#visionTargetX").value = String(Math.max(0, x - Math.round(defaultW / 2)));
  $("#visionTargetY").value = String(Math.max(0, y - Math.round(defaultH / 2)));
  $("#visionTargetW").value = String(defaultW);
  $("#visionTargetH").value = String(defaultH);
  $("#visionTargetToolState").textContent = `已填入点击坐标：x=${x}, y=${y}`;
}

function renderRobot() {
  if (!state.robot) return;
  state.session.mode = state.robot.mode || state.session.mode;
  state.session.connected = Boolean(state.robot.connected);
  renderSession();
  const joints = state.robot.joints_deg || {};
  JOINTS.forEach(([key]) => {
    const el = $(`#joint-${key}`);
    if (el) el.textContent = `${formatNum(joints[key] ?? 0, 2)}°`;
    const input = $(`#fk-${key}`);
    if (input && input.value === "") input.value = formatNum(joints[key] ?? 0, 2);
  });
  const gripper = state.robot.gripper || {};
  renderGripper(gripper);
  renderTcp(state.robot.tcp_pose || {});
}

function renderGripper(gripper) {
  const available = gripper.available !== false;
  const value = gripper.open_percent ?? 50;
  updateGripperLabel(available ? value : "未安装");
  $("#gripperSlider").value = Math.round(value);
  $("#gripperSlider").disabled = !available;
  $("#gripperOpenBtn").disabled = !available;
  $("#gripperCloseBtn").disabled = !available;
  $("#gripperApplyBtn").disabled = !available;
  $("#gripperPanel").classList.toggle("disabled-panel", !available);
}

function renderTcp(tcp) {
  const xyz = tcp.xyz || [];
  const rpy = tcp.rpy || [];
  $("#tcpX").textContent = formatNum(xyz[0], 4);
  $("#tcpY").textContent = formatNum(xyz[1], 4);
  $("#tcpZ").textContent = formatNum(xyz[2], 4);
  $("#tcpR").textContent = formatNum(rpy[0], 4);
  $("#tcpP").textContent = formatNum(rpy[1], 4);
  $("#tcpYaw").textContent = formatNum(rpy[2], 4);
  $("#tcpSource").textContent = tcp.source || "--";
}

function updateGripperLabel(value) {
  if (typeof value === "string") {
    $("#gripperValue").textContent = value;
    return;
  }
  $("#gripperValue").textContent = `${Math.round(Number(value || 0))}%`;
}

function renderPoses(poses) {
  $("#posesList").innerHTML = poses
    .map((item) => {
      const angles = (item.pose?.关节角度 || []).map((v) => formatNum(v, 1)).join(", ");
      return `
        <article class="item-card">
          <h3>${escapeHtml(item.name)}</h3>
          <p>${escapeHtml(item.description || item.pose?.说明 || "")}</p>
          <p>关节：${escapeHtml(angles)}</p>
          <p>夹爪：${formatNum(item.pose?.夹爪 ?? 50, 0)}%</p>
          <div class="button-row">
            <button data-pose-detail="${escapeAttr(item.name)}">详情</button>
            <button data-pose-goto="${escapeAttr(item.name)}">前往</button>
            <button data-pose-delete="${escapeAttr(item.name)}">删除</button>
          </div>
        </article>`;
    })
    .join("");
  $("#posesList").onclick = (event) => {
    const detailBtn = event.target.closest("button[data-pose-detail]");
    const gotoBtn = event.target.closest("button[data-pose-goto]");
    const delBtn = event.target.closest("button[data-pose-delete]");
    if (detailBtn) showPoseDetail(detailBtn.dataset.poseDetail);
    if (gotoBtn) gotoPose(gotoBtn.dataset.poseGoto);
    if (delBtn) deletePose(delBtn.dataset.poseDelete);
  };
}

function renderPoseDetail(name, detail) {
  const pose = detail.pose || detail;
  $("#poseDetailName").textContent = name;
  $("#poseDetailSummary").textContent = formatPoseSummaryDetail(name, pose, detail.description);
  $("#poseDetailResult").textContent = JSON.stringify(compactPoseDetail(pose), null, 2);
}

function formatPoseSummaryDetail(name, pose, description = "") {
  const lines = [`姿态：${name}`, ""];
  const desc = description || pose?.说明 || pose?.description || "";
  if (desc) lines.push(`说明: ${desc}`);
  const joints = normalizePoseJoints(pose);
  if (Object.keys(joints).length) {
    if (lines[lines.length - 1] !== "") lines.push("");
    lines.push("关节角度");
    JOINTS.forEach(([key, label]) => {
      if (Object.prototype.hasOwnProperty.call(joints, key)) {
        lines.push(`  ${label}: ${formatNum(joints[key], 2)} deg`);
      }
    });
  }
  const gripper = pose?.夹爪 ?? pose?.gripper;
  if (gripper !== undefined && gripper !== null) {
    if (lines[lines.length - 1] !== "") lines.push("");
    lines.push(`夹爪: ${formatNum(gripper, 1)}%`);
  }
  const tcp = pose?.tcp_pose || pose?.tcp || pose?.末端位姿;
  if (tcp) {
    if (lines[lines.length - 1] !== "") lines.push("");
    lines.push("TCP");
    if (Array.isArray(tcp.xyz)) lines.push(`  XYZ: ${tcp.xyz.map((value) => formatNum(value, 4)).join(", ")} m`);
    if (Array.isArray(tcp.rpy)) lines.push(`  RPY: ${tcp.rpy.map((value) => formatNum(Number(value) * 57.2958, 2)).join(", ")} deg`);
  }
  if (lines.length <= 2) lines.push(JSON.stringify(pose || {}, null, 2));
  return lines.join("\n");
}

function compactPoseDetail(pose) {
  return {
    description: pose?.说明 || pose?.description || "",
    joints_deg: normalizePoseJoints(pose),
    tcp_pose: pose?.tcp_pose || pose?.tcp || pose?.末端位姿 || null,
    gripper: pose?.夹爪 ?? pose?.gripper ?? null,
    raw_present_position: pose?.raw_present_position || pose?.raw || null,
    multi_turn_state: pose?.multi_turn_state || null,
  };
}

function normalizePoseJoints(pose) {
  if (!pose) return {};
  const source = pose.joints_deg || pose.joints || pose.targets_deg || pose.关节角度 || {};
  if (Array.isArray(source)) {
    return Object.fromEntries(JOINTS.map(([key], index) => [key, Number(source[index] || 0)]));
  }
  if (source && typeof source === "object") return { ...source };
  return {};
}

function renderActions(actions) {
  $("#actionsList").innerHTML = actions
    .map((item) => {
      const s = item.summary || {};
      return `
        <article class="item-card">
          <h3>${escapeHtml(item.name)}</h3>
          <p>姿态数：${s.pose_count ?? "--"}，总时长：${s["总时长"] ?? "--"} 秒</p>
          <div class="tag-row">
            <span class="tag ${s["是否包含 gripper"] ? "on" : ""}">gripper</span>
            <span class="tag ${s["是否包含 tcp_pose"] ? "on" : ""}">tcp_pose</span>
            <span class="tag ${s["是否包含 multi_turn_state"] ? "on" : ""}">multi_turn_state</span>
          </div>
          <div class="button-row">
            <button data-action-play="${escapeAttr(item.name)}">播放</button>
            <button data-action-detail="${escapeAttr(item.name)}">详情</button>
            <button data-action-delete="${escapeAttr(item.name)}">删除</button>
          </div>
        </article>`;
    })
    .join("");
  $("#actionsList").onclick = async (event) => {
    const playBtn = event.target.closest("button[data-action-play]");
    const detailBtn = event.target.closest("button[data-action-detail]");
    const deleteBtn = event.target.closest("button[data-action-delete]");
    if (playBtn) playAction(playBtn.dataset.actionPlay);
    if (detailBtn) showActionDetail(detailBtn.dataset.actionDetail);
    if (deleteBtn) deleteAction(deleteBtn.dataset.actionDelete);
  };
}

function renderRecordingStatus(latestPose = null) {
  const rec = state.recording || {};
  const active = Boolean(rec.active);
  const count = Number(rec.pose_count || 0);
  $("#recordingStatus").textContent = active ? `录制中 ${count} 帧` : "未开始";
  $("#recordingStatus").className = `status-pill ${active ? "good" : "warn"}`;
  $("#recordingNameInput").disabled = active;
  $("#recordingSourceSelect").disabled = active;
  $("#startRecordingBtn").disabled = active;
  $("#captureRecordingBtn").disabled = !active;
  $("#saveRecordingBtn").disabled = !active || count <= 0;
  $("#cancelRecordingBtn").disabled = !active;
  $("#recordingDetail").textContent = JSON.stringify(
    {
      recording: rec,
      latest_pose: latestPose
        ? {
            name: latestPose.name,
            joints_deg: latestPose.joints_deg || latestPose["关节角度"],
            duration_sec: latestPose.duration_sec,
          }
        : undefined,
    },
    null,
    2
  );
}

async function showActionDetail(name) {
  try {
    const data = await getJson(`/api/v1/actions/${encodeURIComponent(name)}`);
    renderActionDetail(name, data);
    log("info", `动作详情已加载：${name}`);
  } catch (error) {
    showError(error);
  }
}

async function deleteAction(name) {
  try {
    const typed = window.prompt(`输入动作名确认删除：${name}`);
    if (typed !== name) return;
    await deleteJson(`/api/v1/actions/${encodeURIComponent(name)}`, { timeout: 8000 });
    $("#actionDetailName").textContent = "未选择";
    $("#actionDetailSummary").textContent = "请选择一个动作。";
    $("#actionDetailResult").textContent = "";
    log("warning", `动作已删除：${name}`);
    await loadActions();
  } catch (error) {
    showError(error);
  }
}

function renderActionDetail(name, detail) {
  const action = detail.action || detail;
  const poses = action.poses || action["poses"] || [];
  const firstPose = poses[0] || null;
  const lastPose = poses.length ? poses[poses.length - 1] : null;
  const summary = detail.summary || action.summary || {};
  $("#actionDetailName").textContent = name;
  $("#actionDetailSummary").textContent = formatActionSummaryDetail(name, summary, poses);
  $("#actionDetailResult").textContent = JSON.stringify(
    {
      summary,
      path: detail.path || action.path || "",
      pose_count: poses.length,
      first_pose: compactActionPose(firstPose),
      last_pose: compactActionPose(lastPose),
      preview_poses: poses.slice(0, 5).map(compactActionPose),
    },
    null,
    2
  );
}

function formatActionSummaryDetail(name, summary, poses) {
  const lines = [`动作：${name}`, ""];
  const fields = [
    ["帧数", "pose_count"],
    ["时长", "总时长"],
    ["末端轨迹点", "末端轨迹点数"],
    ["包含 raw", "是否包含 raw"],
    ["包含 TCP", "是否包含 tcp_pose"],
    ["包含夹爪", "是否包含 gripper"],
    ["包含多圈", "是否包含 multi_turn_state"],
    ["来源", "source"],
    ["更新时间", "updated_at"],
  ];
  fields.forEach(([label, key]) => {
    if (Object.prototype.hasOwnProperty.call(summary, key)) {
      lines.push(`${label}: ${summary[key]}`);
    }
  });
  if (!Object.prototype.hasOwnProperty.call(summary, "pose_count") && Object.prototype.hasOwnProperty.call(summary, "frame_count")) {
    lines.push(`帧数: ${summary.frame_count}`);
  }
  if (!Object.prototype.hasOwnProperty.call(summary, "总时长") && Object.prototype.hasOwnProperty.call(summary, "duration_sec")) {
    lines.push(`时长: ${summary.duration_sec}`);
  }
  const joints = summary.joints || summary.joint_names;
  if (Array.isArray(joints)) lines.push(`关节: ${joints.join(", ")}`);
  if (poses.length) {
    lines.push("");
    lines.push(`首帧: ${formatActionPoseLine(poses[0])}`);
    lines.push(`尾帧: ${formatActionPoseLine(poses[poses.length - 1])}`);
  }
  if (lines.length <= 2) lines.push(JSON.stringify(summary, null, 2));
  return lines.join("\n");
}

function formatActionPoseLine(pose) {
  const compact = compactActionPose(pose);
  if (!compact) return "--";
  const joints = compact.joints_deg || {};
  const jointText = JOINTS.map(([key]) => `${key}=${formatNum(joints[key], 2)}`).join(", ");
  return `${compact.name || "--"} | ${formatNum(compact.duration_sec, 2)}s | ${jointText}`;
}

function compactActionPose(pose) {
  if (!pose) return null;
  return {
    name: pose.name || pose["名称"] || "",
    duration_sec: pose.duration_sec ?? pose["持续时间"] ?? pose["duration"],
    joints_deg: pose.joints_deg || pose.joint_targets_deg || pose.replay_joint_targets_deg || pose["关节角度"] || {},
    tcp_pose: pose.tcp_pose || pose["末端位姿"],
    gripper: pose.gripper,
  };
}

function renderCalibration(calib) {
  $("#calibPath").textContent = calib["标定文件"] || "--";
  $("#calibExists").textContent = calib["是否存在"] ? "是" : "否";
  $("#calibAllowed").textContent = calib["允许真机移动"] ? "是" : "否";
  $("#calibAllowed").className = calib["允许真机移动"] ? "ok-text" : "bad-text";
  const raw = calib.raw_items || {};
  const rows = JOINTS.concat([["gripper", "夹爪"]])
    .map(([key, label]) => {
      const item = raw[key] || {};
      const report = calib["项目"]?.[key] || {};
      return `<tr>
        <td>${escapeHtml(label)}</td>
        <td>${escapeHtml(String(item.id ?? "--"))}</td>
        <td>${escapeHtml(String(item["模式"] ?? "--"))}</td>
        <td>${escapeHtml(String(item.zero_present_raw ?? "--"))}</td>
        <td>${escapeHtml(String(item.home_present_raw ?? "--"))}</td>
        <td>${escapeHtml(String(item.range_min ?? "--"))}</td>
        <td>${escapeHtml(String(item.range_max ?? "--"))}</td>
        <td>${escapeHtml(String(item.phase ?? "--"))}</td>
        <td class="${report["完整"] ? "ok-text" : "bad-text"}">${report["完整"] ? "完整" : "需检查"}</td>
      </tr>`;
    })
    .join("");
  $("#calibTableWrap").innerHTML = `
    <table>
      <thead><tr><th>关节</th><th>id</th><th>模式</th><th>zero_present_raw</th><th>home_present_raw</th><th>range_min</th><th>range_max</th><th>phase</th><th>状态</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

async function diagnoseJ12() {
  try {
    state.j12Diagnostic = await getJson("/api/v1/robot/joint-diagnostics?joint_key=j12", { timeout: 8000 });
    renderJ12Diagnostic(state.j12Diagnostic);
  } catch (error) {
    showError(error);
    $("#j12DiagnosticResult").textContent = error.message || String(error);
  }
}

async function applyJ12Calibration() {
  const assigned = Number($("#j12AssignedAngle").value);
  if (!Number.isFinite(assigned)) {
    showError(new ApiError("BAD_INPUT", "请输入 J12 当前真实姿态对应的角度。"));
    return;
  }
  const body = await withSafety({ joint_key: "j12", current_angle_deg: assigned }, true);
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/robot/calibration/current-angle", body, { timeout: 10000 });
    $("#j12DiagnosticResult").textContent = JSON.stringify(data, null, 2);
    await loadCalibration();
    await diagnoseJ12();
  } catch (_) {}
}

async function diagnoseBatchCalibration() {
  try {
    const data = await getJson("/api/v1/robot/joint-diagnostics/batch", { timeout: 20000 });
    state.batchDiagnostics = data;
    renderBatchDiagnostics(data);
    $("#j12DiagnosticResult").textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    showError(error);
    $("#j12DiagnosticResult").textContent = error.message || String(error);
  }
}

function fillBatchCalibrationFromDiagnostics() {
  const diagnostics = state.batchDiagnostics?.diagnostics || {};
  if (!Object.keys(diagnostics).length) {
    showError(new ApiError("NO_BATCH_DIAGNOSTICS", "请先点击“批量只读诊断”。"));
    return;
  }
  $$(".batch-angle-input").forEach((input) => {
    const item = diagnostics[input.dataset.joint];
    if (!item || item.current_angle_deg == null) return;
    input.value = formatNum(item.current_angle_deg, input.dataset.joint === "j10" ? 2 : 2);
  });
  $("#j12DiagnosticResult").textContent = "已把当前软件换算角度填入批量输入框。请只保留你确认要修正的关节，其他输入框清空。";
}

async function applyBatchCalibration() {
  const jointAngles = {};
  $$(".batch-angle-input").forEach((input) => {
    const raw = input.value.trim();
    if (raw === "") return;
    const value = Number(raw);
    if (Number.isFinite(value)) {
      jointAngles[input.dataset.joint] = value;
    }
  });
  if (!Object.keys(jointAngles).length) {
    showError(new ApiError("BAD_INPUT", "请至少填写一个多圈关节的当前逻辑角度。"));
    return;
  }
  const body = await withSafety({ joint_angles_deg: jointAngles }, true);
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/robot/calibration/current-angles", body, { timeout: 20000 });
    $("#j12DiagnosticResult").textContent = JSON.stringify(data, null, 2);
    await loadCalibration();
    await diagnoseJ12();
    await diagnoseBatchCalibration();
  } catch (_) {}
}

function renderJ12Diagnostic(data) {
  $("#j12PresentRaw").textContent = String(data.present_raw ?? "--");
  $("#j12CurrentAngle").textContent = `${formatNum(data.current_angle_deg, 2)} deg`;
  $("#j12Limit").textContent = `[${formatNum(data.min_angle_deg, 1)}, ${formatNum(data.max_angle_deg, 1)}] deg`;
  $("#j12LimitState").textContent = data.in_limit ? "限位内" : data.reason || "超限";
  $("#j12LimitState").className = data.in_limit ? "ok-text" : "bad-text";
  $("#j12DiagnosticResult").textContent = JSON.stringify(data, null, 2);
}

function renderBatchDiagnostics(data) {
  const diagnostics = data.diagnostics || {};
  const errors = data.errors || {};
  const rows = ["j10", "j11", "j12", "j13", "j15"]
    .map((joint) => {
      const item = diagnostics[joint] || {};
      const error = errors[joint] || "";
      const ok = item.in_limit === true;
      const bad = item.in_limit === false || error;
      return `<tr>
        <td>${escapeHtml(joint.toUpperCase())}</td>
        <td>${escapeHtml(String(item.present_raw ?? "--"))}</td>
        <td>${item.current_angle_deg == null ? "--" : `${formatNum(item.current_angle_deg, 2)}`}</td>
        <td>${item.min_angle_deg == null ? "--" : `${formatNum(item.min_angle_deg, 1)} ~ ${formatNum(item.max_angle_deg, 1)}`}</td>
        <td class="${ok ? "ok-text" : bad ? "bad-text" : ""}">${escapeHtml(error || item.reason || "--")}</td>
      </tr>`;
    })
    .join("");
  $("#batchDiagnosticsTable").innerHTML = `
    <table>
      <thead><tr><th>关节</th><th>Present raw</th><th>当前换算</th><th>软件限位</th><th>判断</th></tr></thead>
      <tbody>${rows}</tbody>
    </table>`;
}

function renderKinematicsStatus() {
  const data = state.kinematicsStatus || {};
  const urdf = data.urdf || {};
  const model = data.model || {};
  const ok = Boolean(urdf.ok && model.available);
  $("#kinStatusPill").textContent = ok ? "可用" : "需检查";
  $("#kinStatusPill").className = `status-pill ${ok ? "good" : "bad"}`;
  $("#kinUrdfPath").textContent = shortPath(urdf.urdf_path || "");
  $("#kinTargetFrame").textContent = model.target_frame || urdf.target_frame || "--";
  $("#kinCounts").textContent = `${(urdf.links || []).length} links / ${(urdf.joints || []).length} joints`;
  $("#kinModelState").textContent = model.available ? `${model.backend || "model"} ee=${model.ee_link_index ?? "--"}` : model.error || "不可用";
  $("#kinModelState").className = model.available ? "ok-text" : "bad-text";
  const jointLimits = model.joint_limits || {};
  const limitSummary = Object.entries(jointLimits).map(([joint, item]) => ({
    joint,
    urdf_joint: item.urdf_joint,
    lower_deg: item.lower_deg,
    upper_deg: item.upper_deg,
    unit: item.unit,
  }));
  $("#kinStatusResult").textContent = JSON.stringify(
    {
      errors: urdf.errors || [],
      warnings: urdf.warnings || [],
      missing_meshes: urdf.missing_meshes || [],
      sdk_joint_mapping: urdf.sdk_joint_mapping || {},
      ordered_joint_urdf_names: model.ordered_joint_urdf_names || [],
      joint_limits: limitSummary,
    },
    null,
    2
  );
}

function renderMotionTuning() {
  const t = state.motionTuning || state.config?.motion || {};
  const overrides = t.jog_direction_overrides || {};
  $("#motionSpeedPercent").value = formatNum(t.default_speed_percent ?? 50, 0);
  $("#quickStepDuration").value = formatNum(t.quick_step_duration_s ?? 0.8, 2);
  $("#quickStepFrames").value = String(t.quick_step_frames ?? 12);
  $("#continuousUpdateHz").value = formatNum(t.continuous_update_hz ?? 20, 1);
  $("#continuousHorizon").value = formatNum(t.continuous_target_horizon_s ?? 0.25, 2);
  $("#playbackUpdateHz").value = formatNum(t.playback_update_hz ?? 20, 1);
  $$("[data-jog-direction]").forEach((select) => {
    const joint = select.dataset.jogDirection;
    select.value = String(Number(overrides[joint] ?? 1) < 0 ? -1 : 1);
  });
  $("#continuousSpeedInput").disabled = state.jointControlMode !== "continuous";
}

function readJogDirectionOverrides() {
  const overrides = {};
  $$("[data-jog-direction]").forEach((select) => {
    const joint = select.dataset.jogDirection;
    overrides[joint] = Number(select.value) < 0 ? -1 : 1;
  });
  return overrides;
}

async function saveMotionTuning() {
  const body = {
    default_speed_percent: Number($("#motionSpeedPercent").value || 50),
    quick_step_duration_s: Number($("#quickStepDuration").value || 0.8),
    quick_step_frames: Number($("#quickStepFrames").value || 12),
    continuous_update_hz: Number($("#continuousUpdateHz").value || 20),
    continuous_target_horizon_s: Number($("#continuousHorizon").value || 0.25),
    playback_update_hz: Number($("#playbackUpdateHz").value || 20),
    jog_direction_overrides: readJogDirectionOverrides(),
  };
  try {
    const data = await postJson("/api/v1/motion/tuning", body);
    state.motionTuning = data.motion || data;
    renderMotionTuning();
    log("info", "运动调参已保存");
  } catch (error) {
    showError(error);
  }
}

async function resetMotionTuning() {
  try {
    const data = await postJson("/api/v1/motion/tuning/reset", {});
    state.motionTuning = data.motion || data;
    renderMotionTuning();
    log("info", "运动调参已恢复推荐值");
  } catch (error) {
    showError(error);
  }
}

function renderContinuousJog(jog) {
  const running = Boolean(jog.running);
  $("#continuousJogStatus").textContent = running
    ? `连续控制：${jog.joint_key || "--"} ${formatNum(jog.speed_deg_s, 1)} deg/s @ ${formatNum(jog.update_hz, 1)} Hz`
    : "连续控制：停止";
  $("#continuousJogStatus").className = `inline-status ${running ? "ok-text" : ""}`;
  const detail = {
    running,
    joint_key: jog.joint_key || null,
    direction: jog.direction ?? null,
    speed_deg_s: jog.speed_deg_s ?? null,
    update_hz: jog.update_hz ?? state.motionTuning?.continuous_update_hz ?? null,
    target_horizon_s: jog.target_horizon_s ?? state.motionTuning?.continuous_target_horizon_s ?? null,
    started_at: jog.started_at || null,
    last_tick_at: jog.last_tick_at || null,
    tick_count: jog.tick_count ?? null,
    message: jog.message || null,
  };
  $("#continuousJogDetail").textContent = running || jog.message ? JSON.stringify(detail, null, 2) : "未运行";
}

function renderDependencies(deps) {
  $("#depsList").innerHTML = Object.entries(deps)
    .filter(([_, value]) => value && typeof value === "object" && "available" in value)
    .map(([name, value]) => `<div class="dep-row"><span>${escapeHtml(name)}</span><span class="${value.available ? "ok-text" : "bad-text"}">${value.available ? "可用" : "缺失"}</span></div>`)
    .join("");
}

function renderHardwareCheck() {
  const hw = state.hardware || {};
  const scan = hw.readonly_scan || {};
  const serial = hw.serial || {};
  const driver = hw.driver || {};
  const deps = hw.dependencies || {};
  const calibration = hw.calibration || {};
  const errors = hw.errors || [];
  $("#hardwareStatus").textContent = hw.ok ? "通过" : "需检查";
  $("#hardwareStatus").className = `status-pill ${hw.ok ? "good" : "bad"}`;
  $("#hardwarePort").textContent = serial.exists
    ? `${hw.port || "--"}${serial.is_symlink ? ` -> ${shortPath(serial.target)}` : ""}`
    : `${hw.port || "--"} 不存在`;
  $("#hardwarePort").className = serial.exists ? "ok-text" : "bad-text";
  $("#hardwareDriver").textContent = driver.usb_ch343 ? "usb_ch343" : driver.option_bound ? "option 占用" : "未识别";
  $("#hardwareDriver").className = driver.usb_ch343 ? "ok-text" : "bad-text";
  $("#hardwareDeps").textContent = deps.real_mode_ready ? "real_mode_ready" : "缺依赖";
  $("#hardwareDeps").className = deps.real_mode_ready ? "ok-text" : "bad-text";
  $("#hardwareCalibration").textContent = calibration.exists ? (calibration.allowed ? "允许真实移动" : "需检查") : "缺失";
  $("#hardwareCalibration").className = calibration.exists && calibration.allowed ? "ok-text" : "bad-text";
  $("#hardwareIds").textContent = scan.found_models
    ? Object.keys(scan.found_models).sort((a, b) => Number(a) - Number(b)).join(", ")
    : "--";
  $("#hardwareIds").className = scan.ok ? "ok-text" : "bad-text";
  $("#hardwareRaw").textContent = scan.present_position
    ? Object.entries(scan.present_position).map(([key, value]) => `${key}:${value}`).join(", ")
    : "--";
  $("#hardwareErrors").innerHTML = errors.length
    ? errors.map((item) => `<div class="hardware-error">${escapeHtml(item)}</div>`).join("")
    : `<div class="hardware-ok">真实硬件只读检查通过。</div>`;
}

function showPage(name) {
  $$(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.page === name));
  $$(".page").forEach((page) => page.classList.remove("active"));
  $(`#page${capitalize(name)}`).classList.add("active");
  if (name === "poses") loadPoses();
  if (name === "actions") loadActions();
  if (name === "follow") {
    refreshFollow();
    refreshVisionPreview();
  }
  if (name === "agent") loadAgentStatus();
  if (name === "cinematic") loadCinematicStatus();
  if (name === "kinematics") {
    loadKinematicsStatus();
    refreshKinematicsRender();
  }
  if (name === "calibration") loadCalibration();
  if (name === "calibration") diagnoseJ12();
  if (name === "settings") {
    loadDependencies();
    loadHardwareCheck();
    loadMotionTuning();
  }
}

function showError(error) {
  const code = error.code || "ERROR";
  const message = error.message || String(error);
  state.lastError = `${code}: ${message}`;
  $("#topError").textContent = state.lastError;
  $("#topError").classList.remove("hidden");
  log("error", state.lastError);
  setTimeout(() => $("#topError").classList.add("hidden"), 6000);
}

function log(level, message) {
  const line = { time: new Date().toLocaleTimeString(), level, message };
  state.logs.unshift(line);
  state.logs = state.logs.slice(0, 300);
  renderLogs();
}

function renderLogs() {
  const html = state.logs.map((item) => `<div class="log-entry ${item.level === "error" ? "error" : ""}">[${item.time}] ${escapeHtml(item.message)}</div>`).join("");
  $("#miniLog").innerHTML = html;
  $("#fullLog").innerHTML = html;
}

function clearLogs() {
  state.logs = [];
  renderLogs();
}

async function copyLastError() {
  if (!state.lastError) return;
  try {
    await navigator.clipboard.writeText(state.lastError);
    log("info", "最近错误已复制");
  } catch (error) {
    showError(error);
  }
}

async function withPending(key, fn) {
  state.pending.add(key);
  setPending(true);
  try {
    return await fn();
  } finally {
    state.pending.delete(key);
    setPending(state.pending.size > 0);
  }
}

function setPending(isPending) {
  $$("button").forEach((btn) => {
    if (btn.id === "topStopBtn" || btn.id === "quickStopBtn") return;
    btn.disabled = isPending;
  });
}

function formatNum(value, digits = 2) {
  const n = Number(value);
  if (!Number.isFinite(n)) return "--";
  return n.toFixed(digits);
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/`/g, "&#96;");
}

function shortPath(value) {
  const text = String(value || "");
  return text.length > 36 ? `...${text.slice(-33)}` : text;
}

function formatFileSize(value) {
  const size = Number(value || 0);
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

function capitalize(name) {
  return name.charAt(0).toUpperCase() + name.slice(1);
}

function $(selector) {
  return document.querySelector(selector);
}

function $$(selector) {
  return Array.from(document.querySelectorAll(selector));
}

class ApiError extends Error {
  constructor(code, message) {
    super(message);
    this.code = code;
  }
}
