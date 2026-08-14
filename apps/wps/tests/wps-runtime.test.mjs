import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const HOST_SOURCE = await readFile(
  new URL("../host-runtime.js", import.meta.url),
  "utf8",
);
const TASKPANE_SOURCE = await readFile(
  new URL("../taskpane.js", import.meta.url),
  "utf8",
);
const MAIN_SOURCE = await readFile(new URL("../main.js", import.meta.url), "utf8");
const RIBBON_SOURCE = await readFile(
  new URL("../js/ribbon.js", import.meta.url),
  "utf8",
);
const BOOTSTRAP_COMPLETE_SOURCE = await readFile(
  new URL("../js/bootstrap-complete.js", import.meta.url),
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

test("Ribbon callbacks keep ribbonUI outside the WPS Application proxy", () => {
  const existingRibbonUI = { Invalidate() {} };
  const application = {};
  Object.defineProperty(application, "ribbonUI", {
    configurable: false,
    value: existingRibbonUI,
    writable: false,
  });
  const receivedRibbonUI = { Invalidate() {} };
  const calls = [];
  const context = {
    Application: application,
    DocxToolEarlyLog() {},
    DocxToolHostRuntime: {
      setRibbonUI(value) { calls.push(["set", value]); },
      start() { calls.push(["start"]); },
      handleRibbonAction(id) { calls.push(["action", id]); },
      getActionEnabled() { return true; },
    },
  };
  context.window = context;
  vm.runInNewContext(RIBBON_SOURCE, context, { filename: "ribbon.js" });

  assert.equal(context.DocxToolRibbonCallbacks.onAddinLoad(receivedRibbonUI), true);
  assert.equal(application.ribbonUI, existingRibbonUI);
  assert.deepEqual(calls.slice(0, 2), [["set", receivedRibbonUI], ["start"]]);
  assert.equal(context.DocxToolRibbonCallbacks.onAction({ Id: "panel" }), true);
  assert.deepEqual(calls.at(-1), ["action", "panel"]);
});

test("Host invalidates the Ribbon UI captured by OnAddinLoad", async () => {
  const harness = makeHostHarness();
  let invalidationCount = 0;
  harness.runtime.setRibbonUI({
    Invalidate() { invalidationCount += 1; },
  });

  await harness.runtime.runCommand(
    "health",
    requestContext("health", "request-ribbon-invalidate"),
  );

  assert.equal(invalidationCount, 1);
});

test("Host preview keeps one request_id through save, binding, Range, and comments", async () => {
  const harness = makeHostHarness();
  assert.equal(harness.runtime.start(), "started");

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-preview"),
  );

  const required = [
    "document.save.invoke.start",
    "document.save.wait.completed",
    "preview.recognition.completed",
    "preview.host_snapshot.completed",
    "preview.binding.completed",
    "preview.range.revalidate.completed",
    "preview.comment.created",
    "preview.comments.completed",
    "preview.completed",
    "host.command.completed",
  ];
  for (const event of required) assert.ok(harness.events().includes(event), event);
  for (const entry of harness.logs.filter((item) => required.includes(item.event))) {
    assert.equal(entry.details.request_id, "request-preview", entry.event);
  }
  assert.equal(harness.comments.created.length, 1);
  assert.equal(harness.comments.created[0].deleted, false);
  assert.match(harness.comments.created[0].Text, /^识别格式：/);
  assert.doesNotMatch(harness.comments.created[0].Text, /DocxTool 预览|DocxTool Engine/);
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/recognize"))
      .map((item) => item.headers["X-DocxTool-Request-Id"]),
    ["request-preview", "request-preview"],
  );
});

test("Host writes canonical review bindings as explicit review comments", async () => {
  const reviewItem = bindingItem("ABCD", 0, 4, 0, {
    binding_status: "review",
    recommended_action: "preview_only",
    preview_eligible: true,
  });
  const harness = makeHostHarness({ bindingItems: [reviewItem] });
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-review-preview"),
  );

  assert.equal(harness.comments.created.length, 1);
  assert.match(harness.comments.created[0].Text, /建议人工复核/);
  const state = harness.runtime.getStateSnapshot();
  assert.equal(state.preview_comment_count, 1);
  assert.equal(state.preview_confirmed_count, 0);
  assert.equal(state.preview_review_count, 1);
});

test("Host rejects a changed canonical review Range before Comments.Add", async () => {
  const reviewItem = bindingItem("ABCD", 0, 4, 0, {
    binding_status: "review",
    recommended_action: "preview_only",
    preview_eligible: true,
    raw_fragment_sha256: sha256("changed"),
  });
  const harness = makeHostHarness({ bindingItems: [reviewItem] });
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-review-changed"),
    ),
    /PREVIEW_RANGE_HASH_MISMATCH/,
  );

  assert.equal(harness.comments.created.length, 0);
  assert.ok(harness.events().includes("preview.range.fragment_mismatch"));
  assert.ok(!harness.events().includes("preview.comment.created"));
});

test("Host writes confirmed and review comments but skips unresolved blocks", async () => {
  const items = [
    bindingItem("ABCD", 0, 1, 0),
    bindingItem("ABCD", 1, 2, 1, {
      binding_status: "review",
      recommended_action: "preview_only",
      preview_eligible: true,
    }),
    bindingItem("ABCD", null, null, 2, {
      type_id: "__table__",
      binding_status: "unresolved",
      recommended_action: "skip",
      preview_eligible: false,
      host_paragraph_index: null,
      host_paragraph_raw_sha256: "",
      raw_fragment_sha256: "",
    }),
  ];
  const harness = makeHostHarness({ bindingItems: items });
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-mixed-preview"),
  );

  assert.equal(harness.comments.created.length, 2);
  const state = harness.runtime.getStateSnapshot();
  assert.equal(state.preview_confirmed_count, 1);
  assert.equal(state.preview_review_count, 1);
  assert.equal(state.recognition.unresolved_count, 1);
});

test("Host logs paragraph-change Range failure before command summary", async () => {
  const item = bindingItem("ABCD", 0, 4);
  item.host_paragraph_raw_sha256 = "0".repeat(64);
  const harness = makeHostHarness({ bindingItems: [item] });
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-range-fail"),
    ),
    /PREVIEW_PARAGRAPH_CHANGED/,
  );

  const specific = harness.events().indexOf("preview.range.paragraph_changed");
  const summary = harness.events().indexOf("host.command.failed");
  assert.ok(specific >= 0);
  assert.ok(summary > specific);
  assert.equal(harness.comments.created.length, 0);
});

test("Host logs Save invocation failure before preview and command summaries", async () => {
  const harness = makeHostHarness();
  harness.document.Save = () => {
    throw new Error("HOST_SAVE_FAILED");
  };
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-save-fail"),
    ),
    /WPS_DOCUMENT_SAVE_CALL_FAILED/,
  );

  const specific = harness.events().indexOf("document.save.invoke.failed");
  const preflightSummary = harness.events().indexOf("preview.preflight.failed");
  const previewSummary = harness.events().indexOf("preview.failed");
  const commandSummary = harness.events().indexOf("host.command.failed");
  assert.ok(specific >= 0);
  assert.ok(preflightSummary > specific);
  assert.ok(previewSummary > preflightSummary);
  assert.ok(commandSummary > previewSummary);
});

test("Host logs Binder API failure at binding stage", async () => {
  const harness = makeHostHarness({
    routeOverride: async ({ path }) => {
      if (path !== "/v1/recognize/bind") return null;
      return {
        ok: false,
        status: 400,
        payload: { ok: false, error_code: "WPS_BINDING_SDK_FAILED" },
      };
    },
  });
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-bind-fail"),
    ),
    /WPS_BINDING_SDK_FAILED/,
  );

  const apiFailure = harness.events().indexOf("api.request.failed");
  const bindingFailure = harness.events().indexOf("preview.binding.failed");
  const commandSummary = harness.events().indexOf("host.command.failed");
  assert.ok(apiFailure >= 0);
  assert.ok(bindingFailure > apiFailure);
  assert.ok(commandSummary > bindingFailure);
});

test("Host rolls back earlier comments when a later Comments.Add fails", async () => {
  const items = [bindingItem("ABCD", 0, 2, 0), bindingItem("ABCD", 2, 4, 1)];
  const harness = makeHostHarness({ bindingItems: items, failAddAt: 2 });
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-comment-fail"),
    ),
    /WPS_PREVIEW_COMMENT_CREATE_CALL_FAILED/,
  );

  assert.equal(harness.comments.created.length, 1);
  assert.equal(harness.comments.created[0].deleted, true);
  assert.ok(harness.events().includes("preview.comment.create_call.failed"));
  assert.ok(harness.events().includes("preview.comments.rollback.completed"));
  assert.ok(!harness.events().includes("preview.comments.completed"));
});

test("Host rolls back comments when preview session storage fails", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  const documentPathHash = sha256("c:\\fixtures\\sample.docx");
  harness.storage.failSetKey = `docxtool_wps_preview_v2:${documentPathHash}`;

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-session-fail"),
    ),
    /WPS_PREVIEW_SESSION_WRITE_FAILED/,
  );

  assert.equal(harness.comments.created.length, 1);
  assert.equal(harness.comments.created[0].deleted, true);
  assert.ok(harness.events().includes("preview.session.write_failed"));
  assert.ok(harness.events().includes("preview.comments.rollback.completed"));
  assert.ok(!harness.events().includes("preview.comments.completed"));
});

test("Host keeps metadata and cleanup failures as separate comment events", async () => {
  const harness = makeHostHarness({ failMetadataAt: 1, failDeleteAt: 1 });
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-comment-double-fail"),
    ),
    /WPS_PREVIEW_COMMENT_METADATA_FAILED/,
  );

  assert.ok(harness.events().includes("preview.comment.metadata.failed"));
  assert.ok(harness.events().includes("preview.comment_cleanup.item.failed"));
  assert.ok(harness.events().includes("preview.comments.rollback.failed"));
  const summary = harness.logs.find((item) => item.event === "host.command.failed");
  assert.equal(summary.details.error_code, "WPS_PREVIEW_COMMENT_METADATA_FAILED");
});

