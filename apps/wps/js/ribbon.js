"use strict";

function OnAddinLoad(ribbonUI) {
  var startedAt = Date.now();
  window.DocxToolEarlyLog("INFO", "ribbon", "ribbon.addin.load.enter", "WPS Ribbon 加载回调已进入", {
    ribbon_ui_available: Boolean(ribbonUI),
    application_available: Boolean(window.Application),
    host_runtime_present: Boolean(window.DocxToolHostRuntime)
  });
  var stage = "validate_application";
  try {
    if (!window.Application) throw new Error("WPS_APPLICATION_UNAVAILABLE");
    stage = "lookup_host_runtime";
    if (!window.DocxToolHostRuntime) throw new Error("LOCAL_APPLICATION_RUNTIME_NOT_READY");
    window.Application.ribbonUI = ribbonUI;
    stage = "host_start";
    window.DocxToolEarlyLog("INFO", "ribbon", "ribbon.addin.host_start.call", "开始调用 Host Runtime", {});
    window.DocxToolHostRuntime.start();
    window.DocxToolEarlyLog("INFO", "ribbon", "ribbon.addin.host_start.returned", "Host Runtime 调用已返回", {});
    window.DocxToolEarlyLog("INFO", "ribbon", "ribbon.addin.load.completed", "WPS Ribbon 加载完成", {
      duration_ms: Date.now() - startedAt
    });
    return true;
  } catch (error) {
    window.DocxToolEarlyLog("ERROR", "ribbon", "ribbon.addin.load.failed", "WPS Ribbon 加载失败", {
      stage: stage,
      error_type: error && error.name ? error.name : "Error",
      error_code: error && error.message ? error.message : "WPS_RIBBON_LOAD_FAILED"
    });
    throw error;
  }
}

function OnAction(control) {
  var id = control && (control.Id || control.id) ? String(control.Id || control.id) : "";
  window.DocxToolHostRuntime.handleRibbonAction(id);
}

function GetActionEnabled(control) {
  var id = control && (control.Id || control.id) ? String(control.Id || control.id) : "";
  return window.DocxToolHostRuntime.getActionEnabled(id);
}

window.OnAddinLoad = OnAddinLoad;
window.OnAction = OnAction;
window.GetActionEnabled = GetActionEnabled;
window.DocxToolEarlyLog("INFO", "ribbon", "ribbon.script.loaded", "Ribbon 回调脚本已加载", {});
