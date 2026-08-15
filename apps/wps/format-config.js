(function () {
  "use strict";

  const SCHEMA_VERSION = 1;
  const CURRENT_KEY = "docxtool_wps_format_config_current_v1";
  const DRAFT_KEY = "docxtool_wps_format_config_draft_v1";
  const REVISION_KEY = "docxtool_wps_format_config_revision_v1";
  const STYLE_NAMES = ["主标题", "一级标题", "二级标题", "三级标题", "四级标题", "正文"];
  const FONTS = [
    "方正小标宋简体", "方正大标宋简体", "黑体", "楷体_GB2312", "仿宋_GB2312", "仿宋",
    "宋体", "新宋体", "华文中宋", "微软雅黑", "等线", "思源宋体", "思源黑体",
    "Times New Roman", "Arial", "Calibri", "Cambria"
  ];
  const SIZES = ["初号", "小初", "一号", "小一", "二号", "小二", "三号", "小三", "四号", "小四", "五号", "小五", "六号", "小六"];
  const SIZE_POINTS = { "初号": 42, "小初": 36, "一号": 26, "小一": 24, "二号": 22, "小二": 18, "三号": 16, "小三": 15, "四号": 14, "小四": 12, "五号": 10.5, "小五": 9, "六号": 7.5, "小六": 6.5 };
  const PATTERNS = ["{a}、", "（{b}）", "{c}.", "（{d}）"];
  const INDENTS = [0, 1, 1.5, 2, 2.5, 3];
  const ALIGNMENTS = ["居中", "左对齐", "右对齐", "两端对齐"];

  function copyJson(value) {
    return value && typeof value === "object" ? JSON.parse(JSON.stringify(value)) : {};
  }

  function validateFormatConfig(value) {
    if (!value || typeof value !== "object" || !Array.isArray(value.styles) || value.styles.length < STYLE_NAMES.length || !value.page || typeof value.page !== "object") {
      throw new Error("WPS_FORMAT_CONFIG_INVALID");
    }
    return value;
  }

  function styleByName(configValue, name, index) {
    const styles = Array.isArray(configValue && configValue.styles) ? configValue.styles : [];
    return styles.find((item) => item && item.name === name) || styles[index] || {};
  }

  function numberOr(value, fallback) {
    const numeric = Number(value);
    return Number.isFinite(numeric) ? numeric : fallback;
  }

  function formatNumberType(pattern) {
    const value = String(pattern || "");
    if (!value) return "无样式";
    if (value.includes("{a}") || value.includes("{b}")) return "中文数字";
    if (value.includes("{c}") || value.includes("{d}")) return "阿拉伯数字";
    return "自定义符号";
  }

  function parseStoredJson(raw, missingAllowed) {
    if (raw === null || raw === undefined || raw === "") {
      if (missingAllowed) return null;
      throw new Error("WPS_FORMAT_STORAGE_VALUE_MISSING");
    }
    if (typeof raw !== "string") throw new Error("WPS_FORMAT_STORAGE_VALUE_INVALID");
    try {
      return JSON.parse(raw);
    } catch (error) {
      throw new Error("WPS_FORMAT_STORAGE_JSON_INVALID");
    }
  }

  function validateEnvelope(value, draft) {
    if (!value || value.schema_version !== SCHEMA_VERSION || typeof value.config_version !== "string") {
      throw new Error("WPS_FORMAT_STORAGE_ENVELOPE_INVALID");
    }
    validateFormatConfig(value.format_config);
    if (draft) validateFormatConfig(value.default_format_config);
    return value;
  }

  function readCurrent(store) {
    const value = parseStoredJson(store.getItem(CURRENT_KEY), true);
    return value ? validateEnvelope(value, false) : null;
  }

  function writeCurrent(store, configVersion, formatConfig) {
    const envelope = {
      schema_version: SCHEMA_VERSION,
      config_version: String(configVersion || ""),
      format_config: copyJson(validateFormatConfig(formatConfig))
    };
    store.setItem(CURRENT_KEY, JSON.stringify(envelope));
    return envelope;
  }

  function readDraft(store) {
    const value = parseStoredJson(store.getItem(DRAFT_KEY), false);
    return validateEnvelope(value, true);
  }

  function writeDraft(store, configVersion, formatConfig, defaultFormatConfig) {
    const envelope = {
      schema_version: SCHEMA_VERSION,
      config_version: String(configVersion || ""),
      format_config: copyJson(validateFormatConfig(formatConfig)),
      default_format_config: copyJson(validateFormatConfig(defaultFormatConfig))
    };
    store.setItem(DRAFT_KEY, JSON.stringify(envelope));
    return envelope;
  }

  function readRevision(store) {
    const raw = store.getItem(REVISION_KEY);
    if (raw === null || raw === undefined || raw === "") return 0;
    const revision = Number(raw);
    if (!Number.isInteger(revision) || revision < 0) throw new Error("WPS_FORMAT_REVISION_INVALID");
    return revision;
  }

  function writeRevision(store, revision) {
    if (!Number.isInteger(revision) || revision < 0) throw new Error("WPS_FORMAT_REVISION_INVALID");
    store.setItem(REVISION_KEY, String(revision));
  }

  window.DocxToolFormatConfig = Object.freeze({
    SCHEMA_VERSION,
    CURRENT_KEY,
    DRAFT_KEY,
    REVISION_KEY,
    STYLE_NAMES,
    FONTS,
    SIZES,
    SIZE_POINTS,
    PATTERNS,
    INDENTS,
    ALIGNMENTS,
    copyJson,
    validateFormatConfig,
    styleByName,
    numberOr,
    formatNumberType,
    readCurrent,
    writeCurrent,
    readDraft,
    writeDraft,
    readRevision,
    writeRevision
  });
})();
