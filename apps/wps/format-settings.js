(function () {
  "use strict";

  const format = window.DocxToolFormatConfig;
  const SYSTEM_PROFILE_ID = "system:default";
  const NEW_PROFILE_ID = "new:draft";
  let runtimeConfig = null;
  let profiles = [];
  let selectedProfile = null;
  let selectedProfileId = "";
  let newProfileSourceId = "";
  let draftConfig = null;
  let defaultConfig = null;
  let initialized = false;
  let isNewProfile = false;
  let dirty = false;
  let rendering = false;
  let closing = false;
  let logSequence = 0;
  const SAFE_DETAIL_FIELDS = new Set([
    "config_version", "style_count", "duration_ms", "revision", "error_code",
    "error_type", "profile_count", "profile_id_short", "is_system"
  ]);

  function node(id) {
    const value = document.getElementById(id);
    if (!value) throw new Error("WPS_FORMAT_DIALOG_ELEMENT_MISSING");
    return value;
  }

  function stableErrorCode(error, fallback) {
    const message = error && typeof error.message === "string" ? error.message : "";
    return /^WPS_[A-Z0-9_]+$/.test(message) ? message : fallback;
  }

  function profileErrorMessage(code) {
    return {
      WPS_FORMAT_PROFILE_ACCOUNT_REQUIRED: "当前账号不可用，请重新登录。",
      WPS_FORMAT_PROFILE_NAME_REQUIRED: "请输入模板名称。",
      WPS_FORMAT_PROFILE_NAME_TOO_LONG: "模板名称不能超过 80 个字符。",
      WPS_FORMAT_PROFILE_NAME_CONFLICT: "当前账号已存在同名模板。",
      WPS_FORMAT_PROFILE_NOT_FOUND: "模板不存在或不属于当前账号。",
      WPS_FORMAT_PROFILE_SYSTEM_LOCKED: "系统默认模板不能直接修改，请先添加模板。",
      WPS_FORMAT_PROFILE_CONFIG_INVALID: "模板内容无效，未保存任何修改。",
      WPS_FORMAT_PROFILE_DATABASE_FAILED: "本地模板数据库操作失败。",
      WPS_FORMAT_PROFILE_MIGRATION_FAILED: "旧格式设置迁移失败。"
    }[code] || "格式模板操作失败。";
  }

  function log(level, event, message, details) {
    const safeDetails = {};
    Object.keys(details || {}).forEach((key) => {
      const value = details[key];
      if (SAFE_DETAIL_FIELDS.has(key) && (["string", "number", "boolean"].includes(typeof value) || value == null)) safeDetails[key] = value;
    });
    safeDetails.event_sequence = ++logSequence;
    const line = `[WPS][format-settings] ${event} | ${message}`;
    if (level === "ERROR") console.error(line, safeDetails);
    else if (level === "WARNING" || level === "WARN") console.warn(line, safeDetails);
    else console.log(line, safeDetails);
    if (!runtimeConfig || !runtimeConfig.controlBaseUrl || !runtimeConfig.sessionToken || typeof fetch !== "function") return;
    void fetch(`${runtimeConfig.controlBaseUrl}/v1/log`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "Authorization": `Bearer ${runtimeConfig.sessionToken}` },
      body: JSON.stringify({ level, component: "format_settings", event, message, details: safeDetails }),
      keepalive: true
    }).catch(() => {});
  }

  async function controlApi(path, body, method) {
    if (!runtimeConfig || !runtimeConfig.controlBaseUrl || !runtimeConfig.sessionToken) {
      throw new Error("WPS_RUNTIME_CONFIG_MISSING");
    }
    const requestMethod = method || "POST";
    const response = await fetch(`${runtimeConfig.controlBaseUrl}${path}`, {
      method: requestMethod,
      headers: {
        "Content-Type": "application/json",
        "Authorization": `Bearer ${runtimeConfig.sessionToken}`
      },
      body: requestMethod === "GET" ? undefined : JSON.stringify(body || {})
    });
    let payload;
    try { payload = await response.json(); }
    catch (error) { throw new Error("WPS_BRIDGE_RESPONSE_INVALID"); }
    if (!response.ok || !payload.ok) throw new Error(payload.error_code || "WPS_BRIDGE_REQUEST_FAILED");
    return payload.data;
  }

  function setOptions(select, values, value, emptyLabel) {
    const items = emptyLabel
      ? [{ value: "", label: emptyLabel }, ...values.map((item) => ({ value: item, label: item }))]
      : values.map((item) => ({ value: item, label: item }));
    select.replaceChildren(...items.map((item) => {
      const option = document.createElement("option");
      option.value = String(item.value);
      option.textContent = String(item.label);
      return option;
    }));
    select.value = value === undefined || value === null ? "" : String(value);
  }

  function makeCell() {
    return document.createElement("td");
  }

  function makeSelect(values, value, field, ariaLabel, emptyLabel) {
    const select = document.createElement("select");
    select.dataset.field = field;
    select.setAttribute("aria-label", ariaLabel);
    setOptions(select, values, value, emptyLabel);
    return select;
  }

  function renderStyleRows(configValue) {
    const rows = format.STYLE_NAMES.map((name, index) => {
      const style = format.styleByName(configValue, name, index);
      const row = document.createElement("tr");
      row.dataset.index = String(index);

      const nameCell = makeCell();
      nameCell.className = "style-name";
      nameCell.textContent = name;
      row.appendChild(nameCell);

      const fontCell = makeCell();
      fontCell.appendChild(makeSelect(format.FONTS, style.font || "", "font", `${name}字体`));
      row.appendChild(fontCell);

      const sizeCell = makeCell();
      sizeCell.appendChild(makeSelect(format.SIZES, style.size || "", "size", `${name}字号`));
      row.appendChild(sizeCell);

      const boldCell = makeCell();
      const boldLabel = document.createElement("label");
      boldLabel.className = "bold-toggle";
      const bold = document.createElement("input");
      bold.type = "checkbox";
      bold.dataset.field = "bold";
      bold.checked = style.bold === true;
      bold.setAttribute("aria-label", `${name}加粗`);
      boldLabel.appendChild(bold);
      boldCell.appendChild(boldLabel);
      row.appendChild(boldCell);

      const patternCell = makeCell();
      const pattern = makeSelect(format.PATTERNS, style.pattern || "", "pattern", `${name}编号样式`, "无样式");
      patternCell.appendChild(pattern);
      row.appendChild(patternCell);

      const numberTypeCell = makeCell();
      const numberType = document.createElement("input");
      numberType.type = "text";
      numberType.readOnly = true;
      numberType.dataset.field = "number_type";
      numberType.value = format.formatNumberType(style.pattern);
      numberType.setAttribute("aria-label", `${name}编号类型`);
      numberTypeCell.appendChild(numberType);
      row.appendChild(numberTypeCell);
      pattern.addEventListener("change", () => { numberType.value = format.formatNumberType(pattern.value); });

      const indentCell = makeCell();
      indentCell.appendChild(makeSelect(format.INDENTS.map(String), String(format.numberOr(style.indent, 0)), "indent", `${name}首行缩进`));
      row.appendChild(indentCell);

      const alignCell = makeCell();
      alignCell.appendChild(makeSelect(format.ALIGNMENTS, style.align || "左对齐", "align", `${name}对齐方式`));
      row.appendChild(alignCell);
      return row;
    });
    node("format_style_rows").replaceChildren(...rows);
  }

  function render(configValue) {
    format.validateFormatConfig(configValue);
    const page = configValue.page;
    const margins = ["2.0cm", "2.2cm", "2.4cm", "2.6cm", "2.8cm", "3.0cm", "3.2cm", "3.5cm", "3.7cm", "4.0cm"];
    setOptions(node("format_paper_size"), ["A4", "A3", "Letter"], page.width_cm === 29.7 ? "A3" : page.width_cm === 21.59 ? "Letter" : "A4");
    setOptions(node("format_margin_top"), margins, `${format.numberOr(page.margin_top_cm, 3.7)}cm`);
    setOptions(node("format_margin_bottom"), margins, `${format.numberOr(page.margin_bottom_cm, 3.5)}cm`);
    setOptions(node("format_margin_left"), margins, `${format.numberOr(page.margin_left_cm, 2.8)}cm`);
    setOptions(node("format_margin_right"), margins, `${format.numberOr(page.margin_right_cm, 2.6)}cm`);
    setOptions(node("format_line_spacing"), Array.from({ length: 21 }, (_, index) => `${20 + index}磅`), `${format.numberOr(page.line_spacing_pt, 28)}磅`);
    const numberStyle = format.styleByName(configValue, "数字", 6);
    const letterStyle = format.styleByName(configValue, "字母", 7);
    const pageStyle = format.styleByName(configValue, "页码设置", 8);
    setOptions(node("format_number_font"), format.FONTS, numberStyle.font || "Times New Roman");
    setOptions(node("format_number_size"), format.SIZES, numberStyle.size || "", "跟随段落");
    setOptions(node("format_letter_font"), format.FONTS, letterStyle.font || "Times New Roman");
    setOptions(node("format_letter_size"), format.SIZES, letterStyle.size || "", "跟随段落");
    setOptions(node("format_page_font"), format.FONTS, pageStyle.font || "宋体");
    setOptions(node("format_page_size"), format.SIZES, pageStyle.size || "四号");
    node("format_page_style").value = ({ "— 1 —": "dash", "1": "plain", "第 1 页": "cn", "第 1 页 / 共 n 页": "cn_total" }[pageStyle.pattern] || "dash");
    node("format_page_position").value = ({ "奇右|偶左": "outside", "奇右偶左": "outside", "居中": "center", "左对齐": "left", "右对齐": "right" }[pageStyle.align] || "outside");
    renderStyleRows(configValue);
  }

  function collect() {
    const next = format.copyJson(draftConfig);
    format.validateFormatConfig(next);
    const pageDimensions = { A4: [21, 29.7], A3: [29.7, 42], Letter: [21.59, 27.94] }[node("format_paper_size").value] || [21, 29.7];
    next.page.width_cm = pageDimensions[0];
    next.page.height_cm = pageDimensions[1];
    next.page.margin_top_cm = format.numberOr(node("format_margin_top").value.replace("cm", ""), 3.7);
    next.page.margin_bottom_cm = format.numberOr(node("format_margin_bottom").value.replace("cm", ""), 3.5);
    next.page.margin_left_cm = format.numberOr(node("format_margin_left").value.replace("cm", ""), 2.8);
    next.page.margin_right_cm = format.numberOr(node("format_margin_right").value.replace("cm", ""), 2.6);
    next.page.line_spacing_pt = format.numberOr(node("format_line_spacing").value.replace("磅", ""), 28);

    format.STYLE_NAMES.forEach((name, index) => {
      const row = node("format_style_rows").querySelector(`[data-index="${index}"]`);
      const updated = { ...format.styleByName(next, name, index), name };
      ["font", "size", "pattern", "align"].forEach((field) => { updated[field] = row.querySelector(`[data-field="${field}"]`).value; });
      updated.bold = row.querySelector('[data-field="bold"]').checked;
      updated.indent = format.numberOr(row.querySelector('[data-field="indent"]').value, 0);
      next.styles[index] = updated;
    });

    const updateNamed = (name, index, updates) => {
      next.styles[index] = { ...format.styleByName(next, name, index), name, ...updates };
    };
    const numberSize = node("format_number_size").value;
    const letterSize = node("format_letter_size").value;
    updateNamed("数字", 6, { font: node("format_number_font").value, ...(numberSize ? { size: numberSize } : {}) });
    updateNamed("字母", 7, { font: node("format_letter_font").value, ...(letterSize ? { size: letterSize } : {}) });
    if (!numberSize) delete next.styles[6].size;
    if (!letterSize) delete next.styles[7].size;
    const pageStyleValue = { dash: "— 1 —", plain: "1", cn: "第 1 页", cn_total: "第 1 页 / 共 n 页" }[node("format_page_style").value] || "— 1 —";
    updateNamed("页码设置", 8, {
      font: node("format_page_font").value,
      size: node("format_page_size").value,
      pattern: pageStyleValue,
      align: ({ outside: "奇右|偶左", center: "居中", left: "左对齐", right: "右对齐" }[node("format_page_position").value] || "奇右|偶左")
    });
    if (!next.page_number || typeof next.page_number !== "object") next.page_number = {};
    next.page_number.font_name = node("format_page_font").value;
    next.page_number.font_size_pt = format.SIZE_POINTS[node("format_page_size").value];
    next.page_number.style = node("format_page_style").value;
    next.page_number.position = node("format_page_position").value;
    return format.validateFormatConfig(next);
  }

  function renderProfileOptions() {
    const options = profiles.map((profile) => {
      const option = document.createElement("option");
      option.value = profile.profile_id;
      option.textContent = profile.is_system ? `${profile.name}（系统）` : profile.name;
      return option;
    });
    if (isNewProfile) {
      const option = document.createElement("option");
      option.value = NEW_PROFILE_ID;
      option.textContent = "新模板（未保存）";
      options.push(option);
    }
    node("format_profile_select").replaceChildren(...options);
    node("format_profile_select").value = isNewProfile ? NEW_PROFILE_ID : selectedProfileId;
  }

  function loadProfile(profile) {
    if (!profile || typeof profile !== "object" || !profile.profile_id) {
      throw new Error("WPS_FORMAT_PROFILE_RESPONSE_INVALID");
    }
    selectedProfile = profile;
    selectedProfileId = String(profile.profile_id);
    isNewProfile = false;
    draftConfig = format.copyJson(format.validateFormatConfig(profile.format_config));
    if (profile.is_system) defaultConfig = format.copyJson(draftConfig);
    rendering = true;
    try {
      renderProfileOptions();
      node("format_profile_name").value = String(profile.name || "");
      node("format_profile_name").readOnly = profile.is_system === true;
      node("format_profile_delete").disabled = profile.is_system === true;
      render(draftConfig);
    } finally {
      rendering = false;
    }
    dirty = false;
    node("format_dialog_error").textContent = "";
  }

  function applyProfileResponse(response) {
    if (!response || !Array.isArray(response.profiles) || !response.active_profile) {
      throw new Error("WPS_FORMAT_PROFILE_RESPONSE_INVALID");
    }
    profiles = response.profiles.slice();
    const system = profiles.find((profile) => profile.profile_id === SYSTEM_PROFILE_ID);
    if (!system || !system.format_config) throw new Error("WPS_FORMAT_DEFAULT_CONFIG_INVALID");
    defaultConfig = format.copyJson(format.validateFormatConfig(system.format_config));
    loadProfile(response.active_profile);
  }

  async function fetchProfile(profileId) {
    const result = await controlApi(
      `/v1/format/profiles/detail?profile_id=${encodeURIComponent(profileId)}`,
      null,
      "GET"
    );
    if (!result || !result.profile) throw new Error("WPS_FORMAT_PROFILE_RESPONSE_INVALID");
    return result.profile;
  }

  async function switchProfile() {
    const requestedId = node("format_profile_select").value;
    const currentSelectValue = isNewProfile ? NEW_PROFILE_ID : selectedProfileId;
    if (requestedId === currentSelectValue) return;
    if (dirty && !window.confirm("当前模板有未保存修改，是否放弃修改并切换模板？")) {
      node("format_profile_select").value = currentSelectValue;
      return;
    }
    loadProfile(await fetchProfile(requestedId));
    log("INFO", "wps.format_profile.selected", "WPS 格式模板已在设置窗口中选择", {
      profile_id_short: requestedId.slice(0, 16),
      is_system: requestedId === SYSTEM_PROFILE_ID,
      profile_count: profiles.length
    });
  }

  function addProfile() {
    if (!initialized) throw new Error("WPS_FORMAT_DIALOG_NOT_READY");
    draftConfig = format.copyJson(collect());
    newProfileSourceId = selectedProfileId;
    selectedProfile = null;
    selectedProfileId = "";
    isNewProfile = true;
    rendering = true;
    try {
      renderProfileOptions();
      node("format_profile_name").value = "";
      node("format_profile_name").readOnly = false;
      node("format_profile_delete").disabled = false;
    } finally {
      rendering = false;
    }
    dirty = true;
    node("format_dialog_error").textContent = "";
    node("format_profile_name").focus();
    log("INFO", "wps.format_profile.create.draft", "WPS 新格式模板草稿已创建", {
      profile_count: profiles.length,
      style_count: format.STYLE_NAMES.length
    });
  }

  async function deleteProfile() {
    if (!initialized) throw new Error("WPS_FORMAT_DIALOG_NOT_READY");
    if (isNewProfile) {
      loadProfile(await fetchProfile(newProfileSourceId || SYSTEM_PROFILE_ID));
      return;
    }
    if (!selectedProfile || selectedProfile.is_system) {
      throw new Error("WPS_FORMAT_PROFILE_SYSTEM_LOCKED");
    }
    if (!window.confirm("确定删除当前格式模板吗？此操作不会删除文档。")) return;
    const deletedId = selectedProfileId;
    const response = await controlApi("/v1/format/profiles/delete", { profile_id: deletedId });
    applyProfileResponse(response);
    log("INFO", "wps.format_profile.deleted", "WPS 本地格式模板已删除", {
      profile_id_short: deletedId.slice(0, 16),
      profile_count: profiles.length
    });
  }

  function closeWindow() {
    closing = true;
    window.close();
  }

  function cancelSettings() {
    if (closing) return;
    log("INFO", "wps.format_settings.dialog.cancelled", "WPS 格式设置窗口已取消", {
      profile_id_short: (selectedProfileId || NEW_PROFILE_ID).slice(0, 16),
      profile_count: profiles.length,
      style_count: format.STYLE_NAMES.length
    });
    closeWindow();
  }

  function restoreDefaults() {
    if (!initialized) throw new Error("WPS_FORMAT_DIALOG_NOT_READY");
    draftConfig = format.copyJson(defaultConfig);
    rendering = true;
    try { render(draftConfig); }
    finally { rendering = false; }
    dirty = true;
  }

  async function saveSettings() {
    if (!initialized) throw new Error("WPS_FORMAT_DIALOG_NOT_READY");
    const next = collect();
    let response;
    if (isNewProfile) {
      response = await controlApi("/v1/format/profiles/create", {
        name: node("format_profile_name").value,
        format_config: next
      });
    } else if (selectedProfile && selectedProfile.is_system) {
      if (dirty) throw new Error("WPS_FORMAT_PROFILE_SYSTEM_LOCKED");
      response = await controlApi("/v1/format/profiles/select", {
        profile_id: SYSTEM_PROFILE_ID
      });
    } else if (dirty) {
      response = await controlApi("/v1/format/profiles/update", {
        profile_id: selectedProfileId,
        name: node("format_profile_name").value,
        format_config: next
      });
    } else {
      response = await controlApi("/v1/format/profiles/select", {
        profile_id: selectedProfileId
      });
    }
    applyProfileResponse(response);
    log("INFO", "wps.format_settings.dialog.saved", "WPS 格式模板已保存并设为当前模板", {
      config_version: String(selectedProfile.config_version || ""),
      style_count: format.STYLE_NAMES.length,
      revision: Number(selectedProfile.revision || 0),
      profile_id_short: selectedProfileId.slice(0, 16),
      profile_count: profiles.length
    });
    closeWindow();
  }

  function showOperationFailure(error, fallback) {
    const code = stableErrorCode(error, fallback);
    node("format_dialog_error").textContent = `${profileErrorMessage(code)} 错误代码：${code}`;
    log("ERROR", "wps.format_profile.operation.failed", "WPS 格式模板操作失败", {
      error_code: code,
      error_type: error && error.name ? error.name : "Error",
      profile_id_short: (selectedProfileId || NEW_PROFILE_ID).slice(0, 16)
    });
  }

  function showFailure(error) {
    const code = stableErrorCode(error, "WPS_FORMAT_DIALOG_INITIALIZE_FAILED");
    node("format_dialog_error").textContent = `格式设置初始化失败。错误代码：${code}`;
    ["format_settings_restore", "format_settings_save", "format_profile_add", "format_profile_delete", "format_profile_select"].forEach((id) => {
      node(id).disabled = true;
    });
    log("ERROR", "wps.format_settings.dialog.open.failed", "WPS 格式设置窗口初始化失败", {
      error_code: code,
      error_type: error && error.name ? error.name : "Error"
    });
  }

  async function initialize() {
    const startedAt = Date.now();
    if (!format) throw new Error("WPS_FORMAT_CONFIG_MODULE_UNAVAILABLE");
    const response = await fetch("./runtime/config", { cache: "no-store", credentials: "same-origin" });
    if (!response.ok) throw new Error("WPS_RUNTIME_CONFIG_LOAD_FAILED");
    runtimeConfig = Object.freeze(await response.json());
    applyProfileResponse(await controlApi("/v1/format/profiles", null, "GET"));
    initialized = true;
    log("INFO", "wps.format_settings.dialog.opened", "WPS 格式设置窗口已初始化", {
      config_version: String(selectedProfile.config_version || ""),
      style_count: format.STYLE_NAMES.length,
      revision: Number(selectedProfile.revision || 0),
      profile_count: profiles.length,
      profile_id_short: selectedProfileId.slice(0, 16),
      duration_ms: Date.now() - startedAt
    });
  }

  node("dialog_close").addEventListener("click", cancelSettings);
  node("format_settings_cancel").addEventListener("click", cancelSettings);
  node("format_settings_restore").addEventListener("click", () => {
    try { restoreDefaults(); } catch (error) { showOperationFailure(error, "WPS_FORMAT_SETTINGS_RESTORE_FAILED"); }
  });
  node("format_profile_add").addEventListener("click", () => {
    try { addProfile(); } catch (error) { showOperationFailure(error, "WPS_FORMAT_PROFILE_CREATE_FAILED"); }
  });
  node("format_profile_delete").addEventListener("click", () => {
    void deleteProfile().catch((error) => showOperationFailure(error, "WPS_FORMAT_PROFILE_DELETE_FAILED"));
  });
  node("format_profile_select").addEventListener("change", () => {
    void switchProfile().catch((error) => showOperationFailure(error, "WPS_FORMAT_PROFILE_SELECT_FAILED"));
  });
  node("format_profile_name").addEventListener("input", () => {
    if (!rendering) dirty = true;
  });
  node("format_style_rows").closest(".dialog-content").addEventListener("change", (event) => {
    if (!rendering && event.target !== node("format_profile_select")) dirty = true;
  });
  node("format_settings_save").addEventListener("click", () => {
    void saveSettings().catch((error) => showOperationFailure(error, "WPS_FORMAT_SETTINGS_SAVE_FAILED"));
  });

  window.DocxToolFormatSettingsDialog = Object.freeze({
    initialize,
    restoreDefaults,
    saveSettings,
    cancelSettings,
    addProfile,
    deleteProfile,
    switchProfile,
    collect
  });
  void initialize().catch(showFailure);
})();
