import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const CLIENT_SOURCE = readFileSync(new URL("../reader/reader-client.js", import.meta.url), "utf8");
const UI_SOURCE = readFileSync(new URL("../reader/reader-ui.js", import.meta.url), "utf8");

function element(id) {
  return {
    id,
    disabled: false,
    hidden: false,
    value: "",
    checked: false,
    textContent: "",
    scrollTop: 0,
    offsetTop: 0,
    offsetHeight: 600,
    scrollHeight: 1200,
    clientHeight: 300,
    dataset: {},
    style: {},
    children: [],
    listeners: new Map(),
    classList: {
      values: new Set(),
      toggle(value, enabled) {
        if (enabled) this.values.add(value);
        else this.values.delete(value);
      },
    },
    addEventListener(name, callback) { this.listeners.set(name, callback); },
    setAttribute(name, value) { this[name] = String(value); },
    replaceChildren(...children) {
      children.forEach((child, index) => { child.offsetTop = index * 600; });
      this.children = children;
    },
  };
}

function createHarness(options = {}) {
  let now = 1000;
  let nextFrame = 0;
  const frames = new Map();
  const calls = [];
  const logs = [];
  const elements = new Map();
  const ids = [
    "reader_panel", "reader_book_select", "reader_import", "reader_delete", "reader_stealth",
    "reader_book_library", "reader_library", "reader_reveal", "reader_empty", "reader_chapter", "reader_content", "reader_controls",
    "reader_previous_chapter", "reader_previous_block", "reader_play", "reader_next_block",
    "reader_next_chapter", "reader_font_size", "reader_line_height", "reader_theme", "reader_opacity",
    "reader_speed", "reader_speed_visual", "reader_speed_value", "reader_progress_fill", "reader_progress_value",
    "reader_stealth_mode", "reader_notice", "reader_error", "reader_font_setting", "reader_line_setting", "reader_theme_setting",
    "reader_opacity_setting", "reader_settings_popover", "reader_font_setting_label", "reader_line_setting_label",
    "reader_theme_setting_label", "reader_opacity_setting_label", "reader_play_label", "reader_play_icon",
  ];
  ids.forEach((id) => elements.set(id, element(id)));
  elements.get("reader_library").hidden = true;
  elements.get("reader_settings_popover").hidden = true;
  const book = { id: "book-1234567890", display_name: "fixture", chapter_count: 2 };
  const chapters = [
    { book_id: book.id, chapter_index: 0, title: "第一章", start_offset: 0, end_offset: 30000 },
    { book_id: book.id, chapter_index: 1, title: "第二章", start_offset: 30000, end_offset: 60000 },
  ];
  const client = {
    async loadState() {
      calls.push({ method: "state" });
      return {
        books: [book], current_book: book,
        progress: { book_id: book.id, chapter_index: Number(options.progressChapterIndex || 0), text_offset: Number(options.progressOffset || 0), scroll_ratio: 0 },
        chapters,
        settings: { font_size: 16, line_height: 1.6, theme: "light", opacity: 1, auto_scroll_speed: 1, stealth_mode: false },
      };
    },
    async loadContent(bookId, chapterIndex, startOffset, limit) {
      calls.push({ method: "content", bookId, chapterIndex, startOffset, limit });
      const chapter = chapters[chapterIndex];
      const start = Number.isInteger(startOffset) ? startOffset : chapter.start_offset;
      const end = Math.min(start + limit, chapter.end_offset);
      const availableChars = Math.max(2, end - start);
      const firstParagraphChars = Math.max(1, Math.floor((availableChars - 1) / 2));
      return {
        book_id: bookId, chapter_index: chapterIndex, chapter_title: chapter.title,
        chapter_start_offset: chapter.start_offset, start_offset: start,
        end_offset: end, chapter_end_offset: chapter.end_offset,
        text: `${"甲".repeat(firstParagraphChars)}\n${"乙".repeat(availableChars - firstParagraphChars - 1)}`,
      };
    },
    async saveProgress(progress) { calls.push({ method: "progress", progress }); return { progress }; },
    async saveSettings(settings) { calls.push({ method: "settings", settings }); return { settings }; },
    async navigate(bookId, chapterIndex, textOffset, direction) {
      calls.push({ method: "navigate", bookId, chapterIndex, textOffset, direction });
      return { target_offset: direction < 0 ? 0 : 5 };
    },
    async importBook(file) { calls.push({ method: "import", file }); return { book }; },
    async selectBook(bookId) { calls.push({ method: "select", bookId }); return { book }; },
    async deleteBook(bookId) { calls.push({ method: "delete", bookId }); return {}; },
  };
  const documentListeners = new Map();
  const context = {
    Date: class extends Date { static now() { return now; } },
    Error, Math, Number, String, Boolean, Object, Promise, Set,
    URLSearchParams,
    console: { log() {}, warn() {}, error() {} },
    confirm: () => true,
    requestAnimationFrame(callback) { nextFrame += 1; frames.set(nextFrame, callback); return nextFrame; },
    cancelAnimationFrame(id) { frames.delete(id); },
    document: {
      visibilityState: "visible",
      getElementById(id) { return elements.get(id) || null; },
      createElement() { return element(""); },
      addEventListener(name, callback) { documentListeners.set(name, callback); },
    },
    DocxToolReaderClient: client,
    DocxToolTaskpaneLog(level, event, message, details) {
      logs.push({ level, event, message, details });
    },
  };
  context.window = context;
  vm.runInNewContext(UI_SOURCE, context, { filename: "reader-ui.js" });
  return {
    calls, context, elements, logs,
    async flush(turns = 12) { for (let index = 0; index < turns; index += 1) await Promise.resolve(); },
    dispatch(id, eventName, event = {}) { elements.get(id).listeners.get(eventName)(event); },
    documentEvent(name) { documentListeners.get(name)(); },
    runFrame(timestamp) { const item = frames.entries().next().value; assert.ok(item, "missing animation frame"); frames.delete(item[0]); item[1](timestamp); },
    setNow(value) { now = value; },
  };
}

