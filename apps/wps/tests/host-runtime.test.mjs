import {
  BOOTSTRAP_COMPLETE_SOURCE,
  FORMAT_CONFIG_SOURCE,
  HOST_SOURCE,
  MAIN_SOURCE,
  RIBBON_SOURCE,
  TASKPANE_KEY,
  TASKPANE_SOURCE,
  TASKPANE_VERSION_KEY,
  assert,
  bindingItem,
  completeBootstrap,
  createHash,
  makeComments,
  makeDocument,
  makeElement,
  makeHostHarness,
  makeParagraphRange,
  makeStorage,
  makeTaskpaneHarness,
  readFile,
  requestContext,
  sha256,
  test,
  vm,
  webcrypto,
} from "./support/wps-runtime-harness.mjs";

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
  assert.equal(harness.taskpaneCreateCalls.length, 0);
  assert.ok(harness.events().includes("preview.taskpane.open.skipped"));
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
  assert.match(harness.comments.created[0].Author, /^DocxTool复核·/);
  assert.equal(harness.comments.created[0].Initial, "DCR");
  const state = harness.runtime.getStateSnapshot();
  assert.equal(state.preview_comment_count, 1);
  assert.equal(state.preview_confirmed_count, 0);
  assert.equal(state.preview_review_count, 1);
});

test("Host preview comments use Chinese format names without internal type ids", async () => {
  const expectedByType = {
    title: "主标题", title_cont: "主标题续行", dispatch_number: "发文字号",
    addressing: "称呼", body: "正文",
    heading1: "一级标题", heading2: "二级标题", heading3: "三级标题", heading4: "四级标题",
    responsibility_line: "责任单位", meeting_meta: "会议信息", meeting_title_meta: "会议标题信息",
    sign_org: "落款单位", sign_date: "落款日期", note: "来源或注释",
    embedded_document_title: "内嵌文档标题", attachment_note: "附件说明",
    attachment_title: "附件正文标题", date_line: "日期", author_line: "作者",
    role_name: "职务姓名", title2: "正文标题", glossary_title: "名词解释标题",
    glossary_item: "名词解释条目", attachment_note_item: "附件说明续项",
    attachment_page_mark: "附件正文标记", attachment_body: "附件正文",
    list: "列表", list_item: "列表项", quote: "引文", annotation: "注释", closing: "结束语",
    number: "数字", letter: "字母", page_number: "页码", superscript: "上标",
    __object_caption__: "对象题注", __table__: "表格", __image__: "图片",
    __letterhead__: "版头", internal_future_type: "未知格式",
  };
  const entries = Object.entries(expectedByType);
  const rawText = "A".repeat(entries.length);
  const items = entries.map(([typeId], index) => (
    bindingItem(rawText, index, index + 1, index, { type_id: typeId })
  ));
  const harness = makeHostHarness({ rawText, bindingItems: items });
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-chinese-format-names"),
  );

  assert.deepEqual(
    harness.comments.created.map((item) => item.Text.match(/^识别格式：([^；]+)/)?.[1]),
    entries.map(([, roleName]) => roleName),
  );
  for (const comment of harness.comments.created) {
    assert.doesNotMatch(comment.Text, /\b[a-z][a-z0-9_]*\b/i);
  }
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

test("Host logs safe boundary diagnostics when the final preview character is unavailable", async () => {
  const harness = makeHostHarness();
  const characters = harness.document.Paragraphs.Item(1).Range.Characters;
  const originalItem = characters.Item.bind(characters);
  characters.Count = 4;
  characters.Item = (index) => Number(index) === 4 ? null : originalItem(index);
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-boundary-diagnostics"),
    ),
    /PREVIEW_RANGE_BOUNDARY_INVALID/,
  );

  const failure = harness.logs.find((item) => item.event === "preview.range.boundary_invalid");
  assert.ok(failure);
  assert.deepEqual(
    {
      host_paragraph_index: failure.details.host_paragraph_index,
      start_utf16: failure.details.start_utf16,
      end_utf16: failure.details.end_utf16,
      raw_length: failure.details.raw_length,
      characters_count: failure.details.characters_count,
      first_ordinal: failure.details.first_ordinal,
      end_ordinal: failure.details.end_ordinal,
      first_boundary_present: failure.details.first_boundary_present,
      last_boundary_present: failure.details.last_boundary_present,
      set_range_available: failure.details.set_range_available,
    },
    {
      host_paragraph_index: 0,
      start_utf16: 0,
      end_utf16: 4,
      raw_length: 4,
      characters_count: 4,
      first_ordinal: 0,
      end_ordinal: 4,
      first_boundary_present: true,
      last_boundary_present: false,
      set_range_available: true,
    },
  );
  assert.equal(harness.comments.created.length, 0);
});

