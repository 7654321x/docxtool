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
  let currentRequestId = "";
  let started = false;
  let pollTimer = null;
  const SAFE_DETAIL_FIELDS = new Set([
    "application_available", "applied_count", "applied_total", "batch_index", "binding_status", "block_count",
    "block_index", "blocks", "busy", "command", "compatibility_warnings", "confirmed_count",
    "config_present", "control_port", "control_url_present", "docxtool_version", "duration_ms", "error_code", "error_type", "flushed_count",
    "headings", "host_paragraph_index", "http_status", "interval_ms", "method",
    "operation_id_short", "pane_instance_id_present", "paragraph_count", "paragraphs", "path", "plan_id_short",
    "plugin_storage_available", "poll_interval_ms", "raw_length", "raw_present", "reason", "request_id", "request_key", "response_ok", "review", "review_count",
    "stage", "start_utf16", "end_utf16", "table_paragraph_count", "token_present", "queued_count",
    "total_duration_ms", "unresolved", "unresolved_count", "validated_count", "skipped_count",
    "failed_count", "wait_attempts"
  ]);

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
    catch (error) {
      log("WARNING", "host.state.invalid", "Host 状态读取失败", {
        error_type: error && error.name ? error.name : "Error",
        error_code: "WPS_STATE_JSON_INVALID"
      });
      return {};
    }
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
    Object.keys(details).slice(0, 30).forEach((key) => {
      const value = details[key];
      if (SAFE_DETAIL_FIELDS.has(key) && (["string", "number", "boolean"].includes(typeof value) || value == null)) result[key] = value;
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
    const requestMethod = method || "POST";
    const startedAt = Date.now();
    log("INFO", "api.request.start", "Control API 请求开始", { request_id: currentRequestId, method: requestMethod, path });
    try {
      const response = await fetch(`${config.controlBaseUrl}${path}`, {
        method: requestMethod,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${config.sessionToken}`,
          "X-DocxTool-Request-Id": currentRequestId
        },
        body: requestMethod === "GET" ? undefined : JSON.stringify(body || {})
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error_code || "WPS_CONTROL_REQUEST_FAILED");
      log("INFO", "api.request.completed", "Control API 请求完成", {
        request_id: currentRequestId, method: requestMethod, path, http_status: response.status,
        response_ok: true, duration_ms: Date.now() - startedAt
      });
      return payload.data;
    } catch (error) {
      log("ERROR", "api.request.failed", "Control API 请求失败", {
        request_id: currentRequestId, method: requestMethod, path,
        error_code: error && error.message ? error.message : "WPS_CONTROL_REQUEST_FAILED",
        duration_ms: Date.now() - startedAt
      });
      throw error;
    }
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

  async function validatePreviewRanges(result) {
    const startedAt = Date.now();
    const document = activeDocument();
    const validated = [];
    let skipped = 0;
    let failed = 0;
    log("INFO", "preview.range_validation.start", "开始验证预览范围", {
      request_id: currentRequestId
    });
    try {
      for (const item of result.items || []) {
        if (!item.preview_eligible) {
          skipped += 1;
          continue;
        }
        validated.push({ item, range: await previewRange(document, item) });
      }
    } catch (error) {
      failed += 1;
      log("ERROR", "preview.range_validation.failed", "预览范围验证失败", {
        request_id: currentRequestId, validated_count: validated.length,
        skipped_count: skipped, failed_count: failed,
        duration_ms: Date.now() - startedAt,
        error_type: error && error.name ? error.name : "Error",
        error_code: error && error.message ? error.message : "PREVIEW_RANGE_VALIDATION_FAILED"
      });
      throw error;
    }
    log("INFO", "preview.range_validation.completed", "预览范围验证完成", {
      request_id: currentRequestId, validated_count: validated.length,
      skipped_count: skipped, failed_count: failed,
      duration_ms: Date.now() - startedAt
    });
    return validated;
  }

  async function applyPreviewComments(validatedRanges) {
    const startedAt = Date.now();
    log("INFO", "preview.comments.start", "开始写入预览批注", { request_id: currentRequestId });
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
      for (const entry of validatedRanges) {
        const item = entry.item;
        const range = entry.range;
        const role = roleNames[item.type_id] || item.type_id || "未知";
        const confidence = Math.round(Number(item.confidence || 0) * 100);
        const review = item.review_level === "review" || item.review_level === "critical_review" ? "；建议人工复核" : "";
        const comment = comments.Add(range, `DocxTool 预览：${role}；置信度 ${confidence}%${review}。正式格式由 DocxTool Engine 统一生成。`);
        if (!comment) throw new Error("PREVIEW_COMMENT_CREATE_FAILED");
        comment.Author = author;
        comment.Initial = initial;
        created.push(comment);
        applied += 1;
        if (applied % PREVIEW_BATCH_SIZE === 0) {
          log("INFO", "preview.comments.batch", "预览批注批次已写入", {
            request_id: currentRequestId, batch_index: applied / PREVIEW_BATCH_SIZE, applied_total: applied
          });
          await sleep(0);
        }
      }
    } catch (error) {
      for (let index = created.length - 1; index >= 0; index -= 1) {
        try {
          if (created[index] && typeof created[index].Delete === "function") created[index].Delete();
        } catch (cleanupError) {
          log("WARNING", "preview.comment_cleanup.item.failed", "预览批注清理失败", {
            request_id: currentRequestId, block_index: index,
            error_type: cleanupError && cleanupError.name ? cleanupError.name : "Error",
            error_code: cleanupError && cleanupError.message ? cleanupError.message : "PREVIEW_COMMENT_CLEANUP_FAILED"
          });
        }
      }
      throw error;
    }
    const currentHash = await currentDocumentPathHash();
    storage().setItem(previewStorageKey(currentHash), JSON.stringify({ session_id: sessionId, author, initial }));
    log("INFO", "preview.comments.completed", "预览批注写入完成", {
      request_id: currentRequestId, applied_count: applied, duration_ms: Date.now() - startedAt
    });
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
    const totalStartedAt = Date.now();
    log("INFO", "preview.start", "预览排版开始", { request_id: currentRequestId });
    let stage = "save";
    try {
    const saveStartedAt = Date.now();
    log("INFO", "preview.save.start", "开始保存当前文档", { request_id: currentRequestId });
    const sourcePath = await saveActiveDocument();
    log("INFO", "preview.save.completed", "当前文档保存完成", {
      request_id: currentRequestId, duration_ms: Date.now() - saveStartedAt
    });
    stage = "document_path_wait";
    const pathWaitStartedAt = Date.now();
    log("INFO", "preview.document_path.wait.start", "开始确认当前文档路径", {
      request_id: currentRequestId
    });
    await waitForActiveDocument(sourcePath);
    log("INFO", "preview.document_path.wait.completed", "当前文档路径已确认", {
      request_id: currentRequestId, duration_ms: Date.now() - pathWaitStartedAt
    });
    writeState({ status: "RUNNING", stage: "recognition", message: "正在识别当前文档…", error_code: "" });
    const recognitionStartedAt = Date.now();
    stage = "recognition";
    log("INFO", "preview.recognition.start", "开始请求文档识别", { request_id: currentRequestId });
    const recognition = await api("/v1/recognize", { source_path: sourcePath });
    log("INFO", "preview.recognition.completed", "文档识别完成", {
      request_id: currentRequestId, plan_id_short: String(recognition.plan_id || "").slice(0, 12),
      block_count: recognition.block_count, review_count: recognition.review_count || 0,
      unresolved_count: recognition.unresolved_count || 0, duration_ms: Date.now() - recognitionStartedAt
    });
    writeState({ status: "RUNNING", stage: "host_binding", message: "识别完成，正在验证当前 WPS 文档位置…" });
    stage = "host_snapshot";
    const snapshotStartedAt = Date.now();
    log("INFO", "preview.host_snapshot.start", "开始采集 WPS 文档快照", { request_id: currentRequestId });
    const hostSnapshot = await buildHostSnapshot();
    log("INFO", "preview.host_snapshot.completed", "WPS 文档快照采集完成", {
      request_id: currentRequestId, paragraph_count: hostSnapshot.paragraphs.length,
      table_paragraph_count: hostSnapshot.paragraphs.filter((item) => item.is_in_table).length,
      duration_ms: Date.now() - snapshotStartedAt
    });
    stage = "binding";
    const bindingStartedAt = Date.now();
    log("INFO", "preview.binding.start", "开始验证识别位置", { request_id: currentRequestId });
    const result = await api("/v1/recognize/bind", { plan_id: recognition.plan_id, host_snapshot: hostSnapshot });
    log("INFO", "preview.binding.completed", "识别位置验证完成", {
      request_id: currentRequestId, confirmed_count: result.confirmed_count,
      review_count: result.binding_review_count, unresolved_count: result.unresolved_count,
      duration_ms: Date.now() - bindingStartedAt
    });
    stage = "range_validation";
    const validatedRanges = await validatePreviewRanges(result);
    writeState({ status: "RUNNING", stage: "preview_comments", message: "宿主位置验证完成，正在写入预览批注…" });
    stage = "comments";
    const applied = await applyPreviewComments(validatedRanges);
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
    log("INFO", "preview.completed", "预览排版完成", {
      request_id: currentRequestId, block_count: result.block_count, applied_count: applied,
      review_count: result.binding_review_count, unresolved_count: result.unresolved_count,
      total_duration_ms: Date.now() - totalStartedAt
    });
    } catch (error) {
      if (stage !== "range_validation") {
        const stageEvent = stage === "document_path_wait"
          ? "preview.document_path.wait.failed"
          : `preview.${stage}.failed`;
        log("ERROR", stageEvent, "预览排版阶段失败", {
          request_id: currentRequestId, stage,
          error_type: error && error.name ? error.name : "Error",
          error_code: error && error.message ? error.message : "WPS_PREVIEW_FAILED"
        });
      }
      log("ERROR", "preview.failed", "预览排版失败", {
        request_id: currentRequestId, stage,
        error_type: error && error.name ? error.name : "Error",
        error_code: error && error.message ? error.message : "WPS_PREVIEW_FAILED",
        total_duration_ms: Date.now() - totalStartedAt
      });
      throw error;
    }
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
    const totalStartedAt = Date.now();
    const document = activeDocument();
    log("INFO", "format.start", "一键排版开始", { request_id: currentRequestId });
    let stage = "preview_clear";
    log("INFO", "format.preview_clear.start", "开始清除预览批注", { request_id: currentRequestId });
    try {
      await clearPreviewComments({ silent: true });
    } catch (error) {
      log("ERROR", "format.preview_clear.failed", "预览批注清除失败", {
        request_id: currentRequestId, error_type: error && error.name ? error.name : "Error",
        error_code: error && error.message ? error.message : "WPS_PREVIEW_CLEAR_FAILED"
      });
      log("ERROR", "format.failed", "一键排版失败", { request_id: currentRequestId, stage });
      throw error;
    }
    log("INFO", "format.preview_clear.completed", "预览批注清除完成", { request_id: currentRequestId });
    stage = "save";
    log("INFO", "format.save.start", "开始保存当前文档", { request_id: currentRequestId });
    let sourcePath;
    try {
      sourcePath = await saveActiveDocument();
    } catch (error) {
      log("ERROR", "format.save.failed", "当前文档保存失败", {
        request_id: currentRequestId, error_type: error && error.name ? error.name : "Error",
        error_code: error && error.message ? error.message : "WPS_DOCUMENT_SAVE_FAILED"
      });
      log("ERROR", "format.failed", "一键排版失败", { request_id: currentRequestId, stage });
      throw error;
    }
    log("INFO", "format.save.completed", "当前文档保存完成", { request_id: currentRequestId });
    let operationId = "";
    let committed = false;
    writeState({ status: "RUNNING", stage: "format_prepare", message: "正在调用 DocxTool Engine 排版…", error_code: "" });
    try {
      stage = "transaction_prepare";
      log("INFO", "format.transaction.prepare.start", "开始准备排版事务", { request_id: currentRequestId });
      const prepared = await api("/v1/format/prepare", { source_path: sourcePath });
      operationId = prepared.operation_id;
      log("INFO", "format.prepare.completed", "排版结果准备完成", {
        request_id: currentRequestId, operation_id_short: operationId.slice(0, 12),
        paragraph_count: prepared.paragraph_count, headings: prepared.heading_count,
        compatibility_warnings: warningCount(prepared)
      });
      log("INFO", "format.transaction.prepare.completed", "排版事务准备完成", {
        request_id: currentRequestId, operation_id_short: operationId.slice(0, 12)
      });
      writeState({ status: "RUNNING", stage: "document_close", message: "排版结果已生成，正在安全替换当前文档…", operation_id: operationId });
      stage = "document_close";
      log("INFO", "format.document.close.start", "开始关闭当前文档", { request_id: currentRequestId });
      if (typeof document.Close !== "function") throw new Error("DOCUMENT_CLOSE_UNSUPPORTED");
      document.Close(0);
      log("INFO", "format.document.close.completed", "当前文档已关闭", { request_id: currentRequestId });
      stage = "commit";
      log("INFO", "format.commit.start", "开始提交排版事务", { request_id: currentRequestId });
      await api("/v1/format/commit", { operation_id: operationId });
      committed = true;
      log("INFO", "format.commit.completed", "排版事务提交完成", { request_id: currentRequestId });
      stage = "document_reopen";
      log("INFO", "format.document.reopen.start", "开始重新打开文档", { request_id: currentRequestId });
      if (!app.Documents || typeof app.Documents.Open !== "function") throw new Error("DOCUMENT_OPEN_UNSUPPORTED");
      app.Documents.Open(sourcePath);
      await waitForActiveDocument(sourcePath);
      log("INFO", "format.document.reopen.completed", "文档重新打开完成", { request_id: currentRequestId });
      stage = "finalize";
      log("INFO", "format.finalize.start", "开始完成排版事务", { request_id: currentRequestId });
      await api("/v1/format/finalize", { operation_id: operationId });
      log("INFO", "format.finalize.completed", "排版事务已完成", { request_id: currentRequestId });
      operationId = "";
      committed = false;
      const warnings = warningCount(prepared);
      writeState({
        status: "PASS", stage: "completed",
        message: `排版完成：${prepared.paragraph_count} 个段落，${prepared.heading_count} 个标题${warnings ? `；兼容性提示 ${warnings} 项` : ""}。`,
        format_result: prepared, compatibility_warnings: prepared.compatibility_warnings || [],
        error_code: "", operation_id: "", preview_comment_count: 0
      });
      log("INFO", "format.completed", "一键排版完成", {
        request_id: currentRequestId, paragraphs: prepared.paragraph_count, headings: prepared.heading_count,
        compatibility_warnings: warnings, total_duration_ms: Date.now() - totalStartedAt
      });
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_FORMAT_FAILED";
      log("ERROR", `format.${stage}.failed`, "一键排版阶段失败", {
        request_id: currentRequestId, stage, error_code: code,
        error_type: error && error.name ? error.name : "Error"
      });
      log("ERROR", "format.failed", "一键排版失败", {
        request_id: currentRequestId, stage, error_code: code,
        total_duration_ms: Date.now() - totalStartedAt
      });
      try {
        log("WARNING", "transaction.recovery.start", "开始恢复排版事务", { request_id: currentRequestId });
        await recoverFormat(operationId, sourcePath, committed);
        log("WARNING", "transaction.recovery.completed", "排版事务恢复完成", { request_id: currentRequestId });
      } catch (recoveryError) {
        log("ERROR", "transaction.recovery.failed", "排版事务恢复失败", {
          request_id: currentRequestId, stage: "format_recovery",
          error_type: recoveryError && recoveryError.name ? recoveryError.name : "Error",
          error_code: recoveryError && recoveryError.message ? recoveryError.message : "WPS_FORMAT_RECOVERY_REQUIRED"
        });
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
    const startedAt = Date.now();
    log("INFO", "host.command.start", "WPS 命令开始执行", { request_id: currentRequestId, command: name });
    try {
      if (name === "preview") await runPreview();
      else if (name === "apply") await runFormat();
      else if (name === "clear_preview") await clearPreview();
      else if (name === "health") await runHealth();
      else throw new Error("WPS_COMMAND_UNKNOWN");
      log("INFO", "host.command.completed", "WPS 命令执行完成", {
        request_id: currentRequestId, command: name, duration_ms: Date.now() - startedAt
      });
    } catch (error) {
      const code = error && error.message ? error.message : "WPS_COMMAND_FAILED";
      writeState({ status: "FAIL", stage: "failed", message: `失败：${code}`, error_code: code });
      log("ERROR", "host.command.failed", "WPS 命令执行失败", {
        request_id: currentRequestId, command: name, error_code: code,
        duration_ms: Date.now() - startedAt
      });
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
      log("INFO", "host.storage.request.observed", "Host 已读取到任务窗格请求", {
        raw_present: true, raw_length: String(raw).length, busy
      });
      let request;
      try {
        request = JSON.parse(raw);
      } catch (error) {
        log("ERROR", "host.request.parse.failed", "任务窗格请求解析失败", {
          error_type: error && error.name ? error.name : "Error",
          error_code: "WPS_REQUEST_JSON_INVALID"
        });
        throw error;
      }
      log("INFO", "host.request.parsed", "任务窗格请求解析完成", {
        request_id: request && request.request_id ? request.request_id : "",
        command: request && request.command_name ? request.command_name : "",
        pane_instance_id_present: Boolean(request && request.pane_instance_id)
      });
      if (!request || !request.request_id || !request.command_name) {
        log("WARNING", "host.request.ignored", "任务窗格请求被忽略", {
          request_id: request && request.request_id ? request.request_id : "",
          command: request && request.command_name ? request.command_name : "",
          reason: request && request.request_id ? "invalid_schema" : "missing_request_id"
        });
        log("ERROR", "host.request.invalid", "任务窗格请求无效", {});
        storage().setItem(REQUEST_KEY, "");
        return;
      }
      log("INFO", "host.request.detected", "检测到任务窗格请求", {
        request_id: request.request_id, command: request.command_name
      });
      if (request.request_id === lastRequestId) {
        log("WARNING", "host.request.ignored", "任务窗格请求被忽略", {
          request_id: request.request_id, command: request.command_name,
          reason: "already_processed"
        });
        log("WARNING", "host.request.duplicate", "忽略重复任务窗格请求", {
          request_id: request.request_id, command: request.command_name
        });
        storage().setItem(REQUEST_KEY, "");
        return;
      }
      lastRequestId = request.request_id;
      currentRequestId = request.request_id;
      storage().setItem(REQUEST_KEY, "");
      log("INFO", "host.request.claimed", "任务窗格请求已领取", {
        request_id: request.request_id, command: request.command_name
      });
      void runCommand(request.command_name).finally(() => {
        log("INFO", "host.request.completed", "任务窗格请求处理结束", {
          request_id: request.request_id, command: request.command_name
        });
        currentRequestId = "";
      });
    } catch (error) {
      log("ERROR", "host.request.invalid", "任务窗格请求处理失败", { error_code: error && error.message ? error.message : "UNKNOWN" });
    }
  }

  async function flushEarlyLogs() {
    const queue = Array.isArray(globalObject.DocxToolEarlyLogQueue) ? globalObject.DocxToolEarlyLogQueue : [];
    const queuedCount = queue.length;
    log("INFO", "bootstrap.early_log.flush.start", "开始汇入早期启动日志", { queued_count: queuedCount });
    const entries = queue.splice(0, queue.length);
    try {
      for (const entry of entries) {
        log(entry.level, entry.event, entry.message, entry.details);
      }
      log("INFO", "bootstrap.early_log.flush.completed", "早期启动日志汇入完成", {
        queued_count: queuedCount, flushed_count: entries.length
      });
    } catch (error) {
      log("WARNING", "bootstrap.early_log.flush.failed", "早期启动日志汇入失败", {
        queued_count: queuedCount, flushed_count: 0,
        error_type: error && error.name ? error.name : "Error",
        error_code: error && error.message ? error.message : "WPS_EARLY_LOG_FLUSH_FAILED"
      });
    }
  }

  function validateConfig() {
    if (!config.controlBaseUrl || !config.sessionToken) {
      log("ERROR", "host.config.invalid", "WPS Control 配置无效", {
        token_present: Boolean(config.sessionToken)
      });
      throw new Error("WPS_CONTROL_NOT_CONFIGURED");
    }
    const controlUrl = new URL(config.controlBaseUrl);
    if (controlUrl.hostname !== "127.0.0.1" || !controlUrl.port) throw new Error("WPS_CONTROL_CONFIG_INVALID");
    log("INFO", "host.config.validated", "WPS Control 配置验证完成", {
      control_port: Number(controlUrl.port), token_present: true
    });
  }

  function start() {
    log("INFO", "host.start.enter", "Host Runtime 启动入口已进入", {});
    if (started) return "already_started";
    let stage = "config_validate";
    try {
      log("INFO", "host.config.validate.start", "开始验证 Host Runtime 配置", {});
      validateConfig();
      log("INFO", "host.config.validate.completed", "Host Runtime 配置验证完成", {});
      stage = "storage_initialize";
      log("INFO", "host.storage.initialize.start", "开始验证 PluginStorage", {});
      if (!app || !app.PluginStorage) throw new Error("WPS_PLUGIN_STORAGE_UNAVAILABLE");
      log("INFO", "host.storage.initialize.completed", "PluginStorage 验证完成", {});
      started = true;
      writeState({ status: "READY", stage: "ready", message: "DocxTool WPS 已就绪", recognition_rows: [], compatibility_warnings: [], error_code: "" });
      stage = "poll_start";
      log("INFO", "host.poll.start", "开始创建任务窗格请求轮询", {
        poll_interval_ms: 250, request_key: REQUEST_KEY
      });
      pollTimer = setInterval(pollTaskpaneRequests, 250);
      log("INFO", "host.poll.started", "任务窗格请求轮询已启动", {
        poll_interval_ms: 250, request_key: REQUEST_KEY
      });
      void flushEarlyLogs();
      log("INFO", "host.start.completed", "Host Runtime 启动完成", {});
      return "started";
    } catch (error) {
      log("ERROR", "host.start.failed", "Host Runtime 启动失败", {
        stage, error_type: error && error.name ? error.name : "Error",
        error_code: error && error.message ? error.message : "WPS_HOST_START_FAILED"
      });
      throw error;
    }
  }

  function handleRibbonAction(id) {
    log("INFO", "ribbon.action.received", "收到 Ribbon 操作", { command: id, busy });
    currentRequestId = `ribbon-${randomId()}`;
    log("INFO", "ribbon.action.started", "Ribbon 操作开始", { request_id: currentRequestId, command: id });
    void runCommand(id).then(() => {
      log("INFO", "ribbon.action.completed", "Ribbon 操作完成", { request_id: currentRequestId, command: id });
      currentRequestId = "";
    }).catch((error) => {
      log("ERROR", "ribbon.action.failed", "Ribbon 操作失败", {
        request_id: currentRequestId, command: id,
        error_code: error && error.message ? error.message : "WPS_COMMAND_FAILED"
      });
      currentRequestId = "";
    });
  }

  function getActionEnabled(id) {
    if (id === "panel" || id === "health") return !busy;
    try { return !busy && savedDocxPath().toLowerCase().endsWith(".docx"); }
    catch (_) { return false; }
  }

  if (!globalObject.DocxToolEarlyLog) throw new Error("WPS_BOOTSTRAP_LOG_UNAVAILABLE");
  globalObject.DocxToolEarlyLog("INFO", "bootstrap", "runtime.config.detected", "WPS 运行配置已读取", {
    config_present: Boolean(globalObject.DocxToolWpsConfig),
    control_url_present: Boolean(config.controlBaseUrl),
    token_present: Boolean(config.sessionToken)
  });
  globalObject.DocxToolEarlyLog("INFO", "host", "host.runtime.loaded", "Host Runtime 脚本已加载", {
    application_available: Boolean(app), plugin_storage_available: Boolean(app && app.PluginStorage),
    config_present: Boolean(globalObject.DocxToolWpsConfig)
  });
  globalObject.DocxToolHostRuntime = Object.freeze({ start, runCommand, getBusy: () => busy, handleRibbonAction, getActionEnabled });
})();
