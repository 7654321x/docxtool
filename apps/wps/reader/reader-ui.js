(function (global) {
  "use strict";

  const client = global.DocxToolReaderClient;
  const BLOCK_CHARS = 12000;
  const SAVE_INTERVAL_MS = 1500;
  const PLAY_LINE_INTERVAL_MS = 450;
  const SPEED_VALUES = Object.freeze([0.5, 0.75, 1, 1.25, 1.5, 2]);
  let state = null;
  let content = null;
  let playing = false;
  let frame = 0;
  let previousTimestamp = 0;
  let playElapsedMs = 0;
  let playbackLoading = false;
  let lastSavedAt = 0;
  let collapsed = false;
  let resumePlaybackAfterReveal = false;
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

  function totalBookChars() {
    const items = chapters();
    if (!items.length) return 0;
    const endOffset = Number(items[items.length - 1].end_offset);
    return Number.isFinite(endOffset) && endOffset > 0 ? endOffset : 0;
  }

  function readerDetails(extras) {
    const reader = optionalNode("reader_content");
    const book = activeBook();
    const paragraphs = contentParagraphs();
    return Object.assign({
      book_id_short: book && book.id ? book.id.slice(0, 12) : "",
      chapter_index: content ? content.chapter_index : -1,
      start_offset: content ? content.start_offset : -1,
      end_offset: content ? content.end_offset : -1,
      chapter_end_offset: content ? content.chapter_end_offset : -1,
      text_chars: content && typeof content.text === "string" ? content.text.length : 0,
      paragraph_count: paragraphs.length,
      reader_scroll_top: reader ? Number(reader.scrollTop || 0) : -1,
      reader_scroll_height: reader ? Number(reader.scrollHeight || 0) : -1,
      reader_client_height: reader ? Number(reader.clientHeight || 0) : -1,
    }, extras || {});
  }

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

  function updateStealthVisual(enabled) {
    const button = optionalNode("reader_stealth");
    if (!button) return;
    const active = Boolean(enabled);
    button.classList.toggle("reader-tool-button-active", active);
    if (typeof button.setAttribute === "function") button.setAttribute("aria-pressed", String(active));
  }

  function updateProgressVisual() {
    const fill = optionalNode("reader_progress_fill");
    const value = optionalNode("reader_progress_value");
    if (!fill || !value) return;
    const progress = currentProgress();
    const ratio = progress ? progress.scroll_ratio : 0;
    const percentage = (ratio * 100).toFixed(2);
    fill.style.width = `${percentage}%`;
    value.textContent = `${percentage}%`;
  }

  function displayError(error) {
    const notice = optionalNode("reader_notice");
    if (notice) notice.textContent = "";
    const code = error && error.message ? error.message : "WPS_READER_REQUEST_FAILED";
    const messages = {
      READER_FILE_EMPTY: "TXT 文件为空。",
      READER_FILE_TOO_LARGE: "TXT 文件超过本地导入大小限制。",
      READER_ENCODING_UNSUPPORTED: "无法识别 TXT 编码。",
      READER_BOOK_NOT_FOUND: "未找到所选书籍。",
      READER_CONTENT_NOT_FOUND: "未找到本地阅读内容。",
      READER_PROGRESS_INVALID: "阅读进度无效。",
    };
    node("reader_error").textContent = messages[code] || "本地阅读服务异常，请关闭 WPS 后重新打开。";
    log("ERROR", "reader.ui.error", "Reader 操作失败", { error_code: code });
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
    updateStealthVisual(settings.stealth_mode);
    updateSettingButtonLabels(settings);
    updateProgressVisual();
    applyStyleSettings();
    log("INFO", "reader.state.rendered", "本地书库状态已渲染", {
      book_count: Array.isArray(state.books) ? state.books.length : 0,
      book_id_short: book && book.id ? book.id.slice(0, 12) : "",
      chapter_count: chapters().length,
    });
  }

  function renderContent() {
    const reader = node("reader_content");
    reader.replaceChildren();
    if (!content) return;
    const paragraphs = contentParagraphs();
    reader.replaceChildren(...paragraphs.map((item) => {
      const paragraph = document.createElement("p");
      paragraph.textContent = item.text;
      paragraph.dataset.startOffset = String(item.startOffset);
      return paragraph;
    }));
    reader.scrollTop = 0;
    node("reader_chapter").textContent = content.chapter_title;
    updateNavigation();
    updateProgressVisual();
    log(
      paragraphs.length ? "INFO" : "ERROR",
      paragraphs.length ? "reader.content.render.completed" : "reader.content.render.empty",
      paragraphs.length ? "Reader 正文已渲染" : "Reader 正文没有可渲染段落",
      readerDetails({ rendered_paragraph_count: reader.children.length }),
    );
    if (!paragraphs.length) {
      node("reader_error").textContent = "当前书籍没有可显示的正文。";
    }
  }

  function contentParagraphs() {
    if (!content) return [];
    const paragraphs = [];
    let offset = content.start_offset;
    content.text.split("\n").forEach((value) => {
      if (value.trim()) paragraphs.push({ text: value, startOffset: offset });
      offset += value.length + 1;
    });
    return paragraphs;
  }

  function contentParagraphStarts() {
    return contentParagraphs().map((item) => item.startOffset);
  }

  function clamp(value, minimum, maximum) {
    return Math.max(minimum, Math.min(maximum, value));
  }

  function lineHeightPixels() {
    const reader = node("reader_content");
    if (typeof global.getComputedStyle === "function") {
      const computed = global.getComputedStyle(reader);
      const computedLineHeight = Number.parseFloat(computed.lineHeight);
      if (Number.isFinite(computedLineHeight) && computedLineHeight > 0) return computedLineHeight;
    }
    const settings = state && state.settings ? state.settings : {};
    return Math.max(1, Number(settings.font_size || 16) * Number(settings.line_height || 1.6));
  }

  function pageDistancePixels() {
    const reader = node("reader_content");
    return Math.max(lineHeightPixels(), Number(reader.clientHeight || 0) - lineHeightPixels());
  }

  function readerParagraphMetrics() {
    const reader = node("reader_content");
    const readerRect = typeof reader.getBoundingClientRect === "function"
      ? reader.getBoundingClientRect()
      : null;
    return Array.prototype.map.call(reader.children, (paragraph, index) => {
      const paragraphRect = typeof paragraph.getBoundingClientRect === "function"
        ? paragraph.getBoundingClientRect()
        : null;
      const top = paragraphRect && readerRect
        ? Number(paragraphRect.top) - Number(readerRect.top)
        : Number(paragraph.offsetTop || 0) - Number(reader.scrollTop || 0);
      const measuredHeight = paragraphRect ? Number(paragraphRect.height) : Number(paragraph.offsetHeight || 0);
      const height = Number.isFinite(measuredHeight) && measuredHeight > 0 ? measuredHeight : lineHeightPixels();
      return {
        index,
        startOffset: Number(paragraph.dataset.startOffset),
        textLength: String(paragraph.textContent || "").length,
        top,
        bottom: top + height,
        height,
      };
    }).filter((item) => Number.isFinite(item.startOffset) && Number.isFinite(item.top));
  }

  function visualOffset() {
    if (!content || !activeBook()) return 0;
    const reader = node("reader_content");
    const metrics = readerParagraphMetrics();
    const visible = metrics.find((item) => item.bottom > 0 && item.top < Number(reader.clientHeight || 0));
    if (visible) {
      const fraction = clamp(-visible.top / visible.height, 0, 1);
      return clamp(
        visible.startOffset + Math.round(visible.textLength * fraction),
        content.start_offset,
        content.end_offset,
      );
    }
    const usableHeight = reader.scrollHeight - reader.clientHeight;
    const localRatio = usableHeight > 0
      ? clamp(reader.scrollTop / usableHeight, 0, 1)
      : 1;
    return Math.min(
      content.chapter_end_offset,
      content.start_offset + Math.round((content.end_offset - content.start_offset) * localRatio),
    );
  }

  function updateNavigation() {
    const chapterIndex = content ? content.chapter_index : 0;
    node("reader_previous_chapter").disabled = chapterIndex <= 0;
    node("reader_next_chapter").disabled = chapterIndex >= chapters().length - 1;
    const reader = node("reader_content");
    const atStart = Number(reader.scrollTop || 0) <= 1;
    const atEnd = Number(reader.scrollTop || 0) + Number(reader.clientHeight || 0)
      >= Number(reader.scrollHeight || 0) - 1;
    node("reader_previous_block").disabled = !content
      || (atStart && content.start_offset <= content.chapter_start_offset);
    node("reader_next_block").disabled = !content
      || (atEnd && content.end_offset >= content.chapter_end_offset);
    const playLabel = optionalNode("reader_play_label");
    const playIcon = optionalNode("reader_play_icon");
    if (playLabel) playLabel.textContent = playing ? "暂停" : "播放";
    else node("reader_play").textContent = playing ? "暂停" : "播放";
    if (playIcon && typeof playIcon.setAttribute === "function") {
      playIcon.setAttribute("href", `./images/taskpane-icons.svg#${playing ? "pause" : "play"}`);
    }
  }

  async function refresh({ restoreProgress = false } = {}) {
    log("INFO", "reader.state.load.start", "开始读取本地书库状态", {
      stage: restoreProgress ? "restore_progress" : "refresh",
    });
    state = await client.loadState();
    log("INFO", "reader.state.load.completed", "本地书库状态读取完成", {
      book_count: Array.isArray(state.books) ? state.books.length : 0,
      book_id_short: activeBook() && activeBook().id ? activeBook().id.slice(0, 12) : "",
      chapter_count: chapters().length,
    });
    renderState();
    const book = activeBook();
    if (!book) {
      content = null;
      renderContent();
      log("INFO", "reader.state.empty", "本地书库没有当前书籍", { book_count: 0 });
      return;
    }
    const progress = state.progress || {};
    const chapterIndex = Number(progress.chapter_index || 0);
    const restoredOffset = restoreProgress && Number.isInteger(Number(progress.text_offset))
      ? Number(progress.text_offset)
      : undefined;
    const chapter = chapters()[chapterIndex];
    if (Number.isInteger(restoredOffset) && chapter) {
      await loadRestoredContent(chapterIndex, restoredOffset);
      return;
    }
    await loadContent(chapterIndex);
  }

  async function loadRestoredContent(chapterIndex, restoredOffset) {
    pause(false);
    const book = activeBook();
    const chapter = chapters()[chapterIndex];
    if (!book || !chapter) throw new Error("READER_CONTENT_NOT_FOUND");
    const targetEnd = Math.min(
      chapter.end_offset,
      Math.max(chapter.start_offset + BLOCK_CHARS, restoredOffset + Math.floor(BLOCK_CHARS / 2)),
    );
    let cursor = chapter.start_offset;
    let combined = null;
    let blockCount = 0;
    log("INFO", "reader.progress.restore.prefix.start", "开始从本章开头恢复阅读正文", {
      book_id_short: book.id.slice(0, 12),
      chapter_index: chapterIndex,
      requested_start_offset: restoredOffset,
      content_end_offset: targetEnd,
    });
    while (cursor < targetEnd) {
      const part = await client.loadContent(book.id, chapterIndex, cursor, BLOCK_CHARS);
      blockCount += 1;
      if (!combined) {
        combined = { ...part };
      } else {
        const overlap = Math.max(0, combined.end_offset - part.start_offset);
        combined.text += part.text.slice(overlap);
        combined.end_offset = part.end_offset;
      }
      if (part.end_offset <= cursor) throw new Error("READER_CONTENT_WINDOW_STALLED");
      cursor = part.end_offset;
    }
    content = combined;
    log("INFO", "reader.content.load.completed", "Reader 正文加载完成", readerDetails({
      requested_start_offset: chapter.start_offset,
    }));
    log("INFO", "reader.progress.restore.prefix.completed", "已保留阅读位置之前的本章正文", readerDetails({
      requested_start_offset: restoredOffset,
      content_end_offset: content ? content.end_offset : -1,
      block_count: blockCount,
    }));
    renderContent();
    restoreLoadedProgress(restoredOffset);
  }

  async function loadContent(chapterIndex, startOffset, restoredOffset, options = {}) {
    if (!options.preservePlaying) pause(false);
    const book = activeBook();
    if (!book) return;
    log("INFO", "reader.content.load.start", "开始加载 Reader 正文", {
      book_id_short: book.id.slice(0, 12),
      chapter_index: chapterIndex,
      requested_start_offset: Number.isInteger(startOffset) ? startOffset : -1,
    });
    content = await client.loadContent(book.id, chapterIndex, startOffset, BLOCK_CHARS);
    log("INFO", "reader.content.load.completed", "Reader 正文加载完成", readerDetails({
      requested_start_offset: Number.isInteger(startOffset) ? startOffset : -1,
    }));
    renderContent();
    if (Number.isInteger(restoredOffset)) restoreLoadedProgress(restoredOffset);
  }

  function restoreLoadedProgress(restoredOffset) {
    const starts = contentParagraphStarts().filter((value) => value <= restoredOffset);
    const targetOffset = starts.length ? starts[starts.length - 1] : content.start_offset;
    const restored = scrollToLoadedParagraph(targetOffset, false);
    log(restored ? "INFO" : "WARNING", "reader.progress.restore.completed", restored
      ? "Reader 已恢复到保存的阅读位置"
      : "Reader 未能滚动到保存的阅读位置", readerDetails({
      requested_start_offset: restoredOffset,
      target_offset: targetOffset,
      reason: restored ? "position_restored" : "target_not_rendered",
    }));
  }

  function currentProgress() {
    if (!content || !activeBook()) return null;
    const offset = visualOffset();
    const totalChars = totalBookChars();
    const globalRatio = totalChars > 0 ? Math.max(0, Math.min(1, offset / totalChars)) : 0;
    return {
      book_id: activeBook().id,
      chapter_index: content.chapter_index,
      text_offset: offset,
      scroll_ratio: globalRatio,
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
      log("INFO", "reader.progress.saved", "阅读进度已保存", {
        book_id_short: progress.book_id.slice(0, 12),
        progress_offset: progress.text_offset,
        progress_percent: Number((progress.scroll_ratio * 100).toFixed(2)),
      });
    } catch (error) {
      log("ERROR", "reader.progress.save_failed", "阅读进度保存失败", { error_code: error.message || "READER_PROGRESS_SAVE_FAILED" });
      displayError(error);
    }
  }

  function pause(save) {
    if (frame) global.cancelAnimationFrame(frame);
    frame = 0;
    previousTimestamp = 0;
    playElapsedMs = 0;
    const wasPlaying = playing;
    playing = false;
    updateNavigation();
    if (wasPlaying) log("INFO", "reader.play.paused", "阅读自动滚动已暂停", {});
    if (save) void saveProgress(true);
  }

  async function continuePlaybackWindow() {
    if (!playing || playbackLoading || !content) return;
    playbackLoading = true;
    try {
      const nextChapterIndex = content.chapter_index + 1;
      if (content.end_offset < content.chapter_end_offset) {
        log("INFO", "reader.play.window.requested", "自动滚动准备加载后续正文窗口", readerDetails({
          requested_start_offset: content.end_offset,
          direction: 1,
        }));
        await loadContent(content.chapter_index, content.end_offset, undefined, { preservePlaying: true });
      } else if (nextChapterIndex < chapters().length) {
        log("INFO", "reader.play.chapter.requested", "自动滚动准备进入下一章", readerDetails({
          chapter_index: nextChapterIndex,
          direction: 1,
        }));
        await loadContent(nextChapterIndex, undefined, undefined, { preservePlaying: true });
      } else {
        log("INFO", "reader.play.reached_end", "自动滚动已到整本书末尾", readerDetails({ at_end: true }));
        pause(true);
        return;
      }
      log("INFO", "reader.play.window.completed", "自动滚动已加载后续正文并继续", readerDetails({
        direction: 1,
      }));
    } finally {
      playbackLoading = false;
      if (playing) {
        previousTimestamp = 0;
        frame = global.requestAnimationFrame(tick);
      }
    }
  }

  function tick(timestamp) {
    if (!playing || playbackLoading) return;
    if (!previousTimestamp) previousTimestamp = timestamp;
    const elapsed = Math.min(250, timestamp - previousTimestamp);
    previousTimestamp = timestamp;
    const speed = Number((state.settings || {}).auto_scroll_speed || 1);
    const reader = node("reader_content");
    const interval = Math.max(80, PLAY_LINE_INTERVAL_MS / Math.max(0.5, speed));
    const lineHeight = lineHeightPixels();
    playElapsedMs += elapsed;
    automaticScrollUntil = Date.now() + 50;
    while (playElapsedMs >= interval) {
      playElapsedMs -= interval;
      reader.scrollTop = Math.min(
        Math.max(0, reader.scrollHeight - reader.clientHeight),
        reader.scrollTop + lineHeight,
      );
      log("INFO", "reader.play.line.completed", "自动滚动已向下阅读一行", readerDetails({
        line_height_px: Math.round(lineHeight * 100) / 100,
        speed,
      }));
      if (reader.scrollTop + reader.clientHeight >= reader.scrollHeight - 1) {
        void continuePlaybackWindow().catch(displayError);
        return;
      }
    }
    void saveProgress(false);
    frame = global.requestAnimationFrame(tick);
  }

  function play() {
    if (!content || playing) return;
    const reader = node("reader_content");
    const noScrollableContent = reader.scrollHeight <= reader.clientHeight + 1;
    const atEnd = reader.scrollTop + reader.clientHeight >= reader.scrollHeight - 1;
    log("INFO", "reader.play.requested", "用户请求开始自动滚动", readerDetails({ at_end: atEnd }));
    const bookEnded = content.end_offset >= content.chapter_end_offset
      && content.chapter_index >= chapters().length - 1;
    if (bookEnded && (noScrollableContent || atEnd)) {
      node("reader_notice").textContent = "已到正文末尾，请点击“上一页”返回。";
      log("WARNING", "reader.play.unavailable", "当前 Reader 位置无法继续自动滚动", readerDetails({
        at_end: atEnd,
        reason: "book_end",
      }));
      return;
    }
    node("reader_notice").textContent = "";
    playing = true;
    updateNavigation();
    log("INFO", "reader.play.started", "阅读自动滚动已开始", readerDetails({ at_end: false }));
    if (noScrollableContent || atEnd) void continuePlaybackWindow().catch(displayError);
    else frame = global.requestAnimationFrame(tick);
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
    updateStealthVisual(state.settings.stealth_mode);
    updateSettingButtonLabels(state.settings);
    applyStyleSettings();
    log("INFO", "reader.settings.saved", "阅读设置已保存", {});
  }

  async function changePage(direction) {
    if (!content) return;
    const navigationDirection = direction < 0 ? -1 : 1;
    pause(true);
    const reader = node("reader_content");
    const scrollTopBefore = Number(reader.scrollTop || 0);
    const maxScrollTop = Math.max(0, Number(reader.scrollHeight || 0) - Number(reader.clientHeight || 0));
    const atBoundary = navigationDirection < 0
      ? scrollTopBefore <= 1
      : scrollTopBefore + Number(reader.clientHeight || 0) >= Number(reader.scrollHeight || 0) - 1;
    const pageDistance = pageDistancePixels();
    node("reader_notice").textContent = "";
    log("INFO", "reader.navigation.requested", "用户请求翻阅相邻页面", readerDetails({
      direction: navigationDirection,
      navigation_mode: "viewport_page",
      page_distance_px: Math.round(pageDistance * 100) / 100,
      overlap_px: Math.round(lineHeightPixels() * 100) / 100,
      start_offset: visualOffset(),
    }));

    if (!atBoundary) {
      reader.scrollTop = clamp(
        scrollTopBefore + navigationDirection * pageDistance,
        0,
        maxScrollTop,
      );
      updateNavigation();
      updateProgressVisual();
      await saveProgress(true);
      log("INFO", "reader.navigation.scroll.completed", "Reader 已按视口翻阅页面", readerDetails({
        direction: navigationDirection,
        navigation_mode: "viewport_page",
        scroll_top_before: scrollTopBefore,
        scroll_top_after: Number(reader.scrollTop || 0),
        target_offset: visualOffset(),
      }));
      return;
    }

    if (navigationDirection > 0 && content.end_offset < content.chapter_end_offset) {
      const previousEndOffset = content.end_offset;
      await loadContent(content.chapter_index, content.end_offset);
      await saveProgress(true);
      log("INFO", "reader.navigation.window.completed", "下一页已加载后续正文窗口", readerDetails({
        direction: navigationDirection,
        navigation_mode: "viewport_page",
        requested_start_offset: previousEndOffset,
        target_offset: visualOffset(),
      }));
      return;
    }

    if (navigationDirection < 0 && content.start_offset > content.chapter_start_offset) {
      const previousStartOffset = content.start_offset;
      const previousWindowStart = Math.max(
        content.chapter_start_offset,
        content.start_offset - BLOCK_CHARS,
      );
      await loadContent(content.chapter_index, previousWindowStart);
      reader.scrollTop = Math.max(0, reader.scrollHeight - reader.clientHeight);
      updateNavigation();
      updateProgressVisual();
      await saveProgress(true);
      log("INFO", "reader.navigation.window.completed", "上一页已加载前一个正文窗口", readerDetails({
        direction: navigationDirection,
        navigation_mode: "viewport_page",
        requested_start_offset: previousWindowStart,
        target_offset: visualOffset(),
        previous_window_end_offset: previousStartOffset,
      }));
      return;
    }

    node("reader_notice").textContent = navigationDirection < 0
      ? "已经是本章开头。"
      : "本章内容已读完，请点击“下一章”。";
    log("INFO", "reader.navigation.unavailable", "当前章节没有更多可翻阅页面", readerDetails({
      direction: navigationDirection,
      navigation_mode: "viewport_page",
      reason: navigationDirection < 0 ? "chapter_start" : "chapter_end",
    }));
  }

  function scrollToLoadedParagraph(targetOffset, logNavigation = true) {
    const reader = node("reader_content");
    const scrollTopBefore = Number(reader.scrollTop || 0);
    const paragraph = Array.prototype.find.call(
      reader.children,
      (item) => Number(item.dataset.startOffset) === targetOffset,
    );
    if (!paragraph) return false;
    let targetTop = Number(paragraph.offsetTop);
    if (typeof paragraph.getBoundingClientRect === "function"
        && typeof reader.getBoundingClientRect === "function") {
      targetTop = reader.scrollTop
        + paragraph.getBoundingClientRect().top
        - reader.getBoundingClientRect().top;
    }
    if (!Number.isFinite(targetTop)) return false;
    reader.scrollTop = Math.max(0, targetTop);
    updateNavigation();
    updateProgressVisual();
    if (logNavigation) {
      log("INFO", "reader.navigation.scroll.completed", "Reader 已滚动到指定正文位置", readerDetails({
        target_offset: targetOffset,
        target_in_current_window: true,
        content_scroll_top: Number(reader.scrollTop || 0),
        reason: Number(reader.scrollTop || 0) === scrollTopBefore ? "position_unchanged" : "position_changed",
      }));
    }
    return true;
  }

  async function toggleStealthMode() {
    const checkbox = node("reader_stealth_mode");
    checkbox.checked = !checkbox.checked;
    await saveSettings();
  }

  async function changeChapter(direction) {
    if (!content) return;
    const next = content.chapter_index + direction;
    log("INFO", "reader.chapter.requested", "用户请求切换章节", readerDetails({ direction: direction < 0 ? -1 : 1 }));
    if (next < 0 || next >= chapters().length) {
      node("reader_notice").textContent = direction < 0 ? "已经是第一章。" : "已经是最后一章。";
      log("INFO", "reader.chapter.unavailable", "当前书籍没有相邻章节", readerDetails({
        direction: direction < 0 ? -1 : 1,
        reason: direction < 0 ? "first_chapter" : "last_chapter",
      }));
      return;
    }
    await saveProgress(true);
    await loadContent(next);
    log("INFO", "reader.chapter.completed", "Reader 已切换章节", readerDetails({ direction: direction < 0 ? -1 : 1 }));
  }

  async function importBook(file) {
    if (!file) return;
    pause(false);
    clearError();
    node("reader_notice").textContent = "正在导入 TXT，请稍候…";
    log("INFO", "reader.import.requested", "已提交本地 TXT 导入请求", {});
    await client.importBook(file);
    await refresh();
    node("reader_notice").textContent = "TXT 导入完成，内容已加载。";
    log("INFO", "reader.import.loaded", "本地 TXT 已导入并加载", {});
  }

  async function selectBook(bookId) {
    pause(true);
    log("INFO", "reader.book.select.requested", "用户请求切换本地书籍", { book_id_short: bookId.slice(0, 12) });
    await client.selectBook(bookId);
    await refresh({ restoreProgress: true });
    log("INFO", "reader.book.select.completed", "本地书籍已切换并加载", readerDetails({}));
  }

  async function deleteCurrentBook() {
    const book = activeBook();
    if (!book || !global.confirm("确定删除此本地托管书籍吗？原始 TXT 不会被删除。")) return;
    pause(false);
    await client.deleteBook(book.id);
    await refresh();
  }

  function setCollapsed(value) {
    const nextCollapsed = Boolean(value);
    if (nextCollapsed === collapsed) return;
    const shouldResume = !nextCollapsed && resumePlaybackAfterReveal;
    if (nextCollapsed) {
      resumePlaybackAfterReveal = playing;
      if (playing) {
        log("INFO", "reader.play.suspended.collapsed", "阅读栏隐藏，自动滚动已临时暂停", {});
      }
      pause(true);
    } else {
      resumePlaybackAfterReveal = false;
    }
    collapsed = nextCollapsed;
    node("reader_panel").classList.toggle("reader-collapsed", collapsed);
    node("reader_reveal").hidden = !collapsed;
    log("INFO", collapsed ? "reader.ui.collapsed" : "reader.ui.revealed", collapsed ? "阅读界面已折叠" : "阅读界面已展开", {});
    if (shouldResume) {
      log("INFO", "reader.play.resumed.revealed", "阅读栏重新出现，继续自动滚动", {});
      play();
    }
  }

  function bind() {
    node("reader_import").addEventListener("change", (event) => {
      void importBook(event.target.files && event.target.files[0]).catch(displayError);
      event.target.value = "";
    });
    node("reader_book_select").addEventListener("change", (event) => void selectBook(event.target.value).catch(displayError));
    node("reader_delete").addEventListener("click", () => void deleteCurrentBook().catch(displayError));
    node("reader_previous_block").addEventListener("click", () => void changePage(-1).catch(displayError));
    node("reader_next_block").addEventListener("click", () => void changePage(1).catch(displayError));
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
    node("reader_stealth").addEventListener("click", () => void toggleStealthMode().catch(displayError));
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
      updateNavigation();
      updateProgressVisual();
      void saveProgress(false);
    });
    node("reader_content").addEventListener("mouseup", () => pause(true));
    node("reader_panel").addEventListener("mouseleave", () => {
      if ((state.settings || {}).stealth_mode) setCollapsed(true);
      else pause(true);
    });
    node("reader_content").addEventListener("keydown", (event) => {
      if (event.key === " ") {
        event.preventDefault();
        playing ? pause(true) : play();
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        void changePage(-1).catch(displayError);
      } else if (event.key === "ArrowRight") {
        event.preventDefault();
        void changePage(1).catch(displayError);
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
      resumePlaybackAfterReveal = false;
      pause(true);
      node("reader_panel").hidden = true;
    },
    pauseAndSave() {
      resumePlaybackAfterReveal = false;
      pause(true);
    },
    initialize() { bind(); },
    _testing: {
      getState: () => ({ state, content, playing, collapsed, resumePlaybackAfterReveal }),
      tick,
      setState(value) { state = value; },
    },
  });
})(window);
