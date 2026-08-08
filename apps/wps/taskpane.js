(function () {
  "use strict";

  const app = window.Application;
  const config = window.DocxToolWpsConfig || {};
  const STATE_KEY = "docxtool_wps_state_v1";
  const REQUEST_KEY = "docxtool_wps_request_v1";
  let lastUpdated = "";

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
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.sessionToken}`
      },
      body: JSON.stringify({ level, component: "taskpane", event, message, details: details || {} })
    }).catch(() => undefined);
  }

  function request(commandName) {
    const requestId = `pane-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
    storage().setItem(REQUEST_KEY, JSON.stringify({
      request_id: requestId,
      command_name: commandName,
      created_at: new Date().toISOString()
    }));
    node("message").textContent = "命令已发送，等待 WPS 主上下文处理…";
    log("INFO", "request.created", "任务窗格命令已发送", { command: commandName, request_id: requestId });
  }

  function render(state) {
    node("status").textContent = state.status || "READY";
    node("message").textContent = state.message || "就绪";
    node("error").textContent = state.error_code || "";
    const recognition = state.recognition;
    if (!recognition) {
      node("summary").textContent = "尚未识别。";
      node("rows").replaceChildren();
      return;
    }
    node("summary").textContent = `文档模式 ${recognition.document_mode || "UNKNOWN"}；识别 ${recognition.block_count || 0} 项；建议复核 ${recognition.review_count || 0}；未定位 ${recognition.unresolved_count || 0}`;
    const rows = Array.isArray(state.recognition_rows) ? state.recognition_rows : [];
    node("rows").replaceChildren(...rows.map((item) => {
      const row = document.createElement("div");
      row.className = "row";
      const paragraph = Number.isInteger(item.paragraph_index) ? `段落 ${item.paragraph_index + 1}` : "结构项";
      const confidence = Math.round(Number(item.confidence || 0) * 100);
      const locator = item.locator_verified ? "已定位" : "未定位";
      row.textContent = `${paragraph} · ${item.role_name || item.type_id || "未知"} · ${confidence}% · ${locator}${item.review_level === "review" || item.review_level === "critical_review" ? " · 建议复核" : ""}`;
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
      node("error").textContent = error && error.message ? error.message : "TASKPANE_RENDER_FAILED";
    }
  }

  ["preview", "apply", "clear_preview", "health"].forEach((id) => {
    node(id).addEventListener("click", () => request(id));
  });

  setInterval(poll, 300);
  poll();
  log("INFO", "loaded", "DocxTool WPS 任务窗格已加载");
})();
