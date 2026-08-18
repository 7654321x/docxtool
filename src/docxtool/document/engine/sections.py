"""渲染阶段分节页面布局与页眉页脚引用保留。

本模块属于 Renderer 内部能力：只处理输出 DOCX 的 sectPr、页边距、
文档网格和页眉页脚关系，不读取识别状态，也不修改段落类型。
"""

from __future__ import annotations

import copy
import math

from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_LINE_SPACING
from docx.shared import Pt

from docxtool.document.configuration.models import PageSettings
from docxtool.document.engine.paragraph_styles import (
    STYLE_PROFILE_WPS_BUILTIN,
    STYLE_PROFILE_WPS_DOCXTOOL,
    normalize_style_profile,
)
from docxtool.document.diagnostics.logging import logger
from docxtool.document.errors import ExportError


def sectPr_with_preserved_header_footer_refs(sectPr, doc_part, source_parts, part_copier):
    """复制分节属性并迁移页眉页脚关系。

    传入源 sectPr、目标 doc part、源 rId 到 Part 的映射和关系复制器；
    返回复制后的 sectPr。若源为空返回 None。
    """
    if sectPr is None:
        return None

    copied_sectPr = copy.deepcopy(sectPr)
    if not source_parts:
        return copied_sectPr
    if part_copier is None:
        raise ExportError("缺少节页眉/页脚关系复制器，无法保留引用")

    for tag, reltype in (
        (qn("w:headerReference"), RT.HEADER),
        (qn("w:footerReference"), RT.FOOTER),
    ):
        for ref in list(copied_sectPr.findall(tag)):
            old_rid = ref.get(qn("r:id"))
            source_part = source_parts.get(old_rid)
            if source_part is None:
                raise ExportError(f"无法解析节页眉/页脚引用: {old_rid}")
            new_part = part_copier.copy_part(source_part)
            ref.set(qn("r:id"), doc_part.relate_to(new_part, reltype))

    return copied_sectPr


def sectPr_is_landscape(sectPr) -> bool:
    """判断分节是否为横向页面。

    传入 sectPr XML；返回 bool。优先使用 orient，缺失时按页宽页高判断。
    """
    pg_sz = sectPr.find(qn("w:pgSz")) if sectPr is not None else None
    if pg_sz is None:
        return False
    if pg_sz.get(qn("w:orient")) == "landscape":
        return True
    try:
        return int(pg_sz.get(qn("w:w"))) > int(pg_sz.get(qn("w:h")))
    except (TypeError, ValueError):
        return False


def section_margins_cm(settings: PageSettings, is_landscape: bool) -> tuple[float, float, float, float]:
    """计算分节页边距。

    传入页面设置和是否横向；返回 top、bottom、left、right 的厘米值。
    横向分节按物理边旋转纵向配置。
    """
    if not is_landscape:
        return (
            settings.margin_top_cm,
            settings.margin_bottom_cm,
            settings.margin_left_cm,
            settings.margin_right_cm,
        )
    return (
        settings.margin_left_cm,
        settings.margin_right_cm,
        settings.margin_bottom_cm,
        settings.margin_top_cm,
    )


def line_spacing_twips(settings: PageSettings) -> int:
    """把配置行距转换为 Word twips。

    传入 PageSettings；返回整数 twips。非法或空值按 28 磅处理。
    """
    try:
        value = float(settings.line_spacing_value)
    except (TypeError, ValueError):
        value = 28.0
    if value <= 0:
        value = 28.0
    return int(round(value * 20))


def doc_grid_char_space(content_width_twips: float, chars_per_line: int,
                        normal_font_size_pt: float = 16.0) -> int:
    """计算 OOXML docGrid 字距。

    传入版心宽度 twips、每行字数和 Normal 字号；返回 Word 要求的
    charSpace 整数值，即“目标字距与字号差值（磅）×4096”。
    """
    desired_pitch_pt = content_width_twips / chars_per_line / 20
    return math.floor((desired_pitch_pt - normal_font_size_pt) * 4096)