function installGroupedCharacters(harness, groupedCharacters) {
  const characters = harness.document.Paragraphs.Item(1).Range.Characters;
  characters.Count = groupedCharacters.length;
  characters.Item = (index) => {
    const ordinal = Number(index) - 1;
    if (ordinal < 0 || ordinal >= groupedCharacters.length) return null;
    return {
      Start: ordinal,
      End: ordinal + 1,
      Text: groupedCharacters[ordinal],
      SetRange(nextStart, nextEnd) {
        this.Start = nextStart;
        this.End = nextEnd;
        this.Text = groupedCharacters.slice(nextStart, nextEnd).join("");
      },
    };
  };
}

test("Host maps in-range UTF-16 offsets through WPS grouped character ranges", async () => {
  const rawText = "A\u0301B\u0301C\u0301D\u0301E\u0301F";
  const groupedCharacters = ["A\u0301", "B\u0301", "C\u0301", "D\u0301", "E\u0301", "F"];
  const startUtf16 = 2;
  const endUtf16 = 4;
  const harness = makeHostHarness({
    rawText,
    bindingItems: [bindingItem(rawText, startUtf16, endUtf16)],
  });
  installGroupedCharacters(harness, groupedCharacters);
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-grouped-in-range-character-range"),
  );

  assert.equal(harness.comments.created.length, 1);
  assert.equal(harness.comments.created[0].Range.Text, "B\u0301");
  assert.ok(!harness.events().includes("preview.range.readback_mismatch"));
});

test("Host maps UTF-16 preview offsets through WPS grouped character ranges", async () => {
  const rawText = "A\u0301B\u0301C\u0301D\u0301E\u0301F";
  const groupedCharacters = ["A\u0301", "B\u0301", "C\u0301", "D\u0301", "E\u0301", "F"];
  const startUtf16 = 2;
  const endUtf16 = 10;
  const harness = makeHostHarness({
    rawText,
    bindingItems: [bindingItem(rawText, startUtf16, endUtf16)],
  });
  installGroupedCharacters(harness, groupedCharacters);
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-grouped-character-range"),
  );

  assert.equal(harness.comments.created.length, 1);
  assert.equal(harness.comments.created[0].Range.Text, rawText.slice(startUtf16, endUtf16));
  assert.ok(harness.events().includes("preview.range.revalidate.completed"));
  assert.ok(!harness.events().includes("preview.range.boundary_invalid"));
});

test("Host rejects a UTF-16 offset inside a WPS grouped character", async () => {
  const rawText = "A\u0301B\u0301";
  const groupedCharacters = ["A\u0301", "B\u0301"];
  const harness = makeHostHarness({
    rawText,
    bindingItems: [bindingItem(rawText, 1, 2)],
  });
  installGroupedCharacters(harness, groupedCharacters);
  harness.runtime.start();

  await assert.rejects(
    harness.runtime.runCommand(
      "preview",
      requestContext("preview", "request-grouped-invalid-boundary"),
    ),
    /HOST_RANGE_UTF16_BOUNDARY_INVALID/,
  );

  assert.equal(harness.comments.created.length, 0);
  assert.ok(harness.events().includes("preview.range.utf16_boundary_invalid"));
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
  const [confirmedComment, reviewComment] = harness.comments.created;
  assert.match(confirmedComment.Author, /^DocxTool·/);
  assert.equal(confirmedComment.Initial, "DCT");
  assert.doesNotMatch(confirmedComment.Text, /建议人工复核/);
  assert.notEqual(confirmedComment.Text, "");
  assert.match(reviewComment.Author, /^DocxTool复核·/);
  assert.equal(reviewComment.Initial, "DCR");
  assert.match(reviewComment.Text, /建议人工复核/);
  assert.notEqual(reviewComment.Text, "");
  assert.notEqual(confirmedComment.Author, reviewComment.Author);
  const documentPathHash = sha256("c:\\fixtures\\sample.docx");
  const session = JSON.parse(harness.values.get(`docxtool_wps_preview_v2:${documentPathHash}`));
  assert.equal(session.schema_version, 2);
  assert.equal(session.authors.confirmed.author, confirmedComment.Author);
  assert.equal(session.authors.confirmed.initial, "DCT");
  assert.equal(session.authors.review.author, reviewComment.Author);
  assert.equal(session.authors.review.initial, "DCR");
  const state = harness.runtime.getStateSnapshot();
  assert.equal(state.preview_confirmed_count, 1);
  assert.equal(state.preview_review_count, 1);
  assert.equal(state.recognition.unresolved_count, 1);
 });

test("Host labels a same-paragraph heading and body as inline body", async () => {
  const harness = makeHostHarness({
    bindingItems: [bindingItem("ABCD", 0, 4, 0, { type_id: "heading2", inline_body: true })],
  });
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-inline-body-label"),
  );

  assert.equal(harness.comments.created.length, 1);
  assert.match(harness.comments.created[0].Text, /二级标题\+行内正文/);
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
  const items = [
    bindingItem("ABCD", 0, 2, 0),
    bindingItem("ABCD", 2, 4, 1, {
      binding_status: "review",
      review_level: "critical_review",
      recommended_action: "preview_only",
    }),
  ];
  const harness = makeHostHarness({ bindingItems: items });
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

  assert.equal(harness.comments.created.length, 2);
  assert.equal(harness.comments.created[0].Initial, "DCT");
  assert.equal(harness.comments.created[1].Initial, "DCR");
  assert.ok(harness.comments.created.every((comment) => comment.deleted));
  assert.ok(harness.events().includes("preview.session.write_failed"));
  assert.ok(harness.events().includes("preview.comments.rollback.completed"));
  assert.ok(!harness.events().includes("preview.comments.completed"));
});

