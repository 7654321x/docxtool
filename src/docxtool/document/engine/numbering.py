"""Text numbering detection and conservative normalization helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum


class NumberingStyle(str, Enum):
    CHINESE_DUN = "chinese_dun"
    CHINESE_PAREN = "chinese_paren"
    DIGIT_DOT = "digit_dot"
    DIGIT_DUN = "digit_dun"
    DIGIT_PAREN = "digit_paren"
    CIRCLED = "circled"


@dataclass(frozen=True)
class NumberingToken:
    raw: str
    value: int
    level: int
    style: NumberingStyle
    body: str
    confidence: float


@dataclass(frozen=True)
class NumberingIssue:
    index: int
    level: int
    expected: int
    actual: int
    kind: str


@dataclass(frozen=True)
class NumberingNormalization:
    text: str
    changed: bool
    token: NumberingToken | None
    reason: str = ""


_CN_DIGITS = "一二三四五六七八九十百千万零〇"
_CIRCLED = "①②③④⑤⑥⑦⑧⑨⑩"
_CIRCLED_TO_INT = {char: index for index, char in enumerate(_CIRCLED, start=1)}
_INT_TO_CIRCLED = {index: char for char, index in _CIRCLED_TO_INT.items()}
_TOKEN_RE = re.compile(
    rf"^\s*(?P<token>"
    rf"(?P<chinese_dun>[{_CN_DIGITS}]{{1,6}})、|"
    rf"(?P<chinese_paren>[（(][{_CN_DIGITS}]{{1,6}}[）)])|"
    rf"(?P<digit_dot>\d{{1,3}}[.．])|"
    rf"(?P<digit_dun>\d{{1,3}}、)|"
    rf"(?P<digit_paren>[（(]\d{{1,3}}[）)])|"
    rf"(?P<circled>[{_CIRCLED}])"
    rf")\s*(?P<body>.*)$"
)
_DATE_PREFIX_RE = re.compile(r"^\s*(?:19|20)\d{2}[.．、年-]")
_LAW_RE = re.compile(r"^\s*第[一二三四五六七八九十百千万0-9]+条")
_ATTACHMENT_RE = re.compile(r"^\s*附件\s*([0-9一二三四五六七八九十]+|[:：])")
_LEVEL_BY_STYLE = {
    NumberingStyle.CHINESE_DUN: 1,
    NumberingStyle.CHINESE_PAREN: 2,
    NumberingStyle.DIGIT_DOT: 3,
    NumberingStyle.DIGIT_DUN: 3,
    NumberingStyle.DIGIT_PAREN: 4,
    NumberingStyle.CIRCLED: 4,
}
_CANONICAL_STYLE = {
    1: NumberingStyle.CHINESE_DUN,
    2: NumberingStyle.CHINESE_PAREN,
    3: NumberingStyle.DIGIT_DOT,
    4: NumberingStyle.DIGIT_PAREN,
}


def detect_numbering_token(text: str) -> NumberingToken | None:
    """Detect a leading text numbering token with date/law/attachment protection."""

    if _is_protected_text(text):
        return None
    match = _TOKEN_RE.match(text or "")
    if not match:
        return None

    style = _matched_style(match)
    raw = match.group("token")
    value = _token_value(raw, style)
    body = match.group("body") or ""
    if value is None or value <= 0:
        return None
    confidence = 0.94 if body and not _is_protected_body(body) else 0.62
    return NumberingToken(
        raw=raw,
        value=value,
        level=_LEVEL_BY_STYLE[style],
        style=style,
        body=body,
        confidence=confidence,
    )


def normalize_numbering_text(text: str, *, safe: bool = True) -> NumberingNormalization:
    """Normalize the leading numbering token, preserving protected text."""

    token = detect_numbering_token(text)
    if token is None:
        return NumberingNormalization(text=text, changed=False, token=None, reason="no_text_token")
    if safe and token.confidence < 0.9:
        return NumberingNormalization(text=text, changed=False, token=token, reason="low_confidence")

    canonical = render_numbering_token(token.value, _CANONICAL_STYLE[token.level])
    normalized = canonical + token.body.lstrip()
    if normalized == text:
        return NumberingNormalization(text=text, changed=False, token=token, reason="already_normalized")
    return NumberingNormalization(
        text=normalized,
        changed=True,
        token=token,
        reason=f"{token.style.value}_to_{_CANONICAL_STYLE[token.level].value}",
    )


def normalize_paragraph_numbering_run(paragraph: object, *, safe: bool = True) -> NumberingNormalization:
    """Normalize a paragraph's first text run without touching Word native numPr."""

    text = str(getattr(paragraph, "text", "") or "")
    if has_native_numbering(paragraph):
        return NumberingNormalization(text=text, changed=False, token=None, reason="native_numbering")

    result = normalize_numbering_text(text, safe=safe)
    if not result.changed:
        return result
    runs = list(getattr(paragraph, "runs", []) or [])
    if not runs:
        return NumberingNormalization(text=text, changed=False, token=result.token, reason="no_runs")

    remaining = result.text
    for run in runs:
        current = str(getattr(run, "text", "") or "")
        if not current:
            continue
        run.text = remaining[: len(current)]
        remaining = remaining[len(current) :]
        if not remaining:
            break
    if remaining:
        runs[-1].text = str(getattr(runs[-1], "text", "") or "") + remaining
    return result