def set_sectPr_page_layout(sectPr, settings: PageSettings, doc_mode: str = "") -> None:
    """写入单个分节的页面尺寸、页边距和文档网格。

    传入 sectPr、页面设置和文档模式；返回 None，直接修改 sectPr XML。
    SCHEME 模式不写 docGrid。
    """
    if sectPr is None:
        return

    pg_sz = sectPr.find(qn("w:pgSz"))
    is_landscape = sectPr_is_landscape(sectPr)
    if not is_landscape:
        if pg_sz is None:
            pg_sz = OxmlElement("w:pgSz")
            sectPr.insert(0, pg_sz)
        pg_sz.set(qn("w:w"), str(int(round(settings.page_width_cm * 567))))
        pg_sz.set(qn("w:h"), str(int(round(settings.page_height_cm * 567))))
        pg_sz.attrib.pop(qn("w:orient"), None)
    elif pg_sz is not None:
        pg_sz.set(qn("w:orient"), "landscape")

    margin_top, margin_bottom, margin_left, margin_right = section_margins_cm(
        settings, is_landscape
    )

    pg_mar = sectPr.find(qn("w:pgMar"))
    if pg_mar is None:
        pg_mar = OxmlElement("w:pgMar")
        sectPr.append(pg_mar)
    top_twips = int(round(margin_top * 567))
    bottom_twips = int(round(margin_bottom * 567))
    left_twips = int(round(margin_left * 567))
    right_twips = int(round(margin_right * 567))
    pg_mar.set(qn("w:top"), str(top_twips))
    pg_mar.set(qn("w:bottom"), str(bottom_twips))
    pg_mar.set(qn("w:left"), str(left_twips))
    pg_mar.set(qn("w:right"), str(right_twips))
    pg_mar.set(qn("w:header"), "0")
    footer_twips = max(bottom_twips - int(round(0.7 * 567)), int(round(0.3 * 567)))
    pg_mar.set(qn("w:footer"), str(footer_twips))

    for old in sectPr.findall(qn("w:docGrid")):
        sectPr.remove(old)
    if settings.chars_per_line > 0 and settings.lines_per_page > 0 and doc_mode != "SCHEME":
        page_w = (29.7 if is_landscape else settings.page_width_cm) * 567
        if is_landscape and pg_sz is not None:
            try:
                page_w = int(pg_sz.get(qn("w:w"))) or page_w
            except (TypeError, ValueError):
                pass
        content_width = (
            page_w
            - int(pg_mar.get(qn("w:left")))
            - int(pg_mar.get(qn("w:right")))
        )
        char_space = doc_grid_char_space(content_width, settings.chars_per_line)
        doc_grid = OxmlElement("w:docGrid")
        doc_grid.set(qn("w:type"), "linesAndChars")
        doc_grid.set(qn("w:charsPerLine"), str(settings.chars_per_line))
        doc_grid.set(qn("w:linesPerPage"), str(settings.lines_per_page))
        doc_grid.set(qn("w:charSpace"), str(char_space))
        doc_grid.set(qn("w:linePitch"), str(line_spacing_twips(settings)))
        sectPr.append(doc_grid)


def write_doc_grid(section, settings: PageSettings, doc_mode: str = "") -> bool:
    """向单个 section 写入文档网格。

    传入 python-docx section、页面设置和文档模式；返回 bool 表示是否写入。
    每行字数或每页行数为 0，或 SCHEME 模式时跳过。
    """
    if settings.chars_per_line <= 0 or settings.lines_per_page <= 0:
        return False
    if doc_mode == "SCHEME":
        return False
    sectPr = section._sectPr
    for old in sectPr.findall(qn("w:docGrid")):
        sectPr.remove(old)

    pg_sz = sectPr.find(qn("w:pgSz"))
    pg_mar = sectPr.find(qn("w:pgMar"))
    try:
        page_w = int(pg_sz.get(qn("w:w")))
        left = int(pg_mar.get(qn("w:left")))
        right = int(pg_mar.get(qn("w:right")))
    except (AttributeError, TypeError, ValueError):
        twips_per_cm = 1440 / 2.54
        page_w = round(settings.page_width_cm * twips_per_cm)
        left = round(settings.margin_left_cm * twips_per_cm)
        right = round(settings.margin_right_cm * twips_per_cm)
    content_width = page_w - left - right
    char_space = doc_grid_char_space(content_width, settings.chars_per_line)
    line_pitch = line_spacing_twips(settings)

    logger.info(
        "[网格] charSpace=%s  版心=%.0ftwip  期望%s字/行",
        char_space,
        content_width,
        settings.chars_per_line,
    )
    logger.info(
        "[网格] XML: charsPerLine=%s linesPerPage=%s charSpace=%s linePitch=%s",
        settings.chars_per_line,
        settings.lines_per_page,
        char_space,
        line_pitch,
    )

    doc_grid = OxmlElement("w:docGrid")
    doc_grid.set(qn("w:type"), "linesAndChars")
    doc_grid.set(qn("w:charsPerLine"), str(settings.chars_per_line))
    doc_grid.set(qn("w:linesPerPage"), str(settings.lines_per_page))
    doc_grid.set(qn("w:charSpace"), str(char_space))
    doc_grid.set(qn("w:linePitch"), str(line_pitch))
    sectPr.append(doc_grid)
    return True


