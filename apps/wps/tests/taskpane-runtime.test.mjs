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

test("TaskPane opens the central format settings dialog without hiding the main panel", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.click("format_settings");
  await harness.flushAsync();
  assert.equal(harness.elements.get("format_main_panel").hidden, false);
  assert.equal(harness.dialogCalls.length, 1, JSON.stringify({ events: harness.events(), error: harness.elements.get("error").textContent, message: harness.elements.get("message").textContent }));
  assert.match(harness.dialogCalls[0][0], /format-settings\.html\?v=2$/);
  assert.equal(harness.dialogCalls[0][1], "格式设置");
  assert.equal(harness.dialogCalls[0][4], true);
  assert.equal(harness.dialogCalls[0][5], false);
  assert.equal(harness.dialogCalls[0][9], true);
  assert.equal(harness.dialogCalls[0][11], true);
  assert.equal(harness.storage.getItem("docxtool_wps_format_config_draft_v1"), "");
});

test("TaskPane uses the Dialog's shared current config for Preview and Apply", async () => {
  const harness = makeTaskpaneHarness({ host_ready: true, status: "READY", updated_at: "1" });
  await harness.flushAsync();
  harness.click("format_settings");
  await harness.flushAsync();
  const updated = harness.getActiveFormatConfig();
  updated.page.margin_top_cm = 4;
  harness.setActiveFormatConfig(updated);
  harness.click("preview");
  await harness.flushAsync();
  const preview = harness.commandRequests.find((item) => item.command === "preview");
  assert.equal(preview.format_config.page.margin_top_cm, 4);
  assert.equal(preview.format_config.page.lines_per_page, 22);
  assert.equal(preview.format_config.page.grid_alignment, "文字对齐字符网络");
  assert.equal(preview.format_config.page.margin_top_cm, 4);
  assert.equal(preview.format_config.page_number.first_page, true);
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
  await harness.flushAsync(30);
  harness.click("health");
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
  await harness.flushAsync(30);
  harness.click("health");
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
  assert.deepEqual(harness.storage.getCalls, [
    "docxtool_wps_format_config_current_v1",
  ]);
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
