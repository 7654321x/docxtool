# Changelog

## 1.6 - 2026-07-31

- Made recognition-plan host binding locally ambiguity-aware so unresolved repeated text does not invalidate unrelated physical paragraphs.
- Added run-intersection formatting facts for logical fragments, the `host-text-v1` canonical text contract, and complete logical-segment counts.

## 1.5 - 2026-07-31

- Added source-range based logical fragment locators, including raw and canonical UTF-16 coordinate definitions.
- Added SDK v2 locator fields, explicit text opt-ins, and a host-neutral recognition-plan binding API with ambiguity rejection.
- Added regression coverage for mixed physical paragraphs, duplicate text, host paragraph shifts, canonical normalization, Unicode surrogate pairs, and CLI binding output.

## 1.4 - 2026-07-30

- Added a reusable Chinese official-document formatting and recognition specification for WPS and third-party AI integrations.

## 1.3 - 2026-07-29

- Added a stable, local-only `docxtool.sdk` recognition API for third-party integrations.
- Added the `docxtool-recognize` command for writing redacted JSON recognition plans from DOCX snapshots.
- Kept the existing web service, recognition rules, formatting engine, and DOCX export flow unchanged.

## 1.2 - 2026-07-29

- Added Python 3.8 compatibility for Windows 7 while retaining Python 3.10 support.
- Rebuilt production and development dependency locks from Python 3.8.
- Added dual-version CI and Windows startup compatibility checks.
- Completed authoritative structured document recognition with document-head analysis, global context, heading families, constrained decoding, diagnostics, and review signals.
- Clarified strict, structural, and normalize processing boundaries; structural mode now repairs only reliable document boundaries while preserving visible text by default.
- Improved letterhead, title, heading, numbering, punctuation, signature, attachment, page-number, table, section, and DOCX relationship handling.
- Added protected user authentication, private template/task ownership, deployment hardening, and Cloudflare Pages proxy coverage.
- Added batch DOCX regression comparison, deterministic visual rendering checks, and reusable recognition benchmarks.

## 1.1 - 2026-07-29

- Added account authentication, session isolation, anonymous-resource migration, and protected template ownership.
- Upgraded document recognition with structured candidates, context-aware decoding, diagnostics, and review signals.
- Improved official-document formatting for letterheads, headings, signatures, attachments, numbering, punctuation, and layout preservation.
- Added production deployment materials, dependency locks, security hardening, automated regression tooling, and batch document validation.
- Improved the administrator workspace, frontend authentication experience, and Cloudflare Pages proxy integration.