def apply_page_settings(
    doc,
    settings: PageSettings,
    doc_mode: str = "",
    *,
    style_profile: str = "docxtool",
) -> None:
    """设置输出文档全局页面、字体默认值和兼容网格。

    传入目标 Document、页面设置和文档模式；返回 None，直接写入
    documentDefaults、Normal 样式、各节 sectPr 和 settings 兼容项。
    """
    resolved_style_profile = normalize_style_profile(style_profile)
    preserve_builtin_styles = resolved_style_profile in {
        STYLE_PROFILE_WPS_BUILTIN,
        STYLE_PROFILE_WPS_DOCXTOOL,
    }
    if not preserve_builtin_styles:
        styles_element = doc.styles._element
        docDefaults = styles_element.find(qn("w:docDefaults"))
        if docDefaults is None:
            docDefaults = OxmlElement("w:docDefaults")
            styles_element.insert(0, docDefaults)
        rPrDefault = docDefaults.find(qn("w:rPrDefault"))
        if rPrDefault is None:
            rPrDefault = OxmlElement("w:rPrDefault")
            docDefaults.append(rPrDefault)
        rPrDef = rPrDefault.find(qn("w:rPr"))
        if rPrDef is None:
            rPrDef = OxmlElement("w:rPr")
            rPrDefault.append(rPrDef)
        for old in rPrDef.findall(qn("w:rFonts")):
            rPrDef.remove(old)
        for old in rPrDef.findall(qn("w:sz")):
            rPrDef.remove(old)
        for old in rPrDef.findall(qn("w:szCs")):
            rPrDef.remove(old)
        for old_lang in rPrDef.findall(qn("w:lang")):
            rPrDef.remove(old_lang)
        lang = OxmlElement("w:lang")
        lang.set(qn("w:val"), "en-US")
        lang.set(qn("w:eastAsia"), "zh-CN")
        lang.set(qn("w:bidi"), "ar-SA")
        rPrDef.append(lang)
        df = OxmlElement("w:rFonts")
        df.set(qn("w:eastAsia"), "仿宋_GB2312")
        df.set(qn("w:ascii"), "Times New Roman")
        df.set(qn("w:hAnsi"), "Times New Roman")
        rPrDef.append(df)
        sz = OxmlElement("w:sz")
        sz.set(qn("w:val"), "32")
        rPrDef.append(sz)
        szCs = OxmlElement("w:szCs")
        szCs.set(qn("w:val"), "32")
        rPrDef.append(szCs)

    style = None
    if not preserve_builtin_styles:
        style = doc.styles["Normal"]
        style.font.size = Pt(16)
        style.font.name = "Times New Roman"
        rPr = style.element.get_or_add_rPr()
        for old in rPr.findall(qn("w:rFonts")):
            rPr.remove(old)
        rFonts = OxmlElement("w:rFonts")
        rFonts.set(qn("w:eastAsia"), "仿宋_GB2312")
        rFonts.set(qn("w:ascii"), "Times New Roman")
        rFonts.set(qn("w:hAnsi"), "Times New Roman")
        rPr.insert(0, rFonts)

    for section in doc.sections:
        set_sectPr_page_layout(section._sectPr, settings, doc_mode)

    logger.info(
        "[页面] 边距 上%s 下%s 左%s 右%s cm",
        settings.margin_top_cm,
        settings.margin_bottom_cm,
        settings.margin_left_cm,
        settings.margin_right_cm,
    )

    settings_element = doc.settings._element
    compat = settings_element.find(qn("w:compat"))
    if compat is None:
        compat = OxmlElement("w:compat")
        settings_element.append(compat)
    for name, val in [
        ("compatibilityMode", "15"),
        ("overrideTableStyleFontSizeAndJustification", "1"),
        ("noExtraLineSpacing", "1"),
        ("useFELayout", "1"),
        ("balanceSingleByteDoubleByteWidth", "1"),
        ("doNotExpand", "1"),
        ("doNotLeaveBackslashAlone", "1"),
    ]:
        el = OxmlElement("w:compatSetting")
        el.set(qn("w:name"), name)
        el.set(qn("w:val"), val)
        compat.append(el)

    if style is not None:
        style.paragraph_format.space_before = Pt(0)
        style.paragraph_format.space_after = Pt(0)
        style.paragraph_format.line_spacing = Pt(settings.line_spacing_value)
        style.paragraph_format.line_spacing_rule = WD_LINE_SPACING.EXACTLY
        style_pPr = style.element.get_or_add_pPr()
        for old in style_pPr.findall(qn("w:contextualSpacing")):
            style_pPr.remove(old)
        ctxSpc = OxmlElement("w:contextualSpacing")
        ctxSpc.set(qn("w:val"), "0")
        style_pPr.append(ctxSpc)


