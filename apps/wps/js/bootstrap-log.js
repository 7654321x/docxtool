(function () {
  "use strict";

  var queue = [];
  var limit = 150;
  var allowedFields = new Set([
    "application_available", "bootstrap_id", "config_present", "control_host", "duration_ms", "error_code", "error_type",
    "control_port", "control_url_present", "document_ready_state", "flushed_count", "queued_count",
    "host_runtime_present", "plugin_storage_available", "ribbon_ui_available", "stage", "token_present"
  ]);

  function safeDetails(details) {
    var result = {};
    if (!details || typeof details !== "object") return result;
    Object.keys(details).forEach(function (key) {
      var value = details[key];
      if (allowedFields.has(key) && (["string", "number", "boolean"].includes(typeof value) || value == null)) {
        result[key] = value;
      }
    });
    return result;
  }

  function earlyLog(level, component, event, message, details) {
    var entry = {
      level: String(level || "INFO").toUpperCase(),
      component: String(component || "bootstrap"),
      event: String(event || "runtime.event"),
      message: String(message || ""),
      details: safeDetails(details)
    };
    queue.push(entry);
    if (queue.length > limit) queue.shift();
    var line = "[WPS][" + entry.component + "] " + entry.event + " | " + entry.message;
    if (entry.level === "ERROR") console.error(line, entry.details);
    else if (entry.level === "WARNING" || entry.level === "WARN") console.warn(line, entry.details);
    else console.log(line, entry.details);
  }

  window.DocxToolEarlyLogQueue = queue;
  window.DocxToolEarlyLog = earlyLog;
  earlyLog("INFO", "bootstrap", "bootstrap_log.script.loaded", "早期日志脚本已加载", {
    bootstrap_id: window.DocxToolBootstrapId || ""
  });
})();
