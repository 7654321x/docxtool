(function () {
  "use strict";

  const globalObject = window;
  const app = globalObject.Application;
  const config = globalObject.DocxToolWpsConfig || {};
  const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
  const TASKPANE_VERSION_KEY = "docxtool_wps_taskpane_version_v1";
  const TASKPANE_PAGE_VERSION = "10";
  const PREVIEW_KEY_PREFIX = "docxtool_wps_preview_v2:";
  const PREVIEW_BATCH_SIZE = 5;
  const TASKPANE_HOST_PROBE_DELAYS_MS = [0, 100, 500, 1000];
  const SAVE_WAIT_ATTEMPTS = 30;
  const REOPEN_WAIT_ATTEMPTS = 30;
  const DOCX_SAVE_FORMAT = 12;
  const PANEL_READY_LAYOUT_SETTLE_MS = 150;
  let busy = false;
  let lastRequestId = "";
  let started = false;
  let bridgeRunning = false;
  let bridgeReady = false;
  let hostGeneration = 0;
  let hostState = {};
  let statePublishChain = Promise.resolve();
  let statePublishError = "";
  let ribbonUI = null;
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
    "deleted_count", "document_id_short", "event_sequence", "log_file", "pending_present", "slot_occupied",
    "callbacks_registered", "state", "host_ready", "cleared_count", "cause_event",
    "primary_error_code", "previous_status", "current_status", "preview_confirmed_count",
    "preview_eligible_count", "preview_review_count", "warning_code",
    "conversion_state", "inline_shape_count", "mismatch_count", "section_count",
    "shape_count", "source_format", "target_format", "target_state",
    "bridge_ready", "command_sequence", "generation_changed", "host_generation",
    "replaced", "state_revision", "wait_timed_out", "page_version", "pane_branch",
    "pane_dock_position", "pane_expected_dock_position", "pane_found", "pane_id",
    "pane_visible", "pane_width", "active_document_present", "active_window_present",
    "checkpoint", "document_matches_expected", "observed_delay_ms", "pane_reference_matches",
    "pane_dock_position_before", "pane_dock_position_requested", "pane_dock_position_after",
    "pane_dock_position_effective", "pane_width_before", "pane_width_requested",
    "pane_width_after", "pane_width_effective", "pane_visible_before", "pane_visible_requested",
    "pane_visible_after", "pane_visible_effective", "stored_pane_id_present"
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
    return hostState;
  }

  function writeState(patch) {
    if (statePublishError) throw new Error(statePublishError);
    const state = Object.assign({}, hostState, patch, { updated_at: new Date().toISOString() });
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
    hostState = JSON.parse(serialized);
    if (bridgeReady) queueStatePublication(hostState);
    return state;
  }

  function randomId() {
    if (globalObject.crypto && typeof globalObject.crypto.randomUUID === "function") return globalObject.crypto.randomUUID();
    return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2)}`;
  }

  const bootstrapId = String(globalObject.DocxToolBootstrapId || "");
  const hostInstanceIdShort = `host-${randomId().replace(/-/g, "").slice(0, 12)}`;
  const hostContextId = `host-context-${randomId()}`;

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

  function taskpaneExpectedDockPosition() {
    const value = app && app.Enum ? Number(app.Enum.msoCTPDockPositionRight) : NaN;
    return Number.isFinite(value) ? value : -1;
  }

  function taskpaneDetails(pane, branch) {
    const width = pane && "Width" in pane ? Number(pane.Width) : NaN;
    const dockPosition = pane && "DockPosition" in pane ? Number(pane.DockPosition) : NaN;
    return {
      pane_branch: branch,
      pane_id: pane && pane.ID != null ? String(pane.ID) : "",
      pane_visible: Boolean(pane && pane.Visible === true),
      pane_width: Number.isFinite(width) ? width : -1,
      pane_dock_position: Number.isFinite(dockPosition) ? dockPosition : -1,
      pane_expected_dock_position: taskpaneExpectedDockPosition()
    };
  }

  function taskpaneHostDetails(pane, branch, checkpoint, requestContext, extras) {
    const document = app && app.ActiveDocument;
    const currentDocumentName = activeDocumentName();
    const expectedDocumentName = requestContext && requestContext.document_name
      ? String(requestContext.document_name)
      : "";
    const details = Object.assign({}, contextDetails(requestContext), taskpaneDetails(pane, branch), {
      checkpoint,
      active_document_present: Boolean(document),
      active_window_present: Boolean(document && document.ActiveWindow),
      document_matches_expected: !expectedDocumentName || currentDocumentName === expectedDocumentName
    }, extras || {});
    if (currentDocumentName) details.document_name = currentDocumentName;
    return details;
  }

  function logStoredTaskpaneSnapshot(event, message, checkpoint, requestContext, extras) {
    try {
      const storedPaneId = readTaskpaneId(requestContext);
      const pane = storedPaneId && app && typeof app.GetTaskPane === "function"
        ? app.GetTaskPane(Number(storedPaneId))
        : null;
      log("INFO", event, message, taskpaneHostDetails(
        pane,
        "stored",
        checkpoint,
        requestContext,
        Object.assign({
          pane_found: Boolean(pane),
          stored_pane_id_present: Boolean(storedPaneId)
        }, extras || {})
      ));
    } catch (error) {
      log("WARNING", `${event}.failed`, "任务窗格宿主状态快照采集失败", {
        ...contextDetails(requestContext), checkpoint,
        error_code: "WPS_TASKPANE_HOST_SNAPSHOT_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
    }
  }

  function scheduleTaskpaneHostSnapshots(pane, branch, requestContext) {
    const paneId = pane && pane.ID != null ? Number(pane.ID) : NaN;
    TASKPANE_HOST_PROBE_DELAYS_MS.forEach((delay) => {
      setTimeout(() => {
        try {
          const observedPane = Number.isFinite(paneId) && app && typeof app.GetTaskPane === "function"
            ? app.GetTaskPane(paneId)
            : null;
          log("INFO", "taskpane.host_state.snapshot", "任务窗格宿主属性延时快照已采集", taskpaneHostDetails(
            observedPane,
            branch,
            `after_open_${delay}ms`,
            requestContext,
            {
              observed_delay_ms: delay,
              pane_found: Boolean(observedPane),
              pane_reference_matches: Boolean(observedPane && observedPane === pane)
            }
          ));
        } catch (error) {
          log("WARNING", "taskpane.host_state.snapshot.failed", "任务窗格宿主属性延时快照采集失败", {
            ...contextDetails(requestContext), checkpoint: `after_open_${delay}ms`,
            observed_delay_ms: delay,
            error_code: "WPS_TASKPANE_HOST_SNAPSHOT_FAILED",
            error_type: error && error.name ? error.name : "Error"
          });
        }
      }, delay);
    });
  }

  function logUnexpectedTaskpaneDock(pane, branch, requestContext) {
    const details = taskpaneDetails(pane, branch);
    if (details.pane_expected_dock_position < 0 || details.pane_dock_position < 0
        || details.pane_expected_dock_position === details.pane_dock_position) return;
    log("WARNING", "taskpane.dock_position.unexpected", "任务窗格实际停靠位置与 WPS 右侧停靠枚举不一致", {
      ...contextDetails(requestContext), ...details,
      error_code: "WPS_TASKPANE_DOCK_POSITION_UNEXPECTED"
    });
  }

  function activateDocumentAfterTaskpaneOpen(requestContext, branch) {
    const document = app && app.ActiveDocument;
    if (!document) {
      log("INFO", "taskpane.document_focus.skipped", "当前没有活动文档，任务窗格保持网页焦点", {
        ...contextDetails(requestContext), pane_branch: branch, reason: "no_active_document"
      });
      return;
    }
    const startedAt = Date.now();
    log("INFO", "taskpane.document_focus.start", "开始将焦点交还当前文档窗口", {
      ...contextDetails(requestContext), pane_branch: branch,
      active_document_present: true,
      active_window_present: Boolean(document.ActiveWindow)
    });
    if (typeof document.Activate !== "function") {
      log("ERROR", "taskpane.document_activate.unsupported", "WPS 当前文档不支持 Activate", {
        ...contextDetails(requestContext), pane_branch: branch,
        error_code: "WPS_DOCUMENT_ACTIVATE_UNSUPPORTED"
      });
      throw new Error("WPS_DOCUMENT_ACTIVATE_UNSUPPORTED");
    }
    log("INFO", "taskpane.document_activate.start", "开始激活当前 WPS 文档", {
      ...contextDetails(requestContext), pane_branch: branch,
      active_document_present: true
    });
    try {
      document.Activate();
    } catch (error) {
      log("ERROR", "taskpane.document_activate.failed", "WPS 当前文档激活失败", {
        ...contextDetails(requestContext), pane_branch: branch,
        error_code: "WPS_DOCUMENT_ACTIVATE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_DOCUMENT_ACTIVATE_FAILED");
    }
    log("INFO", "taskpane.document_activate.completed", "当前 WPS 文档已激活", {
      ...contextDetails(requestContext), pane_branch: branch,
      active_document_present: Boolean(app && app.ActiveDocument)
    });
    const activeWindow = document.ActiveWindow;
    if (!activeWindow || typeof activeWindow.Activate !== "function") {
      log("ERROR", "taskpane.document_window_activate.unsupported", "WPS 当前文档窗口不支持 Activate", {
        ...contextDetails(requestContext), pane_branch: branch,
        error_code: "WPS_DOCUMENT_WINDOW_ACTIVATE_UNSUPPORTED"
      });
      throw new Error("WPS_DOCUMENT_WINDOW_ACTIVATE_UNSUPPORTED");
    }
    log("INFO", "taskpane.document_window_activate.start", "开始激活当前 WPS 文档窗口", {
      ...contextDetails(requestContext), pane_branch: branch,
      active_window_present: true
    });
    try {
      activeWindow.Activate();
    } catch (error) {
      log("ERROR", "taskpane.document_window_activate.failed", "WPS 当前文档窗口激活失败", {
        ...contextDetails(requestContext), pane_branch: branch,
        error_code: "WPS_DOCUMENT_WINDOW_ACTIVATE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_DOCUMENT_WINDOW_ACTIVATE_FAILED");
    }
    log("INFO", "taskpane.document_window_activate.completed", "当前 WPS 文档窗口已激活", {
      ...contextDetails(requestContext), pane_branch: branch,
      active_window_present: Boolean(document.ActiveWindow)
    });
    log("INFO", "taskpane.document_focus.completed", "焦点已交还当前文档窗口", {
      ...contextDetails(requestContext), pane_branch: branch,
      duration_ms: Date.now() - startedAt
    });
  }

  async function runPanelReady(requestContext) {
    const startedAt = Date.now();
    log("INFO", "panel_ready.start", "任务窗格加载完成，开始触发 WPS 工作区重算", {
      ...contextDetails(requestContext), pane_branch: "panel_ready"
    });
    logStoredTaskpaneSnapshot(
      "panel_ready.host_snapshot.before",
      "工作区重算前窗格状态已采集",
      "before_panel_ready_lifecycle",
      requestContext,
      { command: "panel_ready" }
    );
    const sourceDocument = app && app.ActiveDocument;
    if (!sourceDocument) {
      log("ERROR", "panel_ready.source_document.missing", "工作区重算前没有活动文档", {
        ...contextDetails(requestContext), active_document_present: false,
        error_code: "WPS_PANEL_READY_DOCUMENT_UNAVAILABLE"
      });
      throw new Error("WPS_PANEL_READY_DOCUMENT_UNAVAILABLE");
    }
    if (!app.Documents || typeof app.Documents.Add !== "function") {
      log("ERROR", "panel_ready.temporary_document.create_unsupported", "WPS Documents.Add 不可用", {
        ...contextDetails(requestContext), active_document_present: true,
        error_code: "WPS_PANEL_READY_DOCUMENT_ADD_UNSUPPORTED"
      });
      throw new Error("WPS_PANEL_READY_DOCUMENT_ADD_UNSUPPORTED");
    }
    if (typeof sourceDocument.Activate !== "function") {
      log("ERROR", "panel_ready.source_document.activate_unsupported", "原文档不支持重新激活", {
        ...contextDetails(requestContext), active_document_present: true,
        error_code: "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_UNSUPPORTED"
      });
      throw new Error("WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_UNSUPPORTED");
    }
    let temporaryDocument;
    log("INFO", "panel_ready.temporary_document.create.start", "开始创建临时空白文档", {
      ...contextDetails(requestContext), stage: "temporary_document_create"
    });
    try {
      temporaryDocument = app.Documents.Add();
    } catch (error) {
      log("ERROR", "panel_ready.temporary_document.create.failed", "临时空白文档创建失败", {
        ...contextDetails(requestContext), stage: "temporary_document_create",
        error_code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_CREATE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_PANEL_READY_TEMPORARY_DOCUMENT_CREATE_FAILED");
    }
    if (!temporaryDocument) {
      log("ERROR", "panel_ready.temporary_document.create.empty", "WPS 未返回临时空白文档", {
        ...contextDetails(requestContext), stage: "temporary_document_create",
        error_code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_UNAVAILABLE"
      });
      throw new Error("WPS_PANEL_READY_TEMPORARY_DOCUMENT_UNAVAILABLE");
    }
    if (typeof temporaryDocument.Close !== "function") {
      log("ERROR", "panel_ready.temporary_document.close_unsupported", "临时空白文档不支持关闭", {
        ...contextDetails(requestContext), stage: "temporary_document_create",
        error_code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLOSE_UNSUPPORTED"
      });
      throw new Error("WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLOSE_UNSUPPORTED");
    }
    log("INFO", "panel_ready.temporary_document.create.completed", "临时空白文档创建完成", {
      ...contextDetails(requestContext), stage: "temporary_document_create",
      active_document_present: Boolean(app.ActiveDocument),
      document_matches_expected: app.ActiveDocument === temporaryDocument
    });
    log("INFO", "panel_ready.source_document.activate.start", "开始切回原文档", {
      ...contextDetails(requestContext), stage: "source_document_activate"
    });
    try {
      sourceDocument.Activate();
    } catch (error) {
      log("ERROR", "panel_ready.source_document.activate.failed", "切回原文档失败", {
        ...contextDetails(requestContext), stage: "source_document_activate",
        error_code: "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      log("INFO", "panel_ready.temporary_document.cleanup.start", "原文档激活失败，开始关闭临时空白文档", {
        ...contextDetails(requestContext), stage: "temporary_document_cleanup",
        primary_error_code: "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED"
      });
      try {
        temporaryDocument.Close(0);
      } catch (cleanupError) {
        log("ERROR", "panel_ready.temporary_document.cleanup.failed", "原文档激活失败后临时文档清理失败", {
          ...contextDetails(requestContext), stage: "temporary_document_cleanup",
          primary_error_code: "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED",
          error_code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLEANUP_FAILED",
          error_type: cleanupError && cleanupError.name ? cleanupError.name : "Error"
        });
        throw new Error("WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLEANUP_FAILED");
      }
      log("INFO", "panel_ready.temporary_document.cleanup.completed", "原文档激活失败后临时文档已关闭", {
        ...contextDetails(requestContext), stage: "temporary_document_cleanup",
        primary_error_code: "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED"
      });
      throw new Error("WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED");
    }
    log("INFO", "panel_ready.source_document.activate.completed", "已切回原文档", {
      ...contextDetails(requestContext), stage: "source_document_activate",
      active_document_present: Boolean(app.ActiveDocument),
      document_matches_expected: app.ActiveDocument === sourceDocument
    });
    log("INFO", "panel_ready.temporary_document.close.start", "开始关闭临时空白文档", {
      ...contextDetails(requestContext), stage: "temporary_document_close"
    });
    try {
      temporaryDocument.Close(0);
    } catch (error) {
      log("ERROR", "panel_ready.temporary_document.close.failed", "临时空白文档关闭失败", {
        ...contextDetails(requestContext), stage: "temporary_document_close",
        error_code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLOSE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLOSE_FAILED");
    }
    log("INFO", "panel_ready.temporary_document.close.completed", "临时空白文档已关闭", {
      ...contextDetails(requestContext), stage: "temporary_document_close",
      active_document_present: Boolean(app.ActiveDocument),
      document_matches_expected: app.ActiveDocument === sourceDocument
    });
    log("INFO", "panel_ready.layout_settle.start", "开始等待 WPS 完成工作区重算", {
      ...contextDetails(requestContext), stage: "layout_settle",
      interval_ms: PANEL_READY_LAYOUT_SETTLE_MS
    });
    const settleStartedAt = Date.now();
    await sleep(PANEL_READY_LAYOUT_SETTLE_MS);
    log("INFO", "panel_ready.layout_settle.completed", "WPS 工作区重算等待完成", {
      ...contextDetails(requestContext), stage: "layout_settle",
      duration_ms: Date.now() - settleStartedAt
    });
    logStoredTaskpaneSnapshot(
      "panel_ready.host_snapshot.after",
      "工作区重算后窗格状态已采集",
      "after_panel_ready_lifecycle",
      requestContext,
      { command: "panel_ready" }
    );
    log("INFO", "panel_ready.completed", "任务窗格工作区重算已完成", {
      ...contextDetails(requestContext),
      duration_ms: Date.now() - startedAt
    });
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

  async function bridgeApi(path, body, requestContext) {
    if (!config.controlBaseUrl || !config.sessionToken) throw new Error("WPS_CONTROL_NOT_CONFIGURED");
    const response = await fetch(`${config.controlBaseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.sessionToken}`,
        "X-DocxTool-Request-Id": requestId(requestContext)
      },
      body: JSON.stringify(body || {})
    });
    let payload;
    try {
      payload = await response.json();
    } catch (error) {
      throw new Error("WPS_BRIDGE_RESPONSE_INVALID");
    }
    if (!response.ok || !payload.ok) throw new Error(payload.error_code || "WPS_BRIDGE_REQUEST_FAILED");
    return payload.data;
  }

  function stateRequestContext(state) {
    const active = state && state.active_request;
    if (!active || !active.request_id) return { request_id: "" };
    return { request_id: active.request_id };
  }

  function queueStatePublication(state) {
    const snapshot = JSON.parse(JSON.stringify(state));
    statePublishChain = statePublishChain.then(async () => {
      if (statePublishError) throw new Error(statePublishError);
      try {
        const result = await bridgeApi("/v1/bridge/state", {
          host_context_id: hostContextId,
          host_generation: hostGeneration,
          state: snapshot
        }, stateRequestContext(snapshot));
        log("INFO", "host.bridge.state.published", "Host 状态已发布到通信桥", {
          ...stateRequestContext(snapshot), host_generation: result.host_generation,
          state_revision: result.state_revision, current_status: snapshot.status || "",
          stage: snapshot.stage || ""
        });
      } catch (error) {
        const errorCode = stableErrorCode(error, "WPS_BRIDGE_STATE_PUBLISH_FAILED");
        statePublishError = errorCode;
        bridgeReady = false;
        bridgeRunning = false;
        log("ERROR", "host.bridge.state.publish_failed", "Host 状态发布失败", {
          ...stateRequestContext(snapshot), host_generation: hostGeneration,
          current_status: snapshot.status || "", stage: snapshot.stage || "",
          error_code: errorCode,
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error(errorCode);
      }
    });
    void statePublishChain.catch(() => {});
  }

  async function flushStatePublication() {
    await statePublishChain;
    if (statePublishError) throw new Error(statePublishError);
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
    log("INFO", "preview.range_selection.start", "开始筛选可预览范围", {
      ...contextDetails(requestContext)
    });
    for (const item of result.items || []) {
      if (!item.preview_eligible) {
        skipped += 1;
        continue;
      }
      validated.push(item);
    }
    log("INFO", "preview.range_selection.completed", "可预览范围筛选完成", {
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
          comment = comments.Add(range, `识别格式：${role}；置信度 ${confidence}%${review}。`);
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

  function taskpaneUrl() {
    const url = new URL("taskpane.html", globalObject.location.href);
    url.searchParams.set("v", TASKPANE_PAGE_VERSION);
    return url.href;
  }

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

  function readTaskpaneVersion(requestContext) {
    try {
      return storage().getItem(TASKPANE_VERSION_KEY);
    } catch (error) {
      log("ERROR", "taskpane.storage_version.read_failed", "任务窗格页面版本读取失败", {
        ...contextDetails(requestContext), error_code: "WPS_TASKPANE_VERSION_READ_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_TASKPANE_VERSION_READ_FAILED");
    }
  }

  function writeTaskpaneVersion(value, requestContext) {
    try {
      storage().setItem(TASKPANE_VERSION_KEY, value);
    } catch (error) {
      log("ERROR", "taskpane.storage_version.write_failed", "任务窗格页面版本写入失败", {
        ...contextDetails(requestContext), error_code: "WPS_TASKPANE_VERSION_WRITE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_TASKPANE_VERSION_WRITE_FAILED");
    }
  }

  function openTaskpane(requestContext) {
    const openStartedAt = Date.now();
    requestContext = Object.assign({}, requestContext || {}, {
      document_name: requestContext && requestContext.document_name
        ? String(requestContext.document_name)
        : activeDocumentName()
    });
    log("INFO", "taskpane.open.enter", "任务窗格打开流程已进入", {
      ...contextDetails(requestContext), page_version: TASKPANE_PAGE_VERSION
    });
    if (!app || typeof app.CreateTaskPane !== "function") {
      log("ERROR", "taskpane.create.unsupported", "WPS 不支持创建任务窗格", {
        ...contextDetails(requestContext), error_code: "WPS_TASKPANE_CREATE_UNSUPPORTED"
      });
      throw new Error("WPS_TASKPANE_CREATE_UNSUPPORTED");
    }
    void reconcileDocumentContext(requestContext, false).catch((error) => log("WARNING", "document.context.refresh.failed", "任务窗格刷新文档上下文失败", { ...contextDetails(requestContext), error_code: stableErrorCode(error, "WPS_DOCUMENT_CONTEXT_UNAVAILABLE") }));
    let current = readTaskpaneId(requestContext);
    const currentPageVersion = current ? readTaskpaneVersion(requestContext) : "";
    log("INFO", "taskpane.storage_state.resolved", "任务窗格本地标识和页面版本已读取", {
      ...contextDetails(requestContext), pane_instance_id_present: Boolean(current),
      page_version: currentPageVersion || ""
    });
    if (current && currentPageVersion !== TASKPANE_PAGE_VERSION) {
      log("INFO", "taskpane.page_version.mismatch", "已有任务窗格页面版本已过期，准备重建", {
        ...contextDetails(requestContext), reason: "page_version_mismatch"
      });
      if (typeof app.GetTaskPane === "function") {
        try {
          const stalePane = app.GetTaskPane(Number(current));
          if (stalePane) {
            stalePane.Visible = false;
            if (stalePane.Visible !== false) throw new Error("WPS_STALE_TASKPANE_NOT_HIDDEN");
          }
        } catch (error) {
          log("ERROR", "taskpane.stale.hide_failed", "旧任务窗格隐藏失败", {
            ...contextDetails(requestContext), reason: "page_version_mismatch",
            error_code: "WPS_STALE_TASKPANE_HIDE_FAILED",
            error_type: error && error.name ? error.name : "Error"
          });
          throw new Error("WPS_STALE_TASKPANE_HIDE_FAILED");
        }
      }
      writeTaskpaneId("", requestContext);
      writeTaskpaneVersion("", requestContext);
      current = "";
    }
    if (current && typeof app.GetTaskPane === "function") {
      const reuseStartedAt = Date.now();
      let reusablePane = null;
      log("INFO", "taskpane.reuse.start", "开始复用任务窗格", {
        ...contextDetails(requestContext), page_version: currentPageVersion
      });
      try {
        const pane = app.GetTaskPane(Number(current));
        log("INFO", "taskpane.reuse.lookup.completed", "已有任务窗格查询完成", {
          ...contextDetails(requestContext), pane_found: Boolean(pane),
          ...taskpaneDetails(pane, "reused")
        });
        if (pane) {
          const before = taskpaneDetails(pane, "reused");
          log("INFO", "taskpane.reuse.show.start", "开始显示已有任务窗格", {
            ...contextDetails(requestContext), ...before,
            pane_visible_before: before.pane_visible,
            pane_visible_requested: true
          });
          pane.Visible = true;
          const after = taskpaneDetails(pane, "reused");
          log("INFO", "taskpane.reuse.show.completed", "已有任务窗格显示属性已写入", {
            ...contextDetails(requestContext), ...after,
            pane_visible_before: before.pane_visible,
            pane_visible_requested: true,
            pane_visible_after: after.pane_visible,
            pane_visible_effective: after.pane_visible === true
          });
          if (pane.Visible === true) reusablePane = pane;
        }
        if (!reusablePane) {
          log("WARNING", "taskpane.reuse.failed", "已有任务窗格不可见，准备重建", { ...contextDetails(requestContext), error_code: "TASKPANE_NOT_VISIBLE" });
        }
      } catch (error) {
        log("WARNING", "taskpane.reuse.failed", "已有任务窗格不可用，准备重建", { ...contextDetails(requestContext), error_code: stableErrorCode(error, "WPS_TASKPANE_REUSE_FAILED") });
      }
      if (reusablePane) {
        logUnexpectedTaskpaneDock(reusablePane, "reused", requestContext);
        activateDocumentAfterTaskpaneOpen(requestContext, "reused");
        log("INFO", "taskpane.reuse.completed", "任务窗格复用完成", {
          ...contextDetails(requestContext), ...taskpaneDetails(reusablePane, "reused"),
          duration_ms: Date.now() - reuseStartedAt
        });
        scheduleTaskpaneHostSnapshots(reusablePane, "reused", requestContext);
        return reusablePane;
      }
      writeTaskpaneId("", requestContext);
    }
    log("INFO", "taskpane.rebuild.start", "开始重建任务窗格", contextDetails(requestContext));
    try {
      let pane;
      try {
        const createStartedAt = Date.now();
        pane = app.CreateTaskPane(taskpaneUrl());
        log("INFO", "taskpane.create.completed", "WPS CreateTaskPane 调用完成", {
          ...contextDetails(requestContext), ...taskpaneDetails(pane, "created"),
          page_version: TASKPANE_PAGE_VERSION, duration_ms: Date.now() - createStartedAt
        });
      } catch (error) {
        log("ERROR", "taskpane.create_call.failed", "WPS CreateTaskPane 调用失败", {
          ...contextDetails(requestContext), error_code: "WPS_TASKPANE_CREATE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_TASKPANE_CREATE_FAILED");
      }
      const expectedDockPosition = taskpaneExpectedDockPosition();
      if (expectedDockPosition < 0 || !("DockPosition" in pane)) {
        log("ERROR", "taskpane.dock_position.unsupported", "WPS 任务窗格不支持右侧停靠属性", {
          ...contextDetails(requestContext), ...taskpaneDetails(pane, "created"),
          error_code: "WPS_TASKPANE_DOCK_POSITION_UNSUPPORTED"
        });
        throw new Error("WPS_TASKPANE_DOCK_POSITION_UNSUPPORTED");
      }
      try {
        const before = taskpaneDetails(pane, "created");
        log("INFO", "taskpane.dock_position.write.start", "开始设置任务窗格右侧停靠位置", {
          ...contextDetails(requestContext), ...before,
          pane_dock_position_before: before.pane_dock_position,
          pane_dock_position_requested: expectedDockPosition
        });
        pane.DockPosition = expectedDockPosition;
        const after = taskpaneDetails(pane, "created");
        if (after.pane_dock_position !== expectedDockPosition) {
          throw new Error("WPS_TASKPANE_DOCK_POSITION_READBACK_FAILED");
        }
        log("INFO", "taskpane.dock_position.completed", "任务窗格右侧停靠位置已在显示前确认", {
          ...contextDetails(requestContext), ...after,
          pane_dock_position_before: before.pane_dock_position,
          pane_dock_position_requested: expectedDockPosition,
          pane_dock_position_after: after.pane_dock_position,
          pane_dock_position_effective: after.pane_dock_position === expectedDockPosition
        });
      } catch (error) {
        log("ERROR", "taskpane.dock_position.failed", "WPS 任务窗格右侧停靠设置失败", {
          ...contextDetails(requestContext), error_code: "WPS_TASKPANE_DOCK_POSITION_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_TASKPANE_DOCK_POSITION_FAILED");
      }
      if ("Width" in pane) {
        try {
          const requestedWidth = 390;
          const before = taskpaneDetails(pane, "created");
          log("INFO", "taskpane.width.write.start", "开始设置任务窗格目标宽度", {
            ...contextDetails(requestContext), ...before,
            pane_width_before: before.pane_width,
            pane_width_requested: requestedWidth
          });
          pane.Width = requestedWidth;
          const after = taskpaneDetails(pane, "created");
          log("INFO", "taskpane.width.completed", "任务窗格宽度已在显示前设置完成", {
            ...contextDetails(requestContext), ...after,
            pane_width_before: before.pane_width,
            pane_width_requested: requestedWidth,
            pane_width_after: after.pane_width,
            pane_width_effective: after.pane_width === requestedWidth
          });
        } catch (error) {
          log("ERROR", "taskpane.width.failed", "WPS 任务窗格宽度设置失败", {
            ...contextDetails(requestContext), error_code: "WPS_TASKPANE_WIDTH_FAILED",
            error_type: error && error.name ? error.name : "Error"
          });
          throw new Error("WPS_TASKPANE_WIDTH_FAILED");
        }
      }
      try {
        const before = taskpaneDetails(pane, "created");
        log("INFO", "taskpane.show.start", "开始显示任务窗格", {
          ...contextDetails(requestContext), ...before,
          pane_visible_before: before.pane_visible,
          pane_visible_requested: true
        });
        pane.Visible = true;
        const after = taskpaneDetails(pane, "created");
        if (after.pane_visible !== true) throw new Error("WPS_TASKPANE_NOT_VISIBLE");
        log("INFO", "taskpane.show.completed", "任务窗格可见状态已确认", {
          ...contextDetails(requestContext), ...after,
          pane_visible_before: before.pane_visible,
          pane_visible_requested: true,
          pane_visible_after: after.pane_visible,
          pane_visible_effective: after.pane_visible === true
        });
      } catch (error) {
        log("ERROR", "taskpane.show.failed", "WPS 任务窗格显示失败", {
          ...contextDetails(requestContext), error_code: "WPS_TASKPANE_SHOW_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_TASKPANE_SHOW_FAILED");
      }
      logUnexpectedTaskpaneDock(pane, "created", requestContext);
      activateDocumentAfterTaskpaneOpen(requestContext, "created");
      writeTaskpaneVersion(TASKPANE_PAGE_VERSION, requestContext);
      writeTaskpaneId(String(pane.ID), requestContext);
      log("INFO", "taskpane.rebuild.completed", "任务窗格重建完成", {
        ...contextDetails(requestContext), ...taskpaneDetails(pane, "created"),
        page_version: TASKPANE_PAGE_VERSION, duration_ms: Date.now() - openStartedAt
      });
      scheduleTaskpaneHostSnapshots(pane, "created", requestContext);
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
      type_id: item.type_id, role_name: roleNames[item.type_id] || "未知",
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
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "排版桥接文档创建前宿主状态已采集",
      "before_bridge_save_as",
      requestContext,
      { command: "apply" }
    );
    log("INFO", "format.bridge.save_as.call.start", "开始调用 WPS Document.SaveAs2 创建桥接文档", {
      ...contextDetails(requestContext), stage: "bridge_save_as"
    });
    try {
      document.SaveAs2(bridgePath);
    } catch (error) {
      log("ERROR", "format.bridge.save.failed", "排版桥接文档创建失败", {
        ...contextDetails(requestContext), error_code: "WPS_FORMAT_BRIDGE_SAVE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_FORMAT_BRIDGE_SAVE_FAILED");
    }
    log("INFO", "format.bridge.save_as.call.completed", "WPS Document.SaveAs2 桥接调用完成", {
      ...contextDetails(requestContext), stage: "bridge_save_as"
    });
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "排版桥接文档 SaveAs2 后宿主状态已采集",
      "after_bridge_save_as",
      requestContext,
      { command: "apply" }
    );
    log("INFO", "format.bridge.activate.wait.start", "开始等待排版桥接文档成为活动文档", {
      ...contextDetails(requestContext), stage: "format_bridge_activate"
    });
    try {
      await waitForActiveDocument(bridgePath, requestContext, "format_bridge_activate");
    } catch (error) {
      log("ERROR", "format.bridge.activate.failed", "排版桥接文档未能成为活动文档", {
        ...contextDetails(requestContext), error_code: "WPS_FORMAT_BRIDGE_ACTIVATE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_FORMAT_BRIDGE_ACTIVATE_FAILED");
    }
    log("INFO", "format.bridge.activate.wait.completed", "排版桥接文档已成为活动文档", {
      ...contextDetails(requestContext), stage: "format_bridge_activate"
    });
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "排版桥接文档激活后宿主状态已采集",
      "after_bridge_activated",
      requestContext,
      { command: "apply" }
    );
    log("INFO", "format.bridge.save.completed", "排版桥接文档创建完成", contextDetails(requestContext));
  }

  function cleanupFormatBridge(bridgeDocument, bridgePath, requestContext) {
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "排版桥接文档关闭前宿主状态已采集",
      "before_bridge_close",
      requestContext,
      { command: "apply" }
    );
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
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "排版桥接文档关闭后宿主状态已采集",
      "after_bridge_close",
      requestContext,
      { command: "apply" }
    );
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
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "排版桥接文档删除后宿主状态已采集",
      "after_bridge_delete",
      requestContext,
      { command: "apply" }
    );
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
        { source_path: sourcePath, command },
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
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "一键排版开始时宿主状态已采集",
      "format_start",
      requestContext,
      { command: "apply" }
    );
    let stage = "preview_clear";
    log("INFO", "format.preview_clear.start", "开始清除预览批注", contextDetails(requestContext));
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "清除预览批注前宿主状态已采集",
      "before_preview_clear",
      requestContext,
      { command: "apply" }
    );
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
    logStoredTaskpaneSnapshot(
      "format.host_context.snapshot",
      "清除预览批注后宿主状态已采集",
      "after_preview_clear",
      requestContext,
      { command: "apply" }
    );
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
        logStoredTaskpaneSnapshot(
          "format.host_context.snapshot",
          "旧格式排版事务准备前宿主状态已采集",
          "before_transaction_prepare",
          requestContext,
          { command: "apply" }
        );
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
        logStoredTaskpaneSnapshot(
          "format.host_context.snapshot",
          "排版事务准备前宿主状态已采集",
          "before_transaction_prepare",
          requestContext,
          { command: "apply" }
        );
        log("INFO", "format.transaction.prepare.start", "开始准备排版事务", contextDetails(requestContext));
        prepared = await api(
          "/v1/format/prepare",
          { source_path: sourcePath },
          undefined,
          requestContext
        );
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
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "排版事务准备后宿主状态已采集",
        "after_transaction_prepare",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
      stage = "commit";
      if (legacyUpgrade) {
        log("INFO", "document.upgrade.publish.start", "开始发布升级并排版后的 DOCX", {
          ...contextDetails(requestContext),
          operation_id_short: operationId.slice(0, 12)
        });
      }
      log("INFO", "format.commit.start", "开始提交排版事务", contextDetails(requestContext));
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "排版事务提交前宿主状态已采集",
        "before_commit",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
      await api("/v1/format/commit", { operation_id: operationId }, undefined, requestContext);
      committed = true;
      log("INFO", "format.commit.completed", "排版事务提交完成", contextDetails(requestContext));
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "排版事务提交后宿主状态已采集",
        "after_commit",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
      if (legacyUpgrade) {
        log("INFO", "document.upgrade.publish.completed", "升级并排版后的 DOCX 已发布", {
          ...contextDetails(requestContext),
          operation_id_short: operationId.slice(0, 12)
        });
      }
      stage = "document_reopen";
      log("INFO", "format.document.reopen.start", "开始重新打开文档", contextDetails(requestContext));
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "目标文档打开前宿主状态已采集",
        "before_target_open",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
      log("INFO", "format.document.open_call.start", "开始调用 WPS Documents.Open 重新打开目标文档", {
        ...contextDetails(requestContext), stage: "document_reopen"
      });
      try {
        app.Documents.Open(targetPath);
      } catch (error) {
        log("ERROR", "format.document.open_call.failed", "WPS 文档重新打开调用失败", {
          ...contextDetails(requestContext), error_code: "WPS_DOCUMENT_OPEN_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error("WPS_DOCUMENT_OPEN_FAILED");
      }
      log("INFO", "format.document.open_call.completed", "WPS Documents.Open 调用完成", {
        ...contextDetails(requestContext), stage: "document_reopen"
      });
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "目标文档打开调用后宿主状态已采集",
        "after_target_open_call",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
      await waitForActiveDocument(targetPath, requestContext, "format_reopen");
      log("INFO", "format.document.reopen.completed", "文档重新打开完成", contextDetails(requestContext));
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "目标文档激活后宿主状态已采集",
        "after_target_activated",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
      stage = "bridge_cleanup";
      cleanupFormatBridge(bridgeDocument, bridgePath, requestContext);
      bridgeDocument = null;
      bridgePath = "";
      stage = "finalize";
      log("INFO", "format.finalize.start", "开始完成排版事务", contextDetails(requestContext));
      await api("/v1/format/finalize", { operation_id: operationId }, undefined, requestContext);
      log("INFO", "format.finalize.completed", "排版事务已完成", contextDetails(requestContext));
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "排版事务完成后宿主状态已采集",
        "after_finalize",
        requestContext,
        { command: "apply", operation_id_short: operationId.slice(0, 12) }
      );
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
      logStoredTaskpaneSnapshot(
        "format.host_context.snapshot",
        "一键排版完成时宿主状态已采集",
        "format_completed",
        requestContext,
        { command: "apply" }
      );
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

  function completeTaskpaneRequest(requestContext, status, errorCode, durationMs) {
    if (!requestContext || requestContext.source !== "taskpane") return;
    writeState({ active_request: Object.assign({}, contextDetails(requestContext), {
      request_id: requestContext.request_id, command: requestContext.command, request_status: status,
      error_code: errorCode || "", duration_ms: durationMs
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
      if (name === "panel_ready") await runPanelReady(requestContext);
      else if (name === "preview") await runPreview(requestContext, documentContext);
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
      completeTaskpaneRequest(requestContext, "PASS", "", Date.now() - startedAt);
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
          request_status: "FAIL", error_code: code, duration_ms: Date.now() - startedAt
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
      if (name !== "panel_ready") {
        try {
          openTaskpane(requestContext);
        } catch (panelError) {
          log("ERROR", "host.command.failure_panel_open.failed", "命令失败后任务窗格打开失败", {
            ...contextDetails(requestContext), command: name, primary_error_code: code,
            error_code: stableErrorCode(panelError, "WPS_TASKPANE_OPEN_FAILED"),
            error_type: panelError && panelError.name ? panelError.name : "Error"
          });
        }
      }
      throw new Error(code);
    } finally {
      let flushError = "";
      try {
        await flushStatePublication();
      } catch (error) {
        flushError = stableErrorCode(error, "WPS_BRIDGE_STATE_FLUSH_FAILED");
        log("ERROR", "host.bridge.state.flush_failed", "命令最终状态发布失败", {
          ...contextDetails(requestContext), command: name, error_code: flushError,
          error_type: error && error.name ? error.name : "Error"
        });
      }
      busy = false;
      try {
        if (ribbonUI && typeof ribbonUI.Invalidate === "function") ribbonUI.Invalidate();
      } catch (error) {
        log("WARNING", "ribbon.invalidate.failed", "Ribbon 状态刷新失败", {
          ...contextDetails(requestContext), command: name,
          error_code: "WPS_RIBBON_INVALIDATE_FAILED",
          error_type: error && error.name ? error.name : "Error"
        });
      }
      if (flushError) throw new Error(flushError);
    }
  }

  async function runBridgeCommand(command) {
    if (!command || command.schema_version !== "wps-command-v2") {
      log("ERROR", "host.bridge.command.schema_invalid", "通信桥命令协议无效", {
        error_code: "WPS_BRIDGE_COMMAND_SCHEMA_INVALID"
      });
      throw new Error("WPS_BRIDGE_COMMAND_SCHEMA_INVALID");
    }
    if (!command.request_id) {
      log("ERROR", "host.bridge.command.request_id_missing", "通信桥命令缺少请求 ID", {
        command: command.command || "", error_code: "WPS_REQUEST_ID_MISSING"
      });
      throw new Error("WPS_REQUEST_ID_MISSING");
    }
    if (!command.command) {
      log("ERROR", "host.bridge.command.command_missing", "通信桥命令缺少命令名称", {
        request_id: command.request_id, error_code: "WPS_REQUEST_COMMAND_MISSING"
      });
      throw new Error("WPS_REQUEST_COMMAND_MISSING");
    }
    let authorization = null;
    if (command.command === "apply") {
      authorization = command.authorization;
      if (!authorization || authorization.request_id !== command.request_id) {
        log("ERROR", "host.bridge.command.authorization_invalid", "一键排版命令缺少有效公网授权", {
          request_id: command.request_id, command: command.command,
          error_code: "WPS_APPLY_AUTHORIZATION_INVALID"
        });
        throw new Error("WPS_APPLY_AUTHORIZATION_INVALID");
      }
      if (!authorization.config_version) {
        log("ERROR", "host.bridge.command.config_version_invalid", "一键排版命令缺少服务器配置版本", {
          request_id: command.request_id, command: command.command,
          error_code: "WPS_APPLY_CONFIG_VERSION_REQUIRED"
        });
        throw new Error("WPS_APPLY_CONFIG_VERSION_REQUIRED");
      }
    }
    if (command.request_id === lastRequestId) {
      log("ERROR", "host.bridge.command.duplicate", "通信桥返回了重复命令", {
        request_id: command.request_id, command: command.command,
        command_sequence: command.command_sequence,
        error_code: "WPS_BRIDGE_COMMAND_DUPLICATE"
      });
      throw new Error("WPS_BRIDGE_COMMAND_DUPLICATE");
    }
    const requestContext = Object.freeze({
      request_id: command.request_id, command: command.command, source: "taskpane",
      document_name: activeDocumentName(),
      config_version: authorization ? authorization.config_version : ""
    });
    lastRequestId = command.request_id;
    writeState({ active_request: Object.assign({}, contextDetails(requestContext), {
      request_id: requestContext.request_id, command: requestContext.command,
      request_status: "CLAIMED", error_code: ""
    }) });
    await flushStatePublication();
    log("INFO", "host.bridge.command.received", "Host 已收到通信桥命令", {
      ...contextDetails(requestContext), command: requestContext.command,
      command_sequence: command.command_sequence, host_generation: hostGeneration
    });
    try {
      await runCommand(requestContext.command, requestContext);
    } catch (_) {
      // runCommand records and publishes the operation-specific failure.
    } finally {
      log("INFO", "taskpane.request.completed", "任务窗格请求处理结束", {
        ...contextDetails(requestContext), command: requestContext.command
      });
    }
  }

  async function runBridgeWaitLoop() {
    log("INFO", "host.bridge.wait.started", "Host 命令长请求已启动", {
      host_generation: hostGeneration, bridge_ready: true
    });
    while (bridgeRunning) {
      let result;
      try {
        result = await bridgeApi("/v1/bridge/host/wait", {
          host_context_id: hostContextId,
          host_generation: hostGeneration,
          timeout_seconds: 25
        }, null);
      } catch (error) {
        const errorCode = stableErrorCode(error, "WPS_BRIDGE_HOST_WAIT_FAILED");
        log("ERROR", "host.bridge.wait.failed", "Host 命令长请求失败", {
          host_generation: hostGeneration, error_code: errorCode,
          error_type: error && error.name ? error.name : "Error"
        });
        throw new Error(errorCode);
      }
      if (result.timed_out) continue;
      await runBridgeCommand(result.command);
    }
  }

  async function startBridgeSession() {
    let stage = "bridge_register";
    try {
      log("INFO", "host.bridge.register.start", "开始注册 Host 通信上下文", {});
      const registration = await bridgeApi("/v1/bridge/host/register", {
        host_context_id: hostContextId
      }, null);
      hostGeneration = registration.host_generation;
      bridgeRunning = true;
      bridgeReady = true;
      statePublishError = "";
      statePublishChain = Promise.resolve();
      log("INFO", "host.bridge.register.completed", "Host 通信上下文注册完成", {
        host_generation: hostGeneration, state_revision: registration.state_revision,
        replaced: Boolean(registration.replaced), bridge_ready: true
      });
      stage = "state_publish";
      writeState({
        status: "READY", stage: "ready", message: "DocxTool WPS 已就绪",
        host_ready: true, recognition_rows: [], compatibility_warnings: [],
        preview_comment_count: 0, preview_confirmed_count: 0, preview_review_count: 0,
        error_code: "", active_request: null, last_request: null
      });
      await flushStatePublication();
      log("INFO", "host.start.completed", "Host Runtime 启动完成", {
        host_ready: true, host_generation: hostGeneration, bridge_ready: true
      });
      stage = "bridge_wait";
      await runBridgeWaitLoop();
      started = false;
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_HOST_START_FAILED");
      bridgeRunning = false;
      bridgeReady = false;
      started = false;
      log("ERROR", "host.start.rollback", "Host Runtime 启动已回滚", {
        stage, error_code: errorCode, host_generation: hostGeneration
      });
      log("ERROR", "host.start.failed", "Host Runtime 启动失败", {
        stage, error_type: error && error.name ? error.name : "Error",
        error_code: errorCode, host_generation: hostGeneration
      });
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
      started = true;
      stage = "bridge_start";
      void startBridgeSession();
      log("INFO", "host.start.scheduled", "Host Runtime 后台通信已调度", {
        bridge_ready: false
      });
      return "started";
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_HOST_START_FAILED");
      bridgeRunning = false;
      bridgeReady = false;
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
          log("INFO", "host.start.lazy.scheduled", "状态面板已调度 Host Runtime 启动", {
            command: id, state: startResult, bridge_ready: false
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

  function setRibbonUI(value) {
    ribbonUI = value;
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
    getBridgeReady: () => bridgeReady,
    getHostGeneration: () => hostGeneration,
    getInstanceIdShort: () => hostInstanceIdShort,
    getStateSnapshot: () => JSON.parse(JSON.stringify(hostState)),
    setRibbonUI,
    handleRibbonAction,
    getActionEnabled
  });
})();
