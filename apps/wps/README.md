# DocxTool WPS App

This directory contains the WPS host application layer for DocxTool.

## Responsibility

`apps/wps` is responsible for:

- WPS Ribbon and task pane UI
- WPS host lifecycle (open/save/close/reopen)
- local runtime orchestration
- preview interaction
- logging and diagnostics

## Boundary

The WPS app calls DocxTool core capabilities but does not implement document recognition, normalization, or formatting rules.

Core pipeline remains:

```
Importer
  -> Segmenter
  -> Recognition
  -> Normalizer
  -> Engine
```

No WPS-specific dependency should be introduced into `src/docxtool`.

## Migration status

Initial app boundary created. Migration should move only WPS host code from the former plugin project. The old WPS formatting engine must not be migrated as a second formatting implementation.
