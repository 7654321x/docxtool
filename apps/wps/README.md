# DocxTool WPS App

This directory is the WPS host application layer.

Responsibilities:

- Ribbon and task pane integration
- WPS document lifecycle
- local runtime orchestration
- preview interaction
- diagnostics

The WPS layer does not implement:

- DOCX recognition rules
- normalization rules
- formatting rules
- a second formatting engine

The document pipeline remains in `src/docxtool`:

```
Importer
  -> Segmenter
  -> Recognition
  -> Normalizer
  -> Engine
```

Migration rule:

- move WPS host code here
- keep core independent from WPS
- do not migrate the old WPS formatting command engine
