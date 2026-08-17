import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const HOST_SOURCE = await readFile(
  new URL("../../host-runtime.js", import.meta.url),
  "utf8",
);
const TASKPANE_SOURCE = await readFile(
  new URL("../../taskpane.js", import.meta.url),
  "utf8",
);
const FORMAT_CONFIG_SOURCE = await readFile(
  new URL("../../format-config.js", import.meta.url),
  "utf8",
);
const MAIN_SOURCE = await readFile(new URL("../../main.js", import.meta.url), "utf8");
const RIBBON_SOURCE = await readFile(
  new URL("../../js/ribbon.js", import.meta.url),
  "utf8",
);
const BOOTSTRAP_COMPLETE_SOURCE = await readFile(
  new URL("../../js/bootstrap-complete.js", import.meta.url),
  "utf8",
);

const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";
const TASKPANE_VERSION_KEY = "docxtool_wps_taskpane_version_v1";

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function makeStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  const storage = {
    failGetKey: "",
    failSetKey: "",
    getCalls: [],
    setCalls: [],
    getItem(key) {
      this.getCalls.push(key);
      if (key === this.failGetKey) throw new Error("STORAGE_GET_FAILED");
      return values.get(key) ?? "";
    },
    setItem(key, value) {
      this.setCalls.push(key);
      if (key === this.failSetKey) throw new Error("STORAGE_SET_FAILED");
      values.set(key, String(value));
    },
  };
  return { storage, values };
}

function makeParagraphRange(rawText) {
  const range = {
    Text: `${rawText}\r`,
    Tables: { Count: 0 },
  };
  range.Characters = {
    Item(index) {
      const start = Number(index) - 1;
      return {
        Start: start,
        End: start + 1,
        Text: rawText.slice(start, start + 1),
        SetRange(nextStart, nextEnd) {
          this.Start = nextStart;
          this.End = nextEnd;
          this.Text = rawText.slice(nextStart, nextEnd);
        },
      };
    },
  };
  return range;
}

function makeComments({ failAddAt = 0, failMetadataAt = 0, failDeleteAt = 0 } = {}) {
  const created = [];
  let addCount = 0;
  return {
    created,
    get Count() {
      return created.length;
    },
    Item(index) {
      return created[index - 1];
    },
    Add(range, text) {
      addCount += 1;
      if (failAddAt === addCount) throw new Error("COMMENT_ADD_FAILED");
      let author = "";
      let initial = "";
      const commentIndex = addCount;
      const comment = {
        get Author() { return author; },
        set Author(value) {
          if (failMetadataAt === commentIndex) throw new Error("COMMENT_METADATA_FAILED");
          author = value;
        },
        get Initial() { return initial; },
        set Initial(value) {
          if (failMetadataAt === commentIndex) throw new Error("COMMENT_METADATA_FAILED");
          initial = value;
        },
        Range: range,
        Text: text,
        deleted: false,
        Delete() {
          if (failDeleteAt === commentIndex) throw new Error("COMMENT_DELETE_FAILED");
          this.deleted = true;
        },
      };
      created.push(comment);
      return comment;
    },
  };
}

function makeDocument(rawText, comments, paragraphSpecs = null, pageStarts = null) {
  const specs = paragraphSpecs || [{ text: rawText, start: 0, end: rawText.length + 1 }];
  const paragraphRanges = specs.map((spec) => {
    const range = makeParagraphRange(spec.text);
    range.Start = spec.start;
    range.End = spec.end;
    return range;
  });
  const paragraphRange = paragraphRanges[0];
  const document = {
    FullName: "C:\\fixtures\\sample.docx",
    Name: "sample.docx",
    Saved: true,
    Tables: { Count: 0 },
    Comments: comments,
    Save() {
      this.Saved = true;
    },
    Paragraphs: {
      Count: paragraphRanges.length,
      Item(index) {
        return { Range: paragraphRanges[index - 1] };
      },
    },
  };
  if (pageStarts) {
    document.ComputeStatistics = () => pageStarts.length;
    document.GoTo = (_what, _which, count) => ({ Start: pageStarts[count - 1] });
  }
  return { document, paragraphRange };
}

