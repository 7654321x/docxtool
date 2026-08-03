"""Shared structural evidence for front-matter role and person lines."""

from __future__ import annotations

import re


ROLE_HINT_RE = re.compile(
    r"(?:书记|主任|主席|部长|局长|处长|科长|司长|厅长|市长|县长|区长|"
    r"镇长|乡长|院长|校长|政委|组长|队长|秘书长|委员|常委|负责人|"
    r"经理|总监|工程师|专员|督导员|顾问|总会计师|总经济师|同志|代表)"
)
_PERSON_NAME_PATTERN = r"(?:[\u4e00-\u9fff×X]{2,4}|[\u4e00-\u9fff×X]{1,2}·[\u4e00-\u9fff×X]{1,2})"
PERSON_NAME_RE = re.compile(_PERSON_NAME_PATTERN + r"$")
NON_PERSON_SUFFIX_RE = re.compile(
    r"(?:报告|总结|方案|计划|意见|通知|办法|材料|讲话|发言|纪要|决定|"
    r"决议|规定|制度|会议|工作)$"
)
_ROLE_CONNECTION_SUFFIX_RE = re.compile(r"(?:[、，,/／&]|兼|及|和|与)+$")
_SPACED_NAME_RE = re.compile(
    r"(?P<separator>[\s\u3000]+)(?P<name>" + _PERSON_NAME_PATTERN + r")$"
)


def has_role_hint(text: str) -> bool:
    """Return whether text contains a generic personal role expression."""
    return bool(ROLE_HINT_RE.search(re.sub(r"\s+", "", text or "")))


def is_person_name_suffix(text: str) -> bool:
    """Return whether a short suffix is name-shaped rather than document-shaped."""
    value = re.sub(r"\s+", "", text or "")
    return bool(PERSON_NAME_RE.fullmatch(value) and not NON_PERSON_SUFFIX_RE.search(value))


def _role_expression_ends_at_boundary(value: str) -> bool:
    role_expression = _ROLE_CONNECTION_SUFFIX_RE.sub("", value.rstrip())
    matches = list(ROLE_HINT_RE.finditer(role_expression))
    return bool(matches and matches[-1].end() == len(role_expression))


def parse_role_name_shape(text: str) -> tuple[str, str] | None:
    """Split a role/name line only when the role ends at the name boundary."""
    value = (text or "").strip()
    if not value:
        return None

    spaced = _SPACED_NAME_RE.search(value)
    if spaced is not None:
        role_expression = value[:spaced.start("separator")].rstrip()
        person_name = spaced.group("name")
        if (
            _role_expression_ends_at_boundary(role_expression)
            and is_person_name_suffix(person_name)
        ):
            return role_expression, person_name
        return None

    compact = re.sub(r"\s+", "", value)
    for start in range(max(1, len(compact) - 5), len(compact)):
        person_name = compact[start:]
        role_expression = compact[:start]
        if (
            is_person_name_suffix(person_name)
            and _role_expression_ends_at_boundary(role_expression)
        ):
            return role_expression, person_name
    return None


def has_compact_role_name_shape(text: str) -> bool:
    """Return whether a role is immediately followed by a name-shaped suffix."""
    value = text or ""
    return not bool(re.search(r"\s", value)) and parse_role_name_shape(value) is not None