def copy_paragraph_sectPr(para, sectPr, source_parts=None, part_copier=None,
                          settings: PageSettings | None = None, doc_mode: str = "") -> None:
    """把源分节属性复制到段落上。

    传入目标段落、源 sectPr、可选页眉页脚关系映射、关系复制器和页面设置；
    返回 None，直接替换段落 pPr 下的 sectPr。
    """
    if sectPr is None:
        return
    pPr = para._element.get_or_add_pPr()
    old = pPr.find(qn("w:sectPr"))
    if old is not None:
        pPr.remove(old)
    copied = sectPr_with_preserved_header_footer_refs(
        sectPr,
        para.part,
        source_parts or {},
        part_copier,
    )
    if settings is not None:
        set_sectPr_page_layout(copied, settings, doc_mode)
    pPr.append(copied)


def replace_body_sectPr(doc, sectPr, source_parts=None, part_copier=None,
                        settings: PageSettings | None = None, doc_mode: str = "") -> None:
    """替换文档 body 末尾分节属性。

    传入目标 Document、源 sectPr、可选页眉页脚关系映射、关系复制器和页面设置；
    返回 None，直接替换 body 下的 sectPr。
    """
    if sectPr is None:
        return
    body = doc._body._element
    old = body.find(qn("w:sectPr"))
    if old is not None:
        body.remove(old)
    copied = sectPr_with_preserved_header_footer_refs(
        sectPr,
        doc.part,
        source_parts or {},
        part_copier,
    )
    if settings is not None:
        set_sectPr_page_layout(copied, settings, doc_mode)
    body.append(copied)


def has_imported_header_footer_refs(doc_data) -> bool:
    """判断导入数据是否带有页眉页脚关系。

    传入 DocumentData 或兼容对象；返回 bool。只读取
    section_relationship_parts 属性，不触碰段落识别结果。
    """
    return bool(getattr(doc_data, "section_relationship_parts", None))


def preserve_even_and_odd_headers_setting(doc, doc_data) -> None:
    """保留源文档奇偶页不同设置。

    传入目标 Document 和 DocumentData；返回 None。若源数据带有
    even_and_odd_headers，则复制到目标 settings XML。
    """
    setting = getattr(doc_data, "even_and_odd_headers", None)
    if setting is None:
        return

    settings_element = doc.settings._element
    old = settings_element.find(qn("w:evenAndOddHeaders"))
    if old is not None:
        settings_element.remove(old)
    settings_element.append(copy.deepcopy(setting))
