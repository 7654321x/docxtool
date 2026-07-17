from copy import deepcopy
from dataclasses import replace

from docxtool.document.engine.context_candidate import (
    build_raw_element_facts,
    classify_context_candidate,
)
from docxtool.document.engine.document_structure import (
    BlockKind,
    BodyBlock,
    ElementKind,
    analyze_document_structure,
)
from docxtool.document.engine.structure_context import (
    ValidationStatus,
    revalidate_element,
    validate_structure_context,
)
from docxtool.document.importer import DocumentData, InlineToken, ParagraphData, ParagraphFeatures


def paragraph(text, type_id, *, tokens=(), confidence=0.95):
    return ParagraphData(
        text, type_id, text, ParagraphFeatures(text=text),
        {"classification_confidence": confidence}, list(tokens),
    )


def candidate(paragraphs, source_index):
    facts = build_raw_element_facts(paragraphs)
    fact = next(item for item in facts if item.source_index == source_index and item.physical_kind != "page_break")
    return classify_context_candidate(facts, fact.index)


def test_same_date_changes_role_with_real_neighbors():
    title_date = [
        paragraph("公文标题", "title"), paragraph("2026年7月17日", "sign_date"),
        paragraph("正文内容较长并以句号结束。", "body"),
    ]
    body_date = [
        paragraph("前一段正文内容较长。", "body"), paragraph("2026年7月17日", "sign_date"),
        paragraph("后一段正文内容较长。", "body"),
    ]
    signature_date = [
        paragraph("正文内容较长并以句号结束。", "body"), paragraph("测试市人民政府", "body"),
        paragraph("2026年7月17日", "body"),
    ]

    assert candidate(title_date, 1).kind == ElementKind.TITLE_METADATA
    assert candidate(body_date, 1).kind == ElementKind.BODY_PARAGRAPH
    assert candidate(signature_date, 2).kind == ElementKind.SIGNATURE_DATE


def test_raw_sign_date_without_signature_is_not_confirmed_signature_date():
    paragraphs = [paragraph("正文内容较长。", "body"), paragraph("2026年7月17日", "sign_date")]
    result = candidate(paragraphs, 1)
    assert result.kind != ElementKind.SIGNATURE_DATE
    assert "previous:signature_candidate" not in {item.detail for item in result.evidence}


def test_plain_raw_type_can_become_signature_date_from_context():
    paragraphs = [
        paragraph("正文内容较长。", "body"), paragraph("测试市人民政府", "body"),
        paragraph("2026年7月17日", "body"),
    ]
    result = candidate(paragraphs, 2)
    assert result.kind == ElementKind.SIGNATURE_DATE
    assert "previous:signature_candidate" in {item.detail for item in result.evidence}
    assert "following:document_end" in {item.detail for item in result.evidence}


def test_title_and_signature_agency_are_distinguished_by_neighbors():
    title = [paragraph("公文标题", "title"), paragraph("测试机关", "sign_org"), paragraph("正文内容较长。", "body")]
    tail = [paragraph("正文内容较长。", "body"), paragraph("测试机关", "body"), paragraph("2026年7月17日", "body")]
    body = [paragraph("前一段正文内容。", "body"), paragraph("本项目由测试市人民政府办公室负责实施。", "sign_org"), paragraph("后一段正文内容。", "body")]

    assert candidate(title, 1).kind == ElementKind.TITLE_METADATA
    assert candidate(tail, 1).kind == ElementKind.SIGNATURE_AGENCY
    body_result = candidate(body, 1)
    assert body_result.kind == ElementKind.BODY_PARAGRAPH
    assert "body_sentence_context" in {item.detail for item in body_result.evidence}


def test_attachment_mentions_note_and_page_title_are_independent():
    mention = [paragraph("前文内容较长。", "body"), paragraph("相关附件另行发送。", "attachment_note"), paragraph("后文内容较长。", "body")]
    note = [paragraph("正文结尾内容较长。", "body"), paragraph("附件：测试清单", "body"), paragraph("测试机关", "sign_org"), paragraph("2026年7月17日", "sign_date")]
    paged = [paragraph("正文结尾内容较长。", "body"), paragraph("附件1", "body", tokens=[InlineToken("page_break")]), paragraph("附件正文内容。", "body")]
    unpaged = [paragraph("正文结尾内容较长。", "body"), paragraph("附件1", "attachment_page_mark"), paragraph("附件正文内容。", "body")]

    assert candidate(mention, 1).kind == ElementKind.BODY_PARAGRAPH
    assert candidate(note, 1).kind == ElementKind.ATTACHMENT_NOTE_ITEM
    paged_result = candidate(paged, 1)
    assert paged_result.kind == ElementKind.ATTACHMENT_TITLE
    assert "preceded_by:real_page_boundary" in {item.detail for item in paged_result.evidence}
    unpaged_result = candidate(unpaged, 1)
    assert unpaged_result.confidence < 0.60
    assert "preceded_by:real_page_boundary" not in {item.detail for item in unpaged_result.evidence}
    assert "no_real_page_boundary" in {item.detail for item in unpaged_result.evidence}


