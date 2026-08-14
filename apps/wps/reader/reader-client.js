(function (global) {
  "use strict";

  const config = global.DocxToolWpsConfig || {};

  function requestId() {
    return `reader-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 9)}`;
  }

  async function call(path, options = {}) {
    if (!config.controlBaseUrl || !config.sessionToken || typeof global.fetch !== "function") {
      throw new Error("WPS_CONTROL_CONFIG_MISSING");
    }
    const headers = Object.assign({
      Authorization: `Bearer ${config.sessionToken}`,
      "X-DocxTool-Request-Id": requestId(),
    }, options.headers || {});
    const response = await global.fetch(`${config.controlBaseUrl}${path}`, Object.assign({}, options, { headers }));
    let payload;
    try {
      payload = await response.json();
    } catch (_error) {
      throw new Error("WPS_READER_RESPONSE_INVALID");
    }
    if (!response.ok || !payload || payload.ok !== true) {
      throw new Error(payload && payload.error_code ? payload.error_code : "WPS_READER_REQUEST_FAILED");
    }
    return payload.data;
  }

  global.DocxToolReaderClient = Object.freeze({
    loadState() { return call("/v1/reader/state"); },
    loadContent(bookId, chapterIndex, startOffset, limit) {
      const query = new URLSearchParams({
        book_id: String(bookId),
        chapter_index: String(chapterIndex),
        limit: String(limit || 12000),
      });
      if (Number.isInteger(startOffset)) query.set("start_offset", String(startOffset));
      return call(`/v1/reader/content?${query.toString()}`);
    },
    importBook(file) {
      return call("/v1/reader/import", {
        method: "POST",
        body: file,
        headers: {
          "Content-Type": "text/plain",
          "X-DocxTool-Reader-Filename": encodeURIComponent(file.name),
        },
      });
    },
    selectBook(bookId) { return call("/v1/reader/select", json({ book_id: bookId })); },
    deleteBook(bookId) { return call("/v1/reader/delete", json({ book_id: bookId })); },
    saveProgress(progress) { return call("/v1/reader/progress", json(progress)); },
    saveSettings(settings) { return call("/v1/reader/settings", json({ settings })); },
    navigate(bookId, chapterIndex, textOffset, direction) {
      return call("/v1/reader/navigate", json({
        book_id: bookId, chapter_index: chapterIndex, text_offset: textOffset, direction,
      }));
    },
  });

  function json(value) {
    return {
      method: "POST",
      body: JSON.stringify(value),
      headers: { "Content-Type": "application/json" },
    };
  }
})(window);
