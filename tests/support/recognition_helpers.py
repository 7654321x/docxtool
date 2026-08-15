from types import SimpleNamespace

from docxtool.document.style_config import StyleRule


def _paragraph(text, type_id="body", index=0, **meta):
    numbering_prefix = meta.pop("numbering_prefix", "")
    segment_numbering_features = meta.pop("segment_numbering_features", numbering_prefix)
    bold_char_ratio = meta.pop("bold_char_ratio", 0.0)
    return SimpleNamespace(
        text=text,
        original_text=text,
        type_id=type_id,
        features=SimpleNamespace(
            paragraph_index=index,
            alignment=meta.pop("alignment", ""),
            style_name=meta.pop("style_name", ""),
            bold=bold_char_ratio >= 0.65,
            bold_char_ratio=bold_char_ratio,
            font_size_pt=None,
            numbering_prefix=numbering_prefix,
            segment_numbering_features=segment_numbering_features,
        ),
        meta=meta,
    )


def _document(*paragraphs, mode="NORMAL"):
    return SimpleNamespace(paragraphs=list(paragraphs), doc_mode=mode)


def _rules():
    return [StyleRule.default_for_row(index) for index in range(10)]
