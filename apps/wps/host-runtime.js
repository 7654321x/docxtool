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
  const DOCX_SAVE_FORMAT = 12;
  let busy = false;
  let lastRequestId = "";
  let started = false;
  let pollTimer = null;
  let pollFirstTickLogged = false;
  let logSequence = 0;
  let logTransportFailureReported = false;
  let logTransportUnavailableReported = false;
  const SAFE_DETAIL_FIELDS = new Set([
    "application_available", "applied_count", "applied_total", "batch_index", "binding_status", "block_count", "bootstrap_id",
    "block_index", "blocks", "busy", "command", "compatibility_warnings", "confirmed_count",
    "config_present", "control_port", "control_url_present", "docxtool_version", "duration_ms", "error_code", "error_type", "flushed_count",
    "headings", "host_instance_id_short", "host_paragraph_index", "http_status", "interval_ms", "method",
    "operation_id_short", "pane_instance_id_present", "paragraph_count", "paragraphs", "path", "plan_id_short",
    "plugin_storage_available", "poll_interval_ms", "raw_length", "raw_present", "reason", "request_id", "request_key", "response_ok", "review", "review_count",
    "stage", "start_utf16", "end_utf16", "table_paragraph_count", "token_present", "queued_count",
    "total_duration_ms", "type_id", "unresolved", "unresolved_count", "validated_count", "skipped_count",
    "failed_count", "wait_attempts", "request_status",
    "deleted_count", "document_id_short", "document_name", "event_sequence", "log_file", "pending_present", "slot_occupied",
    "callbacks_registered", "state", "host_ready", "cleared_count", "cause_event",
    "primary_error_code", "previous_status", "current_status", "preview_confirmed_count",
    "preview_eligible_count", "preview_review_count", "warning_code",
    "conversion_state", "inline_shape_count", "mismatch_count", "section_count",
    "shape_count", "source_format", "target_format", "target_state"
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
    let value;
    try {
      value = storage().getItem(STATE_KEY);
    } catch (error) {
      log("ERROR", "host.state.read_failed", "Host 状态读取失败", {
        error_type: error && error.name ? error.name : "Error",
        error_code: "WPS_STATE_READ_FAILED"
      });
      throw new Error("WPS_STATE_READ_FAILED");
    }
    if (!value) return {};
    try {
      return JSON.parse(value);
    } catch (error) {
      log("ERROR", "host.state.parse_failed", "Host 状态 JSON 无效", {
        error_type: error && error.name ? error.name : "Error",
        error_code: "WPS_STATE_JSON_INVALID"
      });
      throw new Error("WPS_STATE_JSON_INVALID");
    }
  }

  function writeState(patch) {
    const state = Object.assign({}, readState(), patch, { updated_at: new Date().toISOString() });
    let serialized;
    try {
      serialized = JSON.stringify(state);
    } catch (error) {
      log("ERROR", "host.state.serialize_failed", "Host 状态序列化失败", {
        error_type: error && error.name ? error.name : "Error",
        error_code: "WPS_STATE_SERIALIZE_FAILED"
      });
      throw new Error("WPS_STATE_SERIALIZE_FAILED");
    }
    try {
      storage().setItem(STATE_KEY, serialized);
    } catch (error) {
      log("ERROR", "host.state.write_failed", "Host 状态写入失败", {
        error_type: error && error.name ? error.name : "Error",
        error_code: "WPS_STATE_WRITE_FAILED"
      });
      throw new Error("WPS_STATE_WRITE_FAILED");
    }
    return state;
  }

  function randomId() {
    if (globalObject.crypto && typeof globalObject.crypto.randomUUID === "function") return globalObject.crypto.randomUUID();
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }

  const bootstrapId = String(globalObject.DocxToolBootstrapId || "");
  const hostInstanceIdShort = `host-${randomId().replace(/-/g, "").slice(0, 12)}`;

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

  function stableErrorCode(error, fallback) {
    const value = error && error.message ? String(error.message) : "";
    return /^[A-Z][A-Z0-9_]{2,100}$/.test(value) ? value : fallback;
  }

  function commandFailureMessage(errorCode) {
    if (errorCode === "WPS_DOCUMENT_NOT_DOCX") {
      return "当前文档未完成 DOCX 升级，请查看文档升级日志。";
    }
    if (errorCode === "WPS_LEGACY_UPGRADE_TARGET_EXISTS") {
      return "同目录已存在同名 DOCX，未覆盖任何文件。";
    }
    return `失败：${errorCode}`;
  }

  function log(level, event, message, details) {
    const safe = safeDetails(details);
    if (bootstrapId) safe.bootstrap_id = bootstrapId;
    safe.host_instance_id_short = hostInstanceIdShort;
    safe.event_sequence = ++logSequence;
    const line = `[WPS][host] ${event} | ${message}`;
    if (level === "ERROR") console.error(line, safe);
    else if (level === "WARN" || level === "WARNING") console.warn(line, safe);
    else console.log(line, safe);
    if (!config.controlBaseUrl || !config.sessionToken || typeof fetch !== "function") {
      if (!logTransportUnavailableReported) {
        logTransportUnavailableReported = true;
        console.error("[WPS][host] log.transport.unavailable | Host 日志传输配置不可用", {
          control_url_present: Boolean(config.controlBaseUrl),
          token_present: Boolean(config.sessionToken),
          error_code: "WPS_LOG_TRANSPORT_UNAVAILABLE"
        });
      }
      return;
    }
    const headers = { "Content-Type": "application/json", "Authorization": `Bearer ${config.sessionToken}` };
    if (safe.request_id) headers["X-DocxTool-Request-Id"] = safe.request_id;
    void fetch(`${config.controlBaseUrl}/v1/log`, {
      method: "POST",
      headers,
      body: JSON.stringify({ level, component: "host", event, message, details: safe })
    }).then((response) => {
      if (!response.ok) throw new Error("WPS_LOG_HTTP_FAILED");
      logTransportFailureReported = false;
    }).catch((error) => {
      if (logTransportFailureReported) return;
      logTransportFailureReported = true;
      console.error("[WPS][host] log.transport.failed | Host 日志传输失败", {
        error_code: stableErrorCode(error, "WPS_LOG_TRANSPORT_FAILED")
      });
    });
  }

  function requestId(requestContext) {
    return requestContext && requestContext.request_id ? requestContext.request_id : "";
  }

  function contextDetails(requestContext) {
    const documentName = requestContext && requestContext.document_name
      ? String(requestContext.document_name)
      : activeDocumentName();
    const details = { request_id: requestId(requestContext) };
    if (documentName) details.document_name = documentName;
    return details;
  }

  function stopPollingForStorageFailure(errorCode) {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
    started = false;
    log("ERROR", "host.poll.stopped.storage_failure", "PluginStorage 故障导致 Host 轮询停止", {
      error_code: errorCode, host_ready: false
    });
  }

  function clearRequestSlot(requestContext, reason) {
    const details = Object.assign(contextDetails(requestContext), { reason });
    log("DEBUG", "host.request_slot.clear.start", "开始清空任务窗格请求槽", details);
    try {
      storage().setItem(REQUEST_KEY, "");
    } catch (error) {
      log("ERROR", "host.request_slot.clear.failed", "任务窗格请求槽清空失败", {
        ...details, error_code: "WPS_REQUEST_SLOT_CLEAR_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      stopPollingForStorageFailure("WPS_REQUEST_SLOT_CLEAR_FAILED");
      throw new Error("WPS_REQUEST_SLOT_CLEAR_FAILED");
    }
    log("DEBUG", "host.request_slot.clear.completed", "任务窗格请求槽已清空", details);
  }

  async function api(path, body, method, requestContext) {
    if (!config.controlBaseUrl || !config.sessionToken) throw new Error("WPS_CONTROL_NOT_CONFIGURED");
    const requestMethod = method || "POST";
    const startedAt = Date.now();
    log("INFO", "api.request.start", "Control API 请求开始", Object.assign(contextDetails(requestContext), { method: requestMethod, path }));
    try {
      const response = await fetch(`${config.controlBaseUrl}${path}`, {
        method: requestMethod,
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${config.sessionToken}`,
          "X-DocxTool-Request-Id": requestId(requestContext)
        },
        body: requestMethod === "GET" ? undefined : JSON.stringify(body || {})
      });
      const payload = await response.json();
      if (!response.ok || !payload.ok) throw new Error(payload.error_code || "WPS_CONTROL_REQUEST_FAILED");
      log("INFO", "api.request.completed", "Control API 请求完成", {
        ...contextDetails(requestContext), method: requestMethod, path, http_status: response.status,
        response_ok: true, duration_ms: Date.now() - startedAt
      });
      return payload.data;
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_CONTROL_REQUEST_FAILED");
      log("ERROR", "api.request.failed", "Control API 请求失败", {
        ...contextDetails(requestContext), method: requestMethod, path,
        error_code: errorCode,
        error_type: error && error.name ? error.name : "Error",
        duration_ms: Date.now() - startedAt
      });
      throw new Error(errorCode);
    }
  }

  function activeDocument() {
    const document = app && app.ActiveDocument;
    if (!document) throw new Error("WPS_ACTIVE_DOCUMENT_MISSING");
    return document;
  }

  function activeDocumentName() {
    const document = app && app.ActiveDocument;
    return document && document.Name ? String(document.Name).replace(/[\r\n]/g, " ").slice(0, 120) : "";
  }

  function normalizePath(value) {
    return String(value || "").replace(/\//g, "\\").toLowerCase();
  }

  function savedDocumentPath() {
    const path = String(activeDocument().FullName || "");
    if (!path) throw new Error("WPS_DOCUMENT_PATH_MISSING");
    return path;
  }

  function savedDocxPath() {
    const path = savedDocumentPath();
    if (!path.toLowerCase().endsWith(".docx")) throw new Error("WPS_DOCUMENT_NOT_DOCX");
    return path;
  }

  async function saveActiveDocument(requestContext, purpose, requireDocx = true) {
    const document = activeDocument();
    if (typeof document.Save !== "function") {
      log("ERROR", "document.save.unsupported", "当前 WPS 文档不支持保存", {
        ...contextDetails(requestContext), stage: purpose,
        error_code: "WPS_DOCUMENT_SAVE_UNSUPPORTED"
      });
      throw new Error("WPS_DOCUMENT_SAVE_UNSUPPORTED");
    }
    log("INFO", "document.save.invoke.start", "开始调用 WPS Document.Save", {
      ...contextDetails(requestContext), stage: purpose
    });
    try {
      document.Save();
    } catch (error) {
      log("ERROR", "document.save.invoke.failed", "WPS Document.Save 调用失败", {
        ...contextDetails(requestContext), stage: purpose,
        error_code: "WPS_DOCUMENT_SAVE_CALL_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_DOCUMENT_SAVE_CALL_FAILED");
    }
    log("INFO", "document.save.invoke.completed", "WPS Document.Save 调用已返回", {
      ...contextDetails(requestContext), stage: purpose
    });
    log("INFO", "document.save.wait.start", "开始等待 WPS 确认文档已保存", {
      ...contextDetails(requestContext), stage: purpose
    });
    for (let attempt = 0; attempt < SAVE_WAIT_ATTEMPTS; attempt += 1) {
      if (document.Saved === true) {
        let path;
        try {
          path = requireDocx ? savedDocxPath() : savedDocumentPath();
        } catch (error) {
          const code = stableErrorCode(error, "WPS_DOCUMENT_PATH_INVALID");
          log("ERROR", "document.path.invalid", "已保存文档的路径无效", {
            ...contextDetails(requestContext), stage: purpose, error_code: code
          });
          throw new Error(code);
        }
        log("INFO", "document.save.wait.completed", "WPS 已确认文档保存完成", {
          ...contextDetails(requestContext), stage: purpose, wait_attempts: attempt + 1
        });
        return path;
      }
      await sleep(100);
    }
    log("ERROR", "document.save.wait.timeout", "等待 WPS 保存确认超时", {
      ...contextDetails(requestContext), stage: purpose,
      wait_attempts: SAVE_WAIT_ATTEMPTS, error_code: "WPS_DOCUMENT_SAVE_TIMEOUT"
    });
    throw new Error("WPS_DOCUMENT_SAVE_TIMEOUT");
  }

  async function waitForActiveDocument(expectedPath, requestContext, purpose) {
    const expected = normalizePath(expectedPath);
    log("INFO", "document.path.wait.start", "开始等待 WPS 激活目标文档", {
      ...contextDetails(requestContext), stage: purpose
    });
    for (let attempt = 0; attempt < REOPEN_WAIT_ATTEMPTS; attempt += 1) {
      const current = app && app.ActiveDocument ? normalizePath(app.ActiveDocument.FullName) : "";
      if (current === expected) {
        log("INFO", "document.path.wait.completed", "WPS 已激活目标文档", {
          ...contextDetails(requestContext), stage: purpose, wait_attempts: attempt + 1
        });
        return;
      }
      await sleep(100);
    }
    log("ERROR", "document.path.wait.timeout", "等待 WPS 激活目标文档超时", {
      ...contextDetails(requestContext), stage: purpose,
      wait_attempts: REOPEN_WAIT_ATTEMPTS, error_code: "WPS_DOCUMENT_REOPEN_TIMEOUT"
    });
    throw new Error("WPS_DOCUMENT_REOPEN_TIMEOUT");
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

  async function currentDocumentPathHash(requireDocx = true) {
    const path = requireDocx ? savedDocxPath() : savedDocumentPath();
    return sha256(normalizePath(path));
  }

  function previewStorageKey(documentPathHash) {
    return `${PREVIEW_KEY_PREFIX}${documentPathHash}`;
  }

  async function buildHostSnapshot(requestContext, requireDocx = true) {
    const document = activeDocument();
    const paragraphsCollection = document.Paragraphs;
    if (!paragraphsCollection || typeof paragraphsCollection.Item !== "function") {
      log("ERROR", "host_snapshot.paragraphs.unsupported", "WPS 段落集合不可用", {
        ...contextDetails(requestContext), error_code: "WPS_HOST_PARAGRAPHS_UNSUPPORTED"
      });
      throw new Error("WPS_HOST_PARAGRAPHS_UNSUPPORTED");
    }
    const count = Number(paragraphsCollection.Count || 0);
    const documentHasTables = Boolean(document.Tables && Number(document.Tables.Count || 0) > 0);
    const paragraphs = [];
    for (let index = 0; index < count; index += 1) {
      let paragraph;
      try {
        paragraph = paragraphsCollection.Item(index + 1);
      } catch (error) {
        log("ERROR", "host_snapshot.paragraph.read_failed", "WPS 段落读取失败", {
          ...contextDetails(requestContext), host_paragraph_index: index,
          error_code: "WPS_HOST_PARAGRAPH_READ_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_HOST_PARAGRAPH_READ_FAILED");
      }
      const range = paragraph && paragraph.Range;
      if (!range) {
        log("ERROR", "host_snapshot.paragraph.range_missing", "WPS 段落 Range 不可用", {
          ...contextDetails(requestContext), host_paragraph_index: index,
          error_code: "WPS_HOST_PARAGRAPH_RANGE_UNAVAILABLE"
        });
        throw new Error("WPS_HOST_PARAGRAPH_RANGE_UNAVAILABLE");
      }
      let isInTable = false;
      try {
        if (range.Tables && typeof range.Tables.Count !== "undefined") {
          isInTable = Number(range.Tables.Count || 0) > 0;
        } else if (documentHasTables) {
          log("ERROR", "host_snapshot.table_membership.unsupported", "WPS 段落表格归属不可用", {
            ...contextDetails(requestContext), host_paragraph_index: index,
            error_code: "WPS_HOST_TABLE_MEMBERSHIP_UNSUPPORTED"
          });
          throw new Error("WPS_HOST_TABLE_MEMBERSHIP_UNSUPPORTED");
        }
      } catch (error) {
        if (stableErrorCode(error, "") === "WPS_HOST_TABLE_MEMBERSHIP_UNSUPPORTED") throw error;
        log("ERROR", "host_snapshot.table_membership.read_failed", "WPS 段落表格归属读取失败", {
          ...contextDetails(requestContext), host_paragraph_index: index,
          error_code: "WPS_HOST_TABLE_MEMBERSHIP_READ_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_HOST_TABLE_MEMBERSHIP_READ_FAILED");
      }
      let rawText;
      try {
        rawText = stripWpsTerminator(range.Text);
      } catch (error) {
        log("ERROR", "host_snapshot.paragraph.text_failed", "WPS 段落文字读取失败", {
          ...contextDetails(requestContext), host_paragraph_index: index,
          error_code: "WPS_HOST_PARAGRAPH_TEXT_READ_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_HOST_PARAGRAPH_TEXT_READ_FAILED");
      }
      paragraphs.push({
        host_paragraph_id: `main:${String(index).padStart(6, "0")}`,
        host_paragraph_index: index,
        story_id: "main",
        story_type: "main",
        story_paragraph_index: index,
        section_index: null,
        is_in_table: isInTable,
        raw_text: rawText
      });
    }
    let documentIdentity;
    try {
      documentIdentity = await currentDocumentPathHash(requireDocx);
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_HOST_IDENTITY_FAILED");
      log("ERROR", "host_snapshot.identity.failed", "WPS 文档 identity 生成失败", {
        ...contextDetails(requestContext), error_code: errorCode,
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error(errorCode);
    }
    let revision;
    try {
      revision = await sha256(paragraphs.map((item) => item.raw_text).join("\u241e"));
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_HOST_REVISION_FAILED");
      log("ERROR", "host_snapshot.revision.failed", "WPS 文档 revision 生成失败", {
        ...contextDetails(requestContext), error_code: errorCode,
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error(errorCode);
    }
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

  function collectionCount(collection) {
    return collection && typeof collection.Count !== "undefined"
      ? Number(collection.Count || 0)
      : 0;
  }

  async function legacyConversionSnapshot(requestContext) {
    const document = activeDocument();
    const snapshot = await buildHostSnapshot(requestContext, false);
    return {
      revision: snapshot.document_revision,
      paragraph_count: snapshot.paragraphs.length,
      table_count: collectionCount(document.Tables),
      inline_shape_count: collectionCount(document.InlineShapes),
      shape_count: collectionCount(document.Shapes),
      section_count: collectionCount(document.Sections)
    };
  }

  function verifyLegacyConversion(before, after, requestContext) {
    const keys = [
      "revision", "paragraph_count", "table_count", "inline_shape_count",
      "shape_count", "section_count"
    ];
    const mismatches = keys.filter((key) => before[key] !== after[key]);
    if (mismatches.length) {
      log("ERROR", "document.upgrade.verify.failed", "旧格式转换后的文档内容不守恒", {
        ...contextDetails(requestContext), mismatch_count: mismatches.length,
        error_code: "WPS_LEGACY_CONVERSION_CONTENT_MISMATCH"
      });
      throw new Error("WPS_LEGACY_CONVERSION_CONTENT_MISMATCH");
    }
    log("INFO", "document.upgrade.verify.completed", "旧格式转换后的文档内容校验通过", {
      ...contextDetails(requestContext), paragraph_count: after.paragraph_count,
      table_count: after.table_count, inline_shape_count: after.inline_shape_count,
      shape_count: after.shape_count, section_count: after.section_count
    });
  }

  async function previewRange(document, item) {
    const actionMatchesStatus = (
      item.binding_status === "confirmed" && item.recommended_action === "verify_host_range"
    ) || (
      item.binding_status === "review" && item.recommended_action === "preview_only"
    );
    if (!item.preview_eligible || !actionMatchesStatus) throw new Error("PREVIEW_BINDING_UNCONFIRMED");
    if (!Number.isInteger(item.host_paragraph_index)) throw new Error("PREVIEW_HOST_PARAGRAPH_UNRESOLVED");
    if (!Number.isInteger(item.host_raw_start_utf16) || !Number.isInteger(item.host_raw_end_utf16) || item.host_raw_end_utf16 <= item.host_raw_start_utf16) throw new Error("PREVIEW_RANGE_INVALID");
    let paragraph;
    try {
      paragraph = document.Paragraphs && document.Paragraphs.Item ? document.Paragraphs.Item(item.host_paragraph_index + 1) : null;
    } catch (_) {
      throw new Error("PREVIEW_PARAGRAPH_LOOKUP_FAILED");
    }
    const paragraphRange = paragraph && paragraph.Range;
    if (!paragraphRange) throw new Error("PREVIEW_PARAGRAPH_NOT_FOUND");
    let raw;
    try {
      raw = stripWpsTerminator(paragraphRange.Text);
    } catch (_) {
      throw new Error("PREVIEW_PARAGRAPH_TEXT_READ_FAILED");
    }
    if (!item.host_paragraph_raw_sha256 || await sha256(raw) !== item.host_paragraph_raw_sha256) throw new Error("PREVIEW_PARAGRAPH_CHANGED");
    if (item.host_raw_end_utf16 > raw.length) throw new Error("PREVIEW_RANGE_INVALID");
    const fragment = raw.slice(item.host_raw_start_utf16, item.host_raw_end_utf16);
    if (!item.raw_fragment_sha256 || await sha256(fragment) !== item.raw_fragment_sha256) throw new Error("PREVIEW_RANGE_HASH_MISMATCH");
    const characters = paragraphRange.Characters;
    if (!characters || typeof characters.Item !== "function") throw new Error("PREVIEW_CHARACTERS_UNSUPPORTED");
    const firstOrdinal = characterOrdinalAtUtf16Offset(raw, item.host_raw_start_utf16);
    const endOrdinal = characterOrdinalAtUtf16Offset(raw, item.host_raw_end_utf16);
    let first;
    let last;
    try {
      first = characters.Item(firstOrdinal + 1);
      last = characters.Item(endOrdinal);
    } catch (_) {
      throw new Error("PREVIEW_RANGE_CHARACTER_LOOKUP_FAILED");
    }
    if (!first || !last || typeof first.SetRange !== "function") throw new Error("PREVIEW_RANGE_BOUNDARY_INVALID");
    try {
      first.SetRange(Number(first.Start), Number(last.End));
    } catch (_) {
      throw new Error("PREVIEW_RANGE_SET_FAILED");
    }
    let readback;
    try {
      readback = stripWpsTerminator(first.Text);
    } catch (_) {
      throw new Error("PREVIEW_RANGE_READBACK_FAILED");
    }
    if (await sha256(readback) !== item.raw_fragment_sha256) throw new Error("PREVIEW_RANGE_READBACK_MISMATCH");
    return first;
  }

  function previewRangeFailureEvent(errorCode) {
    return {
      PREVIEW_BINDING_UNCONFIRMED: "preview.range.binding_unconfirmed",
      PREVIEW_HOST_PARAGRAPH_UNRESOLVED: "preview.range.paragraph_unresolved",
      PREVIEW_RANGE_INVALID: "preview.range.offset_invalid",
      PREVIEW_PARAGRAPH_LOOKUP_FAILED: "preview.range.paragraph_lookup_failed",
      PREVIEW_PARAGRAPH_NOT_FOUND: "preview.range.paragraph_missing",
      PREVIEW_PARAGRAPH_TEXT_READ_FAILED: "preview.range.paragraph_text_failed",
      PREVIEW_PARAGRAPH_CHANGED: "preview.range.paragraph_changed",
      PREVIEW_RANGE_HASH_MISMATCH: "preview.range.fragment_mismatch",
      PREVIEW_CHARACTERS_UNSUPPORTED: "preview.range.characters_unsupported",
      HOST_RANGE_UTF16_BOUNDARY_INVALID: "preview.range.utf16_boundary_invalid",
      PREVIEW_RANGE_CHARACTER_LOOKUP_FAILED: "preview.range.character_lookup_failed",
      PREVIEW_RANGE_BOUNDARY_INVALID: "preview.range.boundary_invalid",
      PREVIEW_RANGE_SET_FAILED: "preview.range.set_failed",
      PREVIEW_RANGE_READBACK_FAILED: "preview.range.readback_failed",
      PREVIEW_RANGE_READBACK_MISMATCH: "preview.range.readback_mismatch"
    }[errorCode] || "preview.range.validation_failed";
  }

  async function clearPreviewComments(options) {
    const silent = Boolean(options && options.silent);
    const requestContext = options && options.requestContext;
    const requireDocx = !(options && options.requireDocx === false);
    const currentHash = await currentDocumentPathHash(requireDocx);
    const key = previewStorageKey(currentHash);
    let raw;
    try {
      raw = storage().getItem(key);
    } catch (error) {
      log("ERROR", "preview.session.read_failed", "预览批注会话读取失败", {
        ...contextDetails(requestContext), error_code: "WPS_PREVIEW_SESSION_READ_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_PREVIEW_SESSION_READ_FAILED");
    }
    if (!raw) return 0;
    let session;
    try { session = JSON.parse(raw); }
    catch (error) {
      log("WARNING", "preview.session.parse_failed", "预览批注会话 JSON 无效，已清除无效记录", {
        ...contextDetails(requestContext), error_code: "WPS_PREVIEW_SESSION_JSON_INVALID",
        error_type: error && error.name ? error.name : "Error"
      });
      try {
        storage().setItem(key, "");
      } catch (clearError) {
        log("ERROR", "preview.session.clear_failed", "无效预览批注会话清除失败", {
          ...contextDetails(requestContext), error_code: "WPS_PREVIEW_SESSION_CLEAR_FAILED",
          error_type: clearError && clearError.name ? clearError.name : "Error"
        });
        throw new Error("WPS_PREVIEW_SESSION_CLEAR_FAILED");
      }
      return 0;
    }
    const comments = activeDocument().Comments;
    if (!comments || typeof comments.Item !== "function") {
      log("ERROR", "preview.comments.collection_unsupported", "WPS Comments 集合不可用", {
        ...contextDetails(requestContext), error_code: "WPS_PREVIEW_COMMENTS_UNSUPPORTED"
      });
      throw new Error("WPS_PREVIEW_COMMENTS_UNSUPPORTED");
    }
    let deleted = 0;
    for (let index = Number(comments.Count || 0); index >= 1; index -= 1) {
      const comment = comments.Item(index);
      if (String(comment.Author || "") !== session.author || String(comment.Initial || "") !== session.initial) continue;
      if (typeof comment.Delete !== "function") {
        log("ERROR", "preview.comment.delete_unsupported", "WPS 批注不支持删除", {
          ...contextDetails(requestContext), block_index: index,
          error_code: "WPS_PREVIEW_COMMENT_DELETE_UNSUPPORTED"
        });
        throw new Error("WPS_PREVIEW_COMMENT_DELETE_UNSUPPORTED");
      }
      try {
        comment.Delete();
      } catch (error) {
        log("ERROR", "preview.comment.delete_failed", "WPS 批注删除失败", {
          ...contextDetails(requestContext), block_index: index,
          error_code: "WPS_PREVIEW_COMMENT_DELETE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_PREVIEW_COMMENT_DELETE_FAILED");
      }
      deleted += 1;
    }
    try {
      storage().setItem(key, "");
    } catch (error) {
      log("ERROR", "preview.session.clear_failed", "预览批注会话清除失败", {
        ...contextDetails(requestContext), error_code: "WPS_PREVIEW_SESSION_CLEAR_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_PREVIEW_SESSION_CLEAR_FAILED");
    }
    if (!silent || deleted) log("INFO", "preview.comments.cleared", "预览批注已清除", {
      ...contextDetails(requestContext), deleted_count: deleted
    });
    return deleted;
  }

  async function validatePreviewRanges(result, requestContext) {
    const startedAt = Date.now();
    const validated = [];
    let skipped = 0;
    log("INFO", "preview.range_validation.start", "开始验证预览范围", {
      ...contextDetails(requestContext)
    });
    for (const item of result.items || []) {
      if (!item.preview_eligible) {
        skipped += 1;
        continue;
      }
      validated.push(item);
    }
    log("INFO", "preview.range_validation.completed", "预览范围验证完成", {
      ...contextDetails(requestContext), validated_count: validated.length,
      skipped_count: skipped, failed_count: 0,
      confirmed_count: validated.filter((item) => item.binding_status === "confirmed").length,
      review_count: validated.filter((item) => item.binding_status === "review").length,
      duration_ms: Date.now() - startedAt
    });
    return validated;
  }

  async function applyPreviewComments(items, documentIdentity, requestContext) {
    const startedAt = Date.now();
    log("INFO", "preview.comments.start", "开始写入预览批注", contextDetails(requestContext));
    await clearPreviewComments({ silent: true, requestContext });
    const document = activeDocument();
    const comments = document.Comments;
    if (!comments || typeof comments.Add !== "function") {
      log("ERROR", "preview.comments.add_unsupported", "WPS Comments.Add 不可用", {
        ...contextDetails(requestContext), error_code: "WPS_PREVIEW_COMMENT_ADD_UNSUPPORTED"
      });
      throw new Error("WPS_PREVIEW_COMMENT_ADD_UNSUPPORTED");
    }
    const sessionId = randomId();
    const author = `DocxTool·${sessionId.slice(-8)}`;
    const initial = "DCT";
    const created = [];
    let applied = 0;
    let confirmedApplied = 0;
    let reviewApplied = 0;
    try {
      for (const item of items) {
        if (await currentDocumentPathHash() !== documentIdentity) {
          log("ERROR", "preview.range.revalidate.failed", "预览文档已切换", Object.assign(contextDetails(requestContext), {
            block_index: item.block_index, error_code: "PREVIEW_DOCUMENT_CHANGED"
          }));
          throw new Error("PREVIEW_DOCUMENT_CHANGED");
        }
        let range;
        try {
          range = await previewRange(document, item);
        } catch (error) {
          const errorCode = stableErrorCode(error, "WPS_PREVIEW_RANGE_VALIDATION_FAILED");
          log("ERROR", previewRangeFailureEvent(errorCode), "预览范围校验失败", Object.assign(contextDetails(requestContext), {
            block_index: item.block_index, error_code: errorCode,
            error_type: error && error.name ? error.name : "Error"
          }));
          log("ERROR", "preview.range.revalidate.failed", "预览范围最终校验失败", Object.assign(contextDetails(requestContext), {
            block_index: item.block_index,
            error_code: errorCode,
            error_type: error && error.name ? error.name : "Error"
          }));
          throw new Error(errorCode);
        }
        log("DEBUG", "preview.range.revalidate.completed", "预览范围最终校验完成", {
          ...contextDetails(requestContext), block_index: item.block_index,
          host_paragraph_index: item.host_paragraph_index,
          start_utf16: item.host_raw_start_utf16, end_utf16: item.host_raw_end_utf16
        });
        const role = roleNames[item.type_id] || item.type_id || "未知";
        const confidence = Math.round(Number(item.confidence || 0) * 100);
        const requiresReview = item.binding_status === "review"
          || item.review_level === "review"
          || item.review_level === "critical_review";
        const review = requiresReview ? "；建议人工复核" : "";
        let comment;
        try {
          comment = comments.Add(range, `DocxTool 预览：${role}；置信度 ${confidence}%${review}。正式格式由 DocxTool Engine 统一生成。`);
        } catch (error) {
          log("ERROR", "preview.comment.create_call.failed", "WPS Comments.Add 调用失败", {
            ...contextDetails(requestContext), block_index: item.block_index,
            error_code: "WPS_PREVIEW_COMMENT_CREATE_CALL_FAILED",
            error_type: error && error.name ? error.name : "Error"
          });
          throw new Error("WPS_PREVIEW_COMMENT_CREATE_CALL_FAILED");
        }
        if (!comment) {
          log("ERROR", "preview.comment.create_result.empty", "WPS Comments.Add 未返回批注对象", {
            ...contextDetails(requestContext), block_index: item.block_index,
            error_code: "WPS_PREVIEW_COMMENT_CREATE_EMPTY"
          });
          throw new Error("WPS_PREVIEW_COMMENT_CREATE_EMPTY");
        }
        created.push(comment);
        try {
          comment.Author = author;
          comment.Initial = initial;
        } catch (error) {
          log("ERROR", "preview.comment.metadata.failed", "预览批注标识写入失败", {
            ...contextDetails(requestContext), block_index: item.block_index,
            error_code: "WPS_PREVIEW_COMMENT_METADATA_FAILED",
            error_type: error && error.name ? error.name : "Error"
          });
          throw new Error("WPS_PREVIEW_COMMENT_METADATA_FAILED");
        }
        applied += 1;
        if (item.binding_status === "review") reviewApplied += 1;
        else confirmedApplied += 1;
        log("DEBUG", "preview.comment.created", "预览批注已创建", {
          ...contextDetails(requestContext), block_index: item.block_index,
          host_paragraph_index: item.host_paragraph_index, type_id: item.type_id
        });
        if (applied % PREVIEW_BATCH_SIZE === 0) {
          log("INFO", "preview.comments.batch", "预览批注批次已写入", {
            ...contextDetails(requestContext), batch_index: applied / PREVIEW_BATCH_SIZE, applied_total: applied
          });
          await sleep(0);
        }
      }
      const currentHash = await currentDocumentPathHash();
      try {
        storage().setItem(previewStorageKey(currentHash), JSON.stringify({ session_id: sessionId, author, initial }));
      } catch (error) {
        log("ERROR", "preview.session.write_failed", "预览批注会话写入失败", {
          ...contextDetails(requestContext), error_code: "WPS_PREVIEW_SESSION_WRITE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_PREVIEW_SESSION_WRITE_FAILED");
      }
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_PREVIEW_COMMENTS_FAILED");
      let cleanupFailed = 0;
      log("WARNING", "preview.comments.rollback.start", "开始回滚本次已创建的预览批注", {
        ...contextDetails(requestContext), applied_count: created.length,
        primary_error_code: errorCode
      });
      for (let index = created.length - 1; index >= 0; index -= 1) {
        try {
          if (created[index] && typeof created[index].Delete === "function") created[index].Delete();
        } catch (cleanupError) {
          cleanupFailed += 1;
          log("WARNING", "preview.comment_cleanup.item.failed", "预览批注清理失败", {
            ...contextDetails(requestContext), block_index: index,
            error_type: cleanupError && cleanupError.name ? cleanupError.name : "Error",
            error_code: stableErrorCode(cleanupError, "WPS_PREVIEW_COMMENT_CLEANUP_FAILED")
          });
        }
      }
      if (cleanupFailed) {
        log("ERROR", "preview.comments.rollback.failed", "部分预览批注回滚失败", {
          ...contextDetails(requestContext), failed_count: cleanupFailed,
          deleted_count: created.length - cleanupFailed,
          error_code: "WPS_PREVIEW_COMMENT_ROLLBACK_INCOMPLETE"
        });
      } else {
        log("WARNING", "preview.comments.rollback.completed", "本次预览批注已全部回滚", {
          ...contextDetails(requestContext), deleted_count: created.length
        });
      }
      throw new Error(errorCode);
    }
    log("INFO", "preview.comments.completed", "预览批注写入完成", {
      ...contextDetails(requestContext), applied_count: applied,
      preview_confirmed_count: confirmedApplied, preview_review_count: reviewApplied,
      duration_ms: Date.now() - startedAt
    });
    return applied;
  }

  function taskpaneUrl() { return new URL("taskpane.html", globalObject.location.href).href; }

  async function reconcileDocumentContext(requestContext, requireDocx = true) {
    const documentIdentity = await currentDocumentPathHash(requireDocx);
    const documentName = activeDocumentName();
    const state = readState();
    if (state.document_identity && state.document_identity !== documentIdentity) {
      writeState({
        status: "READY", stage: "document_changed", message: "已切换文档，请重新识别。",
        document_identity: documentIdentity, document_name: documentName, recognition: null, recognition_rows: [],
        preview_comment_count: 0, preview_confirmed_count: 0, preview_review_count: 0,
        compatibility_warnings: [], format_result: null, error_code: ""
      });
      log("INFO", "document.context.changed", "当前 WPS 文档已切换", {
        ...contextDetails(requestContext), reason: "active_document_changed"
      });
    } else if (state.document_identity !== documentIdentity || state.document_name !== documentName) {
      writeState({ document_identity: documentIdentity, document_name: documentName });
    }
    return documentIdentity;
  }

  function readTaskpaneId(requestContext) {
    try {
      return storage().getItem(TASKPANE_KEY);
    } catch (error) {
      log("ERROR", "taskpane.storage_id.read_failed", "任务窗格 ID 读取失败", {
        ...contextDetails(requestContext), error_code: "WPS_TASKPANE_ID_READ_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_TASKPANE_ID_READ_FAILED");
    }
  }

  function writeTaskpaneId(value, requestContext) {
    try {
      storage().setItem(TASKPANE_KEY, value);
    } catch (error) {
      log("ERROR", "taskpane.storage_id.write_failed", "任务窗格 ID 写入失败", {
        ...contextDetails(requestContext), error_code: "WPS_TASKPANE_ID_WRITE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_TASKPANE_ID_WRITE_FAILED");
    }
  }

  function openTaskpane(requestContext) {
    if (!app || typeof app.CreateTaskPane !== "function") {
      log("ERROR", "taskpane.create.unsupported", "WPS 不支持创建任务窗格", {
        ...contextDetails(requestContext), error_code: "WPS_TASKPANE_CREATE_UNSUPPORTED"
      });
      throw new Error("WPS_TASKPANE_CREATE_UNSUPPORTED");
    }
    void reconcileDocumentContext(requestContext, false).catch((error) => log("WARNING", "document.context.refresh.failed", "任务窗格刷新文档上下文失败", { ...contextDetails(requestContext), error_code: stableErrorCode(error, "WPS_DOCUMENT_CONTEXT_UNAVAILABLE") }));
    const current = readTaskpaneId(requestContext);
    if (current && typeof app.GetTaskPane === "function") {
      log("INFO", "taskpane.reuse.start", "开始复用任务窗格", contextDetails(requestContext));
      try {
        const pane = app.GetTaskPane(Number(current));
        if (pane) {
          pane.Visible = true;
          if (pane.Visible === true) {
            log("INFO", "taskpane.reuse.completed", "任务窗格复用完成", contextDetails(requestContext));
            return pane;
          }
        }
        log("WARNING", "taskpane.reuse.failed", "已有任务窗格不可见，准备重建", { ...contextDetails(requestContext), error_code: "TASKPANE_NOT_VISIBLE" });
      } catch (error) {
        log("WARNING", "taskpane.reuse.failed", "已有任务窗格不可用，准备重建", { ...contextDetails(requestContext), error_code: stableErrorCode(error, "WPS_TASKPANE_REUSE_FAILED") });
      }
      writeTaskpaneId("", requestContext);
    }
    log("INFO", "taskpane.rebuild.start", "开始重建任务窗格", contextDetails(requestContext));
    try {
      let pane;
      try {
        pane = app.CreateTaskPane(taskpaneUrl());
      } catch (error) {
        log("ERROR", "taskpane.create_call.failed", "WPS CreateTaskPane 调用失败", {
          ...contextDetails(requestContext), error_code: "WPS_TASKPANE_CREATE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_TASKPANE_CREATE_FAILED");
      }
      try {
        pane.Visible = true;
        if (pane.Visible !== true) throw new Error("WPS_TASKPANE_NOT_VISIBLE");
      } catch (error) {
        log("ERROR", "taskpane.show.failed", "WPS 任务窗格显示失败", {
          ...contextDetails(requestContext), error_code: "WPS_TASKPANE_SHOW_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_TASKPANE_SHOW_FAILED");
      }
      if ("Width" in pane) {
        try {
          pane.Width = 390;
        } catch (error) {
          log("ERROR", "taskpane.width.failed", "WPS 任务窗格宽度设置失败", {
            ...contextDetails(requestContext), error_code: "WPS_TASKPANE_WIDTH_FAILED",
            error_type: error && error.name ? error.name : "Error"
          });
          throw new Error("WPS_TASKPANE_WIDTH_FAILED");
        }
      }
      writeTaskpaneId(String(pane.ID), requestContext);
      log("INFO", "taskpane.rebuild.completed", "任务窗格重建完成", contextDetails(requestContext));
      return pane;
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_TASKPANE_SHOW_FAILED");
      log("ERROR", "taskpane.rebuild.failed", "任务窗格重建失败", {
        ...contextDetails(requestContext), error_code: errorCode
      });
      throw new Error(errorCode);
    }
  }

  async function runPreview(requestContext, documentContext) {
    const totalStartedAt = Date.now();
    log("INFO", "preview.start", "预览排版开始", contextDetails(requestContext));
    let stage = "document_path_wait";
    try {
    const sourcePath = documentContext.path;
    const pathWaitStartedAt = Date.now();
    log("INFO", "preview.document_path.wait.start", "开始确认当前文档路径", {
      ...contextDetails(requestContext)
    });
    await waitForActiveDocument(sourcePath, requestContext, "preview_path_confirm");
    log("INFO", "preview.document_path.wait.completed", "当前文档路径已确认", {
      ...contextDetails(requestContext), duration_ms: Date.now() - pathWaitStartedAt
    });
    writeState({ status: "RUNNING", stage: "recognition", message: "正在识别当前文档…", error_code: "" });
    const recognitionStartedAt = Date.now();
    stage = "recognition";
    log("INFO", "preview.recognition.start", "开始请求文档识别", contextDetails(requestContext));
    const recognition = await api("/v1/recognize", { source_path: sourcePath }, undefined, requestContext);
    log("INFO", "preview.recognition.completed", "文档识别完成", {
      ...contextDetails(requestContext), plan_id_short: String(recognition.plan_id || "").slice(0, 12),
      block_count: recognition.block_count, review_count: recognition.review_count || 0,
      unresolved_count: recognition.unresolved_count || 0, duration_ms: Date.now() - recognitionStartedAt
    });
    writeState({ status: "RUNNING", stage: "host_binding", message: "识别完成，正在验证当前 WPS 文档位置…" });
    stage = "host_snapshot";
    const snapshotStartedAt = Date.now();
    log("INFO", "preview.host_snapshot.start", "开始采集 WPS 文档快照", contextDetails(requestContext));
    const hostSnapshot = await buildHostSnapshot(requestContext);
    log("INFO", "preview.host_snapshot.completed", "WPS 文档快照采集完成", {
      ...contextDetails(requestContext), paragraph_count: hostSnapshot.paragraphs.length,
      table_paragraph_count: hostSnapshot.paragraphs.filter((item) => item.is_in_table).length,
      duration_ms: Date.now() - snapshotStartedAt
    });
    stage = "binding";
    const bindingStartedAt = Date.now();
    log("INFO", "preview.binding.start", "开始验证识别位置", contextDetails(requestContext));
    const result = await api("/v1/recognize/bind", { plan_id: recognition.plan_id, host_snapshot: hostSnapshot }, undefined, requestContext);
    log("INFO", "preview.binding.completed", "识别位置验证完成", {
      ...contextDetails(requestContext), confirmed_count: result.confirmed_count,
      review_count: result.binding_review_count, unresolved_count: result.unresolved_count,
      preview_eligible_count: result.preview_eligible_count,
      duration_ms: Date.now() - bindingStartedAt
    });
    stage = "range_validation";
    const validatedRanges = await validatePreviewRanges(result, requestContext);
    writeState({ status: "RUNNING", stage: "preview_comments", message: "宿主位置验证完成，正在写入预览批注…" });
    stage = "comments";
    const applied = await applyPreviewComments(validatedRanges, hostSnapshot.document_identity, requestContext);
    const previewConfirmedCount = validatedRanges.filter((item) => item.binding_status === "confirmed").length;
    const previewReviewCount = validatedRanges.filter((item) => item.binding_status === "review").length;
    const rows = (result.items || []).map((item) => ({
      block_index: item.block_index, paragraph_index: item.host_paragraph_index,
      type_id: item.type_id, role_name: roleNames[item.type_id] || item.type_id,
      confidence: item.confidence, review_level: item.review_level,
      locator_verified: item.preview_eligible, binding_status: item.binding_status,
      segment_index: item.segment_index, segment_count: item.segment_count
    }));
    const previewMessage = `预览完成：识别 ${result.block_count} 项；批注 ${applied} 项（确认 ${previewConfirmedCount}，复核 ${previewReviewCount}）；未定位 ${result.unresolved_count}`;
    writeState({
      status: "PASS", stage: "preview_completed",
      message: documentContext.upgraded
        ? `已升级为 ${String(sourcePath).split("\\").pop()}；${previewMessage}`
        : previewMessage,
      recognition: result, recognition_rows: rows, preview_comment_count: applied,
      preview_confirmed_count: previewConfirmedCount, preview_review_count: previewReviewCount,
      document_identity: hostSnapshot.document_identity,
      document_name: activeDocumentName(),
      error_code: ""
    });
    openTaskpane();
    log("INFO", "preview.completed", "预览排版完成", {
      ...contextDetails(requestContext), block_count: result.block_count, applied_count: applied,
      review_count: result.binding_review_count, unresolved_count: result.unresolved_count,
      preview_confirmed_count: previewConfirmedCount, preview_review_count: previewReviewCount,
      total_duration_ms: Date.now() - totalStartedAt
    });
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_PREVIEW_FAILED");
      if (stage !== "range_validation") {
        const stageEvent = stage === "document_path_wait"
          ? "preview.document_path.wait.failed"
          : `preview.${stage}.failed`;
        log("ERROR", stageEvent, "预览排版阶段失败", {
          ...contextDetails(requestContext), stage,
          error_type: error && error.name ? error.name : "Error",
          error_code: errorCode
        });
      }
      log("ERROR", "preview.failed", "预览排版失败", {
        ...contextDetails(requestContext), stage,
        error_type: error && error.name ? error.name : "Error",
        error_code: errorCode,
        total_duration_ms: Date.now() - totalStartedAt
      });
      throw new Error(errorCode);
    }
  }

  async function clearPreview(requestContext) {
    const startedAt = Date.now();
    log("INFO", "preview.clear.start", "开始清除预览", contextDetails(requestContext));
    try {
      const currentFormat = documentFormat(savedDocumentPath());
      if (currentFormat !== "docx") {
        writeState({
          status: "PASS", stage: "preview_cleared",
          message: "当前旧格式文档没有可清除的 DocxTool 预览。",
          recognition: null, recognition_rows: [], preview_comment_count: 0,
          preview_confirmed_count: 0, preview_review_count: 0,
          document_identity: await currentDocumentPathHash(false),
          document_name: activeDocumentName(), error_code: ""
        });
        log("INFO", "preview.clear.skipped_legacy", "旧格式文档无需清除预览", {
          ...contextDetails(requestContext), source_format: currentFormat,
          deleted_count: 0, duration_ms: Date.now() - startedAt
        });
        return;
      }
      const deleted = await clearPreviewComments({ silent: false, requestContext });
      writeState({
        status: "PASS", stage: "preview_cleared", message: `预览已清除：删除 ${deleted} 条 DocxTool 批注。`,
        recognition: null, recognition_rows: [], preview_comment_count: 0,
        preview_confirmed_count: 0, preview_review_count: 0, error_code: ""
      });
      log("INFO", "preview.clear.completed", "预览清除完成", {
        ...contextDetails(requestContext), deleted_count: deleted,
        duration_ms: Date.now() - startedAt
      });
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_PREVIEW_CLEAR_FAILED");
      log("ERROR", "preview.clear.failed", "预览清除失败", {
        ...contextDetails(requestContext), stage: "preview_clear",
        error_type: error && error.name ? error.name : "Error",
        error_code: errorCode,
        duration_ms: Date.now() - startedAt
      });
      throw new Error(errorCode);
    }
  }

  function formatBridgePath(sourcePath, operationId) {
    return sourcePath.replace(/\.docx$/i, `.docxtool-formatting-${operationId.slice(0, 12)}.docx`);
  }

  async function saveFormatBridge(document, bridgePath, requestContext) {
    log("INFO", "format.bridge.save.start", "开始创建排版桥接文档", contextDetails(requestContext));
    try {
      document.SaveAs2(bridgePath);
    } catch (error) {
      log("ERROR", "format.bridge.save.failed", "排版桥接文档创建失败", {
        ...contextDetails(requestContext), error_code: "WPS_FORMAT_BRIDGE_SAVE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_FORMAT_BRIDGE_SAVE_FAILED");
    }
    try {
      await waitForActiveDocument(bridgePath, requestContext, "format_bridge_activate");
    } catch (error) {
      log("ERROR", "format.bridge.activate.failed", "排版桥接文档未能成为活动文档", {
        ...contextDetails(requestContext), error_code: "WPS_FORMAT_BRIDGE_ACTIVATE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_FORMAT_BRIDGE_ACTIVATE_FAILED");
    }
    log("INFO", "format.bridge.save.completed", "排版桥接文档创建完成", contextDetails(requestContext));
  }

  function cleanupFormatBridge(bridgeDocument, bridgePath, requestContext) {
    log("INFO", "format.bridge.close.start", "开始关闭排版桥接文档", contextDetails(requestContext));
    try {
      bridgeDocument.Close(0);
    } catch (error) {
      log("ERROR", "format.bridge.close.failed", "排版桥接文档关闭失败", {
        ...contextDetails(requestContext), error_code: "WPS_FORMAT_BRIDGE_CLOSE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_FORMAT_BRIDGE_CLOSE_FAILED");
    }
    log("INFO", "format.bridge.close.completed", "排版桥接文档已关闭", contextDetails(requestContext));
    log("INFO", "format.bridge.delete.start", "开始删除排版桥接文档", contextDetails(requestContext));
    try {
      app.FileSystem.unlinkSync(bridgePath);
    } catch (error) {
      log("ERROR", "format.bridge.delete.failed", "排版桥接文档删除失败", {
        ...contextDetails(requestContext), error_code: "WPS_FORMAT_BRIDGE_DELETE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_FORMAT_BRIDGE_DELETE_FAILED");
    }
    log("INFO", "format.bridge.delete.completed", "排版桥接文档已删除", contextDetails(requestContext));
    log("INFO", "format.bridge.cleanup.completed", "排版桥接文档清理完成", contextDetails(requestContext));
  }

  async function recoverFormat(operationId, sourcePath, targetPath, committed, bridgeDocument, bridgePath, requestContext) {
    if (!operationId) return;
    if (committed && sourceIsActive(targetPath)) {
      const current = activeDocument();
      if (typeof current.Close !== "function") {
        log("ERROR", "format.recovery.close_unsupported", "恢复事务时 WPS Document.Close 不可用", {
          ...contextDetails(requestContext), error_code: "WPS_FORMAT_RECOVERY_CLOSE_UNSUPPORTED"
        });
        throw new Error("WPS_FORMAT_RECOVERY_CLOSE_UNSUPPORTED");
      }
      try {
        current.Close(0);
      } catch (error) {
        log("ERROR", "format.recovery.close_failed", "恢复事务时关闭 WPS 文档失败", {
          ...contextDetails(requestContext), error_code: "WPS_FORMAT_RECOVERY_CLOSE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_FORMAT_RECOVERY_CLOSE_FAILED");
      }
    }
    try {
      await api("/v1/format/rollback", {
        operation_id: operationId,
        preserve_conversion: Boolean(bridgeDocument && bridgePath)
      }, undefined, requestContext);
    } catch (error) {
      log("ERROR", "format.rollback.failed", "一键排版回滚失败", { ...contextDetails(requestContext), error_code: stableErrorCode(error, "WPS_FORMAT_ROLLBACK_FAILED") });
      throw new Error("WPS_FORMAT_RECOVERY_REQUIRED");
    }
    if (!sourceIsActive(sourcePath)) {
      if (!app.Documents || typeof app.Documents.Open !== "function") {
        log("ERROR", "format.recovery.open_unsupported", "恢复事务时 WPS Documents.Open 不可用", {
          ...contextDetails(requestContext), error_code: "WPS_FORMAT_RECOVERY_OPEN_UNSUPPORTED"
        });
        throw new Error("WPS_FORMAT_RECOVERY_OPEN_UNSUPPORTED");
      }
      try {
        app.Documents.Open(sourcePath);
      } catch (error) {
        log("ERROR", "format.recovery.open_failed", "恢复事务时重新打开 WPS 文档失败", {
          ...contextDetails(requestContext), error_code: "WPS_FORMAT_RECOVERY_OPEN_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_FORMAT_RECOVERY_OPEN_FAILED");
      }
      await waitForActiveDocument(sourcePath, requestContext, "format_recovery_reopen");
    }
    if (bridgeDocument && bridgePath) {
      cleanupFormatBridge(bridgeDocument, bridgePath, requestContext);
    }
    log("WARNING", "format.rollback.completed", "一键排版失败后已恢复原文档", contextDetails(requestContext));
  }

  function warningCount(prepared) {
    return Array.isArray(prepared.compatibility_warnings) ? prepared.compatibility_warnings.length : 0;
  }

  function documentFormat(path) {
    const lower = String(path || "").toLowerCase();
    if (lower.endsWith(".docx")) return "docx";
    if (lower.endsWith(".doc")) return "doc";
    if (lower.endsWith(".wps")) return "wps";
    throw new Error("WPS_DOCUMENT_FORMAT_UNSUPPORTED");
  }

  async function ensureDocxForCommand(requestContext, command) {
    const document = activeDocument();
    const startedAt = Date.now();
    log("INFO", "document.format.detect.start", "开始检测当前文档格式", {
      ...contextDetails(requestContext), command
    });
    const sourcePath = await saveActiveDocument(
      requestContext,
      "document_format_preflight",
      false
    );
    const sourceFormat = documentFormat(sourcePath);
    log("INFO", "document.format.detected", "当前文档格式检测完成", {
      ...contextDetails(requestContext), command, source_format: sourceFormat,
      target_format: "docx", duration_ms: Date.now() - startedAt
    });
    if (sourceFormat === "docx") {
      return {
        path: sourcePath,
        sourcePath,
        targetPath: sourcePath,
        sourceFormat,
        upgraded: false,
        pendingUpgrade: false,
        operationId: "",
        bridgeDocument: null,
        bridgePath: ""
      };
    }

    let stage = "snapshot";
    let operationId = "";
    let committed = false;
    let bridgeDocument = null;
    let bridgePath = "";
    let targetPath = sourcePath;
    try {
      if (typeof document.SaveAs2 !== "function") throw new Error("WPS_FORMAT_BRIDGE_SAVE_UNSUPPORTED");
      if (typeof document.Close !== "function") throw new Error("WPS_FORMAT_BRIDGE_CLOSE_UNSUPPORTED");
      if (!app.Documents || typeof app.Documents.Open !== "function") throw new Error("WPS_DOCUMENT_OPEN_UNSUPPORTED");
      if (!app.FileSystem || typeof app.FileSystem.unlinkSync !== "function") throw new Error("WPS_FORMAT_BRIDGE_DELETE_UNSUPPORTED");
      writeState({
        status: "RUNNING", stage: "document_upgrade",
        message: "正在将旧格式静默升级为 DOCX…", error_code: ""
      });
      log("INFO", "document.upgrade.start", "旧格式文档静默升级开始", {
        ...contextDetails(requestContext), command, source_format: sourceFormat,
        target_format: "docx"
      });
      const before = await legacyConversionSnapshot(requestContext);
      stage = "reserve";
      const reserved = await api(
        "/v1/format/upgrade/reserve",
        { source_path: sourcePath },
        undefined,
        requestContext
      );
      operationId = reserved.operation_id;
      bridgePath = reserved.conversion_path;
      targetPath = reserved.target_path;
      log("INFO", "document.upgrade.reserved", "旧格式升级事务已预留", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12),
        source_format: sourceFormat, target_format: "docx"
      });
      stage = "save_as";
      log("INFO", "document.upgrade.save_as.start", "开始调用 WPS 转换旧格式文档", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12),
        source_format: sourceFormat, target_format: "docx"
      });
      try {
        document.SaveAs2(bridgePath, DOCX_SAVE_FORMAT);
      } catch (error) {
        log("ERROR", "document.upgrade.save_as.failed", "WPS 旧格式转换调用失败", {
          ...contextDetails(requestContext), command,
          operation_id_short: operationId.slice(0, 12),
          error_code: "WPS_LEGACY_CONVERSION_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_LEGACY_CONVERSION_FAILED");
      }
      if (sourceIsActive(bridgePath)) bridgeDocument = document;
      await waitForActiveDocument(bridgePath, requestContext, "document_upgrade_activate");
      bridgeDocument = document;
      log("INFO", "document.upgrade.save_as.completed", "WPS 旧格式转换完成", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12),
        source_format: sourceFormat, target_format: "docx"
      });
      stage = "verify";
      log("INFO", "document.upgrade.verify.start", "开始校验旧格式转换内容", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12)
      });
      const after = await legacyConversionSnapshot(requestContext);
      verifyLegacyConversion(before, after, requestContext);
      const context = {
        path: bridgePath,
        sourcePath,
        targetPath,
        sourceFormat,
        upgraded: true,
        pendingUpgrade: true,
        operationId,
        bridgeDocument,
        bridgePath
      };
      if (command === "apply") return context;

      stage = "prepare_converted";
      log("INFO", "document.upgrade.publish.start", "开始发布升级后的 DOCX", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12)
      });
      await api(
        "/v1/format/upgrade/prepare-converted",
        { operation_id: operationId },
        undefined,
        requestContext
      );
      stage = "commit";
      await api(
        "/v1/format/commit",
        { operation_id: operationId },
        undefined,
        requestContext
      );
      committed = true;
      log("INFO", "document.upgrade.publish.completed", "升级后的 DOCX 已发布", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12)
      });
      stage = "reopen";
      log("INFO", "document.upgrade.reopen.start", "开始打开升级后的 DOCX", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12)
      });
      try {
        app.Documents.Open(targetPath);
      } catch (error) {
        log("ERROR", "document.upgrade.reopen.failed", "升级后的 DOCX 打开失败", {
          ...contextDetails(requestContext), command,
          operation_id_short: operationId.slice(0, 12),
          error_code: "WPS_DOCUMENT_OPEN_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_DOCUMENT_OPEN_FAILED");
      }
      await waitForActiveDocument(targetPath, requestContext, "document_upgrade_reopen");
      log("INFO", "document.upgrade.reopen.completed", "升级后的 DOCX 已打开", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12)
      });
      stage = "bridge_cleanup";
      cleanupFormatBridge(bridgeDocument, bridgePath, requestContext);
      bridgeDocument = null;
      bridgePath = "";
      stage = "finalize";
      await api(
        "/v1/format/finalize",
        { operation_id: operationId },
        undefined,
        requestContext
      );
      log("INFO", "document.upgrade.completed", "旧格式文档静默升级完成", {
        ...contextDetails(requestContext), command,
        operation_id_short: operationId.slice(0, 12),
        source_format: sourceFormat, target_format: "docx",
        duration_ms: Date.now() - startedAt
      });
      return {
        path: targetPath,
        sourcePath: targetPath,
        targetPath,
        sourceFormat,
        upgraded: true,
        pendingUpgrade: false,
        operationId: "",
        bridgeDocument: null,
        bridgePath: ""
      };
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_DOCUMENT_UPGRADE_FAILED");
      log("ERROR", "document.upgrade.failed", "旧格式文档静默升级失败", {
        ...contextDetails(requestContext), command, stage,
        error_code: errorCode,
        error_type: error && error.name ? error.name : "Error",
        duration_ms: Date.now() - startedAt
      });
      try {
        await recoverFormat(
          operationId,
          sourcePath,
          targetPath,
          committed,
          bridgeDocument,
          bridgePath,
          requestContext
        );
      } catch (recoveryError) {
        const recoveryCode = stableErrorCode(
          recoveryError,
          "WPS_FORMAT_RECOVERY_REQUIRED"
        );
        log("ERROR", "document.upgrade.rollback.failed", "旧格式升级回滚失败", {
          ...contextDetails(requestContext), command,
          primary_error_code: errorCode,
          error_code: recoveryCode,
          error_type: recoveryError && recoveryError.name ? recoveryError.name : "Error"
        });
        throw new Error(recoveryCode);
      }
      log("WARNING", "document.upgrade.rollback.completed", "旧格式升级失败后已恢复原文档", {
        ...contextDetails(requestContext), command, error_code: errorCode
      });
      throw new Error(errorCode);
    }
  }

  async function runFormat(requestContext, documentContext) {
    const totalStartedAt = Date.now();
    const document = activeDocument();
    log("INFO", "format.start", "一键排版开始", contextDetails(requestContext));
    let stage = "preview_clear";
    log("INFO", "format.preview_clear.start", "开始清除预览批注", contextDetails(requestContext));
    try {
      await clearPreviewComments({ silent: true, requestContext, requireDocx: false });
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_PREVIEW_CLEAR_FAILED");
      log("ERROR", "format.preview_clear.failed", "预览批注清除失败", {
        ...contextDetails(requestContext), error_type: error && error.name ? error.name : "Error",
        error_code: errorCode
      });
      log("ERROR", "format.failed", "一键排版失败", Object.assign(contextDetails(requestContext), {
        stage, error_code: errorCode
      }));
      throw new Error(errorCode);
    }
    log("INFO", "format.preview_clear.completed", "预览批注清除完成", contextDetails(requestContext));
    const sourcePath = documentContext.sourcePath;
    const sourceFormat = documentContext.sourceFormat;
    const legacyUpgrade = documentContext.pendingUpgrade;
    let operationId = documentContext.operationId;
    let committed = false;
    let bridgeDocument = documentContext.bridgeDocument;
    let bridgePath = documentContext.bridgePath;
    const targetPath = documentContext.targetPath;
    writeState({ status: "RUNNING", stage: "format_prepare", message: "正在调用 DocxTool Engine 排版…", error_code: "" });
    try {
      if (typeof document.SaveAs2 !== "function") throw new Error("WPS_FORMAT_BRIDGE_SAVE_UNSUPPORTED");
      if (typeof document.Close !== "function") throw new Error("WPS_FORMAT_BRIDGE_CLOSE_UNSUPPORTED");
      if (!app.Documents || typeof app.Documents.Open !== "function") throw new Error("WPS_DOCUMENT_OPEN_UNSUPPORTED");
      if (!app.FileSystem || typeof app.FileSystem.unlinkSync !== "function") throw new Error("WPS_FORMAT_BRIDGE_DELETE_UNSUPPORTED");
      let prepared;
      if (legacyUpgrade) {
        stage = "transaction_prepare";
        log("INFO", "document.upgrade.format.start", "开始排版升级后的临时 DOCX", {
          ...contextDetails(requestContext),
          operation_id_short: operationId.slice(0, 12)
        });
        prepared = await api(
          "/v1/format/upgrade/prepare",
          { operation_id: operationId },
          undefined,
          requestContext
        );
        log("INFO", "document.upgrade.format.completed", "升级后的临时 DOCX 排版完成", {
          ...contextDetails(requestContext),
          operation_id_short: operationId.slice(0, 12),
          paragraph_count: prepared.paragraph_count,
          headings: prepared.heading_count
        });
      } else {
        stage = "transaction_prepare";
        log("INFO", "format.transaction.prepare.start", "开始准备排版事务", contextDetails(requestContext));
        prepared = await api("/v1/format/prepare", { source_path: sourcePath }, undefined, requestContext);
        operationId = prepared.operation_id;
        bridgeDocument = document;
        bridgePath = formatBridgePath(sourcePath, operationId);
        writeState({ status: "RUNNING", stage: "bridge_save", message: "排版结果已生成，正在安全替换当前文档…", operation_id: operationId });
        stage = "bridge_save";
        await saveFormatBridge(bridgeDocument, bridgePath, requestContext);
      }
      log("INFO", "format.prepare.completed", "排版结果准备完成", {
        ...contextDetails(requestContext), operation_id_short: operationId.slice(0, 12),
        paragraph_count: prepared.paragraph_count, headings: prepared.heading_count,
        compatibility_warnings: warningCount(prepared), log_file: prepared.log_file
      });
      log("INFO", "format.transaction.prepare.completed", "排版事务准备完成", {
        ...contextDetails(requestContext), operation_id_short: operationId.slice(0, 12)
      });
      stage = "commit";
      if (legacyUpgrade) {
        log("INFO", "document.upgrade.publish.start", "开始发布升级并排版后的 DOCX", {
          ...contextDetails(requestContext),
          operation_id_short: operationId.slice(0, 12)
        });
      }
      log("INFO", "format.commit.start", "开始提交排版事务", contextDetails(requestContext));
      await api("/v1/format/commit", { operation_id: operationId }, undefined, requestContext);
      committed = true;
      log("INFO", "format.commit.completed", "排版事务提交完成", contextDetails(requestContext));
      if (legacyUpgrade) {
        log("INFO", "document.upgrade.publish.completed", "升级并排版后的 DOCX 已发布", {
          ...contextDetails(requestContext),
          operation_id_short: operationId.slice(0, 12)
        });
      }
      stage = "document_reopen";
      log("INFO", "format.document.reopen.start", "开始重新打开文档", contextDetails(requestContext));
      try {
        app.Documents.Open(targetPath);
      } catch (error) {
        log("ERROR", "format.document.open_call.failed", "WPS 文档重新打开调用失败", {
          ...contextDetails(requestContext), error_code: "WPS_DOCUMENT_OPEN_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_DOCUMENT_OPEN_FAILED");
      }
      await waitForActiveDocument(targetPath, requestContext, "format_reopen");
      log("INFO", "format.document.reopen.completed", "文档重新打开完成", contextDetails(requestContext));
      stage = "bridge_cleanup";
      cleanupFormatBridge(bridgeDocument, bridgePath, requestContext);
      bridgeDocument = null;
      bridgePath = "";
      stage = "finalize";
      log("INFO", "format.finalize.start", "开始完成排版事务", contextDetails(requestContext));
      await api("/v1/format/finalize", { operation_id: operationId }, undefined, requestContext);
      log("INFO", "format.finalize.completed", "排版事务已完成", contextDetails(requestContext));
      operationId = "";
      committed = false;
      const warnings = warningCount(prepared);
      const documentIdentity = await currentDocumentPathHash();
      writeState({
        status: "PASS", stage: "completed",
        message: legacyUpgrade
          ? `已升级为 ${String(targetPath).split("\\").pop()} 并完成排版：${prepared.paragraph_count} 个段落，${prepared.heading_count} 个标题${warnings ? `；兼容性提示 ${warnings} 项` : ""}。`
          : `排版完成：${prepared.paragraph_count} 个段落，${prepared.heading_count} 个标题${warnings ? `；兼容性提示 ${warnings} 项` : ""}。`,
        format_result: prepared, compatibility_warnings: prepared.compatibility_warnings || [],
        error_code: "", operation_id: "", preview_comment_count: 0,
        preview_confirmed_count: 0, preview_review_count: 0,
        document_identity: documentIdentity, document_name: activeDocumentName()
      });
      log("INFO", "format.completed", "一键排版完成", {
        ...contextDetails(requestContext), paragraphs: prepared.paragraph_count, headings: prepared.heading_count,
        compatibility_warnings: warnings, source_format: sourceFormat, target_format: "docx",
        total_duration_ms: Date.now() - totalStartedAt
      });
      if (legacyUpgrade) {
        log("INFO", "document.upgrade.completed", "旧格式文档升级并排版完成", {
          ...contextDetails(requestContext), source_format: sourceFormat,
          target_format: "docx", total_duration_ms: Date.now() - totalStartedAt
        });
      }
    } catch (error) {
      const code = stableErrorCode(error, "WPS_FORMAT_FAILED");
      if (legacyUpgrade) {
        log("ERROR", "document.upgrade.failed", "旧格式文档升级排版失败", {
          ...contextDetails(requestContext), stage, error_code: code,
          error_type: error && error.name ? error.name : "Error"
        });
      }
      log("ERROR", `format.${stage}.failed`, "一键排版阶段失败", {
        ...contextDetails(requestContext), stage, error_code: code,
        error_type: error && error.name ? error.name : "Error"
      });
      log("ERROR", "format.failed", "一键排版失败", {
        ...contextDetails(requestContext), stage, error_code: code,
        total_duration_ms: Date.now() - totalStartedAt
      });
      try {
        log("WARNING", "transaction.recovery.start", "开始恢复排版事务", contextDetails(requestContext));
        await recoverFormat(operationId, sourcePath, targetPath, committed, bridgeDocument, bridgePath, requestContext);
        log("WARNING", "transaction.recovery.completed", "排版事务恢复完成", contextDetails(requestContext));
      } catch (recoveryError) {
        const recoveryCode = stableErrorCode(recoveryError, "WPS_FORMAT_RECOVERY_REQUIRED");
        if (legacyUpgrade) {
          log("ERROR", "document.upgrade.rollback.failed", "旧格式升级排版回滚失败", {
            ...contextDetails(requestContext), primary_error_code: code,
            error_code: recoveryCode,
            error_type: recoveryError && recoveryError.name ? recoveryError.name : "Error"
          });
        }
        log("ERROR", "transaction.recovery.failed", "排版事务恢复失败", {
          ...contextDetails(requestContext), stage: "format_recovery",
          error_type: recoveryError && recoveryError.name ? recoveryError.name : "Error",
          error_code: recoveryCode
        });
        log("ERROR", "format.recovery.required", "一键排版失败且自动恢复未完成", {
          ...contextDetails(requestContext), error_code: recoveryCode, primary_error_code: code
        });
        throw new Error(recoveryCode);
      }
      if (legacyUpgrade) {
        log("WARNING", "document.upgrade.rollback.completed", "旧格式升级排版失败后已恢复原文档", {
          ...contextDetails(requestContext), error_code: code
        });
      }
      throw new Error(code);
    }
  }

  async function runHealth(requestContext) {
    const result = await api("/v1/health", null, "GET", requestContext);
    writeState({ status: "PASS", stage: "health", message: `本地服务正常；DocxTool ${result.docxtool_version}`, health: result, error_code: "" });
    openTaskpane(requestContext);
    log("INFO", "health.pass", "WPS 本机检测通过", {
      ...contextDetails(requestContext), docxtool_version: result.docxtool_version
    });
  }

  function completeTaskpaneRequest(requestContext, status, errorCode) {
    if (!requestContext || requestContext.source !== "taskpane") return;
    writeState({ active_request: Object.assign({}, contextDetails(requestContext), {
      request_id: requestContext.request_id, command: requestContext.command, request_status: status, error_code: errorCode || ""
    }) });
  }

  async function runCommand(name, requestContext) {
    if (busy && name !== "panel") {
      log("WARNING", "host.command.rejected.busy", "WPS Host 正在执行其他命令", {
        ...contextDetails(requestContext), command: name,
        error_code: "WPS_COMMAND_BUSY"
      });
      throw new Error("WPS_COMMAND_BUSY");
    }
    if (name === "panel") { openTaskpane(); return; }
    busy = true;
    const startedAt = Date.now();
    log("INFO", "host.command.start", "WPS 命令开始执行", Object.assign(contextDetails(requestContext), { command: name }));
    try {
      let documentContext = null;
      if (name === "preview" || name === "apply") {
        try {
          documentContext = await ensureDocxForCommand(requestContext, name);
        } catch (error) {
          const errorCode = stableErrorCode(error, "WPS_DOCUMENT_PREFLIGHT_FAILED");
          const eventPrefix = name === "apply" ? "format" : "preview";
          log("ERROR", `${eventPrefix}.preflight.failed`, "功能执行前文档准备失败", {
            ...contextDetails(requestContext), command: name,
            stage: "document_preflight", error_code: errorCode,
            error_type: error && error.name ? error.name : "Error"
          });
          log("ERROR", `${eventPrefix}.failed`, name === "apply" ? "一键排版失败" : "预览排版失败", {
            ...contextDetails(requestContext), command: name,
            stage: "document_preflight", error_code: errorCode
          });
          throw new Error(errorCode);
        }
        if (!documentContext.pendingUpgrade) {
          const documentIdentity = await reconcileDocumentContext(requestContext);
          writeState({ document_identity: documentIdentity });
        }
      }
      if (name === "preview") await runPreview(requestContext, documentContext);
      else if (name === "apply") await runFormat(requestContext, documentContext);
      else if (name === "clear_preview") await clearPreview(requestContext);
      else if (name === "health") await runHealth(requestContext);
      else {
        log("ERROR", "host.command.unknown", "收到未知 WPS 命令", {
          ...contextDetails(requestContext), command: name,
          error_code: "WPS_COMMAND_UNKNOWN"
        });
        throw new Error("WPS_COMMAND_UNKNOWN");
      }
      completeTaskpaneRequest(requestContext, "PASS");
      log("INFO", "host.command.completed", "WPS 命令执行完成", {
        ...contextDetails(requestContext), command: name, duration_ms: Date.now() - startedAt
      });
    } catch (error) {
      const code = stableErrorCode(error, "WPS_COMMAND_FAILED");
      log("ERROR", "host.command.failed", "WPS 命令执行失败", {
        ...contextDetails(requestContext), command: name, error_code: code,
        duration_ms: Date.now() - startedAt
      });
      const failureState = { status: "FAIL", stage: "failed", message: commandFailureMessage(code), error_code: code };
      if (requestContext && requestContext.source === "taskpane") {
        failureState.active_request = Object.assign({}, contextDetails(requestContext), {
          request_id: requestContext.request_id, command: requestContext.command,
          request_status: "FAIL", error_code: code
        });
      }
      try {
        writeState(failureState);
      } catch (stateError) {
        log("ERROR", "host.command.failure_state.failed", "命令失败状态发布失败", {
          ...contextDetails(requestContext), command: name, primary_error_code: code,
          error_code: stableErrorCode(stateError, "WPS_COMMAND_FAILURE_STATE_WRITE_FAILED"),
          error_type: stateError && stateError.name ? stateError.name : "Error"
        });
      }
      try {
        openTaskpane(requestContext);
      } catch (panelError) {
        log("ERROR", "host.command.failure_panel_open.failed", "命令失败后任务窗格打开失败", {
          ...contextDetails(requestContext), command: name, primary_error_code: code,
          error_code: stableErrorCode(panelError, "WPS_TASKPANE_OPEN_FAILED"),
          error_type: panelError && panelError.name ? panelError.name : "Error"
        });
      }
      throw new Error(code);
    } finally {
      busy = false;
      try {
        if (app.ribbonUI && typeof app.ribbonUI.Invalidate === "function") app.ribbonUI.Invalidate();
      } catch (error) {
        log("WARNING", "ribbon.invalidate.failed", "Ribbon 状态刷新失败", {
          ...contextDetails(requestContext), command: name,
          error_code: "WPS_RIBBON_INVALIDATE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
      }
    }
  }

  function pollTaskpaneRequests() {
    if (!pollFirstTickLogged) {
      pollFirstTickLogged = true;
      log("INFO", "host.poll.first_tick", "任务窗格请求轮询已执行首次检查", {
        host_ready: started, poll_interval_ms: 250, request_key: REQUEST_KEY
      });
    }
    try {
      let raw;
      try {
        raw = storage().getItem(REQUEST_KEY);
      } catch (error) {
        log("ERROR", "host.request_slot.read_failed", "Host 请求槽读取失败", {
          error_code: "WPS_REQUEST_SLOT_READ_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        stopPollingForStorageFailure("WPS_REQUEST_SLOT_READ_FAILED");
        throw new Error("WPS_REQUEST_SLOT_READ_FAILED");
      }
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
        clearRequestSlot(null, "json_invalid");
        throw new Error("WPS_REQUEST_JSON_INVALID");
      }
      log("INFO", "host.request.parsed", "任务窗格请求解析完成", {
        request_id: request && request.request_id ? request.request_id : "",
        command: request && request.command_name ? request.command_name : "",
        pane_instance_id_present: Boolean(request && request.pane_instance_id)
      });
      if (!request || request.schema_version !== "wps-request-v2") {
        log("ERROR", "host.request.schema_invalid", "任务窗格请求协议版本无效", {
          request_id: request && request.request_id ? request.request_id : "",
          command: request && request.command_name ? request.command_name : "",
          reason: "schema_invalid", error_code: "WPS_REQUEST_SCHEMA_INVALID"
        });
        clearRequestSlot(request, "schema_invalid");
        return;
      }
      if (!request.request_id) {
        log("ERROR", "host.request.id_missing", "任务窗格请求缺少请求 ID", {
          reason: "request_id_missing", error_code: "WPS_REQUEST_ID_MISSING"
        });
        clearRequestSlot(null, "request_id_missing");
        return;
      }
      if (!request.command_name) {
        log("ERROR", "host.request.command_missing", "任务窗格请求缺少命令", {
          request_id: request.request_id, reason: "command_missing",
          error_code: "WPS_REQUEST_COMMAND_MISSING"
        });
        clearRequestSlot(request, "command_missing");
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
        clearRequestSlot(request, "already_processed");
        return;
      }
      if (busy) {
        clearRequestSlot(request, "busy");
        writeState({ last_request: { request_id: request.request_id, request_status: "FAIL", error_code: "WPS_COMMAND_BUSY" } });
        log("WARNING", "host.request.rejected.busy", "任务窗格请求被忙碌命令拒绝", Object.assign(contextDetails(request), {
          command: request.command_name, reason: "busy", error_code: "WPS_COMMAND_BUSY"
        }));
        return;
      }
      const requestContext = Object.freeze({
        request_id: request.request_id, command: request.command_name, source: "taskpane",
        document_name: activeDocumentName()
      });
      lastRequestId = request.request_id;
      writeState({ active_request: Object.assign({}, contextDetails(requestContext), {
        request_id: requestContext.request_id, command: requestContext.command, request_status: "CLAIMED", error_code: ""
      }) });
      clearRequestSlot(requestContext, "claimed");
      log("INFO", "taskpane.request.claimed", "任务窗格请求已领取", Object.assign(contextDetails(requestContext), { command: requestContext.command }));
      log("INFO", "host.request.claimed", "任务窗格请求已领取", Object.assign(contextDetails(requestContext), { command: requestContext.command }));
      void runCommand(requestContext.command, requestContext).finally(() => {
        log("INFO", "taskpane.request.completed", "任务窗格请求处理结束", Object.assign(contextDetails(requestContext), { command: requestContext.command }));
      });
    } catch (error) {
      log("ERROR", "host.request.invalid", "任务窗格请求处理失败", { error_code: stableErrorCode(error, "WPS_HOST_REQUEST_FAILED") });
    }
  }

  function validateConfig() {
    if (!config.controlBaseUrl || !config.sessionToken) {
      log("ERROR", "host.config.missing", "WPS Control 配置缺失", {
        control_url_present: Boolean(config.controlBaseUrl),
        token_present: Boolean(config.sessionToken),
        error_code: "WPS_CONTROL_CONFIG_MISSING"
      });
      throw new Error("WPS_CONTROL_CONFIG_MISSING");
    }
    let controlUrl;
    try {
      controlUrl = new URL(config.controlBaseUrl);
    } catch (error) {
      log("ERROR", "host.config.url_invalid", "WPS Control URL 无法解析", {
        control_url_present: true, token_present: true,
        error_code: "WPS_CONTROL_URL_INVALID",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_CONTROL_URL_INVALID");
    }
    if (controlUrl.hostname !== "127.0.0.1" || !controlUrl.port) {
      log("ERROR", "host.config.endpoint_invalid", "WPS Control 必须使用带端口的 loopback 地址", {
        control_url_present: true, token_present: true,
        error_code: "WPS_CONTROL_ENDPOINT_INVALID"
      });
      throw new Error("WPS_CONTROL_ENDPOINT_INVALID");
    }
    log("INFO", "host.config.validated", "WPS Control 配置验证完成", {
      control_port: Number(controlUrl.port), token_present: true
    });
  }

  function start() {
    log("INFO", "host.start.enter", "Host Runtime 启动入口已进入", {});
    if (started) {
      log("INFO", "host.start.already_started", "Host Runtime 已启动，本次调用不重复初始化", {});
      return "already_started";
    }
    let stage = "config_validate";
    try {
      log("INFO", "host.config.validate.start", "开始验证 Host Runtime 配置", {});
      validateConfig();
      log("INFO", "host.config.validate.completed", "Host Runtime 配置验证完成", {});
      stage = "storage_initialize";
      log("INFO", "host.storage.initialize.start", "开始验证 PluginStorage", {});
      if (!app || !app.PluginStorage) throw new Error("WPS_PLUGIN_STORAGE_UNAVAILABLE");
      log("INFO", "host.storage.initialize.completed", "PluginStorage 验证完成", {});
      stage = "storage_reset";
      const staleRequestPresent = Boolean(storage().getItem(REQUEST_KEY));
      log("INFO", "host.storage.reset.start", "开始清理旧 Host 状态和请求槽", {
        slot_occupied: staleRequestPresent
      });
      try {
        storage().setItem(REQUEST_KEY, "");
        storage().setItem(STATE_KEY, "");
      } catch (error) {
        log("ERROR", "host.storage.reset.failed", "旧 Host 状态或请求槽清理失败", {
          slot_occupied: staleRequestPresent,
          error_code: "WPS_HOST_STORAGE_RESET_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_HOST_STORAGE_RESET_FAILED");
      }
      log("INFO", "host.storage.reset.completed", "旧 Host 状态和请求槽已清理", {
        cleared_count: staleRequestPresent ? 2 : 1
      });
      stage = "poll_start";
      log("INFO", "host.poll.start", "开始创建任务窗格请求轮询", {
        poll_interval_ms: 250, request_key: REQUEST_KEY
      });
      pollFirstTickLogged = false;
      pollTimer = setInterval(pollTaskpaneRequests, 250);
      if (!pollTimer) throw new Error("WPS_REQUEST_POLL_UNAVAILABLE");
      log("INFO", "host.poll.started", "任务窗格请求轮询已启动", {
        poll_interval_ms: 250, request_key: REQUEST_KEY
      });
      stage = "state_publish";
      log("INFO", "host.state.publish.start", "开始发布 Host 就绪状态", {});
      writeState({
        status: "READY", stage: "ready", message: "DocxTool WPS 已就绪",
        host_ready: true, recognition_rows: [], compatibility_warnings: [],
        preview_comment_count: 0, preview_confirmed_count: 0, preview_review_count: 0,
        error_code: "", active_request: null, last_request: null
      });
      log("INFO", "host.state.publish.completed", "Host 就绪状态已发布", {
        host_ready: true
      });
      started = true;
      log("INFO", "host.start.completed", "Host Runtime 启动完成", { host_ready: true });
      return "started";
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_HOST_START_FAILED");
      if (pollTimer) clearInterval(pollTimer);
      pollTimer = null;
      pollFirstTickLogged = false;
      started = false;
      log("ERROR", "host.start.rollback", "Host Runtime 启动已回滚", {
        stage, error_code: errorCode
      });
      log("ERROR", "host.start.failed", "Host Runtime 启动失败", {
        stage, error_type: error && error.name ? error.name : "Error",
        error_code: errorCode
      });
      throw new Error(errorCode);
    }
  }

  function handleRibbonAction(id) {
    log("INFO", "ribbon.action.received", "收到 Ribbon 操作", {
      ...contextDetails(null), command: id, busy
    });
    if (id === "panel") {
      if (!started) {
        log("INFO", "host.start.lazy.enter", "状态面板正在补充启动 Host Runtime", {
          command: id, reason: "addin_load_not_observed", host_ready: false
        });
        try {
          const startResult = start();
          log("INFO", "host.start.lazy.completed", "状态面板已补充启动 Host Runtime", {
            command: id, state: startResult, host_ready: true
          });
        } catch (error) {
          const errorCode = stableErrorCode(error, "WPS_HOST_START_FAILED");
          log("ERROR", "host.start.lazy.failed", "状态面板补充启动 Host Runtime 失败", {
            command: id, stage: "ribbon_panel", reason: "addin_load_not_observed",
            error_code: errorCode,
            error_type: error && error.name ? error.name : "Error"
          });
          throw new Error(errorCode);
        }
      }
      openTaskpane();
      return;
    }
    if (!started) {
      log("ERROR", "ribbon.action.blocked", "Host 尚未完成启动，Ribbon 业务命令被拒绝", {
        command: id, reason: "host_not_started", error_code: "WPS_HOST_NOT_STARTED",
        host_ready: false
      });
      throw new Error("WPS_HOST_NOT_STARTED");
    }
    const requestContext = Object.freeze({
      request_id: `ribbon-${randomId()}`, command: id, source: "ribbon",
      document_name: activeDocumentName()
    });
    log("INFO", "ribbon.action.started", "Ribbon 操作开始", Object.assign(contextDetails(requestContext), { command: id }));
    void runCommand(id, requestContext).then(() => {
      log("INFO", "ribbon.action.completed", "Ribbon 操作完成", Object.assign(contextDetails(requestContext), { command: id }));
    }).catch((error) => {
      log("ERROR", "ribbon.action.failed", "Ribbon 操作失败", {
        ...contextDetails(requestContext), command: id,
        error_code: stableErrorCode(error, "WPS_COMMAND_FAILED")
      });
    });
  }

  function getActionEnabled(id) {
    if (id === "panel") return true;
    if (!started) return false;
    if (id === "health") return !busy;
    try {
      return !busy && ["docx", "doc", "wps"].includes(documentFormat(savedDocumentPath()));
    }
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
    bootstrap_id: bootstrapId, config_present: Boolean(globalObject.DocxToolWpsConfig),
    host_instance_id_short: hostInstanceIdShort
  });
  globalObject.DocxToolHostRuntime = Object.freeze({
    start,
    runCommand,
    getBusy: () => busy,
    getInstanceIdShort: () => hostInstanceIdShort,
    handleRibbonAction,
    getActionEnabled
  });
})();