function bindingItem(rawText, start, end, blockIndex = 0, overrides = {}) {
  return Object.assign({
    block_index: blockIndex,
    type_id: "body",
    review_level: "confirmed",
    confidence: 0.99,
    binding_status: "confirmed",
    recommended_action: "verify_host_range",
    preview_eligible: true,
    host_paragraph_index: 0,
    host_raw_start_utf16: start,
    host_raw_end_utf16: end,
    host_paragraph_raw_sha256: sha256(rawText),
    raw_fragment_sha256: sha256(rawText.slice(start, end)),
  }, overrides);
}

function makeHostHarness({
  rawText = "ABCD",
  bindingItems,
  failAddAt = 0,
  failMetadataAt = 0,
  failDeleteAt = 0,
  routeOverride,
  transport = true,
  bootstrapId = "",
  convertedRawText = "",
  paragraphSpecs = null,
  pageStarts = null,
} = {}) {
  const { storage, values } = makeStorage();
  const comments = makeComments({ failAddAt, failMetadataAt, failDeleteAt });
  const { document, paragraphRange } = makeDocument(
    rawText, comments, paragraphSpecs, pageStarts,
  );
  const logs = [];
  const apiCalls = [];
  const intervals = [];
  const bridgeWaiters = [];
  let bridgeGeneration = 1;
  let bridgeStateRevision = 1;
  let bridgeState = { host_ready: false, status: "NOT_READY" };
  const panes = [];
  const taskpaneCreateCalls = [];
  const taskpaneOperations = [];
  const activationCalls = [];
  const documentLifecycleCalls = [];
  const bridgePaths = [];
  const saveAsFormats = [];
  const deletedPaths = [];
  const application = {
    ActiveDocument: document,
    PluginStorage: storage,
    ribbonUI: { Invalidate() {} },
    CreateTaskPane(...args) {
      taskpaneCreateCalls.push(args);
      const paneState = { visible: false, width: 640, dockPosition: 2 };
      const pane = { ID: panes.length + 1 };
      Object.defineProperties(pane, {
        Visible: {
          get() { return paneState.visible; },
          set(value) {
            paneState.visible = Boolean(value);
            if (paneState.visible) paneState.width = 325;
            taskpaneOperations.push(`visible:${String(Boolean(value))}`);
          },
        },
        Width: {
          get() { return paneState.width; },
          set(value) {
            paneState.width = Number(value);
            taskpaneOperations.push(`width:${String(Number(value))}`);
          },
        },
        DockPosition: {
          get() { return paneState.dockPosition; },
          set(value) {
            paneState.dockPosition = Number(value);
            taskpaneOperations.push(`dock:${String(Number(value))}`);
          },
        },
      });
      panes.push(pane);
      return pane;
    },
    GetTaskPane(id) {
      return panes.find((item) => item.ID === id) || null;
    },
    Documents: {
      Add() {
        const temporaryDocument = {
          Close(saveChanges) {
            documentLifecycleCalls.push(`temporary.close:${String(saveChanges)}`);
            if (application.ActiveDocument === temporaryDocument) {
              application.ActiveDocument = document;
            }
          },
        };
        documentLifecycleCalls.push("temporary.add");
        application.ActiveDocument = temporaryDocument;
        return temporaryDocument;
      },
      Open(path) {
        const reopened = {
          FullName: path,
          Name: String(path).split("\\").pop(),
          Saved: true,
          Tables: document.Tables,
          InlineShapes: document.InlineShapes,
          Shapes: document.Shapes,
          Sections: document.Sections,
          Comments: document.Comments,
          Paragraphs: document.Paragraphs,
          ActiveWindow: {
            Activate() { activationCalls.push("window"); },
          },
          Activate() {
            activationCalls.push("document");
          },
          Save() {
            this.Saved = true;
          },
          SaveAs2(savePath, format) {
            bridgePaths.push(savePath);
            saveAsFormats.push(format);
            this.FullName = savePath;
            this.Name = String(savePath).split("\\").pop();
            this.Saved = true;
            application.ActiveDocument = this;
          },
          Close() {
            if (application.ActiveDocument === reopened) {
              application.ActiveDocument = null;
            }
          },
        };
        application.ActiveDocument = reopened;
        return reopened;
      },
    },
    FileSystem: {
      unlinkSync(path) {
        deletedPaths.push(path);
      },
    },
    Enum: {
      msoCTPDockPositionRight: 2,
      msoCTPDockPositionFloating: 4,
      wdGoToPage: 1,
      wdGoToAbsolute: 1,
      wdStatisticPages: 2,
    },
  };
  document.Activate = () => {
    activationCalls.push("document");
    documentLifecycleCalls.push("source.activate");
    application.ActiveDocument = document;
  };
  document.ActiveWindow = {
    Activate() { activationCalls.push("window"); },
  };
  document.SaveAs2 = (path, format) => {
    bridgePaths.push(path);
    saveAsFormats.push(format);
    document.FullName = path;
    document.Name = String(path).split("\\").pop();
    if (convertedRawText) paragraphRange.Text = `${convertedRawText}\r`;
    document.Saved = true;
    application.ActiveDocument = document;
  };
  document.Close = () => {
    if (application.ActiveDocument === document) {
      application.ActiveDocument = null;
    }
  };

  const defaultItems = bindingItems || [bindingItem(rawText, 0, rawText.length)];
  async function fetch(url, options = {}) {
    const path = new URL(url).pathname;
    const body = options.body ? JSON.parse(options.body) : {};
    if (path === "/v1/log") {
      logs.push(body);
      return { ok: true, status: 200, json: async () => ({ ok: true }) };
    }
    apiCalls.push({ path, body, headers: options.headers || {} });
    if (routeOverride) {
      const overridden = await routeOverride({
        path,
        body,
        application,
        document,
        defaultItems,
      });
      if (overridden) {
        return {
          ok: overridden.ok ?? true,
          status: overridden.status ?? 200,
          json: async () => overridden.payload,
        };
      }
    }
    let data;
    if (path === "/v1/bridge/host/register") {
      data = {
        host_generation: bridgeGeneration,
        state_revision: bridgeStateRevision,
        replaced: false,
      };
    } else if (path === "/v1/bridge/state") {
      bridgeState = body.state;
      bridgeStateRevision += 1;
      data = {
        host_generation: bridgeGeneration,
        state_revision: bridgeStateRevision,
      };
    } else if (path === "/v1/bridge/host/wait") {
      return await new Promise((resolve) => bridgeWaiters.push(resolve));
    } else if (path === "/v1/recognize") {
      data = {
        plan_id: "plan-test",
        document_mode: "NORMAL",
        block_count: defaultItems.length,
        review_count: 0,
        unresolved_count: 0,
      };
    } else if (path === "/v1/recognize/bind") {
      data = {
        block_count: defaultItems.length,
        confirmed_count: defaultItems.filter((item) => item.binding_status === "confirmed").length,
        binding_review_count: defaultItems.filter((item) => item.binding_status === "review").length,
        unresolved_count: defaultItems.filter((item) => item.binding_status === "unresolved").length,
        preview_eligible_count: defaultItems.filter((item) => item.preview_eligible).length,
        items: defaultItems,
      };
    } else if (path === "/v1/health") {
      data = { docxtool_version: "test" };
    } else if (path === "/v1/format/prepare") {
      data = {
        operation_id: "operation-test",
        paragraph_count: 1,
        heading_count: 0,
        compatibility_warnings: [],
        log_file: "document.log",
      };
    } else if (path === "/v1/letterhead/inspect") {
      data = {
        status: "none",
        exists: false,
        replaceable: false,
        fields: null,
      };
    } else if (path === "/v1/letterhead/prepare") {
      data = {
        operation_id: "operation-test",
        state: "prepared",
        action: "generated",
      };
    } else if (path === "/v1/format/upgrade/reserve") {
      data = {
        operation_id: "operation-test",
        state: "conversion_pending",
        conversion_path: "C:\\fixtures\\.legacy.docxtool-convert-operation-te.docx",
        target_path: "C:\\fixtures\\legacy.docx",
        source_format: "doc",
      };
    } else if (path === "/v1/format/upgrade/prepare") {
      data = {
        operation_id: "operation-test",
        paragraph_count: 1,
        heading_count: 0,
        compatibility_warnings: [],
        log_file: "document.log",
      };
    } else if (path === "/v1/format/upgrade/prepare-converted") {
      data = {
        operation_id: "operation-test",
        state: "prepared",
      };
    } else {
      data = { state: "ok" };
    }
    return {
      ok: true,
      status: 200,
      json: async () => ({ ok: true, data }),
    };
  }

  const consoleLines = [];
  const quietConsole = {
    log(message) { consoleLines.push(String(message)); },
    warn(message) { consoleLines.push(String(message)); },
    error(message) { consoleLines.push(String(message)); },
  };
  const context = {
    Application: application,
    Date,
    Error,
    JSON,
    Math,
    Promise,
    TextEncoder,
    URL,
    console: quietConsole,
    crypto: webcrypto,
    fetch,
    location: { href: "http://127.0.0.1:3889/index.html" },
    setInterval(callback) {
      intervals.push(callback);
      return intervals.length;
    },
    clearInterval() {},
    setTimeout(callback) {
      callback();
      return 1;
    },
    DocxToolWpsConfig: transport ? {
      controlBaseUrl: "http://127.0.0.1:9527",
      sessionToken: "test-token",
    } : {},
    DocxToolBootstrapId: bootstrapId,
    DocxToolEarlyLog() {},
  };
  context.window = context;
  vm.runInNewContext(HOST_SOURCE, context, { filename: "host-runtime.js" });

  return {
    application,
    activationCalls,
    bridgePaths,
    comments,
    consoleLines,
    context,
    document,
    documentLifecycleCalls,
    deletedPaths,
    events: () => logs.map((item) => item.event),
    async flushAsync(turns = 12) {
      for (let index = 0; index < turns; index += 1) await Promise.resolve();
    },
    async waitForBridgeReady() {
      for (let index = 0; index < 30; index += 1) {
        if (context.DocxToolHostRuntime.getBridgeReady() && bridgeWaiters.length === 1) return;
        await new Promise((resolve) => setImmediate(resolve));
      }
      assert.fail("Host bridge did not become ready");
    },
    deliverBridgeCommand(command) {
      const resolve = bridgeWaiters.shift();
      assert.ok(resolve, "Host bridge has no pending wait request");
      resolve({
        ok: true,
        status: 200,
        json: async () => ({
          ok: true,
          data: {
            timed_out: false,
            command: Object.assign({
              schema_version: "wps-command-v2",
              pane_instance_id: "pane-test",
              command_sequence: 1,
              host_generation: bridgeGeneration,
            }, command),
          },
        }),
      });
    },
    get bridgeState() { return bridgeState; },
    get bridgeWaiterCount() { return bridgeWaiters.length; },
    intervals,
    logs,
    apiCalls,
    runtime: context.DocxToolHostRuntime,
    saveAsFormats,
    storage,
    taskpaneCreateCalls,
    taskpaneOperations,
    values,
  };
}

