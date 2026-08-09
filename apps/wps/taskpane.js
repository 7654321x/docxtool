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
    if (!config.controlBaseUrl || !config.sessionToken || typeof fetch !== "function") return;
    void fetch(`${config.controlBaseUrl}/v1/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${config.sessionToken}` },
      body: JSON.stringify({ level, component: "taskpane", event, message, details: details || {} })
    }).catch(() => undefined);
  }

  function request(commandName) {
    const requestId = `pane-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
    log("INFO", "taskpane.request.prepare", "开始准备任务窗格请求", {
      request_id: requestId, command: commandName, pane_instance_id: paneInstanceId
    });
    const serialized = JSON.stringify({ request_id: requestId, command_name: commandName, created_at: new Date().toISOString() });
    log("INFO", "taskpane.storage.write.start", "开始写入任务窗格请求", {
      request_id: requestId, command: commandName, pane_instance_id: paneInstanceId,
      request_key: REQUEST_KEY
    });
    storage().setItem(REQUEST_KEY, serialized);
    log("INFO", "taskpane.storage.write.completed", "任务窗格请求写入完成", {
      request_id: requestId, command: commandName, value_present: true
    });
    const readback = storage().getItem(REQUEST_KEY);
    const readbackRequest = readback ? JSON.parse(readback) : null;
    log("INFO", "taskpane.storage.write.verified", "任务窗格请求读回验证完成", {
      request_id: requestId, command: commandName, readback_present: Boolean(readback),
      request_id_match: Boolean(readbackRequest && readbackRequest.request_id === requestId)
    });
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
      log("WARN", "taskpane.focus_document.failed", "返回当前文档失败", { pane_instance_id: paneInstanceId, error_code: error && error.message ? error.message : "UNKNOWN" });
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
      log("WARN", "taskpane.close.failed", "任务窗格隐藏失败", { pane_instance_id: paneInstanceId, error_code: error && error.message ? error.message : "UNKNOWN" });
    }
  }

  function formatWarning(value) {
    if (typeof value === "string") return value;
    if (!value || typeof value !== "object") return String(value || "");
    return Object.entries(value).map(([key, item]) => `${key}=${String(item)}`).join("；");
  }

  function render(state) {
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
    node("summary").textContent = `文档模式 ${recognition.document_mode || "UNKNOWN"}；识别 ${recognition.block_count || 0} 项；安全批注 ${state.preview_comment_count || 0}；绑定复核 ${recognition.binding_review_count || 0}；未定位 ${recognition.unresolved_count || 0}`;
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

  function poll() {
    try {
      const raw = storage().getItem(STATE_KEY);
      if (!raw) return;
      const state = JSON.parse(raw);
      if (state.updated_at && state.updated_at === lastUpdated) return;
      lastUpdated = state.updated_at || "";
      render(state);
    } catch (error) {
      log("WARNING", "taskpane.state.invalid", "任务窗格状态读取失败", {
        pane_instance_id: paneInstanceId,
        error_code: error && error.message ? error.message : "TASKPANE_STATE_INVALID"
      });
      node("error").textContent = error && error.message ? error.message : "TASKPANE_RENDER_FAILED";
    }
  }

  ["preview", "apply", "clear_preview", "health"].forEach((id) => node(id).addEventListener("click", () => request(id)));
  node("focus_document").addEventListener("click", focusDocument);
  node("close_panel").addEventListener("click", closePanel);

  setInterval(poll, 300);
  poll();
  log("INFO", "taskpane.loaded", "DocxTool WPS 任务窗格已加载", { pane_instance_id: paneInstanceId });
})();