test("Host distinguishes first reopen failure and completes transaction recovery", async () => {
  let openCount = 0;
  const harness = makeHostHarness({
    routeOverride: async ({ path, application, document }) => {
      if (path === "/v1/format/commit") {
        const openDocument = application.Documents.Open.bind(application.Documents);
        application.Documents.Open = (documentPath) => {
          openCount += 1;
          if (openCount === 1) throw new Error("OPEN_FAILED");
          return openDocument(documentPath);
        };
      }
      return null;
    },
  });
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "apply",
      requestContext("apply", "request-reopen-fail"),
    ),
    /WPS_DOCUMENT_OPEN_FAILED/,
  );

  assert.equal(openCount, 2);
  assert.ok(harness.events().includes("format.document.open_call.failed"));
  assert.ok(harness.events().includes("transaction.recovery.start"));
  assert.ok(harness.events().includes("transaction.recovery.completed"));
  assert.ok(!harness.events().includes("format.finalize.completed"));
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/format/"))
      .map((item) => item.path),
    ["/v1/format/prepare", "/v1/format/commit", "/v1/format/rollback"],
  );
});

test("Host keeps a bridge document open while replacing and reopening the source", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();

  await harness.runtime.runCommand(
    "apply",
    requestContext("apply", "request-format-bridge"),
  );

  assert.equal(harness.bridgePaths.length, 1);
  assert.match(harness.bridgePaths[0], /\.docxtool-formatting-operation-te\.docx$/);
  assert.deepEqual(harness.deletedPaths, harness.bridgePaths);
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\sample.docx");
  const events = harness.events();
  assert.ok(events.indexOf("format.bridge.save.completed") < events.indexOf("format.commit.start"));
  assert.ok(events.indexOf("format.document.reopen.completed") < events.indexOf("format.bridge.cleanup.completed"));
  assert.ok(events.indexOf("format.bridge.cleanup.completed") < events.indexOf("format.finalize.start"));
  assert.ok(events.indexOf("format.bridge.save_as.call.start") < events.indexOf("format.bridge.save_as.call.completed"));
  assert.ok(events.indexOf("format.document.open_call.start") < events.indexOf("format.document.open_call.completed"));
  const checkpoints = harness.logs
    .filter((entry) => entry.event === "format.host_context.snapshot")
    .map((entry) => entry.details.checkpoint);
  assert.deepEqual(checkpoints, [
    "format_start",
    "before_preview_clear",
    "after_preview_clear",
    "before_transaction_prepare",
    "before_bridge_save_as",
    "after_bridge_save_as",
    "after_bridge_activated",
    "after_transaction_prepare",
    "before_commit",
    "after_commit",
    "before_target_open",
    "after_target_open_call",
    "after_target_activated",
    "before_bridge_close",
    "after_bridge_close",
    "after_bridge_delete",
    "after_finalize",
    "format_completed",
  ]);
  for (const entry of harness.logs.filter((item) => item.event === "format.host_context.snapshot")) {
    assert.equal(entry.details.request_id, "request-format-bridge");
  }
});

test("Host sends only the authorization identity to the local Engine route", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  const context = requestContext("apply", "request-authorized-config");
  context.config_version = "config-1";

  await harness.runtime.runCommand("apply", context);

  const prepare = harness.apiCalls.find((item) => item.path === "/v1/format/prepare");
  assert.equal(prepare.headers["X-DocxTool-Request-Id"], context.request_id);
  assert.equal(Object.hasOwn(prepare.body, "format_config"), false);
});

test("Host fixes requested pre-format pages before preparing the document", async () => {
  const paragraphSpecs = [
    { text: "第一页", start: 0, end: 4 },
    { text: "跨页段落", start: 4, end: 13 },
    { text: "第三页", start: 13, end: 17 },
  ];
  const harness = makeHostHarness({
    rawText: "第一页",
    paragraphSpecs,
    pageStarts: [0, 8, 13],
  });
  harness.runtime.start();
  const context = requestContext("apply", "request-page-scope");
  context.config_version = "config-1";
  context.format_scope = { mode: "pre_format_pages", page_spec: "2-3" };

  await harness.runtime.runCommand("apply", context);

  const prepare = harness.apiCalls.find((item) => item.path === "/v1/format/prepare");
  assert.deepEqual(
    Array.from(prepare.body.selected_host_paragraph_indexes),
    [1, 2],
  );
  assert.equal(prepare.body.host_snapshot.paragraphs.length, 3);
  assert.equal(
    harness.logs.filter((item) => item.event === "format.scope.resolved").length,
    1,
  );
});

test("Host rejects a pre-format page beyond the original page count", async () => {
  const harness = makeHostHarness({
    paragraphSpecs: [{ text: "第一页", start: 0, end: 4 }],
    pageStarts: [0],
  });
  harness.runtime.start();
  const context = requestContext("apply", "request-page-out-of-range");
  context.config_version = "config-1";
  context.format_scope = { mode: "pre_format_pages", page_spec: "2" };

  await assert.rejects(
    harness.runtime.runCommand("apply", context),
    /WPS_FORMAT_PAGE_OUT_OF_RANGE/,
  );
  assert.equal(
    harness.apiCalls.some((item) => item.path === "/v1/format/prepare"),
    false,
  );
});

test("Host operation logs do not expose the active document name", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();

  await harness.runtime.runCommand(
    "health",
    requestContext("health", "request-document-name"),
  );

  const started = harness.logs.find((item) => item.event === "host.command.start");
  assert.equal(Object.hasOwn(started.details, "document_name"), false);
});

test("Host silently upgrades a legacy DOC before recognition preview", async () => {
  const harness = makeHostHarness();
  harness.document.FullName = "C:\\fixtures\\legacy.doc";
  harness.document.Name = "legacy.doc";
  harness.runtime.start();
  assert.equal(harness.runtime.getActionEnabled("apply"), true);
  assert.equal(harness.runtime.getActionEnabled("preview"), true);

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-legacy-doc"),
  );

  assert.deepEqual(harness.saveAsFormats, [12]);
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.docx");
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/format/"))
      .map((item) => item.path),
    [
      "/v1/format/upgrade/reserve",
      "/v1/format/upgrade/prepare-converted",
      "/v1/format/commit",
      "/v1/format/finalize",
    ],
  );
  const state = harness.runtime.getStateSnapshot();
  assert.equal(state.status, "PASS");
  assert.equal(state.error_code, "");
  assert.match(state.message, /已升级为 legacy\.docx/);
  assert.equal(state.preview_comment_count, 1);
});

test("Host does not upgrade legacy documents for health or clear preview", async () => {
  const harness = makeHostHarness();
  harness.document.FullName = "C:\\fixtures\\legacy.wps";
  harness.document.Name = "legacy.wps";
  harness.runtime.start();

  await harness.runtime.runCommand(
    "health",
    requestContext("health", "request-legacy-health"),
  );
  await harness.runtime.runCommand(
    "clear_preview",
    requestContext("clear_preview", "request-legacy-clear"),
  );

  assert.deepEqual(harness.saveAsFormats, []);
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.wps");
  assert.equal(
    harness.apiCalls.filter((item) => item.path.startsWith("/v1/format/")).length,
    0,
  );
  const state = harness.runtime.getStateSnapshot();
  assert.equal(state.status, "PASS");
  assert.match(state.message, /没有可清除的 DocxTool 预览/);
});

test("Host does not repeat legacy conversion after the first preview upgrade", async () => {
  const harness = makeHostHarness();
  harness.document.FullName = "C:\\fixtures\\legacy.wps";
  harness.document.Name = "legacy.wps";
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-upgrade-first"),
  );
  await harness.runtime.runCommand(
    "clear_preview",
    requestContext("clear_preview", "request-upgrade-clear"),
  );
  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-upgrade-second"),
  );

  assert.deepEqual(harness.saveAsFormats, [12]);
  assert.equal(
    harness.apiCalls.filter(
      (item) => item.path === "/v1/format/upgrade/reserve",
    ).length,
    1,
  );
  assert.equal(
    harness.apiCalls.filter((item) => item.path === "/v1/recognize").length,
    2,
  );
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.docx");
});

test("Host silently upgrades legacy DOC once and opens the formatted DOCX", async () => {
  const harness = makeHostHarness();
  harness.document.FullName = "C:\\fixtures\\legacy.doc";
  harness.document.Name = "legacy.doc";
  harness.runtime.start();

  await harness.runtime.runCommand(
    "apply",
    requestContext("apply", "request-legacy-upgrade"),
  );

  assert.equal(harness.bridgePaths.length, 1);
  assert.match(harness.bridgePaths[0], /\.docxtool-convert-operation-te\.docx$/);
  assert.deepEqual(harness.saveAsFormats, [12]);
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.docx");
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/format/"))
      .map((item) => item.path),
    [
      "/v1/format/upgrade/reserve",
      "/v1/format/upgrade/prepare",
      "/v1/format/commit",
      "/v1/format/finalize",
    ],
  );
  const state = harness.runtime.getStateSnapshot();
  assert.match(state.message, /已升级为 legacy\.docx/);
});

test("Host blocks a legacy upgrade target collision before SaveAs2", async () => {
  for (const command of ["preview", "apply"]) {
    const harness = makeHostHarness({
      routeOverride: async ({ path }) => {
        if (path !== "/v1/format/upgrade/reserve") return null;
        return {
          ok: false,
          status: 409,
          payload: { ok: false, error_code: "WPS_LEGACY_UPGRADE_TARGET_EXISTS" },
        };
      },
    });
    harness.document.FullName = "C:\\fixtures\\legacy.doc";
    harness.document.Name = "legacy.doc";
    harness.runtime.start();

    await assert.rejects(
      harness.runtime.runCommand(
        command,
        requestContext(command, `request-legacy-collision-${command}`),
      ),
      /WPS_LEGACY_UPGRADE_TARGET_EXISTS/,
    );

    assert.deepEqual(harness.saveAsFormats, []);
    assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.doc");
    assert.deepEqual(
      harness.apiCalls
        .filter((item) => item.path.startsWith("/v1/format/"))
        .map((item) => item.path),
      ["/v1/format/upgrade/reserve"],
    );
  }
});

