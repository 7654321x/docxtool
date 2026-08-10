(function () {
  "use strict";

  var queue = [];
  var limit = 150;
  var eventSequence = 0;
  var allowedFields = new Set([
    "application_available", "bootstrap_id", "config_present", "control_host", "duration_ms", "error_code", "error_type",
    "control_port", "control_url_present", "document_ready_state", "flushed_count", "queued_count",
    "host_instance_id_short", "host_ready", "host_runtime_present", "plugin_storage_available", "ribbon_ui_available",
    "stage", "state", "token_present", "callbacks_registered", "event_sequence"
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
    var safe = safeDetails(details);
    safe.event_sequence = ++eventSequence;
    var entry = {
      level: String(level || "INFO").toUpperCase(),
      component: String(component || "bootstrap"),
      event: String(event || "runtime.event"),
      message: String(message || ""),
      details: safe
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
  window.DocxToolFlushEarlyLogs = async function () {
    var config = window.DocxToolWpsConfig || {};
    if (!config.controlBaseUrl || !config.sessionToken || typeof fetch !== "function") {
      throw new Error("WPS_BOOTSTRAP_LOG_TRANSPORT_UNAVAILABLE");
    }
    var entries = queue.splice(0, queue.length);
    for (var entry of entries) {
      var response = await fetch(config.controlBaseUrl + "/v1/log", {
        method: "POST",
        headers: { "Content-Type": "application/json", "Authorization": "Bearer " + config.sessionToken },
        body: JSON.stringify(entry)
      });
      if (!response.ok) throw new Error("WPS_BOOTSTRAP_LOG_FLUSH_FAILED");
    }
    return entries.length;
  };
  earlyLog("INFO", "bootstrap", "bootstrap_log.script.loaded", "早期日志脚本已加载", {
    bootstrap_id: window.DocxToolBootstrapId || ""
  });
})();
