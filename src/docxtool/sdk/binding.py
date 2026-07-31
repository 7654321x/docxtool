"""Host-neutral verification of a recognition plan against local text."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any, Mapping, Optional, Sequence, Tuple

from docxtool.document.source_tape import (
    HOST_TEXT_CONTRACT_VERSION,
    SOURCE_LOCATOR_VERSION,
    SourceTape,
    canonicalize_text,
)

from .models import (
    BoundRecognitionBlock,
    HostParagraph,
    HostSnapshot,
    PhysicalParagraphBinding,
    RecognitionBinding,
    RecognitionBlock,
    RecognitionPlan,
)


def _sha256(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _raw_index_for_utf16_offset(value: str, offset: Optional[int]) -> Optional[int]:
    """Return a code-point boundary for an exact UTF-16 offset."""
    if offset is None or offset < 0:
        return None
    current = 0
    if offset == 0:
        return 0
    for index, character in enumerate(value or "", start=1):
        current += 2 if ord(character) > 0xFFFF else 1
        if current == offset:
            return index
        if current > offset:
            return None
    return len(value or "") if current == offset else None


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
    contract_version = value.get("text_contract_version", HOST_TEXT_CONTRACT_VERSION)
    if not isinstance(contract_version, str):
        raise ValueError("host_snapshot.text_contract_version 必须为字符串")
    return HostSnapshot(
        host_type=host_type,
        paragraphs=tuple(paragraphs),
        document_identity=str(identity) if identity is not None else None,
        text_contract_version=contract_version,
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


def _align_groups(
    groups: Sequence[_PhysicalGroup],
    hosts: Sequence[_HostText],
) -> dict[int, tuple[str, Optional[int], int, tuple[int, ...], tuple[str, ...], tuple[str, ...]]]:
    """Return a local alignment state for every source physical paragraph.

    A global dynamic-programming score is still required to preserve document
    order.  Its ambiguity is not global, however: each source group receives
    only the host positions that participate in an optimal monotonic path.
    Therefore one repeated paragraph cannot make unrelated unique paragraphs
    unsafe to bind.
    """
    rows, cols = len(groups), len(hosts)
    forward = [[0] * (cols + 1) for _ in range(rows + 1)]
    for row in range(1, rows + 1):
        for col in range(1, cols + 1):
            match = _alignment_score(groups[row - 1], hosts[col - 1])
            forward[row][col] = max(
                forward[row - 1][col],
                forward[row][col - 1],
                forward[row - 1][col - 1] + match if match else -1,
            )

    backward = [[0] * (cols + 1) for _ in range(rows + 1)]
    for row in range(rows - 1, -1, -1):
        for col in range(cols - 1, -1, -1):
            match = _alignment_score(groups[row], hosts[col])
            backward[row][col] = max(
                backward[row + 1][col],
                backward[row][col + 1],
                backward[row + 1][col + 1] + match if match else -1,
            )

    optimum = forward[rows][cols]
    result = {}
    for row, group in enumerate(groups):
        candidates = []
        for col, host in enumerate(hosts):
            score = _alignment_score(group, host)
            if score and forward[row][col] + score + backward[row + 1][col + 1] == optimum:
                candidates.append((col, score))
        candidate_positions = tuple(position for position, _score in candidates)
        if not candidates:
            result[group.physical_index] = (
                "unmatched", None, 0, (), (), ("PHYSICAL_PARAGRAPH_UNMATCHED",),
            )
            continue
        if len(candidates) > 1:
            result[group.physical_index] = (
                "ambiguous", None, 0, candidate_positions,
                ("PARAGRAPH_ORDER_MATCH",), ("SOURCE_OCCURRENCE_AMBIGUOUS",),
            )
            continue
        position, score = candidates[0]
        evidence = ["PARAGRAPH_ORDER_MATCH"]
        if score == 100:
            evidence.extend(("PHYSICAL_RAW_TEXT_MATCH", "PHYSICAL_HASH_MATCH"))
            status = "matched_unique"
        else:
            evidence.append("PHYSICAL_CANONICAL_TEXT_MATCH")
            status = "matched_review"
        result[group.physical_index] = (status, position, score, candidate_positions, tuple(evidence), ())
    return result


def _bound(
    block: RecognitionBlock,
    host_index: Optional[int],
    status: str,
    confidence: float,
    evidence: Sequence[str],
    warnings: Sequence[str],
    start: Optional[int] = None,
    end: Optional[int] = None,
    canonical_start: Optional[int] = None,
    canonical_end: Optional[int] = None,
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
        host_canonical_start_utf16=canonical_start,
        host_canonical_end_utf16=canonical_end,
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
        tape=SourceTape.from_text(item.raw_text, contract_version=snapshot.text_contract_version),
        raw_hash=_sha256(item.raw_text),
        canonical_hash=_sha256(
            canonicalize_text(item.raw_text)
            if snapshot.text_contract_version == HOST_TEXT_CONTRACT_VERSION
            else SourceTape.from_text(item.raw_text, snapshot.text_contract_version).canonical_text
        ),
    ) for item in snapshot.paragraphs if item.story_type == "main" and not item.is_in_table)
    groups = _physical_groups(plan)
    alignments = _align_groups(groups, hosts)
    duplicates = {}
    for host in hosts:
        duplicates[host.raw_hash] = duplicates.get(host.raw_hash, 0) + 1
    host_by_position = {position: item for position, item in enumerate(hosts)}
    group_by_index = {group.physical_index: group for group in groups}
    physical_paragraphs = []
    for physical_index in sorted(group_by_index):
        status, host_position, score, candidates, evidence, warnings = alignments[physical_index]
        physical_paragraphs.append(PhysicalParagraphBinding(
            source_physical_paragraph_index=physical_index,
            host_paragraph_index=(
                host_by_position[host_position].paragraph.host_paragraph_index
                if host_position is not None else None
            ),
            status=status,
            score=score,
            candidate_host_paragraph_indexes=tuple(
                host_by_position[position].paragraph.host_paragraph_index for position in candidates
            ),
            evidence=evidence,
            warnings=warnings,
        ))
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
        alignment = alignments.get(block.physical_paragraph_index)
        if alignment is None:
            result.append(_bound(block, None, "unresolved", 0.0, (), ("PHYSICAL_PARAGRAPH_UNMATCHED",)))
            continue
        alignment_status, host_position, score, _candidates, alignment_evidence, alignment_warnings = alignment
        if alignment_status in {"ambiguous", "unmatched"} or host_position is None:
            result.append(_bound(
                block, None, "unresolved", 0.0,
                alignment_evidence, alignment_warnings,
            ))
            continue
        host = host_by_position[host_position]
        evidence = list(alignment_evidence)
        warnings = []
        if duplicates.get(host.raw_hash, 0) > 1:
            evidence.append("DUPLICATE_TEXT_DISAMBIGUATED")
        if score == 100:
            start, end = block.raw_start_utf16, block.raw_end_utf16
            fragment = host.tape.raw_slice_utf16(start or 0, end or 0) if start is not None and end is not None else None
            if fragment is None or _sha256(fragment) != block.raw_fragment_sha256:
                result.append(_bound(
                    block, host.paragraph.host_paragraph_index, "unresolved", 0.0,
                    evidence, ("SOURCE_TEXT_HASH_MISMATCH",),
                ))
                continue
            evidence.append("SEGMENT_TEXT_MATCH")
            # Convert exact raw UTF-16 offsets through the verified host tape.
            # A raw span may not begin inside a surrogate pair; that condition
            # has already been rejected by ``raw_slice_utf16`` above.
            raw_start_index = _raw_index_for_utf16_offset(host.tape.raw_text, start)
            raw_end_index = _raw_index_for_utf16_offset(host.tape.raw_text, end)
            host_canonical_range = (
                host.tape.canonical_range_for_raw_span(raw_start_index, raw_end_index)
                if raw_start_index is not None and raw_end_index is not None
                else None
            )
            if host_canonical_range is None:
                result.append(_bound(
                    block, host.paragraph.host_paragraph_index, "unresolved", 0.0,
                    evidence, ("HOST_CANONICAL_RANGE_UNRESOLVED",),
                ))
                continue
            result.append(_bound(
                block, host.paragraph.host_paragraph_index, "confirmed", 1.0,
                evidence + ["SEGMENT_ORDER_MATCH"], warnings, start, end,
                host_canonical_range[0], host_canonical_range[1],
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
            block, host.paragraph.host_paragraph_index, "review", 0.93,
            evidence + ["SEGMENT_TEXT_MATCH", "SEGMENT_ORDER_MATCH"],
            ("RAW_TEXT_NORMALIZED",), start, end, canonical_start, canonical_end,
        ))

    return RecognitionBinding(
        locator_version=SOURCE_LOCATOR_VERSION,
        source_sha256=plan.source_sha256,
        host_type=snapshot.host_type,
        document_identity=snapshot.document_identity,
        host_text_contract_version=snapshot.text_contract_version,
        blocks=tuple(result),
        physical_paragraphs=tuple(physical_paragraphs),
    )