test("Host restores the legacy source when preview upgrade reopen fails", async () => {
  let openCount = 0;
  const harness = makeHostHarness({
    routeOverride: async ({ path, application }) => {
      if (path !== "/v1/format/commit") return null;
      const openDocument = application.Documents.Open.bind(application.Documents);
      application.Documents.Open = (documentPath) => {
        openCount += 1;
        if (openCount === 1) throw new Error("OPEN_FAILED");
        return openDocument(documentPath);
      };
      return null;
    },
  });
  harness.document.FullName = "C:\\fixtures\\legacy.doc";
  harness.document.Name = "legacy.doc";
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-preview-upgrade-reopen-fail"),
    ),
    /WPS_DOCUMENT_OPEN_FAILED/,
  );

  assert.equal(openCount, 2);
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.doc");
  assert.ok(harness.events().includes("document.upgrade.reopen.failed"));
  assert.ok(harness.events().includes("document.upgrade.rollback.completed"));
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/format/"))
      .map((item) => item.path),
    [
      "/v1/format/upgrade/reserve",
      "/v1/format/upgrade/prepare-converted",
      "/v1/format/commit",
      "/v1/format/rollback",
    ],
  );
});

test("Host rolls back when the WPS legacy SaveAs2 call fails", async () => {
  const harness = makeHostHarness({
    routeOverride: async ({ path, document }) => {
      if (path !== "/v1/format/upgrade/reserve") return null;
      document.SaveAs2 = () => {
        throw new Error("SAVE_AS_FAILED");
      };
      return null;
    },
  });
  harness.document.FullName = "C:\\fixtures\\legacy.wps";
  harness.document.Name = "legacy.wps";
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "apply",
      requestContext("apply", "request-legacy-save-as-fail"),
    ),
    /WPS_LEGACY_CONVERSION_FAILED/,
  );

  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.wps");
  assert.ok(harness.events().includes("document.upgrade.save_as.failed"));
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/format/"))
      .map((item) => item.path),
    ["/v1/format/upgrade/reserve", "/v1/format/rollback"],
  );
});

test("Host rolls back a legacy conversion whose visible content changed", async () => {
  const harness = makeHostHarness({ convertedRawText: "changed" });
  harness.document.FullName = "C:\\fixtures\\legacy.doc";
  harness.document.Name = "legacy.doc";
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "apply",
      requestContext("apply", "request-legacy-mismatch"),
    ),
    /WPS_LEGACY_CONVERSION_CONTENT_MISMATCH/,
  );

  assert.ok(harness.events().includes("document.upgrade.verify.failed"));
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.doc");
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/format/"))
      .map((item) => item.path),
    ["/v1/format/upgrade/reserve", "/v1/format/rollback"],
  );
});

test("Host start registers one long request without storage polling", async () => {
  const harness = makeHostHarness();

  assert.equal(harness.runtime.start(), "started");
  await harness.waitForBridgeReady();

  assert.equal(harness.runtime.getStateSnapshot().host_ready, true);
  assert.equal(harness.intervals.length, 0);
  assert.equal(harness.bridgeWaiterCount, 1);
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => item.path.startsWith("/v1/bridge/"))
      .map((item) => item.path),
    ["/v1/bridge/host/register", "/v1/bridge/state", "/v1/bridge/host/wait"],
  );
});

test("Panel action starts one Host bridge when OnAddinLoad was not observed", async () => {
  const harness = makeHostHarness();

  harness.runtime.handleRibbonAction("panel");
  await harness.waitForBridgeReady();

  assert.equal(harness.intervals.length, 0);
  assert.equal(harness.bridgeWaiterCount, 1);
  assert.equal(harness.taskpaneCreateCalls.length, 1);
  assert.equal(harness.taskpaneCreateCalls[0].length, 1);
  assert.match(harness.taskpaneCreateCalls[0][0], /taskpane\.html\?v=19$/);
  assert.equal(harness.values.get(TASKPANE_VERSION_KEY), "19");
  assert.ok(harness.events().includes("host.start.lazy.enter"));
  assert.ok(harness.events().includes("host.start.lazy.scheduled"));

  harness.runtime.handleRibbonAction("panel");
  assert.equal(
    harness.apiCalls.filter((item) => item.path === "/v1/bridge/host/register").length,
    1,
  );
});

test("Panel records TaskPane creation and reuse host properties", () => {
  const harness = makeHostHarness();
  harness.runtime.start();

  harness.runtime.handleRibbonAction("panel");

  const created = harness.logs.find((entry) => entry.event === "taskpane.create.completed");
  const shown = harness.logs.find((entry) => entry.event === "taskpane.show.completed");
  const width = harness.logs.find((entry) => entry.event === "taskpane.width.completed");
  const widthStarted = harness.logs.find((entry) => entry.event === "taskpane.width.write.start");
  const rebuilt = harness.logs.find((entry) => entry.event === "taskpane.rebuild.completed");
  assert.equal(created.details.pane_id, "1");
  assert.equal(created.details.pane_visible, false);
  assert.equal(created.details.pane_dock_position, 2);
  assert.equal(shown.details.pane_visible, true);
  assert.equal(shown.details.pane_width, 325);
  assert.equal(shown.details.pane_visible_before, false);
  assert.equal(shown.details.pane_visible_after, true);
  assert.equal(shown.details.pane_visible_effective, true);
  assert.equal(widthStarted.details.pane_width_before, 325);
  assert.equal(widthStarted.details.pane_width_requested, 633);
  assert.equal(width.details.pane_width, 633);
  assert.equal(width.details.pane_width_after, 633);
  assert.equal(width.details.pane_width_effective, true);
  assert.equal(rebuilt.details.pane_branch, "created");
  assert.equal(rebuilt.details.pane_expected_dock_position, 2);
  const snapshots = harness.logs.filter((entry) => entry.event === "taskpane.host_state.snapshot");
  assert.deepEqual(
    snapshots.slice(0, 4).map((entry) => entry.details.checkpoint),
    ["after_open_0ms", "after_open_100ms", "after_open_500ms", "after_open_1000ms"],
  );
  assert.ok(snapshots.slice(0, 4).every((entry) => entry.details.pane_found === true));
  assert.ok(snapshots.slice(0, 4).every((entry) => entry.details.active_document_present === true));

  harness.runtime.handleRibbonAction("panel");

  const reused = harness.logs.filter((entry) => entry.event === "taskpane.reuse.completed").at(-1);
  assert.equal(reused.details.pane_branch, "reused");
  assert.equal(reused.details.pane_visible, true);
  assert.equal(reused.details.pane_width, 633);
  assert.equal(reused.details.pane_dock_position, 2);
});

test("Panel applies the native width after show and returns focus to the document", () => {
  const harness = makeHostHarness();
  harness.runtime.start();

  harness.runtime.handleRibbonAction("panel");

  assert.deepEqual(
    harness.taskpaneOperations.slice(0, 3),
    ["dock:2", "visible:true", "width:633"],
  );
  assert.deepEqual(harness.activationCalls, ["document", "window"]);
  const events = harness.events();
  assert.ok(events.indexOf("taskpane.dock_position.completed") < events.indexOf("taskpane.show.completed"));
  assert.ok(events.indexOf("taskpane.show.completed") < events.indexOf("taskpane.width.completed"));
  assert.ok(events.indexOf("taskpane.show.completed") < events.indexOf("taskpane.document_focus.completed"));
});

test("panel_ready mirrors the successful document lifecycle without window focus", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  await harness.waitForBridgeReady();
  harness.runtime.handleRibbonAction("panel");
  const operationStart = harness.taskpaneOperations.length;
  const activationStart = harness.activationCalls.length;
  const lifecycleStart = harness.documentLifecycleCalls.length;
  const sourcePath = harness.document.FullName;

  await harness.runtime.runCommand(
    "panel_ready",
    requestContext("panel_ready", "request-panel-ready"),
  );

  assert.deepEqual(harness.taskpaneOperations.slice(operationStart), []);
  assert.deepEqual(harness.activationCalls.slice(activationStart), ["document"]);
  assert.deepEqual(
    harness.documentLifecycleCalls.slice(lifecycleStart),
    ["temporary.add", "source.activate", "temporary.close:0"],
  );
  assert.equal(harness.application.ActiveDocument, harness.document);
  assert.equal(harness.document.FullName, sourcePath);
  const events = harness.events();
  assert.ok(events.indexOf("panel_ready.temporary_document.create.completed") < events.indexOf("panel_ready.source_document.activate.completed"));
  assert.ok(events.indexOf("panel_ready.source_document.activate.completed") < events.indexOf("panel_ready.temporary_document.close.completed"));
  assert.ok(events.indexOf("panel_ready.temporary_document.close.completed") < events.indexOf("panel_ready.layout_settle.completed"));
  assert.equal(events.includes("panel_ready.document_focus.completed"), false);
  assert.equal(harness.runtime.getStateSnapshot().active_request.request_status, "PASS");
});