function requestContext(command, requestId) {
  return { command, request_id: requestId, source: "taskpane" };
}

function completeBootstrap(harness, bootstrapId = "bootstrap-test") {
  const earlyLogs = [];
  harness.bootstrapLogs = earlyLogs;
  harness.context.DocxToolBootstrapId = bootstrapId;
  harness.context.DocxToolEarlyLog = (level, component, event, message, details) => {
    earlyLogs.push({ level, component, event, message, details });
  };
  harness.context.DocxToolFlushEarlyLogs = async () => earlyLogs.length;
  vm.runInNewContext(
    BOOTSTRAP_COMPLETE_SOURCE,
    harness.context,
    { filename: "bootstrap-complete.js" },
  );
  return earlyLogs;
}


function makeElement(id) {
  const rect = id === "taskpane_header"
      ? { top: 0, right: 380, bottom: 64, left: 0, width: 380, height: 64 }
    : id === "content"
      ? { top: 64, right: 380, bottom: 720, left: 0, width: 380, height: 656 }
      : { top: 80, right: 200, bottom: 112, left: 0, width: 200, height: 32 };
  return {
    id,
    tagName: id === "taskpane_header" ? "HEADER" : "DIV",
    disabled: false,
    scrollTop: 0,
    clientWidth: rect.width,
    clientHeight: rect.height,
    scrollWidth: rect.width,
    scrollHeight: rect.height,
    offsetTop: rect.top,
    offsetHeight: rect.height,
    rect,
    textContent: "",
    hidden: false,
    value: "",
    children: [],
    dataset: {},
    listeners: new Map(),
    classList: {
      values: new Set(),
      add(value) { this.values.add(value); },
      remove(value) { this.values.delete(value); },
      toggle(value, enabled) {
        if (enabled) this.values.add(value);
        else this.values.delete(value);
      },
    },
    addEventListener(name, callback) {
      this.listeners.set(name, callback);
    },
    getBoundingClientRect() {
      return { ...this.rect };
    },
    replaceChildren(...children) { this.children = children; },
    appendChild(child) { this.children.push(child); return child; },
    append(...children) { this.children.push(...children.flat()); },
    querySelector(selector) {
      const field = String(selector).match(/^\[data-field="([^"]+)"\]$/);
      const index = String(selector).match(/^\[data-index="([^"]+)"\]$/);
      const matches = (item) => item && item.dataset && ((field && item.dataset.field === field[1]) || (index && item.dataset.index === index[1]));
      const visit = (items) => {
        for (const item of items || []) {
          if (matches(item)) return item;
          const nested = visit(item.children);
          if (nested) return nested;
        }
        return null;
      };
      return matches(this) ? this : visit(this.children);
    },
    setAttribute(name, value) {
      if (!this.attributes) this.attributes = new Map();
      this.attributes.set(name, String(value));
    },
    focus() {},
  };
}

