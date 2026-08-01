from docxtool.document.importer import (
    ParagraphFeatures,
    _set_source_locator,
    _source_line_spans,
    _trim_source_span,
)
from docxtool.document.segmentation import (
    set_source_locator,
    source_line_spans,
    trim_source_span,
)


def test_importer_reexports_segmentation_source_helpers():
    """旧 importer 私有入口传入无业务数据时，返回的函数对象应指向 segmentation 实现。"""
    assert _set_source_locator is set_source_locator
    assert _source_line_spans is source_line_spans
    assert _trim_source_span is trim_source_span


def test_set_source_locator_confirms_raw_and_canonical_ranges():
    """精确范围传入父子段特征后，返回值应写入 confirmed locator 字段。"""
    parent = ParagraphFeatures(
        source_physical_paragraph_index=3,
        source_physical_text="  标题\n正文  ",
    )
    child = ParagraphFeatures()

    set_source_locator(child, parent, 2, 4)

    assert child.source_locator_status == "confirmed"
    assert child.source_physical_paragraph_index == 3
    assert child.source_fragment_text == "标题"
    assert child.source_start_utf16 is not None
    assert child.source_end_utf16 is not None
