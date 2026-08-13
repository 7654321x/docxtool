import assert from "node:assert/strict";
import test from "node:test";
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
    replaceChildren() {},
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

const script = scriptMatch[1]
  .replace(/\nbootstrap\(\);\s*$/, "")
  .replace("}catch(_){}\n  }\n  status('排版超时", "}catch(error){globalThis.__pollErrors=(globalThis.__pollErrors||[]).concat(String(error&&error.stack||error))}\n  }\n  status('排版超时");
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
  styleRows,
  upload,
  runUploadWithEnvironment: async (file, fetchImpl, timeoutImpl) => {
    fetch = fetchImpl;
    setTimeout = timeoutImpl;
    return upload(file);
  },
  getUploadState: () => ({
    message: document.getElementById('msg').textContent,
    resultVisible: document.getElementById('resultCard').style.display === 'block',
    lastDownloadUrl,
    lastDownloadName,
    pollErrors: globalThis.__pollErrors || [],
  })
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
assert.equal(defaultConfig.letterhead.agencies[0].name, "");
assert.equal(defaultConfig.letterhead.document_number.agency_code, "");
assert.equal(defaultConfig.letterhead.document_number.year, null);
assert.equal(defaultConfig.letterhead.document_number.sequence, null);
assert.equal(defaultConfig.letterhead.issuance_mode, "single");
assert.equal(defaultConfig.letterhead.separator_style, "straight");
assert.equal(defaultConfig.letterhead.replace_managed, true);
assert.equal(defaultConfig.page_number.position, "outside");
assert.equal(defaultConfig.page_number.first_page, true);
assert.equal(defaultConfig.page_number.enabled, true);
assert.equal(defaultConfig.page_number.font_name, "宋体");
assert.equal(defaultConfig.page_number.font_size_pt, 14);
assert.equal(defaultConfig.page_number.bold, false);
assert.equal(defaultConfig.signature_block.mode, "without_seal");
assert.equal(defaultConfig.output_suffix, "_排版");
assert.equal(defaultConfig.mode, "smart");
assert.equal(defaultConfig.processing_mode, "smart");
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
elements.get("settingMode").value = "strict";
assert.equal(frontend.collectConfig().processing_mode, "strict");

assert.match(html, /href="#settingLetterhead"><span>01<\/span>版头设置/);
assert.match(html, /letterhead-block-head[^>]*><h3>版头设置<\/h3><label class="switch" title="启用版头设置">/);
assert.doesNotMatch(html, />生成版头</);
assert.doesNotMatch(html, /生成正文流中的机关标志/);
assert.doesNotMatch(html, /letterheadDisabledNote/);
assert.match(html, /当前版本仅支持单一机关发文/);
assert.doesNotMatch(html, /<option value="joint">联合发文<\/option>/);
assert.match(html, /<option value="star">五角星型<\/option>/);
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
assert.match(html, /<form class="auth-form" id="authForm" autocomplete="on"/);
assert.match(html, /id="authPassword"[^>]*autocomplete="current-password"/);
assert.match(html, /authPassword'\)\.autocomplete=registering\?'new-password':'current-password'/);
assert.doesNotMatch(html, /<form class="auth-form" id="authForm" autocomplete="off"/);
for (const id of ["styleMatrixBody", "marginTop", "pageNumberEnabled", "specialBold"]) {
  assert.equal((html.match(new RegExp(`id="${id}"`, "g")) || []).length, 1);
}

elements.get("letterheadEnabled").checked = true;
frontend.setIssuanceMode("joint");
frontend.addLetterheadAgency();
let letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 1);
assert.equal(letterheadState.agencies[0].role, "sponsor");
assert.equal(elements.get("letterheadIssuanceMode").value, "single");
frontend.removeLetterheadAgency(letterheadState.agencies[0].id);
assert.equal(frontend.getLetterheadState().agencies.length, 1);
frontend.addLetterheadAgency();
letterheadState = frontend.getLetterheadState();
assert.equal(letterheadState.agencies.length, 1);
letterheadState.agencies[0].name = "测试机关";
elements.get("letterheadDirection").value = "upward";
elements.get("letterheadAgencyCode").value = "测发";
elements.get("letterheadYear").value = "2026";
elements.get("letterheadSequence").value = "8";
frontend.renderLetterhead();
letterheadState = frontend.getLetterheadState();
assert.equal(elements.get("letterheadFields").hidden, false);
assert.equal(letterheadState.agencies[0].role, "sponsor");
assert.equal(letterheadState.signers.length, 1);
assert.match(elements.get("previewLetterheadMark").textContent, /测试机关/);
assert.equal(elements.get("letterheadNumberPreview").value, "测发〔2026〕8号");
letterheadState.signers[0].name = "张三";
frontend.addLetterheadSigner(letterheadState.agencies[0].id);
elements.get("letterheadSeparatorStyle").value = "star";
const collectedLetterhead = frontend.collectLetterheadConfig();
assert.equal(collectedLetterhead.issuance_mode, "single");
assert.equal(collectedLetterhead.document_direction, "upward");
assert.deepEqual(
  JSON.parse(JSON.stringify(collectedLetterhead.agencies.map((agency) => agency.order))),
  [1],
);
assert.equal(collectedLetterhead.signers.length, 1);
assert.equal(collectedLetterhead.separator_style, "star");
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

