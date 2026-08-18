"""Document import pipeline extracted from the legacy importer facade."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import re
from typing import Any, List

from docxtool.document.recognition.config import DEFAULT_CONFIG
from docxtool.document.recognition.features import BlockKind, DocumentBlock, detect_mode, extract_features
from docxtool.document.configuration.models import StyleRule


def run_document_pipeline(
    filepath: str,
    rules: List[StyleRule],
    features: dict,
    *,
    strict_preservation: bool,
    recognition_mode: str,
    importer: Any,
    compatibility: Any,
    document_factory: Any,
    import_error_type: type[Exception],
    logger: Any,
    format_scope: Any = None,
    format_scope_resolver: Any = None,
) -> Any:
    """Run the existing importer sequence through injected compatibility hooks."""

    resolved_options = compatibility.resolve_import_processing_options(
        features,
        strict_preservation=strict_preservation,
        recognition_mode=recognition_mode,
        feature_bool_func=compatibility._feature_bool,
        normalize_basic_text_func=compatibility._normalize_text,
        normalize_quotes_func=compatibility._normalize_quotes,
        to_chinese_punctuation_func=compatibility._to_chinese_punctuation,
        normalize_inline_tokens_func=compatibility._normalize_inline_tokens,
        inline_token_type=compatibility.InlineToken,
        import_error_type=import_error_type,
    )
    strict_preservation = resolved_options.strict_preservation
    structural_preservation = resolved_options.structural_preservation
    processing_strategy = resolved_options.processing_strategy
    recognition_mode = resolved_options.recognition_mode

    original_filepath = filepath
    doc = compatibility._open_docx_document(
        filepath,
        document_factory=document_factory,
        repair_broken_rels_func=compatibility._repair_broken_rels,
        import_error_type=import_error_type,
        cleanup_warning=logger.warning,
    )
    if format_scope_resolver is not None:
        if format_scope is not None:
            raise ValueError("format_scope 与 format_scope_resolver 不能同时使用")
        format_scope = format_scope_resolver(
            tuple((index, paragraph.text) for index, paragraph in enumerate(doc.paragraphs))
        )
    data = compatibility.DocumentData(
        filepath=original_filepath,
        strict_preservation=strict_preservation,
        processing_strategy=processing_strategy,
        recognition_mode=recognition_mode,
        format_scope=format_scope,
    )
    source_visible_texts = [
        paragraph.text
        for index, paragraph in enumerate(doc.paragraphs)
        if paragraph.text
        and (
            format_scope is None
            or index in format_scope.source_physical_paragraph_indexes
        )
    ]

    from docxtool.document.analysis.letterhead import (
        detect_letterhead,
        with_letterhead_fields,
    )

    data.letterhead_detection = with_letterhead_fields(doc, detect_letterhead(doc))
    protected_letterhead_indexes = set(data.letterhead_detection.protected_body_indexes)
    raw_blocks = compatibility._read_body_blocks(
        doc,
        data,
        strict_preservation=strict_preservation,
        protected_letterhead_indexes=protected_letterhead_indexes,
        extract_features_func=compatibility.extract_features,
    )
    from docxtool.document.analysis.layout_policy import (
        assign_pre_normalization_layout_hints,
    )

    assign_pre_normalization_layout_hints(raw_blocks)
    mode_features = []
    for block_index, block in enumerate(raw_blocks):
        if block[0] != "paragraph":
            continue
        _, paragraph, paragraph_features, _inline_tokens, _sect_pr = block
        source_text = paragraph_features.source_physical_text or paragraph.text
        mode_features.append(DocumentBlock(
            index=block_index,
            kind=BlockKind.PARAGRAPH,
            text=source_text,
            paragraph_index=len(mode_features),
            style_name=paragraph_features.style_name,
            alignment=paragraph_features.alignment,
            bold=paragraph_features.bold,
            font_size_pt=paragraph_features.weighted_font_size or paragraph_features.font_size_pt,
            weighted_font_size=paragraph_features.weighted_font_size,
            max_font_size=paragraph_features.max_font_size,
            min_font_size=paragraph_features.min_font_size,
            bold_char_ratio=paragraph_features.bold_char_ratio,
            italic_char_ratio=paragraph_features.italic_char_ratio,
            explicitly_formatted_char_ratio=paragraph_features.explicitly_formatted_char_ratio,
            raw_reference=paragraph,
        ))
    mode_features = [
        extract_features(
            block,
            mode_features[index - 1] if index else None,
            mode_features[index + 1] if index + 1 < len(mode_features) else None,
        )
        for index, block in enumerate(mode_features)
    ]
    document_mode = detect_mode(mode_features).mode
    flat_lines = compatibility._build_logical_lines(
        raw_blocks,
        document_mode=document_mode,
        strict_preservation=strict_preservation,
        structural_preservation=structural_preservation,
        split_inline_heading_body_enabled=resolved_options.split_inline_heading_body,
        normalize_text_func=resolved_options.normalize_text,
        source_starts_body_region_func=compatibility._source_starts_body_region,
        split_inline_heading_body_spans_func=compatibility._split_inline_heading_body_spans,
        validate_numbered_heading_body_split_func=(
            compatibility._validate_numbered_heading_body_split
        ),
        should_split_structural_line_breaks_func=(
            compatibility._should_split_structural_line_breaks
        ),
        split_structural_tail_after_numbered_heading_func=(
            compatibility._split_structural_tail_after_numbered_heading
        ),
        validate_source_span_partition_func=compatibility._validate_source_span_partition,
        detect_numbering_prefix_func=compatibility._detect_numbering_prefix,
        inline_lead_bold_func=compatibility._has_inline_lead_bold_transition,
    )

    ctx = compatibility.DetectionContext()
    last_body_idx = compatibility._find_last_body_candidate_index(
        [item[1] if item[0] == "text" else "" for item in flat_lines],
        is_attachment_start_func=lambda text: bool(re.match(r"^附件", text)),
        is_sign_date_func=compatibility._normalization_is_sign_date_text,
        is_attachment_item_func=lambda text: bool(re.match(r"^\d+[.．、]", text)),
        is_attachment_page_mark_func=compatibility._is_attachment_page_mark,
    )
    for index, item in enumerate(flat_lines):
        ctx._remaining_has_no_body = index >= last_body_idx
        materialized = compatibility._materialize_non_text_item(item)
        if materialized is not None:
            data.paragraphs.append(materialized)
            continue

        _, line, paragraph_features, inline_tokens, sect_pr = item
        next_line, next_features = compatibility._next_text_and_features(flat_lines, index)
        managed_title = (
            data.letterhead_detection.status == "managed"
            and paragraph_features.style_name == "Docxtool Title"
            and not ctx.has_seen_real_body
        )
        if managed_title:
            type_id = "title" if not ctx.title_texts else "title_cont"
            meta_patch = {"is_title": True} if type_id == "title" else {}
            prefix = ""
            clean_text = line
        else:
            structural_type, structural_meta, structural_prefix, fixed_text = (
                compatibility.detect_structural_type(
                    line,
                    next_line,
                    ctx,
                    paragraph_features,
                    next_features,
                )
            )
            if structural_type:
                structural_meta.pop("numbering", None)
                type_id = structural_type
                meta_patch = structural_meta
                prefix = structural_prefix
                clean_text = fixed_text
                ctx.prev_type_id = structural_type
            else:
                type_id, meta_patch, prefix = compatibility.detect_paragraph_type(
                    line,
                    paragraph_features,
                    ctx,
                    rules,
                )
                clean_text = compatibility.strip_numbering(line, prefix)

        if strict_preservation or structural_preservation:
            clean_text = line
            meta_patch = dict(meta_patch or {})
            meta_patch.pop("numbering", None)
            if meta_patch.get("strip_inferred_speech_numbering"):
                clean_text = compatibility._strip_inferred_speech_numbering(line)

        if ctx.attachment_page_mode and type_id == "body":
            type_id = "attachment_body"
        type_id = compatibility._advance_legacy_context(
            ctx,
            type_id,
            clean_text,
            meta_patch,
            record_structural_func=compatibility._record_structural,
        )
        paragraph = compatibility._materialize_text_paragraph(
            line=line,
            clean_text=clean_text,
            type_id=type_id,
            features=paragraph_features,
            meta=meta_patch,
            inline_tokens=inline_tokens,
            sect_pr=sect_pr,
            strict_preservation=strict_preservation,
            recognition_version=compatibility.RECOGNITION_VERSION_TAG,
            paragraph_index=len(data.paragraphs),
            logger=logger,
        )
        data.paragraphs.append(paragraph)

    data.doc_mode = document_mode.value
    before_normalization = compatibility._normalization_capture_pre_normalization_snapshot(
        data,
        source_visible_texts,
    )
    if strict_preservation:
        importer._record_strict_normalization_suggestions(data)
    importer._apply_core_classification(data, features)
    compatibility.apply_recognition(
        data,
        replace(DEFAULT_CONFIG, mode=recognition_mode),
    )
    compatibility._normalization_apply_post_recognition_normalization(
        data,
        rules,
        doc.paragraphs,
        strict_preservation=strict_preservation,
        structural_preservation=structural_preservation,
        processing_strategy=processing_strategy,
        numbering_enabled=resolved_options.numbering_enabled,
        before_normalization=before_normalization,
        normalize_tail_structures_func=compatibility._normalize_tail_structures,
        reorder_attachment_note_before_signature_func=(
            importer._reorder_attachment_note_before_signature
        ),
        assign_numbering_func=importer._assign_numbering,
        record_applied_normalization_changes_func=(
            importer._record_applied_normalization_changes
        ),
        fix_numbering_gaps_func=importer._fix_numbering_gaps,
        strip_auto_numbering_func=importer._strip_auto_numbering,
        sync_recognition_consistency_func=compatibility._sync_recognition_consistency,
    )
    from docxtool.document.analysis.document_structure import analyze_document_structure
    from docxtool.document.analysis.layout_policy import (
        assign_layout_policies,
        validate_layout_preservation,
    )

    data.recognition_structure = analyze_document_structure(data)
    assign_layout_policies(data, data.recognition_structure)
    validate_layout_preservation(data)
    data.recognition_diagnostics["structure_tree"] = "built"
    logger.info(
        "[导入] source_path_hash=%s paragraphs=%s tables=%s strategy=%s recognition=%s",
        hashlib.sha256(str(original_filepath).encode("utf-8")).hexdigest()[:12],
        len(data.paragraphs),
        len(data.tables),
        processing_strategy,
        recognition_mode,
    )
    return data