def test_context_candidate_is_independent_from_structure_kind():
    paragraphs = [paragraph("标题", "title"), paragraph("正文内容较长。", "body")]
    structure = analyze_document_structure(DocumentData(paragraphs=paragraphs))
    original = validate_structure_context(structure, paragraphs).elements[1]
    wrong_element = replace(structure.elements[1], kind=ElementKind.SIGNATURE_DATE)
    changed_structure = replace(structure, elements=(structure.elements[0], wrong_element))
    changed = validate_structure_context(changed_structure, paragraphs).elements[1]

    assert original.context_kind == changed.context_kind == ElementKind.BODY_PARAGRAPH
    assert changed.structure_kind == ElementKind.SIGNATURE_DATE


def test_same_context_candidate_survives_block_change_but_reconciliation_changes():
    paragraphs = [paragraph("正文内容较长。", "body")]
    structure = analyze_document_structure(DocumentData(paragraphs=paragraphs))
    original = validate_structure_context(structure, paragraphs).elements[0]
    title_span = replace(structure.body.span, kind=BlockKind.TITLE)
    changed_structure = replace(structure, body=BodyBlock(title_span, title_span.elements))
    changed = validate_structure_context(changed_structure, paragraphs).elements[0]

    assert original.context_kind == changed.context_kind == ElementKind.BODY_PARAGRAPH
    assert original.final_kind == ElementKind.BODY_PARAGRAPH
    assert changed.status == ValidationStatus.CONFLICT
    assert changed.final_kind == ElementKind.UNKNOWN


def test_structure_context_disagreement_inside_allowed_block_is_provisional():
    paragraphs = [paragraph("公文标题", "title"), paragraph("2026年7月17日", "date_line"), paragraph("正文内容较长。", "body")]
    structure = analyze_document_structure(DocumentData(paragraphs=paragraphs))
    wrong = replace(structure.elements[1], kind=ElementKind.DOCUMENT_TITLE)
    changed_structure = replace(structure, elements=(structure.elements[0], wrong, structure.elements[2]))
    result = validate_structure_context(changed_structure, paragraphs).elements[1]

    assert result.structure_kind == ElementKind.DOCUMENT_TITLE
    assert result.context_kind == ElementKind.TITLE_METADATA
    assert result.status == ValidationStatus.PROVISIONAL
    assert "structure_context_kind_disagreement" in {item.detail for item in result.evidence}


def test_evidence_is_authentic_stable_and_does_not_include_text():
    paragraphs = [paragraph("前一段正文内容较长。", "body"), paragraph("相关附件另行发送。", "body"), paragraph("后一段正文内容较长。", "body")]
    first = candidate(paragraphs, 1)
    second = candidate(paragraphs, 1)
    assert first == second
    assert {item.source for item in first.evidence} <= {"block", "context", "style", "text", "structural"}
    assert "position:document_tail" not in {item.detail for item in first.evidence}
    assert "title_like_before" not in {item.detail for item in first.evidence}
    assert all(paragraphs[1].original_text not in item.detail for item in first.evidence)


def test_revalidate_recomputes_context_and_ignores_distant_text_change():
    paragraphs = [
        paragraph("第一段远处正文内容。", "body"), paragraph("第二段远处正文内容。", "body"),
        paragraph("第三段正文内容。", "body"), paragraph("目标正文内容较长。", "body"),
        paragraph("相邻正文内容较长。", "body"),
    ]
    structure = analyze_document_structure(DocumentData(paragraphs=paragraphs))
    validation = validate_structure_context(structure, paragraphs)
    target = next(item for item in validation.elements if item.source_index == 3)
    distant = deepcopy(paragraphs)
    distant[0].original_text = "远处内容已改变。"
    assert revalidate_element(target, structure, distant)


def test_revalidate_rejects_removed_page_boundary_and_signature_pair():
    paged = [paragraph("正文内容较长。", "body"), paragraph("附件1", "attachment_page_mark", tokens=[InlineToken("page_break")]), paragraph("附件正文内容。", "body")]
    paged_structure = analyze_document_structure(DocumentData(paragraphs=paged))
    paged_validation = validate_structure_context(paged_structure, paged)
    title = next(item for item in paged_validation.elements if item.context_kind == ElementKind.ATTACHMENT_TITLE)
    without_page = deepcopy(paged)
    without_page[1].inline_tokens = []
    assert not revalidate_element(title, paged_structure, without_page)

    signed = [paragraph("正文内容较长。", "body"), paragraph("测试机关", "sign_org"), paragraph("2026年7月17日", "sign_date")]
    signed_structure = analyze_document_structure(DocumentData(paragraphs=signed))
    signed_validation = validate_structure_context(signed_structure, signed)
    date = next(item for item in signed_validation.elements if item.context_kind == ElementKind.SIGNATURE_DATE)
    assert not revalidate_element(date, signed_structure, signed[1:])