test("panel_ready reports each document lifecycle failure at its source", async () => {
  const cases = [
    {
      code: "WPS_PANEL_READY_DOCUMENT_UNAVAILABLE",
      event: "panel_ready.source_document.missing",
      setup(harness) {
        harness.application.ActiveDocument = null;
      },
    },
    {
      code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_CREATE_FAILED",
      event: "panel_ready.temporary_document.create.failed",
      setup(harness) {
        harness.application.Documents.Add = () => { throw new Error("DOCUMENT_ADD_FAILED"); };
      },
    },
    {
      code: "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED",
      event: "panel_ready.source_document.activate.failed",
      setup(harness) {
        harness.document.Activate = () => { throw new Error("DOCUMENT_ACTIVATE_FAILED"); };
      },
    },
    {
      code: "WPS_PANEL_READY_TEMPORARY_DOCUMENT_CLOSE_FAILED",
      event: "panel_ready.temporary_document.close.failed",
      setup(harness) {
        const addDocument = harness.application.Documents.Add.bind(harness.application.Documents);
        harness.application.Documents.Add = () => {
          const temporaryDocument = addDocument();
          temporaryDocument.Close = () => { throw new Error("DOCUMENT_CLOSE_FAILED"); };
          return temporaryDocument;
        };
      },
    },
  ];

  for (const item of cases) {
    const harness = makeHostHarness();
    harness.runtime.start();
    await harness.waitForBridgeReady();
    item.setup(harness);
    await assert.rejects(
      harness.runtime.runCommand(
        "panel_ready",
        requestContext("panel_ready", `request-${item.code}`),
      ),
      new RegExp(item.code),
    );
    assert.ok(harness.events().includes(item.event), item.event);
    assert.equal(harness.taskpaneCreateCalls.length, 0);
    if (item.code === "WPS_PANEL_READY_SOURCE_DOCUMENT_ACTIVATE_FAILED") {
      assert.deepEqual(harness.documentLifecycleCalls, ["temporary.add", "temporary.close:0"]);
    }
  }
});

test("Panel reuse does not rebuild when returning document focus fails", () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  harness.runtime.handleRibbonAction("panel");
  harness.document.Activate = () => { throw new Error("DOCUMENT_ACTIVATE_FAILED"); };

  assert.throws(
    () => harness.runtime.handleRibbonAction("panel"),
    /WPS_DOCUMENT_ACTIVATE_FAILED/,
  );

  assert.equal(
    harness.events().filter((event) => event === "taskpane.rebuild.start").length,
    1,
  );
  assert.ok(harness.events().includes("taskpane.document_activate.failed"));
});

test("Panel replaces a stale TaskPane page before showing it", () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  const stalePane = harness.application.CreateTaskPane("http://127.0.0.1:3889/taskpane.html");
  stalePane.Visible = true;
  harness.values.set(TASKPANE_KEY, String(stalePane.ID));

  harness.runtime.handleRibbonAction("panel");

  assert.equal(stalePane.Visible, false);
  assert.equal(harness.taskpaneCreateCalls.length, 2);
  assert.match(harness.taskpaneCreateCalls[1][0], /taskpane\.html\?v=19$/);
  assert.equal(harness.values.get(TASKPANE_VERSION_KEY), "19");
  assert.ok(harness.events().includes("taskpane.page_version.mismatch"));
});

test("Bootstrap completion restores one Host long request", async () => {
  const harness = makeHostHarness();

  const firstBootstrapLogs = completeBootstrap(harness, "bootstrap-first");
  await harness.waitForBridgeReady();

  assert.equal(harness.intervals.length, 0);
  assert.equal(harness.bridgeWaiterCount, 1);
  assert.deepEqual(
    firstBootstrapLogs.map((entry) => entry.event),
    ["bootstrap.completed", "bootstrap.host_start.enter", "bootstrap.host_start.completed"],
  );
  assert.equal(
    firstBootstrapLogs.find((entry) => entry.event === "bootstrap.host_start.completed").details.state,
    "started",
  );

  harness.deliverBridgeCommand({
    request_id: "request-after-bootstrap",
    command: "health",
  });
  await harness.waitForBridgeReady();
  const claimed = harness.logs.find((entry) => entry.event === "host.bridge.command.received");
  assert.equal(claimed.details.request_id, "request-after-bootstrap");
  assert.equal(claimed.details.command, "health");
  assert.equal(harness.runtime.getStateSnapshot().status, "PASS");
  assert.equal(harness.bridgeWaiterCount, 1);

  const repeatedBootstrapLogs = completeBootstrap(harness, "bootstrap-first");
  assert.equal(harness.bridgeWaiterCount, 1);
  assert.equal(
    repeatedBootstrapLogs.find((entry) => entry.event === "bootstrap.host_start.completed").details.state,
    "already_started",
  );
});

test("A fresh Bootstrap context starts a fresh Host instance", async () => {
  const first = makeHostHarness({ bootstrapId: "bootstrap-first" });
  const second = makeHostHarness({ bootstrapId: "bootstrap-second" });

  completeBootstrap(first, "bootstrap-first");
  completeBootstrap(second, "bootstrap-second");
  await first.waitForBridgeReady();
  await second.waitForBridgeReady();

  assert.equal(first.bridgeWaiterCount, 1);
  assert.equal(second.bridgeWaiterCount, 1);
  const firstStart = first.logs.find((entry) => entry.event === "host.start.completed");
  const secondStart = second.logs.find((entry) => entry.event === "host.start.completed");
  assert.equal(firstStart.details.bootstrap_id, "bootstrap-first");
  assert.equal(secondStart.details.bootstrap_id, "bootstrap-second");
  assert.notEqual(
    firstStart.details.host_instance_id_short,
    secondStart.details.host_instance_id_short,
  );
});

test("Host bridge registration failure stops the wait chain", async () => {
  const harness = makeHostHarness({
    routeOverride: async ({ path }) => path === "/v1/bridge/host/register" ? {
      ok: false,
      status: 400,
      payload: { ok: false, error_code: "WPS_HOST_REGISTRATION_REJECTED" },
    } : null,
  });
  harness.runtime.start();
  await harness.flushAsync();

  assert.equal(harness.runtime.getBridgeReady(), false);
  const failed = harness.logs.find((item) => item.event === "host.start.failed");
  assert.equal(failed.details.error_code, "WPS_HOST_REGISTRATION_REJECTED");
  assert.equal(failed.details.stage, "bridge_register");
});

test("Host state publish failure stops the wait chain with one stable code", async () => {
  const harness = makeHostHarness({
    routeOverride: async ({ path }) => path === "/v1/bridge/state" ? {
      ok: false,
      status: 400,
      payload: { ok: false, error_code: "WPS_BRIDGE_STATE_REJECTED" },
    } : null,
  });
  harness.runtime.start();
  await harness.flushAsync(20);

  assert.equal(harness.runtime.getBridgeReady(), false);
  const specific = harness.logs.find((item) => item.event === "host.bridge.state.publish_failed");
  const summary = harness.logs.find((item) => item.event === "host.start.failed");
  assert.equal(specific.details.error_code, "WPS_BRIDGE_STATE_REJECTED");
  assert.equal(summary.details.error_code, "WPS_BRIDGE_STATE_REJECTED");
});

test("Host distinguishes TaskPane creation, layout, focus, and storage failures", async () => {
  const cases = [
    {
      code: "WPS_TASKPANE_ID_READ_FAILED",
      event: "taskpane.storage_id.read_failed",
      setup(harness) { harness.storage.failGetKey = TASKPANE_KEY; },
    },
    {
      code: "WPS_TASKPANE_CREATE_FAILED",
      event: "taskpane.create_call.failed",
      setup(harness) {
        harness.application.CreateTaskPane = () => { throw new Error("CREATE_FAILED"); };
      },
    },
    {
      code: "WPS_TASKPANE_DOCK_POSITION_FAILED",
      event: "taskpane.dock_position.failed",
      setup(harness) {
        harness.application.CreateTaskPane = () => {
          const pane = { ID: 99, Visible: false, Width: 640 };
          Object.defineProperty(pane, "DockPosition", {
            get() { return 2; },
            set() { throw new Error("DOCK_POSITION_FAILED"); },
          });
          return pane;
        };
      },
    },
    {
      code: "WPS_DOCUMENT_ACTIVATE_FAILED",
      event: "taskpane.document_activate.failed",
      setup(harness) {
        harness.document.Activate = () => { throw new Error("DOCUMENT_ACTIVATE_FAILED"); };
      },
    },
    {
      code: "WPS_DOCUMENT_WINDOW_ACTIVATE_FAILED",
      event: "taskpane.document_window_activate.failed",
      setup(harness) {
        harness.document.ActiveWindow.Activate = () => { throw new Error("WINDOW_ACTIVATE_FAILED"); };
      },
    },
    {
      code: "WPS_TASKPANE_ID_WRITE_FAILED",
      event: "taskpane.storage_id.write_failed",
      setup(harness) { harness.storage.failSetKey = TASKPANE_KEY; },
    },
  ];

  for (const item of cases) {
    const harness = makeHostHarness();
    harness.runtime.start();
    item.setup(harness);
    await assert.rejects(
      harness.runtime.runCommand(
        "health",
        requestContext("health", `request-${item.code}`),
      ),
      new RegExp(item.code),
    );
    assert.ok(harness.events().includes(item.event), item.event);
    const summary = harness.logs.find((entry) => entry.event === "host.command.failed");
    assert.equal(summary.details.error_code, item.code);
  }
});

test("Host long request distinguishes schema and field failures", async () => {
  const cases = [
    [{ schema_version: "invalid", request_id: "request-1", command: "health" }, "host.bridge.command.schema_invalid"],
    [{ schema_version: "wps-command-v2", command: "health" }, "host.bridge.command.request_id_missing"],
    [{ schema_version: "wps-command-v2", request_id: "request-no-command" }, "host.bridge.command.command_missing"],
  ];
  for (const [command, event] of cases) {
    const harness = makeHostHarness();
    harness.runtime.start();
    await harness.waitForBridgeReady();
    harness.deliverBridgeCommand(command);
    await harness.flushAsync();
    assert.ok(harness.events().includes(event), event);
    assert.equal(harness.runtime.getBridgeReady(), false);
  }
});

