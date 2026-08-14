"""Render normal and preserved document items in their original order."""
# ruff: noqa: F821

from __future__ import annotations

from .special_items import render_special_item


def _sync_from_core(module) -> None:
    for name, value in vars(module).items():
        if not name.startswith("__"):
            globals()[name] = value


def render_document_items(
    context,
    doc_data,
    rules,
    settings,
    numbered_bold_enabled=True,
    *,
    compatibility_module,
):
    """Render the existing item loop against one shared export context."""
    _compatibility_module = compatibility_module
    _sync_from_core(_compatibility_module)
    doc = context.doc
    section_relationship_parts = context.section_relationship_parts
    section_part_copier = context.section_part_copier
    stats = context.stats
    prev_was_title = context.prev_was_title
    prev_type_id = context.prev_type_id
    body_flow_started = context.body_flow_started
    line_twips = context.line_twips
    numbering_enabled = context.numbering_enabled
    native_numbering_copier = context.native_numbering_copier
    numbering_mode = context.numbering_mode
    strict_preservation = context.strict_preservation
    normalization_processing = context.normalization_processing
    render_items = context.render_items
    paragraph_i = context.paragraph_i
    _deferred_body_log = context.deferred_body_log
    inline_heading_body_pairs = context.inline_heading_body_pairs
    section_paragraphs = context.section_paragraphs
    letterhead_enabled = context.letterhead_enabled
    style_profile = context.style_profile

    for i, pd in enumerate(render_items):
        if render_special_item(context, pd, compatibility_module=_compatibility_module):
            continue

        para_no = paragraph_i
        paragraph_i += 1
        try:
            logger.debug("[引擎] 段落 %s: type=%s chars=%s", para_no, pd.type_id, len(pd.text))
            preserve_layout = pd.meta.get("layout_policy") == "preserve_layout"

            # 确定对应的 StyleRule 索引
            rule_index = TYPE_TO_RULE_INDEX.get(pd.type_id)
            if rule_index is None:
                logger.warning("[渲染] 未知段落类型 %r，显式使用正文规则", pd.type_id)
                rule_index = 5
            raw_rule = rules[rule_index] if rule_index < len(rules) else StyleRule.default_for_row(rule_index)

            # glossary_title 特殊处理（内联段落）
            if pd.type_id == "glossary_title":
                resolved = copy.copy(raw_rule)
                resolved.row_index = 0
                resolved.font = "方正小标宋简体"
                resolved.font_size_pt = 22
                resolved.bold = False
                resolved.alignment = "居中"
                resolved.first_line_indent = 0.0
                para = doc.add_paragraph(pd.text)
                run = para.runs[0] if para.runs else para.add_run(pd.text)
                apply_style(para, resolved)
                _set_run_fonts(run, cn_font=resolved.font)
                run.font.size = Pt(resolved.font_size_pt)
                run.font.bold = resolved.bold
                _set_para_spacing(para, before_lines=1, after_lines=1)
                pPr = para._element.get_or_add_pPr()
                page_break = OxmlElement('w:pageBreakBefore')
                pPr.append(page_break)
                prev_was_title = True
                continue

            # meta → 重写规则（按文种分派）
            resolved = _resolve_rule(pd, raw_rule, rules)

            # 空行插入（三号 16pt 行距 28 磅）
            # date_line 后的留白由段后间距控制，避免生成真实空段落。
            need_gap = (prev_was_title and is_head_gap_follow_type(pd.type_id)
                        and prev_type_id not in ("date_line", "role_name")
                        and pd.text.strip())

            if need_gap and not letterhead_enabled and not strict_preservation:
                spacer = doc.add_paragraph("")
                spPPr = spacer._element.get_or_add_pPr()
                spSpacing = OxmlElement('w:spacing')
                spSpacing.set(qn('w:line'), str(line_twips))
                spSpacing.set(qn('w:lineRule'), 'exact')
                spPPr.append(spSpacing)
                spacer.add_run("").font.size = Pt(16)

            # 标题先清理旧编号，再建段落
            text = pd.text
            # A standalone heading is not a body sentence. Its terminal
            # Chinese full stop is copied formatting noise and is removed in
            # every editable processing mode at all four heading levels.
            stripped_text = text.rstrip()
            first_period = stripped_text.find("。")
            has_inline_body = (
                first_period >= 0
                and len(stripped_text[first_period + 1:].strip())
                >= _INLINE_HEADING_BODY_MIN_CHARS
            )
            if (
                not strict_preservation
                and pd.type_id in ("heading1", "heading2", "heading3", "heading4")
                and stripped_text.endswith("。")
                and not has_inline_body
            ):
                text = stripped_text[:-1]
            if numbering_enabled and normalization_processing and not preserve_layout:
                numbering_result = normalize_numbering_text(text, safe=numbering_mode != "off")
                if numbering_result.changed:
                    text = numbering_result.text
            numbering_correction = bool(pd.meta.get("numbering_correction"))
            if not preserve_layout and pd.type_id.startswith("heading") and (
                normalization_processing or numbering_correction
            ):
                text = _strip_heading_numbering(text)
                # 一/二级标题特殊处理：句号分割的行内标题（政协报告体例）
                if normalization_processing and pd.type_id in ("heading1", "heading2"):
                    text = _handle_heading_period(text)

            inline_tokens = list(getattr(pd, "inline_tokens", None) or [])
            if normalization_processing and not preserve_layout:
                inline_tokens = _without_redundant_trailing_body_page_breaks(
                    pd,
                    render_items[i + 1] if i + 1 < len(render_items) else None,
                    inline_tokens,
                )
            if inline_tokens and text == pd.text:
                para = doc.add_paragraph("")
                _write_inline_tokens(para, inline_tokens)
            else:
                para = doc.add_paragraph(text)
            _set_paragraph_style_id(
                para,
                _style_id_for_type(pd.type_id, style_profile),
            )
            native_numbering = getattr(getattr(pd, "features", None), "native_numbering", None)
            preserve_native_numbering = bool(
                native_numbering is not None
                and (
                    strict_preservation
                    or not (numbering_enabled and pd.type_id.startswith("heading"))
                )
            )
            if preserve_native_numbering:
                native_numbering_copier.apply(para, native_numbering)
                context.native_numbering_elements.add(para._p)
                stats["native_numbering_preserved"] += 1
            next_pd = render_items[i + 1] if i + 1 < len(render_items) else None
            if _is_standalone_keep_heading(pd, next_pd, para.text):
                _set_keep_with_next(para)

            # 逐段写入 XML 属性
            pPr = para._element.get_or_add_pPr()
            spacing = OxmlElement('w:spacing')
            # 段前/段后间距（自然模式下生效）
            before_lines = settings.space_before_line + (
                1 if need_gap and letterhead_enabled else 0
            )
            if strict_preservation and need_gap and not letterhead_enabled:
                before_lines += 1
            before_twip = int(before_lines * line_twips)
            after_twip = int(settings.space_after_line * line_twips)
            spacing.set(qn('w:before'), str(before_twip))
            spacing.set(qn('w:after'), str(after_twip))
            spacing.set(qn('w:beforeLines'), str(int(before_lines * 100)))
            spacing.set(qn('w:afterLines'), str(int(settings.space_after_line * 100)))
            # 网格模式 → 固定行距；自然模式(每行=0) → 不设，让段间距生效
            if settings.chars_per_line > 0:
                spacing.set(qn('w:line'), str(line_twips))
                spacing.set(qn('w:lineRule'), 'exact')
            pPr.append(spacing)
            if i < 3:
                logger.info(f"[段落{i}] XML: grid={'on' if settings.chars_per_line>0 else 'off'}")
            # 禁用 Word 自动上下文间距
            ctxSpc = OxmlElement('w:contextualSpacing')
            ctxSpc.set(qn('w:val'), '0')
            _set_unique(pPr, qn('w:contextualSpacing'), ctxSpc)
            # 关闭孤行控制
            wc = OxmlElement('w:widowControl')
            wc.set(qn('w:val'), '0')
            _set_unique(pPr, qn('w:widowControl'), wc)

            # 应用样式（带降级）
            if not apply_style_safe(para, resolved):
                logger.warning(f"[引擎] 段落 {i} 样式降级，继续后续")
                first_start = getattr(resolved, 'first_line_indent', 2.0) or 2.0
                _apply_hanging_indent_chars(para, first_start, first_start)

            _apply_rule_paragraph_format(para, resolved, line_twips)

            if pd.type_id == "dispatch_number":
                para.alignment = WD_ALIGN_PARAGRAPH.CENTER
                _apply_first_line_indent_chars(para, 0)

            # GB/T 9704 落款位置：发文机关右空 2 字，成文日期右空 4 字。
            # 直接格式固定最终位置，避免浏览器旧配置覆盖规范值。
            if pd.type_id == "sign_org":
                _apply_right_indent(para, 2)
            elif pd.type_id == "sign_date":
                _apply_right_indent(para, 4)

            # 头部署名/日期的相邻间距：
            # 主标题与职务姓名之间空 1 行，职务姓名与后续标题/正文也空 1 行。
            if pd.type_id in ("role_name", "author_line"):
                head_gap = (
                    1
                    if pd.type_id == "role_name"
                    and prev_type_id in ("title", "title_cont")
                    else 0
                )
                _set_para_spacing(
                    para,
                    before_lines=head_gap,
                    after_lines=(
                        1
                        if pd.type_id == "role_name"
                        and (next_pd is None or next_pd.type_id != "date_line")
                        else 0
                    ),
                    line_twips=line_twips,
                )
            elif pd.type_id == "date_line":
                _set_para_spacing(para, before_lines=0, after_lines=1, line_twips=line_twips)
            elif pd.type_id == "addressing" and body_flow_started:
                # Opening salutations keep the configured one-line gap.  A
                # repeated salutation inside or after the speech body is part
                # of the body flow and must not create another blank line.
                _set_para_spacing(
                    para,
                    before_lines=0,
                    after_lines=0,
                    line_twips=line_twips,
                    explicit_zero=True,
                )
            elif pd.type_id in ("heading2", "heading3", "heading4"):
                _set_para_spacing(para, before_lines=0, after_lines=0, line_twips=line_twips)
            elif pd.type_id == "sign_org" and prev_type_id in (
                "attachment_note", "attachment_note_item"
            ):
                _set_para_spacing(para, before_lines=3, after_lines=0, line_twips=line_twips)

            # (colon_inline_body removed — scheme mode deleted)            # date_line 强制适应一行（自动计算压缩量）
            if getattr(resolved, 'date_line_compress', False):
                pPr = para._element.get_or_add_pPr()
                csc = OxmlElement('w:characterSpacingControl')
                csc.set(qn('w:val'), 'compressPunctuation')
                pPr.append(csc)
                # 自动计算字符间距压缩
                text_len = len(pd.text)
                if text_len > 27:
                    shrink = min(int((text_len - 27) * 5), 40)  # 每超出1字收紧0.25pt，最多2pt
                    for run in para.runs:
                        rPr = run._element.get_or_add_rPr()
                        sp = OxmlElement('w:spacing')
                        sp.set(qn('w:val'), str(-shrink))
                        rPr.append(sp)

            # glossary_title 独立分支保留；其他段前段后由 JSON StyleRule 控制。
            if pd.type_id == "glossary_title":
                _set_para_spacing(para, before_lines=1, after_lines=1, line_twips=line_twips)

            # Compatibility input can still contain a heading/body sentence
            # in one ParagraphData item. Split it once into a heading and one
            # complete body paragraph; later body sentences stay together.
            if not strict_preservation and pd.type_id == "heading1" and "。" in para.text:
                full_text = para.text
                expected_body_text = full_text.split("。", 1)[1].strip()
                body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                body_para = _apply_heading1_report_split(
                    para, full_text, resolved, body_rule, line_twips,
                    remove_heading_period=True,
                    body_style_id=_style_id_for_type("body", style_profile),
                )
                if body_para is not None:
                    body_text = body_para.text
                    inline_heading_body_pairs.append((para, body_para, expected_body_text))
                    stats["body"] += 1
                    apply_superscript_split(body_para)
                    if numbered_bold_enabled:
                        _apply_special_bold(body_para, body_text)
                    _deferred_body_log.append(
                        f"[排版] #{i}h1→body | chars={len(body_text)} | "
                        f"字体={body_rule.font} | 字号={body_rule.font_size_pt}pt | 加粗={body_rule.bold} | "
                        f"对齐={body_rule.alignment} | 首行缩进={body_rule.first_line_indent}字符 | "
                        f"行距={settings.line_spacing_value}pt固定 | 对网=1"
                    )

            # X是/固定词组 特殊加粗
            inline_heading2_colon = bool(
                pd.type_id == "heading2"
                and (
                    pd.meta.get("numbered_heading2_colon_inline_body")
                    or getattr(
                        getattr(pd, "features", None),
                        "numbered_heading2_colon_inline_body",
                        False,
                    )
                )
            )
            inline_heading2_period = bool(
                pd.type_id == "heading2"
                and (
                    pd.meta.get("numbered_heading2_period_inline_body")
                    or getattr(
                        getattr(pd, "features", None),
                        "numbered_heading2_period_inline_body",
                        False,
                    )
                )
            )
            inline_heading2_body = inline_heading2_colon or inline_heading2_period
            if (
                not preserve_layout
                and not inline_heading2_body
                and pd.meta.get("numbered_bold")
                and para.runs
            ):
                _apply_special_bold(para, pd.text)

            if not preserve_layout and pd.type_id == "responsibility_line" and para.runs:
                _apply_responsibility_line(para, pd.text)

            # 冒号关键词加粗（如"责任单位：区政府" → "责任单位："加粗）
            if (
                not preserve_layout
                and not inline_heading2_body
                and pd.type_id != "responsibility_line"
                and pd.meta.get("colon_bold")
                and para.runs
            ):
                _apply_colon_bold(para, pd.text)

            if (
                not preserve_layout
                and not inline_heading2_body
                and (pd.type_id == "responsibility_line" or pd.meta.get("colon_bold"))
                and para.runs
            ):
                _apply_key_value_line_format(para)

            # Legacy report metadata still reaches this compatibility branch
            # when the generic structural split did not already consume it.
            if (
                normalization_processing
                and pd.meta.get("heading1_report_split")
                and para.runs
                and "。" in para.text
            ):
                body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                expected_body_text = pd.text.split("。", 1)[1].strip()
                body_para = _apply_heading1_report_split(
                    para,
                    pd.text,
                    resolved,
                    body_rule,
                    line_twips,
                    body_style_id=_style_id_for_type("body", style_profile),
                )
                if body_para is not None:
                    inline_heading_body_pairs.append((para, body_para, expected_body_text))
                    stats["body"] += 1

            # Source-backed inline emphasis keeps one physical body paragraph.
            if (
                not preserve_layout
                and not inline_heading2_body
                and pd.meta.get("inline_lead_bold")
                and para.runs
            ):
                _apply_inline_lead_bold(para, pd.text, resolved)
            # 报告首句加粗（首句楷体_GB2312 加粗，剩余仿宋正文）
            elif (
                not preserve_layout
                and not inline_heading2_body
                and pd.meta.get("report_first_sentence_bold")
                and para.runs
            ):
                _apply_report_first_sentence(para, pd.text, resolved)

            # 编号：从 meta 读取预计算编号，插入到第一个 run 前
            numbering = "" if strict_preservation or pd.meta.get("colon_inline_body") else pd.meta.get("numbering", "")
            logger.debug(f"[编号] meta={numbering!r} type={pd.type_id}")
            if numbering and para.runs:
                new_r = OxmlElement('w:r')
                t = OxmlElement('w:t')
                t.text = numbering
                new_r.append(t)
                # 设置字体
                rPr = OxmlElement('w:rPr')
                rF = OxmlElement('w:rFonts')
                rF.set(qn('w:eastAsia'), resolved.font)
                rF.set(qn('w:ascii'), 'Times New Roman')
                rF.set(qn('w:hAnsi'), 'Times New Roman')
                rPr.append(rF)
                sz = OxmlElement('w:sz')
                sz.set(qn('w:val'), str(int(resolved.font_size_pt * 2)))  # half-pt → 1/2pt
                rPr.append(sz)
                if resolved.bold:
                    b = OxmlElement('w:b')
                    rPr.append(b)
                new_r.insert(0, rPr)
                para.runs[0]._element.addprevious(new_r)

            if pd.type_id == "heading2":
                body_rule = rules[5] if len(rules) > 5 else StyleRule.default_for_row(5)
                if not strict_preservation and inline_heading2_colon:
                    _apply_numbered_heading2_colon_format(
                        para, para.text, resolved, body_rule
                    )
                elif not strict_preservation and inline_heading2_period:
                    _apply_numbered_heading2_period_format(
                        para, para.text, resolved, body_rule
                    )
                elif not strict_preservation:
                    _apply_numbered_heading2_period_format(
                        para, para.text, resolved, body_rule
                    )
                else:
                    _enforce_inline_heading2_format(para, resolved.bold, body_rule.bold)

            # 名词解释条目（编号后执行：关键词黑体，正文仿宋）
            if not preserve_layout and pd.meta.get("glossary_item") and para.runs:
                _apply_glossary_item(para, pd.text, resolved)

            # 上标拆分
            if not preserve_layout:
                apply_superscript_split(para)

            # 最终强制 snapToGrid
            pPr_final = para._element.get_or_add_pPr()
            snap_val = '0' if pd.type_id in ('title', 'heading1', 'heading2', 'heading3', 'heading4') else '1'
            snap = OxmlElement('w:snapToGrid')
            snap.set(qn('w:val'), snap_val)
            _set_unique(pPr_final, qn('w:snapToGrid'), snap)
            if _is_terminal_body_paragraph(render_items, i, pd):
                _set_widow_control(para, True)
            if pd.meta.get("sectPr") is not None:
                section_paragraphs.append((para, pd.meta.get("sectPr")))
                _copy_paragraph_sectPr(
                    para,
                    pd.meta.get("sectPr"),
                    section_relationship_parts,
                    section_part_copier,
                    settings,
                    doc_data.doc_mode,
                )
            # 段落排版日志（每段汇总格式信息）
            text_digest = hashlib.sha256(pd.text.encode("utf-8")).hexdigest()[:12]
            indent = getattr(resolved, 'first_line_indent', 0)
            logger.info(
                f"[排版] #{i} {pd.type_id} | "
                f"chars={len(pd.text)} text_sha256={text_digest} | "
                f"字体={resolved.font} | "
                f"字号={resolved.font_size_pt}pt | "
                f"加粗={resolved.bold} | "
                f"对齐={resolved.alignment} | "
                f"首行缩进={int(indent)}字符 | "
                    f"行距={settings.line_spacing_value}pt固定 | "
                f"对网={snap_val}"
            )
            # 输出 heading1 拆出的 body 日志
            for log_line in _deferred_body_log:
                logger.info(log_line)
            _deferred_body_log.clear()

            # 记录头部区域；后接正文或一级标题时需要空一行。
            prev_was_title = is_head_type_requiring_gap(pd.type_id)
            prev_type_id = pd.type_id
            if is_body_flow_type(pd.type_id):
                body_flow_started = True

            # 统计
            if pd.type_id in stats:
                stats[pd.type_id] += 1
            elif pd.type_id.startswith("heading"):
                k = pd.type_id
                stats[k] = stats.get(k, 0) + 1
            else:
                stats["body"] += 1

        except ExportError:
            raise
        except Exception as e:
            if is_structure_sensitive_type(pd.type_id):
                raise ExportError(
                    f"结构段落排版失败: type={pd.type_id} index={i}"
                ) from e
            logger.error(f"[引擎] 段落 {i} 异常: {e}，降级为纯文本")
            # 降级兜底：不跳过，用原始文本 + 正文格式写入
            try:
                fallback = doc.add_paragraph(pd.text)
                fallback.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
                stats["body"] += 1
            except Exception:
                pass  # 最终兜底：实在写不了才跳过
            continue
