from __future__ import annotations

from types import SimpleNamespace

from docxtool.document.engine import core, export_pipeline


def test_core_export_facade_uses_one_context_in_pipeline_order(monkeypatch) -> None:
    context = SimpleNamespace(stats={"total": 0})
    calls = []

    def prepare(*args, **kwargs):
        calls.append(("prepare", kwargs["compatibility_module"]))
        return context

    def render(received, *args, **kwargs):
        calls.append(("render", received, kwargs["compatibility_module"]))

    def finalize(received, *args, **kwargs):
        calls.append(("finalize", received, kwargs["compatibility_module"]))
        return received.stats

    monkeypatch.setattr(export_pipeline, "prepare_render_context", prepare)
    monkeypatch.setattr(export_pipeline, "render_document_items", render)
    monkeypatch.setattr(export_pipeline, "finalize_export", finalize)

    result = core.export_doc(
        SimpleNamespace(filepath="fixture.docx", paragraphs=[], tables=[]),
        [],
        SimpleNamespace(),
        "output.docx",
    )

    assert result is context.stats
    assert calls == [
        ("prepare", core),
        ("render", context, core),
        ("finalize", context, core),
    ]


def test_core_export_facade_forwards_explicit_style_profile(monkeypatch) -> None:
    received = {}

    def fake_export(*args, **kwargs):
        received.update(kwargs)
        return {}

    monkeypatch.setattr(core, "_export_pipeline", fake_export)

    core.export_doc(
        SimpleNamespace(filepath="fixture.docx", paragraphs=[], tables=[]),
        [],
        SimpleNamespace(),
        "output.docx",
        style_profile="wps_builtin",
    )

    assert received["style_profile"] == "wps_builtin"