test("Host clears both preview authors without deleting user or other plugin comments", async () => {
  const items = [
    bindingItem("ABCD", 0, 2, 0),
    bindingItem("ABCD", 2, 4, 1, {
      binding_status: "review",
      recommended_action: "preview_only",
    }),
  ];
  const harness = makeHostHarness({ bindingItems: items });
  harness.runtime.start();

  await harness.runtime.runCommand(
    "preview",
    requestContext("preview", "request-dual-author-preview"),
  );

  const userComment = harness.comments.Add({}, "");
  userComment.Author = "本机用户";
  userComment.Initial = "用户";
  const otherPluginComment = harness.comments.Add({}, "其他插件批注");
  otherPluginComment.Author = "OtherPlugin";
  otherPluginComment.Initial = "OTP";

  await harness.runtime.runCommand(
    "clear_preview",
    requestContext("clear_preview", "request-dual-author-clear"),
  );

  assert.equal(harness.comments.created[0].deleted, true);
  assert.equal(harness.comments.created[1].deleted, true);
  assert.equal(userComment.deleted, false);
  assert.equal(otherPluginComment.deleted, false);
});

test("Host clears legacy single-author preview sessions", async () => {
  const harness = makeHostHarness();
  const legacyComment = harness.comments.Add({}, "旧版预览批注");
  legacyComment.Author = "DocxTool·legacy01";
  legacyComment.Initial = "DCT";
  const userComment = harness.comments.Add({}, "");
  userComment.Author = "本机用户";
  userComment.Initial = "用户";
  const documentPathHash = sha256("c:\\fixtures\\sample.docx");
  harness.values.set(
    `docxtool_wps_preview_v2:${documentPathHash}`,
    JSON.stringify({
      session_id: "legacy-session",
      author: legacyComment.Author,
      initial: legacyComment.Initial,
    }),
  );
  harness.runtime.start();

  await harness.runtime.runCommand(
    "clear_preview",
    requestContext("clear_preview", "request-legacy-author-clear"),
  );

  assert.equal(legacyComment.deleted, true);
  assert.equal(userComment.deleted, false);
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
  assert.match(harness.taskpaneCreateCalls[0][0], /taskpane\.html\?v=27$/);
  assert.equal(harness.values.get(TASKPANE_VERSION_KEY), "27");
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
  assert.equal(widthStarted.details.pane_width_requested, 422);
  assert.equal(width.details.pane_width, 422);
  assert.equal(width.details.pane_width_after, 422);
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
  assert.equal(reused.details.pane_branch, "memory_reused");
  assert.equal(reused.details.pane_visible, true);
  assert.equal(reused.details.pane_width, 422);
  assert.equal(reused.details.pane_dock_position, 2);
});

test("Panel applies the native width after show and returns focus to the document", () => {
  const harness = makeHostHarness();
  harness.runtime.start();

  harness.runtime.handleRibbonAction("panel");

  assert.deepEqual(
    harness.taskpaneOperations.slice(0, 3),
    ["dock:2", "visible:true", "width:422"],
  );
  assert.deepEqual(harness.activationCalls, ["document", "window"]);
  const events = harness.events();
  assert.ok(events.indexOf("taskpane.dock_position.completed") < events.indexOf("taskpane.show.completed"));
  assert.ok(events.indexOf("taskpane.show.completed") < events.indexOf("taskpane.width.completed"));
  assert.ok(events.indexOf("taskpane.show.completed") < events.indexOf("taskpane.document_focus.completed"));
});

test("Panel reuses the in-process TaskPane even when persistent pane storage was cleared", async () => {
  const harness = makeHostHarness();
  harness.runtime.start();
  harness.runtime.handleRibbonAction("panel");
  harness.values.set(TASKPANE_KEY, "");
  harness.values.set(TASKPANE_VERSION_KEY, "");

  await harness.runtime.runCommand(
    "health",
    { ...requestContext("health", "request-memory-pane-reuse"), source: "ribbon" },
  );

  assert.equal(harness.taskpaneCreateCalls.length, 1);
  assert.ok(harness.events().includes("taskpane.memory_reuse.completed"));
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
  assert.match(harness.taskpaneCreateCalls[1][0], /taskpane\.html\?v=27$/);
  assert.equal(harness.values.get(TASKPANE_VERSION_KEY), "27");
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
        { ...requestContext("health", `request-${item.code}`), source: "ribbon" },
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