test("Reader client sends TXT as a raw body rather than JSON or Base64", async () => {
  const calls = [];
  const context = {
    Date, Math, Error, Object, Promise, URLSearchParams,
    fetch: async (url, options) => {
      calls.push({ url, options });
      return { ok: true, json: async () => ({ ok: true, data: {} }) };
    },
    DocxToolWpsConfig: { controlBaseUrl: "http://127.0.0.1:9999", sessionToken: "token" },
  };
  context.window = context;
  vm.runInNewContext(CLIENT_SOURCE, context, { filename: "reader-client.js" });
  const file = { name: "fixture.txt" };
  await context.DocxToolReaderClient.importBook(file);
  assert.equal(calls[0].options.body, file);
  assert.equal(calls[0].options.headers["Content-Type"], "text/plain");
  assert.equal(calls[0].options.headers["X-DocxTool-Reader-Filename"], "fixture.txt");
  assert.doesNotMatch(CLIENT_SOURCE, /base64/i);
});

test("Reader loads bounded blocks, scrolls one line per playback step, and ignores its own scroll event", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();
  const firstContent = harness.calls.find((item) => item.method === "content");
  assert.equal(firstContent.limit, 12000);
  assert.equal(harness.elements.get("reader_content").children.length, 2);
  assert.equal(harness.elements.get("reader_previous_block").disabled, true);
  assert.equal(harness.elements.get("reader_next_block").disabled, false);
  assert.ok(harness.logs.some((item) => item.event === "reader.content.load.completed" && item.details.text_chars > 0));
  assert.ok(harness.logs.some((item) => item.event === "reader.content.render.completed" && item.details.rendered_paragraph_count === 2));

  harness.dispatch("reader_play", "click");
  assert.ok(harness.logs.some((item) => item.event === "reader.play.requested"));
  assert.ok(harness.logs.some((item) => item.event === "reader.play.started"));
  harness.runFrame(1000);
  harness.runFrame(2000);
  harness.runFrame(3000);
  assert.equal(harness.elements.get("reader_content").scrollTop, 25.6);
  assert.ok(harness.logs.some((item) => item.event === "reader.play.line.completed"));
  harness.dispatch("reader_content", "scroll");
  assert.equal(harness.context.DocxToolReader._testing.getState().playing, true);

  harness.setNow(2000);
  harness.dispatch("reader_content", "scroll");
  assert.equal(harness.context.DocxToolReader._testing.getState().playing, false);
});

