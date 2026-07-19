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
  applyConfigToForm,
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
assert.equal(defaultConfig.letterhead.agencies[0].name, "xxx市政府");
assert.equal(defaultConfig.letterhead.document_number.agency_code, "市委办");
assert.equal(defaultConfig.letterhead.document_number.year, new Date().getFullYear());
assert.equal(defaultConfig.letterhead.document_number.sequence, 1);
assert.equal(defaultConfig.letterhead.replace_managed, true);
assert.equal(defaultConfig.page_number.position, "outside");
assert.equal(defaultConfig.page_number.first_page, true);
assert.equal(defaultConfig.page_number.enabled, true);
assert.equal(defaultConfig.page_number.font_name, "宋体");
assert.equal(defaultConfig.page_number.font_size_pt, 14);
assert.equal(defaultConfig.page_number.bold, false);
assert.equal(defaultConfig.signature_block.mode, "without_seal");
assert.equal(defaultConfig.output_suffix, "_排版");
assert.equal(defaultConfig.styles.length, 10);
assert.equal(defaultConfig.styles[9].name, "正文上标");
assert.equal(Object.hasOwn(defaultConfig.features, "page_number_enabled"), false);
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
assert.equal(migratedConfig.signature_block.mode, "preserve");

const legacyPageNumberConfig = frontend.normalizeConfig(
  { features: { page_number_enabled: false } },
  { id: "legacy-page", name: "旧页码模板" },
);
assert.equal(legacyPageNumberConfig.page_number.enabled, false);
const canonicalPageNumberConfig = frontend.normalizeConfig(
  { features: { page_number_enabled: true }, page_number: { enabled: false, style: "cn_total", position: "center" } },
  { id: "canonical-page", name: "新版页码模板" },
);
assert.equal(canonicalPageNumberConfig.page_number.enabled, false);
frontend.applyConfigToForm(canonicalPageNumberConfig);
assert.equal(elements.get("pageNumberEnabled").checked, false);
assert.equal(elements.get("pageStyle").value, "cn_total");
assert.equal(elements.get("pagePosition").value, "center");
frontend.applyConfigToForm(frontend.normalizeConfig(
  { page_number: { style: "chinese_total", position: "centre" } },
  { id: "legacy-page-aliases", name: "旧页码别名" },
));
assert.equal(elements.get("pageStyle").value, "cn_total");
assert.equal(elements.get("pagePosition").value, "center");

elements.get("paperSize").value = "Letter";
elements.get("pageStyle").value = "cn";
elements.get("pagePosition").value = "right";
elements.get("outputSuffix").value = "_测试";
const effectiveGlobalConfig = frontend.collectConfig();
assert.equal(effectiveGlobalConfig.page.paper_size, "Letter");
assert.equal(effectiveGlobalConfig.page.width_cm, 21.59);
assert.equal(effectiveGlobalConfig.page.height_cm, 27.94);
assert.equal(effectiveGlobalConfig.page_number.style, "cn");
assert.equal(effectiveGlobalConfig.page_number.position, "right");
assert.equal(effectiveGlobalConfig.output_suffix, "_测试");

elements.get("signatureBlockMode").value = "with_seal";
assert.equal(frontend.collectConfig().signature_block.mode, "with_seal");

assert.match(html, /href="#settingLetterhead"><span>01<\/span>版头设置/);
assert.match(html, /letterhead-block-head[^>]*><h3>版头设置<\/h3><label class="switch" title="启用版头设置">/);
assert.doesNotMatch(html, />生成版头</);
assert.doesNotMatch(html, /生成正文流中的机关标志/);
assert.doesNotMatch(html, /letterheadDisabledNote/);
assert.match(html, /href="#settingStyles"><span>02<\/span>段落样式/);
assert.match(html, /href="#settingGlobal"><span>03<\/span>全局设置/);
assert.match(html, /href="#settingFeatures"><span>04<\/span>功能开关/);
assert.match(html, /const API_PREFIX = '\/api'/);
assert.match(html, /加盖印章版式（不生成印章）/);
assert.doesNotMatch(html, /<h4>正文上标<\/h4>/);
assert.doesNotMatch(html, /id="pageLanguage"/);
assert.doesNotMatch(html, /<option>- 1 -<\/option>|<option>1 \/ n<\/option>/);
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
assert.match(elements.get("letterheadAgencies").innerHTML, /title="上移"/);
assert.match(elements.get("letterheadAgencies").innerHTML, /title="下移"/);
const originalSponsorId = letterheadState.agencies[0].id;
const originalJointId = letterheadState.agencies[1].id;
frontend.moveLetterheadAgency(originalJointId, -1);
letterheadState = frontend.getLetterheadState();
assert.deepEqual(letterheadState.agencies.map(agency => agency.id), [originalJointId, originalSponsorId]);
assert.deepEqual(letterheadState.agencies.map(agency => agency.role), ["sponsor", "joint"]);
frontend.moveLetterheadAgency(originalJointId, 1);
letterheadState = frontend.getLetterheadState();
assert.deepEqual(letterheadState.agencies.map(agency => agency.id), [originalSponsorId, originalJointId]);
assert.deepEqual(letterheadState.agencies.map(agency => agency.role), ["sponsor", "joint"]);
letterheadState.agencies[0].name = "主办机关";
letterheadState.agencies[1].name = "联合机关";
frontend.addLetterheadAgency();
letterheadState = frontend.getLetterheadState();
assert.match(elements.get("letterheadAgencies").innerHTML, /title="上移"/);
assert.match(elements.get("letterheadAgencies").innerHTML, /title="下移"/);
const movableAgencyId = letterheadState.agencies[2].id;
letterheadState.agencies[2].name = "第三机关";
frontend.moveLetterheadAgency(movableAgencyId, -1);
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies[1].id, movableAgencyId);
frontend.removeLetterheadAgency(movableAgencyId);
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 2);
frontend.removeLetterheadAgency(letterheadState.agencies[1].id);
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 1);
assert.equal(letterheadState.agencies[0].role, "sponsor");
assert.equal(elements.get("letterheadIssuanceMode").value, "single");
frontend.removeLetterheadAgency(letterheadState.agencies[0].id);
assert.equal(frontend.getLetterheadState().agencies.length, 1);
frontend.addLetterheadAgency();
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 2);
assert.equal(elements.get("letterheadIssuanceMode").value, "joint");
letterheadState.agencies[1].name = "联合机关";
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
assert.equal(collectedLetterhead.replace_managed, true);

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
