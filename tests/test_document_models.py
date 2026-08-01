from docxtool.document.importer import (
    DocumentData as ImporterDocumentData,
    InlineToken as ImporterInlineToken,
    ParagraphData as ImporterParagraphData,
    ParagraphFeatures as ImporterParagraphFeatures,
    SourceRun as ImporterSourceRun,
)
from docxtool.document.models import (
    DocumentData,
    InlineToken,
    ParagraphData,
    ParagraphFeatures,
    SourceRun,
)


def test_importer_reexports_document_models():
    """旧 importer 路径传入无数据，返回的新模型对象应与 models 包导出保持同一身份。"""
    assert ImporterDocumentData is DocumentData
    assert ImporterInlineToken is InlineToken
    assert ImporterParagraphData is ParagraphData
    assert ImporterParagraphFeatures is ParagraphFeatures
    assert ImporterSourceRun is SourceRun


def test_document_model_defaults_match_importer_contract():
    """默认构造不传入业务数据时，返回值应保持旧 importer 模型的默认字段语义。"""
    features = ParagraphFeatures()
    paragraph = ParagraphData("正文", "body", "正文", features)
    data = DocumentData(paragraphs=[paragraph])

    assert features.source_locator_status == "unresolved"
    assert features.segment_count == 1
    assert paragraph.meta == {}
    assert paragraph.inline_tokens == []
    assert data.processing_strategy == "normalize"
    assert data.recognition_mode == "authoritative"
