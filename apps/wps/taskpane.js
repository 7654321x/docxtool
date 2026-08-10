(function () {
  "use strict";

  const app = window.Application;
  const config = window.DocxToolWpsConfig || {};
  const STATE_KEY = "docxtool_wps_state_v1";
  const REQUEST_KEY = "docxtool_wps_request_v1";
  const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
  const paneInstanceId = `pane-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
  let lastUpdated = "";
  let lastStatus = "";
  let pendingRequestId = "";
  let pendingRequestedAt = 0;
  let pendingClaimed = false;
  let logSequence = 0;
  let logTransportFailureReported = false;
  let logTransportUnavailableReported = false;
  let pollTimer = null;
  let pollingStopped = false;
  const REQUEST_ACK_TIMEOUT_MS = 5000;
  const SAFE_DETAIL_FIELDS = new Set([
    "command", "current_status", "document_name", "error_code", "error_type", "event_sequence", "host_ready",
    "pane_instance_id", "pending_present", "previous_status", "readback_present", "reason",
    "request_id", "request_id_match", "request_key", "request_status", "slot_occupied", "stage",
    "value_present", "cause_event"
  ]);

  function node(id) {
    const value = document.getElementById(id);
    if (!value) throw new Error("TASKPANE_ELEMENT_MISSING");
    return value;
  }

  function storage() {
    if (!app || !app.PluginStorage) throw new Error("WPS_PLUGIN_STORAGE_UNAVAILABLE");
    return app.PluginStorage;
  }

  function log(level, event, message, details) {
    const safeDetails = {};
    Object.keys(details || {}).forEach((key) => {
      const value = details[key];
      if (SAFE_DETAIL_FIELDS.has(key) && (["string", "number", "boolean"].includes(typeof value) || value == null)) {
        safeDetails[key] = value;
      }
    });
    safeDetails.event_sequence = ++logSequence;
    const line = `[WPS][taskpane] ${event} | ${message}`;
    if (level === "ERROR") console.error(line, safeDetails);
    else if (level === "WARN" || level === "WARNING") console.warn(line, safeDetails);
    else console.log(line, safeDetails);
    if (!config.controlBaseUrl || !config.sessionToken || typeof fetch !== "function") {
      if (!logTransportUnavailableReported) {
        logTransportUnavailableReported = true;
        console.error("[WPS][taskpane] log.transport.unavailable | 任务窗格日志传输配置不可用", {
          control_url_present: Boolean(config.controlBaseUrl),
          token_present: Boolean(config.sessionToken),
          error_code: "WPS_LOG_TRANSPORT_UNAVAILABLE"
        });
      }
      return;
    }
    const headers = { "Content-Type": "application/json", "Authorization": `Bearer ${config.sessionToken}` };
    if (safeDetails.request_id) headers["X-DocxTool-Request-Id"] = safeDetails.request_id;
    void fetch(`${config.controlBaseUrl}/v1/log`, {
      method: "POST",
      headers,
      body: JSON.stringify({ level, component: "taskpane", event, message, details: safeDetails })
    }).then((response) => {
      if (!response.ok) throw new Error("WPS_LOG_HTTP_FAILED");
      logTransportFailureReported = false;
    }).catch((error) => {
      if (logTransportFailureReported) return;
      logTransportFailureReported = true;
      console.error("[WPS][taskpane] log.transport.failed | 任务窗格日志传输失败", {
        error_code: stableErrorCode(error, "WPS_LOG_TRANSPORT_FAILED")
      });
    });
  }

  function contextDetails(state) {
    return {
      host_ready: Boolean(state && state.host_ready === true),
      document_name: state && state.document_name ? String(state.document_name) : ""
    };
  }

  function stableErrorCode(error, fallback) {
    const value = error && error.message ? String(error.message) : "";
    return /^[A-Z][A-Z0-9_]{2,100}$/.test(value) ? value : fallback;
  }

  function setBusinessButtonsDisabled(disabled) {
    ["preview", "apply", "clear_preview", "health"].forEach((id) => { node(id).disabled = Boolean(disabled); });
  }

  function request(commandName) {
    const state = readState();
    let occupiedValue;
    try {
      occupiedValue = storage().getItem(REQUEST_KEY);
    } catch (error) {
      log("ERROR", "taskpane.request_slot.read_failed", "任务窗格请求槽读取失败", {
        command: commandName, error_code: "WPS_REQUEST_SLOT_READ_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_REQUEST_SLOT_READ_FAILED");
    }
    if (pendingRequestId || occupiedValue) {
      node("message").textContent = "命令正在处理中。";
      node("error").textContent = "WPS_COMMAND_BUSY";
      log("WARNING", "taskpane.request.blocked.busy", "任务窗格请求被忙碌状态阻止", Object.assign(contextDetails(state), {
        command: commandName, reason: "pending_request", request_status: "BLOCKED",
        pending_present: Boolean(pendingRequestId), slot_occupied: Boolean(occupiedValue),
        error_code: "WPS_COMMAND_BUSY"
      }));
      return;
    }
    if (state.host_ready !== true) {
      node("message").textContent = "WPS Host 尚未就绪，请重启 WPS。";
      node("error").textContent = "WPS_HOST_NOT_READY";
      log("WARNING", "taskpane.request.blocked.host_not_ready", "任务窗格请求因 Host 未就绪被阻止", Object.assign(contextDetails(state), {
        command: commandName, reason: "host_not_ready", request_status: "BLOCKED",
        pending_present: false, slot_occupied: false, error_code: "WPS_HOST_NOT_READY"
      }));
      return;
    }
    const requestId = `pane-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
    log("INFO", "taskpane.request.prepare", "开始准备任务窗格请求", {
      request_id: requestId, command: commandName, pane_instance_id: paneInstanceId
    });
    let serialized;
    try {
      serialized = JSON.stringify({
        schema_version: "wps-request-v2", request_id: requestId, command_name: commandName,
        created_at: new Date().toISOString(), pane_instance_id: paneInstanceId
      });
    } catch (error) {
      log("ERROR", "taskpane.request.serialize_failed", "任务窗格请求序列化失败", {
        request_id: requestId, command: commandName,
        error_code: "WPS_REQUEST_SERIALIZE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_REQUEST_SERIALIZE_FAILED");
    }
    log("INFO", "taskpane.storage.write.start", "开始写入任务窗格请求", {
      request_id: requestId, command: commandName, pane_instance_id: paneInstanceId,
      request_key: REQUEST_KEY
    });
    try {
      storage().setItem(REQUEST_KEY, serialized);
    } catch (error) {
      log("ERROR", "taskpane.storage.write.failed", "任务窗格请求写入失败", {
        request_id: requestId, command: commandName,
        error_code: "WPS_REQUEST_SLOT_WRITE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_REQUEST_SLOT_WRITE_FAILED");
    }
    log("INFO", "taskpane.storage.write.completed", "任务窗格请求写入完成", {
      request_id: requestId, command: commandName, value_present: true
    });
    let readback;
    try {
      readback = storage().getItem(REQUEST_KEY);
    } catch (error) {
      log("ERROR", "taskpane.storage.readback.failed", "任务窗格请求读回失败", {
        request_id: requestId, command: commandName,
        error_code: "WPS_REQUEST_READBACK_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_REQUEST_READBACK_FAILED");
    }
    let readbackRequest;
    try {
      readbackRequest = readback ? JSON.parse(readback) : null;
    } catch (error) {
      log("ERROR", "taskpane.storage.readback.parse_failed", "任务窗格请求读回内容无效", {
        request_id: requestId, command: commandName,
        error_code: "WPS_REQUEST_READBACK_JSON_INVALID",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_REQUEST_READBACK_JSON_INVALID");
    }
    log("INFO", "taskpane.storage.write.verified", "任务窗格请求读回验证完成", {
      request_id: requestId, command: commandName, readback_present: Boolean(readback),
      request_id_match: Boolean(readbackRequest && readbackRequest.request_id === requestId)
    });
    if (!readbackRequest || readbackRequest.request_id !== requestId) {
      log("ERROR", "taskpane.storage.write.verify_failed", "任务窗格请求写入校验失败", {
        request_id: requestId, command: commandName,
        readback_present: Boolean(readback), request_id_match: false,
        error_code: "WPS_REQUEST_WRITE_VERIFY_FAILED"
      });
      throw new Error("WPS_REQUEST_WRITE_VERIFY_FAILED");
    }
    pendingRequestId = requestId;
    pendingRequestedAt = Date.now();
    pendingClaimed = false;
    setBusinessButtonsDisabled(true);
    node("message").textContent = "命令已发送，等待 WPS 主上下文处理…";
    log("INFO", "taskpane.request.created", "任务窗格命令已发送", {
      pane_instance_id: paneInstanceId, command: commandName, request_id: requestId
    });
  }

  function focusDocument() {
    log("INFO", "taskpane.focus_document.start", "开始返回当前文档", { pane_instance_id: paneInstanceId });
    try {
      const document = app && app.ActiveDocument;
      if (document && typeof document.Activate === "function") document.Activate();
      if (document && document.ActiveWindow && typeof document.ActiveWindow.Activate === "function") document.ActiveWindow.Activate();
      log("INFO", "taskpane.focus_document.completed", "已返回当前文档", { pane_instance_id: paneInstanceId });
    } catch (error) {
      log("WARN", "taskpane.focus_document.failed", "返回当前文档失败", { pane_instance_id: paneInstanceId, error_code: stableErrorCode(error, "WPS_FOCUS_DOCUMENT_FAILED") });
    }
  }

  function closePanel() {
    log("INFO", "taskpane.close.start", "开始关闭任务窗格", { pane_instance_id: paneInstanceId });
    try {
      const saved = storage().getItem(TASKPANE_KEY);
      if (!saved || !app || typeof app.GetTaskPane !== "function") return;
      const pane = app.GetTaskPane(Number(saved));
      if (pane) pane.Visible = false;
      log("INFO", "taskpane.close.completed", "任务窗格已隐藏", { pane_instance_id: paneInstanceId });
    } catch (error) {
      log("WARN", "taskpane.close.failed", "任务窗格隐藏失败", { pane_instance_id: paneInstanceId, error_code: stableErrorCode(error, "WPS_TASKPANE_CLOSE_FAILED") });
    }
  }

  function formatWarning(value) {
    if (typeof value === "string") return value;
    if (!value || typeof value !== "object") return String(value || "");
    return Object.entries(value).map(([key, item]) => `${key}=${String(item)}`).join("；");
  }

  function readState() {
    let raw;
    try {
      raw = storage().getItem(STATE_KEY);
    } catch (error) {
      log("ERROR", "taskpane.state.read_failed", "任务窗格状态读取失败", {
        error_code: "WPS_STATE_READ_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_STATE_READ_FAILED");
    }
    if (!raw) return {};
    try {
      return JSON.parse(raw);
    } catch (error) {
      log("ERROR", "taskpane.state.parse_failed", "任务窗格状态 JSON 无效", {
        error_code: "WPS_STATE_JSON_INVALID",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_STATE_JSON_INVALID");
    }
  }

  function updatePendingRequest(state) {
    if (!pendingRequestId) return;
    const active = [state.active_request, state.last_request].find((item) => item && item.request_id === pendingRequestId) || {};
    if (active.request_id === pendingRequestId && ["CLAIMED", "RUNNING"].includes(active.request_status) && !pendingClaimed) {
      pendingClaimed = true;
      log("INFO", "taskpane.request.claimed", "任务窗格请求已被 Host 领取", { request_id: pendingRequestId, request_status: active.request_status });
    }
    if (active.request_id === pendingRequestId && ["PASS", "FAIL"].includes(active.request_status)) {
      log("INFO", "taskpane.request.completed", "任务窗格请求已完成", { request_id: pendingRequestId, request_status: active.request_status });
      pendingRequestId = "";
      pendingRequestedAt = 0;
      pendingClaimed = false;
      setBusinessButtonsDisabled(false);
      return;
    }
    if (Date.now() - pendingRequestedAt >= REQUEST_ACK_TIMEOUT_MS) {
      node("error").textContent = "REQUEST_ACK_TIMEOUT";
      log("WARNING", "taskpane.request.timeout", "任务窗格请求领取超时", { request_id: pendingRequestId, error_code: "WPS_REQUEST_ACK_TIMEOUT" });
      pendingRequestId = "";
      pendingRequestedAt = 0;
      pendingClaimed = false;
      setBusinessButtonsDisabled(false);
    }
  }

  function render(state) {
    updatePendingRequest(state);
    if (state.host_ready !== true) {
      node("status").textContent = "NOT_READY";
      node("message").textContent = "WPS Host 尚未就绪，请重启 WPS。";
      node("error").textContent = "";
      node("summary").textContent = "尚未识别。";
      node("warnings").textContent = "";
      node("rows").replaceChildren();
      setBusinessButtonsDisabled(true);
      log("WARNING", "taskpane.host.not_ready", "任务窗格检测到 Host 尚未就绪", Object.assign(contextDetails(state), {
        reason: "host_not_ready", error_code: "WPS_HOST_NOT_READY"
      }));
      return;
    }
    setBusinessButtonsDisabled(Boolean(pendingRequestId));
    const currentStatus = state.status || "READY";
    if (currentStatus !== lastStatus) {
      log("INFO", "taskpane.state.changed", "任务窗格状态已变化", {
        pane_instance_id: paneInstanceId, previous_status: lastStatus, current_status: currentStatus,
        stage: state.stage || ""
      });
      lastStatus = currentStatus;
    }
    node("status").textContent = currentStatus;
    node("message").textContent = state.message || "就绪";
    node("error").textContent = state.error_code || "";
    const warnings = Array.isArray(state.compatibility_warnings) ? state.compatibility_warnings : [];
    node("warnings").textContent = warnings.length ? `兼容性提示：${warnings.map(formatWarning).join("；")}` : "";
    const recognition = state.recognition;
    if (!recognition) {
      node("summary").textContent = "尚未识别。";
      node("rows").replaceChildren();
      return;
    }
    node("summary").textContent = `文档模式 ${recognition.document_mode || "UNKNOWN"}；识别 ${recognition.block_count || 0} 项；批注 ${state.preview_comment_count || 0}；确认 ${state.preview_confirmed_count || 0}；复核 ${state.preview_review_count || 0}；未定位 ${recognition.unresolved_count || 0}`;
    const rows = Array.isArray(state.recognition_rows) ? state.recognition_rows : [];
    node("rows").replaceChildren(...rows.map((item) => {
      const row = document.createElement("div");
      row.className = "row";
      const paragraph = Number.isInteger(item.paragraph_index) ? `段落 ${item.paragraph_index + 1}` : "结构项";
      const confidence = Math.round(Number(item.confidence || 0) * 100);
      const binding = item.binding_status === "confirmed" ? "已确认" : item.binding_status === "review" ? "需复核" : "未定位";
      row.textContent = `${paragraph} · ${item.role_name || item.type_id || "未知"} · ${confidence}% · ${binding}${item.review_level === "review" || item.review_level === "critical_review" ? " · 识别建议复核" : ""}`;
      return row;
    }));
  }

  function stopPollingForStateFailure(error) {
    if (pollingStopped) return;
    pollingStopped = true;
    if (pollTimer !== null) clearInterval(pollTimer);
    pollTimer = null;
    const errorCode = stableErrorCode(error, "WPS_TASKPANE_STATE_INVALID");
    const storageFailure = errorCode === "WPS_STATE_READ_FAILED";
    setBusinessButtonsDisabled(true);
    node("status").textContent = "ERROR";
    node("message").textContent = "任务窗格状态通道不可用，请重新打开状态面板。";
    node("error").textContent = errorCode;
    log("ERROR", storageFailure
      ? "taskpane.poll.stopped.storage_failure"
      : "taskpane.poll.stopped.state_invalid", "任务窗格状态轮询已停止", {
      pane_instance_id: paneInstanceId,
      cause_event: storageFailure ? "taskpane.state.read_failed" : "taskpane.state.parse_failed",
      error_code: errorCode
    });
  }

  function poll() {
    if (pollingStopped) return;
    try {
      const state = readState();
      if (!state.updated_at) return;
      if (state.updated_at && state.updated_at === lastUpdated) return;
      lastUpdated = state.updated_at || "";
      render(state);
    } catch (error) {
      stopPollingForStateFailure(error);
    }
  }

  ["preview", "apply", "clear_preview", "health"].forEach((id) => node(id).addEventListener("click", () => {
    try {
      request(id);
    } catch (error) {
      const code = stableErrorCode(error, "WPS_TASKPANE_REQUEST_FAILED");
      node("message").textContent = "命令发送失败。";
      node("error").textContent = code;
      log("ERROR", "taskpane.request.failed", "任务窗格命令发送失败", {
        command: id, error_code: code,
        error_type: error && error.name ? error.name : "Error"
      });
    }
  }));
  node("focus_document").addEventListener("click", focusDocument);
  node("close_panel").addEventListener("click", closePanel);

  try {
    const initialState = readState();
    render(initialState);
    log("INFO", "taskpane.loaded", "DocxTool WPS 任务窗格已加载", Object.assign(contextDetails(initialState), {
      pane_instance_id: paneInstanceId, pending_present: false,
      slot_occupied: Boolean(storage().getItem(REQUEST_KEY))
    }));
    pollTimer = setInterval(poll, 300);
  } catch (error) {
    pollingStopped = true;
    setBusinessButtonsDisabled(true);
    const errorCode = stableErrorCode(error, "WPS_TASKPANE_LOAD_FAILED");
    node("status").textContent = "ERROR";
    node("message").textContent = "任务窗格加载失败，请重新打开状态面板。";
    node("error").textContent = errorCode;
    log("ERROR", "taskpane.load.failed", "任务窗格初始化失败", {
      pane_instance_id: paneInstanceId,
      error_code: errorCode,
      error_type: error && error.name ? error.name : "Error"
    });
  }
})();
