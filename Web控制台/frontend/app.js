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
  followConfig: null,
  hardware: null,
  motionTuning: null,
  kinematicsStatus: null,
  recording: null,
  action: null,
  lastActionVideoDialogId: "",
  agent: null,
  agentMessages: [],
  lastAgentReply: null,
  agentPendingTimer: null,
  agentAskBusy: false,
  agentVoiceRecorder: null,
  agentVoiceBusy: false,
  agentVoiceMode: "idle",
  agentVoiceSelection: null,
  subjectLock: null,
  subjectLockProfiles: [],
  subjectLockProfile: null,
  subjectLockProfileId: "",
  subjectLockTimer: null,
  latestVision: null,
  visionStatusTimer: null,
  visionStatusRefreshInFlight: false,
  jointControlMode: "step",
  continuousJogActive: false,
  continuousJogStopping: false,
  continuousJogPointerId: null,
  continuousJogButton: null,
  batchDiagnostics: null,
  modeSelectDirty: false,
  libraryRenameTarget: null,
  localActions: [],
  localPoses: [],
  community: { items: [], stats: {}, kind: "all", selected: null, importTarget: null, publishPreset: null },
  lastActionVideo: null,
  composer: {
    sourceKind: "action",
    sources: { robot_variant: "", actions: [], poses: [], skipped: [] },
    frames: [],
    previewId: "",
    previewDuration: 0,
    previewSegments: [],
    previewTime: 0,
    previewPlaying: false,
    previewLoop: false,
    previewAnimation: null,
    previewStartedAt: 0,
    previewRenderPending: false,
    previewQueuedTime: null,
    previewObjectUrl: "",
    dragIndex: null,
  },
};

document.addEventListener("DOMContentLoaded", init);

async function init() {
  $("#apiAddress").textContent = `API: ${location.origin}`;
  buildJointControls();
  buildFollowJointChecks();
  buildJogDirectionOverrides();
  buildFkInputs();
  buildJogButtons();
  bindEvents();
  initializeAgentVoice();
  await loadConfig();
  await refreshAll();
  connectWebSocket();
  startVisionStatusPolling();
  state.agentPendingTimer = window.setInterval(expireAgentPendingActions, 1000);
}

function bindEvents() {
  $$(".nav-item").forEach((btn) => btn.addEventListener("click", () => showPage(btn.dataset.page)));
  window.addEventListener("focus", refreshActiveVisionStatus);
  document.addEventListener("visibilitychange", () => {
    if (!document.hidden) refreshActiveVisionStatus();
  });
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
  $("#recordingFrameWarningClose").addEventListener("click", () => $("#recordingFrameWarningDialog").close());
  $("#actionVideoClose").addEventListener("click", () => $("#actionVideoDialog").close());
  $("#actionVideoShare").addEventListener("click", () => {
    const video = state.lastActionVideo;
    $("#actionVideoDialog").close();
    openCommunityPublish("action", video?.action_name || "", video?.media_id || "");
  });
  $("#communityPublishBtn").addEventListener("click", () => openCommunityPublish());
  $("#communityPublishClose").addEventListener("click", closeCommunityPublish);
  $("#communityPublishCancel").addEventListener("click", closeCommunityPublish);
  $("#communityPublishForm").addEventListener("submit", submitCommunityPublish);
  $("#communityPublishKind").addEventListener("change", () => fillCommunityPublishSources());
  $("#communityPublishSource").addEventListener("change", () => {
    const title = $("#communityPublishTitle");
    if (!title.value || title.value === $("#communityPublishSource").dataset.previousSource) title.value = $("#communityPublishSource").value;
    $("#communityPublishSource").dataset.previousSource = $("#communityPublishSource").value;
  });
  $("#communityDetailClose").addEventListener("click", () => $("#communityDetailDialog").close());
  $("#communityDetailFavorite").addEventListener("click", toggleCommunityDetailFavorite);
  $("#communityDetailImport").addEventListener("click", () => importCommunityItem(state.community.selected?.id));
  $("#communityImportCancel").addEventListener("click", () => $("#communityImportDialog").close());
  $("#communityImportForm").addEventListener("submit", submitCommunityImportRename);
  $("#communitySearch").addEventListener("input", debounce(loadCommunity, 220));
  $("#communityCategory").addEventListener("change", loadCommunity);
  $("#communitySort").addEventListener("change", loadCommunity);
  $("#communityFavoritesOnly").addEventListener("change", loadCommunity);
  $("#communityKindFilter").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-community-kind]");
    if (!button) return;
    state.community.kind = button.dataset.communityKind;
    $$("#communityKindFilter button").forEach((node) => node.classList.toggle("active", node === button));
    loadCommunity();
  });
  $("#composerRefreshSources").addEventListener("click", loadComposerSources);
  $("#composerSourceTabs").addEventListener("click", (event) => {
    const button = event.target.closest("button[data-composer-source-kind]");
    if (!button) return;
    state.composer.sourceKind = button.dataset.composerSourceKind;
    $$("#composerSourceTabs button").forEach((item) => item.classList.toggle("active", item === button));
    renderComposerSources();
  });
  $("#composerSourceSearch").addEventListener("input", renderComposerSources);
  $("#composerSourceList").addEventListener("click", handleComposerSourceClick);
  $("#composerTimeline").addEventListener("click", handleComposerTimelineClick);
  $("#composerTimeline").addEventListener("input", handleComposerTimelineInput);
  $("#composerTimeline").addEventListener("dragstart", handleComposerDragStart);
  $("#composerTimeline").addEventListener("dragover", handleComposerDragOver);
  $("#composerTimeline").addEventListener("dragleave", handleComposerDragLeave);
  $("#composerTimeline").addEventListener("drop", handleComposerDrop);
  $("#composerTimeline").addEventListener("dragend", clearComposerDragState);
  $("#composerClearTimeline").addEventListener("click", () => resetComposerDraft());
  $("#composerBuildPreview").addEventListener("click", buildComposerPreview);
  $("#composerPlayPreview").addEventListener("click", playComposerPreview);
  $("#composerPausePreview").addEventListener("click", pauseComposerPreview);
  $("#composerLoopPreview").addEventListener("change", () => {
    state.composer.previewLoop = $("#composerLoopPreview").checked;
  });
  $("#composerPreviewScrubber").addEventListener("input", scrubComposerPreview);
  $("#composerEntryDuration").addEventListener("input", invalidateComposerPreview);
  $("#composerDescription").addEventListener("input", invalidateComposerPreview);
  $("#composerSaveAction").addEventListener("click", saveComposedAction);
  $("#libraryRenameCancel").addEventListener("click", closeLibraryRenameDialog);
  $("#libraryRenameForm").addEventListener("submit", submitLibraryRename);
  $("#refreshFollowBtn").addEventListener("click", refreshFollowPageStatus);
  $("#startFollowBtn").addEventListener("click", startFollow);
  $("#stopFollowBtn").addEventListener("click", stopFollow);
  $("#saveFollowConfigBtn").addEventListener("click", saveFollowConfig);
  $("#followLatestUrl").addEventListener("input", () => {
    $("#followLatestUrl").dataset.userEdited = "1";
  });
  $("#refreshAgentBtn").addEventListener("click", loadAgentStatus);
  $("#sendAgentBtn").addEventListener("click", sendAgentMessage);
  $("#agentVoiceBtn").addEventListener("click", toggleAgentVoiceRecording);
  $("#cancelAgentVoiceBtn").addEventListener("click", cancelAgentVoiceRecording);
  $("#resetAgentBtn").addEventListener("click", resetAgentSession);
  $("#clearAgentChatBtn").addEventListener("click", clearAgentChat);
  $("#agentChatLog").addEventListener("click", handleAgentPendingActionClick);
  $("#refreshSubjectLockBtn").addEventListener("click", refreshSubjectLockPageStatus);
  $("#startSubjectLockCalibrationBtn").addEventListener("click", startSubjectLockCalibration);
  $("#validateSubjectLockBtn").addEventListener("click", validateSubjectLockProfile);
  $("#moveSubjectLockToStartBtn").addEventListener("click", moveSubjectLockToStart);
  $("#playSubjectLockBtn").addEventListener("click", playSubjectLockProfile);
  $("#stopSubjectLockBtn").addEventListener("click", stopSubjectLock);
  $("#subjectLockProfilesList").addEventListener("click", handleSubjectLockProfileClick);
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
    if (document.hidden && state.agentVoiceRecorder?.state === "recording") cancelAgentVoiceRecording();
  });
}

async function requestJson(path, options = {}) {
  const method = options.method || "GET";
  const timeout = options.timeout ?? 10000;
  const retries = options.retries ?? (method === "GET" ? 1 : 0);

  for (let attempt = 0; attempt <= retries; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    try {
      const response = await fetch(API_BASE + path, {
        method,
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
      const transient = error.name === "AbortError" || error instanceof TypeError;
      if (transient && attempt < retries) {
        await new Promise((resolve) => setTimeout(resolve, 350));
        continue;
      }
      if (error.name === "AbortError") {
        throw new ApiError("TIMEOUT", "请求超时，请检查局域网连接后重试。");
      }
      if (error instanceof TypeError) {
        throw new ApiError("NETWORK_ERROR", "网络连接中断，请确认设备仍连接同一局域网。");
      }
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }
}

function getJson(path, options = {}) {
  return requestJson(path, options);
}

function postJson(path, body = {}, options = {}) {
  return requestJson(path, { ...options, method: "POST", body });
}

async function postAudioWav(path, wavBlob, options = {}) {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), options.timeout ?? 35000);
  try {
    const response = await fetch(API_BASE + path, {
      method: "POST",
      headers: { "Content-Type": "audio/wav" },
      body: wavBlob,
      signal: controller.signal,
    });
    const payload = await response.json();
    if (!payload.ok) {
      const error = payload.error || { code: "HTTP_ERROR", message: `HTTP ${response.status}` };
      throw new ApiError(error.code, error.message);
    }
    return payload.data;
  } catch (error) {
    if (error.name === "AbortError") throw new ApiError("TIMEOUT", "语音识别请求超时。");
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
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
    updateCameraHubLinks();
  } catch (error) {
    showError(error);
  }
}

async function refreshAll() {
  await Promise.allSettled([refreshSession(), refreshState(), refreshFollow(), loadFollowConfig(), loadMotionTuning(), loadKinematicsStatus(), loadPoses(), loadActions(), loadCalibration(), loadDependencies()]);
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
    state.localPoses = data.poses || [];
    renderPoses(state.localPoses);
  } catch (error) {
    showError(error);
  }
}

