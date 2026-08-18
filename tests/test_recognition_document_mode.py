from __future__ import annotations

import pytest

from docxtool.document.recognition.document_mode import (
    has_doc_type_keyword,
    has_title_keyword,
)
from docxtool.document.recognition.features import (
    BlockKind,
    DocumentBlock,
    detect_mode,
    extract_features,
)
from docxtool.document.recognition.model import DocumentMode


def _mode_for_title(title: str) -> DocumentMode:
    feature = extract_features(
        DocumentBlock(
            index=0,
            kind=BlockKind.PARAGRAPH,
            text=title,
            style_name="Title",
            alignment="center",
            bold=True,
            font_size_pt=22,
        )
    )
    return detect_mode([feature]).mode


def test_title_keyword_keeps_legacy_title_scorer_evidence() -> None:
    assert has_title_keyword("2025年度民主生活会对照检查材料")
    assert has_title_keyword("在会议上的讲话稿")
    assert not has_title_keyword("2025年10月15日")


def test_doc_type_keyword_keeps_role_name_support_evidence() -> None:
    assert has_doc_type_keyword("关于重点工作的通知")
    assert has_doc_type_keyword("年度工作总结")
    assert not has_doc_type_keyword("普通正文段落")


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("年度工作报告", DocumentMode.REPORT),
        ("政府工作报告", DocumentMode.REPORT),
        ("政协常委会工作报告", DocumentMode.REPORT),
        ("法院工作报告", DocumentMode.REPORT),
        ("检察院工作报告", DocumentMode.REPORT),
        ("年度工作回顾", DocumentMode.REPORT),
        ("情况报告", DocumentMode.UNKNOWN),
        ("调研报告", DocumentMode.UNKNOWN),
        ("述职报告", DocumentMode.UNKNOWN),
        ("工作总结", DocumentMode.UNKNOWN),
        ("会议通知", DocumentMode.NOTICE),
        ("实施方案", DocumentMode.PLAN),
    ],
)
def test_detect_mode_is_the_only_document_mode_authority(
    title: str, expected: DocumentMode
) -> None:
    assert _mode_for_title(title) is expected