function webResponse(payload, { ok = true, status = 200, contentType = "application/json" } = {}) {
  return {
    ok,
    status,
    headers: { get: (name) => name.toLowerCase() === "content-type" ? contentType : null },
    async json() { return payload; },
    async blob() { return new Blob([JSON.stringify(payload)], { type: contentType }); },
  };
}

async function runUploadScenario(statuses, { download } = {}) {
  let statusIndex = 0;
  const observed = [];
  const paths = [];
  const fetchImpl = async (url) => {
    const path = String(url);
    paths.push(path);
    if (path.endsWith("/upload")) return webResponse({ task_id: "task-acceptance", status: "queued", queue_ahead: 0 });
    if (path.includes("/status/")) {
      const next = statuses[Math.min(statusIndex, statuses.length - 1)];
      statusIndex += 1;
      observed.push(next instanceof Error ? "ERROR" : next);
      if (next instanceof Error) throw next;
      return webResponse({ status: next });
    }
    if (path.includes("/download/")) return download || webResponse("docx", { contentType: "application/vnd.openxmlformats-officedocument.wordprocessingml.document" });
    throw new Error(`UNEXPECTED_URL:${path}`);
  };
  await frontend.runUploadWithEnvironment({
    name: "acceptance.docx",
    size: 100,
    async arrayBuffer() { return new ArrayBuffer(8); },
  }, fetchImpl, (callback) => { callback(); return 1; });
  return { ...frontend.getUploadState(), statusCalls: statusIndex, observed, paths };
}

await test("Web polling waits through 15 seconds queued plus 35 seconds processing", async () => {
  const result = await runUploadScenario([
    ...Array(15).fill("queued"),
    ...Array(35).fill("processing"),
    "done",
  ]);
  assert.equal(result.message, "下载完成");
});

await test("Web polling waits through 55 seconds processing", async () => {
  const result = await runUploadScenario([...Array(55).fill("processing"), "done"]);
  assert.equal(result.message, "下载完成");
});

for (const terminal of ["failed", "timeout", "interrupted", "expired"]) {
  await test(`Web renders server terminal state ${terminal} without a client timeout`, async () => {
    const result = await runUploadScenario([terminal]);
    assert.notEqual(result.message, "排版超时，请稍后重试或重新上传");
    assert.equal(result.statusCalls, 1);
  });
}

await test("Web polling recovers after one status network error", async () => {
  const result = await runUploadScenario([new Error("network"), "done"]);
  assert.deepEqual(result.observed.slice(0, 2), ["ERROR", "done"]);
  assert.ok(result.paths.some((path) => path.includes("/download/")));
  assert.equal(result.pollErrors.length, 0, String(result.pollErrors[0] || ""));
  assert.equal(result.message, "下载完成");
});

await test("Web stops after three consecutive status network errors", async () => {
  const result = await runUploadScenario([
    new Error("network-1"),
    new Error("network-2"),
    new Error("network-3"),
  ]);
  assert.equal(result.statusCalls, 3);
  assert.match(result.message, /状态查询连续失败/);
  assert.equal(result.resultVisible, false);
});

for (const statusCode of [403, 404, 500]) {
  await test(`Web rejects JSON download error ${statusCode} instead of saving DOCX`, async () => {
    const result = await runUploadScenario(["done"], {
      download: webResponse({ code: "DOWNLOAD_FAILED", error: "download failed" }, { ok: false, status: statusCode }),
    });
    assert.equal(result.resultVisible, false);
    assert.notEqual(result.message, "下载完成");
  });
}

await test("Web rejects a successful download with the wrong content type", async () => {
  const result = await runUploadScenario(["done"], {
    download: webResponse("not-docx", { contentType: "text/plain" }),
  });
  assert.match(result.message, /未返回 DOCX 文件/);
  assert.equal(result.resultVisible, false);
});