function makeTaskpaneHarness(initialState, {
  transport = true,
  commandFailure = "",
  notificationAckFailure = "",
  invalidJsonPath = "",
  stateWaitFailure = "",
  nowMs = Date.now(),
  account = {
    signed_in: true,
    username: "User01",
    network_available: true,
    apply_available: true,
    pending_result_count: 0,
    error_code: "",
  },
} = {}) {
  const { storage, values } = makeStorage();
  const elements = new Map();
  const logs = [];
  const consoleLines = [];
  const bridgeCalls = [];
  const commandRequests = [];
  const notificationAcknowledgements = [];
  const dialogCalls = [];
  const stateWaiters = [];
  const scrollCalls = [];
  const timeouts = [];
  const windowListeners = new Map();
  const documentListeners = new Map();
  let activeDocumentReads = 0;
  let initialStatePending = true;
  let hostGeneration = initialState && initialState.host_ready ? 1 : 0;
  let stateRevision = 1;
  let nextStateWaitFailure = stateWaitFailure;
  let nextNotificationAckFailure = notificationAckFailure;
  let currentAccount = account;
  let currentNowMs = nowMs;
  const HarnessDate = class extends Date {
    static now() { return currentNowMs; }
  };
  const ids = [
    "preview", "apply", "format_settings", "add_letterhead", "clear_preview", "health",
    "format_mode", "reader_mode", "format_mode_tab", "reader_mode_tab",
    "format_main_panel",
    "format_scope_mode", "format_page_spec",
    "letterhead_modal", "letterhead_mark", "letterhead_number", "letterhead_signer",
    "letterhead_separator", "letterhead_form_error", "letterhead_cancel", "letterhead_confirm",
    "close_panel", "status", "account", "message", "error", "warnings", "notifications_panel", "notifications", "summary", "rows",
    "taskpane_header", "content",
  ];
  for (const id of ids) elements.set(id, makeElement(id));
  elements.get("format_scope_mode").value = "whole";
  elements.get("format_page_spec").value = "";
  elements.get("format_page_spec").focus = () => {};
  elements.get("letterhead_separator").value = "straight";
  elements.get("reader_mode").hidden = true;
  elements.get("format_main_panel").hidden = false;
  elements.get("content").scrollTop = 80;
  const body = {
    scrollTop: 80,
    clientWidth: 380,
    clientHeight: 720,
    scrollWidth: 380,
    scrollHeight: 720,
    tagName: "BODY",
    id: "",
  };
  const document = {
    readyState: "loading",
    visibilityState: "visible",
    documentElement: {
      scrollTop: 80,
      clientWidth: 380,
      clientHeight: 720,
      scrollWidth: 380,
      scrollHeight: 720,
    },
    body,
    activeElement: body,
    addEventListener(name, callback) {
      const listeners = documentListeners.get(name) || [];
      listeners.push(callback);
      documentListeners.set(name, listeners);
    },
    elementFromPoint() {
      return elements.get("taskpane_header").rect.bottom > 0
        ? elements.get("taskpane_header")
        : elements.get("content");
    },
    getElementById(id) {
      return elements.get(id) || null;
    },
    hasFocus() {
      return true;
    },
    createElement(tagName) { return makeElement(tagName); },
    createTextNode(text) { const item = makeElement("TEXT"); item.textContent = String(text); return item; },
  };
  const defaultFormatConfig = {
    styles: [
      { name: "主标题", font: "方正小标宋简体", size: "二号", bold: false, pattern: "", indent: 0, align: "居中" },
      { name: "一级标题", font: "黑体", size: "三号", bold: false, pattern: "{a}、", indent: 2, align: "左对齐" },
      { name: "二级标题", font: "楷体_GB2312", size: "三号", bold: true, pattern: "（{b}）", indent: 2, align: "左对齐" },
      { name: "三级标题", font: "仿宋_GB2312", size: "三号", bold: true, pattern: "{c}.", indent: 2, align: "左对齐" },
      { name: "四级标题", font: "仿宋_GB2312", size: "三号", bold: false, pattern: "（{d}）", indent: 2, align: "左对齐" },
      { name: "正文", font: "仿宋_GB2312", size: "三号", bold: false, pattern: "", indent: 2, align: "两端对齐" },
      { name: "数字", font: "Times New Roman", bold: false },
      { name: "字母", font: "Times New Roman", bold: false },
      { name: "页码设置", font: "宋体", size: "四号", pattern: "— 1 —", align: "奇右|偶左" },
    ],
    page: { width_cm: 21, height_cm: 29.7, margin_top_cm: 3.7, margin_bottom_cm: 3.5, margin_left_cm: 2.8, margin_right_cm: 2.6, lines_per_page: 22, chars_per_line: 28, line_spacing_pt: 28, space_before_line: 0, space_after_line: 0, grid_alignment: "文字对齐字符网络" },
    page_number: { enabled: true, style: "dash", position: "outside", font_name: "宋体", font_size_pt: 14, first_page: true, section_numbering: "continue", offset_from_text_mm: 7 },
  };
  const cloneFormatConfig = (value) => JSON.parse(JSON.stringify(value));
  let activeFormatProfile = {
    profile_id: "system:default",
    name: "系统默认",
    is_system: true,
    revision: 0,
    config_version: "config-1",
    format_config: cloneFormatConfig(defaultFormatConfig),
  };
  function formatProfileResponse() {
    const system = {
      profile_id: "system:default",
      name: "系统默认",
      is_system: true,
      revision: 0,
      config_version: "config-1",
      format_config: cloneFormatConfig(defaultFormatConfig),
    };
    return {
      profiles: activeFormatProfile.profile_id === "system:default"
        ? [system]
        : [system, { ...activeFormatProfile, format_config: undefined }],
      active_profile_id: activeFormatProfile.profile_id,
      active_profile: cloneFormatConfig(activeFormatProfile),
      legacy_imported: false,
    };
  }
  function response(data, { ok = true, status = 200 } = {}) {
    return {
      ok,
      status,
      json: async () => data,
    };
  }
  async function fetch(url, options = {}) {
    const path = new URL(url).pathname;
    const body = options.body ? JSON.parse(options.body) : {};
    if (path === "/v1/log") {
      logs.push(body);
      return response({ ok: true });
    }
    bridgeCalls.push({
      path,
      body,
      cache: options.cache,
      headers: options.headers || {},
    });
    if (path === invalidJsonPath) {
      return { ok: true, status: 200, json: async () => { throw new Error("INVALID_JSON"); } };
    }
    if (path === "/v1/format/default") {
      return response({
        ok: true,
        data: {
          config_version: "config-1",
          format_config: structuredClone(defaultFormatConfig),
        },
      });
    }
    if (path === "/v1/format/profiles/initialize" || path === "/v1/format/profiles") {
      return response({ ok: true, data: formatProfileResponse() });
    }
    if (path === "/v1/format/profiles/active") {
      const data = formatProfileResponse();
      return response({ ok: true, data: {
        active_profile_id: data.active_profile_id,
        active_profile: data.active_profile,
      } });
    }
    if (path === "/v1/format/profiles/detail") {
      const data = formatProfileResponse();
      return response({ ok: true, data: {
        profile: data.active_profile,
      } });
    }
    if (path === "/v1/bridge/state/wait") {
      if (nextStateWaitFailure) {
        const code = nextStateWaitFailure;
        nextStateWaitFailure = "";
        return response({ ok: false, error_code: code }, { ok: false, status: 400 });
      }
      if (initialStatePending) {
        initialStatePending = false;
        return response({
          ok: true,
          data: {
            timed_out: false,
            generation_changed: false,
            host_generation: hostGeneration,
            state_revision: stateRevision,
            state: initialState,
            account: currentAccount,
          },
        });
      }
      return await new Promise((resolve, reject) => stateWaiters.push({ resolve, reject }));
    }
    if (path === "/v1/account/notifications/read") {
      notificationAcknowledgements.push(body.notification_ids || []);
      if (nextNotificationAckFailure) {
        const code = nextNotificationAckFailure;
        nextNotificationAckFailure = "";
        return response({ ok: false, error_code: code }, { ok: false, status: 400 });
      }
      return response({
        ok: true,
        data: {
          acknowledged_notification_ids: body.notification_ids || [],
        },
      });
    }
    if (path === "/v1/bridge/command") {
      commandRequests.push(body);
      if (commandFailure) {
        return response(
          { ok: false, error_code: commandFailure },
          { ok: false, status: 400 },
        );
      }
      return response({
        ok: true,
        data: {
          request_id: body.request_id,
          command_sequence: commandRequests.length,
          state_revision: stateRevision + 1,
        },
      });
    }
    throw new Error(`UNEXPECTED_TASKPANE_ROUTE:${path}`);
  }
  const application = {
    PluginStorage: storage,
    ShowDialog(...args) { dialogCalls.push(args); },
    GetTaskPane() {
      return null;
    },
  };
  Object.defineProperty(application, "ActiveDocument", {
    get() {
      activeDocumentReads += 1;
      return null;
    },
  });
  const readerCalls = [];
  const reader = {
    initialize() { readerCalls.push("initialize"); },
    async activate() { readerCalls.push("activate"); },
    deactivate() { readerCalls.push("deactivate"); },
    pauseAndSave() { readerCalls.push("pauseAndSave"); },
  };
  const context = {
    Application: application,
    Date: HarnessDate,
    Error,
    JSON,
    Math,
    Object,
    Promise,
    URL,
    location: { href: "http://127.0.0.1:3889/taskpane.html" },
    console: {
      log(message) { consoleLines.push(String(message)); },
      warn(message) { consoleLines.push(String(message)); },
      error(message) { consoleLines.push(String(message)); },
    },
    document,
    fetch,
    setTimeout(callback, delay = 0) {
      timeouts.push({ callback, delay });
      return timeouts.length;
    },
    addEventListener(name, callback) {
      const listeners = windowListeners.get(name) || [];
      listeners.push(callback);
      windowListeners.set(name, listeners);
    },
    devicePixelRatio: 1,
    innerHeight: 720,
    innerWidth: 380,
    outerHeight: 720,
    outerWidth: 380,
    screenX: 80,
    screenY: 120,
    screenLeft: 80,
    screenTop: 120,
    screen: {
      width: 1920,
      height: 1080,
      availWidth: 1920,
      availHeight: 1040,
      availLeft: 0,
      availTop: 0,
    },
    pageXOffset: 0,
    pageYOffset: 0,
    visualViewport: {
      height: 720,
      width: 380,
      offsetTop: 0,
      pageTop: 0,
    },
    getComputedStyle() {
      return {
        display: "block",
        opacity: "1",
        overflow: "visible",
        position: "static",
        transform: "none",
        visibility: "visible",
        zIndex: "auto",
      };
    },
    scrollTo(x, y) {
      scrollCalls.push([x, y]);
    },
    confirm() { return false; },
    DocxToolWpsConfig: transport ? {
      controlBaseUrl: "http://127.0.0.1:9527",
      sessionToken: "test-token",
    } : {},
    DocxToolReader: reader,
  };
  context.window = context;
  context.self = context;
  context.top = context;
  vm.runInNewContext(FORMAT_CONFIG_SOURCE, context, { filename: "format-config.js" });
  vm.runInNewContext(TASKPANE_SOURCE, context, { filename: "taskpane.js" });
  return {
    click(id) {
      elements.get(id).listeners.get("click")();
    },
    get activeDocumentReads() { return activeDocumentReads; },
    bridgeCalls,
    commandRequests,
    notificationAcknowledgements,
    dialogCalls,
    consoleLines,
    elements,
    context,
    events: () => logs.map((item) => item.event),
    logs,
    readerCalls,
    document,
    dispatchDocumentEvent(name, event = {}) {
      (documentListeners.get(name) || []).forEach((callback) => callback(event));
    },
    dispatchWindowEvent(name, event = {}) {
      (windowListeners.get(name) || []).forEach((callback) => callback(event));
    },
    flushTimeouts() {
      while (timeouts.length) timeouts.shift().callback();
    },
    scrollCalls,
    storage,
    async flushAsync(turns = 12) {
      for (let index = 0; index < turns; index += 1) await Promise.resolve();
    },
    pushState(state, { generationChanged = false, generation, account: nextAccount } = {}) {
      const waiter = stateWaiters.shift();
      assert.ok(waiter, "TaskPane has no pending state wait request");
      hostGeneration = generation ?? hostGeneration;
      if (nextAccount) currentAccount = nextAccount;
      stateRevision += 1;
      waiter.resolve(response({
        ok: true,
        data: {
          timed_out: false,
          generation_changed: generationChanged,
          host_generation: hostGeneration,
          state_revision: stateRevision,
          state,
          account: currentAccount,
        },
      }));
    },
    timeoutStateWait() {
      const waiter = stateWaiters.shift();
      assert.ok(waiter, "TaskPane has no pending state wait request");
      waiter.resolve(response({
        ok: true,
        data: {
          timed_out: true,
          generation_changed: false,
          host_generation: hostGeneration,
          state_revision: stateRevision,
          state: initialState,
          account: currentAccount,
        },
      }));
    },
    failNextStateWait(code) {
      const waiter = stateWaiters.shift();
      assert.ok(waiter, "TaskPane has no pending state wait request");
      waiter.resolve(response({ ok: false, error_code: code }, { ok: false, status: 400 }));
    },
    get stateWaiterCount() { return stateWaiters.length; },
    advanceTime(milliseconds) { currentNowMs += milliseconds; },
    values,
    getActiveFormatConfig() {
      return cloneFormatConfig(activeFormatProfile.format_config);
    },
    setActiveFormatConfig(configValue) {
      activeFormatProfile = {
        ...activeFormatProfile,
        profile_id: "fmt_test_profile",
        name: "测试模板",
        is_system: false,
        revision: Number(activeFormatProfile.revision || 0) + 1,
        format_config: cloneFormatConfig(configValue),
      };
    },
  };
}


export {
  HOST_SOURCE,
  TASKPANE_SOURCE,
  FORMAT_CONFIG_SOURCE,
  MAIN_SOURCE,
  RIBBON_SOURCE,
  BOOTSTRAP_COMPLETE_SOURCE,
  TASKPANE_KEY,
  TASKPANE_VERSION_KEY,
  sha256,
  makeStorage,
  makeParagraphRange,
  makeComments,
  makeDocument,
  bindingItem,
  makeHostHarness,
  requestContext,
  completeBootstrap,
  makeElement,
  makeTaskpaneHarness,
  assert,
  createHash,
  webcrypto,
  readFile,
  test,
  vm,
};
