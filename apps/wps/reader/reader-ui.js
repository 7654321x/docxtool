(function (global) {
  "use strict";

  const client = global.DocxToolReaderClient;
  const BLOCK_CHARS = 12000;
  const SAVE_INTERVAL_MS = 1500;
  const SPEED_PIXELS_PER_SECOND = 28;
  const SPEED_VALUES = Object.freeze([0.5, 0.75, 1, 1.25, 1.5, 2]);
  let state = null;
  let content = null;
  let playing = false;
  let frame = 0;
  let previousTimestamp = 0;
  let lastSavedAt = 0;
  let collapsed = false;
  let automaticScrollUntil = 0;

  function node(id) {
    const value = document.getElementById(id);
    if (!value) throw new Error("READER_ELEMENT_MISSING");
    return value;
  }

  function optionalNode(id) { return document.getElementById(id); }

  function log(level, event, message, details) {
    if (typeof global.DocxToolTaskpaneLog !== "function") return;
    global.DocxToolTaskpaneLog(level, event, message, details || {});
  }

  function activeBook() { return state && state.current_book; }
  function chapters() { return state && Array.isArray(state.chapters) ? state.chapters : []; }

  function togglePopover(id, focusId) {
    const panel = optionalNode(id);
    if (!panel) return;
    panel.hidden = !panel.hidden;
    if (!panel.hidden && focusId) {
      const target = optionalNode(focusId);
      if (target && typeof target.focus === "function") target.focus();
    }
  }

  function updateSettingButtonLabels(settings) {
    const labels = {
      reader_font_setting_label: `字号 ${settings.font_size || 16}`,
      reader_line_setting_label: `行距 ${settings.line_height || 1.6}`,
      reader_theme_setting_label: `主题 ${{ light: "浅色", soft_gray: "柔和灰", eye_care: "护眼" }[settings.theme] || "浅色"}`,
      reader_opacity_setting_label: `透明度 ${Math.round(Number(settings.opacity || 1) * 100)}%`,
    };
    Object.entries(labels).forEach(([id, text]) => {
      const target = optionalNode(id);
      if (target) target.textContent = text;
    });
  }

  function formatSpeed(value) {
    return `${Number(value).toFixed(2).replace(/0$/, "")}×`;
  }

  function speedIndex(value) {
    const numeric = Number(value);
    let bestIndex = 0;
    let bestDistance = Number.POSITIVE_INFINITY;
    SPEED_VALUES.forEach((candidate, index) => {
      const distance = Math.abs(candidate - numeric);
      if (distance < bestDistance) {
        bestDistance = distance;
        bestIndex = index;
      }
    });
    return bestIndex;
  }

  function speedValueFromIndex(value) {
    const index = Math.max(0, Math.min(SPEED_VALUES.length - 1, Number(value) || 0));
    return SPEED_VALUES[index];
  }

  function updateSpeedVisual(value) {
    const visual = optionalNode("reader_speed_visual");
    const label = optionalNode("reader_speed_value");
    const numeric = Number(value);
    const current = Number.isFinite(numeric) ? numeric : 1;
    if (visual) {
      visual.value = String(speedIndex(current));
      if (typeof visual.setAttribute === "function") visual.setAttribute("aria-valuetext", formatSpeed(current));
    }
    if (label) label.textContent = formatSpeed(current);
  }

  function updateProgressVisual() {
    const fill = optionalNode("reader_progress_fill");
    const value = optionalNode("reader_progress_value");
    if (!fill || !value) return;
    const progress = currentProgress();
    const ratio = progress ? progress.scroll_ratio : 0;
    fill.style.width = `${Math.round(ratio * 100)}%`;
    value.textContent = `${Math.round(ratio * 100)}%`;
  }

  function displayError(error) {
    const code = error && error.message ? error.message : "WPS_READER_REQUEST_FAILED";
    const messages = {
      READER_FILE_EMPTY: "TXT 文件为空。",
      READER_FILE_TOO_LARGE: "TXT 文件超过本地导入大小限制。",
      READER_ENCODING_UNSUPPORTED: "无法识别 TXT 编码。",
      READER_BOOK_NOT_FOUND: "未找到所选书籍。",
      READER_CONTENT_NOT_FOUND: "未找到本地阅读内容。",
      READER_PROGRESS_INVALID: "阅读进度无效。",
    };
    node("reader_error").textContent = `${messages[code] || "阅读操作失败。"} 错误代码：${code}`;
  }

  function clearError() { node("reader_error").textContent = ""; }

  function renderState() {
    const book = activeBook();
    const select = node("reader_book_select");
    select.replaceChildren(...(state.books || []).map((item) => {
      const option = document.createElement("option");
      option.value = item.id;
      option.textContent = item.display_name;
      option.selected = Boolean(book && item.id === book.id);
      return option;
    }));
    select.disabled = !book;
    node("reader_empty").hidden = Boolean(book);
    node("reader_controls").hidden = !book;
    node("reader_content").hidden = !book;
    node("reader_chapter").textContent = content ? content.chapter_title : "";
    const settings = state.settings || {};
    node("reader_font_size").value = String(settings.font_size || 16);
    node("reader_line_height").value = String(settings.line_height || 1.6);
    node("reader_theme").value = settings.theme || "light";
    node("reader_opacity").value = String(settings.opacity || 1);
    node("reader_speed").value = String(settings.auto_scroll_speed || 1);
    node("reader_stealth_mode").checked = Boolean(settings.stealth_mode);
    updateSpeedVisual(settings.auto_scroll_speed || 1);
    updateSettingButtonLabels(settings);
    updateProgressVisual();
    applyStyleSettings();
  }

  function renderContent() {
    const reader = node("reader_content");
    reader.replaceChildren();
    if (!content) return;
    const fragments = content.text.split(/\n{2,}/).filter(Boolean);
    reader.replaceChildren(...fragments.map((value) => {
      const paragraph = document.createElement("p");
      paragraph.textContent = value;
      return paragraph;
    }));
    reader.scrollTop = 0;
    node("reader_chapter").textContent = content.chapter_title;
    updateNavigation();
    updateProgressVisual();
  }

  function updateNavigation() {
    const chapterIndex = content ? content.chapter_index : 0;
    node("reader_previous_chapter").disabled = chapterIndex <= 0;
    node("reader_next_chapter").disabled = chapterIndex >= chapters().length - 1;
    node("reader_previous_block").disabled = !content || content.start_offset <= content.chapter_start_offset;
    node("reader_next_block").disabled = !content || content.end_offset >= content.chapter_end_offset;
    const playLabel = optionalNode("reader_play_label");
    const playIcon = optionalNode("reader_play_icon");
    if (playLabel) playLabel.textContent = playing ? "暂停" : "播放";
    else node("reader_play").textContent = playing ? "暂停" : "播放";
    if (playIcon && typeof playIcon.setAttribute === "function") {
      playIcon.setAttribute("href", `./images/taskpane-icons.svg#${playing ? "pause" : "play"}`);
    }
  }

  async function refresh({ restoreProgress = false } = {}) {
    state = await client.loadState();
    renderState();
    const book = activeBook();
    if (!book) {
      content = null;
      renderContent();
      return;
    }
    const progress = state.progress || {};
    await loadContent(
      Number(progress.chapter_index || 0),
      restoreProgress ? Number(progress.text_offset) : undefined,
    );
  }

  async function loadContent(chapterIndex, startOffset) {
    pause(false);
    const book = activeBook();
    if (!book) return;
    content = await client.loadContent(book.id, chapterIndex, startOffset, BLOCK_CHARS);
    renderContent();
  }

  function currentProgress() {
    if (!content || !activeBook()) return null;
    const reader = node("reader_content");
    const usableHeight = Math.max(1, reader.scrollHeight - reader.clientHeight);
    const ratio = Math.max(0, Math.min(1, reader.scrollTop / usableHeight));
    const offset = Math.min(
      content.chapter_end_offset,
      content.start_offset + Math.round((content.end_offset - content.start_offset) * ratio),
    );
    return {
      book_id: activeBook().id,
      chapter_index: content.chapter_index,
      text_offset: offset,
      scroll_ratio: ratio,
    };
  }

  async function saveProgress(force) {
    const progress = currentProgress();
    if (!progress) return;
    const now = Date.now();
    if (!force && now - lastSavedAt < SAVE_INTERVAL_MS) return;
    lastSavedAt = now;
    try {
      state.progress = (await client.saveProgress(progress)).progress;
      log("INFO", "reader.progress.saved", "阅读进度已保存", { book_id_short: progress.book_id.slice(0, 12) });
    } catch (error) {
      log("ERROR", "reader.progress.save_failed", "阅读进度保存失败", { error_code: error.message || "READER_PROGRESS_SAVE_FAILED" });
      displayError(error);
    }
  }

  function pause(save) {
    if (frame) global.cancelAnimationFrame(frame);
    frame = 0;
    previousTimestamp = 0;
    const wasPlaying = playing;
    playing = false;
    updateNavigation();
    if (wasPlaying) log("INFO", "reader.play.paused", "阅读自动滚动已暂停", {});
    if (save) void saveProgress(true);
  }

  function tick(timestamp) {
    if (!playing) return;
    if (!previousTimestamp) previousTimestamp = timestamp;
    const elapsed = Math.min(250, timestamp - previousTimestamp);
    previousTimestamp = timestamp;
    const speed = Number((state.settings || {}).auto_scroll_speed || 1);
    const reader = node("reader_content");
    automaticScrollUntil = Date.now() + 50;
    reader.scrollTop += SPEED_PIXELS_PER_SECOND * speed * elapsed / 1000;
    if (reader.scrollTop + reader.clientHeight >= reader.scrollHeight - 1) {
      pause(true);
      return;
    }
    void saveProgress(false);
    frame = global.requestAnimationFrame(tick);
  }

  function play() {
    if (!content || playing) return;
    playing = true;
    updateNavigation();
    log("INFO", "reader.play.started", "阅读自动滚动已开始", {});
    frame = global.requestAnimationFrame(tick);
  }

  function applyStyleSettings() {
    const settings = state && state.settings ? state.settings : {};
    const reader = node("reader_content");
    reader.style.fontSize = `${settings.font_size || 16}px`;
    reader.style.lineHeight = String(settings.line_height || 1.6);
    reader.style.opacity = String(settings.opacity || 1);
    reader.dataset.theme = settings.theme || "light";
  }

  async function saveSettings() {
    const settings = {
      font_size: Number(node("reader_font_size").value),
      line_height: Number(node("reader_line_height").value),
      theme: node("reader_theme").value,
      opacity: Number(node("reader_opacity").value),
      auto_scroll_speed: Number.isFinite(Number(node("reader_speed").value))
        && Number(node("reader_speed").value) >= 0.5
        ? Number(node("reader_speed").value)
        : Number((state.settings || {}).auto_scroll_speed || 1),
      stealth_mode: Boolean(node("reader_stealth_mode").checked),
    };
    state.settings = (await client.saveSettings(settings)).settings;
    updateSpeedVisual(state.settings.auto_scroll_speed || 1);
    updateSettingButtonLabels(state.settings);
    applyStyleSettings();
    log("INFO", "reader.settings.saved", "阅读设置已保存", {});
  }

  async function changeBlock(direction) {
    if (!content) return;
    const target = direction < 0
      ? Math.max(content.chapter_start_offset, content.start_offset - BLOCK_CHARS)
      : content.end_offset;
    if (target === content.start_offset) return;
    await saveProgress(true);
    await loadContent(content.chapter_index, target);
  }

  async function changeChapter(direction) {
    if (!content) return;
    const next = content.chapter_index + direction;
    if (next < 0 || next >= chapters().length) return;
    await saveProgress(true);
    await loadContent(next);
  }

  async function importBook(file) {
    if (!file) return;
    pause(false);
    clearError();
    await client.importBook(file);
    await refresh();
  }

  async function selectBook(bookId) {
    pause(true);
    await client.selectBook(bookId);
    await refresh({ restoreProgress: true });
  }

  async function deleteCurrentBook() {
    const book = activeBook();
    if (!book || !global.confirm("确定删除此本地托管书籍吗？原始 TXT 不会被删除。")) return;
    pause(false);
    await client.deleteBook(book.id);
    await refresh();
  }

  function setCollapsed(value) {
    collapsed = Boolean(value);
    pause(true);
    node("reader_panel").classList.toggle("reader-collapsed", collapsed);
    node("reader_reveal").hidden = !collapsed;
    log("INFO", collapsed ? "reader.ui.collapsed" : "reader.ui.revealed", collapsed ? "阅读界面已折叠" : "阅读界面已展开", {});
  }

  function bind() {
    node("reader_import").addEventListener("change", (event) => {
      void importBook(event.target.files && event.target.files[0]).catch(displayError);
      event.target.value = "";
    });
    node("reader_book_select").addEventListener("change", (event) => void selectBook(event.target.value).catch(displayError));
    node("reader_delete").addEventListener("click", () => void deleteCurrentBook().catch(displayError));
    node("reader_previous_block").addEventListener("click", () => void changeBlock(-1).catch(displayError));
    node("reader_next_block").addEventListener("click", () => void changeBlock(1).catch(displayError));
    node("reader_previous_chapter").addEventListener("click", () => void changeChapter(-1).catch(displayError));
    node("reader_next_chapter").addEventListener("click", () => void changeChapter(1).catch(displayError));
    node("reader_play").addEventListener("click", () => playing ? pause(true) : play());
    ["reader_font_size", "reader_line_height", "reader_theme", "reader_opacity", "reader_speed", "reader_stealth_mode"].forEach((id) => {
      node(id).addEventListener("change", () => void saveSettings().catch(displayError));
    });
    const speedVisual = optionalNode("reader_speed_visual");
    if (speedVisual) {
      speedVisual.addEventListener("input", () => updateSpeedVisual(speedValueFromIndex(speedVisual.value)));
      speedVisual.addEventListener("change", () => {
        node("reader_speed").value = String(speedValueFromIndex(speedVisual.value));
        void saveSettings().catch(displayError);
      });
    }
    node("reader_stealth").addEventListener("click", () => setCollapsed(true));
    if (optionalNode("reader_book_library")) {
      node("reader_book_library").addEventListener("click", () => togglePopover("reader_library", "reader_book_select"));
    }
    [
      ["reader_font_setting", "reader_font_size"],
      ["reader_line_setting", "reader_line_height"],
      ["reader_theme_setting", "reader_theme"],
      ["reader_opacity_setting", "reader_opacity"],
    ].forEach(([buttonId, focusId]) => {
      if (optionalNode(buttonId)) node(buttonId).addEventListener("click", () => togglePopover("reader_settings_popover", focusId));
    });
    node("reader_reveal").addEventListener("mouseenter", () => setCollapsed(false));
    node("reader_content").addEventListener("scroll", () => {
      if (playing && Date.now() > automaticScrollUntil) pause(false);
      updateProgressVisual();
      void saveProgress(false);
    });
    node("reader_content").addEventListener("mouseup", () => pause(true));
    node("reader_content").addEventListener("mouseleave", () => {
      if ((state.settings || {}).stealth_mode) setCollapsed(true);
      else pause(true);
    });
    node("reader_content").addEventListener("keydown", (event) => {
      if (event.key === " ") {
        event.preventDefault();
        playing ? pause(true) : play();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        void changeBlock(-1).catch(displayError);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        void changeBlock(1).catch(displayError);
      }
    });
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState !== "visible") pause(true);
    });
  }

  global.DocxToolReader = Object.freeze({
    async activate() {
      node("reader_panel").hidden = false;
      if (!state) await refresh({ restoreProgress: true });
    },
    deactivate() {
      pause(true);
      node("reader_panel").hidden = true;
    },
    pauseAndSave() { pause(true); },
    initialize() { bind(); },
    _testing: {
      getState: () => ({ state, content, playing, collapsed }),
      tick,
      setState(value) { state = value; },
    },
  });
})(window);