test("Reader pauses and saves on visibility, manual selection, panel leave, and mode exit", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();
  harness.dispatch("reader_play", "click");
  harness.context.document.visibilityState = "hidden";
  harness.documentEvent("visibilitychange");
  await harness.flush();
  assert.equal(harness.context.DocxToolReader._testing.getState().playing, false);
  assert.ok(harness.calls.some((item) => item.method === "progress"));

  assert.equal(harness.context.DocxToolReader._testing.getState().collapsed, false);
  assert.equal(harness.elements.get("reader_content").listeners.has("mouseleave"), false);
  harness.dispatch("reader_stealth", "click");
  await harness.flush();
  assert.equal(harness.elements.get("reader_stealth")["aria-pressed"], "true");
  assert.equal(harness.context.DocxToolReader._testing.getState().collapsed, false);
  harness.dispatch("reader_panel", "mouseleave");
  assert.equal(harness.context.DocxToolReader._testing.getState().collapsed, true);
  harness.dispatch("reader_reveal", "mouseenter");
  assert.equal(harness.context.DocxToolReader._testing.getState().collapsed, false);
  harness.context.DocxToolReader.deactivate();
  assert.equal(harness.elements.get("reader_panel").hidden, true);
});

test("Reader pauses while auto-hidden and resumes only when the reading panel reappears", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();
  harness.dispatch("reader_stealth", "click");
  await harness.flush();
  harness.dispatch("reader_play", "click");
  assert.equal(harness.context.DocxToolReader._testing.getState().playing, true);

  harness.dispatch("reader_panel", "mouseleave");
  assert.equal(harness.context.DocxToolReader._testing.getState().collapsed, true);
  assert.equal(harness.context.DocxToolReader._testing.getState().playing, false);
  assert.equal(harness.context.DocxToolReader._testing.getState().resumePlaybackAfterReveal, true);
  assert.ok(harness.logs.some((item) => item.event === "reader.play.suspended.collapsed"));

  harness.dispatch("reader_reveal", "mouseenter");
  assert.equal(harness.context.DocxToolReader._testing.getState().collapsed, false);
  assert.equal(harness.context.DocxToolReader._testing.getState().playing, true);
  assert.equal(harness.context.DocxToolReader._testing.getState().resumePlaybackAfterReveal, false);
  assert.ok(harness.logs.some((item) => item.event === "reader.play.resumed.revealed"));
});

test("Reader toolbar buttons reveal the existing library and style controls", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  harness.dispatch("reader_book_library", "click");
  assert.equal(harness.elements.get("reader_library").hidden, false);
  harness.dispatch("reader_font_setting", "click");
  assert.equal(harness.elements.get("reader_settings_popover").hidden, false);
  harness.elements.get("reader_font_size").value = "18";
  harness.dispatch("reader_font_size", "change");
  const settings = harness.calls.filter((item) => item.method === "settings").at(-1);
  assert.equal(settings.settings.font_size, 18);
  assert.equal(settings.settings.auto_scroll_speed, 1);
  harness.dispatch("reader_theme_setting", "click");
  assert.equal(harness.elements.get("reader_settings_popover").hidden, true);
});

test("Reader import shows progress and completion feedback", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  const file = { name: "fixture.txt" };
  harness.dispatch("reader_import", "change", { target: { files: [file], value: "fixture.txt" } });
  assert.equal(harness.elements.get("reader_notice").textContent, "正在导入 TXT，请稍候…");
  await harness.flush();
  assert.ok(harness.calls.some((item) => item.method === "import" && item.file === file));
  assert.equal(harness.elements.get("reader_notice").textContent, "TXT 导入完成，内容已加载。");
});

test("Reader restores saved progress while keeping all earlier chapter text in the scroll area", async () => {
  const harness = createHarness({ progressOffset: 12000 });
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  const requests = harness.calls.filter((item) => item.method === "content");
  assert.deepEqual(requests.map((item) => item.startOffset), [0, 12000]);
  assert.equal(harness.context.DocxToolReader._testing.getState().content.start_offset, 0);
  assert.equal(harness.elements.get("reader_content").children.length, 3);
  assert.equal(harness.elements.get("reader_content").scrollTop, 600);
  assert.ok(harness.logs.some((item) => item.event === "reader.progress.restore.prefix.completed"));
  assert.ok(harness.logs.some((item) => item.event === "reader.progress.restore.completed"));
});

test("Reader speed slider maps only to the existing six saved values", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  assert.equal(harness.elements.get("reader_speed_visual").value, "2");
  const expected = [0.5, 0.75, 1, 1.25, 1.5, 2];
  expected.forEach((value, index) => {
    harness.elements.get("reader_speed_visual").value = String(index);
    harness.dispatch("reader_speed_visual", "input");
    harness.dispatch("reader_speed_visual", "change");
    const settings = harness.calls.filter((item) => item.method === "settings").at(-1);
    assert.equal(settings.settings.auto_scroll_speed, value);
  });
  assert.equal(harness.elements.get("reader_speed_value").textContent, "2.0×");
});

