import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import vm from "node:vm";

const root = new URL("../", import.meta.url);
const configSource = await readFile(new URL("format-config.js", root), "utf8");
const htmlSource = await readFile(new URL("format-settings.html", root), "utf8");
const dialogSource = await readFile(new URL("format-settings.js", root), "utf8");

function makeStorage() {
  const values = new Map();
  return {
    getItem(key) { return values.get(key) ?? ""; },
    setItem(key, value) { values.set(key, String(value)); },
  };
}

function validConfig() {
  return {
    styles: [
      { name: "主标题" }, { name: "一级标题" }, { name: "二级标题" },
      { name: "三级标题" }, { name: "四级标题" }, { name: "正文" },
    ],
    page: {},
  };
}

function dialogConfig() {
  return {
    styles: [
      { name: "主标题", font: "方正小标宋简体", size: "二号", bold: false, pattern: "", indent: 0, align: "居中" },
      { name: "一级标题", font: "黑体", size: "三号", bold: false, pattern: "{a}、", indent: 2, align: "左对齐" },
      { name: "二级标题", font: "楷体_GB2312", size: "三号", bold: true, pattern: "（{b}）", indent: 2, align: "左对齐" },
      { name: "三级标题", font: "仿宋_GB2312", size: "三号", bold: false, pattern: "{c}.", indent: 2, align: "左对齐" },
      { name: "四级标题", font: "仿宋_GB2312", size: "三号", bold: false, pattern: "（{d}）", indent: 2, align: "左对齐" },
      { name: "正文", font: "仿宋_GB2312", size: "三号", bold: false, pattern: "", indent: 2, align: "两端对齐" },
      { name: "数字", font: "Times New Roman", bold: false },
      { name: "字母", font: "Times New Roman", bold: false },
      { name: "页码设置", font: "宋体", size: "四号", pattern: "— 1 —", align: "奇右|偶左" },
    ],
    page: {
      width_cm: 21, height_cm: 29.7, margin_top_cm: 3.7, margin_bottom_cm: 3.5,
      margin_left_cm: 2.8, margin_right_cm: 2.6, line_spacing_pt: 28,
      lines_per_page: 22, chars_per_line: 28, grid_alignment: "文字对齐字符网络",
      space_before_line: 0, space_after_line: 0,
    },
    page_number: {
      enabled: true, font_name: "宋体", font_size_pt: 14,
      style: "dash", position: "outside",
    },
  };
}