test("Host rejects apply bridge commands without matching public authorization", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  await harness.waitForBridgeReady();
  harness.deliverBridgeCommand({
    request_id: "request-apply-no-auth",
    command: "apply",
  });
  await harness.flushAsync();

  assert.ok(harness.events().includes("host.bridge.command.authorization_invalid"));
  assert.equal(harness.runtime.getBridgeReady(), false);
});

test("Host adds a letterhead through the document transaction without recognition", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  const request = requestContext("add_letterhead", "request-add-letterhead");
  request.letterhead = {
    mark_text: "测试机关文件",
    document_number: "测发〔2026〕1号",
    signer: "",
    separator_style: "straight",
    replace_existing: false,
  };

  await harness.runtime.runCommand("add_letterhead", request);

  const businessPaths = harness.apiCalls
    .filter((item) => !item.path.startsWith("/v1/bridge/") && item.path !== "/v1/log")
    .map((item) => item.path);
  assert.deepEqual(businessPaths, [
    "/v1/letterhead/inspect",
    "/v1/letterhead/prepare",
    "/v1/format/commit",
    "/v1/format/finalize",
  ]);
  assert.ok(!businessPaths.includes("/v1/recognize"));
  assert.equal(harness.runtime.getStateSnapshot().message, "版头添加成功。");
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\sample.docx");
});

test("Host inspects a legacy letterhead without permanently upgrading the document", async () => {
  const harness = makeHostHarness();
  harness.document.FullName = "C:\\fixtures\\legacy.doc";
  harness.document.Name = "legacy.doc";
  harness.runtime.start();

  await harness.runtime.runCommand(
    "inspect_letterhead",
    requestContext("inspect_letterhead", "request-inspect-legacy-letterhead"),
  );

  assert.deepEqual(harness.saveAsFormats, [12]);
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => !item.path.startsWith("/v1/bridge/") && item.path !== "/v1/log")
      .map((item) => item.path),
    [
      "/v1/format/upgrade/reserve",
      "/v1/letterhead/inspect",
      "/v1/format/rollback",
    ],
  );
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.doc");
  assert.equal(harness.deletedPaths.length, 1);
  assert.match(harness.deletedPaths[0], /\.docxtool-convert-operation-te\.docx$/);
});

test("Host adds a letterhead to a legacy document and publishes one DOCX", async () => {
  const harness = makeHostHarness();
  harness.document.FullName = "C:\\fixtures\\legacy.wps";
  harness.document.Name = "legacy.wps";
  harness.runtime.start();
  const request = requestContext("add_letterhead", "request-add-legacy-letterhead");
  request.letterhead = {
    mark_text: "测试机关文件",
    document_number: "测发〔2026〕1号",
    signer: "",
    separator_style: "straight",
    replace_existing: false,
  };

  await harness.runtime.runCommand("add_letterhead", request);

  assert.deepEqual(harness.saveAsFormats, [12]);
  assert.deepEqual(
    harness.apiCalls
      .filter((item) => !item.path.startsWith("/v1/bridge/") && item.path !== "/v1/log")
      .map((item) => item.path),
    [
      "/v1/format/upgrade/reserve",
      "/v1/letterhead/inspect",
      "/v1/format/upgrade/prepare",
      "/v1/format/commit",
      "/v1/format/finalize",
    ],
  );
  assert.equal(harness.application.ActiveDocument.FullName, "C:\\fixtures\\legacy.docx");
  assert.equal(harness.runtime.getStateSnapshot().message, "版头添加成功。");
});

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
  let currentAccount = account;
  let currentNowMs = nowMs;
  const HarnessDate = class extends Date {
    static now() { return currentNowMs; }
  };
  const ids = [
    "preview", "apply", "format_settings", "add_letterhead", "clear_preview", "health",
    "format_mode", "reader_mode", "format_mode_tab", "reader_mode_tab",
    "format_main_panel", "format_settings_panel", "format_settings_close",
    "format_settings_restore", "format_settings_save",
    "format_style_settings",
    "format_paper_size", "format_margin_top", "format_margin_bottom", "format_margin_left", "format_margin_right", "format_line_spacing",
    "format_number_font", "format_number_size", "format_letter_font", "format_letter_size",
    "format_page_font", "format_page_size", "format_page_style", "format_page_position",
    "format_scope_mode", "format_page_spec",
    "letterhead_modal", "letterhead_mark", "letterhead_number", "letterhead_signer",
    "letterhead_separator", "letterhead_form_error", "letterhead_cancel", "letterhead_confirm",
    "close_panel", "status", "account", "message", "error", "warnings", "summary", "rows",
    "taskpane_header", "content",
  ];
  for (const id of ids) elements.set(id, makeElement(id));
  elements.get("format_scope_mode").value = "whole";
  elements.get("format_page_spec").value = "";
  elements.get("format_page_spec").focus = () => {};
  elements.get("letterhead_separator").value = "straight";
  elements.get("reader_mode").hidden = true;
  elements.get("format_settings_panel").hidden = true;
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
    bridgeCalls.push({ path, body, headers: options.headers || {} });
    if (path === invalidJsonPath) {
      return { ok: true, status: 200, json: async () => { throw new Error("INVALID_JSON"); } };
    }
    if (path === "/v1/format/default") {
      return response({
        ok: true,
        data: {
          config_version: "config-1",
          format_config: {
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
          },
        },
      });
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
  vm.runInNewContext(TASKPANE_SOURCE, context, { filename: "taskpane.js" });
  return {
    click(id) {
      elements.get(id).listeners.get("click")();
    },
    get activeDocumentReads() { return activeDocumentReads; },
    bridgeCalls,
    commandRequests,
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
  };
}

test("TaskPane resets the WPS viewport again after page load settles", () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });

  assert.deepEqual(harness.scrollCalls, [[0, 0]]);
  assert.equal(harness.document.documentElement.scrollTop, 0);
  assert.equal(harness.document.body.scrollTop, 0);
  assert.equal(harness.elements.get("content").scrollTop, 0);

  harness.document.documentElement.scrollTop = 80;
  harness.document.body.scrollTop = 80;
  harness.elements.get("content").scrollTop = 80;
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();

  assert.deepEqual(harness.scrollCalls, [[0, 0], [0, 0]]);
  assert.equal(harness.document.documentElement.scrollTop, 0);
  assert.equal(harness.document.body.scrollTop, 0);
  assert.equal(harness.elements.get("content").scrollTop, 0);
  const completed = harness.logs.filter(
    (item) => item.event === "taskpane.viewport.reset.completed",
  );
  assert.deepEqual(completed.map((item) => item.details.stage), ["initial", "load_settled"]);
  assert.equal(completed[1].details.root_scroll_top, 0);
  assert.equal(completed[1].details.body_scroll_top, 0);
  assert.equal(completed[1].details.content_scroll_top, 0);
});

test("TaskPane renders protocol statuses in Chinese", async () => {
  const cases = [
    ["READY", "就绪"],
    ["RUNNING", "处理中"],
    ["PASS", "成功"],
    ["FAIL", "失败"],
  ];
  for (const [protocolStatus, displayStatus] of cases) {
    const harness = makeTaskpaneHarness({
      host_ready: true,
      status: protocolStatus,
      updated_at: "1",
    });
    await harness.flushAsync();
    assert.equal(harness.elements.get("status").textContent, displayStatus);
  }

  const notReady = makeTaskpaneHarness({
    host_ready: false,
    status: "NOT_READY",
    updated_at: "1",
  });
  await notReady.flushAsync();
  assert.equal(notReady.elements.get("status").textContent, "未就绪");
});

test("TaskPane switches format and reader modes without submitting reader commands to HostBridge", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();

  assert.deepEqual(harness.readerCalls, ["initialize"]);
  assert.equal(harness.elements.get("format_mode").hidden, false);
  assert.equal(harness.elements.get("reader_mode").hidden, true);
  harness.click("reader_mode_tab");
  await harness.flushAsync();
  assert.equal(harness.elements.get("format_mode").hidden, true);
  assert.equal(harness.elements.get("reader_mode").hidden, false);
  assert.ok(harness.readerCalls.includes("activate"));
  assert.equal(harness.commandRequests.length, 0);

  harness.click("format_mode_tab");
  await harness.flushAsync();
  assert.equal(harness.elements.get("format_mode").hidden, false);
  assert.equal(harness.elements.get("reader_mode").hidden, true);
  assert.ok(harness.readerCalls.includes("deactivate"));
  assert.equal(harness.commandRequests.length, 0);
});

test("TaskPane opens the four-section format settings view and saves the session config", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.click("format_settings");
  await harness.flushAsync();
  assert.equal(harness.elements.get("format_settings_panel").hidden, false);
  assert.equal(harness.elements.get("format_main_panel").hidden, true);
  assert.equal(harness.elements.get("format_style_settings").children.length, 6);
  harness.elements.get("format_margin_top").value = "4.0cm";
  harness.click("format_settings_restore");
  assert.equal(harness.elements.get("format_margin_top").value, "3.7cm");
  harness.elements.get("format_margin_top").value = "4.0cm";
  harness.elements.get("format_page_position").value = "center";
  harness.click("format_settings_save");
  assert.equal(harness.elements.get("format_settings_panel").hidden, true);
  assert.equal(harness.elements.get("format_main_panel").hidden, false);
  harness.click("preview");
  await harness.flushAsync();
  const preview = harness.commandRequests.find((item) => item.command === "preview");
  assert.equal(preview.format_config.page.margin_top_cm, 4);
  assert.equal(preview.format_config.page.lines_per_page, 22);
  assert.equal(preview.format_config.page.grid_alignment, "文字对齐字符网络");
  assert.equal(preview.format_config.page_number.position, "center");
  assert.equal(preview.format_config.page_number.first_page, true);
});

