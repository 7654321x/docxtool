# SDK Contract Examples

These examples are intentionally short and sanitized. They show the shape of the
contract, not real user document content.

## RecognitionRequest

```json
{
  "schema_version": "recognition-request-v1",
  "processing_mode": "structural",
  "recognition_mode": "authoritative",
  "include_text": false,
  "include_raw_text": false,
  "format_config": null,
  "feature_overrides": null
}
```

## Ordinary Paragraph HostSnapshot

```json
{
  "schema_version": "host-snapshot-v1",
  "integration_contract_version": "integration-contract-v1",
  "snapshot_id": "wps-session-0001",
  "document_identity": "local-doc-001",
  "document_revision": "rev-001",
  "host": { "kind": "wps", "version": null, "platform": "windows" },
  "text_contract_version": "host-text-v1",
  "offset_encoding": "utf16_code_unit",
  "paragraphs": [
    {
      "host_paragraph_id": "main:000000",
      "host_paragraph_index": 0,
      "story_id": "main",
      "story_type": "main",
      "story_paragraph_index": 0,
      "section_index": 0,
      "is_in_table": false,
      "raw_text": "普通示例段落"
    }
  ]
}
```

## Microsoft Word HostSnapshot

```json
{
  "schema_version": "host-snapshot-v1",
  "integration_contract_version": "integration-contract-v1",
  "snapshot_id": "word-session-0001",
  "host": { "kind": "microsoft-word", "version": null, "platform": "office-js" },
  "text_contract_version": "host-text-v1",
  "offset_encoding": "utf16_code_unit",
  "paragraphs": [
    {
      "host_paragraph_id": "main:000000",
      "host_paragraph_index": 0,
      "story_id": "main",
      "story_type": "main",
      "story_paragraph_index": 0,
      "section_index": 0,
      "is_in_table": false,
      "raw_text": "普通示例段落"
    }
  ]
}
```

## One Physical Paragraph, Two Logical Segments

The source physical paragraph may contain a heading and body text in one Word
paragraph. The plan returns two blocks sharing one `physical_group_id`:

```json
{
  "blocks": [
    {
      "block_id": "blk_heading",
      "physical_group_id": "pg_001",
      "semantic": { "kind": "paragraph", "type_id": "heading1", "section": "body", "format_role": "heading1" },
      "segment": { "index": 0, "count_total": 2, "count_located": 2, "count_confirmed": 2 }
    },
    {
      "block_id": "blk_body",
      "physical_group_id": "pg_001",
      "semantic": { "kind": "paragraph", "type_id": "body", "section": "body", "format_role": "body" },
      "segment": { "index": 1, "count_total": 2, "count_located": 2, "count_confirmed": 2 }
    }
  ]
}
```

## Repeated Paragraph Ambiguity

When identical host paragraphs cannot be disambiguated by monotonic order, the
binding for that physical group is `unresolved`:

```json
{
  "binding": {
    "status": "unresolved",
    "confidence": 0.0,
    "warnings": ["SOURCE_OCCURRENCE_AMBIGUOUS"],
    "recommended_action": "skip"
  }
}
```

## Review

Canonical text may match while raw text differs, for example NBSP versus normal
space. That block is preview-only:

```json
{
  "binding": {
    "status": "review",
    "confidence": 0.93,
    "warnings": ["RAW_TEXT_NORMALIZED"],
    "recommended_action": "preview_only"
  }
}
```

## Incomplete Segment Group

If one logical fragment in a physical paragraph cannot be verified, hosts must
not apply the group automatically:

```json
{
  "segment": {
    "index": 1,
    "count_total": 3,
    "count_located": 2,
    "count_confirmed": 2
  },
  "source_locator": {
    "status": "unresolved",
    "warnings": ["SEGMENT_GROUP_INCOMPLETE"]
  }
}
```

## Confirmed Binding Preconditions

```json
{
  "binding": {
    "status": "confirmed",
    "recommended_action": "verify_host_range"
  },
  "preconditions": {
    "plan_id": "plan_example",
    "snapshot_id": "wps-session-0001",
    "document_identity": "local-doc-001",
    "document_revision": "rev-001",
    "host_paragraph_id": "main:000000",
    "host_paragraph_raw_sha256": "hash",
    "host_paragraph_canonical_sha256": "hash",
    "raw_fragment_sha256": "hash",
    "canonical_fragment_sha256": "hash",
    "text_contract_version": "host-text-v1",
    "offset_encoding": "utf16_code_unit"
  }
}
```