test("Reader progress is a read-only visual of the whole-book ratio", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  harness.elements.get("reader_content").scrollTop = 450;
  harness.setNow(2000);
  harness.dispatch("reader_content", "scroll");
  assert.equal(harness.elements.get("reader_progress_value").textContent, "7.50%");
  assert.equal(harness.elements.get("reader_progress_fill").style.width, "7.50%");
  const saved = harness.calls.filter((item) => item.method === "progress").at(-1);
  assert.ok(saved.progress.scroll_ratio > 0.07 && saved.progress.scroll_ratio < 0.08);
  assert.equal(harness.elements.get("reader_progress_fill").listeners.has("input"), false);
  assert.equal(harness.elements.get("reader_progress_fill").listeners.has("change"), false);
});

test("Reader pages by viewport height with one-line overlap", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  harness.elements.get("reader_content").scrollTop = 450;
  harness.dispatch("reader_content", "scroll");
  const first = harness.elements.get("reader_progress_value").textContent;
  harness.dispatch("reader_next_block", "click");
  await harness.flush();
  assert.equal(harness.calls.filter((item) => item.method === "navigate").length, 0);
  assert.equal(harness.elements.get("reader_content").scrollTop, 724.4);
  assert.equal(harness.elements.get("reader_previous_block").disabled, false);
  assert.notEqual(first, "0%");
  assert.ok(harness.logs.some((item) => item.event === "reader.navigation.requested"));
  assert.ok(harness.logs.some((item) => item.event === "reader.navigation.scroll.completed"));
  assert.equal(harness.logs.find((item) => item.event === "reader.navigation.scroll.completed").details.navigation_mode, "viewport_page");
});

test("Reader page navigation loads adjacent bounded windows at their visual edges", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  harness.elements.get("reader_content").scrollTop = 900;
  harness.dispatch("reader_next_block", "click");
  await harness.flush();
  assert.equal(harness.calls.filter((item) => item.method === "content").at(-1).startOffset, 12000);
  assert.equal(harness.elements.get("reader_content").scrollTop, 0);

  harness.dispatch("reader_previous_block", "click");
  await harness.flush();
  assert.equal(harness.calls.filter((item) => item.method === "content").at(-1).startOffset, 0);
  assert.equal(harness.elements.get("reader_content").scrollTop, 900);
  assert.ok(harness.logs.filter((item) => item.event === "reader.navigation.window.completed").length >= 2);
});

test("Reader playback loads the next bounded window instead of stopping at a block boundary", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  harness.elements.get("reader_content").scrollTop = 900;
  harness.dispatch("reader_play", "click");
  await harness.flush();

  assert.equal(harness.context.DocxToolReader._testing.getState().playing, true);
  assert.ok(harness.calls.some((item) => item.method === "content" && item.startOffset === 12000));
  assert.ok(harness.logs.some((item) => item.event === "reader.play.window.completed"));
});

test("Reader explains why playback cannot continue at the end of the book", async () => {
  const harness = createHarness({ progressChapterIndex: 1, progressOffset: 60000 });
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();

  harness.elements.get("reader_content").scrollTop = 900;
  harness.dispatch("reader_play", "click");

  assert.equal(harness.context.DocxToolReader._testing.getState().playing, false);
  assert.equal(harness.elements.get("reader_notice").textContent, "已到正文末尾，请点击“上一页”返回。");
  assert.ok(harness.logs.some((item) => item.event === "reader.play.unavailable"));
});

test("Reader keyboard shortcuts are scoped to the reading content", async () => {
  const harness = createHarness();
  harness.context.DocxToolReader.initialize();
  await harness.context.DocxToolReader.activate();
  await harness.flush();
  let prevented = false;
  harness.dispatch("reader_content", "keydown", {
    key: "ArrowRight", preventDefault() { prevented = true; },
  });
  await harness.flush();
  assert.equal(prevented, true);
  assert.equal(harness.elements.get("reader_content").scrollTop, 274.4);
  assert.equal(harness.calls.filter((item) => item.method === "navigate").length, 0);
  assert.doesNotMatch(UI_SOURCE, /window\.Application|ActiveDocument|\bRange\b|\bComments\b/);
});