test("TaskPane sends the same saved format config to Preview and Apply", async () => {
  const makeSaved = async () => {
    const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
    await harness.flushAsync();
    harness.click("format_settings");
    await harness.flushAsync();
    harness.elements.get("format_margin_left").value = "3.2cm";
    harness.click("format_settings_save");
    await harness.flushAsync();
    return harness;
  };
  const previewHarness = await makeSaved();
  previewHarness.click("preview");
  await previewHarness.flushAsync();
  const applyHarness = await makeSaved();
  applyHarness.click("apply");
  await applyHarness.flushAsync();
  const previewConfig = previewHarness.commandRequests.find((item) => item.command === "preview").format_config;
  const applyConfig = applyHarness.commandRequests.find((item) => item.command === "apply").format_config;
  assert.deepEqual(previewConfig, applyConfig);
});

test("TaskPane closes format settings without saving draft changes", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.click("format_settings");
  await harness.flushAsync();
  harness.elements.get("format_margin_right").value = "4.0cm";
  harness.click("format_settings_close");
  harness.click("format_settings");
  await harness.flushAsync();
  assert.equal(harness.elements.get("format_margin_right").value, "2.6cm");
});

test("TaskPane submits panel_ready once after READY and load_settled", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();

  assert.equal(harness.commandRequests.length, 0);
  assert.equal(harness.elements.get("preview").disabled, true);

  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();

  assert.equal(harness.commandRequests.length, 1);
  const panelRequest = harness.commandRequests[0];
  assert.equal(panelRequest.command, "panel_ready");
  assert.equal(panelRequest.host_generation, 1);
  assert.equal(harness.elements.get("preview").disabled, true);

  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();
  assert.equal(harness.commandRequests.length, 1);

  harness.pushState({
    host_ready: true,
    status: "READY",
    updated_at: "2",
    active_request: {
      request_id: panelRequest.request_id,
      command: "panel_ready",
      request_status: "CLAIMED",
    },
  });
  await harness.flushAsync();
  harness.pushState({
    host_ready: true,
    status: "READY",
    updated_at: "3",
    active_request: {
      request_id: panelRequest.request_id,
      command: "panel_ready",
      request_status: "PASS",
    },
  });
  await harness.flushAsync();

  assert.equal(harness.elements.get("preview").disabled, false);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.panel_ready.submit.start").length,
    1,
  );
  assert.equal(
    harness.events().filter((event) => event === "taskpane.panel_ready.completed").length,
    1,
  );
  const snapshots = harness.logs.filter(
    (item) => item.event === "taskpane.panel_ready.layout.snapshot",
  );
  assert.deepEqual(snapshots.map((item) => item.details.stage), ["panel_ready_before", "panel_ready_after"]);
  assert.ok(snapshots.every((item) => item.details.window_screen_y === 120));
});

test("TaskPane records bounded first-load geometry, focus, and event-loop probes", () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });

  const initial = harness.logs.find(
    (item) => item.event === "taskpane.layout.snapshot" && item.details.stage === "initial",
  );
  assert.equal(initial.details.inner_width, 380);
  assert.equal(initial.details.inner_height, 720);
  assert.equal(initial.details.header_top, 0);
  assert.equal(initial.details.header_height, 64);
  assert.equal(initial.details.header_clipped_top, false);
  assert.equal(initial.details.document_has_focus, true);
  assert.equal(initial.details.active_element_tag, "BODY");
  assert.equal(initial.details.top_element_id, "taskpane_header");
  assert.equal(initial.details.window_screen_x, 80);
  assert.equal(initial.details.window_screen_y, 120);
  assert.equal(initial.details.screen_width, 1920);
  assert.equal(initial.details.screen_avail_height, 1040);
  assert.equal(initial.details.physical_inner_width, 380);
  assert.equal(initial.details.physical_header_height, 64);
  assert.equal(initial.details.window_top_is_self, true);
  assert.equal(initial.details.frame_element_present, false);
  assert.equal(initial.details.header_transform, "none");

  const header = harness.elements.get("taskpane_header");
  header.rect.top = -64;
  header.rect.bottom = 0;
  harness.document.activeElement = harness.elements.get("content");
  harness.dispatchWindowEvent("resize");

  const clipped = harness.logs.find((item) => item.event === "taskpane.layout.header_clipped");
  assert.equal(clipped.details.stage, "resize");
  assert.equal(clipped.details.header_clipped_top, true);
  assert.equal(clipped.details.top_element_id, "content");
  assert.equal(clipped.details.error_code, "WPS_TASKPANE_HEADER_CLIPPED");

  harness.flushTimeouts();
  const probes = harness.logs.filter((item) => item.event === "taskpane.event_loop.probe");
  assert.deepEqual(probes.map((item) => item.details.scheduled_delay_ms), [100, 500, 1000]);
  assert.ok(probes.every((item) => item.details.timer_drift_ms >= 0));
  assert.ok(probes.every((item) => item.details.state_wait_in_flight === true));

  harness.dispatchWindowEvent("pagehide", { persisted: false });
  harness.dispatchWindowEvent("beforeunload");
  harness.dispatchWindowEvent("unload");
  assert.ok(harness.events().includes("taskpane.lifecycle.pagehide"));
  assert.ok(harness.events().includes("taskpane.lifecycle.beforeunload"));
  assert.ok(harness.events().includes("taskpane.lifecycle.unload"));
});

test("TaskPane blocks not-ready and busy states with distinct events", async () => {
  const notReady = makeTaskpaneHarness({
    host_ready: false,
    status: "NOT_READY",
    updated_at: "1",
  });
  await notReady.flushAsync();
  notReady.click("preview");
  await notReady.flushAsync();
  assert.ok(notReady.events().includes("taskpane.request.blocked.host_not_ready"));
  assert.equal(notReady.elements.get("error").textContent, "错误代码：WPS_HOST_NOT_READY");

  const busy = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await busy.flushAsync();
  busy.click("health");
  await busy.flushAsync();
  busy.click("preview");
  await busy.flushAsync();
  assert.ok(busy.events().includes("taskpane.request.blocked.busy"));
  assert.equal(busy.elements.get("error").textContent, "错误代码：WPS_COMMAND_BUSY");
});

test("TaskPane submits through the bridge and observes claim and completion", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();
  const panelRequest = harness.commandRequests.find((item) => item.command === "panel_ready");
  harness.pushState({
    host_ready: true,
    status: "READY",
    active_request: {
      request_id: panelRequest.request_id,
      command: "panel_ready",
      request_status: "PASS",
    },
  });
  await harness.flushAsync();
  harness.click("preview");
  await harness.flushAsync();
  const clicked = harness.logs.find((item) => item.event === "taskpane.action.clicked");
  assert.equal(clicked.details.command, "preview");
  assert.equal(clicked.details.window_screen_y, 120);
  assert.equal(clicked.details.header_top, 0);
  const request = harness.commandRequests.find((item) => item.command === "preview");
  assert.equal(request.command, "preview");
  assert.equal(request.host_generation, 1);
  assert.ok(harness.events().includes("taskpane.bridge.command.submit.completed"));

  harness.pushState({
    host_ready: true,
    status: "RUNNING",
    updated_at: "2",
    active_request: {
      request_id: request.request_id,
      command: "preview",
      request_status: "CLAIMED",
    },
  });
  await harness.flushAsync();
  harness.pushState({
    host_ready: true,
    status: "PASS",
    updated_at: "3",
    active_request: {
      request_id: request.request_id,
      command: "preview",
      request_status: "PASS",
    },
  });
  await harness.flushAsync();
  assert.ok(harness.events().includes("taskpane.request.claimed"));
  assert.ok(harness.events().includes("taskpane.request.completed"));
  assert.deepEqual(
    harness.logs
      .filter((item) => item.event === "taskpane.command.layout.snapshot")
      .filter((item) => item.details.command === "preview")
      .map((item) => item.details.stage),
    ["request_prepare", "request_claimed", "request_completed"],
  );
  assert.equal(harness.elements.get("preview").disabled, false);
});

test("TaskPane uses the five-second ACK wait after command enqueue", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready);
  await harness.flushAsync();
  harness.click("health");
  await harness.flushAsync();

  harness.pushState(ready);
  await harness.flushAsync();

  const stateWaits = harness.bridgeCalls.filter(
    (item) => item.path === "/v1/bridge/state/wait",
  );
  assert.equal(stateWaits.at(-1).body.timeout_seconds, 5);
});

test("TaskPane sends a pre-format page scope only for specified pages", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const scoped = makeTaskpaneHarness(ready);
  await scoped.flushAsync();
  scoped.elements.get("format_scope_mode").value = "pre_format_pages";
  scoped.elements.get("format_page_spec").value = "3,5-6";
  scoped.click("apply");
  await scoped.flushAsync();
  const scopedRequest = scoped.commandRequests.find((item) => item.command === "apply");
  assert.deepEqual(
    JSON.parse(JSON.stringify(scopedRequest.format_scope)),
    { mode: "pre_format_pages", page_spec: "3,5-6" },
  );

  const whole = makeTaskpaneHarness(ready);
  await whole.flushAsync();
  whole.click("apply");
  await whole.flushAsync();
  const wholeRequest = whole.commandRequests.find((item) => item.command === "apply");
  assert.equal(wholeRequest.format_scope, null);
});

