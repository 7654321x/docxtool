"""engine_normal — 通用公文排版样式重写。"""

import copy
from docxtool.document.style_config import StyleRule


def _copy(rule):
    return copy.copy(rule)


def resolve(pd, raw_rule, rules, meta=None):
    """通用模式样式重写。"""
    meta = meta or pd.meta or {}
    r = raw_rule

    if meta.get("is_title"):
        return _copy(r)
    if pd.type_id == "title_cont":
        return _copy(r)
    if pd.type_id == "date_line":
        r = _copy(r)
        r.date_line_compress = True
        return r
    if pd.type_id == "author_line":
        return _copy(r)
    if pd.type_id == "role_name":
        return _copy(r)
    if pd.type_id == "heading1_report":
        return _copy(r)
    if pd.type_id == "attachment_page_mark":
        return _copy(r)
    if pd.type_id == "attachment_title":
        return _copy(r)
    if pd.type_id == "responsibility_line":
        r = _copy(r)
        r.alignment = "左对齐"
        r.first_line_indent = 0.0
        return r
    if pd.type_id in ("sign_org", "sign_date"):
        return _copy(r)
    if pd.type_id == "title2":
        return _copy(r)
    if meta.get("numbered_bold"):
        r = _copy(r); r.bold = True
        return r
    if meta.get("no_indent"):
        r = _copy(r); r.first_line_indent = 0.0
        return r
    if pd.type_id == "sign_off":
        return _copy(r)
    if meta.get("align_right"):
        r = _copy(r); r.alignment = "右对齐"
        return r
    return r
