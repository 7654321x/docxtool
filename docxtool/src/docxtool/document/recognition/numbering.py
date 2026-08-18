"""标题编号和 Word 编号事实到识别候选的映射。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any, Callable, Optional, Tuple

from docxtool.document.configuration.models import NB_FIXED, NB_SUFFIXES

HEADING_PATTERNS = (
    (re.compile(r'^[一二三四五六七八九十百]+[、.．]+'), "heading1"),
    (re.compile(r'^[（\(][一二三四五六七八九十百]+[）\)]'), "heading2"),
    (re.compile(r'^\d+[.．]'), "heading3"),
    (re.compile(r'^[（\(]\d+[）\)]'), "heading4"),
)

_NB_RE = re.compile(rf'[一二三四五六七八九十]+(?:{"|".join(NB_SUFFIXES)})')
_NB_FIXED_RE = re.compile(rf'^(?:{"|".join(map(re.escape, NB_FIXED))})') if NB_FIXED else None


def find_numbered_bold_pos(text: str, *, normalize_text: Optional[Callable[[str], str]] = None) -> int:
    """传入段落文本，返回“一是/一要/比如”等引导句首次位置；未命中返回 -1。"""
    value = normalize_text(text) if normalize_text else (text or "")
    if _NB_FIXED_RE:
        fixed_match = _NB_FIXED_RE.search(value)
        if fixed_match:
            return fixed_match.start()
    match = _NB_RE.search(value)
    return match.start() if match else -1


def looks_like_damaged_heading(text: str) -> bool:
    """传入段落文本，返回是否具备 OCR 或标点损坏后的中文标题编号形态。"""
    value = (text or "").strip()
    if len(value) > 30 or re.search(r'[。；：]', value[:10]):
        return False
    if re.match(r'^([一二三四五六七八九十百]+)[，,、\s]', value):
        return True
    if re.match(r'^[）\)][一二三四五六七八九十百]+', value):
        return True
    if re.match(r'^[（\(][一二三四五六七八九十百]+', value) and len(value) <= 15:
        return True
    return False


def match_numbering(
    text: str,
    *,
    normalize_text: Optional[Callable[[str], str]] = None,
    contains_colon: Optional[Callable[[str], bool]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """传入段落文本，返回标题层级和原始编号前缀；未命中返回 `(None, None)`。"""
    value = normalize_text(text) if normalize_text else (text or "")
    colon_check = contains_colon or (lambda candidate: "：" in candidate or ":" in candidate)
    for pattern, type_id in HEADING_PATTERNS:
        match = pattern.match(value)
        if match:
            if type_id == "heading4" and colon_check(value):
                continue
            return type_id, match.group(0)
    return None, None


def match_style_or_level(
    text: str,
    features: Any,
    *,
    normalize_text: Optional[Callable[[str], str]] = None,
) -> Tuple[Optional[str], Optional[str]]:
    """传入段落文本和特征，返回 Word 样式/列表推导的标题类型和前缀。"""
    if not features:
        return None, None
    prefix = getattr(features, "numbering_prefix", "") or ""
    native = getattr(features, "native_numbering", None)
    if find_numbered_bold_pos(text, normalize_text=normalize_text) == 0:
        return None, None
    if prefix.startswith("@lvl_0") and len(text) > 25 and re.search(r'[、，；]', text):
        return None, None
    native_level = native_numbering_heading_level(native)
    if native_level is not None and (
        len((text or "").strip()) > 40
        or (text or "").rstrip().endswith(("。", "！", "？", ".", "!", "?"))
        or "：" in (text or "")
        or ":" in (text or "")
    ):
        return None, None
    if native_level is not None:
        return f"heading{native_level}", ""
    if native is None and prefix.startswith("@lvl_"):
        try:
            level = int(prefix[5:])
            return f"heading{min(level + 2, 4)}", ""
        except ValueError:
            pass
    if prefix.startswith("@style_"):
        return prefix[7:], ""
    return None, None


def native_numbering_heading_level(native: Any) -> int | None:
    """根据有效 OOXML 编号模板返回公文标题层级。"""
    if native is None:
        return None
    template = re.sub(r"\s+", "", str(getattr(native, "lvl_text", "") or ""))
    num_fmt = str(getattr(native, "num_fmt", "") or "")
    if not template:
        return None
    placeholder = rf"%{int(getattr(native, 'ilvl', 0)) + 1}"
    chinese_format = num_fmt in {
        "chineseCounting", "chineseCountingThousand", "ideographTraditional",
    }
    decimal_format = num_fmt in {"decimal", "decimalZero"}
    if chinese_format and re.fullmatch(rf"{re.escape(placeholder)}[、.．]", template):
        return 1
    if chinese_format and re.fullmatch(
        rf"[（(]{re.escape(placeholder)}[）)]", template
    ):
        return 2
    if decimal_format and re.fullmatch(rf"{re.escape(placeholder)}[.．]", template):
        return 3
    if decimal_format and re.fullmatch(
        rf"[（(]{re.escape(placeholder)}[）)]", template
    ):
        return 4
    return None


def resolve_native_numbering_levels(features: list[Any]) -> list[Any]:
    """用模板、Word 标题样式和同编号族上下文补全原生编号标题层级。"""
    resolved = list(features)
    family_levels: dict[tuple[str, int], tuple[int, str]] = {}
    body_list_positions = _native_body_list_positions(resolved)

    for index, item in enumerate(resolved):
        if index in body_list_positions:
            resolved[index] = replace(item, native_numbering_body_list=True)
            continue
        if not _native_heading_eligible(item):
            continue
        level = item.native_numbering_template_level
        source = "template" if level is not None else ""
        if level is None:
            level, source = _native_heading_anchor(item)
        if level is None:
            continue
        resolved[index] = _with_native_heading_level(item, level, source)
        family_levels[(item.native_numbering_family, item.native_numbering_ilvl)] = (
            level,
            source,
        )

    for index, item in enumerate(resolved):
        if index in body_list_positions:
            continue
        if item.native_numbering_level is not None or not _native_heading_eligible(item):
            continue
        family_key = (item.native_numbering_family, item.native_numbering_ilvl)
        family_match = family_levels.get(family_key)
        if family_match is not None:
            resolved[index] = _with_native_heading_level(
                item, family_match[0], "family-sibling"
            )
            continue
        relative = _relative_family_level(item, family_levels)
        if relative is not None:
            resolved[index] = _with_native_heading_level(
                item, relative, "family-context"
            )
    return resolved


def _native_body_list_positions(features: list[Any]) -> set[int]:
    positions: set[int] = set()
    active_family = ""
    for index, item in enumerate(features):
        if not item.native_numbering_present:
            active_family = ""
            continue
        previous = features[index - 1] if index else None
        if previous is not None and (
            previous.colon_at_end or previous.colon_explanatory_body
        ):
            active_family = item.native_numbering_family
        if active_family and item.native_numbering_family == active_family:
            positions.add(index)
        elif active_family:
            active_family = ""
    return positions


def _native_heading_eligible(features: Any) -> bool:
    native_template_level = features.native_numbering_template_level
    colon_inline_heading2 = bool(
        native_template_level == 2
        and features.colon_label
        and not features.colon_at_end
        and bool(features.colon_value and features.colon_value.strip())
    )
    period_position = features.normalized_text.find("。")
    period_inline_heading2 = bool(
        native_template_level == 2
        and period_position >= 0
        and len(features.normalized_text[period_position + 1:].strip()) >= 5
    )
    inline_heading2 = colon_inline_heading2 or period_inline_heading2
    return bool(
        features.native_numbering_present
        and features.native_numbering_family
        and features.native_numbering_ilvl is not None
        and (inline_heading2 or features.text_length <= 40)
        and (inline_heading2 or not features.ends_with_sentence_punctuation)
        and not features.date_match
        and not features.attachment_note_match
        and not features.recipient_match
        and (inline_heading2 or not features.key_value_label)
        and not features.colon_at_end
        and (inline_heading2 or not features.colon_explanatory_body)
        and not re.fullmatch(
            r"附件[0-9一二三四五六七八九十百千]*",
            features.compact_text,
        )
    )


def _native_heading_anchor(features: Any) -> tuple[int | None, str]:
    style = re.sub(r"\s+", " ", str(features.style_name or "").strip().casefold())
    style_match = re.fullmatch(r"(?:heading|标题)\s*([1-4])", style)
    if style_match is not None:
        return int(style_match.group(1)), "word-style"
    legacy_match = re.fullmatch(r"heading([1-4])", str(features.legacy_type_id or ""))
    if legacy_match is not None:
        return int(legacy_match.group(1)), "legacy"
    return None, ""


def _relative_family_level(
    features: Any,
    family_levels: dict[tuple[str, int], tuple[int, str]],
) -> int | None:
    candidates = [
        (abs(features.native_numbering_ilvl - ilvl), level, ilvl)
        for (family, ilvl), (level, _source) in family_levels.items()
        if family == features.native_numbering_family
    ]
    if not candidates:
        return None
    _distance, anchor_level, anchor_ilvl = min(candidates)
    inferred = anchor_level + features.native_numbering_ilvl - anchor_ilvl
    return inferred if 1 <= inferred <= 4 else None


def _with_native_heading_level(features: Any, level: int, source: str) -> Any:
    return replace(
        features,
        numbering_level=features.numbering_level or level,
        heading_shape_level=features.heading_shape_level or level,
        heading_semantic_score=max(features.heading_semantic_score, 0.8),
        native_numbering_level=level,
        native_numbering_level_source=source,
        numbered_heading2_colon_inline_body=(
            level == 2
            and bool(features.colon_label)
            and not features.colon_at_end
            and bool(features.colon_value and features.colon_value.strip())
        ),
        numbered_heading2_period_inline_body=(
            level == 2
            and "。" in features.normalized_text
            and len(features.normalized_text.split("。", 1)[1].strip()) >= 5
        ),
    )


def legacy_numbered_heading_score(
    text: str,
    type_id: str | None,
    prefix: str | None,
    *,
    contains_colon: bool,
) -> int:
    """传入编号类型、前缀和冒号事实，返回旧 importer 编号标题候选分。"""
    if type_id == "heading1":
        return 100
    if type_id == "heading2":
        return 100
    if type_id == "heading3":
        return 90
    if type_id == "heading4":
        return 0 if contains_colon else 90
    return 0