test("TaskPane validates and submits the add-letterhead form in Chinese", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.click("add_letterhead");
  await harness.flushAsync();
  const inspectRequest = harness.commandRequests.find(
    (item) => item.command === "inspect_letterhead",
  );
  assert.ok(inspectRequest);
  harness.pushState({
    host_ready: true,
    status: "PASS",
    active_request: {
      request_id: inspectRequest.request_id,
      command: "inspect_letterhead",
      request_status: "PASS",
    },
    letterhead_inspection: { status: "none", exists: false, fields: null },
  });
  await harness.flushAsync();

  harness.elements.get("letterhead_mark").value = "测试机关文件";
  harness.elements.get("letterhead_number").value = "测发〔2026〕1号";
  harness.elements.get("letterhead_signer").value = "张三";
  harness.elements.get("letterhead_separator").value = "star";
  harness.click("letterhead_confirm");
  await harness.flushAsync();
  const request = harness.commandRequests.find(
    (item) => item.command === "add_letterhead",
  );
  assert.deepEqual(JSON.parse(JSON.stringify(request.letterhead)), {
    mark_text: "测试机关文件",
    document_number: "测发〔2026〕1号",
    signer: "张三",
    separator_style: "star",
    replace_existing: false,
  });

  const invalid = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await invalid.flushAsync();
  invalid.elements.get("letterhead_mark").value = "测试机关文件";
  invalid.elements.get("letterhead_number").value = "格式错误";
  invalid.click("letterhead_confirm");
  await invalid.flushAsync();
  assert.match(
    invalid.elements.get("letterhead_form_error").textContent,
    /发文字号格式应为/,
  );
});

test("TaskPane confirms before replacing an inspected existing letterhead", async () => {
  const harness = makeTaskpaneHarness({
    host_ready: true,
    status: "PASS",
    letterhead_inspection: {
      status: "managed",
      exists: true,
      replaceable: true,
      fields: {
        mark_text: "旧机关文件",
        document_number: "旧发〔2026〕1号",
        signer: "",
        separator_style: "straight",
      },
    },
  });
  let confirmed = 0;
  harness.context.confirm = () => {
    confirmed += 1;
    return true;
  };
  await harness.flushAsync();
  harness.elements.get("letterhead_mark").value = "新机关文件";
  harness.elements.get("letterhead_number").value = "新发〔2026〕2号";
  harness.click("letterhead_confirm");
  await harness.flushAsync();

  const request = harness.commandRequests.find(
    (item) => item.command === "add_letterhead",
  );
  assert.equal(confirmed, 1);
  assert.equal(request.letterhead.replace_existing, true);
});

test("TaskPane rejects an empty specified page range in Chinese", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.elements.get("format_scope_mode").value = "pre_format_pages";
  harness.elements.get("format_page_spec").value = "   ";

  harness.click("apply");
  await harness.flushAsync();

  assert.equal(
    harness.commandRequests.some((item) => item.command === "apply"),
    false,
  );
  assert.equal(harness.elements.get("message").textContent, "请输入有效页码范围。");
});

test("TaskPane accepts a terminal panel_ready PASS that arrives after ACK timeout", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready, { nowMs: 1000 });
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();
  const panelRequest = harness.commandRequests.find((item) => item.command === "panel_ready");

  harness.advanceTime(5001);
  harness.pushState(ready);
  await harness.flushAsync(50);
  assert.ok(harness.events().includes("taskpane.request.timeout"));

  harness.pushState({
    host_ready: true,
    status: "READY",
    updated_at: "2",
    last_request: {
      request_id: panelRequest.request_id,
      command: "panel_ready",
      request_status: "PASS",
    },
  });
  await harness.flushAsync(50);

  assert.ok(harness.events().includes("taskpane.panel_ready.completed"));
  assert.equal(harness.elements.get("preview").disabled, false);
  assert.equal(harness.elements.get("apply").disabled, false);
});

test("TaskPane keeps a late terminal panel_ready FAIL disabled and ignores duplicates", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready, { nowMs: 1000 });
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();
  const panelRequest = harness.commandRequests.find((item) => item.command === "panel_ready");

  harness.advanceTime(5001);
  harness.pushState(ready);
  await harness.flushAsync(50);
  const failureState = {
    host_ready: true,
    status: "FAIL",
    updated_at: "2",
    last_request: {
      request_id: panelRequest.request_id,
      command: "panel_ready",
      request_status: "FAIL",
      error_code: "WPS_PANEL_READY_FAILED",
    },
  };
  harness.pushState(failureState);
  await harness.flushAsync(50);
  harness.pushState(failureState);
  await harness.flushAsync(50);

  assert.equal(
    harness.events().filter((event) => event === "taskpane.panel_ready.failed").length,
    1,
  );
  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(harness.elements.get("apply").disabled, true);
});

test("TaskPane ignores an unrelated terminal state while waiting for panel_ready", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready, { nowMs: 1000 });
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();

  harness.advanceTime(5001);
  harness.pushState(ready);
  await harness.flushAsync(50);
  harness.pushState({
    host_ready: true,
    status: "PASS",
    updated_at: "2",
    last_request: {
      request_id: "unrelated-request",
      command: "health",
      request_status: "PASS",
    },
  });
  await harness.flushAsync(50);

  assert.equal(harness.events().includes("taskpane.panel_ready.completed"), false);
  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(harness.bridgeCalls.filter((item) => item.path === "/v1/bridge/command").length, 1);
});

test("TaskPane stops a panel_ready wait at thirty seconds and prepares a fresh pane", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready, { nowMs: 1000 });
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();

  harness.advanceTime(29999);
  harness.timeoutStateWait();
  await harness.flushAsync(50);
  assert.equal(harness.events().includes("taskpane.panel_ready.terminal_timeout"), false);
  assert.equal(harness.stateWaiterCount, 1);

  harness.advanceTime(1);
  harness.timeoutStateWait();
  await harness.flushAsync(50);

  assert.equal(
    harness.events().filter((event) => event === "taskpane.panel_ready.terminal_timeout").length,
    1,
  );
  assert.equal(harness.stateWaiterCount, 0);
  assert.equal(harness.values.get("docxtool_wps_taskpane_id_v1"), "");
  assert.equal(harness.values.get("docxtool_wps_taskpane_version_v1"), "");
  assert.equal(harness.elements.get("error").textContent, "错误代码：WPS_PANEL_READY_TERMINAL_TIMEOUT");
  assert.match(harness.elements.get("message").textContent, /重启 WPS/);
  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(harness.elements.get("apply").disabled, true);
});

test("TaskPane releases an ordinary command after the five-second ACK timeout", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready, { nowMs: 1000 });
  await harness.flushAsync();
  harness.click("health");
  await harness.flushAsync();

  harness.advanceTime(5001);
  harness.pushState(ready);
  await harness.flushAsync(50);
  harness.click("health");
  await harness.flushAsync();

  assert.equal(harness.commandRequests.filter((item) => item.command === "health").length, 2);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.request.timeout").length,
    1,
  );
  assert.equal(harness.events().includes("taskpane.panel_ready.terminal_timeout"), false);
});

test("TaskPane summary separates confirmed, review, and unresolved preview items", async () => {
  const harness = makeTaskpaneHarness({
    host_ready: true,
    status: "PASS",
    updated_at: "1",
    preview_comment_count: 2,
    preview_confirmed_count: 1,
    preview_review_count: 1,
    recognition: {
      document_mode: "NORMAL",
      block_count: 3,
      unresolved_count: 1,
    },
    recognition_rows: [],
  });
  await harness.flushAsync();

  assert.match(harness.elements.get("summary").textContent, /识别 3 项/);
  assert.match(harness.elements.get("summary").textContent, /文档模式 普通公文/);
  assert.doesNotMatch(harness.elements.get("summary").textContent, /NORMAL/);
  assert.match(harness.elements.get("summary").textContent, /批注 2/);
  assert.match(harness.elements.get("summary").textContent, /确认 1/);
  assert.match(harness.elements.get("summary").textContent, /复核 1/);
  assert.match(harness.elements.get("summary").textContent, /未定位 1/);
});

test("TaskPane groups recognition rows into role counts with confirmation and review badges", async () => {
  const harness = makeTaskpaneHarness({
    host_ready: true,
    status: "PASS",
    updated_at: "1",
    recognition: { document_mode: "NORMAL", block_count: 3, unresolved_count: 0 },
    recognition_rows: [
      { role_name: "一级标题", binding_status: "confirmed", review_level: "confirmed" },
      { role_name: "一级标题", binding_status: "confirmed", review_level: "confirmed" },
      { role_name: "附件", binding_status: "review", review_level: "review" },
    ],
  });
  await harness.flushAsync();

  assert.equal(harness.elements.get("rows").children.length, 2);
  assert.match(harness.elements.get("rows").children[0].textContent, /一级标题 2 项 已确认/);
  assert.match(harness.elements.get("rows").children[1].textContent, /附件 1 项 待复核 1 项/);
  assert.match(harness.elements.get("rows").children[0].innerHTML, /recognition-pill/);
  assert.match(harness.elements.get("rows").children[1].innerHTML, /recognition-review/);
});

test("TaskPane never exposes an internal type id when no Chinese role is supplied", async () => {
  const harness = makeTaskpaneHarness({
    host_ready: true,
    status: "PASS",
    updated_at: "1",
    recognition: { document_mode: "UNKNOWN", block_count: 1, unresolved_count: 0 },
    recognition_rows: [{
      paragraph_index: 0,
      type_id: "internal_future_type",
      role_name: "",
      confidence: 0.9,
      binding_status: "confirmed",
      review_level: "confirmed",
    }],
  });
  await harness.flushAsync();

  assert.match(harness.elements.get("rows").children[0].textContent, /未知/);
  assert.doesNotMatch(
    harness.elements.get("rows").children[0].textContent,
    /internal_future_type/,
  );
});

test("TaskPane clears the pending-result warning after account synchronization", async () => {
  const completed = {
      host_ready: true,
      status: "PASS",
      updated_at: "1",
      result_sync_status: "pending",
      active_request: {
        request_id: "request-apply-sync",
        command: "apply",
        request_status: "PASS",
      },
    };
  const harness = makeTaskpaneHarness(completed, {
    account: {
      signed_in: true,
      username: "User01",
      network_available: false,
      apply_available: false,
      pending_result_count: 1,
      error_code: "WPS_PUBLIC_SERVER_UNAVAILABLE",
    },
  });
  await harness.flushAsync();

  assert.equal(harness.elements.get("status").textContent, "成功");
  assert.match(harness.elements.get("warnings").textContent, /排版已完成，结果尚未同步/);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.result.sync.pending").length,
    1,
  );

  harness.pushState(completed, {
    account: {
      signed_in: true,
      username: "User01",
      network_available: true,
      apply_available: true,
      pending_result_count: 0,
      error_code: "",
    },
  });
  await harness.flushAsync();

  assert.equal(harness.elements.get("warnings").textContent, "");
  assert.equal(
    harness.bridgeCalls.filter((item) => item.path === "/v1/account").length,
    0,
  );
});

