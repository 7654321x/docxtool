"""Host-neutral verification of a recognition plan against local text."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Optional, Sequence, Tuple

from docxtool.document.source_tape import SourceTape, canonicalize_text

from .models import (
    BoundRecognitionBlock,
    HostParagraph,
    HostSnapshot,
    RecognitionBinding,
    RecognitionBlock,
    RecognitionPlan,
)


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class _HostText:
    paragraph: HostParagraph
    tape: SourceTape
    raw_hash: str
    canonical_hash: str


@dataclass(frozen=True)
class _PhysicalGroup:
    physical_index: int
    raw_hash: str
    canonical_hash: str
    blocks: Tuple[RecognitionBlock, ...]


def _coerce_snapshot(value: HostSnapshot | Mapping[str, Any]) -> HostSnapshot:
    if isinstance(value, HostSnapshot):
        return value
    if not isinstance(value, Mapping):
        raise TypeError("host_snapshot 必须为 HostSnapshot 或 JSON 对象")
    paragraphs_value = value.get("paragraphs")
    if not isinstance(paragraphs_value, Sequence) or isinstance(paragraphs_value, (str, bytes)):
        raise ValueError("host_snapshot.paragraphs 必须为段落数组")
    paragraphs = []
    for ordinal, item in enumerate(paragraphs_value):
        if isinstance(item, HostParagraph):
            paragraphs.append(item)
            continue
        if not isinstance(item, Mapping) or not isinstance(item.get("raw_text"), str):
            raise ValueError("每个 host paragraph 必须包含 raw_text 字符串")
        index = item.get("host_paragraph_index", ordinal)
        if not isinstance(index, int) or index < 0:
            raise ValueError("host_paragraph_index 必须为非负整数")
        paragraphs.append(HostParagraph(
            host_paragraph_index=index,
            raw_text=item["raw_text"],
            story_type=str(item.get("story_type", "main") or "main"),
            is_in_table=bool(item.get("is_in_table", False)),
        ))
    host_type = value.get("host_type", "unknown")
    if not isinstance(host_type, str) or not host_type:
        raise ValueError("host_snapshot.host_type 必须为非空字符串")
    identity = value.get("document_identity")
    return HostSnapshot(
        host_type=host_type,
        paragraphs=tuple(paragraphs),
        document_identity=str(identity) if identity is not None else None,
    )


def _physical_groups(plan: RecognitionPlan) -> Tuple[_PhysicalGroup, ...]:
    grouped = {}
    for block in plan.blocks:
        if block.physical_paragraph_index is None:
            continue
        grouped.setdefault(block.physical_paragraph_index, []).append(block)
    result = []
    for physical_index in sorted(grouped):
        blocks = tuple(sorted(grouped[physical_index], key=lambda item: (item.segment_index, item.block_index)))
        result.append(_PhysicalGroup(
            physical_index=physical_index,
            raw_hash=blocks[0].physical_text_sha256,
            canonical_hash=blocks[0].physical_canonical_text_sha256,
            blocks=blocks,
        ))
    return tuple(result)


def _alignment_score(group: _PhysicalGroup, host: _HostText) -> int:
    if group.raw_hash and group.raw_hash == host.raw_hash:
        return 100
    if group.canonical_hash and group.canonical_hash == host.canonical_hash:
        return 80
    return 0


def _align_groups(groups: Sequence[_PhysicalGroup], hosts: Sequence[_HostText]) -> tuple[dict[int, tuple[int, int]], bool]:
    """Return a monotonic exact-text alignment and whether it is unique.

    The score only admits raw or canonical full-paragraph equality.  A fuzzy
    result is intentionally not generated, because callers must not format an
    ambiguous host document automatically.
    """
    rows, cols = len(groups), len(hosts)
    scores = [[0] * (cols + 1) for _ in range(rows + 1)]
    ways = [[0] * (cols + 1) for _ in range(rows + 1)]
    previous = [[None] * (cols + 1) for _ in range(rows + 1)]
    ways[0][0] = 1
    for row in range(rows + 1):
        for col in range(cols + 1):
            if row == 0 and col == 0:
                continue
            options = []
            if row:
                options.append((scores[row - 1][col], ways[row - 1][col], (row - 1, col, "skip_source")))
            if col:
                options.append((scores[row][col - 1], ways[row][col - 1], (row, col - 1, "skip_host")))
            if row and col:
                match = _alignment_score(groups[row - 1], hosts[col - 1])
                if match:
                    options.append((scores[row - 1][col - 1] + match, ways[row - 1][col - 1], (row - 1, col - 1, "match")))
            best = max(value[0] for value in options)
            tied = [value for value in options if value[0] == best]
            scores[row][col] = best
            ways[row][col] = min(2, sum(value[1] for value in tied))
            # Prefer a match for deterministic diagnostics, but only a unique
            # path can ever be confirmed below.
            previous[row][col] = next((value[2] for value in tied if value[2][2] == "match"), tied[0][2])

    matches = {}
    row, col = rows, cols
    while row or col:
        item = previous[row][col]
        if item is None:
            break
        prior_row, prior_col, action = item
        if action == "match":
            matches[groups[row - 1].physical_index] = (col - 1, _alignment_score(groups[row - 1], hosts[col - 1]))
        row, col = prior_row, prior_col
    return matches, ways[rows][cols] == 1


def _bound(
    block: RecognitionBlock,
    host_index: Optional[int],
    status: str,
    confidence: float,
    evidence: Sequence[str],
    warnings: Sequence[str],
    start: Optional[int] = None,
    end: Optional[int] = None,
) -> BoundRecognitionBlock:
    return BoundRecognitionBlock(
        block_index=block.block_index,
        physical_paragraph_index=block.physical_paragraph_index,
        host_paragraph_index=host_index,
        binding_status=status,
        binding_confidence=confidence,
        binding_evidence=tuple(dict.fromkeys(evidence)),
        binding_warnings=tuple(dict.fromkeys(warnings)),
        host_raw_start_utf16=start,
        host_raw_end_utf16=end,
    )


def bind_recognition_plan(
    plan: RecognitionPlan,
    host_snapshot: HostSnapshot | Mapping[str, Any],
) -> RecognitionBinding:
    """Bind a plan to a local host snapshot without calling any editor API.

    Returned offsets refer only to the supplied ``raw_text`` strings.  WPS and
    Word integrations must translate them only after their own API snapshot is
    verified, and must skip any block whose status is not ``confirmed``.
    """
    snapshot = _coerce_snapshot(host_snapshot)
    hosts = tuple(_HostText(
        paragraph=item,
        tape=SourceTape.from_text(item.raw_text),
        raw_hash=_sha256(item.raw_text),
        canonical_hash=_sha256(canonicalize_text(item.raw_text)),
    ) for item in snapshot.paragraphs if item.story_type == "main" and not item.is_in_table)
    groups = _physical_groups(plan)
    matched, unique_alignment = _align_groups(groups, hosts)
    duplicates = {}
    for host in hosts:
        duplicates[host.raw_hash] = duplicates.get(host.raw_hash, 0) + 1
    host_by_position = {position: item for position, item in enumerate(hosts)}
    result = []

    for block in plan.blocks:
        if block.physical_paragraph_index is None:
            result.append(_bound(block, None, "unresolved", 0.0, (), ("SOURCE_PHYSICAL_PARAGRAPH_MISSING",)))
            continue
        if block.source_locator_status != "confirmed" or not block.locator_verified:
            result.append(_bound(
                block, None, "unresolved", 0.0, (),
                tuple(block.source_locator_warnings) + ("SOURCE_LOCATOR_NOT_CONFIRMED",),
            ))
            continue
        matched_item = matched.get(block.physical_paragraph_index)
        if matched_item is None:
            result.append(_bound(block, None, "unresolved", 0.0, (), ("PHYSICAL_PARAGRAPH_UNMATCHED",)))
            continue
        host_position, score = matched_item
        host = host_by_position[host_position]
        if not unique_alignment:
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, "unresolved", 0.0,
                ("PHYSICAL_TEXT_MATCH",), ("SOURCE_OCCURRENCE_AMBIGUOUS",),
            ))
            continue
        evidence = ["PARAGRAPH_ORDER_MATCH"]
        warnings = []
        if duplicates.get(host.raw_hash, 0) > 1:
            evidence.append("DUPLICATE_TEXT_DISAMBIGUATED")
        if score == 100:
            evidence.extend(("PHYSICAL_RAW_TEXT_MATCH", "PHYSICAL_HASH_MATCH"))
            start, end = block.raw_start_utf16, block.raw_end_utf16
            fragment = host.tape.raw_slice_utf16(start or 0, end or 0) if start is not None and end is not None else None
            if fragment is None or _sha256(fragment) != block.raw_fragment_sha256:
                result.append(_bound(
                    block, host.paragraph.host_paragraph_index, "unresolved", 0.0,
                    evidence, ("SOURCE_TEXT_HASH_MISMATCH",),
                ))
                continue
            evidence.append("SEGMENT_TEXT_MATCH")
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, "confirmed", 1.0,
                evidence + ["SEGMENT_ORDER_MATCH"], warnings, start, end,
            ))
            continue

        canonical_start = block.canonical_start_utf16
        canonical_end = block.canonical_end_utf16
        raw_span = (
            host.tape.raw_span_for_canonical_range(canonical_start, canonical_end)
            if canonical_start is not None and canonical_end is not None
            else None
        )
        if raw_span is None:
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, "unresolved", 0.0,
                evidence + ["PHYSICAL_CANONICAL_TEXT_MATCH"], ("SOURCE_RANGE_UNRESOLVED",),
            ))
            continue
        start_cp, end_cp = raw_span
        start, end = host.tape.raw_offset_utf16(start_cp), host.tape.raw_offset_utf16(end_cp)
        fragment = host.tape.raw_slice_utf16(start or 0, end or 0) if start is not None and end is not None else None
        if fragment is None or _sha256(canonicalize_text(fragment)) != block.canonical_fragment_sha256:
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, "unresolved", 0.0,
                evidence + ["PHYSICAL_CANONICAL_TEXT_MATCH"], ("SOURCE_TEXT_HASH_MISMATCH",),
            ))
            continue
        result.append(_bound(
            block, host.paragraph.host_paragraph_index, "confirmed", 0.93,
            evidence + ["PHYSICAL_CANONICAL_TEXT_MATCH", "SEGMENT_TEXT_MATCH", "SEGMENT_ORDER_MATCH"],
            ("RAW_TEXT_NORMALIZED",), start, end,
        ))

    return RecognitionBinding(
        locator_version="2.0",
        source_sha256=plan.source_sha256,
        host_type=snapshot.host_type,
        document_identity=snapshot.document_identity,
        blocks=tuple(result),
    )
