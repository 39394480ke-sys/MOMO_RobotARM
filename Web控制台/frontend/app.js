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
  agent: null,
  agentMessages: [],
  cinematic: null,
  jointControlMode: "step",
  continuousJogActive: false,
  continuousJogStopping: false,
  continuousJogPointerId: null,
  continuousJogButton: null,
  j12Diagnostic: null,
  modeSelectDirty: false,
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  $("#apiAddress").textContent = `API: ${location.origin}`;
  buildJointControls();
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
  $("#refreshFollowBtn").addEventListener("click", refreshFollow);
  $("#startFollowBtn").addEventListener("click", startFollow);
  $("#stopFollowBtn").addEventListener("click", stopFollow);
  $("#followLatestUrl").addEventListener("input", () => {
    $("#followLatestUrl").dataset.userEdited = "1";
    renderVisionPreviewUrl();
  });
  $("#refreshVisionPreviewBtn").addEventListener("click", refreshVisionPreview);
  $("#refreshAgentBtn").addEventListener("click", loadAgentStatus);
  $("#sendAgentBtn").addEventListener("click", sendAgentMessage);
  $("#resetAgentBtn").addEventListener("click", resetAgentSession);
  $("#refreshCinematicBtn").addEventListener("click", loadCinematicStatus);
  $("#agentInput").addEventListener("keydown", (event) => {
    if (event.key === "Enter") sendAgentMessage();
  });
  $("#kinRefreshBtn").addEventListener("click", refreshState);
  $("#fkBtn").addEventListener("click", computeFk);
  $("#ikBtn").addEventListener("click", computeIk);
  $("#executeIkBtn").addEventListener("click", executeIk);
  $("#refreshCalibrationBtn").addEventListener("click", loadCalibration);
  $("#j12DiagnoseBtn").addEventListener("click", diagnoseJ12);
  $("#j12ApplyCalibrationBtn").addEventListener("click", applyJ12Calibration);
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
  await Promise.allSettled([refreshSession(), refreshState(), refreshFollow(), loadMotionTuning(), loadPoses(), loadActions(), loadCalibration(), loadDependencies()]);
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
  } catch (error) {
    showError(error);
  }
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
    log("info", `已删除姿态：${name}`);
    await loadPoses();
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
  try {
    const data = await postJson("/api/v1/agent/ask", { text, speak: false }, { timeout: 70000 });
    appendAgentMessage("AI", data.reply || data.message || "已完成。", "ai");
    log("info", "AI 对话完成");
  } catch (error) {
    appendAgentMessage("ERROR", error.message || String(error), "error");
    showError(error);
  }
}

