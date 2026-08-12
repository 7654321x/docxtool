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
      return new Promise(function (resolve, reject) {
        var script = document.createElement("script");
        script.src = source;
        script.onload = function () { scriptLoaded(label); resolve(); };
        script.onerror = function () { scriptFailed(label); reject(new Error("WPS_BOOTSTRAP_SCRIPT_LOAD_FAILED")); };
        document.head.appendChild(script);
      });
    } catch (error) {
      scriptFailed(label);
      throw error;
    }
  }

  window.DocxToolBootstrapId = bootstrapId;
  window.DocxToolBootstrapScriptLoaded = scriptLoaded;
  console.log("[WPS][bootstrap] bootstrap.main.loaded | WPS 主启动脚本已加载", {
    bootstrap_id: bootstrapId,
    application_available: Boolean(window.Application),
    document_ready_state: document.readyState
  });
  (async function () {
    bootstrapLog("INFO", "bootstrap.runtime_config.load.start", "开始读取同源 WPS 运行配置", {});
    var response = await fetch("runtime/config", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error("WPS_RUNTIME_CONFIG_LOAD_FAILED");
    window.DocxToolWpsConfig = Object.freeze(await response.json());
    bootstrapLog("INFO", "bootstrap.runtime_config.loaded", "同源 WPS 运行配置已读取", {});
    await loadScript("js/bootstrap-log.js", "bootstrap_log");
    bootstrapLog("INFO", "bootstrap.main.loaded", "WPS 主启动脚本已加载", {
      bootstrap_id: bootstrapId,
      application_available: Boolean(window.Application),
      document_ready_state: document.readyState
    });
    await loadScript("host-runtime.js", "host_runtime");
    await loadScript("js/ribbon.js", "ribbon");
    await loadScript("js/bootstrap-complete.js", "complete");
  })().catch(function (error) {
    bootstrapLog("ERROR", "bootstrap.main.failed", "WPS 启动失败", { error_code: error.message || "WPS_BOOTSTRAP_FAILED" });
  });
})();
