from docxtool.document.importer import (
    ParagraphFeatures,
    SourceRun,
    _set_source_locator,
    _source_line_spans,
    _trim_source_span,
)
from docxtool.document.segmentation import (
    assign_segment_ordinals,
    build_segment_features,
    build_unresolved_empty_segment_features,
    set_source_locator,
    source_line_spans,
    trim_source_span,
)
from docxtool.document.segmentation.source_locator import build_physical_source_features
from docxtool.document.source_tape import canonicalize_text


def test_importer_reexports_segmentation_source_helpers():
    """旧 importer 私有入口传入无业务数据时，返回的函数对象应指向 segmentation 实现。"""
    assert _set_source_locator is set_source_locator
    assert _source_line_spans is source_line_spans
    assert _trim_source_span is trim_source_span


def test_build_physical_source_features_preserves_initial_locator_contract():
    """原始物理段文本和序号传入后，应返回与旧导入层一致的初始 locator 字段。"""
    raw_text = "标题\r\n正文\U00020000"

    features = build_physical_source_features(raw_text, 7)

    assert features.text == raw_text.strip()
    assert features.paragraph_index == 7
    assert features.source_physical_paragraph_index == 7
    assert features.source_physical_text == raw_text
    assert features.source_start_utf16 == 0
    assert features.source_end_utf16 == len(raw_text.encode("utf-16-le")) // 2
    assert features.source_canonical_text == canonicalize_text(raw_text)
    assert features.source_canonical_start_utf16 == 0
    assert features.source_canonical_end_utf16 == (
        len(features.source_canonical_text.encode("utf-16-le")) // 2
    )
    assert features.source_fragment_text == raw_text
    assert features.source_canonical_fragment_text == features.source_canonical_text
    assert features.source_locator_status == "confirmed"
    assert features.source_locator_evidence == ("PHYSICAL_PARAGRAPH_EXTRACTED",)
    assert features.source_locator_warnings == ()


def test_build_physical_source_features_keeps_empty_source_unresolved():
    """空物理段传入后，应保持旧有 unresolved 状态和警告。"""
    features = build_physical_source_features("", 2)

    assert features.text == ""
    assert features.source_locator_status == "unresolved"
    assert features.source_locator_evidence == ()
    assert features.source_locator_warnings == ("SOURCE_RANGE_UNRESOLVED",)


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


def test_build_segment_features_preserves_locator_format_and_callback_flags():
    """父段特征和范围传入后，应返回带定位、格式和回调标记的子段特征。"""
    parent = ParagraphFeatures(
        font_name="仿宋_GB2312",
        font_size_pt=16.0,
        bold=False,
        alignment="left",
        style_name="正文",
        numbering_prefix="",
        source_physical_paragraph_index=5,
        source_physical_text="标题正文",
        source_run_spans=(
            SourceRun(
                start=0,
                end=2,
                font_name="黑体",
                east_asia_font_name="黑体",
                ascii_font_name="Arial",
                font_size_pt=16.0,
                bold=True,
                italic=False,
                underline=False,
                explicit=True,
                inherited=False,
                known=True,
                format_sources=("direct_run",),
            ),
        ),
    )

    child = build_segment_features(
        parent,
        0,
        2,
        paragraph_index=9,
        is_new_line=True,
        inline_lead_bold_func=lambda source, start, end, features: source[start:end] == "标题",
    )

    assert child.paragraph_index == 9
    assert child.is_new_line is True
    assert child.source_locator_status == "confirmed"
    assert child.source_fragment_text == "标题"
    assert child.segment_font_name == "黑体"
    assert child.segment_bold_char_ratio == 1.0
    assert child.inline_lead_bold is True


def test_assign_segment_ordinals_groups_by_physical_paragraph():
    """多个逻辑段特征传入后，应按物理段分别写入顺序号和总数。"""
    first = ParagraphFeatures(source_physical_paragraph_index=1)
    second = ParagraphFeatures(source_physical_paragraph_index=1)
    other = ParagraphFeatures(source_physical_paragraph_index=2)
    unresolved = ParagraphFeatures(source_physical_paragraph_index=None)

    assign_segment_ordinals([first, second, other, unresolved])

    assert (first.segment_index, first.segment_count) == (0, 2)
    assert (second.segment_index, second.segment_count) == (1, 2)
    assert (other.segment_index, other.segment_count) == (0, 1)
    assert unresolved.segment_index == 0
    assert unresolved.segment_count == 1


def test_unresolved_empty_segment_features_keep_physical_anchor():
    """空可见文本段传入父特征后，应保留物理锚点并标记未解析范围。"""
    parent = ParagraphFeatures(
        font_name="仿宋_GB2312",
        font_size_pt=16.0,
        bold=False,
        alignment="center",
        style_name="Normal",
        numbering_prefix="",
        source_physical_paragraph_index=8,
        source_physical_text="",
    )

    child = build_unresolved_empty_segment_features(parent, paragraph_index=3)

    assert child.paragraph_index == 3
    assert child.source_physical_paragraph_index == 8
    assert child.source_physical_text == ""
    assert child.source_locator_warnings == ("SOURCE_RANGE_UNRESOLVED",)
    assert child.font_name == "仿宋_GB2312"
