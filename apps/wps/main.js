"use strict";

function ribbonCallbacks() {
  if (!window.DocxToolRibbonCallbacks) throw new Error("WPS_RIBBON_CALLBACKS_NOT_READY");
  return window.DocxToolRibbonCallbacks;
}

function OnAddinLoad(ribbonUI) {
  return ribbonCallbacks().onAddinLoad(ribbonUI);
}

function OnAction(control) {
  return ribbonCallbacks().onAction(control);
}

function GetActionEnabled(control) {
  return ribbonCallbacks().getActionEnabled(control);
}

function GetImage(control) {
  return ribbonCallbacks().getImage(control);
}

window.OnAddinLoad = OnAddinLoad;
window.OnAction = OnAction;
window.GetActionEnabled = GetActionEnabled;
window.GetImage = GetImage;

(function () {
  "use strict";

  var bootstrapId = "bootstrap-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 9);

  function bootstrapLog(level, event, message, details) {
    if (typeof window.DocxToolEarlyLog === "function") {
      window.DocxToolEarlyLog(level, "bootstrap", event, message, details || {});
      return;
    }
    var line = "[WPS][bootstrap] " + event + " | " + message;
    if (level === "ERROR") console.error(line, details || {});
    else console.log(line, details || {});
  }

  function scriptLoaded(label) {
    bootstrapLog("INFO", "bootstrap." + label + ".loaded", "WPS 启动子脚本已加载", {});
  }

  function scriptFailed(label) {
    bootstrapLog("ERROR", "bootstrap." + label + ".failed", "WPS 启动子脚本加载失败", {});
  }

  function loadScript(source, label) {
    bootstrapLog("INFO", "bootstrap." + label + ".load.start", "开始加载 WPS 启动子脚本", {});
    try {
      document.write("<script language='javascript' src='" + source + "'><\/script>");
    } catch (error) {
      scriptFailed(label);
      throw error;
    }
    scriptLoaded(label);
  }

  window.DocxToolBootstrapId = bootstrapId;
  window.DocxToolBootstrapScriptLoaded = scriptLoaded;
  console.log("[WPS][bootstrap] bootstrap.main.loaded | WPS 主启动脚本已加载", {
    bootstrap_id: bootstrapId,
    application_available: Boolean(window.Application),
    document_ready_state: document.readyState
  });
  loadScript("js/bootstrap-log.js", "bootstrap_log");
  bootstrapLog("INFO", "bootstrap.main.loaded", "WPS 主启动脚本已加载", {
    bootstrap_id: bootstrapId,
    application_available: Boolean(window.Application),
    document_ready_state: document.readyState
  });
  loadScript("runtime/runtime-config.js", "runtime_config");
  loadScript("host-runtime.js", "host_runtime");
  loadScript("js/ribbon.js", "ribbon");
  loadScript("js/bootstrap-complete.js", "complete");
})();
