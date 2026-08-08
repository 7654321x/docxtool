(function () {
  "use strict";

  const globalObject = window;
  const app = globalObject.Application;
  const config = globalObject.DocxToolWpsConfig || {};
  const STATE_KEY = "docxtool_wps_state_v1";
  const REQUEST_KEY = "docxtool_wps_request_v1";
  const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
  const PREVIEW_KEY_PREFIX = "docxtool_wps_preview_v2:";
  const PREVIEW_BATCH_SIZE = 5;
  const SAVE_WAIT_ATTEMPTS = 30;
  const REOPEN_WAIT_ATTEMPTS = 30;
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

  function sleep(milliseconds) {
    return new Promise((resolve) => setTimeout(resolve, milliseconds));
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

  function normalizePath(value) {
    return String(value || "").replace(/\//g, "\\").toLowerCase();
  }

  function savedDocxPath() {
    const path = String(activeDocument().FullName || "");
    if (!path || !path.toLowerCase().endsWith(".docx")) throw new Error("DOCUMENT_MUST_BE_SAVED_AS_DOCX");
    return path;
  }

  async function saveActiveDocument() {
    const document = activeDocument();
    if (typeof document.Save !== "function") throw new Error("DOCUMENT_SAVE_UNSUPPORTED");
    document.Save();
    for (let attempt = 0; attempt < SAVE_WAIT_ATTEMPTS; attempt += 1) {
      if (document.Saved === true) return savedDocxPath();
      await sleep(100);
    }
    throw new Error("DOCUMENT_SAVE_TIMEOUT");
  }

  async function waitForActiveDocument(expectedPath) {
    const expected = normalizePath(expectedPath);
    for (let attempt = 0; attempt < REOPEN_WAIT_ATTEMPTS; attempt += 1) {
      const current = app && app.ActiveDocument ? normalizePath(app.ActiveDocument.FullName) : "";
      if (current === expected) return;
      await sleep(100);
    }
    throw new Error("DOCUMENT_REOPEN_TIMEOUT");
  }

  function sourceIsActive(sourcePath) {
    return Boolean(app && app.ActiveDocument && normalizePath(app.ActiveDocument.FullName) === normalizePath(sourcePath));
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

  async function currentDocumentPathHash() {
    return sha256(normalizePath(savedDocxPath()));
  }

  function previewStorageKey(documentPathHash) {
    return `${PREVIEW_KEY_PREFIX}${documentPathHash}`;
  }

  async function buildHostSnapshot() {
    const document = activeDocument();
    const paragraphsCollection = document.Paragraphs;
    if (!paragraphsCollection || typeof paragraphsCollection.Item !== "function") throw new Error("HOST_PARAGRAPHS_UNSUPPORTED");
    const count = Number(paragraphsCollection.Count || 0);
    const documentHasTables = Boolean(document.Tables && Number(document.Tables.Count || 0) > 0);
    const paragraphs = [];
    for (let index = 0; index < count; index += 1) {
      const paragraph = paragraphsCollection.Item(index + 1);
      const range = paragraph && paragraph.Range;
      if (!range) throw new Error("HOST_PARAGRAPH_RANGE_UNAVAILABLE");
      let isInTable = false;
      if (range.Tables && typeof range.Tables.Count !== "undefined") {
        isInTable = Number(range.Tables.Count || 0) > 0;
      } else if (documentHasTables) {
        throw new Error("HOST_TABLE_MEMBERSHIP_UNSUPPORTED");
      }
      paragraphs.push({
        host_paragraph_id: `main:${String(index).padStart(6, "0")}`,
        host_paragraph_index: index,
        story_id: "main",
        story_type: "main",
        story_paragraph_index: index,
        section_index: null,
        is_in_table: isInTable,
        raw_text: stripWpsTerminator(range.Text)
      });
    }
    const documentIdentity = await currentDocumentPathHash();
    const revision = await sha256(paragraphs.map((item) => item.raw_text).join("\u241e"));
    return {
      schema_version: "host-snapshot-v1",
      integration_contract_version: "integration-contract-v1",
      snapshot_id: `wps-${randomId()}`,
      document_identity: documentIdentity,
      document_revision: revision,
      host: { kind: "wps", platform: "windows" },
      host_type: "wps",
      text_contract_version: "host-text-v1",
      offset_encoding: "utf16_code_unit",
      paragraphs
    };
  }

  async function previewRange(document, item) {
    if (!item.preview_eligible || item.binding_status !== "confirmed") throw new Error("PREVIEW_BINDING_UNCONFIRMED");
    if (!Number.isInteger(item.host_paragraph_index)) throw new Error("PREVIEW_HOST_PARAGRAPH_UNRESOLVED");
    if (!Number.isInteger(item.host_raw_start_utf16) || !Number.isInteger(item.host_raw_end_utf16) || item.host_raw_end_utf16 <= item.host_raw_start_utf16) throw new Error("PREVIEW_RANGE_INVALID");
    const paragraph = document.Paragraphs && document.Paragraphs.Item ? document.Paragraphs.Item(item.host_paragraph_index + 1) : null;
    const paragraphRange = paragraph && paragraph.Range;
    if (!paragraphRange) throw new Error("PREVIEW_PARAGRAPH_NOT_FOUND");
    const raw = stripWpsTerminator(paragraphRange.Text);
    if (!item.host_paragraph_raw_sha256 || await sha256(raw) !== item.host_paragraph_raw_sha256) throw new Error("PREVIEW_PARAGRAPH_CHANGED");
    if (item.host_raw_end_utf16 > raw.length) throw new Error("PREVIEW_RANGE_INVALID");
    const fragment = raw.slice(item.host_raw_start_utf16, item.host_raw_end_utf16);
    if (!item.raw_fragment_sha256 || await sha256(fragment) !== item.raw_fragment_sha256) throw new Error("PREVIEW_RANGE_HASH_MISMATCH");
    const characters = paragraphRange.Characters;
    if (!characters || typeof characters.Item !== "function") throw new Error("PREVIEW_CHARACTERS_UNSUPPORTED");
    const firstOrdinal = characterOrdinalAtUtf16Offset(raw, item.host_raw_start_utf16);
    const endOrdinal = characterOrdinalAtUtf16Offset(raw, item.host_raw_end_utf16);
    const first = characters.Item(firstOrdinal + 1);
    const last = characters.Item(endOrdinal);
    if (!first || !last || typeof first.SetRange !== "function") throw new Error("PREVIEW_RANGE_BOUNDARY_INVALID");
    first.SetRange(Number(first.Start), Number(last.End));
    if (await sha256(stripWpsTerminator(first.Text)) !== item.raw_fragment_sha256) throw new Error("PREVIEW_RANGE_READBACK_MISMATCH");
    return first;
  }

  async function clearPreviewComments(options) {
    const silent = Boolean(options && options.silent);
    const currentHash = await currentDocumentPathHash();
    const key = previewStorageKey(currentHash);
    const raw = storage().getItem(key);
    if (!raw) return 0;
    let session;
    try { session = JSON.parse(raw); }
    catch (_) { storage().setItem(key, ""); return 0; }
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
    storage().setItem(key, "");
    if (!silent || deleted) log("INFO", "preview.comments.cleared", "预览批注已清除", { deleted_count: deleted });
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
        if (!item.preview_eligible) continue;
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
        if (applied % PREVIEW_BATCH_SIZE === 0) await sleep(0);
      }
    } catch (error) {
      for (let index = created.length - 1; index >= 0; index -= 1) {
        try { if (created[index] && typeof created[index].Delete === "function") created[index].Delete(); } catch (_) {}
      }
      throw error;
    }
    const currentHash = await currentDocumentPathHash();
    storage().setItem(previewStorageKey(currentHash), JSON.stringify({ session_id: sessionId, author, initial }));
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
    const sourcePath = await saveActiveDocument();
    writeState({ status: "RUNNING", stage: "recognition", message: "正在识别当前文档…", error_code: "" });
    const recognition = await api("/v1/recognize", { source_path: sourcePath });
    writeState({ status: "RUNNING", stage: "host_binding", message: "识别完成，正在验证当前 WPS 文档位置…" });
    const hostSnapshot = await buildHostSnapshot();
    const result = await api("/v1/recognize/bind", { plan_id: recognition.plan_id, host_snapshot: hostSnapshot });
    writeState({ status: "RUNNING", stage: "preview_comments", message: "宿主位置验证完成，正在写入预览批注…" });
    const applied = await applyPreviewComments(result);
    const rows = (result.items || []).map((item) => ({
      block_index: item.block_index, paragraph_index: item.host_paragraph_index,
      type_id: item.type_id, role_name: roleNames[item.type_id] || item.type_id,
      confidence: item.confidence, review_level: item.review_level,
      locator_verified: item.preview_eligible, binding_status: item.binding_status,
      segment_index: item.segment_index, segment_count: item.segment_count
    }));
    writeState({
      status: "PASS", stage: "preview_completed",
      message: `预览完成：识别 ${result.block_count} 项；安全批注 ${applied} 项；绑定复核 ${result.binding_review_count}；未定位 ${result.unresolved_count}`,
      recognition: result, recognition_rows: rows, preview_comment_count: applied, error_code: ""
    });
    openTaskpane();
    log("INFO", "preview.completed", "预览排版完成", { blocks: result.block_count, comments: applied, review: result.binding_review_count, unresolved: result.unresolved_count });
  }

  async function clearPreview() {
    const deleted = await clearPreviewComments({ silent: false });
    writeState({
      status: "PASS", stage: "preview_cleared", message: `预览已清除：删除 ${deleted} 条 DocxTool 批注。`,
      recognition: null, recognition_rows: [], preview_comment_count: 0, error_code: ""
    });
  }

  async function recoverFormat(operationId, sourcePath, committed) {
    if (!operationId) return;
    if (committed && sourceIsActive(sourcePath)) {
      const current = activeDocument();
      if (typeof current.Close !== "function") throw new Error("WPS_FORMAT_RECOVERY_REQUIRED");
      current.Close(0);
    }
    try {
      await api("/v1/format/rollback", { operation_id: operationId });
    } catch (error) {
      log("ERROR", "format.rollback.failed", "一键排版回滚失败", { error_code: error && error.message ? error.message : "UNKNOWN" });
      throw new Error("WPS_FORMAT_RECOVERY_REQUIRED");
    }
    if (!sourceIsActive(sourcePath)) {
      if (!app.Documents || typeof app.Documents.Open !== "function") throw new Error("WPS_FORMAT_RECOVERY_REQUIRED");
      app.Documents.Open(sourcePath);
      await waitForActiveDocument(sourcePath);
    }
    log("WARNING", "format.rollback.completed", "一键排版失败后已恢复原文档");
  }

  function warningCount(prepared) {
    return Array.isArray(prepared.compatibility_warnings) ? prepared.compatibility_warnings.length : 0;
  }

  async function runFormat() {
    const document = activeDocument();
    await clearPreviewComments({ silent: true });
    const sourcePath = await saveActiveDocument();
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
      await waitForActiveDocument(sourcePath);
      await api("/v1/format/finalize", { operation_id: operationId });
      operationId = "";
      committed = false;
      const warnings = warningCount(prepared);
      writeState({
        status: "PASS", stage: "completed",
        message: `排版完成：${prepared.paragraph_count} 个段落，${prepared.heading_count} 个标题${warnings ? `；兼容性提示 ${warnings} 项` : ""}。`,
        format_result: prepared, compatibility_warnings: prepared.compatibility_warnings || [],
        error_code: "", operation_id: "", preview_comment_count: 0
      });
      log("INFO", "format.completed", "一键排版完成", { paragraphs: prepared.paragraph_count, headings: prepared.heading_count, compatibility_warnings: warnings });
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_FORMAT_FAILED";
      try {
        await recoverFormat(operationId, sourcePath, committed);
      } catch (recoveryError) {
        log("ERROR", "format.recovery.required", "一键排版失败且自动恢复未完成", { error_code: recoveryError && recoveryError.message ? recoveryError.message : "WPS_FORMAT_RECOVERY_REQUIRED", primary_error_code: code });
        throw recoveryError;
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
    writeState({ status: "READY", stage: "ready", message: "DocxTool WPS 已就绪", recognition_rows: [], compatibility_warnings: [], error_code: "" });
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