function makeElement(id) {
  return {
    id,
    value: "",
    textContent: "",
    disabled: false,
    readOnly: false,
    checked: false,
    children: [],
    dataset: {},
    listeners: new Map(),
    addEventListener(name, callback) { this.listeners.set(name, callback); },
    appendChild(child) { this.children.push(child); return child; },
    replaceChildren(...children) { this.children = children; },
    setAttribute() {},
    focus() { this.focused = true; },
    closest() { return this.dialogContent || null; },
    querySelector(selector) {
      const field = String(selector).match(/^\[data-field="([^"]+)"\]$/);
      const index = String(selector).match(/^\[data-index="([^"]+)"\]$/);
      const matches = (item) => item && item.dataset && (
        (field && item.dataset.field === field[1])
        || (index && item.dataset.index === index[1])
      );
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
  };
}

function makeDialogHarness({ activeCustom = false, confirmResult = true } = {}) {
  const ids = [
    "dialog_close", "format_dialog_error", "format_profile_select", "format_profile_name",
    "format_profile_add", "format_profile_delete", "format_style_rows",
    "format_paper_size", "format_margin_top", "format_margin_bottom", "format_margin_left",
    "format_margin_right", "format_line_spacing", "format_number_font", "format_number_size",
    "format_letter_font", "format_letter_size", "format_page_font", "format_page_size",
    "format_page_style", "format_page_position", "format_settings_restore",
    "format_settings_cancel", "format_settings_save", "dialog_content",
  ];
  const elements = new Map(ids.map((id) => [id, makeElement(id)]));
  elements.get("format_style_rows").dialogContent = elements.get("dialog_content");
  const calls = [];
  let closed = false;
  const clone = (value) => JSON.parse(JSON.stringify(value));
  const system = {
    profile_id: "system:default", name: "系统默认", is_system: true,
    revision: 0, config_version: "config-1", format_config: dialogConfig(),
  };
  let custom = {
    profile_id: "fmt_existing", name: "已有模板", is_system: false,
    revision: 1, config_version: "config-1", format_config: dialogConfig(),
  };
  let active = activeCustom ? custom : system;
  function responseData() {
    return {
      profiles: [clone(system), ...(custom ? [{ ...clone(custom), format_config: undefined }] : [])],
      active_profile_id: active.profile_id,
      active_profile: clone(active),
    };
  }
  function response(payload, ok = true) {
    return { ok, status: ok ? 200 : 400, json: async () => payload };
  }
  async function fetch(url, options = {}) {
    const rawUrl = String(url);
    if (rawUrl === "./runtime/config") {
      return response({ controlBaseUrl: "http://127.0.0.1:9527", sessionToken: "token" });
    }
    const parsed = new URL(rawUrl);
    const path = parsed.pathname;
    const body = options.body ? JSON.parse(options.body) : {};
    if (path === "/v1/log") return response({ ok: true });
    calls.push({ path, body, method: options.method || "GET" });
    if (path === "/v1/format/profiles") return response({ ok: true, data: responseData() });
    if (path === "/v1/format/profiles/detail") {
      const id = parsed.searchParams.get("profile_id");
      const profile = id === "system:default" ? system : custom;
      return response({ ok: true, data: { profile: clone(profile) } });
    }
    if (path === "/v1/format/profiles/create") {
      custom = {
        profile_id: "fmt_created", name: body.name, is_system: false,
        revision: 1, config_version: "config-1", format_config: clone(body.format_config),
      };
      active = custom;
      return response({ ok: true, data: responseData() });
    }
    if (path === "/v1/format/profiles/update") {
      custom = { ...custom, name: body.name, revision: custom.revision + 1, format_config: clone(body.format_config) };
      active = custom;
      return response({ ok: true, data: responseData() });
    }
    if (path === "/v1/format/profiles/delete") {
      custom = null;
      active = system;
      return response({ ok: true, data: responseData() });
    }
    if (path === "/v1/format/profiles/select") {
      active = body.profile_id === "system:default" ? system : custom;
      return response({ ok: true, data: responseData() });
    }
    throw new Error(`UNEXPECTED_FORMAT_ROUTE:${path}`);
  }
  const document = {
    getElementById(id) { return elements.get(id) || null; },
    createElement(tagName) { return makeElement(tagName); },
  };
  const context = {
    document,
    fetch,
    URL,
    JSON,
    Error,
    Object,
    Number,
    String,
    Set,
    Array,
    console: { log() {}, warn() {}, error() {} },
    confirm() { return confirmResult; },
    close() { closed = true; },
  };
  context.window = context;
  vm.runInNewContext(configSource, context, { filename: "format-config.js" });
  vm.runInNewContext(dialogSource, context, { filename: "format-settings.js" });
  return {
    calls,
    context,
    elements,
    get closed() { return closed; },
    async flush(turns = 20) {
      for (let index = 0; index < turns; index += 1) await Promise.resolve();
    },
  };
}

test("format settings page keeps the four sections, template manager, and six style rows", () => {
  for (const label of ["段落样式", "页面版式", "字符设置", "页码设置"]) assert.match(htmlSource, new RegExp(label));
  for (const id of [
    "format_profile_select", "format_profile_name", "format_profile_add", "format_profile_delete",
    "format_style_rows", "format_settings_restore", "format_settings_cancel", "format_settings_save",
  ]) {
    assert.match(htmlSource, new RegExp(`id="${id}"`));
  }
  assert.match(htmlSource, /format-config\.js\?v=2/);
  assert.match(htmlSource, /format-settings\.css\?v=2/);
  assert.match(htmlSource, /format-settings\.js\?v=2/);
});

test("format config current, draft and revision storage use validated envelopes", () => {
  const context = { window: {}, JSON, Error, Object, Number, String, Set };
  vm.runInNewContext(configSource, context);
  const format = context.window.DocxToolFormatConfig;
  const store = makeStorage();
  const config = validConfig();
  format.writeDraft(store, "config-1", config, config);
  format.writeCurrent(store, "config-1", config);
  format.writeRevision(store, 3);
  assert.equal(format.readDraft(store).config_version, "config-1");
  assert.equal(format.readCurrent(store).format_config.styles.length, 6);
  assert.equal(format.readRevision(store), 3);
  store.setItem(format.CURRENT_KEY, "{}");
  assert.throws(() => format.readCurrent(store), /WPS_FORMAT_STORAGE_ENVELOPE_INVALID/);
});

test("format dialog source manages account-scoped SQLite profiles through local routes", () => {
  for (const route of ["profiles/create", "profiles/update", "profiles/delete", "profiles/select"]) {
    assert.match(dialogSource, new RegExp(route));
  }
  assert.match(dialogSource, /format_profile_select/);
  assert.match(dialogSource, /format_profile_name/);
  assert.doesNotMatch(dialogSource, /writeCurrent\(store/);
  assert.doesNotMatch(dialogSource, /writeRevision\(store/);
  assert.match(dialogSource, /window\.close\(\)/);
  assert.match(dialogSource, /dialog\.saved/);
  assert.match(dialogSource, /dialog\.cancelled/);
});

test("format dialog adds a named template and saves the full current config", async () => {
  const harness = makeDialogHarness();
  await harness.flush();

  harness.context.DocxToolFormatSettingsDialog.addProfile();
  assert.equal(harness.elements.get("format_profile_name").value, "");
  assert.equal(harness.elements.get("format_profile_name").focused, true);
  harness.elements.get("format_profile_name").value = "机关专用模板";
  await harness.context.DocxToolFormatSettingsDialog.saveSettings();

  const created = harness.calls.find((item) => item.path === "/v1/format/profiles/create");
  assert.equal(created.body.name, "机关专用模板");
  assert.equal(created.body.format_config.page.lines_per_page, 22);
  assert.equal(created.body.format_config.page.grid_alignment, "文字对齐字符网络");
  assert.equal(harness.closed, true);
});

test("system default leaves the heading 3 bold control unchecked", async () => {
  const harness = makeDialogHarness();
  await harness.flush();

  const heading3 = harness.elements.get("format_style_rows").querySelector('[data-index="3"]');
  assert.equal(heading3.querySelector('[data-field="bold"]').checked, false);
});

test("format dialog deletes only a custom template and falls back to system default", async () => {
  const harness = makeDialogHarness({ activeCustom: true });
  await harness.flush();

  await harness.context.DocxToolFormatSettingsDialog.deleteProfile();

  const deleted = harness.calls.find((item) => item.path === "/v1/format/profiles/delete");
  assert.equal(deleted.body.profile_id, "fmt_existing");
  assert.equal(harness.elements.get("format_profile_select").value, "system:default");
  assert.equal(harness.elements.get("format_profile_delete").disabled, true);
});
