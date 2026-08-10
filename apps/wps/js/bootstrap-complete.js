(function () {
  "use strict";
  if (!window.DocxToolEarlyLog) throw new Error("WPS_BOOTSTRAP_LOG_UNAVAILABLE");
  if (typeof window.DocxToolFlushEarlyLogs !== "function") throw new Error("WPS_BOOTSTRAP_LOG_FLUSH_UNAVAILABLE");
  var bootstrapId = window.DocxToolBootstrapId || "";
  var runtime = window.DocxToolHostRuntime;
  var hostInstanceIdShort = runtime && typeof runtime.getInstanceIdShort === "function"
    ? runtime.getInstanceIdShort()
    : "";
  var startupError = null;

  window.DocxToolEarlyLog("INFO", "bootstrap", "bootstrap.completed", "WPS 启动脚本加载完成", {
    bootstrap_id: bootstrapId
  });
  if (!runtime || typeof runtime.start !== "function") {
    startupError = new Error("WPS_HOST_RUNTIME_UNAVAILABLE");
    window.DocxToolEarlyLog("ERROR", "bootstrap", "bootstrap.host_start.failed", "Bootstrap 无法启动 Host Runtime", {
      bootstrap_id: bootstrapId,
      host_instance_id_short: hostInstanceIdShort,
      host_runtime_present: Boolean(runtime),
      stage: "runtime_lookup",
      error_code: "WPS_HOST_RUNTIME_UNAVAILABLE",
      error_type: "Error"
    });
  } else {
    window.DocxToolEarlyLog("INFO", "bootstrap", "bootstrap.host_start.enter", "Bootstrap 开始启动 Host Runtime", {
      bootstrap_id: bootstrapId,
      host_instance_id_short: hostInstanceIdShort,
      host_runtime_present: true,
      stage: "host_start"
    });
    try {
      var state = runtime.start();
      window.DocxToolEarlyLog("INFO", "bootstrap", "bootstrap.host_start.completed", "Bootstrap 已启动 Host Runtime", {
        bootstrap_id: bootstrapId,
        host_instance_id_short: hostInstanceIdShort,
        host_ready: true,
        stage: "host_start",
        state: state
      });
    } catch (error) {
      startupError = error;
      var candidate = error && error.message ? String(error.message) : "";
      var errorCode = /^[A-Z][A-Z0-9_]{2,100}$/.test(candidate) ? candidate : "WPS_HOST_START_FAILED";
      window.DocxToolEarlyLog("ERROR", "bootstrap", "bootstrap.host_start.failed", "Bootstrap 启动 Host Runtime 失败", {
        bootstrap_id: bootstrapId,
        host_instance_id_short: hostInstanceIdShort,
        host_runtime_present: true,
        stage: "host_start",
        error_code: errorCode,
        error_type: error && error.name ? error.name : "Error"
      });
    }
  }

  void window.DocxToolFlushEarlyLogs().then(function (flushedCount) {
    console.log("[WPS][bootstrap] bootstrap.early_log.flush.completed | 早期启动日志汇入完成", {
      flushed_count: flushedCount
    });
  }).catch(function (error) {
    console.error("[WPS][bootstrap] bootstrap.early_log.flush.failed | 早期启动日志汇入失败", {
      error_code: error && error.message ? error.message : "WPS_BOOTSTRAP_LOG_FLUSH_FAILED"
    });
  });
  if (startupError) throw startupError;
})();
