"""Finalize page structures, validation, statistics, and DOCX saving."""
# ruff: noqa: F821

from __future__ import annotations

from docxtool.document.engine.letterhead import LetterheadResult


def _sync_from_core(module) -> None:
    for name, value in vars(module).items():
        if not name.startswith("__"):
            globals()[name] = value


def finalize_export(
    context,
    doc_data,
    rules,
    settings,
    output_path,
    page_number_enabled,
    page_number_options,
    signature_block_options,
    table_format_options,
    cleanup_options,
    letterhead_options,
    *,
    compatibility_module,
):
    _sync_from_core(compatibility_module)
    doc = context.doc
    protected_paragraph_elements = context.protected_paragraph_elements
    letterhead_detection = context.letterhead_detection
    letterhead_enabled = context.letterhead_enabled
    stats = context.stats
    section_paragraphs = context.section_paragraphs
    section_relationship_parts = context.section_relationship_parts
    section_part_copier = context.section_part_copier
    page_rule = context.page_rule
    inline_heading_body_pairs = context.inline_heading_body_pairs
    local_scope = getattr(doc_data, "format_scope", None) is not None

    # 后处理：上标统一
    for para in doc.paragraphs:
        if para._p in protected_paragraph_elements:
            continue
        _apply_universal_superscript(para)

    # 后处理：数字/字母 → Times New Roman
    for para in doc.paragraphs:
        if para._p in protected_paragraph_elements:
            continue
        _apply_digit_latin_font(para)

    # 版头只负责首页正文流，不得覆盖整篇文档的页面设置。
    page_settings = settings
    if not local_scope:
        apply_page_settings(
            doc,
            page_settings,
            doc_data.doc_mode,
            style_profile=context.style_profile,
        )
    _preserve_even_and_odd_headers_setting(doc, doc_data)

    # Structural-preservation mode may split a previously fused leading
    # paragraph into a document number, title and role line.  The source-level
    # detector cannot see that virtual structure, so inspect the rebuilt body
    # once before deciding whether to preserve or complete an existing header.
    apply_detection = letterhead_detection
    if letterhead_detection.status == "none":
        rebuilt_detection = detect_letterhead(doc)
        if rebuilt_detection.status != "none":
            apply_detection = rebuilt_detection
    if letterhead_enabled and letterhead_detection.status != "none":
        # Existing source blocks were intentionally omitted above. Keep the
        # original status for reporting without applying source indexes to the
        # rebuilt output body.
        apply_detection = LetterheadDetection(
            letterhead_detection.status,
            (),
            letterhead_detection.details,
            letterhead_detection.fields,
        )
    letterhead_result = (
        LetterheadResult("preserved", apply_detection.status)
        if local_scope
        else apply_letterhead(
            doc,
            letterhead_options,
            detection=apply_detection,
            rules=rules,
            settings=page_settings,
        )
    )
    # 版头在全局西文字体后处理之后生成，因此需要补做同一轮扫描。
    for element in letterhead_result.protected_elements:
        if element.tag == qn("w:p"):
            _apply_digit_latin_font(Paragraph(element, doc._body))
    protected_paragraph_elements.update(letterhead_result.protected_elements)
    stats["letterhead_detection"] = letterhead_result.detection
    stats["letterhead_action"] = letterhead_result.action
    stats["compatibility_warnings"] = list(letterhead_result.warnings)

    for para, sectPr in section_paragraphs:
        _copy_paragraph_sectPr(
            para,
            sectPr,
            section_relationship_parts,
            section_part_copier,
            None if local_scope else page_settings,
            doc_data.doc_mode,
        )

    _replace_body_sectPr(
        doc,
        getattr(doc_data, "body_sectPr", None),
        section_relationship_parts,
        section_part_copier,
        None if local_scope else page_settings,
        doc_data.doc_mode,
    )

    stats["signature_blocks_adjusted"] = (
        0 if local_scope else apply_signature_block(doc, signature_block_options)
    )

    if local_scope:
        pass
    elif page_number_options is not None:
        if _feature_enabled(page_number_options, True):
            page_options = dict(_feature_options(page_number_options))
            page_options.setdefault("font_name", page_rule.font)
            page_options.setdefault("font_size_pt", page_rule.font_size_pt)
            page_options.setdefault("bold", page_rule.bold)
            if isinstance(page_options.get("first_page"), bool):
                page_options["first_page"] = "show" if page_options["first_page"] else "hide"
            apply_page_number(doc, page_options)
    elif page_number_enabled:
        apply_page_number(
            doc,
            {
                "style": "dash",
                "position": "outside",
                "first_page": True,
                "font_name": page_rule.font,
                "font_size_pt": page_rule.font_size_pt,
                "bold": page_rule.bold,
                "offset_from_text_mm": 7,
            },
        )

    if _feature_enabled(table_format_options, False):
        logger.info("[表格] 当前阶段仅原样复制，已忽略表格格式化配置")
    if not local_scope and _feature_enabled(cleanup_options, False):
        cleanup_styles(doc, _feature_options(cleanup_options), protected_paragraph_elements)

    # 页面行数诊断
    page_h_cm = (
        page_settings.page_height_cm - page_settings.margin_top_cm - page_settings.margin_bottom_cm
    )
    max_lines = page_h_cm / (page_settings.line_spacing_value * 0.0353)  # pt→cm
    logger.info(
        f"[页面] 版心高度={page_h_cm:.1f}cm 行距={page_settings.line_spacing_value}pt → 理论最大={max_lines:.1f}行 设定={page_settings.lines_per_page}行"
    )

    invariant_stats = _enforce_body_paragraph_invariants(
        doc,
        protected_paragraph_elements | context.native_numbering_elements,
        style_profile=context.style_profile,
    )
    stats.update(invariant_stats)
    for heading_para, body_para, expected_body_text in inline_heading_body_pairs:
        _verify_inline_heading_body_pair(
            heading_para,
            body_para,
            expected_body_text,
            expected_body_style_id=_style_id_for_type(
                "body",
                context.style_profile,
            ),
        )
    stats["inline_heading_body_verified"] = len(inline_heading_body_pairs)
    stats["style_fallback_count"] = stats["fallback_count"]
    if invariant_stats["fallback_count"] or invariant_stats["numpr_removed"]:
        logger.info(
            "[结构样式] fallback_count=%s numpr_removed=%s",
            invariant_stats["fallback_count"],
            invariant_stats["numpr_removed"],
        )

    # 保存
    try:
        doc.save(output_path)
        logger.info(
            "[引擎] 排版完成 output_sha256=%s",
            hashlib.sha256(str(output_path).encode("utf-8")).hexdigest()[:12],
        )
    except Exception as e:
        raise ExportError(f"保存失败 {output_path}: {e}")

    return stats
