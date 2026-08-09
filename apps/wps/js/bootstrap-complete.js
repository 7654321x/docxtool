(function () {
  "use strict";
  if (!window.DocxToolEarlyLog) throw new Error("WPS_BOOTSTRAP_LOG_UNAVAILABLE");
  window.DocxToolEarlyLog("INFO", "bootstrap", "bootstrap.completed", "WPS 启动脚本加载完成", {
    bootstrap_id: window.DocxToolBootstrapId || ""
  });
})();
