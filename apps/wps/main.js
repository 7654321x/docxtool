(function () {
  "use strict";

  const globalObject = window;
  const app = globalObject.Application;
  const config = globalObject.DocxToolWpsConfig || {};
  const STATE_KEY = "docxtool_wps_state_v1";
  const REQUEST_KEY = "docxtool_wps_request_v1";
  const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
  const PREVIEW_KEY = "docxtool_wps_preview_v1";
  const PREVIEW_BATCH_SIZE = 5;
  let busy = false;
  let lastRequestId = "";

  const roleNames = {
    main_title: "主标题", title_continuation: "主标题续行",
    heading1: "一级标题", heading2: "二级标题", heading3: "三级标题", heading4: "四级标题",
    body: "正文", recipient: "称呼", role_name: "职务姓名",
    attachment_note: "附件说明", attachment_note_item: "附件说明续项",
    attachment_title: "附件正文标题", attachment_page_mark: "附件正文标记", attachment_body: "附件正文",
    signature_org: "落款署名", signature_date: "落款日期", caption: "对象题注", unknown: "未知"
  };

  function storage() {
    if (!app || !app.PluginStorage) throw new Error("WPS_PLUGIN_STORAGE_UNAVAILABLE");
    return app.PluginStorage;
  }

  function readState() {
    try { const value = storage().getItem(STATE_KEY); return value ? JSON.parse(value) : {}; }
    catch (_) { return {}; }
  }

  function writeState(patch) {
    const state = Object.assign({}, readState(), patch, { updated_at: new Date().toISOString() });
    storage().setItem(STATE_KEY, JSON.stringify(state));
    return state;
  }

  function randomId() {
    if (globalObject.crypto && typeof globalObject.crypto.randomUUID === "function") return globalObject.crypto.randomUUID();
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
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
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${config.sessionToken}` },
      body: JSON.stringify({ level, component: "host", event, message, details: safeDetails(details) })
    }).catch(() => undefined);
  }

  async function api(path, body, method) {
    if (!config.controlBaseUrl || !config.sessionToken) throw new Error("WPS_CONTROL_NOT_CONFIGURED");
    const response = await fetch(`${config.controlBaseUrl}${path}`, {
      method: method || "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${config.sessionToken}` },
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
    const path = String(activeDocument().FullName || "");
    if (!path || !path.toLowerCase().endsWith(".docx")) throw new Error("DOCUMENT_MUST_BE_SAVED_AS_DOCX");
    return path;
  }

  function saveActiveDocument() {
    const document = activeDocument();
    if (typeof document.Save !== "function") throw new Error("DOCUMENT_SAVE_UNSUPPORTED");
    document.Save();
    return savedDocxPath();
  }

  async function sha256(value) {
    if (!globalObject.crypto || !globalObject.crypto.subtle) throw new Error("WEB_CRYPTO_UNAVAILABLE");
    const digest = await globalObject.crypto.subtle.digest("SHA-256", new TextEncoder().encode(String(value)));
    return Array.from(new Uint8Array(digest), (item) => item.toString(16).padStart(2, "0")).join("");
  }

  function stripWpsTerminator(value) {
    let text = String(value || "");
    if (text.endsWith("\r\f")) text = text.slice(0, -2);
    if (text.endsWith("\x07")) text = text.slice(0, -1);
    if (text.endsWith("\r")) text = text.slice(0, -1);
    return text;
  }

  function characterOrdinalAtUtf16Offset(value, offset) {
    let position = 0;
    let ordinal = 0;
    for (const character of value) {
      if (position === offset) return ordinal;
      position += character.length;
      ordinal += 1;
    }
    if (position === offset) return ordinal;
    throw new Error("HOST_RANGE_UTF16_BOUNDARY_INVALID");
  }

  async function previewRange(document, item) {
    if (!item.locator_verified || !Number.isInteger(item.physical_paragraph_index)) throw new Error("PREVIEW_LOCATOR_UNVERIFIED");
    if (!Number.isInteger(item.raw_start_utf16) || !Number.isInteger(item.raw_end_utf16) || item.raw_end_utf16 <= item.raw_start_utf16) throw new Error("PREVIEW_RANGE_INVALID");
    const paragraph = document.Paragraphs && document.Paragraphs.Item ? document.Paragraphs.Item(item.physical_paragraph_index + 1) : null;
    const paragraphRange = paragraph && paragraph.Range;
    if (!paragraphRange) throw new Error("PREVIEW_PARAGRAPH_NOT_FOUND");
    const raw = stripWpsTerminator(paragraphRange.Text);
    if (await sha256(raw) !== item.physical_text_sha256) throw new Error("PREVIEW_PARAGRAPH_CHANGED");
    if (item.raw_end_utf16 > raw.length) throw new Error("PREVIEW_RANGE_INVALID");
    const fragment = raw.slice(item.raw_start_utf16, item.raw_end_utf16);
    if (await sha256(fragment) !== item.text_sha256) throw new Error("PREVIEW_RANGE_HASH_MISMATCH");
    const characters = paragraphRange.Characters;
    if (!characters || typeof characters.Item !== "function") throw new Error("PREVIEW_CHARACTERS_UNSUPPORTED");
    const firstOrdinal = characterOrdinalAtUtf16Offset(raw, item.raw_start_utf16);
    const endOrdinal = characterOrdinalAtUtf16Offset(raw, item.raw_end_utf16);
    const first = characters.Item(firstOrdinal + 1);
    const last = characters.Item(endOrdinal);
    if (!first || !last || typeof first.SetRange !== "function") throw new Error("PREVIEW_RANGE_BOUNDARY_INVALID");
    first.SetRange(Number(first.Start), Number(last.End));
    if (await sha256(stripWpsTerminator(first.Text)) !== item.text_sha256) throw new Error("PREVIEW_RANGE_READBACK_MISMATCH");
    return first;
  }

  async function currentDocumentPathHash() {
    return sha256(savedDocxPath().toLowerCase());
  }

  async function clearPreviewComments(options) {
    const silent = Boolean(options && options.silent);
    const raw = storage().getItem(PREVIEW_KEY);
    if (!raw) return 0;
    let session;
    try { session = JSON.parse(raw); }
    catch (_) { storage().setItem(PREVIEW_KEY, ""); return 0; }
    const currentHash = await currentDocumentPathHash();
    if (currentHash !== session.document_path_hash) {
      if (silent) return 0;
      throw new Error("DOCUMENT_CHANGED");
    }
    const comments = activeDocument().Comments;
    if (!comments || typeof comments.Item !== "function") throw new Error("COMMENT_PREVIEW_UNSUPPORTED");
    let deleted = 0;
    for (let index = Number(comments.Count || 0); index >= 1; index -= 1) {
      const comment = comments.Item(index);
      if (String(comment.Author || "") !== session.author || String(comment.Initial || "") !== session.initial) continue;
      if (typeof comment.Delete !== "function") throw new Error("PREVIEW_COMMENT_DELETE_UNSUPPORTED");
      comment.Delete();
      deleted += 1;
    }
    storage().setItem(PREVIEW_KEY, "");
    log("INFO", "preview.comments.cleared", "预览批注已清除", { deleted_count: deleted });
    return deleted;
  }

  async function applyPreviewComments(result) {
    await clearPreviewComments({ silent: true });
    const document = activeDocument();
    const comments = document.Comments;
    if (!comments || typeof comments.Add !== "function") throw new Error("COMMENT_PREVIEW_UNSUPPORTED");
    const sessionId = randomId();
    const author = `DocxTool·${sessionId.slice(-8)}`;
    const initial = "DCT";
    const created = [];
    let applied = 0;
    try {
      for (const item of result.items || []) {
        if (!item.locator_verified) continue;
        const range = await previewRange(document, item);
        const role = roleNames[item.type_id] || item.type_id || "未知";
        const confidence = Math.round(Number(item.confidence || 0) * 100);
        const review = item.review_level === "review" || item.review_level === "critical_review" ? "；建议人工复核" : "";
        const comment = comments.Add(range, `DocxTool 预览：${role}；置信度 ${confidence}%${review}。正式格式由 DocxTool Engine 统一生成。`);
        if (!comment) throw new Error("PREVIEW_COMMENT_CREATE_FAILED");
        comment.Author = author;
        comment.Initial = initial;
        created.push(comment);
        applied += 1;
        if (applied % PREVIEW_BATCH_SIZE === 0) await new Promise((resolve) => setTimeout(resolve, 0));
      }
    } catch (error) {
      for (let index = created.length - 1; index >= 0; index -= 1) {
        try { if (created[index] && typeof created[index].Delete === "function") created[index].Delete(); } catch (_) {}
      }
      throw error;
    }
    storage().setItem(PREVIEW_KEY, JSON.stringify({ session_id: sessionId, author, initial, document_path_hash: await currentDocumentPathHash() }));
    log("INFO", "preview.comments.applied", "预览批注写入完成", { applied_count: applied });
    return applied;
  }

  function taskpaneUrl() { return new URL("taskpane.html", globalObject.location.href).href; }

  function openTaskpane() {
    if (!app || typeof app.CreateTaskPane !== "function") throw new Error("TASKPANE_UNSUPPORTED");
    const current = storage().getItem(TASKPANE_KEY);
    if (current && typeof app.GetTaskPane === "function") {
      try { const pane = app.GetTaskPane(Number(current)); if (pane) { pane.Visible = true; return pane; } }
      catch (_) { storage().setItem(TASKPANE_KEY, ""); }
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
    writeState({ status: "RUNNING", stage: "preview_comments", message: "识别完成，正在写入预览批注…" });
    const applied = await applyPreviewComments(result);
    const rows = (result.items || []).map((item) => ({
      block_index: item.block_index, paragraph_index: item.physical_paragraph_index,
      type_id: item.type_id, role_name: roleNames[item.type_id] || item.type_id,
      confidence: item.confidence, review_level: item.review_level,
      locator_verified: item.locator_verified, segment_index: item.segment_index, segment_count: item.segment_count
    }));
    writeState({
      status: "PASS", stage: "preview_completed",
      message: `预览完成：识别 ${result.block_count} 项；批注 ${applied} 项；建议复核 ${result.review_count}；未定位 ${result.unresolved_count}`,
      recognition: result, recognition_rows: rows, preview_comment_count: applied, error_code: ""
    });
    openTaskpane();
    log("INFO", "preview.completed", "预览排版完成", { blocks: result.block_count, comments: applied, review: result.review_count, unresolved: result.unresolved_count });
  }

  async function clearPreview() {
    const deleted = await clearPreviewComments({ silent: false });
    writeState({
      status: "PASS", stage: "preview_cleared", message: `预览已清除：删除 ${deleted} 条 DocxTool 批注。`,
      recognition: null, recognition_rows: [], preview_comment_count: 0, error_code: ""
    });
  }

  async function runFormat() {
    const document = activeDocument();
    await clearPreviewComments({ silent: true });
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
      committed = false;
      writeState({
        status: "PASS", stage: "completed",
        message: `排版完成：${prepared.paragraph_count} 个段落，${prepared.heading_count} 个标题。`,
        format_result: prepared, error_code: "", operation_id: "", preview_comment_count: 0
      });
      log("INFO", "format.completed", "一键排版完成", { paragraphs: prepared.paragraph_count, headings: prepared.heading_count });
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_FORMAT_FAILED";
      if (operationId) {
        try { await api("/v1/format/rollback", { operation_id: operationId }); committed = false; }
        catch (rollbackError) { log("ERROR", "format.rollback.failed", "一键排版回滚失败", { error_code: rollbackError && rollbackError.message ? rollbackError.message : "UNKNOWN" }); }
      }
      if (app.Documents && typeof app.Documents.Open === "function") {
        try { app.Documents.Open(sourcePath); } catch (_) { /* keep primary error */ }
      }
      if (committed) log("ERROR", "format.recovery.required", "文档替换后恢复状态未确认", { error_code: code });
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
    if (name === "panel") { openTaskpane(); return; }
    busy = true;
    try {
      if (name === "preview") await runPreview();
      else if (name === "apply") await runFormat();
      else if (name === "clear_preview") await clearPreview();
      else if (name === "health") await runHealth();
      else throw new Error("WPS_COMMAND_UNKNOWN");
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_COMMAND_FAILED";
      writeState({ status: "FAIL", stage: "failed", message: `失败：${code}`, error_code: code });
      log("ERROR", "command.failed", "WPS 命令执行失败", { command: name, error_code: code });
      try { openTaskpane(); } catch (_) {}
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
    try { return !busy && savedDocxPath().toLowerCase().endsWith(".docx"); }
    catch (_) { return false; }
  };
})();
