"""WPS entry point for DocxTool formatting.

The WPS layer owns document lifecycle only. The actual DOCX processing remains
inside docxtool core.
"""

from __future__ import annotations

from pathlib import Path


def format_current_document(source_path: str, output_path: str | None = None) -> Path:
    """Format a DOCX file through the existing DocxTool pipeline.

    This intentionally keeps orchestration thin. Future WPS UI code should call
    this adapter instead of implementing formatting commands itself.
    """
    source = Path(source_path)
    target = Path(output_path) if output_path else source.with_name(f"{source.stem}.formatted{source.suffix}")

    from docxtool.document.style_config import load_rules_and_settings
    from docxtool.document.importing import DocxImporter
    from docxtool.document.engine import export_doc
    from docxtool.security import validate_docx_integrity

    rules, settings, features = load_rules_and_settings()
    document = DocxImporter().load(
        str(source),
        rules,
        features=features,
        recognition_mode="authoritative",
    )
    export_doc(document, rules, settings, str(target), features=features)
    validate_docx_integrity(str(target))
    return target
