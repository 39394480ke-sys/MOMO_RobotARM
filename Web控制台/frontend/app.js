const API_BASE = "";
const SAFE_TEXT = "我确认机械臂周围安全";
const JOINTS = [
  ["shoulder_pan", "J1 底座旋转"],
  ["shoulder_lift", "J2 肩部抬升"],
  ["elbow_flex", "J3 肘部弯曲"],
  ["wrist_flex", "J4 腕部俯仰"],
  ["wrist_roll", "J5 腕部旋转"],
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
  $("#homeBtn").addEventListener("click", () => postDanger("/api/v1/motion/home", { speed_percent: 50 }));
  $("#gripperSlider").addEventListener("input", () => updateGripperLabel(Number($("#gripperSlider").value)));
  $("#gripperOpenBtn").addEventListener("click", () => setGripper(1));
  $("#gripperCloseBtn").addEventListener("click", () => setGripper(0));
  $("#gripperApplyBtn").addEventListener("click", () => setGripper(Number($("#gripperSlider").value) / 100));
  $("#savePoseBtn").addEventListener("click", savePose);
  $("#pauseActionBtn").addEventListener("click", () => postJsonLogged("/api/v1/actions/pause", {}));
  $("#resumeActionBtn").addEventListener("click", () => postJsonLogged("/api/v1/actions/resume", {}));
  $("#stopActionBtn").addEventListener("click", () => postJsonLogged("/api/v1/actions/stop", {}));
  $("#kinRefreshBtn").addEventListener("click", refreshState);
  $("#fkBtn").addEventListener("click", computeFk);
  $("#ikBtn").addEventListener("click", computeIk);
  $("#executeIkBtn").addEventListener("click", executeIk);
  $("#refreshCalibrationBtn").addEventListener("click", loadCalibration);
  $("#refreshDepsBtn").addEventListener("click", loadDependencies);
  $("#connectBtn").addEventListener("click", connectSession);
  $("#disconnectBtn").addEventListener("click", disconnectSession);
  $("#switchModeBtn").addEventListener("click", switchMode);
  $("#clearLogBtn").addEventListener("click", clearLogs);
  $("#miniClearLogBtn").addEventListener("click", clearLogs);
  $("#copyErrorBtn").addEventListener("click", copyLastError);
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
  await Promise.allSettled([refreshSession(), refreshState(), loadPoses(), loadActions(), loadCalibration(), loadDependencies()]);
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
    if (!btn) return;
    const step = selectedJointStep() * Number(btn.dataset.dir);
    jointStep(btn.dataset.joint, step);
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
  if ((state.session.mode || state.robot?.mode) === "real" && value > 2) {
    value = 2;
    $("#jointStepSelect").value = "2";
    log("info", "真实模式步长已限制为 2 deg");
  }
  return value;
}

async function jointStep(jointKey, delta) {
  const body = await withSafety({ joint_key: jointKey, delta_deg: delta, speed_percent: 50 });
  if (!body) return;
  await postJsonLogged("/api/v1/motion/joint-step", body);
}

async function setGripper(openRatio) {
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
  await refreshSession();
}

async function disconnectSession() {
  await postJsonLogged("/api/v1/session/disconnect", {});
  await refreshSession();
}

async function switchMode() {
  const mode = $("#modeSelect").value;
  const body = await withSafety({ mode }, mode === "real");
  if (!body) return;
  await postJsonLogged("/api/v1/session/mode", body);
  await refreshSession();
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
    const text = window.prompt(`真实模式会移动机械臂。请输入：${SAFE_TEXT}`);
    if (text !== SAFE_TEXT) {
      showError(new ApiError("SAFETY_CONFIRM_REQUIRED", "安全确认不正确，操作已取消。"));
      return null;
    }
    return { ...body, confirm_text: text };
  }
  return body;
}

function renderConfig() {
  const cfg = state.config || {};
  const paths = cfg.controller || {};
  $("#configPaths").innerHTML = Object.entries(paths)
    .map(([key, value]) => `<dt>${escapeHtml(key)}</dt><dd>${escapeHtml(String(value))}</dd>`)
    .join("");
}

function renderSession() {
  const mode = state.session.mode || state.robot?.mode || "dry_run";
  const connected = Boolean(state.session.connected);
  $("#modePill").textContent = `模式 ${mode}`;
  $("#modePill").className = `status-pill ${mode === "real" ? "bad" : mode === "dry_run" ? "warn" : "good"}`;
  $("#connectionPill").textContent = connected ? "已连接" : "未连接";
  $("#connectionPill").className = `status-pill ${connected ? "good" : "warn"}`;
  $("#modeSelect").value = mode;
}

function renderWs() {
  $("#wsPill").textContent = state.wsOnline ? "WS 在线" : "WS 离线";
  $("#wsPill").className = `status-pill ${state.wsOnline ? "good" : "bad"}`;
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
  updateGripperLabel(gripper.open_percent ?? 50);
  $("#gripperSlider").value = Math.round(gripper.open_percent ?? 50);
  renderTcp(state.robot.tcp_pose || {});
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

function renderDependencies(deps) {
  $("#depsList").innerHTML = Object.entries(deps)
    .filter(([_, value]) => value && typeof value === "object" && "available" in value)
    .map(([name, value]) => `<div class="dep-row"><span>${escapeHtml(name)}</span><span class="${value.available ? "ok-text" : "bad-text"}">${value.available ? "可用" : "缺失"}</span></div>`)
    .join("");
}

function showPage(name) {
  $$(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.page === name));
  $$(".page").forEach((page) => page.classList.remove("active"));
  $(`#page${capitalize(name)}`).classList.add("active");
  if (name === "poses") loadPoses();
  if (name === "actions") loadActions();
  if (name === "calibration") loadCalibration();
  if (name === "settings") loadDependencies();
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