async function resetAgentSession() {
  try {
    await postJson("/api/v1/agent/reset-session", {}, { timeout: 10000 });
    state.agentMessages = [];
    renderAgentMessages();
    appendAgentMessage("SYSTEM", "AI 会话已重置。", "system");
  } catch (error) {
    showError(error);
  }
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
  $("#agentSttUrl").textContent = agent.stt_url || "--";
  $("#agentTtsEnabled").textContent = agent.tts_enabled ? "开启" : "关闭";
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

function renderCinematicStatus() {
  const data = state.cinematic || {};
  $("#cinematicStatusState").textContent = data.available ? "可用" : "不可用";
  $("#cinematicStatusState").className = `status-pill ${data.available ? "good" : "bad"}`;
  $("#cinematicLatestRecord").textContent = data.latest_record?.name || "--";
  $("#cinematicLatestProject").textContent = data.latest_project?.name || "--";
  $("#cinematicRecordDir").textContent = shortPath(data.record_dir || "");
  $("#cinematicProjectDir").textContent = shortPath(data.project_dir || "");
  $("#cinematicConfigJson").textContent = JSON.stringify({ rail: data.rail || {}, two_step: data.two_step || {} }, null, 2);
  renderCompactFileList("#cinematicRecordsList", data.records || []);
  renderCompactFileList("#cinematicProjectsList", data.projects || []);
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

function refreshVisionPreview() {
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
    const [health, latest] = await Promise.all([
      getJson("/api/v1/vision/health", { timeout: 3000 }),
      getJson("/api/v1/vision/latest", { timeout: 3000 }),
    ]);
    $("#visionHealthState").textContent = health.camera_available ? "camera ok" : health.running ? "running" : "未启动";
    $("#visionHealthState").className = health.camera_available ? "ok-text" : "bad-text";
    $("#visionLatestState").textContent = latest.detected ? "检测到目标" : latest.message || "未检测";
    $("#visionLatestState").className = latest.detected ? "ok-text" : "";
    renderVisionLatestDebug(latest);
  } catch (error) {
    $("#visionHealthState").textContent = "视觉服务不可用";
    $("#visionHealthState").className = "bad-text";
    $("#visionLatestState").textContent = error.message || String(error);
    $("#visionLatestJson").textContent = "";
  }
}

function renderVisionLatestDebug(latest) {
  const camera = latest.camera || {};
  const offset = latest.offset || {};
  const smoothed = latest.smoothed_offset || {};
  const direction = latest.direction || {};
  const detector = latest.detector || {};
  $("#visionFrameSize").textContent = camera.width && camera.height ? `${camera.width} x ${camera.height} @ ${formatNum(latest.fps, 1)}fps` : "--";
  $("#visionOffsetState").textContent = `ndx=${formatNum(offset.ndx, 4)}, ndy=${formatNum(offset.ndy, 4)} | smooth=${formatNum(smoothed.ndx, 4)},${formatNum(smoothed.ndy, 4)}`;
  $("#visionDirectionState").textContent = direction.combined || "--";
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
            <button data-pose-goto="${escapeAttr(item.name)}">前往</button>
            <button data-pose-delete="${escapeAttr(item.name)}">删除</button>
          </div>
        </article>`;
    })
    .join("");
  $("#posesList").onclick = (event) => {
    const gotoBtn = event.target.closest("button[data-pose-goto]");
    const delBtn = event.target.closest("button[data-pose-delete]");
    if (gotoBtn) gotoPose(gotoBtn.dataset.poseGoto);
    if (delBtn) deletePose(delBtn.dataset.poseDelete);
  };
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
          </div>
        </article>`;
    })
    .join("");
  $("#actionsList").onclick = async (event) => {
    const playBtn = event.target.closest("button[data-action-play]");
    const detailBtn = event.target.closest("button[data-action-detail]");
    if (playBtn) playAction(playBtn.dataset.actionPlay);
    if (detailBtn) showActionDetail(detailBtn.dataset.actionDetail);
  };
}

async function showActionDetail(name) {
  try {
    const data = await getJson(`/api/v1/actions/${encodeURIComponent(name)}`);
    log("info", `动作详情：${name} ${JSON.stringify(data.summary)}`);
  } catch (error) {
    showError(error);
  }
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

function renderMotionTuning() {
  const t = state.motionTuning || state.config?.motion || {};
  $("#motionSpeedPercent").value = formatNum(t.default_speed_percent ?? 50, 0);
  $("#quickStepDuration").value = formatNum(t.quick_step_duration_s ?? 0.8, 2);
  $("#quickStepFrames").value = String(t.quick_step_frames ?? 12);
  $("#continuousUpdateHz").value = formatNum(t.continuous_update_hz ?? 20, 1);
  $("#continuousHorizon").value = formatNum(t.continuous_target_horizon_s ?? 0.25, 2);
  $("#playbackUpdateHz").value = formatNum(t.playback_update_hz ?? 20, 1);
  $("#continuousSpeedInput").disabled = state.jointControlMode !== "continuous";
}

async function saveMotionTuning() {
  const body = {
    default_speed_percent: Number($("#motionSpeedPercent").value || 50),
    quick_step_duration_s: Number($("#quickStepDuration").value || 0.8),
    quick_step_frames: Number($("#quickStepFrames").value || 12),
    continuous_update_hz: Number($("#continuousUpdateHz").value || 20),
    continuous_target_horizon_s: Number($("#continuousHorizon").value || 0.25),
    playback_update_hz: Number($("#playbackUpdateHz").value || 20),
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
