# DocxTool Local TXT Reader

`apps/reader` is the independent local TXT-reader domain used by the WPS TaskPane.

It owns TXT decoding, chapter indexes, book metadata, reading progress, and settings. It does not import `apps.wps`, DocxTool Core, Recognition, Normalization, Engine, HostBridge, AccountRuntime, or PublicApi.

## Local data

Runtime data is outside the repository:

```text
%LOCALAPPDATA%\DocxTool\reader\
├─ books\<book_id>.txt
├─ reader.db
└─ temp\
```

`DOCXTOOL_HOME` changes the parent directory for tests and local development. SQLite stores only metadata, chapter offsets, progress, and settings; full book text remains in the managed TXT copy. The original TXT is only read and is never modified, moved, or deleted.

## Boundaries

The WPS adapter is `apps/wps/control/reader_routes.py`. It uses the existing loopback credential and Origin policy but does not use the HostBridge command slot or public account authorization. The Reader has no public service, cloud sync, or second HTTP listener.

## Verification

```pwsh
pwsh -NoProfile -Command ".\.venv\Scripts\python.exe -m pytest -q tests/reader apps/wps/tests/test_reader_routes.py"
pwsh -NoProfile -Command "node --test apps/wps/tests/reader-ui.test.mjs"
```

Tests use anonymous synthetic TXT fixtures only. Logs must never contain book text, book title, original filename, absolute paths, or tokens.
