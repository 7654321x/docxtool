(function () {
  "use strict";

  const globalObject = window;
  const app = globalObject.Application;
  const config = globalObject.DocxToolWpsConfig || {};
  const STATE_KEY = "docxtool_wps_state_v1";
  const REQUEST_KEY = "docxtool_wps_request_v1";
  const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
  let busy = false;
  let lastRequestId = "";

  const roleNames = {
    main_title: "主标题",
    title_continuation: "主标题续行",
    heading1: "一级标题",
    heading2: "二级标题",
    heading3: "三级标题",
    heading4: "四级标题",
    body: "正文",
    recipient: "称呼",
    role_name: "职务姓名",
    attachment_note: "附件说明",
    attachment_note_item: "附件说明续项",
    attachment_title: "附件正文标题",
    attachment_page_mark: "附件正文标记",
    attachment_body: "附件正文",
    signature_org: "落款署名",
    signature_date: "落款日期",
    caption: "对象题注",
    unknown: "未知"
  };

  function storage() {
    if (!app || !app.PluginStorage) throw new Error("WPS_PLUGIN_STORAGE_UNAVAILABLE");
    return app.PluginStorage;
  }

  function readState() {
    try {
      const value = storage().getItem(STATE_KEY);
      return value ? JSON.parse(value) : {};
    } catch (_) {
      return {};
    }
  }

  function writeState(patch) {
    const state = Object.assign({}, readState(), patch, { updated_at: new Date().toISOString() });
    storage().setItem(STATE_KEY, JSON.stringify(state));
    return state;
  }

  function safeDetails(details) {
    const result = {};
    if (!details || typeof details !== "object") return result;
    Object.keys(details).slice(0, 20).forEach((key) => {
      const value = details[key];
      if (["string", "number", "boolean"].includes(typeof value) || value == null) result[key] = value;
    });
    return result;
  }

  function log(level, event, message, details) {
    const line = `[WPS][host] ${event} | ${message}`;
    if (level === "ERROR") console.error(line, details || {});
    else if (level === "WARN" || level === "WARNING") console.warn(line, details || {});
    else console.log(line, details || {});
    if (!config.controlBaseUrl || !config.sessionToken || typeof fetch !== "function") return;
    void fetch(`${config.controlBaseUrl}/v1/log`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.sessionToken}`
      },
      body: JSON.stringify({ level, component: "host", event, message, details: safeDetails(details) })
    }).catch(() => undefined);
  }

  async function api(path, body, method) {
    if (!config.controlBaseUrl || !config.sessionToken) throw new Error("WPS_CONTROL_NOT_CONFIGURED");
    const response = await fetch(`${config.controlBaseUrl}${path}`, {
      method: method || "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.sessionToken}`
      },
      body: method === "GET" ? undefined : JSON.stringify(body || {})
    });
    const payload = await response.json();
    if (!response.ok || !payload.ok) throw new Error(payload.error_code || "WPS_CONTROL_REQUEST_FAILED");
    return payload.data;
  }

  function activeDocument() {
    const document = app && app.ActiveDocument;
    if (!document) throw new Error("NO_ACTIVE_DOCUMENT");
    return document;
  }

  function savedDocxPath() {
    const document = activeDocument();
    const path = String(document.FullName || "");
    if (!path || !path.toLowerCase().endsWith(".docx")) throw new Error("DOCUMENT_MUST_BE_SAVED_AS_DOCX");
    return path;
  }

  function saveActiveDocument() {
    const document = activeDocument();
    if (typeof document.Save !== "function") throw new Error("DOCUMENT_SAVE_UNSUPPORTED");
    document.Save();
    return savedDocxPath();
  }

  function taskpaneUrl() {
    return new URL("taskpane.html", globalObject.location.href).href;
  }

  function openTaskpane() {
    if (!app || typeof app.CreateTaskPane !== "function") throw new Error("TASKPANE_UNSUPPORTED");
    const current = storage().getItem(TASKPANE_KEY);
    if (current && typeof app.GetTaskPane === "function") {
      try {
        const pane = app.GetTaskPane(Number(current));
        if (pane) {
          pane.Visible = true;
          return pane;
        }
      } catch (_) {
        storage().setItem(TASKPANE_KEY, "");
      }
    }
    const pane = app.CreateTaskPane(taskpaneUrl(), "DocxTool");
    pane.Visible = true;
    if ("Width" in pane) pane.Width = 390;
    storage().setItem(TASKPANE_KEY, String(pane.ID));
    return pane;
  }

  async function runPreview() {
    const sourcePath = saveActiveDocument();
    writeState({ status: "RUNNING", stage: "recognition", message: "正在识别当前文档…", error_code: "" });
    const result = await api("/v1/recognize", { source_path: sourcePath });
    const rows = (result.items || []).map((item) => ({
      block_index: item.block_index,
      paragraph_index: item.physical_paragraph_index,
      type_id: item.type_id,
      role_name: roleNames[item.type_id] || item.type_id,
      confidence: item.confidence,
      review_level: item.review_level,
      locator_verified: item.locator_verified,
      segment_index: item.segment_index,
      segment_count: item.segment_count
    }));
    writeState({
      status: "PASS",
      stage: "recognition_completed",
      message: `识别完成：${result.block_count} 项；建议复核 ${result.review_count}；未定位 ${result.unresolved_count}`,
      recognition: result,
      recognition_rows: rows,
      error_code: ""
    });
    openTaskpane();
    log("INFO", "preview.completed", "预览识别完成", { blocks: result.block_count, review: result.review_count, unresolved: result.unresolved_count });
  }

  function clearPreview() {
    writeState({
      status: "PASS",
      stage: "preview_cleared",
      message: "预览结果已清除；未修改文档格式或用户批注。",
      recognition: null,
      recognition_rows: [],
      error_code: ""
    });
    log("INFO", "preview.cleared", "预览状态已清除");
  }

  async function runFormat() {
    const document = activeDocument();
    const sourcePath = saveActiveDocument();
    let operationId = "";
    let committed = false;
    writeState({ status: "RUNNING", stage: "format_prepare", message: "正在调用 DocxTool Engine 排版…", error_code: "" });
    log("INFO", "format.start", "一键排版开始");
    try {
      const prepared = await api("/v1/format/prepare", { source_path: sourcePath });
      operationId = prepared.operation_id;
      writeState({ status: "RUNNING", stage: "document_close", message: "排版结果已生成，正在安全替换当前文档…", operation_id: operationId });
      if (typeof document.Close !== "function") throw new Error("DOCUMENT_CLOSE_UNSUPPORTED");
      document.Close(0);

      await api("/v1/format/commit", { operation_id: operationId });
      committed = true;
      if (!app.Documents || typeof app.Documents.Open !== "function") throw new Error("DOCUMENT_OPEN_UNSUPPORTED");
      app.Documents.Open(sourcePath);
      await api("/v1/format/finalize", { operation_id: operationId });
      writeState({
        status: "PASS",
        stage: "completed",
        message: `排版完成：${prepared.paragraph_count} 个段落，${prepared.heading_count} 个标题。`,
        format_result: prepared,
        error_code: "",
        operation_id: ""
      });
      log("INFO", "format.completed", "一键排版完成", { paragraphs: prepared.paragraph_count, headings: prepared.heading_count });
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_FORMAT_FAILED";
      if (operationId) {
        try {
          await api("/v1/format/rollback", { operation_id: operationId });
          committed = false;
        } catch (rollbackError) {
          log("ERROR", "format.rollback.failed", "一键排版回滚失败", { error_code: rollbackError && rollbackError.message ? rollbackError.message : "UNKNOWN" });
        }
      }
      if (committed && app.Documents && typeof app.Documents.Open === "function") {
        try { app.Documents.Open(sourcePath); } catch (_) { /* source recovery is already server-owned */ }
      } else if (app.Documents && typeof app.Documents.Open === "function") {
        try { app.Documents.Open(sourcePath); } catch (_) { /* original may still be open or reopening may be unnecessary */ }
      }
      throw new Error(code);
    }
  }

  async function runHealth() {
    const result = await api("/v1/health", null, "GET");
    writeState({ status: "PASS", stage: "health", message: `本地服务正常；DocxTool ${result.docxtool_version}`, health: result, error_code: "" });
    openTaskpane();
    log("INFO", "health.pass", "WPS 本机检测通过", { docxtool_version: result.docxtool_version });
  }

  async function runCommand(name) {
    if (busy && name !== "panel") throw new Error("WPS_COMMAND_BUSY");
    if (name === "panel") {
      openTaskpane();
      return;
    }
    busy = true;
    try {
      if (name === "preview") await runPreview();
      else if (name === "apply") await runFormat();
      else if (name === "clear_preview") clearPreview();
      else if (name === "health") await runHealth();
      else throw new Error("WPS_COMMAND_UNKNOWN");
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_COMMAND_FAILED";
      writeState({ status: "FAIL", stage: "failed", message: `失败：${code}`, error_code: code });
      log("ERROR", "command.failed", "WPS 命令执行失败", { command: name, error_code: code });
      try { openTaskpane(); } catch (_) { /* primary error is already persisted */ }
      throw error;
    } finally {
      busy = false;
      try { if (app.ribbonUI && typeof app.ribbonUI.Invalidate === "function") app.ribbonUI.Invalidate(); } catch (_) {}
    }
  }

  function pollTaskpaneRequests() {
    try {
      const raw = storage().getItem(REQUEST_KEY);
      if (!raw) return;
      const request = JSON.parse(raw);
      if (!request || !request.request_id || request.request_id === lastRequestId) return;
      lastRequestId = request.request_id;
      storage().setItem(REQUEST_KEY, "");
      void runCommand(request.command_name).catch(() => undefined);
    } catch (error) {
      log("ERROR", "taskpane.request.failed", "任务窗格请求处理失败", { error_code: error && error.message ? error.message : "UNKNOWN" });
    }
  }

  globalObject.OnAddinLoad = function (ribbonUI) {
    if (app) app.ribbonUI = ribbonUI;
    writeState({ status: "READY", stage: "ready", message: "DocxTool WPS 已就绪", recognition_rows: [], error_code: "" });
    setInterval(pollTaskpaneRequests, 250);
    log("INFO", "addin.loaded", "DocxTool WPS 插件已加载");
  };

  globalObject.OnAction = function (control) {
    const id = control && (control.Id || control.id) ? String(control.Id || control.id) : "";
    void runCommand(id).catch(() => undefined);
  };

  globalObject.GetActionEnabled = function (control) {
    const id = control && (control.Id || control.id) ? String(control.Id || control.id) : "";
    if (id === "panel" || id === "health") return !busy;
    try {
      return !busy && savedDocxPath().toLowerCase().endsWith(".docx");
    } catch (_) {
      return false;
    }
  };
})();
