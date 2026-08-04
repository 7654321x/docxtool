from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_architecture_dag_doc_contains_web_and_sdk_mermaid_flows() -> None:
    text = (ROOT / "docs" / "ARCHITECTURE_DAG.md").read_text(encoding="utf-8")

    assert text.count("```mermaid") >= 2
    assert "flowchart TD" in text
    assert "DAG A：Web 文档处理链" in text
    assert "DAG B：SDK/宿主适配链" in text
    assert "_task_process_subprocess" in text
    assert "RecognitionRequest" in text
    assert "RecognitionBinding" in text


def test_architecture_dag_does_not_add_runtime_dag_dependency() -> None:
    candidates = [
        ROOT / "pyproject.toml",
        ROOT / "requirements.lock",
        ROOT / "requirements-dev.lock",
    ]
    dependency_text = "\n".join(path.read_text(encoding="utf-8") for path in candidates if path.exists()).lower()

    for package_name in ("airflow", "prefect", "dagster", "networkx"):
        assert package_name not in dependency_text


def _package_imports(package: Path) -> set[str]:
    imports = set()
    for path in package.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module)
    return imports


def test_document_layers_have_no_reverse_engine_or_importer_dependencies() -> None:
    document = ROOT / "src" / "docxtool" / "document"
    pipeline_imports = _package_imports(document / "pipeline")
    recognition_imports = _package_imports(document / "recognition")
    engine_imports = _package_imports(document / "engine")

    assert not any(name.startswith("docxtool.document.engine") for name in pipeline_imports)
    assert not any(name.startswith("docxtool.document.engine") for name in recognition_imports)
    assert "docxtool.document.importer" not in engine_imports
