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
  addLetterheadAgency,
  addLetterheadSigner,
  applyLetterheadConfig,
  collectLetterheadConfig,
  collectConfig,
  friendlyError,
  getLetterheadState: () => ({ agencies: letterheadAgencies, signers: letterheadSigners }),
  initSettings,
  normalizeConfig,
  moveLetterheadAgency,
  removeLetterheadAgency,
  renderLetterhead,
  setIssuanceMode,
  setLetterheadSponsor,
  styleRows
};
`,
  context,
);

const frontend = context.__frontend;

frontend.initSettings();
styleDomRows = makeStyleDomRows(frontend.styleRows);

const defaultConfig = frontend.collectConfig();
assert.equal(defaultConfig.letterhead.enabled, false);
assert.equal(defaultConfig.letterhead.agencies.length, 1);
assert.equal(defaultConfig.page_number.position, "outside");
assert.equal(defaultConfig.page_number.first_page, true);
assert.equal(elements.get("letterheadFields").hidden, true);
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
assert.equal(migratedConfig.letterhead.enabled, false);

assert.match(html, /href="#settingLetterhead"><span>01<\/span>版头设置/);
assert.match(html, /href="#settingStyles"><span>02<\/span>段落样式/);
assert.match(html, /href="#settingGlobal"><span>03<\/span>全局设置/);
assert.match(html, /href="#settingFeatures"><span>04<\/span>功能开关/);
assert.match(html, /const API_PREFIX = '\/api'/);
assert.match(html, /fetch\(api\('\/upload'\)/);
assert.match(html, /'X-Format-Config':base64UrlJson\(config\)/);
assert.match(html, /'X-Format-Config-Encoding':'base64url-json'/);
for (const id of ["styleMatrixBody", "marginTop", "pageNumberEnabled", "specialBold"]) {
  assert.equal((html.match(new RegExp(`id="${id}"`, "g")) || []).length, 1);
}

elements.get("letterheadEnabled").checked = true;
frontend.setIssuanceMode("joint");
frontend.addLetterheadAgency();
let letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 2);
letterheadState.agencies[0].name = "主办机关";
letterheadState.agencies[1].name = "联合机关";
frontend.addLetterheadAgency();
letterheadState = frontend.getLetterheadState();
const movableAgencyId = letterheadState.agencies[2].id;
letterheadState.agencies[2].name = "第三机关";
frontend.moveLetterheadAgency(movableAgencyId, -1);
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies[1].id, movableAgencyId);
frontend.removeLetterheadAgency(movableAgencyId);
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 2);
frontend.setLetterheadSponsor(letterheadState.agencies[1].id);
elements.get("letterheadDirection").value = "upward";
elements.get("letterheadAgencyCode").value = "测发";
elements.get("letterheadYear").value = "2026";
elements.get("letterheadSequence").value = "8";
frontend.renderLetterhead();
letterheadState = frontend.getLetterheadState();
assert.equal(elements.get("letterheadFields").hidden, false);
assert.equal(letterheadState.agencies[0].role, "sponsor");
assert.equal(letterheadState.signers.length, 2);
assert.match(elements.get("previewLetterheadMark").textContent, /联合机关/);
assert.equal(elements.get("letterheadNumberPreview").value, "测发〔2026〕8号");
letterheadState.signers[0].name = "张三";
letterheadState.signers[1].name = "李四";
frontend.addLetterheadSigner(letterheadState.agencies[0].id);
const collectedLetterhead = frontend.collectLetterheadConfig();
assert.equal(collectedLetterhead.issuance_mode, "joint");
assert.equal(collectedLetterhead.document_direction, "upward");
assert.deepEqual(
  collectedLetterhead.agencies.map((agency) => agency.order),
  [1, 2],
);
assert.equal(collectedLetterhead.signers.length, 3);
assert.equal(collectedLetterhead.document_number.agency_code, "测发");
assert.equal(collectedLetterhead.document_number.year, 2026);
assert.equal(collectedLetterhead.document_number.sequence, 8);

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
