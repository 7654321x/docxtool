import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import vm from "node:vm";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "..");
const html = await readFile(join(root, "resources", "frontend", "pages", "index.html"), "utf8");
const scriptMatch = html.match(/<script>\s*([\s\S]*?)\s*<\/script>/);
assert.ok(scriptMatch, "index.html should contain the frontend script");

const elements = new Map();
let styleDomRows = [];

function fakeClassList() {
  return {
    add() {},
    remove() {},
    toggle() {},
  };
}

function fakeElement(id = "") {
  if (elements.has(id)) return elements.get(id);
  const element = {
    checked: false,
    classList: fakeClassList(),
    className: "",
    dataset: {},
    download: "",
    href: "",
    id,
    style: {},
    textContent: "",
    value: "",
    addEventListener() {},
    appendChild() {},
    click() {},
    closest() {
      return null;
    },
    querySelector() {
      return null;
    },
    querySelectorAll() {
      return [];
    },
    set innerHTML(value) {
      this._innerHTML = value;
    },
    get innerHTML() {
      return this._innerHTML || "";
    },
  };
  elements.set(id, element);
  return element;
}

function makeStyleDomRows(styleRows) {
  return styleRows.map((row) => ({
    dataset: { key: row.key },
    querySelector(selector) {
      if (selector === ".style-card-title") return { textContent: row.name };
      const match = selector.match(/^\[data-field="([^"]+)"\]$/);
      if (!match) return null;
      const field = match[1];
      if (field === "bold") return { checked: !!row.bold };
      return { value: row[field] ?? "" };
    },
  }));
}

const document = {
  addEventListener() {},
  createElement(tag) {
    return fakeElement(`created-${tag}`);
  },
  getElementById(id) {
    return fakeElement(id);
  },
  querySelectorAll(selector) {
    if (selector === "#styleMatrixBody .style-card-row") return styleDomRows;
    return [];
  },
};

const context = {
  Blob,
  Buffer,
  Date,
  Error,
  JSON,
  Promise,
  RegExp,
  TextDecoder,
  TextEncoder,
  URL: { createObjectURL: () => "blob:test", revokeObjectURL() {} },
  alert() {},
  atob(value) {
    return Buffer.from(value, "base64").toString("binary");
  },
  btoa(value) {
    return Buffer.from(value, "binary").toString("base64");
  },
  console,
  document,
  fetch: async () => new Response("{}", { status: 200 }),
  localStorage: {
    getItem() {
      return null;
    },
    setItem() {},
  },
  prompt() {
    return "";
  },
  setTimeout,
};
context.globalThis = context;

const script = scriptMatch[1].replace(/\nbootstrap\(\);\s*$/, "");
vm.runInNewContext(
  `${script}
globalThis.__frontend = {
  collectConfig,
  friendlyError,
  initSettings,
  normalizeConfig,
  styleRows
};
`,
  context,
);

const frontend = context.__frontend;

frontend.initSettings();
styleDomRows = makeStyleDomRows(frontend.styleRows);

const defaultConfig = frontend.collectConfig();
assert.equal(defaultConfig.styles[6].name, "数字");
assert.equal(defaultConfig.styles[7].name, "字母");
assert.equal(Object.hasOwn(defaultConfig.styles[6], "size"), false);
assert.equal(Object.hasOwn(defaultConfig.styles[7], "size"), false);

elements.get("numberSize").value = "小四";
elements.get("letterSize").value = "五号";
const selectedConfig = frontend.collectConfig();
assert.equal(selectedConfig.styles[6].size, "小四");
assert.equal(selectedConfig.styles[7].size, "五号");

const legacyConfig = {
  styles: [
    { name: "主标题", size: "" },
    {},
    {},
    {},
    {},
    {},
    { name: "数字", size: "" },
    { name: "字母", size: "" },
  ],
  page: {},
};
const migratedConfig = frontend.normalizeConfig(legacyConfig, { id: "custom", name: "旧模板" });
assert.equal(migratedConfig.styles[0].size, "");
assert.equal(Object.hasOwn(migratedConfig.styles[6], "size"), false);
assert.equal(Object.hasOwn(migratedConfig.styles[7], "size"), false);

assert.equal(
  frontend.friendlyError("styles[6].size: 不能为空", "FORMAT_CONFIG_INVALID", {
    field: "styles[6].size",
    reason: "不能为空",
  }),
  "排版设置无效：数字字号不能为空。",
);
assert.equal(
  frontend.friendlyError("styles[1].size: 不能为空", "FORMAT_CONFIG_INVALID", {
    field: "styles[1].size",
    reason: "不能为空",
  }),
  "排版设置无效：styles[1].size 不能为空。",
);