def analyze_numbering_sequence(texts: list[str]) -> list[NumberingIssue]:
    """Report level-local gaps and mixed styles in document order."""

    expected: dict[int, int] = {}
    style_by_level: dict[int, NumberingStyle] = {}
    issues: list[NumberingIssue] = []
    for index, text in enumerate(texts):
        token = detect_numbering_token(text)
        if token is None:
            continue
        previous_style = style_by_level.setdefault(token.level, token.style)
        if token.style != previous_style:
            issues.append(NumberingIssue(index=index, level=token.level, expected=token.value, actual=token.value, kind="mixed_style"))
        expected_value = expected.get(token.level, 1)
        if token.value != expected_value:
            issues.append(NumberingIssue(index=index, level=token.level, expected=expected_value, actual=token.value, kind="gap"))
        expected[token.level] = token.value + 1
        for child_level in range(token.level + 1, 5):
            expected.pop(child_level, None)
            style_by_level.pop(child_level, None)
    return issues


def render_numbering_token(value: int, style: NumberingStyle) -> str:
    if style == NumberingStyle.CHINESE_DUN:
        return f"{_int_to_cn(value)}、"
    if style == NumberingStyle.CHINESE_PAREN:
        return f"（{_int_to_cn(value)}）"
    if style == NumberingStyle.DIGIT_DOT:
        return f"{value}."
    if style == NumberingStyle.DIGIT_DUN:
        return f"{value}、"
    if style == NumberingStyle.DIGIT_PAREN:
        return f"（{value}）"
    if style == NumberingStyle.CIRCLED:
        return _INT_TO_CIRCLED.get(value, str(value))
    raise ValueError(f"Unsupported numbering style: {style}")


def has_native_numbering(paragraph: object) -> bool:
    if bool(getattr(paragraph, "native_numbering", False)):
        return True
    element = getattr(paragraph, "_element", None)
    if element is None:
        return False
    try:
        from docx.oxml.ns import qn

        ppr = element.find(qn("w:pPr"))
        return ppr is not None and ppr.find(qn("w:numPr")) is not None
    except Exception:
        return False


def _matched_style(match: re.Match[str]) -> NumberingStyle:
    for style in NumberingStyle:
        if match.group(style.value):
            return style
    raise ValueError("numbering style was not captured")


def _token_value(raw: str, style: NumberingStyle) -> int | None:
    if style == NumberingStyle.CIRCLED:
        return _CIRCLED_TO_INT.get(raw)
    if style in {NumberingStyle.DIGIT_DOT, NumberingStyle.DIGIT_DUN, NumberingStyle.DIGIT_PAREN}:
        digits = re.sub(r"\D", "", raw)
        return int(digits) if digits else None
    return _cn_to_int(raw.strip("（()）、"))


def _is_protected_text(text: str) -> bool:
    stripped = text or ""
    return bool(_DATE_PREFIX_RE.match(stripped) or _LAW_RE.match(stripped) or _ATTACHMENT_RE.match(stripped))


def _is_protected_body(body: str) -> bool:
    return bool(_LAW_RE.match(body) or re.match(r"^\d{1,2}月\d{1,2}日", body))


def _cn_to_int(value: str) -> int | None:
    digits = {"零": 0, "〇": 0, "一": 1, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    if not value:
        return None
    if value in digits:
        return digits[value]
    if value == "十":
        return 10
    if "十" in value:
        left, _, right = value.partition("十")
        tens = digits.get(left, 1) if left else 1
        ones = digits.get(right, 0) if right else 0
        return tens * 10 + ones
    total = 0
    unit_map = {"百": 100, "千": 1000, "万": 10000}
    current = 0
    for char in value:
        if char in digits:
            current = digits[char]
        elif char in unit_map:
            total += (current or 1) * unit_map[char]
            current = 0
        else:
            return None
    return total + current if total else None


def _int_to_cn(value: int) -> str:
    if value <= 0 or value > 99:
        return str(value)
    ones = ["零", "一", "二", "三", "四", "五", "六", "七", "八", "九"]
    if value < 10:
        return ones[value]
    if value == 10:
        return "十"
    if value < 20:
        return "十" + ones[value % 10]
    tens, rest = divmod(value, 10)
    return ones[tens] + "十" + (ones[rest] if rest else "")
