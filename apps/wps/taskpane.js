(function () {
  "use strict";

  const app = window.Application;
  const config = window.DocxToolWpsConfig || {};
  const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
  const TASKPANE_VERSION_KEY = "docxtool_wps_taskpane_version_v1";
  const paneInstanceId = `pane-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
  let lastStatus = "";
  let currentState = {};
  let hostGeneration = 0;
  let stateRevision = 0;
  let pendingRequestId = "";
  let pendingRequestedAt = 0;
  let pendingClaimed = false;
  let pendingAckTimedOut = false;
  let logSequence = 0;
  let logTransportFailureReported = false;
  let logTransportUnavailableReported = false;
  let stateWaitStopped = false;
  let stateWaitInFlight = false;
  let lastHeaderLayoutProblem = "";
  let layoutSettled = false;
  let panelReadySubmitted = false;
  let panelReadyCompleted = false;
  let panelReadyRequestId = "";
  let accountApplyAvailable = false;
  let accountPendingResultCount = 0;
  let accountNetworkAvailable = true;
  let accountErrorCode = "";
  let lastAccountStatusKey = "";
  let lastResultSyncPending = "";
  const layoutDiagnosticsStartedAt = Date.now();
  const lifecycleEventCounts = Object.create(null);
  const REQUEST_ACK_TIMEOUT_MS = 5000;
  const PANEL_READY_TERMINAL_TIMEOUT_MS = 30000;
  const LAYOUT_EVENT_LIMIT = 4;
  const LAYOUT_PROBE_DELAYS_MS = [100, 500, 1000];
  const SAFE_DETAIL_FIELDS = new Set([
    "active_element_id", "active_element_tag", "actual_delay_ms", "apply_available", "body_client_height", "body_client_width",
    "body_scroll_height", "body_scroll_top", "body_scroll_width", "command", "content_bottom",
    "content_client_height", "content_client_width", "content_height", "content_scroll_height",
    "content_scroll_top", "content_top", "current_status", "device_pixel_ratio", "document_client_height",
    "document_client_width", "document_has_focus", "document_ready_state",
    "document_scroll_height", "document_scroll_width", "error_code", "error_type", "event_sequence", "header_bottom",
    "header_clipped_top", "header_display", "header_height", "header_offset_top", "header_position",
    "header_top", "header_visibility", "host_ready", "inner_height", "inner_width", "layout_event_count",
    "outer_height", "outer_width", "page_persisted", "page_x_offset", "page_y_offset",
    "pane_instance_id", "pending_present", "previous_status", "readback_present", "reason",
    "request_id", "request_status", "result_sync_error_code", "result_sync_status", "stage", "cause_event", "root_scroll_top", "bridge_ready",
    "command_sequence", "generation_changed", "host_generation",
    "scheduled_delay_ms", "state_revision", "state_wait_in_flight", "state_wait_stopped", "timer_drift_ms",
    "top_element_id", "top_element_tag", "trigger", "visibility_state", "visual_viewport_height",
    "visual_viewport_offset_top", "visual_viewport_page_top", "visual_viewport_width", "wait_timed_out",
    "frame_element_present", "header_offset_height", "header_opacity", "header_overflow",
    "header_transform", "header_z_index", "physical_header_height", "physical_inner_height",
    "network_available", "pending_result_count", "physical_inner_width", "screen_avail_height", "screen_avail_left", "screen_avail_top",
    "screen_avail_width", "screen_height", "screen_width", "window_screen_left",
    "window_screen_top", "window_screen_x", "window_screen_y", "window_top_is_self"
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

  function viewportDetails(stage) {
    return {
      stage,
      root_scroll_top: Number(document.documentElement.scrollTop || 0),
      body_scroll_top: Number(document.body.scrollTop || 0),
      content_scroll_top: Number(node("content").scrollTop || 0)
    };
  }

  function rounded(value) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? Math.round(numeric) : 0;
  }

  function layoutDetails(stage, trigger, extras) {
    const root = document.documentElement;
    const body = document.body;
    const header = node("taskpane_header");
    const content = node("content");
    const headerRect = header.getBoundingClientRect();
    const contentRect = content.getBoundingClientRect();
    const visualViewport = window.visualViewport;
    const screenInfo = window.screen || {};
    const visualTop = visualViewport ? rounded(visualViewport.offsetTop) : 0;
    const activeElement = document.activeElement;
    const topElement = document.elementFromPoint(8, 8);
    const headerStyle = window.getComputedStyle(header);
    return Object.assign({
      stage,
      trigger,
      root_scroll_top: rounded(root.scrollTop),
      body_scroll_top: rounded(body.scrollTop),
      content_scroll_top: rounded(content.scrollTop),
      inner_width: rounded(window.innerWidth),
      inner_height: rounded(window.innerHeight),
      outer_width: rounded(window.outerWidth),
      outer_height: rounded(window.outerHeight),
      window_screen_x: rounded(window.screenX),
      window_screen_y: rounded(window.screenY),
      window_screen_left: rounded(window.screenLeft),
      window_screen_top: rounded(window.screenTop),
      screen_width: rounded(screenInfo.width),
      screen_height: rounded(screenInfo.height),
      screen_avail_width: rounded(screenInfo.availWidth),
      screen_avail_height: rounded(screenInfo.availHeight),
      screen_avail_left: rounded(screenInfo.availLeft),
      screen_avail_top: rounded(screenInfo.availTop),
      window_top_is_self: !window.top || window.top === window,
      frame_element_present: Boolean(window.frameElement),
      page_x_offset: rounded(window.pageXOffset),
      page_y_offset: rounded(window.pageYOffset),
      device_pixel_ratio: Number(window.devicePixelRatio || 1),
      physical_inner_width: rounded(window.innerWidth * Number(window.devicePixelRatio || 1)),
      physical_inner_height: rounded(window.innerHeight * Number(window.devicePixelRatio || 1)),
      visual_viewport_width: visualViewport ? rounded(visualViewport.width) : 0,
      visual_viewport_height: visualViewport ? rounded(visualViewport.height) : 0,
      visual_viewport_offset_top: visualTop,
      visual_viewport_page_top: visualViewport ? rounded(visualViewport.pageTop) : 0,
      document_client_width: rounded(root.clientWidth),
      document_client_height: rounded(root.clientHeight),
      document_scroll_width: rounded(root.scrollWidth),
      document_scroll_height: rounded(root.scrollHeight),
      body_client_width: rounded(body.clientWidth),
      body_client_height: rounded(body.clientHeight),
      body_scroll_width: rounded(body.scrollWidth),
      body_scroll_height: rounded(body.scrollHeight),
      header_top: rounded(headerRect.top),
      header_bottom: rounded(headerRect.bottom),
      header_height: rounded(headerRect.height),
      header_offset_top: rounded(header.offsetTop),
      header_offset_height: rounded(header.offsetHeight),
      header_clipped_top: headerRect.height <= 0 || headerRect.top < visualTop || headerRect.bottom <= visualTop,
      header_display: String(headerStyle.display || ""),
      header_position: String(headerStyle.position || ""),
      header_visibility: String(headerStyle.visibility || ""),
      header_opacity: String(headerStyle.opacity || ""),
      header_overflow: String(headerStyle.overflow || ""),
      header_transform: String(headerStyle.transform || ""),
      header_z_index: String(headerStyle.zIndex || ""),
      physical_header_height: rounded(headerRect.height * Number(window.devicePixelRatio || 1)),
      content_top: rounded(contentRect.top),
      content_bottom: rounded(contentRect.bottom),
      content_height: rounded(contentRect.height),
      content_client_width: rounded(content.clientWidth),
      content_client_height: rounded(content.clientHeight),
      content_scroll_height: rounded(content.scrollHeight),
      document_ready_state: String(document.readyState || ""),
      visibility_state: String(document.visibilityState || ""),
      document_has_focus: Boolean(document.hasFocus()),
      active_element_id: activeElement && activeElement.id ? String(activeElement.id) : "",
      active_element_tag: activeElement && activeElement.tagName ? String(activeElement.tagName) : "",
      top_element_id: topElement && topElement.id ? String(topElement.id) : "",
      top_element_tag: topElement && topElement.tagName ? String(topElement.tagName) : "",
      state_wait_in_flight: stateWaitInFlight,
      state_wait_stopped: stateWaitStopped
    }, extras || {});
  }

  function logHeaderLayoutProblem(details) {
    const currentProblem = details.header_height <= 0
      ? "zero_height"
      : details.header_clipped_top
        ? "clipped_top"
        : "";
    if (currentProblem === lastHeaderLayoutProblem) return;
    if (!currentProblem) {
      if (lastHeaderLayoutProblem) {
        log("INFO", "taskpane.layout.header_recovered", "任务窗格顶部区域恢复到可视范围", Object.assign({}, details, {
          previous_status: lastHeaderLayoutProblem
        }));
      }
      lastHeaderLayoutProblem = "";
      return;
    }
    lastHeaderLayoutProblem = currentProblem;
    if (currentProblem === "zero_height") {
      log("WARNING", "taskpane.layout.header_zero_height", "任务窗格顶部区域高度为零", Object.assign({}, details, {
        error_code: "WPS_TASKPANE_HEADER_ZERO_HEIGHT"
      }));
      return;
    }
    log("WARNING", "taskpane.layout.header_clipped", "任务窗格顶部区域位于宿主可视范围之外", Object.assign({}, details, {
      error_code: "WPS_TASKPANE_HEADER_CLIPPED"
    }));
  }

  function logLayoutEvent(event, message, stage, trigger, extras) {
    const details = layoutDetails(stage, trigger, extras);
    log("INFO", event, message, details);
    logHeaderLayoutProblem(details);
  }

  function logLifecycleEvent(name, event) {
    const count = (lifecycleEventCounts[name] || 0) + 1;
    lifecycleEventCounts[name] = count;
    if (count > LAYOUT_EVENT_LIMIT) return;
    logLayoutEvent(`taskpane.lifecycle.${name}`, `任务窗格生命周期事件：${name}`, name, "lifecycle", {
      layout_event_count: count,
      page_persisted: Boolean(event && event.persisted)
    });
  }

  function installLayoutDiagnostics() {
    logLayoutEvent("taskpane.layout.snapshot", "任务窗格初始布局快照已采集", "initial", "initialize");
    if (document.readyState === "loading") {
      document.addEventListener("DOMContentLoaded", (event) => logLifecycleEvent("dom_content_loaded", event), { once: true });
    }
    ["focus", "blur", "resize", "pageshow", "pagehide", "scroll"].forEach((name) => {
      window.addEventListener(name, (event) => logLifecycleEvent(name, event));
    });
    document.addEventListener("visibilitychange", (event) => logLifecycleEvent("visibility_change", event));
    node("content").addEventListener("scroll", (event) => logLifecycleEvent("content_scroll", event));
    LAYOUT_PROBE_DELAYS_MS.forEach((delay) => {
      setTimeout(() => {
        const actualDelay = Date.now() - layoutDiagnosticsStartedAt;
        logLayoutEvent("taskpane.event_loop.probe", "任务窗格事件循环探针已执行", `settled_${delay}ms`, "timer", {
          scheduled_delay_ms: delay,
          actual_delay_ms: actualDelay,
          timer_drift_ms: Math.max(0, actualDelay - delay)
        });
      }, delay);
    });
  }

  function resetViewport(stage) {
    const before = viewportDetails(stage);
    log("INFO", "taskpane.viewport.reset.start", "开始重置任务窗格滚动位置", before);
    try {
      window.scrollTo(0, 0);
      document.documentElement.scrollTop = 0;
      document.body.scrollTop = 0;
      node("content").scrollTop = 0;
    } catch (error) {
      log("ERROR", "taskpane.viewport.reset.failed", "任务窗格初始滚动位置重置失败", {
        ...before,
        error_code: "WPS_TASKPANE_VIEWPORT_RESET_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_TASKPANE_VIEWPORT_RESET_FAILED");
    }
    log("INFO", "taskpane.viewport.reset.completed", "任务窗格滚动位置已重置", viewportDetails(stage));
  }

  function scheduleSettledViewportReset() {
    const resetAfterLoad = (event) => {
      logLifecycleEvent("load", event);
      setTimeout(() => {
        resetViewport("load_settled");
        logLayoutEvent("taskpane.layout.snapshot", "任务窗格加载稳定后的布局快照已采集", "load_settled", "load_timer");
        layoutSettled = true;
        void maybeSubmitPanelReady();
      }, 0);
    };
    try {
      if (document.readyState === "complete") resetAfterLoad();
      else window.addEventListener("load", resetAfterLoad, { once: true });
    } catch (error) {
      log("ERROR", "taskpane.viewport.schedule.failed", "任务窗格加载后滚动重置调度失败", {
        error_code: "WPS_TASKPANE_VIEWPORT_SCHEDULE_FAILED",
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error("WPS_TASKPANE_VIEWPORT_SCHEDULE_FAILED");
    }
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

  async function bridgeApi(path, body, requestId) {
    if (!config.controlBaseUrl || !config.sessionToken) throw new Error("WPS_CONTROL_NOT_CONFIGURED");
    const response = await fetch(`${config.controlBaseUrl}${path}`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${config.sessionToken}`,
        "X-DocxTool-Request-Id": requestId || ""
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

  function renderAccountStatus(account) {
    if (!account || typeof account !== "object") throw new Error("WPS_ACCOUNT_STATUS_MISSING");
    if (!Number.isInteger(account.pending_result_count) || account.pending_result_count < 0) {
      throw new Error("WPS_ACCOUNT_PENDING_RESULT_COUNT_INVALID");
    }
    accountApplyAvailable = account.apply_available === true;
    accountPendingResultCount = account.pending_result_count;
    accountNetworkAvailable = account.network_available === true;
    accountErrorCode = account.error_code || "";
    node("account").textContent = account.signed_in
      ? `${account.username || "当前账号"}${account.network_available ? "" : " · 服务器离线"}`
      : "未登录";
    if (!accountApplyAvailable) node("apply").disabled = true;
    else if (currentState.host_ready === true && panelReadyCompleted && !pendingRequestId) node("apply").disabled = false;
    const statusKey = [
      account.signed_in === true,
      accountApplyAvailable,
      account.network_available === true,
      accountPendingResultCount,
      account.error_code || ""
    ].join(":");
    if (statusKey === lastAccountStatusKey) return;
    lastAccountStatusKey = statusKey;
    if (account.network_available === false && account.error_code) {
      node("message").textContent = "服务器无法连接。";
      node("error").textContent = displayError(account.error_code);
    }
    log("INFO", "taskpane.account.changed", "任务窗格账号状态已更新", {
      apply_available: accountApplyAvailable,
      network_available: account.network_available === true,
      pending_result_count: accountPendingResultCount,
      error_code: account.error_code || ""
    });
  }

  function setBusinessButtonsDisabled(disabled) {
    ["preview", "apply", "add_letterhead", "clear_preview", "health"].forEach((id) => { node(id).disabled = Boolean(disabled); });
    if (!disabled && !accountApplyAvailable) node("apply").disabled = true;
  }

  function requestedFormatScope(commandName) {
    if (commandName !== "apply" || node("format_scope_mode").value === "whole") {
      return null;
    }
    const pageSpec = node("format_page_spec").value.trim();
    if (!pageSpec) throw new Error("WPS_FORMAT_PAGE_SPEC_INVALID");
    return { mode: "pre_format_pages", page_spec: pageSpec };
  }

  async function request(commandName, requestedId, commandPayload) {
    const state = currentState;
    if (pendingRequestId) {
      node("message").textContent = "命令正在处理中。";
      node("error").textContent = displayError("WPS_COMMAND_BUSY");
      log("WARNING", "taskpane.request.blocked.busy", "任务窗格请求被忙碌状态阻止", Object.assign(contextDetails(state), {
        command: commandName, reason: "pending_request", request_status: "BLOCKED",
        pending_present: true,
        error_code: "WPS_COMMAND_BUSY"
      }));
      return;
    }
    if (state.host_ready !== true || !hostGeneration) {
      node("message").textContent = "WPS Host 尚未就绪，请重启 WPS。";
      node("error").textContent = displayError("WPS_HOST_NOT_READY");
      log("WARNING", "taskpane.request.blocked.host_not_ready", "任务窗格请求因 Host 未就绪被阻止", Object.assign(contextDetails(state), {
        command: commandName, reason: "host_not_ready", request_status: "BLOCKED",
        pending_present: false, host_generation: hostGeneration,
        error_code: "WPS_HOST_NOT_READY"
      }));
      return;
    }
    const requestId = requestedId || `pane-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
    log("INFO", "taskpane.request.prepare", "开始准备任务窗格请求", {
      request_id: requestId, command: commandName, pane_instance_id: paneInstanceId
    });
    logLayoutEvent(
      "taskpane.command.layout.snapshot",
      "任务窗格命令准备时布局快照已采集",
      "request_prepare",
      "command",
      {
        request_id: requestId,
        command: commandName,
        pane_instance_id: paneInstanceId,
        host_generation: hostGeneration,
        current_status: state.status || ""
      }
    );
    pendingRequestId = requestId;
    pendingRequestedAt = Date.now();
    pendingClaimed = false;
    pendingAckTimedOut = false;
    setBusinessButtonsDisabled(true);
    node("message").textContent = "命令已发送，等待 WPS 主上下文处理…";
    log("INFO", "taskpane.bridge.command.submit.start", "开始向通信桥提交命令", {
      request_id: requestId, command: commandName, pane_instance_id: paneInstanceId,
      host_generation: hostGeneration
    });
    try {
      const formatScope = requestedFormatScope(commandName);
      const result = await bridgeApi("/v1/bridge/command", {
        request_id: requestId,
        command: commandName,
        pane_instance_id: paneInstanceId,
        host_generation: hostGeneration,
        format_scope: formatScope,
        letterhead: commandName === "add_letterhead" ? commandPayload : null
      }, requestId);
      log("INFO", "taskpane.bridge.command.submit.completed", "任务窗格命令已提交", {
        request_id: requestId, command: commandName,
        command_sequence: result.command_sequence, host_generation: hostGeneration,
        state_revision: result.state_revision
      });
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_BRIDGE_COMMAND_SUBMIT_FAILED");
      pendingRequestId = "";
      pendingRequestedAt = 0;
      pendingClaimed = false;
      pendingAckTimedOut = false;
      setBusinessButtonsDisabled(state.host_ready !== true || !panelReadyCompleted);
      log("ERROR", "taskpane.bridge.command.submit.failed", "任务窗格命令提交失败", {
        request_id: requestId, command: commandName, host_generation: hostGeneration,
        error_code: errorCode,
        error_type: error && error.name ? error.name : "Error"
      });
      throw new Error(errorCode);
    }
    return requestId;
  }

  function openLetterheadForm() {
    node("letterhead_form_error").textContent = "";
    node("letterhead_modal").hidden = false;
    node("letterhead_mark").focus();
    void request("inspect_letterhead").then(() => {
      node("letterhead_modal").hidden = false;
      node("letterhead_mark").focus();
    }).catch((error) => {
      const code = stableErrorCode(error, "WPS_LETTERHEAD_INSPECT_FAILED");
      const message = code === "WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED"
        ? "当前只支持单机关发文版头，未修改文档。"
        : "无法读取当前版头。";
      node("letterhead_form_error").textContent = `${message} ${displayError(code)}`;
    });
  }

  function closeLetterheadForm() {
    node("letterhead_modal").hidden = true;
    node("letterhead_form_error").textContent = "";
  }

  function letterheadPayload(replaceExisting) {
    const markText = node("letterhead_mark").value.trim();
    if (!markText) throw new Error("WPS_LETTERHEAD_MARK_REQUIRED");
    const documentNumber = node("letterhead_number").value.trim();
    if (!/^[^\s，。；：:（）()《》“”〔〕]{1,40}〔\d{4}〕\d{1,6}号$/.test(documentNumber)) {
      throw new Error("WPS_LETTERHEAD_DOCUMENT_NUMBER_INVALID");
    }
    return {
      mark_text: markText,
      document_number: documentNumber,
      signer: node("letterhead_signer").value.trim(),
      separator_style: node("letterhead_separator").value,
      replace_existing: Boolean(replaceExisting)
    };
  }

  async function submitLetterhead(replaceExisting) {
    const payload = letterheadPayload(replaceExisting);
    const inspection = currentState.letterhead_inspection || {};
    if (!replaceExisting && inspection.exists === true) {
      if (inspection.replaceable !== true) {
        const error = new Error("WPS_LETTERHEAD_EXISTING_AMBIGUOUS");
        node("letterhead_form_error").textContent = `无法确定现有版头边界，未修改文档。 ${displayError(error.message)}`;
        throw error;
      }
      if (!window.confirm("当前文档已存在版头，是否使用当前填写内容替换？")) {
        node("letterhead_form_error").textContent = "已取消替换，文档未修改。";
        return;
      }
      return submitLetterhead(true);
    }
    try {
      await request("add_letterhead", undefined, payload);
      node("letterhead_modal").hidden = true;
    } catch (error) {
      const code = stableErrorCode(error, "WPS_LETTERHEAD_ADD_FAILED");
      if (code === "WPS_LETTERHEAD_ALREADY_EXISTS" && !replaceExisting) {
        const confirmed = window.confirm("当前文档已存在版头，是否使用当前填写内容替换？");
        if (confirmed) return submitLetterhead(true);
        node("letterhead_form_error").textContent = "已取消替换，文档未修改。";
        return;
      }
      const messages = {
        WPS_LETTERHEAD_MARK_REQUIRED: "请输入发文机关标志。",
        WPS_LETTERHEAD_DOCUMENT_NUMBER_INVALID: "发文字号格式应为：机关代字〔四位年份〕顺序号号。",
        WPS_LETTERHEAD_EXISTING_AMBIGUOUS: "无法确定现有版头边界，未修改文档。",
        WPS_LETTERHEAD_MARK_TOO_LONG: "发文机关标志过长，无法在版心内排下。",
        WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED: "当前只支持单机关发文版头，未修改文档。"
      };
      node("letterhead_form_error").textContent = `${messages[code] || "版头添加失败。"}${displayError(code) ? ` ${displayError(code)}` : ""}`;
      throw error;
    }
  }

  async function maybeSubmitPanelReady() {
    if (panelReadySubmitted || !layoutSettled || currentState.host_ready !== true || !hostGeneration) return;
    panelReadySubmitted = true;
    panelReadyRequestId = `panel-ready-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
    setBusinessButtonsDisabled(true);
    log("INFO", "taskpane.panel_ready.submit.start", "任务窗格已稳定加载，开始请求 WPS 工作区重算", {
      request_id: panelReadyRequestId, command: "panel_ready",
      pane_instance_id: paneInstanceId, host_generation: hostGeneration,
      stage: "load_settled"
    });
    logLayoutEvent(
      "taskpane.panel_ready.layout.snapshot",
      "WPS 工作区重算请求前布局快照已采集",
      "panel_ready_before",
      "panel_ready",
      {
        request_id: panelReadyRequestId,
        command: "panel_ready",
        pane_instance_id: paneInstanceId,
        host_generation: hostGeneration
      }
    );
    try {
      await request("panel_ready", panelReadyRequestId);
      log("INFO", "taskpane.panel_ready.submit.completed", "WPS 工作区重算请求已提交", {
        request_id: panelReadyRequestId, command: "panel_ready",
        pane_instance_id: paneInstanceId, host_generation: hostGeneration
      });
    } catch (error) {
      const errorCode = stableErrorCode(error, "WPS_PANEL_READY_SUBMIT_FAILED");
      setBusinessButtonsDisabled(true);
      node("message").textContent = "任务窗格工作区重算失败，请重新打开状态面板。";
      node("error").textContent = displayError(errorCode);
      log("ERROR", "taskpane.panel_ready.submit.failed", "WPS 工作区重算请求提交失败", {
        request_id: panelReadyRequestId, command: "panel_ready",
        pane_instance_id: paneInstanceId, host_generation: hostGeneration,
        error_code: errorCode,
        error_type: error && error.name ? error.name : "Error"
      });
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

  function displayStatus(value) {
    const statuses = {
      CONNECTING: "连接中",
      NOT_READY: "未就绪",
      READY: "就绪",
      CLAIMED: "已领取",
      RUNNING: "处理中",
      PASS: "成功",
      FAIL: "失败",
      ERROR: "错误"
    };
    return statuses[String(value || "").toUpperCase()] || "未知状态";
  }

  function displayError(code) {
    return code ? `错误代码：${String(code)}` : "";
  }

  function displayDocumentMode(value) {
    const modes = {
      UNKNOWN: "未知",
      NORMAL: "普通公文",
      REPORT: "报告",
      NOTICE: "通知",
      PLAN: "方案",
      MEETING_MINUTES: "会议纪要"
    };
    return modes[String(value || "").toUpperCase()] || "未知";
  }

  function prepareTaskpaneRecovery(errorCode) {
    try {
      storage().setItem(TASKPANE_KEY, "");
      storage().setItem(TASKPANE_VERSION_KEY, "");
      log("INFO", "taskpane.bridge.state.wait.recovery_prepared", "任务窗格失效标识已清除，下次将重建状态面板", {
        pane_instance_id: paneInstanceId, error_code: errorCode
      });
    } catch (storageError) {
      log("ERROR", "taskpane.bridge.state.wait.recovery_failed", "任务窗格失效标识清除失败", {
        pane_instance_id: paneInstanceId,
        error_code: stableErrorCode(storageError, "WPS_TASKPANE_RECOVERY_STORAGE_FAILED"),
        error_type: storageError && storageError.name ? storageError.name : "Error"
      });
    }
  }

  function stopPanelReadyTerminalWait() {
    const requestId = pendingRequestId;
    const errorCode = "WPS_PANEL_READY_TERMINAL_TIMEOUT";
    stateWaitStopped = true;
    pendingRequestId = "";
    pendingRequestedAt = 0;
    pendingClaimed = false;
    pendingAckTimedOut = false;
    setBusinessButtonsDisabled(true);
    node("status").textContent = displayStatus("ERROR");
    node("message").textContent = "工作区重算未返回最终状态，请重启 WPS 后重新打开状态面板。";
    node("error").textContent = displayError(errorCode);
    log("ERROR", "taskpane.panel_ready.terminal_timeout", "任务窗格工作区重算终态等待超时", {
      request_id: requestId, command: "panel_ready", pane_instance_id: paneInstanceId,
      host_generation: hostGeneration, error_code: errorCode
    });
    prepareTaskpaneRecovery(errorCode);
    log("ERROR", "taskpane.bridge.state.wait.stopped", "任务窗格状态长请求已停止", {
      pane_instance_id: paneInstanceId, host_generation: hostGeneration,
      state_revision: stateRevision,
      cause_event: "taskpane.panel_ready.terminal_timeout",
      error_code: errorCode
    });
  }

  function updatePendingRequest(state) {
    if (!pendingRequestId) return false;
    const active = [state.active_request, state.last_request].find((item) => item && item.request_id === pendingRequestId) || {};
    if (active.request_id === pendingRequestId && ["CLAIMED", "RUNNING"].includes(active.request_status) && !pendingClaimed) {
      pendingClaimed = true;
      pendingAckTimedOut = false;
      log("INFO", "taskpane.request.claimed", "任务窗格请求已被 Host 领取", { request_id: pendingRequestId, request_status: active.request_status });
      logLayoutEvent(
        "taskpane.command.layout.snapshot",
        "Host 领取命令时任务窗格布局快照已采集",
        "request_claimed",
        "state_change",
        {
          request_id: pendingRequestId,
          command: active.command || "",
          request_status: active.request_status,
          pane_instance_id: paneInstanceId
        }
      );
    }
    if (active.request_id === pendingRequestId && ["PASS", "FAIL"].includes(active.request_status)) {
      const completedRequestId = pendingRequestId;
      const panelReadyRequest = active.command === "panel_ready" && completedRequestId === panelReadyRequestId;
      if (panelReadyRequest) {
        panelReadyCompleted = active.request_status === "PASS";
        log(
          panelReadyCompleted ? "INFO" : "ERROR",
          panelReadyCompleted ? "taskpane.panel_ready.completed" : "taskpane.panel_ready.failed",
          panelReadyCompleted ? "任务窗格工作区重算已完成" : "任务窗格工作区重算失败",
          {
            request_id: completedRequestId,
            command: "panel_ready",
            pane_instance_id: paneInstanceId,
            host_generation: hostGeneration,
            request_status: active.request_status,
            error_code: active.error_code || ""
          }
        );
        logLayoutEvent(
          "taskpane.panel_ready.layout.snapshot",
          "WPS 工作区重算完成后的布局快照已采集",
          "panel_ready_after",
          "panel_ready",
          {
            request_id: completedRequestId,
            command: "panel_ready",
            pane_instance_id: paneInstanceId,
            host_generation: hostGeneration,
            request_status: active.request_status
          }
        );
      }
      log("INFO", "taskpane.request.completed", "任务窗格请求已完成", { request_id: pendingRequestId, request_status: active.request_status });
      if (active.command === "inspect_letterhead" && active.request_status === "PASS") {
        const inspection = state.letterhead_inspection || {};
        const fields = inspection.fields;
        if (fields && typeof fields === "object") {
          node("letterhead_mark").value = fields.mark_text || "";
          node("letterhead_number").value = fields.document_number || "";
          node("letterhead_signer").value = fields.signer || "";
          node("letterhead_separator").value = fields.separator_style || "straight";
        }
      }
      if (active.command === "inspect_letterhead" && active.request_status === "FAIL") {
        const code = active.error_code || "WPS_LETTERHEAD_INSPECT_FAILED";
        const message = code === "WPS_LETTERHEAD_JOINT_SOURCE_UNSUPPORTED"
          ? "当前只支持单机关发文版头，未修改文档。"
          : "无法读取当前版头。";
        node("letterhead_form_error").textContent = `${message} ${displayError(code)}`;
      }
      if (active.command === "add_letterhead") {
        if (active.request_status === "FAIL") {
          const code = active.error_code || "WPS_LETTERHEAD_ADD_FAILED";
          node("letterhead_modal").hidden = false;
          node("letterhead_form_error").textContent = `版头添加失败。 ${displayError(code)}`;
        } else {
          node("letterhead_modal").hidden = true;
          node("letterhead_form_error").textContent = "";
        }
      }
      logLayoutEvent(
        "taskpane.command.layout.snapshot",
        "命令完成时任务窗格布局快照已采集",
        "request_completed",
        "state_change",
        {
          request_id: pendingRequestId,
          command: active.command || "",
          request_status: active.request_status,
          pane_instance_id: paneInstanceId
        }
      );
      pendingRequestId = "";
      pendingRequestedAt = 0;
      pendingClaimed = false;
      pendingAckTimedOut = false;
      setBusinessButtonsDisabled(!panelReadyCompleted);
      if (active.command === "inspect_letterhead") {
        node("letterhead_modal").hidden = false;
        node("letterhead_mark").focus();
      }
      return false;
    }
    const elapsed = pendingRequestedAt ? Date.now() - pendingRequestedAt : 0;
    if (
      pendingRequestId === panelReadyRequestId
      && elapsed >= PANEL_READY_TERMINAL_TIMEOUT_MS
    ) {
      stopPanelReadyTerminalWait();
      return true;
    }
    if (!pendingClaimed && !pendingAckTimedOut && elapsed >= REQUEST_ACK_TIMEOUT_MS) {
      node("error").textContent = displayError("WPS_REQUEST_ACK_TIMEOUT");
      log("WARNING", "taskpane.request.timeout", "任务窗格请求领取超时", { request_id: pendingRequestId, error_code: "WPS_REQUEST_ACK_TIMEOUT" });
      pendingAckTimedOut = true;
      if (pendingRequestId !== panelReadyRequestId) {
        pendingRequestId = "";
        pendingRequestedAt = 0;
        pendingClaimed = false;
        pendingAckTimedOut = false;
        setBusinessButtonsDisabled(!panelReadyCompleted);
      }
    }
    return false;
  }

  function render(state) {
    if (updatePendingRequest(state)) return;
    if (state.host_ready !== true) {
      node("status").textContent = displayStatus("NOT_READY");
      node("message").textContent = "WPS Host 尚未就绪，请重启 WPS。";
      node("error").textContent = displayError(state.error_code || "");
      node("summary").textContent = "尚未识别。";
      node("warnings").textContent = "";
      node("rows").replaceChildren();
      setBusinessButtonsDisabled(true);
      log("WARNING", "taskpane.host.not_ready", "任务窗格检测到 Host 尚未就绪", Object.assign(contextDetails(state), {
        reason: "host_not_ready", error_code: "WPS_HOST_NOT_READY"
      }));
      return;
    }
    setBusinessButtonsDisabled(Boolean(pendingRequestId) || !panelReadyCompleted);
    const currentStatus = state.status || "READY";
    if (currentStatus !== lastStatus) {
      log("INFO", "taskpane.state.changed", "任务窗格状态已变化", {
        pane_instance_id: paneInstanceId, previous_status: lastStatus, current_status: currentStatus,
        stage: state.stage || ""
      });
      const activeRequest = state.active_request || state.last_request || {};
      logLayoutEvent(
        "taskpane.state.layout.snapshot",
        "任务窗格状态变化时布局快照已采集",
        state.stage || "state_changed",
        "state_change",
        {
          pane_instance_id: paneInstanceId,
          previous_status: lastStatus,
          current_status: currentStatus,
          request_id: activeRequest.request_id || "",
          command: activeRequest.command || "",
          request_status: activeRequest.request_status || ""
        }
      );
      lastStatus = currentStatus;
    }
    node("status").textContent = displayStatus(currentStatus);
    const waitingForLatePanelReady = pendingRequestId === panelReadyRequestId && pendingAckTimedOut;
    node("message").textContent = waitingForLatePanelReady
      ? "WPS 尚未领取工作区重算请求，继续等待最终状态…"
      : !accountNetworkAvailable && accountErrorCode
        ? "服务器无法连接。"
        : state.message || "就绪";
    node("error").textContent = displayError(
      waitingForLatePanelReady
        ? "WPS_REQUEST_ACK_TIMEOUT"
        : !accountNetworkAvailable && accountErrorCode
          ? accountErrorCode
          : state.error_code || ""
    );
    const warnings = Array.isArray(state.compatibility_warnings) ? state.compatibility_warnings.map(formatWarning) : [];
    if (state.result_sync_status === "pending" && accountPendingResultCount > 0) {
      warnings.unshift("排版已完成，结果尚未同步");
      const pendingKey = `${(state.active_request || state.last_request || {}).request_id || ""}:${accountPendingResultCount}`;
      if (pendingKey !== lastResultSyncPending) {
        lastResultSyncPending = pendingKey;
        log("WARNING", "taskpane.result.sync.pending", "排版已完成，结果正在等待公网补报", {
          request_id: (state.active_request || state.last_request || {}).request_id || "",
          result_sync_status: state.result_sync_status,
          pending_result_count: accountPendingResultCount
        });
      }
    } else {
      lastResultSyncPending = "";
    }
    node("warnings").textContent = warnings.length ? `提示：${warnings.join("；")}` : "";
    const recognition = state.recognition;
    if (!recognition) {
      node("summary").textContent = "尚未识别。";
      node("rows").replaceChildren();
      return;
    }
    node("summary").textContent = `文档模式 ${displayDocumentMode(recognition.document_mode)}；识别 ${recognition.block_count || 0} 项；批注 ${state.preview_comment_count || 0}；确认 ${state.preview_confirmed_count || 0}；复核 ${state.preview_review_count || 0}；未定位 ${recognition.unresolved_count || 0}`;
    const rows = Array.isArray(state.recognition_rows) ? state.recognition_rows : [];
    node("rows").replaceChildren(...rows.map((item) => {
      const row = document.createElement("div");
      row.className = "row";
      const paragraph = Number.isInteger(item.paragraph_index) ? `段落 ${item.paragraph_index + 1}` : "结构项";
      const confidence = Math.round(Number(item.confidence || 0) * 100);
      const binding = item.binding_status === "confirmed" ? "已确认" : item.binding_status === "review" ? "需复核" : "未定位";
      row.textContent = `${paragraph} · ${item.role_name || "未知"} · ${confidence}% · ${binding}${item.review_level === "review" || item.review_level === "critical_review" ? " · 识别建议复核" : ""}`;
      return row;
    }));
  }

  function stopStateWait(error) {
    if (stateWaitStopped) return;
    stateWaitStopped = true;
    const errorCode = stableErrorCode(error, "WPS_BRIDGE_STATE_WAIT_FAILED");
    setBusinessButtonsDisabled(true);
    node("status").textContent = displayStatus("ERROR");
    node("message").textContent = "任务窗格状态通道不可用，请重新打开状态面板。";
    node("error").textContent = displayError(errorCode);
    prepareTaskpaneRecovery(errorCode);
    log("ERROR", "taskpane.bridge.state.wait.failed", "任务窗格状态长请求失败", {
      pane_instance_id: paneInstanceId, host_generation: hostGeneration,
      state_revision: stateRevision,
      error_code: errorCode,
      error_type: error && error.name ? error.name : "Error"
    });
    log("ERROR", "taskpane.bridge.state.wait.stopped", "任务窗格状态长请求已停止", {
      pane_instance_id: paneInstanceId, host_generation: hostGeneration,
      state_revision: stateRevision,
      cause_event: "taskpane.bridge.state.wait.failed",
      error_code: errorCode
    });
  }

  function handleHostGenerationChange(result) {
    if (!result.generation_changed) return;
    log("WARNING", "taskpane.bridge.host_generation.changed", "WPS Host 通信上下文已更换", {
      pane_instance_id: paneInstanceId, host_generation: result.host_generation,
      state_revision: result.state_revision, generation_changed: true,
      error_code: "WPS_HOST_CONTEXT_REPLACED"
    });
    panelReadySubmitted = false;
    panelReadyCompleted = false;
    panelReadyRequestId = "";
    setBusinessButtonsDisabled(true);
    if (pendingRequestId) {
      log("WARNING", "taskpane.request.failed.host_replaced", "任务窗格请求因 Host 更换而终止", {
        request_id: pendingRequestId, host_generation: result.host_generation,
        error_code: "WPS_HOST_CONTEXT_REPLACED"
      });
      pendingRequestId = "";
      pendingRequestedAt = 0;
      pendingClaimed = false;
      pendingAckTimedOut = false;
      node("error").textContent = displayError("WPS_HOST_CONTEXT_REPLACED");
    }
  }

  async function waitForStateChanges() {
    let loadedLogged = false;
    log("INFO", "taskpane.bridge.state.wait.started", "任务窗格状态长请求已启动", {
      pane_instance_id: paneInstanceId, host_generation: hostGeneration,
      state_revision: stateRevision, bridge_ready: false
    });
    while (!stateWaitStopped) {
      let result;
      try {
        stateWaitInFlight = true;
        result = await bridgeApi("/v1/bridge/state/wait", {
          after_revision: stateRevision,
          host_generation: hostGeneration,
          timeout_seconds: pendingRequestId && (
            !pendingClaimed || pendingRequestId === panelReadyRequestId
          ) ? 5 : 25
        }, pendingRequestId);
      } catch (error) {
        stateWaitInFlight = false;
        stopStateWait(error);
        return;
      }
      stateWaitInFlight = false;
      if (stateWaitStopped) return;
      try {
        renderAccountStatus(result.account);
      } catch (error) {
        const errorCode = stableErrorCode(error, "WPS_ACCOUNT_STATUS_INVALID");
        log("ERROR", "taskpane.account.state.invalid", "任务窗格收到的账号状态无效", {
          pane_instance_id: paneInstanceId,
          host_generation: hostGeneration,
          state_revision: stateRevision,
          error_code: errorCode,
          error_type: error && error.name ? error.name : "Error"
        });
        stopStateWait(error);
        return;
      }
      if (result.timed_out) {
        render(currentState);
        continue;
      }
      handleHostGenerationChange(result);
      hostGeneration = result.host_generation;
      stateRevision = result.state_revision;
      currentState = result.state || {};
      log("INFO", "taskpane.bridge.state.received", "任务窗格已收到 Host 状态", {
        pane_instance_id: paneInstanceId, host_generation: hostGeneration,
        state_revision: stateRevision, current_status: currentState.status || "",
        stage: currentState.stage || "", generation_changed: Boolean(result.generation_changed)
      });
      render(currentState);
      if (!loadedLogged) {
        loadedLogged = true;
        log("INFO", "taskpane.loaded", "DocxTool WPS 任务窗格已加载", Object.assign(contextDetails(currentState), {
          pane_instance_id: paneInstanceId, pending_present: false,
          host_generation: hostGeneration, state_revision: stateRevision,
          bridge_ready: currentState.host_ready === true
        }));
      }
      void maybeSubmitPanelReady();
    }
  }

  ["preview", "apply", "clear_preview", "health"].forEach((id) => node(id).addEventListener("click", () => {
    logLayoutEvent(
      "taskpane.action.clicked",
      "任务窗格业务按钮已点击",
      "button_click",
      "user_action",
      {
        command: id,
        pane_instance_id: paneInstanceId,
        host_generation: hostGeneration,
        current_status: currentState.status || "",
        pending_present: Boolean(pendingRequestId)
      }
    );
    void request(id).catch((error) => {
      const code = stableErrorCode(error, "WPS_TASKPANE_REQUEST_FAILED");
      node("message").textContent = code === "WPS_PUBLIC_SERVER_UNAVAILABLE"
        ? "服务器无法连接。"
        : code === "WPS_FORMAT_PAGE_SPEC_INVALID"
          ? "请输入有效页码范围。"
          : "命令发送失败。";
      node("error").textContent = displayError(code);
      log("ERROR", "taskpane.request.failed", "任务窗格命令发送失败", {
        command: id, error_code: code,
        error_type: error && error.name ? error.name : "Error"
      });
    });
  }));
  node("add_letterhead").addEventListener("click", openLetterheadForm);
  node("letterhead_cancel").addEventListener("click", closeLetterheadForm);
  node("letterhead_confirm").addEventListener("click", () => {
    node("letterhead_form_error").textContent = "";
    void submitLetterhead(false).catch((error) => {
      const code = stableErrorCode(error, "WPS_LETTERHEAD_ADD_FAILED");
      const messages = {
        WPS_LETTERHEAD_MARK_REQUIRED: "请输入发文机关标志。",
        WPS_LETTERHEAD_DOCUMENT_NUMBER_INVALID: "发文字号格式应为：机关代字〔四位年份〕顺序号号。"
      };
      if (!node("letterhead_form_error").textContent) {
        node("letterhead_form_error").textContent = `${messages[code] || "版头添加失败。"} ${displayError(code)}`;
      }
      log("ERROR", "taskpane.letterhead.submit.failed", "任务窗格版头请求失败", {
        command: "add_letterhead",
        error_code: code,
        error_type: error && error.name ? error.name : "Error"
      });
    });
  });
  node("format_scope_mode").addEventListener("change", () => {
    const pageInput = node("format_page_spec");
    pageInput.disabled = node("format_scope_mode").value !== "pre_format_pages";
    if (!pageInput.disabled) pageInput.focus();
  });
  node("close_panel").addEventListener("click", closePanel);

  try {
    resetViewport("initial");
    installLayoutDiagnostics();
    scheduleSettledViewportReset();
    setBusinessButtonsDisabled(true);
    node("status").textContent = displayStatus("CONNECTING");
    node("message").textContent = "正在连接 WPS Host…";
    window.addEventListener("beforeunload", (event) => {
      logLifecycleEvent("beforeunload", event);
      stateWaitStopped = true;
    }, { once: true });
    window.addEventListener("unload", (event) => logLifecycleEvent("unload", event), { once: true });
    void waitForStateChanges();
  } catch (error) {
    stateWaitStopped = true;
    setBusinessButtonsDisabled(true);
    const errorCode = stableErrorCode(error, "WPS_TASKPANE_LOAD_FAILED");
    node("status").textContent = displayStatus("ERROR");
    node("message").textContent = "任务窗格加载失败，请重新打开状态面板。";
    node("error").textContent = displayError(errorCode);
    log("ERROR", "taskpane.load.failed", "任务窗格初始化失败", {
      pane_instance_id: paneInstanceId,
      error_code: errorCode,
      error_type: error && error.name ? error.name : "Error"
    });
  }
})();
