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
const BOOTSTRAP_COMPLETE_SOURCE = await readFile(
  new URL("../js/bootstrap-complete.js", import.meta.url),
  "utf8",
);

const STATE_KEY = "docxtool_wps_state_v1";
const REQUEST_KEY = "docxtool_wps_request_v1";
const TASKPANE_KEY = "docxtool_wps_taskpane_id_v1";

function sha256(value) {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function makeStorage(initial = {}) {
  const values = new Map(Object.entries(initial));
  const storage = {
    failGetKey: "",
    failSetKey: "",
    getItem(key) {
      if (key === this.failGetKey) throw new Error("STORAGE_GET_FAILED");
      return values.get(key) ?? "";
    },
    setItem(key, value) {
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

function makeDocument(rawText, comments) {
  const paragraphRange = makeParagraphRange(rawText);
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
      Count: 1,
      Item(index) {
        assert.equal(index, 1);
        return { Range: paragraphRange };
      },
    },
  };
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
} = {}) {
  const { storage, values } = makeStorage({
    [REQUEST_KEY]: "stale-request",
    [STATE_KEY]: JSON.stringify({ status: "STALE" }),
  });
  const comments = makeComments({ failAddAt, failMetadataAt, failDeleteAt });
  const { document, paragraphRange } = makeDocument(rawText, comments);
  const logs = [];
  const apiCalls = [];
  const intervals = [];
  const panes = [];
  const taskpaneCreateCalls = [];
  const bridgePaths = [];
  const saveAsFormats = [];
  const deletedPaths = [];
  const application = {
    ActiveDocument: document,
    PluginStorage: storage,
    ribbonUI: { Invalidate() {} },
    CreateTaskPane(...args) {
      taskpaneCreateCalls.push(args);
      const pane = { ID: panes.length + 1, Visible: false, Width: 0 };
      panes.push(pane);
      return pane;
    },
    GetTaskPane(id) {
      return panes.find((item) => item.ID === id) || null;
    },
    Documents: {
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
    if (path === "/v1/recognize") {
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
    bridgePaths,
    comments,
    consoleLines,
    context,
    document,
    deletedPaths,
    events: () => logs.map((item) => item.event),
    intervals,
    logs,
    apiCalls,
    runtime: context.DocxToolHostRuntime,
    saveAsFormats,
    storage,
    taskpaneCreateCalls,
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

test("Host preview keeps one request_id through save, binding, Range, and comments", async () => {
  const harness = makeHostHarness();
  assert.equal(harness.runtime.start(), "started");
  assert.equal(JSON.parse(harness.values.get(STATE_KEY)).host_ready, true);
  assert.equal(harness.values.get(REQUEST_KEY), "");

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
  const state = JSON.parse(harness.values.get(STATE_KEY));
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
  const state = JSON.parse(harness.values.get(STATE_KEY));
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
});

test("Host operation logs identify the active document by file name", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();

  await harness.runtime.runCommand(
    "health",
    requestContext("health", "request-document-name"),
  );

  const started = harness.logs.find((item) => item.event === "host.command.start");
  assert.equal(started.details.document_name, "sample.docx");
  assert.ok(!started.details.document_name.includes("\\"));
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
  const state = JSON.parse(harness.values.get(STATE_KEY));
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
  const state = JSON.parse(harness.values.get(STATE_KEY));
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
  const state = JSON.parse(harness.values.get(STATE_KEY));
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

test("Host start logs PluginStorage reset failure and does not publish READY", () => {
  const harness = makeHostHarness();
  harness.storage.failSetKey = REQUEST_KEY;

  assert.throws(() => harness.runtime.start(), /WPS_HOST_STORAGE_RESET_FAILED/);
  const specific = harness.events().indexOf("host.storage.reset.failed");
  const summary = harness.events().indexOf("host.start.failed");
  assert.ok(specific >= 0);
  assert.ok(summary > specific);
  assert.notEqual(harness.values.get(STATE_KEY), JSON.stringify({ host_ready: true }));
});

test("Panel action starts Host when WPS reused the add-in without OnAddinLoad", () => {
  const harness = makeHostHarness();

  harness.runtime.handleRibbonAction("panel");

  assert.equal(JSON.parse(harness.values.get(STATE_KEY)).host_ready, true);
  assert.equal(harness.intervals.length, 1);
  assert.equal(harness.taskpaneCreateCalls.length, 1);
  assert.equal(harness.taskpaneCreateCalls[0].length, 1);
  assert.ok(harness.events().includes("host.start.lazy.enter"));
  assert.ok(harness.events().includes("host.start.lazy.completed"));

  harness.runtime.handleRibbonAction("panel");
  assert.equal(harness.intervals.length, 1);
  assert.equal(
    harness.events().filter((event) => event === "host.start.completed").length,
    1,
  );
});

test("Bootstrap completion restores one Host poller and logs its first tick", () => {
  const harness = makeHostHarness();

  const firstBootstrapLogs = completeBootstrap(harness, "bootstrap-first");

  assert.equal(harness.intervals.length, 1);
  assert.deepEqual(
    firstBootstrapLogs.map((entry) => entry.event),
    ["bootstrap.completed", "bootstrap.host_start.enter", "bootstrap.host_start.completed"],
  );
  assert.equal(
    firstBootstrapLogs.find((entry) => entry.event === "bootstrap.host_start.completed").details.state,
    "started",
  );

  harness.values.set(REQUEST_KEY, JSON.stringify({
    schema_version: "wps-request-v2",
    request_id: "request-after-bootstrap",
    command_name: "health",
    pane_instance_id: "pane-after-bootstrap",
  }));
  harness.intervals[0]();
  harness.intervals[0]();
  assert.equal(
    harness.events().filter((event) => event === "host.poll.first_tick").length,
    1,
  );
  assert.ok(harness.events().includes("host.storage.request.observed"));
  const claimed = harness.logs.find((entry) => entry.event === "host.request.claimed");
  assert.equal(claimed.details.request_id, "request-after-bootstrap");
  assert.equal(claimed.details.command, "health");

  const repeatedBootstrapLogs = completeBootstrap(harness, "bootstrap-first");
  assert.equal(harness.intervals.length, 1);
  assert.equal(
    repeatedBootstrapLogs.find((entry) => entry.event === "bootstrap.host_start.completed").details.state,
    "already_started",
  );
});

test("A fresh Bootstrap context starts a fresh Host instance", () => {
  const first = makeHostHarness({ bootstrapId: "bootstrap-first" });
  const second = makeHostHarness({ bootstrapId: "bootstrap-second" });

  completeBootstrap(first, "bootstrap-first");
  completeBootstrap(second, "bootstrap-second");

  assert.equal(first.intervals.length, 1);
  assert.equal(second.intervals.length, 1);
  const firstStart = first.logs.find((entry) => entry.event === "host.start.completed");
  const secondStart = second.logs.find((entry) => entry.event === "host.start.completed");
  assert.equal(firstStart.details.bootstrap_id, "bootstrap-first");
  assert.equal(secondStart.details.bootstrap_id, "bootstrap-second");
  assert.notEqual(
    firstStart.details.host_instance_id_short,
    secondStart.details.host_instance_id_short,
  );
});

test("Bootstrap completion logs the exact Host startup failure", () => {
  const harness = makeHostHarness();
  harness.storage.failSetKey = REQUEST_KEY;

  assert.throws(
    () => completeBootstrap(harness, "bootstrap-failed"),
    /WPS_HOST_STORAGE_RESET_FAILED/,
  );

  const failed = harness.bootstrapLogs.find(
    (entry) => entry.event === "bootstrap.host_start.failed",
  );
  assert.equal(failed.details.bootstrap_id, "bootstrap-failed");
  assert.equal(failed.details.stage, "host_start");
  assert.equal(failed.details.error_code, "WPS_HOST_STORAGE_RESET_FAILED");
});

test("Panel lazy Host start preserves the original startup failure", () => {
  const harness = makeHostHarness();
  harness.storage.failSetKey = REQUEST_KEY;

  assert.throws(
    () => harness.runtime.handleRibbonAction("panel"),
    /WPS_HOST_STORAGE_RESET_FAILED/,
  );
  const specific = harness.logs.find((item) => item.event === "host.start.lazy.failed");
  assert.equal(specific.details.error_code, "WPS_HOST_STORAGE_RESET_FAILED");
  assert.ok(!harness.events().includes("taskpane.rebuild.completed"));
});

test("Host state write failure keeps one stable error code", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  harness.storage.failSetKey = STATE_KEY;

  await assert.rejects(
    harness.runtime.runCommand(
      "health",
      requestContext("health", "request-state-fail"),
    ),
    /WPS_STATE_WRITE_FAILED/,
  );
  const specific = harness.logs.find((item) => item.event === "host.state.write_failed");
  const summary = harness.logs.find((item) => item.event === "host.command.failed");
  assert.equal(specific.details.error_code, "WPS_STATE_WRITE_FAILED");
  assert.equal(summary.details.error_code, "WPS_STATE_WRITE_FAILED");
});

test("Host distinguishes TaskPane id, create, and id-write failures", async () => {
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

test("Host request polling distinguishes JSON, schema, id, and command failures", () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  const poll = harness.intervals[0];
  const cases = [
    ["{", "host.request.parse.failed"],
    [JSON.stringify({}), "host.request.schema_invalid"],
    [JSON.stringify({ schema_version: "wps-request-v2", command_name: "health" }), "host.request.id_missing"],
    [JSON.stringify({ schema_version: "wps-request-v2", request_id: "request-no-command" }), "host.request.command_missing"],
  ];
  for (const [value, event] of cases) {
    harness.values.set(REQUEST_KEY, value);
    poll();
    assert.ok(harness.events().includes(event), event);
    assert.equal(harness.values.get(REQUEST_KEY), "");
  }
});

function makeElement(id) {
  return {
    id,
    disabled: false,
    textContent: "",
    listeners: new Map(),
    addEventListener(name, callback) {
      this.listeners.set(name, callback);
    },
    replaceChildren() {},
  };
}

function makeTaskpaneHarness(initialState, { transport = true, failGetKey = "" } = {}) {
  const { storage, values } = makeStorage({
    [STATE_KEY]: JSON.stringify(initialState),
  });
  storage.failGetKey = failGetKey;
  const elements = new Map();
  const logs = [];
  const consoleLines = [];
  const intervals = [];
  const clearedIntervals = [];
  const ids = [
    "preview", "apply", "clear_preview", "health", "focus_document",
    "close_panel", "status", "message", "error", "warnings", "summary", "rows",
  ];
  for (const id of ids) elements.set(id, makeElement(id));
  const document = {
    getElementById(id) {
      return elements.get(id) || null;
    },
    createElement() {
      return { className: "", textContent: "" };
    },
  };
  async function fetch(_url, options) {
    logs.push(JSON.parse(options.body));
    return { ok: true, status: 200 };
  }
  const context = {
    Application: {
      PluginStorage: storage,
      ActiveDocument: null,
      GetTaskPane() {
        return null;
      },
    },
    Date,
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
    setInterval(callback) {
      intervals.push(callback);
      return intervals.length;
    },
    clearInterval(id) {
      clearedIntervals.push(id);
    },
    DocxToolWpsConfig: transport ? {
      controlBaseUrl: "http://127.0.0.1:9527",
      sessionToken: "test-token",
    } : {},
  };
  context.window = context;
  vm.runInNewContext(TASKPANE_SOURCE, context, { filename: "taskpane.js" });
  return {
    click(id) {
      elements.get(id).listeners.get("click")();
    },
    clearedIntervals,
    consoleLines,
    elements,
    events: () => logs.map((item) => item.event),
    intervals,
    logs,
    storage,
    values,
  };
}

test("TaskPane blocks not-ready and busy states with distinct events", () => {
  const notReady = makeTaskpaneHarness({
    host_ready: false,
    status: "NOT_READY",
    updated_at: "1",
  });
  notReady.click("preview");
  assert.ok(notReady.events().includes("taskpane.request.blocked.host_not_ready"));
  assert.equal(notReady.elements.get("error").textContent, "WPS_HOST_NOT_READY");

  const busy = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  busy.values.set(REQUEST_KEY, "occupied");
  busy.click("health");
  assert.ok(busy.events().includes("taskpane.request.blocked.busy"));
  assert.equal(busy.elements.get("error").textContent, "WPS_COMMAND_BUSY");
});

test("TaskPane writes, verifies, observes claim, and observes completion", () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  harness.click("preview");
  const request = JSON.parse(harness.values.get(REQUEST_KEY));
  assert.equal(request.schema_version, "wps-request-v2");
  assert.equal(request.command_name, "preview");
  assert.ok(harness.events().includes("taskpane.storage.write.verified"));

  harness.values.set(STATE_KEY, JSON.stringify({
    host_ready: true,
    status: "RUNNING",
    updated_at: "2",
    active_request: { request_id: request.request_id, request_status: "CLAIMED" },
  }));
  harness.intervals[0]();
  harness.values.set(STATE_KEY, JSON.stringify({
    host_ready: true,
    status: "PASS",
    updated_at: "3",
    active_request: { request_id: request.request_id, request_status: "PASS" },
  }));
  harness.intervals[0]();
  assert.ok(harness.events().includes("taskpane.request.claimed"));
  assert.ok(harness.events().includes("taskpane.request.completed"));
  assert.equal(harness.elements.get("preview").disabled, false);
});

test("TaskPane summary separates confirmed, review, and unresolved preview items", () => {
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

  assert.match(harness.elements.get("summary").textContent, /识别 3 项/);
  assert.match(harness.elements.get("summary").textContent, /批注 2/);
  assert.match(harness.elements.get("summary").textContent, /确认 1/);
  assert.match(harness.elements.get("summary").textContent, /复核 1/);
  assert.match(harness.elements.get("summary").textContent, /未定位 1/);
});

test("TaskPane logs request-slot write failure before request summary", () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  harness.storage.failSetKey = REQUEST_KEY;
  harness.click("apply");
  const specific = harness.events().indexOf("taskpane.storage.write.failed");
  const summary = harness.events().indexOf("taskpane.request.failed");
  assert.ok(specific >= 0);
  assert.ok(summary > specific);
  assert.equal(harness.elements.get("error").textContent, "WPS_REQUEST_SLOT_WRITE_FAILED");
});

test("TaskPane distinguishes invalid request readback JSON", () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  const originalSet = harness.storage.setItem.bind(harness.storage);
  harness.storage.setItem = (key, value) => {
    originalSet(key, key === REQUEST_KEY ? "{" : value);
  };
  harness.click("preview");
  const specific = harness.events().indexOf("taskpane.storage.readback.parse_failed");
  const summary = harness.events().indexOf("taskpane.request.failed");
  assert.ok(specific >= 0);
  assert.ok(summary > specific);
  assert.equal(harness.elements.get("error").textContent, "WPS_REQUEST_READBACK_JSON_INVALID");
});

test("TaskPane does not start polling when initial state storage is unavailable", () => {
  const harness = makeTaskpaneHarness(
    { host_ready: true, status: "READY", updated_at: "1" },
    { failGetKey: STATE_KEY },
  );

  assert.equal(harness.intervals.length, 0);
  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.state.read_failed").length,
    1,
  );
  assert.ok(harness.events().includes("taskpane.load.failed"));
});

test("TaskPane stops polling after the first runtime state storage failure", () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  harness.storage.failGetKey = STATE_KEY;

  harness.intervals[0]();
  harness.intervals[0]();

  assert.deepEqual(harness.clearedIntervals, [1]);
  assert.equal(harness.elements.get("preview").disabled, true);
  assert.equal(
    harness.events().filter((event) => event === "taskpane.state.read_failed").length,
    1,
  );
  assert.equal(
    harness.events().filter((event) => event === "taskpane.poll.stopped.storage_failure").length,
    1,
  );
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

test("Bootstrap logs the exact child-script boundary that failed", () => {
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
    document: {
      readyState: "loading",
      write() {
        throw new Error("SCRIPT_WRITE_FAILED");
      },
    },
  };
  context.window = context;
  assert.throws(
    () => vm.runInNewContext(MAIN_SOURCE, context, { filename: "main.js" }),
    /SCRIPT_WRITE_FAILED/,
  );
  assert.ok(
    consoleLines.some((line) => line.includes("bootstrap.bootstrap_log.failed")),
  );
  assert.ok(
    !consoleLines.some((line) => line.includes("bootstrap.runtime_config.failed")),
  );
});