async function loadActions() {
  try {
    const data = await getJson("/api/v1/actions");
    state.localActions = data.actions || [];
    renderActions(state.localActions);
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

async function loadFollowConfig() {
  try {
    const data = await getJson("/api/v1/follow/config");
    state.followConfig = data.follow || {};
    renderFollowConfig();
  } catch (error) {
    showError(error);
  }
}

async function loadAgentStatus() {
  try {
    state.agent = await getJson("/api/v1/agent/status");
    renderAgentStatus();
    restoreAgentPendingAction(state.agent.pending_action);
  } catch (error) {
    showError(error);
  }
}

async function loadSubjectLockStatus(options = {}) {
  try {
    const statusPromise = getJson("/api/v1/subject-lock/status", { timeout: 8000 });
    const profilePromise = options.loadProfiles === false
      ? Promise.resolve(null)
      : getJson("/api/v1/subject-lock/profiles", { timeout: 8000 });
    const [status, profileData] = await Promise.all([statusPromise, profilePromise]);
    state.subjectLock = status;
    if (profileData) state.subjectLockProfiles = profileData.profiles || [];
    if (status.profile_id) state.subjectLockProfileId = status.profile_id;
    if (!state.subjectLockProfileId && state.subjectLockProfiles.length) {
      state.subjectLockProfileId = state.subjectLockProfiles[0].profile_id || "";
    }
    renderSubjectLockStatus();
    renderSubjectLockProfiles();
    if (state.subjectLockProfileId && options.loadProfile !== false) {
      await loadSubjectLockProfile(state.subjectLockProfileId, false);
    }
  } catch (error) {
    if (!options.quiet) showError(error);
  }
}

async function loadSubjectLockProfile(profileId, refreshStatus = true) {
  if (!profileId) return;
  try {
    state.subjectLockProfile = await getJson(`/api/v1/subject-lock/profiles/${encodeURIComponent(profileId)}`);
    state.subjectLockProfileId = profileId;
    renderSubjectLockProfile();
    renderSubjectLockProfiles();
    if (refreshStatus) await loadSubjectLockStatus({ loadProfile: false, quiet: true });
  } catch (error) {
    showError(error);
  }
}

async function startSubjectLockCalibration() {
  try {
    const latest = await getJson("/api/v1/vision/latest", { timeout: 5000 });
    if (!latest.has_target && !latest.detected) throw new ApiError("SUBJECT_LOCK_TARGET_REQUIRED", "请先在画面中框选主体。");
    const body = await withSafety({
      name: $("#subjectLockName").value.trim(),
      start_mm: Number($("#subjectLockStartMm").value),
      end_mm: Number($("#subjectLockEndMm").value),
      speed_mm_s: Number($("#subjectLockSpeedMmS").value),
    });
    state.subjectLock = await postJson("/api/v1/subject-lock/calibration/start", body, { timeout: 10000 });
    state.subjectLockProfileId = state.subjectLock.profile_id || "";
    state.subjectLockProfile = null;
    renderSubjectLockStatus();
    startSubjectLockPolling();
    log("info", "主体锁定自动标定已启动");
  } catch (error) {
    showError(error);
  }
}

async function validateSubjectLockProfile() {
  const profileId = currentSubjectLockProfileId();
  if (!profileId) return showError(new ApiError("SUBJECT_LOCK_PROFILE_REQUIRED", "请先选择一条轨迹。"));
  try {
    state.subjectLockProfile = await postJson(
      `/api/v1/subject-lock/profiles/${encodeURIComponent(profileId)}/validate`,
      { speed_mm_s: subjectLockPlaybackSpeed() },
      { timeout: 15000 }
    );
    renderSubjectLockProfile();
    await loadSubjectLockStatus({ loadProfile: false, quiet: true });
  } catch (error) {
    showError(error);
  }
}

async function moveSubjectLockToStart() {
  await runSubjectLockProfileAction("move-to-start", "回到起点");
}

async function playSubjectLockProfile() {
  const profileId = currentSubjectLockProfileId();
  if (!profileId) return showError(new ApiError("SUBJECT_LOCK_PROFILE_REQUIRED", "请先选择一条轨迹。"));
  try {
    const speedMmS = subjectLockPlaybackSpeed();
    state.subjectLockProfile = await postJson(
      `/api/v1/subject-lock/profiles/${encodeURIComponent(profileId)}/validate`,
      { speed_mm_s: speedMmS },
      { timeout: 15000 }
    );
    renderSubjectLockProfile();
    if (!state.subjectLockProfile.validation?.valid) {
      throw new ApiError("SUBJECT_LOCK_SPEED_UNSAFE", state.subjectLockProfile.validation?.message || "当前播放速度未通过安全检查。");
    }
    await runSubjectLockProfileAction("play", `以 ${formatNum(speedMmS, 2)} mm/s 正式播放`);
  } catch (error) {
    showError(error);
  }
}

function subjectLockPlaybackSpeed() {
  const input = $("#subjectLockPlaybackSpeedMmS");
  const speed = Number(input?.value);
  if (!Number.isFinite(speed) || speed < 0.2 || speed > 20) {
    throw new ApiError("SUBJECT_LOCK_SPEED_INVALID", "播放速度必须在 0.2 到 20 mm/s 之间。");
  }
  return speed;
}

async function runSubjectLockProfileAction(action, label) {
  const profileId = currentSubjectLockProfileId();
  if (!profileId) return showError(new ApiError("SUBJECT_LOCK_PROFILE_REQUIRED", "请先选择一条轨迹。"));
  try {
    const body = await withSafety({});
    state.subjectLock = await postJson(`/api/v1/subject-lock/profiles/${encodeURIComponent(profileId)}/${action}`, body, { timeout: 10000 });
    renderSubjectLockStatus();
    startSubjectLockPolling();
    log("info", `主体锁定${label}已启动`);
  } catch (error) {
    showError(error);
  }
}

async function stopSubjectLock() {
  try {
    const data = await postJson("/api/v1/subject-lock/playback/stop", {}, { timeout: 10000 });
    state.subjectLock = data.subject_lock || state.subjectLock;
    renderSubjectLockStatus();
    await loadSubjectLockStatus({ quiet: true });
  } catch (error) {
    showError(error);
  }
}

async function handleSubjectLockProfileClick(event) {
  const deleteButton = event.target.closest("[data-subject-lock-delete]");
  if (deleteButton) {
    const profileId = deleteButton.dataset.subjectLockDelete || "";
    if (!profileId || !window.confirm("删除这条主体锁定轨迹？")) return;
    try {
      await deleteJson(`/api/v1/subject-lock/profiles/${encodeURIComponent(profileId)}`);
      if (state.subjectLockProfileId === profileId) {
        state.subjectLockProfileId = "";
        state.subjectLockProfile = null;
      }
      await loadSubjectLockStatus({ quiet: true });
    } catch (error) {
      showError(error);
    }
    return;
  }
  const row = event.target.closest("[data-subject-lock-profile]");
  if (row) loadSubjectLockProfile(row.dataset.subjectLockProfile || "");
}

function currentSubjectLockProfileId() {
  return state.subjectLockProfileId || state.subjectLock?.profile_id || "";
}

function startSubjectLockPolling() {
  if (state.subjectLockTimer) return;
  state.subjectLockTimer = window.setInterval(async () => {
    await loadSubjectLockStatus({ quiet: true, loadProfiles: false, loadProfile: false });
    if (!state.subjectLock?.running) {
      stopSubjectLockPolling();
      await loadSubjectLockStatus({ quiet: true });
    }
  }, 250);
}

function stopSubjectLockPolling() {
  if (state.subjectLockTimer) window.clearInterval(state.subjectLockTimer);
  state.subjectLockTimer = null;
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
      state.action = msg.data.action || state.action;
      handleActionVideoState(state.action?.video_recording);
      if (msg.data.continuous_jog) renderContinuousJog(msg.data.continuous_jog);
      if (msg.data.subject_lock) {
        state.subjectLock = msg.data.subject_lock;
        renderSubjectLockStatus();
      }
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
      <span class="joint-value" id="joint-${key}">${formatJointReadout(key, undefined)}</span>
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
  wrap.addEventListener("contextmenu", (event) => {
    const btn = event.target.closest("button[data-joint]");
    if (!btn) return;
    event.preventDefault();
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

function buildFollowJointChecks() {
  const wrap = $("#followJointChecks");
  if (!wrap) return;
  const axes = { j11: "水平", j12: "垂直", j13: "垂直", j14: "垂直", j15: "水平" };
  wrap.innerHTML = Object.entries(axes)
    .map(
      ([joint, axis]) => `
    <label class="direction-field check-field">
      <span>${joint.toUpperCase()} ${axis}</span>
      <input type="checkbox" data-follow-joint="${joint}" />
    </label>`
    )
    .join("");
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

function openLibraryRenameDialog(kind, name) {
  const label = kind === "pose" ? "姿态" : "动作";
  state.libraryRenameTarget = { kind, name };
  $("#libraryRenameTitle").textContent = `${label}改名`;
  $("#libraryRenameCurrent").textContent = `当前名称：${name}`;
  $("#libraryRenameInput").value = name;
  $("#libraryRenameError").textContent = "";
  const dialog = $("#libraryRenameDialog");
  dialog.showModal();
  window.setTimeout(() => $("#libraryRenameInput").select(), 0);
}

function closeLibraryRenameDialog() {
  state.libraryRenameTarget = null;
  $("#libraryRenameDialog").close();
}

async function submitLibraryRename(event) {
  event.preventDefault();
  const target = state.libraryRenameTarget;
  if (!target) return;
  const newName = $("#libraryRenameInput").value.trim();
  const errorNode = $("#libraryRenameError");
  if (!newName) {
    errorNode.textContent = "名称不能为空。";
    return;
  }
  if (newName === target.name) {
    errorNode.textContent = "请输入一个不同的新名称。";
    return;
  }

  const collection = target.kind === "pose" ? "poses" : "actions";
  const label = target.kind === "pose" ? "姿态" : "动作";
  const submitButton = $("#libraryRenameSubmit");
  submitButton.disabled = true;
  try {
    await postJson(`/api/v1/${collection}/${encodeURIComponent(target.name)}/rename`, { new_name: newName });
    log("info", `${label}已改名：${target.name} → ${newName}`);
    closeLibraryRenameDialog();
    if (target.kind === "pose") {
      $("#poseDetailName").textContent = "未选择";
      $("#poseDetailSummary").textContent = "请选择一个姿态。";
      $("#poseDetailResult").textContent = "";
      await loadPoses();
    } else {
      $("#actionDetailName").textContent = "未选择";
      $("#actionDetailSummary").textContent = "请选择一个动作。";
      $("#actionDetailResult").textContent = "";
      await loadActions();
    }
  } catch (error) {
    errorNode.textContent = error.message || "改名失败。";
    showError(error);
  } finally {
    submitButton.disabled = false;
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
    record_video: $("#recordActionVideo").checked,
  });
  if (!body) return;
  const data = await postJsonLogged("/api/v1/actions/play", body, { timeout: 10000 });
  state.action = data.action || state.action;
  handleActionVideoState(data.video_recording);
}

function handleActionVideoState(video) {
  if (!video || video.state !== "ready" || !video.media_id) return;
  const finishedAt = Number(video.finished_at || 0);
  if (finishedAt && Date.now() / 1000 - finishedAt > 60) return;
  if (state.lastActionVideoDialogId === video.media_id) return;
  state.lastActionVideoDialogId = video.media_id;
  state.lastActionVideo = { ...video };
  const duration = Number(video.duration_sec);
  const durationText = Number.isFinite(duration) ? `，时长 ${duration.toFixed(1)} 秒` : "";
  $("#actionVideoSummary").textContent = `${video.action_name || "动作"} 的录像已保存${durationText}。`;
  $("#actionVideoOpen").href = cameraHubUrl(video.camera_hub_path || `/?media=${encodeURIComponent(video.media_id)}`);
  const dialog = $("#actionVideoDialog");
  if (!dialog.open) dialog.showModal();
}

function cameraHubUrl(path = "/") {
  const port = Number(state.config?.camera_hub?.public_port || 8020);
  const host = window.location.hostname || "127.0.0.1";
  const protocol = window.location.protocol === "https:" ? "https:" : "http:";
  const normalizedPath = String(path || "/").startsWith("/") ? path : `/${path}`;
  return `${protocol}//${host}:${port}${normalizedPath}`;
}

async function loadCommunity() {
  try {
    const params = new URLSearchParams({
      query: $("#communitySearch")?.value || "",
      kind: state.community.kind,
      category: $("#communityCategory")?.value || "all",
      sort: $("#communitySort")?.value || "popular",
      favorite: $("#communityFavoritesOnly")?.checked ? "true" : "false",
    });
    const data = await getJson(`/api/v1/community/items?${params}`);
    state.community.items = data.items || [];
    state.community.stats = data.stats || {};
    renderCommunity();
  } catch (error) {
    showError(error);
  }
}

function renderCommunity() {
  const stats = state.community.stats;
  $("#communityAssetCount").textContent = stats.asset_count ?? "--";
  $("#communityCreatorCount").textContent = stats.creator_count ?? "--";
  $("#communityReuseCount").textContent = formatCompactNumber(stats.reuse_count);
  $("#communityFavoriteCount").textContent = stats.favorite_count ?? 0;
  $("#communityEmpty").classList.toggle("hidden", state.community.items.length > 0);
  $("#communityGrid").innerHTML = state.community.items.map((item) => {
    const summary = item.summary || {};
    const metric = item.kind === "action" ? `${summary.pose_count || 0} 姿态 · ${formatNum(summary.duration_sec, 1)}s` : `V2 · ${summary.joint_count || 6} 关节`;
    return `<article class="community-card" data-community-open="${escapeAttr(item.id)}">
      <div class="community-card-body"><div class="community-card-head"><div><span class="community-type ${item.kind}">${item.kind === "action" ? "动作" : "姿态"}</span><span class="community-category">${escapeHtml(item.category)}</span></div><button class="community-heart ${item.favorite ? "active" : ""}" data-community-favorite="${escapeAttr(item.id)}" type="button" aria-label="${item.favorite ? "取消收藏" : "收藏"}">${item.favorite ? "♥" : "♡"}</button></div><h3>${escapeHtml(item.title)}</h3><p>${escapeHtml(item.description)}</p><div class="community-card-metric">${escapeHtml(metric)}</div><div class="community-card-footer"><span>${escapeHtml(item.author?.name || "MOMO 创作者")}</span><span>↓ ${formatCompactNumber(item.download_count)} · ♥ ${formatCompactNumber(item.like_count)}</span></div></div>
    </article>`;
  }).join("");
  $("#communityGrid").onclick = (event) => {
    const favorite = event.target.closest("button[data-community-favorite]");
    if (favorite) {
      event.stopPropagation();
      const item = state.community.items.find((entry) => entry.id === favorite.dataset.communityFavorite);
      setCommunityFavorite(item.id, !item.favorite);
      return;
    }
    const card = event.target.closest("[data-community-open]");
    if (card) openCommunityDetail(card.dataset.communityOpen);
  };
}

async function openCommunityDetail(itemId) {
  try {
    const data = await getJson(`/api/v1/community/items/${encodeURIComponent(itemId)}`);
    const item = data.item;
    state.community.selected = item;
    const mediaLabel = item.media?.id ? `<span>已关联 Camera Hub 素材</span>` : "";
    $("#communityDetailMeta").innerHTML = `<span class="community-type ${item.kind}">${item.kind === "action" ? "动作" : "姿态"}</span><span>${escapeHtml(item.category)}</span><span class="compat-badge">V2 已适配</span>${mediaLabel}`;
    $("#communityDetailTitle").textContent = item.title;
    $("#communityDetailAuthor").textContent = `${item.author?.name || "MOMO Studio"}  ${item.author?.handle || ""}`;
    $("#communityDetailDescription").textContent = item.description;
    $("#communityDetailTags").innerHTML = (item.tags || []).map((tag) => `<span class="tag on">${escapeHtml(tag)}</span>`).join("");
    const s = item.summary || {};
    const detail = item.kind === "action"
      ? `<dt>轨迹</dt><dd>${s.pose_count} 个姿态 / ${formatNum(s.duration_sec, 1)} 秒</dd><dt>关节范围</dt><dd>${formatJointRanges(s.joint_ranges_deg)}</dd>`
      : `<dt>结构</dt><dd>${s.joint_count} 关节 V2 姿态</dd><dt>关节角度</dt><dd>${(s.joints_deg || []).map((v, i) => `J${i + 10} ${formatNum(v, 1)}°`).join(" · ")}</dd>`;
    $("#communityDetailSpecs").innerHTML = `<dt>兼容型号</dt><dd>机械臂 V2</dd>${detail}<dt>社区数据</dt><dd>${formatCompactNumber(item.like_count)} 赞 · ${formatCompactNumber(item.comment_count)} 评论 · ${formatCompactNumber(item.download_count)} 复用</dd>`;
    $("#communityDetailSafety").textContent = item.safety_note || "导入后仍由本机安全机制管理。";
    $("#communityDetailFavorite").textContent = item.favorite ? "已收藏" : "收藏";
    $("#communityDetailImport").textContent = `加入${item.kind === "action" ? "动作" : "姿态"}库`;
    if (!$("#communityDetailDialog").open) $("#communityDetailDialog").showModal();
  } catch (error) { showError(error); }
}

async function setCommunityFavorite(itemId, favorite) {
  try {
    const data = await postJson(`/api/v1/community/items/${encodeURIComponent(itemId)}/favorite`, { favorite });
    if (state.community.selected?.id === itemId) state.community.selected = data.item;
    await loadCommunity();
  } catch (error) { showError(error); }
}

function toggleCommunityDetailFavorite() {
  const item = state.community.selected;
  if (!item) return;
  setCommunityFavorite(item.id, !item.favorite).then(() => openCommunityDetail(item.id));
}

async function importCommunityItem(itemId, targetName = null) {
  if (!itemId) return;
  try {
    const data = await postJson(`/api/v1/community/items/${encodeURIComponent(itemId)}/import`, { target_name: targetName });
    log("info", data.message);
    if (data.kind === "action") await loadActions(); else await loadPoses();
    $("#communityDetailDialog").close();
    $("#communityImportDialog").close();
    await loadCommunity();
  } catch (error) {
    if (error.code === "COMMUNITY_NAME_CONFLICT") {
      const item = state.community.selected || state.community.importTarget;
      state.community.importTarget = item;
      $("#communityImportName").value = `${targetName || item?.title || "社区资产"} 副本`;
      $("#communityImportError").textContent = "";
      if (!$("#communityImportDialog").open) $("#communityImportDialog").showModal();
      return;
    }
    showError(error);
  }
}

function submitCommunityImportRename(event) {
  event.preventDefault();
  importCommunityItem(state.community.importTarget?.id, $("#communityImportName").value.trim());
}

async function openCommunityPublish(kind = "action", sourceName = "", mediaId = "") {
  state.community.publishPreset = { kind, sourceName, mediaId };
  $("#communityPublishKind").value = kind;
  await Promise.allSettled([loadActions(), loadPoses()]);
  fillCommunityPublishSources(sourceName);
  $("#communityPublishTitle").value = sourceName || $("#communityPublishSource").value || "";
  $("#communityPublishDescription").value = "";
  $("#communityPublishTags").value = "";
  $("#communityPublishError").textContent = "";
  await loadCommunityCameraMedia(mediaId);
  $("#communityPublishDialog").showModal();
}

function fillCommunityPublishSources(preferred = "") {
  const kind = $("#communityPublishKind").value;
  const items = kind === "action" ? state.localActions : state.localPoses;
  $("#communityPublishSource").innerHTML = items.map((item) => `<option value="${escapeAttr(item.name)}">${escapeHtml(item.name)}</option>`).join("");
  if (preferred && items.some((item) => item.name === preferred)) $("#communityPublishSource").value = preferred;
  $("#communityPublishSource").dataset.previousSource = $("#communityPublishSource").value || "";
  if (!$("#communityPublishTitle").value) $("#communityPublishTitle").value = $("#communityPublishSource").value || "";
}

async function loadCommunityCameraMedia(preferred = "") {
  const select = $("#communityPublishMedia");
  select.innerHTML = `<option value="">不关联素材</option>`;
  try {
    const data = await getJson("/api/v1/community/camera-media", { timeout: 4000 });
    $("#communityPublishMediaStatus").textContent = data.available ? `已连接 Camera Hub，可选 ${data.items.length} 个素材。` : "Camera Hub 当前离线，不影响发布。";
    (data.items || []).forEach((item) => select.insertAdjacentHTML("beforeend", `<option value="${escapeAttr(item.id)}">${["video", "recording"].includes(item.type) ? "视频" : "快照"} · ${escapeHtml(item.download_name || item.id)}</option>`));
    if (preferred) select.value = preferred;
  } catch (_) { $("#communityPublishMediaStatus").textContent = "Camera Hub 当前离线，不影响发布。"; }
}

function closeCommunityPublish() { $("#communityPublishDialog").close(); }

async function submitCommunityPublish(event) {
  event.preventDefault();
  const button = $("#communityPublishSubmit");
  button.disabled = true;
  try {
    const data = await postJson("/api/v1/community/items", {
      kind: $("#communityPublishKind").value, source_name: $("#communityPublishSource").value,
      title: $("#communityPublishTitle").value.trim(), category: $("#communityPublishCategory").value,
      description: $("#communityPublishDescription").value.trim(),
      tags: $("#communityPublishTags").value.split(/[，,]/).map((tag) => tag.trim()).filter(Boolean).slice(0, 5),
      media_id: $("#communityPublishMedia").value,
    });
    closeCommunityPublish();
    log("info", data.message);
    showPage("community");
    await loadCommunity();
    openCommunityDetail(data.item.id);
  } catch (error) { $("#communityPublishError").textContent = error.message; showError(error); }
  finally { button.disabled = false; }
}

async function loadComposerSources() {
  const list = $("#composerSourceList");
  list.innerHTML = `<div class="composer-loading">正在读取本地资产库…</div>`;
  try {
    state.composer.sources = await getJson("/api/v1/action-composer/sources", { timeout: 12000 });
    $("#composerVariantLabel").textContent = `${state.composer.sources.robot_variant || "--"} 当前型号 · 仅显示兼容素材`;
    renderComposerSources();
  } catch (error) {
    list.innerHTML = `<div class="composer-loading bad-text">${escapeHtml(error.message)}</div>`;
    showError(error);
  }
}

function renderComposerSources() {
  const composer = state.composer;
  const query = $("#composerSourceSearch").value.trim().toLowerCase();
  const list = $("#composerSourceList");
  if (composer.sourceKind === "action") {
    const actions = (composer.sources.actions || []).filter((item) => {
      const haystack = `${item.name} ${(item.frames || []).map((frame) => frame.name).join(" ")}`.toLowerCase();
      return !query || haystack.includes(query);
    });
    $("#composerSourceCount").textContent = `${actions.length} 个动作`;
    list.innerHTML = actions.length ? actions.map((action) => `
      <details class="composer-source-action">
        <summary><span><strong>${escapeHtml(action.name)}</strong><small>${action.frame_count} 帧</small></span><button type="button" data-composer-add-action="${escapeAttr(action.name)}">全部加入</button></summary>
        <div class="composer-source-frames">
          ${(action.frames || []).map((frame) => `
            <div class="composer-source-frame">
              <div><strong>${escapeHtml(frame.name || `第 ${frame.display_index} 帧`)}</strong><small>${escapeHtml(composerJointSummary(frame.joints_deg))}</small></div>
              <button type="button" data-composer-add-frame="${escapeAttr(action.name)}" data-frame-index="${frame.frame_index}">加入</button>
            </div>`).join("")}
        </div>
      </details>`).join("") : `<div class="composer-loading">没有匹配当前型号的动作帧。</div>`;
    return;
  }

  const poses = (composer.sources.poses || []).filter((item) => !query || `${item.name} ${item.description || ""}`.toLowerCase().includes(query));
  $("#composerSourceCount").textContent = `${poses.length} 个姿态`;
  list.innerHTML = poses.length ? poses.map((pose) => `
    <article class="composer-source-pose">
      <div><strong>${escapeHtml(pose.name)}</strong><small>${escapeHtml(pose.description || composerJointSummary(pose.joints_deg))}</small></div>
      <button type="button" data-composer-add-pose="${escapeAttr(pose.name)}">加入</button>
    </article>`).join("") : `<div class="composer-loading">没有匹配的姿态。</div>`;
}

function handleComposerSourceClick(event) {
  const allButton = event.target.closest("button[data-composer-add-action]");
  const frameButton = event.target.closest("button[data-composer-add-frame]");
  const poseButton = event.target.closest("button[data-composer-add-pose]");
  if (allButton) {
    event.preventDefault();
    const action = (state.composer.sources.actions || []).find((item) => item.name === allButton.dataset.composerAddAction);
    (action?.frames || []).forEach((frame) => addComposerFrame("action", action.name, frame));
    finishComposerFrameChange();
  } else if (frameButton) {
    const action = (state.composer.sources.actions || []).find((item) => item.name === frameButton.dataset.composerAddFrame);
    const frame = action?.frames?.find((item) => item.frame_index === Number(frameButton.dataset.frameIndex));
    if (action && frame) {
      addComposerFrame("action", action.name, frame);
      finishComposerFrameChange();
    }
  } else if (poseButton) {
    const pose = (state.composer.sources.poses || []).find((item) => item.name === poseButton.dataset.composerAddPose);
    if (pose) {
      addComposerFrame("pose", pose.name, pose);
      finishComposerFrameChange();
    }
  }
}

function addComposerFrame(kind, sourceName, source) {
  const duration = Number(source.duration_sec);
  const hold = Number(source.hold_sec);
  state.composer.frames.push({
    instanceId: composerInstanceId(),
    source_kind: kind,
    source_name: sourceName,
    source_frame_index: kind === "action" ? Number(source.frame_index) : null,
    label: source.name || sourceName,
    duration_sec: Number.isFinite(duration) && duration > 0 ? duration : 2.0,
    hold_sec: Number.isFinite(hold) && hold >= 0 ? hold : 0.0,
    joints_deg: { ...(source.joints_deg || {}) },
    legacy_variant_assumed: Boolean(source.legacy_variant_assumed),
  });
}

function finishComposerFrameChange() {
  invalidateComposerPreview();
  renderComposerTimeline();
}

function renderComposerTimeline() {
  const frames = state.composer.frames;
  $("#composerTimelineEmpty").classList.toggle("hidden", frames.length > 0);
  $("#composerClearTimeline").disabled = frames.length === 0;
  $("#composerSaveAction").disabled = frames.length < 2;
  $("#composerTimeline").innerHTML = frames.map((frame, index) => {
    const effective = state.composer.previewSegments[index - 1]?.duration_sec;
    const adjusted = index > 0 && Number.isFinite(effective) && effective > Number(frame.duration_sec) + 0.01;
    return `<article class="composer-keyframe" draggable="true" data-composer-frame-index="${index}">
      <div class="composer-keyframe-head">
        <span class="composer-drag-handle" title="拖拽排序" aria-hidden="true">⋮⋮</span>
        <span class="composer-keyframe-number">${String(index + 1).padStart(2, "0")}</span>
        <span class="community-type ${frame.source_kind === "pose" ? "pose" : ""}">${frame.source_kind === "pose" ? "姿态" : "动作帧"}</span>
      </div>
      <h4>${escapeHtml(frame.label)}</h4>
      <p>${escapeHtml(frame.source_name)}${frame.source_kind === "action" ? ` · #${Number(frame.source_frame_index) + 1}` : ""}</p>
      <div class="composer-joint-strip">${escapeHtml(composerJointSummary(frame.joints_deg))}</div>
      <div class="composer-timing-grid">
        ${index === 0
          ? `<div class="composer-start-marker">轨迹起点</div>`
          : `<label class="${adjusted ? "composer-duration-adjusted" : ""}"><span>从上一帧</span><span class="composer-number-input"><input type="number" min="0.1" max="60" step="0.1" value="${formatComposerNumber(frame.duration_sec)}" data-composer-duration="${index}" /><b>s</b></span>${adjusted ? `<small>安全时长 ${formatNum(effective, 1)}s</small>` : ""}</label>`}
        <label><span>停留</span><span class="composer-number-input"><input type="number" min="0" max="60" step="0.1" value="${formatComposerNumber(frame.hold_sec)}" data-composer-hold="${index}" /><b>s</b></span></label>
      </div>
      <div class="composer-keyframe-actions">
        <button type="button" data-composer-move="up" data-index="${index}" title="上移" aria-label="上移第 ${index + 1} 帧" ${index === 0 ? "disabled" : ""}>↑</button>
        <button type="button" data-composer-move="down" data-index="${index}" title="下移" aria-label="下移第 ${index + 1} 帧" ${index === frames.length - 1 ? "disabled" : ""}>↓</button>
        <button type="button" data-composer-duplicate="${index}" title="复制" aria-label="复制第 ${index + 1} 帧">⧉</button>
        <button type="button" data-composer-remove="${index}" title="删除" aria-label="删除第 ${index + 1} 帧">×</button>
      </div>
    </article>`;
  }).join("");
  updateComposerSummary();
}

function handleComposerTimelineClick(event) {
  const move = event.target.closest("button[data-composer-move]");
  const duplicate = event.target.closest("button[data-composer-duplicate]");
  const remove = event.target.closest("button[data-composer-remove]");
  if (move) {
    const from = Number(move.dataset.index);
    const to = move.dataset.composerMove === "up" ? from - 1 : from + 1;
    moveComposerFrame(from, to);
  } else if (duplicate) {
    const index = Number(duplicate.dataset.composerDuplicate);
    const copy = { ...state.composer.frames[index], joints_deg: { ...state.composer.frames[index].joints_deg }, instanceId: composerInstanceId() };
    state.composer.frames.splice(index + 1, 0, copy);
    finishComposerFrameChange();
  } else if (remove) {
    state.composer.frames.splice(Number(remove.dataset.composerRemove), 1);
    finishComposerFrameChange();
  }
}

function handleComposerTimelineInput(event) {
  const durationIndex = event.target.dataset.composerDuration;
  const holdIndex = event.target.dataset.composerHold;
  const index = durationIndex ?? holdIndex;
  if (index === undefined) return;
  const value = Number(event.target.value);
  if (!Number.isFinite(value)) return;
  if (durationIndex !== undefined) state.composer.frames[Number(index)].duration_sec = value;
  if (holdIndex !== undefined) state.composer.frames[Number(index)].hold_sec = value;
  invalidateComposerPreview();
  updateComposerSummary();
}

function moveComposerFrame(from, to) {
  const frames = state.composer.frames;
  if (from < 0 || from >= frames.length || to < 0 || to >= frames.length || from === to) return;
  const [frame] = frames.splice(from, 1);
  frames.splice(to, 0, frame);
  finishComposerFrameChange();
}

function handleComposerDragStart(event) {
  const card = event.target.closest("[data-composer-frame-index]");
  if (!card || event.target.closest("input, button")) return event.preventDefault();
  state.composer.dragIndex = Number(card.dataset.composerFrameIndex);
  card.classList.add("dragging");
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", String(state.composer.dragIndex));
}

function handleComposerDragOver(event) {
  const card = event.target.closest("[data-composer-frame-index]");
  if (!card || state.composer.dragIndex === null) return;
  event.preventDefault();
  card.classList.add("drag-over");
  event.dataTransfer.dropEffect = "move";
}

function handleComposerDragLeave(event) {
  event.target.closest("[data-composer-frame-index]")?.classList.remove("drag-over");
}

function handleComposerDrop(event) {
  const card = event.target.closest("[data-composer-frame-index]");
  if (!card || state.composer.dragIndex === null) return;
  event.preventDefault();
  const from = state.composer.dragIndex;
  const to = Number(card.dataset.composerFrameIndex);
  clearComposerDragState();
  moveComposerFrame(from, to);
}

function clearComposerDragState() {
  state.composer.dragIndex = null;
  $$(".composer-keyframe.dragging, .composer-keyframe.drag-over").forEach((item) => item.classList.remove("dragging", "drag-over"));
}

function composerPayload(includeName = false) {
  const payload = {
    description: $("#composerDescription").value.trim(),
    entry_duration_sec: Number($("#composerEntryDuration").value || 2),
    frames: state.composer.frames.map((frame) => ({
      source_kind: frame.source_kind,
      source_name: frame.source_name,
      source_frame_index: frame.source_frame_index,
      duration_sec: Math.max(0.1, Number(frame.duration_sec || 0.1)),
      hold_sec: Math.max(0, Number(frame.hold_sec || 0)),
      label: frame.label,
    })),
  };
  if (includeName) payload.name = $("#composerActionName").value.trim();
  return payload;
}

async function buildComposerPreview() {
  if (state.composer.frames.length < 2) return;
  const button = $("#composerBuildPreview");
  button.disabled = true;
  $("#composerPreviewError").textContent = "";
  $("#composerPreviewState").textContent = "生成中";
  await deleteComposerPreviewSession();
  try {
    const data = await postJson("/api/v1/action-composer/preview", composerPayload(), { timeout: 20000 });
    state.composer.previewId = data.preview_id;
    state.composer.previewDuration = Number(data.total_duration_sec || 0);
    state.composer.previewSegments = data.segments || [];
    state.composer.previewTime = 0;
    $("#composerPreviewScrubber").max = String(Math.max(0.01, state.composer.previewDuration));
    $("#composerPreviewScrubber").value = "0";
    $("#composerPreviewScrubber").disabled = false;
    $("#composerPlayPreview").disabled = false;
    $("#composerPausePreview").disabled = true;
    $("#composerPreviewState").textContent = `${data.frame_count} 帧 · ${formatNum(data.total_duration_sec, 1)}s`;
    renderComposerTimeline();
    updateComposerPreviewTime();
    await renderComposerPreviewFrame(0);
  } catch (error) {
    $("#composerPreviewState").textContent = "生成失败";
    $("#composerPreviewError").textContent = error.message;
    showError(error);
  } finally {
    button.disabled = state.composer.frames.length < 2;
  }
}

function playComposerPreview() {
  if (!state.composer.previewId || state.composer.previewPlaying) return;
  if (state.composer.previewTime >= state.composer.previewDuration) state.composer.previewTime = 0;
  state.composer.previewPlaying = true;
  state.composer.previewStartedAt = performance.now() - state.composer.previewTime * 1000;
  $("#composerPlayPreview").disabled = true;
  $("#composerPausePreview").disabled = false;
  state.composer.previewAnimation = requestAnimationFrame(tickComposerPreview);
}

function pauseComposerPreview() {
  state.composer.previewPlaying = false;
  if (state.composer.previewAnimation) cancelAnimationFrame(state.composer.previewAnimation);
  state.composer.previewAnimation = null;
  $("#composerPlayPreview").disabled = !state.composer.previewId;
  $("#composerPausePreview").disabled = true;
}

function tickComposerPreview(now) {
  if (!state.composer.previewPlaying) return;
  let elapsed = (now - state.composer.previewStartedAt) / 1000;
  if (elapsed >= state.composer.previewDuration) {
    if (state.composer.previewLoop && state.composer.previewDuration > 0) {
      elapsed %= state.composer.previewDuration;
      state.composer.previewStartedAt = now - elapsed * 1000;
    } else {
      state.composer.previewTime = state.composer.previewDuration;
      updateComposerPreviewTime();
      renderComposerPreviewFrame(state.composer.previewTime);
      pauseComposerPreview();
      return;
    }
  }
  state.composer.previewTime = elapsed;
  updateComposerPreviewTime();
  renderComposerPreviewFrame(elapsed);
  state.composer.previewAnimation = requestAnimationFrame(tickComposerPreview);
}

function scrubComposerPreview() {
  if (!state.composer.previewId) return;
  pauseComposerPreview();
  state.composer.previewTime = Number($("#composerPreviewScrubber").value || 0);
  updateComposerPreviewTime();
  renderComposerPreviewFrame(state.composer.previewTime);
}

async function renderComposerPreviewFrame(elapsed) {
  if (!state.composer.previewId) return;
  if (state.composer.previewRenderPending) {
    state.composer.previewQueuedTime = elapsed;
    return;
  }
  state.composer.previewRenderPending = true;
  const previewId = state.composer.previewId;
  try {
    const params = new URLSearchParams({ t: Number(elapsed).toFixed(3), width: "640", height: "420", nonce: String(Date.now()) });
    const response = await fetch(`/api/v1/action-composer/preview/${encodeURIComponent(previewId)}/frame.jpg?${params}`, { cache: "no-store" });
    if (!response.ok) {
      let message = `仿真帧请求失败：HTTP ${response.status}`;
      try { message = (await response.json()).error?.message || message; } catch (_) {}
      throw new ApiError("ACTION_COMPOSER_PREVIEW_FRAME_FAILED", message);
    }
    const blob = await response.blob();
    if (state.composer.previewId !== previewId) return;
    if (state.composer.previewObjectUrl) URL.revokeObjectURL(state.composer.previewObjectUrl);
    state.composer.previewObjectUrl = URL.createObjectURL(blob);
    $("#composerPreviewImage").src = state.composer.previewObjectUrl;
    $("#composerPreviewImage").classList.add("ready");
    $("#composerPreviewEmpty").classList.add("hidden");
  } catch (error) {
    $("#composerPreviewError").textContent = error.message;
    pauseComposerPreview();
  } finally {
    state.composer.previewRenderPending = false;
    const queued = state.composer.previewQueuedTime;
    state.composer.previewQueuedTime = null;
    if (queued !== null && Math.abs(Number(queued) - Number(elapsed)) > 0.02) renderComposerPreviewFrame(queued);
  }
}

function updateComposerPreviewTime() {
  $("#composerPreviewScrubber").value = String(state.composer.previewTime);
  $("#composerPreviewTime").textContent = `${formatNum(state.composer.previewTime, 1)} / ${formatNum(state.composer.previewDuration, 1)}s`;
}

function invalidateComposerPreview() {
  pauseComposerPreview();
  deleteComposerPreviewSession();
  if (state.composer.previewObjectUrl) URL.revokeObjectURL(state.composer.previewObjectUrl);
  state.composer.previewObjectUrl = "";
  state.composer.previewDuration = 0;
  state.composer.previewSegments = [];
  state.composer.previewTime = 0;
  $("#composerPreviewState").textContent = "待生成";
  $("#composerPreviewScrubber").value = "0";
  $("#composerPreviewScrubber").max = "1";
  $("#composerPreviewScrubber").disabled = true;
  $("#composerPlayPreview").disabled = true;
  $("#composerPausePreview").disabled = true;
  $("#composerPreviewImage").classList.remove("ready");
  $("#composerPreviewImage").removeAttribute("src");
  $("#composerPreviewEmpty").classList.remove("hidden");
  $("#composerPreviewEmpty").textContent = state.composer.frames.length >= 2 ? "点击生成预览" : "选择至少两个关键帧";
  updateComposerPreviewTime();
}

async function deleteComposerPreviewSession() {
  const previewId = state.composer.previewId;
  state.composer.previewId = "";
  if (!previewId) return;
  try { await deleteJson(`/api/v1/action-composer/preview/${encodeURIComponent(previewId)}`, { timeout: 3000, retries: 0 }); } catch (_) {}
}

async function saveComposedAction() {
  if (state.composer.frames.length < 2) return;
  const errorNode = $("#composerSaveError");
  errorNode.textContent = "";
  errorNode.classList.remove("success");
  const button = $("#composerSaveAction");
  button.disabled = true;
  try {
    const data = await postJson("/api/v1/action-composer/save", composerPayload(true), { timeout: 15000 });
    const message = data.message || `已保存新动作：${data.name}`;
    log("info", message);
    await loadActions();
    resetComposerDraft({ keepMessage: message });
    await loadComposerSources();
  } catch (error) {
    errorNode.textContent = error.message;
    if (error.code === "ACTION_NAME_CONFLICT") $("#composerActionName").focus();
    showError(error);
  } finally {
    $("#composerSaveAction").disabled = state.composer.frames.length < 2;
  }
}

function resetComposerDraft(options = {}) {
  pauseComposerPreview();
  deleteComposerPreviewSession();
  state.composer.frames = [];
  state.composer.previewDuration = 0;
  state.composer.previewSegments = [];
  state.composer.previewTime = 0;
  $("#composerActionName").value = "";
  $("#composerDescription").value = "";
  $("#composerEntryDuration").value = "2.0";
  $("#composerPreviewError").textContent = "";
  $("#composerSaveError").textContent = options.keepMessage || "";
  $("#composerSaveError").classList.toggle("success", Boolean(options.keepMessage));
  invalidateComposerPreview();
  renderComposerTimeline();
}

function updateComposerSummary() {
  const frames = state.composer.frames;
  const requested = frames.reduce((sum, frame, index) => sum + Number(frame.hold_sec || 0) + (index ? Number(frame.duration_sec || 0) : 0), 0);
  const duration = state.composer.previewId ? state.composer.previewDuration : requested;
  const label = state.composer.previewId ? "安全时长" : "配置时长";
  $("#composerTimelineSummary").textContent = `${frames.length} 帧 · ${label} ${formatNum(duration, 1)}s`;
  $("#composerBuildPreview").disabled = frames.length < 2;
}

function composerJointSummary(joints = {}) {
  return JOINTS.map(([key]) => `${key.toUpperCase()} ${formatNum(joints[key], 1)}${key === "j10" ? "mm" : "°"}`).join(" · ");
}

function composerInstanceId() {
  if (window.crypto?.randomUUID) return window.crypto.randomUUID();
  return `frame-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function formatComposerNumber(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number.toFixed(1) : "0.0";
}

function formatCompactNumber(value) { return new Intl.NumberFormat("zh-CN", { notation: Number(value) >= 1000 ? "compact" : "standard", maximumFractionDigits: 1 }).format(Number(value || 0)); }
function formatJointRanges(ranges = {}) { return Object.entries(ranges).map(([joint, values]) => `${joint.toUpperCase()} ${formatNum(values[0], 1)}°~${formatNum(values[1], 1)}°`).join(" · "); }
function debounce(fn, delay) { let timer; return (...args) => { clearTimeout(timer); timer = setTimeout(() => fn(...args), delay); }; }

function updateCameraHubLinks() {
  const url = cameraHubUrl("/");
  ["#cameraHubFollowLink", "#cameraHubSubjectLink", "#cameraHubSettingsLink"].forEach((selector) => {
    const link = $(selector);
    if (link) link.href = url;
  });
}

async function startActionRecording() {
  const name = $("#recordingNameInput").value.trim();
  const body = await withSafety({ name });
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/actions/recording/start", body);
    state.recording = data.recording || {};
    if (!name && state.recording.name) $("#recordingNameInput").value = state.recording.name;
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
  const recording = state.recording || {};
  if (Number(recording.pose_count || 0) < 2) {
    showRecordingFrameWarning();
    return;
  }
  try {
    const clearAutoName = Boolean(recording.auto_named);
    const data = await postJsonLogged("/api/v1/actions/recording/save", {});
    state.recording = data.recording || {};
    if (clearAutoName) $("#recordingNameInput").value = "";
    renderRecordingStatus();
    await loadActions();
  } catch (_) {}
}

function showRecordingFrameWarning() {
  const dialog = $("#recordingFrameWarningDialog");
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
    return;
  }
  window.alert("动作录制至少需要两帧。当前帧已保留，请继续采集后再保存。");
}

async function cancelActionRecording() {
  try {
    const clearAutoName = Boolean(state.recording?.auto_named);
    const data = await postJsonLogged("/api/v1/actions/recording/cancel", {});
    state.recording = data.recording || {};
    if (clearAutoName) $("#recordingNameInput").value = "";
    renderRecordingStatus();
  } catch (_) {}
}

async function computeFk() {
  const joints = JOINTS.map(([key]) => Number($(`#fk-${key}`).value || state.robot?.joints_deg?.[key] || 0));
  try {
    const data = await postJson("/api/v1/kinematics/fk", { joints_deg: joints });
    $("#fkResult").textContent = JSON.stringify(data, null, 2);
    renderFkSummary(data);
    log("info", "FK 计算完成");
  } catch (error) {
    $("#fkSummary").textContent = error.message || String(error);
    $("#fkSummary").className = "kin-result-summary muted-box bad-text";
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
    renderIkSummary(data);
    log("info", "IK 计算完成");
  } catch (error) {
    $("#ikSummary").textContent = error.message || String(error);
    $("#ikSummary").className = "kin-result-summary muted-box bad-text";
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
  invalidateVisibleAgentPendingActions("连接状态已变化");
  state.modeSelectDirty = false;
  await refreshSession();
}

async function disconnectSession() {
  await postJsonLogged("/api/v1/session/disconnect", {});
  invalidateVisibleAgentPendingActions("连接已断开");
  state.modeSelectDirty = false;
  await refreshSession();
}

async function switchMode() {
  const mode = $("#modeSelect").value;
  const body = await withSafety({ mode }, mode === "real");
  if (!body) return;
  await postJsonLogged("/api/v1/session/mode", body);
  invalidateVisibleAgentPendingActions("控制模式已变化");
  state.modeSelectDirty = false;
  await refreshSession();
}

async function startFollow() {
  const followConfig = readFollowConfigForm();
  const body = {
    latest_url: $("#followLatestUrl").value.trim() || "http://127.0.0.1:8000/latest",
    poll_interval: Number($("#followPollInterval").value || 0.05),
    pan_joint: "j11",
    tilt_joint: "j13",
    enabled_follow_joints: followConfig.enabled_follow_joints,
    pan_sign: followConfig.pan_sign,
    tilt_sign: followConfig.tilt_sign,
    pan_dead_zone_norm: followConfig.pan_dead_zone_norm,
    tilt_dead_zone_norm: followConfig.tilt_dead_zone_norm,
    pan_resume_zone_norm: followConfig.pan_resume_zone_norm,
    tilt_resume_zone_norm: followConfig.tilt_resume_zone_norm,
    max_pan_step_deg: followConfig.max_pan_step_deg,
    max_tilt_step_deg: followConfig.max_tilt_step_deg,
    rail_enabled: $("#railEnabled").checked,
    rail_start_mm: Number($("#railStartMm").value || -140),
    rail_end_mm: Number($("#railEndMm").value || 140),
    rail_speed_mm_s: Number($("#railSpeedMmS").value || 5),
  };
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

function renderFollowConfig() {
  const cfg = state.followConfig || state.follow?.effective_config || {};
  $("#followPollInterval").value = formatNum(cfg.poll_interval_sec ?? 0.05, 3);
  $("#followControlHz").value = formatNum(cfg.control_update_hz ?? 40, 0);
  $("#followStaleTimeout").value = formatNum(cfg.vision_stale_timeout_sec ?? 0.25, 2);
  $("#followMaxPanSpeed").value = formatNum(cfg.max_pan_speed_deg_s ?? 12, 2);
  $("#followMaxTiltSpeed").value = formatNum(cfg.max_tilt_speed_deg_s ?? 10, 2);
  $("#followPanAccel").value = formatNum(cfg.pan_accel_deg_s2 ?? 30, 1);
  $("#followTiltAccel").value = formatNum(cfg.tilt_accel_deg_s2 ?? 25, 1);
  $("#followPanDead").value = formatNum(cfg.pan_dead_zone_norm ?? 0.03, 4);
  $("#followTiltDead").value = formatNum(cfg.tilt_dead_zone_norm ?? 0.035, 4);
  $("#followPanResume").value = formatNum(cfg.pan_resume_zone_norm ?? 0.05, 4);
  $("#followTiltResume").value = formatNum(cfg.tilt_resume_zone_norm ?? 0.055, 4);
  $("#followPanSign").value = String(Number(cfg.pan_sign ?? 1) < 0 ? -1 : 1);
  $("#followTiltSign").value = String(Number(cfg.tilt_sign ?? 1) < 0 ? -1 : 1);
  const enabled = new Set(Array.isArray(cfg.enabled_follow_joints) ? cfg.enabled_follow_joints : ["j11", "j13"]);
  $$("[data-follow-joint]").forEach((input) => {
    input.checked = enabled.has(input.dataset.followJoint);
  });
  $("#followConfigState").textContent = "视觉参数已加载";
  $("#followConfigState").className = "inline-status ok-text";
}

function readFollowConfigForm() {
  const enabled = $$("[data-follow-joint]")
    .filter((input) => input.checked)
    .map((input) => input.dataset.followJoint);
  return {
    poll_interval_sec: Number($("#followPollInterval").value || 0.05),
    control_update_hz: Number($("#followControlHz").value || 40),
    vision_stale_timeout_sec: Number($("#followStaleTimeout").value || 0.25),
    max_pan_speed_deg_s: Number($("#followMaxPanSpeed").value || 12),
    max_tilt_speed_deg_s: Number($("#followMaxTiltSpeed").value || 10),
    pan_accel_deg_s2: Number($("#followPanAccel").value || 30),
    tilt_accel_deg_s2: Number($("#followTiltAccel").value || 25),
    pan_joint: "j11",
    tilt_joint: "j13",
    enabled_follow_joints: enabled.length ? enabled : ["j11", "j13"],
    pan_sign: Number($("#followPanSign").value || 1),
    tilt_sign: Number($("#followTiltSign").value || 1),
    pan_dead_zone_norm: Number($("#followPanDead").value || 0.03),
    tilt_dead_zone_norm: Number($("#followTiltDead").value || 0.035),
    pan_resume_zone_norm: Number($("#followPanResume").value || 0.05),
    tilt_resume_zone_norm: Number($("#followTiltResume").value || 0.055),
    rail_cinematic: {
      enabled: $("#railEnabled").checked,
      joint: "j10",
      start_mm: Number($("#railStartMm").value || -140),
      end_mm: Number($("#railEndMm").value || 140),
      speed_mm_s: Number($("#railSpeedMmS").value || 5),
      bounce: false,
    },
  };
}

async function saveFollowConfig() {
  try {
    const data = await postJson("/api/v1/follow/config", readFollowConfigForm());
    state.followConfig = data.follow || {};
    renderFollowConfig();
    $("#followConfigState").textContent = "视觉参数已保存";
    $("#followConfigState").className = "inline-status ok-text";
    log("info", "视觉跟随参数已保存");
    await refreshFollow();
  } catch (error) {
    $("#followConfigState").textContent = error.message || String(error);
    $("#followConfigState").className = "inline-status bad-text";
    showError(error);
  }
}

async function sendAgentMessage() {
  if (state.agentAskBusy || state.agentVoiceMode !== "idle") return;
  const input = $("#agentInput");
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  appendAgentMessage("我", text, "user");
  state.agentAskBusy = true;
  setAgentVoiceControls(state.agentVoiceMode);
  try {
    const data = await postJson("/api/v1/agent/ask", { text, speak: false }, { timeout: 70000 });
    state.lastAgentReply = data;
    const posterUrl = data.raw_payload?.poster_demo ? data.raw_payload?.poster_url : "";
    appendAgentMessage(
      "AI",
      data.reply || data.message || "已完成。",
      "ai",
      posterUrl ? { type: "image", url: posterUrl, title: "AI 海报" } : null,
      data.pending_action || null
    );
    log("info", "AI 对话完成");
    if (data.raw_payload?.agent_demo || data.raw_payload?.poster_demo) {
      await Promise.allSettled([refreshSession(), refreshState(), loadActions()]);
    }
  } catch (error) {
    appendAgentMessage("ERROR", error.message || String(error), "error");
    showError(error);
  } finally {
    state.agentAskBusy = false;
    setAgentVoiceControls(state.agentVoiceMode);
  }
}

function initializeAgentVoice() {
  const supported = Boolean(window.isSecureContext && navigator.mediaDevices?.getUserMedia && window.AudioWorkletNode && window.MomoAudio);
  if (!supported) {
    $("#agentVoiceBtn").disabled = true;
    setAgentVoiceStatus(
      window.isSecureContext ? "当前浏览器不支持网页录音。" : "语音输入需要通过 HTTPS 或 localhost 访问。",
      true
    );
    return;
  }
  state.agentVoiceRecorder = new MomoAudio.VoiceRecorder({
    workletUrl: "/static/audio-recorder-worklet.js?v=20260724-web-cloud-stt",
    maxDurationMs: 20000,
    onTick: renderAgentVoiceElapsed,
    onAutoStop: (wavBlob, error) => {
      if (error) {
        finishAgentVoiceWithError(error);
        return;
      }
      rememberAgentVoiceSelection();
      transcribeAgentAudio(wavBlob);
    },
  });
}

async function toggleAgentVoiceRecording() {
  if (!state.agentVoiceRecorder || state.agentVoiceBusy || state.agentAskBusy) return;
  if (state.agentVoiceRecorder.state === "recording") {
    await stopAgentVoiceRecording();
    return;
  }
  state.agentVoiceBusy = true;
  setAgentVoiceControls("starting");
  setAgentVoiceStatus("正在请求麦克风权限...");
  try {
    await state.agentVoiceRecorder.start();
    state.agentVoiceBusy = false;
    setAgentVoiceControls("recording");
    renderAgentVoiceElapsed(0);
  } catch (error) {
    state.agentVoiceBusy = false;
    finishAgentVoiceWithError(normalizeMicrophoneError(error));
  }
}

async function stopAgentVoiceRecording() {
  if (state.agentVoiceRecorder?.state !== "recording" || state.agentVoiceBusy) return;
  state.agentVoiceBusy = true;
  rememberAgentVoiceSelection();
  setAgentVoiceControls("transcribing");
  setAgentVoiceStatus("正在处理录音...");
  try {
    const wavBlob = await state.agentVoiceRecorder.stop();
    await transcribeAgentAudio(wavBlob);
  } catch (error) {
    finishAgentVoiceWithError(error);
  }
}

async function cancelAgentVoiceRecording() {
  if (!state.agentVoiceRecorder || state.agentVoiceRecorder.state === "idle") return;
  state.agentVoiceBusy = true;
  try {
    await state.agentVoiceRecorder.cancel();
    setAgentVoiceStatus("录音已取消。");
  } catch (error) {
    setAgentVoiceStatus(error.message || String(error), true);
  } finally {
    state.agentVoiceBusy = false;
    setAgentVoiceControls("idle");
  }
}

async function transcribeAgentAudio(wavBlob) {
  if (!wavBlob) return finishAgentVoiceWithError(new Error("录音内容为空。"));
  state.agentVoiceBusy = true;
  setAgentVoiceControls("transcribing");
  setAgentVoiceStatus("正在识别语音...");
  try {
    const data = await postAudioWav("/api/v1/agent/transcribe", wavBlob, { timeout: 35000 });
    const input = $("#agentInput");
    const selection = state.agentVoiceSelection || {
      start: input.selectionStart,
      end: input.selectionEnd,
    };
    const inserted = MomoAudio.insertTranscript(input.value, selection.start, selection.end, data.text);
    input.value = inserted.value;
    input.focus();
    input.setSelectionRange(inserted.selectionStart, inserted.selectionStart);
    setAgentVoiceStatus("识别完成，请确认文字后发送。");
  } catch (error) {
    setAgentVoiceStatus(error.message || String(error), true);
    showError(error);
  } finally {
    state.agentVoiceBusy = false;
    state.agentVoiceSelection = null;
    setAgentVoiceControls("idle");
  }
}

function rememberAgentVoiceSelection() {
  const input = $("#agentInput");
  state.agentVoiceSelection = {
    start: input.selectionStart ?? input.value.length,
    end: input.selectionEnd ?? input.value.length,
  };
}

function renderAgentVoiceElapsed(elapsedMs) {
  const seconds = Math.min(20, Math.floor(Number(elapsedMs || 0) / 1000));
  setAgentVoiceStatus(`录音中 ${String(seconds).padStart(2, "0")} / 20 秒`);
}

function setAgentVoiceControls(mode) {
  state.agentVoiceMode = mode;
  const voiceButton = $("#agentVoiceBtn");
  const cancelButton = $("#cancelAgentVoiceBtn");
  const input = $("#agentInput");
  const sendButton = $("#sendAgentBtn");
  voiceButton.classList.toggle("recording", mode === "recording");
  voiceButton.classList.toggle("transcribing", mode === "transcribing" || mode === "starting");
  voiceButton.disabled = state.agentAskBusy || mode === "transcribing" || mode === "starting";
  voiceButton.setAttribute("aria-label", mode === "recording" ? "停止并识别录音" : "开始语音输入");
  voiceButton.title = mode === "recording" ? "停止并识别录音" : "开始语音输入";
  voiceButton.querySelector("span").textContent = mode === "recording" ? "■" : "🎙";
  cancelButton.classList.toggle("hidden", mode !== "recording");
  input.disabled = mode === "transcribing";
  sendButton.disabled = state.agentAskBusy || mode !== "idle";
}

function setAgentVoiceStatus(message, isError = false) {
  const status = $("#agentVoiceStatus");
  status.textContent = message;
  status.classList.toggle("error", isError);
}

function finishAgentVoiceWithError(error) {
  state.agentVoiceBusy = false;
  state.agentVoiceSelection = null;
  setAgentVoiceControls("idle");
  setAgentVoiceStatus(error.message || String(error), true);
}

function normalizeMicrophoneError(error) {
  if (error?.name === "NotAllowedError") return new Error("麦克风权限被拒绝，请在浏览器设置中允许后重试。");
  if (error?.name === "NotFoundError") return new Error("没有找到可用的麦克风。");
  return error instanceof Error ? error : new Error(String(error));
}

async function resetAgentSession() {
  try {
    await postJson("/api/v1/agent/reset-session", {}, { timeout: 10000 });
    state.agentMessages = [];
    state.lastAgentReply = null;
    renderAgentMessages();
    appendAgentMessage("SYSTEM", "AI 会话已重置。", "system");
  } catch (error) {
    showError(error);
  }
}

function clearAgentChat() {
  state.agentMessages = [];
  state.lastAgentReply = null;
  renderAgentMessages();
}

function useAgentPrompt(text) {
  const input = $("#agentInput");
  input.value = text;
  input.focus();
}

async function stopNow() {
  const errors = [];
  try {
    await postJson("/api/v1/follow/stop", {});
  } catch (error) {
    errors.push(error);
  }
  try {
    await postJson("/api/v1/motion/stop", {});
  } catch (error) {
    errors.push(error);
  }
  log("info", "急停请求已发送");
  invalidateVisibleAgentPendingActions("急停已清除待确认动作");
  await Promise.allSettled([refreshState(), refreshFollow()]);
  if (errors.length) {
    showError(errors[errors.length - 1]);
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
  const cfg = follow.effective_config || {};
  const vision = follow.last_vision || {};
  const offset = vision.offset || {};
  const smoothed = vision.smoothed_offset || {};
  const last = follow.last_command || {};
  const commands = Array.isArray(last.commands) ? last.commands : [];
  $("#followRunning").textContent = follow.running ? "运行" : "停止";
  const sessionMode = follow.dry_run === false ? "real" : "dry-run";
  $("#followModeState").textContent = `${sessionMode} / ${follow.control_mode || "joint_step"}`;
  $("#followStepCount").textContent = `${follow.tick_count ?? follow.step_count ?? 0} / ${formatNum(follow.actual_update_hz, 1)}Hz`;
  const enabledJoints = Array.isArray(cfg.enabled_follow_joints) && cfg.enabled_follow_joints.length ? cfg.enabled_follow_joints : [cfg.pan_joint || "j11", cfg.tilt_joint || "j13"];
  $("#followJointState").textContent = enabledJoints.map((joint) => String(joint).toUpperCase()).join(", ");
  $("#followDeadZoneState").textContent = `pan ${formatNum(cfg.pan_dead_zone_norm, 4)} / tilt ${formatNum(cfg.tilt_dead_zone_norm, 4)}`;
  $("#followRailState").textContent = rail.enabled
    ? `${rail.joint || "j10"} ${rail.running ? "运行" : rail.phase || "停止"} ${formatNum(rail.virtual_pos_mm, 2)}mm`
    : "关闭";
  $("#followDirectionState").textContent = `${vision.direction || "--"} | ndx=${formatNum(smoothed.ndx ?? offset.ndx, 4)}, ndy=${formatNum(smoothed.ndy ?? offset.ndy, 4)}`;
  const targets = last.targets_deg || follow.targets_deg || {};
  $("#followLastCommand").textContent = Object.keys(targets).length
    ? `${Object.entries(targets).map(([joint, value]) => `${joint.toUpperCase()}:${formatNum(value, 2)}`).join(", ")} ${follow.hold_reason ? `(${follow.hold_reason})` : ""}`
    : commands.length ? commands.map(formatFollowCommand).join(", ") : last.message || "--";
  $("#followLastError").textContent = follow.last_error || "--";
}

function formatFollowCommand(cmd) {
  const joint = String(cmd.joint_key || "--").toUpperCase();
  const suffix = cmd.kind === "rail_cinematic" ? "mm" : "deg";
  return `${joint}:${formatNum(cmd.delta_deg, 3)}${suffix}`;
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
  const toolCheck = agent.tool_check || {};
  $("#agentToolCheck").textContent = toolCheck.ok ? "通过" : toolCheck.message || "--";
  $("#agentToolCheck").className = toolCheck.ok ? "ok-text" : "bad-text";
}

function appendAgentMessage(role, text, kind, attachment = null, pendingAction = null) {
  if (pendingAction) invalidateVisibleAgentPendingActions("已被新的待确认动作替换");
  state.agentMessages.push({ role, text, kind, attachment, pendingAction, time: new Date().toLocaleTimeString() });
  state.agentMessages = state.agentMessages.slice(-80);
  renderAgentMessages();
}

function renderAgentMessages() {
  $("#agentChatLog").innerHTML = state.agentMessages
    .map(
      (item) => `<div class="agent-message ${escapeAttr(item.kind)}">
        <strong>[${escapeHtml(item.role)}]</strong>
        <div class="agent-message-content">${escapeHtml(item.text).replace(/\n/g, "<br>")}${renderAgentAttachment(item.attachment)}${renderAgentPendingAction(item.pendingAction)}</div>
      </div>`
    )
    .join("");
  $("#agentChatLog").scrollTop = $("#agentChatLog").scrollHeight;
}

function renderAgentPendingAction(action) {
  if (!action || !action.id) return "";
  const summary = action.summary || {};
  const status = action.uiStatus || action.status || "pending";
  const statusLabels = {
    pending: "等待确认",
    executing: "执行中",
    executed: "已执行",
    cancelled: "已取消",
    expired: "已过期",
    invalidated: "已失效",
  };
  const unit = summary.unit === "mm" ? "mm" : "°";
  const values = [];
  if (summary.joint) values.push(["关节", summary.joint]);
  if (summary.current != null) values.push(["当前", `${formatNum(summary.current, 2)} ${unit}`]);
  if (summary.delta != null) values.push(["变化", `${formatSignedAgentValue(summary.delta)} ${unit}`]);
  if (summary.target != null) values.push(["目标", `${formatNum(summary.target, 2)} ${unit}`]);
  if (summary.open_ratio != null) values.push(["夹爪开度", `${formatNum(Number(summary.open_ratio) * 100, 0)}%`]);
  if (summary.speed_percent != null) values.push(["速度", `${summary.speed_percent}%`]);
  if (summary.speed != null) values.push(["播放速度", `${formatNum(summary.speed, 1)}x`]);
  if (summary.frame_count != null) values.push(["动作帧", String(summary.frame_count)]);
  if (summary.duration_sec != null) values.push(["总时长", `${formatNum(summary.duration_sec, 2)} 秒`]);
  if (summary.pose_name) values.push(["姿态", summary.pose_name]);
  if (summary.description) values.push(["说明", summary.description]);
  if (summary.profile_name) values.push(["轨迹", summary.profile_name]);
  if (summary.operation) {
    values.push(["操作", summary.operation === "move_to_start" ? "回到起点" : "正式播放"]);
  }
  if (summary.rail_start_mm != null && summary.rail_end_mm != null) {
    values.push(["导轨范围", `${formatNum(summary.rail_start_mm, 1)} → ${formatNum(summary.rail_end_mm, 1)} mm`]);
  }
  if (summary.rail_speed_mm_s != null) values.push(["轨迹速度", `${formatNum(summary.rail_speed_mm_s, 2)} mm/s`]);
  if (summary.calibration_point_count != null) values.push(["标定点", String(summary.calibration_point_count)]);
  if (Array.isArray(summary.joints) && summary.joints.length) {
    values.push(["跟随关节", summary.joints.map((joint) => String(joint).toUpperCase()).join(" / ")]);
  }
  const planItems = Array.isArray(summary.items) ? summary.items : [];
  const planHtml = planItems.length
    ? `<div class="agent-pending-plan">${planItems
        .map((item) => {
          const itemUnit = item.unit === "mm" ? "mm" : "°";
          return `<div class="agent-pending-plan-row">
            <strong>${escapeHtml(item.joint || "--")}</strong>
            <span>${escapeHtml(`${formatNum(item.current, 2)} ${itemUnit}`)}</span>
            <span aria-hidden="true">→</span>
            <span>${escapeHtml(`${formatNum(item.target, 2)} ${itemUnit}`)}</span>
            <small>${escapeHtml(`${formatSignedAgentValue(item.delta)} ${itemUnit}`)}</small>
          </div>`;
        })
        .join("")}</div>`
    : "";
  const remaining = Math.max(0, Math.ceil((Number(action.expires_at || 0) * 1000 - Date.now()) / 1000));
  const canAct = status === "pending" && remaining > 0;
  const detail = action.uiMessage || (canAct ? `${remaining} 秒内有效` : statusLabels[status] || status);
  return `<section class="agent-pending-card ${escapeAttr(status)}" data-agent-action-id="${escapeAttr(action.id)}">
    <div class="agent-pending-head">
      <strong>${escapeHtml(summary.title || "待确认动作")}</strong>
      <span>${escapeHtml(statusLabels[status] || status)}</span>
    </div>
    <dl>${values.map(([label, value]) => `<div><dt>${escapeHtml(label)}</dt><dd>${escapeHtml(value)}</dd></div>`).join("")}</dl>
    ${planHtml}
    <p>${escapeHtml(detail)}</p>
    <div class="agent-pending-actions">
      <button class="primary" data-agent-pending-command="confirm" ${canAct ? "" : "disabled"}>确认执行</button>
      <button data-agent-pending-command="cancel" ${canAct ? "" : "disabled"}>取消</button>
    </div>
  </section>`;
}

function handleAgentPendingActionClick(event) {
  const button = event.target.closest("[data-agent-pending-command]");
  if (!button || button.disabled) return;
  const card = button.closest("[data-agent-action-id]");
  if (!card) return;
  const actionId = card.dataset.agentActionId;
  if (button.dataset.agentPendingCommand === "confirm") confirmAgentPendingAction(actionId);
  if (button.dataset.agentPendingCommand === "cancel") cancelAgentPendingAction(actionId);
}

async function confirmAgentPendingAction(actionId) {
  setAgentPendingActionState(actionId, "executing", "正在复核状态并执行");
  try {
    const data = await postJson("/api/v1/agent/pending/confirm", { action_id: actionId }, { timeout: 70000 });
    setAgentPendingActionState(actionId, "executed", data.message || "动作已执行");
    appendAgentMessage("SYSTEM", data.message || "动作已执行。", "system");
    await Promise.allSettled([
      refreshSession(),
      refreshState(),
      loadActions(),
      loadPoses(),
      loadSubjectLockStatus({ quiet: true }),
      refreshFollow(),
    ]);
  } catch (error) {
    setAgentPendingActionState(actionId, "invalidated", error.message || String(error));
    showError(error);
  }
}

async function cancelAgentPendingAction(actionId) {
  setAgentPendingActionState(actionId, "executing", "正在取消");
  try {
    const data = await postJson("/api/v1/agent/pending/cancel", { action_id: actionId }, { timeout: 10000 });
    setAgentPendingActionState(actionId, "cancelled", data.message || "待确认动作已取消");
  } catch (error) {
    setAgentPendingActionState(actionId, "invalidated", error.message || String(error));
    showError(error);
  }
}

function setAgentPendingActionState(actionId, status, message = "") {
  const item = state.agentMessages.find((entry) => entry.pendingAction?.id === actionId);
  if (!item) return;
  item.pendingAction.uiStatus = status;
  item.pendingAction.uiMessage = message;
  renderAgentMessages();
}

function invalidateVisibleAgentPendingActions(message) {
  let changed = false;
  state.agentMessages.forEach((item) => {
    const action = item.pendingAction;
    if (action && (action.uiStatus || action.status) === "pending") {
      action.uiStatus = "invalidated";
      action.uiMessage = message;
      changed = true;
    }
  });
  if (changed) renderAgentMessages();
}

function expireAgentPendingActions() {
  let changed = false;
  state.agentMessages.forEach((item) => {
    const action = item.pendingAction;
    if (!action || (action.uiStatus || action.status) !== "pending") return;
    if (Date.now() >= Number(action.expires_at || 0) * 1000) {
      action.uiStatus = "expired";
      action.uiMessage = "30 秒确认时间已结束，请重新生成动作";
      changed = true;
    }
  });
  if (changed) {
    renderAgentMessages();
    return;
  }
  $$(".agent-pending-card.pending > p").forEach((element) => {
    const card = element.closest("[data-agent-action-id]");
    const item = state.agentMessages.find((entry) => entry.pendingAction?.id === card?.dataset.agentActionId);
    if (!item) return;
    const remaining = Math.max(0, Math.ceil((Number(item.pendingAction.expires_at || 0) * 1000 - Date.now()) / 1000));
    element.textContent = `${remaining} 秒内有效`;
  });
}

function restoreAgentPendingAction(action) {
  if (!action?.id || state.agentMessages.some((item) => item.pendingAction?.id === action.id)) return;
  appendAgentMessage("SYSTEM", "已恢复尚未确认的动作。", "system", null, action);
}

function formatSignedAgentValue(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "--";
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}`;
}

function renderAgentAttachment(attachment) {
  if (!attachment || attachment.type !== "image" || !attachment.url) return "";
  const src = `${attachment.url}${String(attachment.url).includes("?") ? "&" : "?"}t=${Date.now()}`;
  return `
    <figure class="agent-image-attachment">
      <img src="${escapeAttr(src)}" alt="${escapeAttr(attachment.title || "AI 海报")}" />
      <figcaption>${escapeHtml(attachment.title || "AI 海报")}</figcaption>
    </figure>`;
}

function renderSubjectLockStatus() {
  const data = state.subjectLock || {};
  const phaseLabels = {
    idle: "空闲",
    starting: "启动中",
    moving_to_point: "前往标定点",
    centering: "精细居中",
    ready: "可播放",
    needs_speed: "检查未通过",
    moving_to_start: "回到起点",
    at_start: "已到起点",
    playing: "播放中",
    finished: "已完成",
    stopped: "已停止",
    error: "错误",
  };
  const phase = data.phase || "idle";
  const good = ["ready", "at_start", "finished"].includes(phase);
  const bad = ["error", "needs_speed"].includes(phase);
  $("#subjectLockMode").textContent = data.dry_run === false ? "REAL" : "DRY-RUN";
  $("#subjectLockMode").className = `status-pill ${data.dry_run === false ? "bad" : "good"}`;
  $("#subjectLockPhase").textContent = phaseLabels[phase] || phase;
  $("#subjectLockPhase").className = `status-pill ${good ? "good" : bad ? "bad" : "warn"}`;
  $("#subjectLockProgress").value = Math.max(0, Math.min(1, Number(data.progress || 0)));
  $("#subjectLockCurrentProfile").textContent = data.profile_name || data.profile_id || "--";
  $("#subjectLockPointState").textContent = `${data.calibration_point_index || 0} / ${data.calibration_point_count || 11}`;
  $("#subjectLockErrorState").textContent = data.horizontal_error_norm == null ? "--" : formatNum(data.horizontal_error_norm, 4);
  $("#subjectLockVerticalErrorState").textContent = data.vertical_error_norm == null ? "--" : formatNum(data.vertical_error_norm, 4);
  $("#subjectLockVisionAge").textContent = data.latest_vision_age_ms == null ? "--" : `${formatNum(data.latest_vision_age_ms, 1)} ms`;
  $("#subjectLockHoldReason").textContent = data.hold_reason || "--";
  $("#subjectLockFrequency").textContent = data.actual_update_hz ? `${formatNum(data.actual_update_hz, 2)} Hz` : "--";
  $("#subjectLockP95").textContent = data.p95_interval_ms ? `${formatNum(data.p95_interval_ms, 2)} ms` : "--";
  $("#subjectLockSkipped").textContent = String(data.skipped_tick_count || 0);
  $("#subjectLockMessage").textContent = data.last_error || data.message || "等待操作";
  $("#subjectLockMessage").className = `inline-status ${bad ? "bad-text" : good ? "ok-text" : ""}`;
  const targets = data.targets_deg || {};
  $("#subjectLockTargetJ10").textContent = targets.j10 == null ? "--" : `${formatNum(targets.j10, 3)} mm`;
  $("#subjectLockTargetJ11").textContent = targets.j11 == null ? "--" : `${formatNum(targets.j11, 3)}°`;
  $("#subjectLockTargetJ13").textContent = targets.j13 == null ? "--" : `${formatNum(targets.j13, 3)}°`;
  $("#subjectLockWriteCount").textContent = String(data.write_count || 0);
  const running = Boolean(data.running);
  $("#startSubjectLockCalibrationBtn").disabled = running;
  $("#validateSubjectLockBtn").disabled = running || !currentSubjectLockProfileId();
  $("#moveSubjectLockToStartBtn").disabled = running || !state.subjectLockProfile?.validation?.valid;
  $("#playSubjectLockBtn").disabled = running || !state.subjectLockProfile?.validation?.valid;
  $("#stopSubjectLockBtn").disabled = !running;
}

function renderSubjectLockProfiles() {
  const wrap = $("#subjectLockProfilesList");
  const profiles = state.subjectLockProfiles || [];
  wrap.innerHTML = profiles.length
    ? profiles
        .map((item) => {
          const selected = item.profile_id === currentSubjectLockProfileId();
          const valid = Boolean(item.validation?.valid);
          return `<div class="subject-lock-profile-row ${selected ? "active" : ""}">
            <button class="compact-list-row compact-list-button" data-subject-lock-profile="${escapeAttr(item.profile_id || "")}">
              <strong>${escapeHtml(item.name || item.profile_id || "未命名")}</strong>
              <span>${formatNum(item.rail?.start_mm, 1)} → ${formatNum(item.rail?.end_mm, 1)} mm · ${valid ? "可播放" : "需检查"}</span>
            </button>
            <button class="subject-lock-delete" data-subject-lock-delete="${escapeAttr(item.profile_id || "")}" title="删除轨迹" aria-label="删除轨迹">×</button>
          </div>`;
        })
        .join("")
    : `<div class="empty-text">暂无主体锁定轨迹</div>`;
}

function renderSubjectLockProfile() {
  const profile = state.subjectLockProfile || {};
  const rail = profile.rail || {};
  const validation = profile.validation || {};
  const metrics = validation.metrics || {};
  if (profile.profile_id) {
    $("#subjectLockName").value = profile.name || profile.profile_id;
    $("#subjectLockStartMm").value = rail.start_mm ?? -50;
    $("#subjectLockEndMm").value = rail.end_mm ?? 50;
    $("#subjectLockSpeedMmS").value = rail.requested_speed_mm_s ?? 2;
    $("#subjectLockPlaybackSpeedMmS").value = rail.requested_speed_mm_s ?? 2;
  }
  $("#subjectLockValidation").textContent = validation.valid ? "检查通过" : validation.message ? "检查未通过" : "未检查";
  $("#subjectLockValidation").className = `status-pill ${validation.valid ? "good" : validation.message ? "bad" : "warn"}`;
  $("#subjectLockRequestedSpeed").textContent = rail.requested_speed_mm_s == null ? "--" : `${formatNum(rail.requested_speed_mm_s, 3)} mm/s`;
  $("#subjectLockSafeSpeed").textContent = validation.safe_max_speed_mm_s == null ? "--" : `${formatNum(validation.safe_max_speed_mm_s, 3)} mm/s`;
  $("#subjectLockJ11Speed").textContent = metrics.max_j11_speed_deg_s == null ? "--" : `${formatNum(metrics.max_j11_speed_deg_s, 3)}°/s`;
  $("#subjectLockJ11Accel").textContent = metrics.max_j11_accel_deg_s2 == null ? "--" : `${formatNum(metrics.max_j11_accel_deg_s2, 3)}°/s²`;
  renderSubjectLockCurve(profile);
  renderSubjectLockStatus();
}

function renderSubjectLockCurve(profile) {
  const svg = $("#subjectLockCurve");
  const x = profile?.curve?.x || [];
  const y = profile?.curve?.y || [];
  if (x.length < 2 || x.length !== y.length) {
    svg.innerHTML = `<text x="320" y="132" text-anchor="middle" class="curve-empty">等待标定数据</text>`;
    return;
  }
  const minX = Math.min(...x);
  const maxX = Math.max(...x);
  const minY = Math.min(...y);
  const maxY = Math.max(...y);
  const pad = 34;
  const sx = (value) => pad + ((value - minX) / Math.max(1e-9, maxX - minX)) * (640 - pad * 2);
  const sy = (value) => 260 - pad - ((value - minY) / Math.max(1e-9, maxY - minY || 1)) * (260 - pad * 2);
  const points = x.map((value, index) => `${sx(value).toFixed(2)},${sy(y[index]).toFixed(2)}`).join(" ");
  svg.innerHTML = `
    <line class="curve-axis" x1="${pad}" y1="${260 - pad}" x2="${640 - pad}" y2="${260 - pad}" />
    <line class="curve-axis" x1="${pad}" y1="${pad}" x2="${pad}" y2="${260 - pad}" />
    <polyline class="curve-line" points="${points}" />
    ${x.map((value, index) => `<circle class="curve-point" cx="${sx(value)}" cy="${sy(y[index])}" r="4" />`).join("")}
    <text class="curve-label" x="${pad}" y="248">${formatNum(minX, 1)} mm</text>
    <text class="curve-label" x="${640 - pad}" y="248" text-anchor="end">${formatNum(maxX, 1)} mm</text>
    <text class="curve-label" x="42" y="24">J11 ${formatNum(maxY, 1)}°</text>`;
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

async function refreshFollowPageStatus() {
  await Promise.allSettled([refreshFollow(), refreshVisionProxyStatus()]);
}

async function refreshSubjectLockPageStatus() {
  await Promise.allSettled([loadSubjectLockStatus(), refreshSubjectLockTargetState()]);
}

function startVisionStatusPolling() {
  if (state.visionStatusTimer) return;
  state.visionStatusTimer = window.setInterval(refreshActiveVisionStatus, 2000);
}

async function refreshActiveVisionStatus() {
  if (document.hidden || state.visionStatusRefreshInFlight) return;
  const followActive = $("#pageFollow")?.classList.contains("active");
  const subjectLockActive = $("#pageCinematic")?.classList.contains("active");
  if (!followActive && !subjectLockActive) return;

  state.visionStatusRefreshInFlight = true;
  try {
    const requests = [];
    if (followActive) requests.push(refreshVisionProxyStatus());
    if (subjectLockActive) requests.push(refreshSubjectLockTargetState());
    await Promise.allSettled(requests);
  } finally {
    state.visionStatusRefreshInFlight = false;
  }
}

async function refreshVisionProxyStatus() {
  try {
    const [health, latest, targetState, engineStatus, followStatus] = await Promise.all([
      getJson("/api/v1/vision/health", { timeout: 3000 }),
      getJson("/api/v1/vision/latest", { timeout: 3000 }),
      getJson("/api/v1/vision/target/state", { timeout: 3000 }),
      getJson("/api/v1/vision/status", { timeout: 3000 }),
      getJson("/api/v1/follow/status", { timeout: 3000 }),
    ]);
    state.follow = followStatus;
    renderFollow();
    renderVisionHealth(health);
    renderVisionEngineStatus(engineStatus, latest);
    $("#visionLatestState").textContent = latest.detected ? "检测到目标" : latest.message || "未检测";
    $("#visionLatestState").className = latest.detected ? "ok-text" : "";
    renderVisionTargetState(targetState);
    renderVisionLatestDebug(latest);
  } catch (error) {
    $("#visionHealthState").textContent = "视觉服务不可用";
    $("#visionHealthState").className = "bad-text";
    $("#visionEngineState").textContent = "--";
    $("#visionLatestState").textContent = error.message || String(error);
    $("#visionCameraState").textContent = "--";
    $("#visionLatestJson").textContent = "";
    state.latestVision = null;
  }
}

function renderVisionHealth(health) {
  $("#visionHealthState").textContent = health.camera_available ? "camera ok" : health.running ? "running / no camera" : "未启动";
  $("#visionHealthState").className = health.camera_available ? "ok-text" : health.running ? "" : "bad-text";
}

function renderVisionTargetState(targetState) {
  const mode = targetState.target_mode || "--";
  const tracking = targetState.tracking_state || "--";
  const bbox = targetState.tracker_last_bbox || targetState.manual_reference_bbox || targetState.target?.bbox || null;
  $("#visionTargetToolState").textContent = Array.isArray(bbox)
    ? `目标 ${mode} / ${tracking} / bbox=${bbox.map((value) => formatNum(value, 0)).join(",")}`
    : `目标 ${mode} / ${tracking}`;
}

async function refreshSubjectLockTargetState() {
  try {
    const targetState = await getJson("/api/v1/vision/target/state", { timeout: 3000 });
    const source = targetState.target?.source || targetState.target_source || "none";
    $("#subjectLockTargetState").textContent = targetState.has_target
      ? `已锁定 · ${source}`
      : `未锁定 · ${targetState.tracking_state || "idle"}`;
  } catch (_) {
    $("#subjectLockTargetState").textContent = "视觉服务不可用";
  }
}

function renderVisionEngineStatus(status, latest = null) {
  const running = status.running ? "running" : "stopped";
  const camera = status.camera || status.source || {};
  const latestCamera = latest?.camera || {};
  const cameraIndex = camera.camera_index ?? camera.index ?? latestCamera.camera_index ?? latestCamera.index;
  const opened = camera.opened ?? latestCamera.opened ?? latestCamera.available;
  const read = latestCamera.available ?? latest?.detected ?? false;
  const width = latestCamera.width ?? camera.width;
  const height = latestCamera.height ?? camera.height;
  const fps = latest?.fps ?? status.fps;
  const cameraText = camera.available === false || latestCamera.available === false ? "camera unavailable" : cameraIndex != null ? `camera ${cameraIndex}` : "";
  const frameId = status.frame_id ?? status.latest_frame_id ?? "";
  $("#visionEngineState").textContent = [running, cameraText, frameId !== "" ? `frame ${frameId}` : ""].filter(Boolean).join(" / ");
  $("#visionEngineState").className = status.running ? "ok-text" : "bad-text";
  $("#visionCameraState").textContent = `opened=${formatBool(opened)} / read=${formatBool(read)} / index=${cameraIndex ?? "--"}`;
  if (width && height) {
    $("#visionFrameSize").textContent = `${width} x ${height} @ ${formatNum(fps, 1)}fps`;
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
  const desired = offset.desired_center || latest.desired_center || null;
  const deadX = offset.dead_zone_x_norm ?? latest.dead_zone_x_norm ?? 0.02;
  const deadY = offset.dead_zone_y_norm ?? latest.dead_zone_y_norm ?? 0.025;
  const faces = Array.isArray(latest.faces) ? latest.faces : [];
  $("#visionFrameId").textContent = latest.frame_id != null ? String(latest.frame_id) : "--";
  $("#visionTrackingState").textContent = `${latest.target_source || "none"} / ${latest.tracking_state || "idle"}`;
  $("#visionFrameSize").textContent = camera.width && camera.height ? `${camera.width} x ${camera.height} @ ${formatNum(latest.fps, 1)}fps` : "--";
  $("#visionOffsetState").textContent = `ndx=${formatNum(offset.ndx, 4)}, ndy=${formatNum(offset.ndy, 4)} | smooth=${formatNum(smoothed.ndx, 4)},${formatNum(smoothed.ndy, 4)}`;
  $("#visionDesiredCenterState").textContent = Array.isArray(desired) ? desired.map((value) => formatNum(value, 1)).join(", ") : "--";
  $("#visionDeadZoneState").textContent = `x=${formatNum(deadX, 4)}, y=${formatNum(deadY, 4)}, ${offset.in_dead_zone ? "inside" : "outside"}`;
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
      camera: latest.camera,
      offset: latest.offset,
      smoothed_offset: latest.smoothed_offset,
      direction: latest.direction,
      detector: latest.detector,
    },
    null,
    2
  );
}

function formatBool(value) {
  if (value === true) return "true";
  if (value === false) return "false";
  return "--";
}

function renderRobot() {
  if (!state.robot) return;
  state.session.mode = state.robot.mode || state.session.mode;
  state.session.connected = Boolean(state.robot.connected);
  renderSession();
  const joints = state.robot.joints_deg || {};
  JOINTS.forEach(([key]) => {
    const el = $(`#joint-${key}`);
    if (el) el.textContent = formatJointReadout(key, joints[key] ?? 0);
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
            <button data-pose-share="${escapeAttr(item.name)}">分享到社区</button>
            <button data-pose-rename="${escapeAttr(item.name)}">改名</button>
            <button data-pose-delete="${escapeAttr(item.name)}">删除</button>
          </div>
        </article>`;
    })
    .join("");
  $("#posesList").onclick = (event) => {
    const detailBtn = event.target.closest("button[data-pose-detail]");
    const gotoBtn = event.target.closest("button[data-pose-goto]");
    const renameBtn = event.target.closest("button[data-pose-rename]");
    const shareBtn = event.target.closest("button[data-pose-share]");
    const delBtn = event.target.closest("button[data-pose-delete]");
    if (detailBtn) showPoseDetail(detailBtn.dataset.poseDetail);
    if (gotoBtn) gotoPose(gotoBtn.dataset.poseGoto);
    if (renameBtn) openLibraryRenameDialog("pose", renameBtn.dataset.poseRename);
    if (shareBtn) openCommunityPublish("pose", shareBtn.dataset.poseShare);
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
          <p>姿态数：${s.pose_count ?? "--"}，预计时长：${s["总时长"] ?? "--"} 秒（不含前往首帧）</p>
          <div class="tag-row">
            <span class="tag ${s["是否包含 gripper"] ? "on" : ""}">gripper</span>
            <span class="tag ${s["是否包含 tcp_pose"] ? "on" : ""}">tcp_pose</span>
            <span class="tag ${s["是否包含 multi_turn_state"] ? "on" : ""}">multi_turn_state</span>
          </div>
          <div class="button-row">
            <button data-action-play="${escapeAttr(item.name)}">播放</button>
            <button data-action-detail="${escapeAttr(item.name)}">详情</button>
            <button data-action-share="${escapeAttr(item.name)}">分享到社区</button>
            <button data-action-rename="${escapeAttr(item.name)}">改名</button>
            <button data-action-delete="${escapeAttr(item.name)}">删除</button>
          </div>
        </article>`;
    })
    .join("");
  $("#actionsList").onclick = async (event) => {
    const playBtn = event.target.closest("button[data-action-play]");
    const detailBtn = event.target.closest("button[data-action-detail]");
    const renameBtn = event.target.closest("button[data-action-rename]");
    const shareBtn = event.target.closest("button[data-action-share]");
    const deleteBtn = event.target.closest("button[data-action-delete]");
    if (playBtn) playAction(playBtn.dataset.actionPlay);
    if (detailBtn) showActionDetail(detailBtn.dataset.actionDetail);
    if (renameBtn) openLibraryRenameDialog("action", renameBtn.dataset.actionRename);
    if (shareBtn) openCommunityPublish("action", shareBtn.dataset.actionShare);
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
    const confirmed = window.confirm(`是否确认删除动作：${name}？\n删除后无法恢复。`);
    if (!confirmed) return;
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

async function diagnoseBatchCalibration() {
  try {
    const data = await getJson("/api/v1/robot/joint-diagnostics/batch", { timeout: 20000 });
    state.batchDiagnostics = data;
    renderBatchDiagnostics(data);
    $("#calibrationResult").textContent = JSON.stringify(data, null, 2);
  } catch (error) {
    showError(error);
    $("#calibrationResult").textContent = error.message || String(error);
  }
}

function fillBatchCalibrationFromDiagnostics() {
  const diagnostics = state.batchDiagnostics?.diagnostics || {};
  if (!Object.keys(diagnostics).length) {
    showError(new ApiError("NO_BATCH_DIAGNOSTICS", "请先点击“刷新当前状态”。"));
    return;
  }
  $$(".batch-angle-input").forEach((input) => {
    const item = diagnostics[input.dataset.joint];
    if (!item || item.current_angle_deg == null) return;
    input.value = formatNum(item.current_angle_deg, input.dataset.joint === "j10" ? 2 : 2);
  });
  $("#calibrationResult").textContent = "已把当前软件换算值填入输入框。请只保留你确认要修正的关节，其他输入框清空。";
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
    showError(new ApiError("BAD_INPUT", "请至少填写一个关节的当前逻辑值。"));
    return;
  }
  const body = await withSafety({ joint_angles_deg: jointAngles }, true);
  if (!body) return;
  try {
    const data = await postJsonLogged("/api/v1/robot/calibration/current-angles", body, { timeout: 20000 });
    $("#calibrationResult").textContent = JSON.stringify(data, null, 2);
    await loadCalibration();
    await diagnoseBatchCalibration();
  } catch (_) {}
}

function renderBatchDiagnostics(data) {
  const diagnostics = data.diagnostics || {};
  const errors = data.errors || {};
  const rows = ["j10", "j11", "j12", "j13", "j14", "j15"]
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
  renderKinematicsSummary(urdf, model);
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

function renderKinematicsSummary(urdf, model) {
  const errors = urdf.errors || [];
  const warnings = urdf.warnings || [];
  const missingMeshes = urdf.missing_meshes || [];
  const joints = model.ordered_joint_urdf_names || [];
  const cards = [
    ["检查结果", errors.length ? `${errors.length} 个错误` : warnings.length ? `${warnings.length} 个提醒` : "通过", errors.length ? "bad-text" : "ok-text"],
    ["模型状态", model.available ? "PyBullet 可用" : model.error || "不可用", model.available ? "ok-text" : "bad-text"],
    ["关节链", joints.length ? joints.join(" / ") : "--", ""],
    ["资源", missingMeshes.length ? `${missingMeshes.length} 个缺失资源` : "资源完整", missingMeshes.length ? "bad-text" : "ok-text"],
  ];
  $("#kinStatusSummary").innerHTML = cards
    .map(
      ([label, value, klass]) => `<div class="kin-summary-card">
        <strong>${escapeHtml(label)}</strong>
        <span class="${escapeAttr(klass)}">${escapeHtml(value)}</span>
      </div>`
    )
    .join("");
}

function renderFkSummary(data) {
  const pose = data.tcp_pose || {};
  const xyz = pose.xyz || pose.xyz_m || data.xyz || [];
  const rpy = pose.rpy || pose.rpy_rad || data.rpy || [];
  $("#fkSummary").className = "kin-result-summary muted-box";
  $("#fkSummary").innerHTML = [
    `<div><strong>末端位置</strong></div>${formatVectorGrid(["x", "y", "z"], xyz, 4, "m")}`,
    `<div><strong>末端姿态</strong></div>${formatVectorGrid(["roll", "pitch", "yaw"], rpy, 4, "rad")}`,
  ].join("");
}

function renderIkSummary(data) {
  const targets = data.target_joints_deg || data.solution_joints_deg || {};
  const ik = data.ik || {};
  const predicted = data.predicted_xyz_m || data.predicted_xyz || ik.xyz || data.tcp_pose?.xyz || [];
  const error = data.position_error_m ?? data.pos_error_m ?? data.error_m ?? ik.position_error_m;
  $("#ikSummary").className = "kin-result-summary muted-box";
  const jointItems = JOINTS.map(([key], index) => `<span>${key.toUpperCase()} ${formatNum(jointValue(targets, key, index), 2)}</span>`).join("");
  $("#ikSummary").innerHTML = [
    `<div><strong>目标关节</strong></div><div class="kin-result-grid">${jointItems}</div>`,
    `<div><strong>预测位置</strong></div>${formatVectorGrid(["x", "y", "z"], predicted, 4, "m")}`,
    `<div>位置误差：${formatNum(error, 5)} m</div>`,
  ].join("");
}

function jointValue(targets, key, index) {
  if (Array.isArray(targets)) return targets[index];
  return targets ? targets[key] : undefined;
}

function formatVectorGrid(labels, values, digits = 3, unit = "") {
  return `<div class="kin-result-grid">${labels
    .map((label, index) => `<span>${escapeHtml(label)} ${formatNum(values[index], digits)}${unit ? ` ${escapeHtml(unit)}` : ""}</span>`)
    .join("")}</div>`;
}

function renderMotionTuning() {
  const t = state.motionTuning || state.config?.motion || {};
  const overrides = t.jog_direction_overrides || {};
  $("#motionSpeedPercent").value = formatNum(t.default_speed_percent ?? 50, 0);
  $("#continuousUpdateHz").value = formatNum(t.continuous_update_hz ?? 50, 1);
  $("#playbackUpdateHz").value = formatNum(t.playback_update_hz ?? 20, 1);
  $$("[data-jog-direction]").forEach((select) => {
    const joint = select.dataset.jogDirection;
    select.value = String(Number(overrides[joint] ?? 1) < 0 ? -1 : 1);
  });
  $("#continuousSpeedInput").disabled = state.jointControlMode !== "continuous";
  if ($("#motionTuningState")) {
    $("#motionTuningState").textContent = "当前调参已加载";
    $("#motionTuningState").className = "inline-status ok-text";
  }
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
    continuous_update_hz: Number($("#continuousUpdateHz").value || 50),
    playback_update_hz: Number($("#playbackUpdateHz").value || 20),
    jog_direction_overrides: readJogDirectionOverrides(),
  };
  try {
    const data = await postJson("/api/v1/motion/tuning", body);
    state.motionTuning = data.motion || data;
    renderMotionTuning();
    $("#motionTuningState").textContent = `已同步 ${Array.isArray(data.saved_paths) ? data.saved_paths.length : 0} 个配置文件`;
    $("#motionTuningState").className = "inline-status ok-text";
    log("info", "运动调参已保存");
  } catch (error) {
    showError(error);
  }
}

async function resetMotionTuning() {
  try {
    const data = await postJson("/api/v1/motion/tuning", {
      default_speed_percent: 50,
      continuous_update_hz: 50,
      playback_update_hz: 20,
      jog_direction_overrides: Object.fromEntries(JOINTS.map(([key]) => [key, 1])),
    });
    state.motionTuning = data.motion || data;
    renderMotionTuning();
    $("#motionTuningState").textContent = `已恢复 Web 推荐值并同步 ${Array.isArray(data.saved_paths) ? data.saved_paths.length : 0} 个配置文件`;
    $("#motionTuningState").className = "inline-status ok-text";
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
    actual_update_hz: jog.actual_update_hz ?? null,
    mean_interval_ms: jog.mean_interval_ms ?? null,
    p95_interval_ms: jog.p95_interval_ms ?? null,
    max_interval_ms: jog.max_interval_ms ?? null,
    skipped_tick_count: jog.skipped_tick_count ?? null,
    write_count: jog.write_count ?? null,
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
  const leavingComposer = name !== "composer" && $("#pageComposer")?.classList.contains("active");
  if (leavingComposer) resetComposerDraft();
  if (name !== "cinematic") stopSubjectLockPolling();
  if (name !== "agent" && state.agentVoiceRecorder?.state === "recording") cancelAgentVoiceRecording();
  $$(".nav-item").forEach((btn) => btn.classList.toggle("active", btn.dataset.page === name));
  $$(".page").forEach((page) => page.classList.remove("active"));
  $(`#page${capitalize(name)}`).classList.add("active");
  if (name === "poses") loadPoses();
  if (name === "actions") loadActions();
  if (name === "composer") loadComposerSources();
  if (name === "community") loadCommunity();
  if (name === "follow") {
    refreshFollow();
    loadFollowConfig();
    refreshVisionProxyStatus();
  }
  if (name === "agent") loadAgentStatus();
  if (name === "cinematic") {
    loadSubjectLockStatus().then(() => {
      if (state.subjectLock?.running) startSubjectLockPolling();
    });
    refreshSubjectLockTargetState();
  }
  if (name === "kinematics") {
    loadKinematicsStatus();
    refreshKinematicsRender();
  }
  if (name === "calibration") loadCalibration();
  if (name === "calibration") diagnoseBatchCalibration();
  if (name === "settings") {
    loadDependencies();
    loadHardwareCheck();
    loadMotionTuning();
  }
}

function showError(error) {
  const code = error.code || "ERROR";
  if (code === "GRIPPER_UNAVAILABLE") return;
  const rawMessage = error.message || String(error);
  const message = isRealServoCommError(code, rawMessage)
    ? `真实舵机通信/写入失败，已停止真实动作。请先运行轻量 SDK 只读总线扫描：诊断舵机总线_lightweight_sdk.py --port /dev/momo-servo --no-gripper；再检查对应 ID 的电源、负载、线序、USB/串口稳定性。原始错误：${rawMessage}`
    : rawMessage;
  state.lastError = `${code}: ${message}`;
  $("#topError").textContent = state.lastError;
  $("#topError").classList.remove("hidden");
  log("error", state.lastError);
  setTimeout(() => $("#topError").classList.add("hidden"), 6000);
}

function isRealServoCommError(code, message) {
  const text = `${code || ""} ${message || ""}`.toLowerCase();
  return (
    text.includes("real_servo_comm_failed") ||
    text.includes("there is no status packet") ||
    text.includes("txrxresult") ||
    text.includes("status packet") ||
    (text.includes("写入") && text.includes("id") && (text.includes("失败") || text.includes("重试")))
  );
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

function formatJointReadout(jointKey, value) {
  const formatted = formatNum(value, 2);
  return jointKey === "j10" ? `${formatted} mm` : `${formatted}°`;
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