test("TaskPane restores apply availability from the bridge account state", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const offlineAccount = {
    signed_in: true,
    username: "User01",
    network_available: false,
    apply_available: false,
    pending_result_count: 0,
    error_code: "WPS_PUBLIC_SERVER_UNAVAILABLE",
  };
  const harness = makeTaskpaneHarness(ready, { account: offlineAccount });
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();
  const panelRequest = harness.commandRequests.find((item) => item.command === "panel_ready");
  harness.pushState({
    host_ready: true,
    status: "READY",
    active_request: {
      request_id: panelRequest.request_id,
      command: "panel_ready",
      request_status: "PASS",
    },
  });
  await harness.flushAsync();
  assert.equal(harness.elements.get("apply").disabled, true);
  assert.equal(harness.elements.get("account").textContent, "User01 · 服务器离线");
  assert.equal(harness.elements.get("message").textContent, "服务器无法连接。");
  assert.equal(
    harness.elements.get("error").textContent,
    "错误代码：WPS_PUBLIC_SERVER_UNAVAILABLE",
  );

  harness.pushState(ready, {
    account: {
      ...offlineAccount,
      network_available: true,
      apply_available: true,
      error_code: "",
    },
  });
  await harness.flushAsync();

  assert.equal(harness.elements.get("apply").disabled, false);
  assert.equal(harness.elements.get("account").textContent, "User01");
});

test("TaskPane distinguishes a missing local account service from server offline", async () => {
  const accountRequired = {
    signed_in: false,
    network_available: false,
    apply_available: false,
    pending_result_count: 0,
    error_code: "WPS_PUBLIC_ACCOUNT_REQUIRED",
  };
  const harness = makeTaskpaneHarness(
    { host_ready: true, status: "READY", updated_at: "1" },
    { account: accountRequired },
  );
  await harness.flushAsync();

  assert.equal(harness.elements.get("account").textContent, "本地账号服务未启动");
  assert.equal(
    harness.elements.get("message").textContent,
    "请从登录窗口登录或注册后重新启动 DocxTool WPS。",
  );
  assert.equal(
    harness.elements.get("error").textContent,
    "错误代码：WPS_PUBLIC_ACCOUNT_REQUIRED",
  );
  assert.equal(harness.elements.get("apply").disabled, true);
  assert.notEqual(harness.elements.get("message").textContent, "服务器无法连接。");
});

test("TaskPane logs bridge command failure before request summary", async () => {
  const harness = makeTaskpaneHarness(
    { host_ready: true, status: "READY", updated_at: "1" },
    { commandFailure: "WPS_COMMAND_BUSY" },
  );
  await harness.flushAsync();
  harness.click("apply");
  await harness.flushAsync();
  const specific = harness.events().indexOf("taskpane.bridge.command.submit.failed");
  const summary = harness.events().indexOf("taskpane.request.failed");
  assert.ok(specific >= 0);
  assert.ok(summary > specific);
  assert.equal(harness.elements.get("error").textContent, "错误代码：WPS_COMMAND_BUSY");
});

test("TaskPane distinguishes an invalid bridge command response", async () => {
  const harness = makeTaskpaneHarness(
    { host_ready: true, status: "READY", updated_at: "1" },
    { invalidJsonPath: "/v1/bridge/command" },
  );
  await harness.flushAsync();
  harness.click("preview");
  await harness.flushAsync();
  const specific = harness.events().indexOf("taskpane.bridge.command.submit.failed");
  const summary = harness.events().indexOf("taskpane.request.failed");
  assert.ok(specific >= 0);
  assert.ok(summary > specific);
  assert.equal(harness.elements.get("error").textContent, "错误代码：WPS_BRIDGE_RESPONSE_INVALID");
});

test("TaskPane stops when its initial state long request fails", async () => {
  const harness = makeTaskpaneHarness(
    { host_ready: true, status: "READY", updated_at: "1" },
    { stateWaitFailure: "WPS_BRIDGE_STATE_UNAVAILABLE" },
  );
  await harness.flushAsync();

  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.bridge.state.wait.failed").length,
    1,
  );
  assert.equal(
    harness.events().filter((event) => event === "taskpane.bridge.state.wait.stopped").length,
    1,
  );
  assert.equal(harness.stateWaiterCount, 0);
  assert.equal(harness.values.get("docxtool_wps_taskpane_id_v1"), "");
  assert.equal(harness.values.get("docxtool_wps_taskpane_version_v1"), "");
  assert.ok(harness.events().includes("taskpane.bridge.state.wait.recovery_prepared"));
});

test("TaskPane stops with a specific error when bridge account state is invalid", async () => {
  const harness = makeTaskpaneHarness(
    { host_ready: true, status: "READY", updated_at: "1" },
    { account: { signed_in: true, apply_available: true } },
  );
  await harness.flushAsync();

  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.account.state.invalid").length,
    1,
  );
  assert.equal(
    harness.events().filter((event) => event === "taskpane.bridge.state.wait.stopped").length,
    1,
  );
  assert.equal(
    harness.elements.get("error").textContent,
    "错误代码：WPS_ACCOUNT_PENDING_RESULT_COUNT_INVALID",
  );
  assert.equal(harness.stateWaiterCount, 0);
});

test("TaskPane stops after the first runtime state long-request failure", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.failNextStateWait("WPS_BRIDGE_STATE_UNAVAILABLE");
  await harness.flushAsync();

  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.bridge.state.wait.failed").length,
    1,
  );
  assert.equal(
    harness.events().filter((event) => event === "taskpane.bridge.state.wait.stopped").length,
    1,
  );
  assert.equal(harness.stateWaiterCount, 0);
});

test("Idle TaskPane keeps one long request and does not touch WPS objects", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();

  assert.equal(harness.stateWaiterCount, 1);
  assert.equal(harness.activeDocumentReads, 0);
  assert.deepEqual(harness.storage.getCalls, []);
  assert.equal(TASKPANE_SOURCE.includes("setInterval("), false);
  assert.equal(HOST_SOURCE.includes("setInterval("), false);
});

test("TaskPane terminates a pending command when Host generation changes", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.click("preview");
  await harness.flushAsync();
  const request = harness.commandRequests[0];

  harness.pushState(
    { host_ready: false, status: "NOT_READY", error_code: "WPS_HOST_CONTEXT_REPLACED" },
    { generationChanged: true, generation: 2 },
  );
  await harness.flushAsync();

  assert.ok(harness.events().includes("taskpane.bridge.host_generation.changed"));
  assert.ok(harness.events().includes("taskpane.request.failed.host_replaced"));
  assert.equal(harness.elements.get("error").textContent, "错误代码：WPS_HOST_CONTEXT_REPLACED");
  assert.ok(request.request_id);
});

test("TaskPane submits panel_ready again after Host generation changes", async () => {
  const ready = { host_ready: true, status: "READY", updated_at: "1" };
  const harness = makeTaskpaneHarness(ready);
  await harness.flushAsync();
  harness.dispatchWindowEvent("load");
  harness.flushTimeouts();
  await harness.flushAsync();
  const firstPanelRequest = harness.commandRequests.find((item) => item.command === "panel_ready");
  harness.pushState({
    host_ready: true,
    status: "READY",
    active_request: {
      request_id: firstPanelRequest.request_id,
      command: "panel_ready",
      request_status: "PASS",
    },
  });
  await harness.flushAsync();

  harness.pushState(ready, { generationChanged: true, generation: 2 });
  await harness.flushAsync();

  const panelRequests = harness.commandRequests.filter((item) => item.command === "panel_ready");
  assert.equal(panelRequests.length, 2);
  assert.equal(panelRequests[1].host_generation, 2);
  assert.notEqual(panelRequests[1].request_id, firstPanelRequest.request_id);
  assert.equal(harness.elements.get("preview").disabled, true);
});

test("Host and TaskPane keep local evidence when log transport is unavailable", () => {
  const host = makeHostHarness({ transport: false });
  assert.throws(() => host.runtime.start(), /WPS_CONTROL_CONFIG_MISSING/);
  assert.ok(host.consoleLines.some((line) => line.includes("log.transport.unavailable")));

  const taskpane = makeTaskpaneHarness(
    { host_ready: false, status: "NOT_READY", updated_at: "1" },
    { transport: false },
  );
  taskpane.click("preview");
  assert.ok(taskpane.consoleLines.some((line) => line.includes("log.transport.unavailable")));
});

test("Bootstrap logs the exact asynchronous child-script boundary that failed", async () => {
  const consoleLines = [];
  const context = {
    Error,
    Math,
    Date,
    console: {
      log(message) {
        consoleLines.push(String(message));
      },
      warn(message) {
        consoleLines.push(String(message));
      },
      error(message) {
        consoleLines.push(String(message));
      },
    },
    fetch: async () => ({ ok: true, json: async () => ({}) }),
    document: {
      readyState: "loading",
      createElement() {
        return {};
      },
      head: {
        appendChild(script) { script.onerror(); },
      },
    },
  };
  context.window = context;
  vm.runInNewContext(MAIN_SOURCE, context, { filename: "main.js" });
  for (let index = 0; index < 8; index += 1) await Promise.resolve();
  assert.ok(
    consoleLines.some((line) => line.includes("bootstrap.bootstrap_log.failed")),
  );
  assert.ok(
    !consoleLines.some((line) => line.includes("bootstrap.runtime_config.failed")),
  );
});
