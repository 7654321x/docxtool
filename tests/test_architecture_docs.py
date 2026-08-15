from __future__ import annotations

import ast
import re
from pathlib import Path
from urllib.parse import unquote


ROOT = Path(__file__).resolve().parents[1]


def test_documentation_ownership_entries_are_published_and_navigable() -> None:
    required = {
        "docs/ARCHITECTURE.md",
        "docs/RELEASE.md",
        "docs/WPS_REGRESSION_CHECKLIST.md",
        "docs/WPS_VALIDATION.md",
        "docs/design/WPS_READER_UI_TECHNICAL_DESIGN.md",
        "docs/design/WPS_BUILTIN_STYLE_GALLERY_TECHNICAL_DESIGN.md",
        "docs/design/GIT_BASELINE_RELEASE_WORKFLOW.md",
        "docs/design/wps-format-settings.md",
        "docs/design/CODEX_WORKFLOW_OPTIMIZATION.md",
        "apps/reader/AGENTS.md",
    }
    navigation = (ROOT / "docs" / "README.md").read_text(encoding="utf-8")
    publish_script = (ROOT / "scripts" / "publish_to_github.ps1").read_text(encoding="utf-8")

    for relative in required:
        assert (ROOT / relative).is_file()
        assert relative in publish_script

    assert "ARCHITECTURE.md" in navigation
    assert "RELEASE.md" in navigation
    assert "WPS_REGRESSION_CHECKLIST.md" in navigation
    assert "CODEX_WORKFLOW_OPTIMIZATION.md" in navigation


def test_changed_verification_entry_is_published_and_has_explicit_output_contract() -> None:
    script = (ROOT / "scripts" / "verify_changed.ps1").read_text(encoding="utf-8")
    publish = (ROOT / "scripts" / "publish_to_github.ps1").read_text(encoding="utf-8")

    assert "SELECTED_CHECKS" in script
    assert "SKIPPED_CHECKS" in script
    assert "NOT_RUN" in script
    assert "apps/wps/scripts/verify.ps1" in script
    assert "EXE build" in script
    assert '"scripts/verify_changed.ps1"' in publish


def test_docs_root_keeps_only_current_main_documents() -> None:
    expected = {
        "API.md",
        "ARCHITECTURE.md",
        "DEPLOY.md",
        "DOCX_REGRESSION_CHECKLIST.md",
        "HOST_TEXT_V1_GOLDEN.json",
        "INTEGRATION_CONTRACT_V1.md",
        "README.md",
        "RELEASE.md",
        "SDK.md",
        "WPS_REGRESSION_CHECKLIST.md",
        "WPS_VALIDATION.md",
    }
    actual = {path.name for path in (ROOT / "docs").iterdir() if path.is_file()}
    assert actual == expected


def test_current_documentation_does_not_restore_obsolete_wps_facts() -> None:
    current_documents = [
        ROOT / "README.md",
        ROOT / "CONVENTIONS.md",
        ROOT / "WPS_SERVER_PRD.md",
        ROOT / "WPS_SERVER_TECHNICAL_DESIGN.md",
        ROOT / "公文格式规范.md",
        ROOT / "apps" / "wps" / "README.md",
        ROOT / "apps" / "wps" / "AGENTS.md",
        ROOT / "docs" / "API.md",
        ROOT / "docs" / "DEPLOY.md",
        ROOT / "docs" / "WPS_VALIDATION.md",
        ROOT / "docs" / "WPS_REGRESSION_CHECKLIST.md",
    ]
    text = "\n".join(path.read_text(encoding="utf-8") for path in current_documents)

    obsolete = (
        "复用有效会话，或在过期后静默登录一次",
        "结果补报只保存在当前进程内存中",
        "构建用户端控制台单文件 EXE",
        "版本归属：DocxTool 5.2.2",
        "版本基线：Docxtool `1.3`",
        "classified-offline",
        "前28字",
    )
    for phrase in obsolete:
        assert phrase not in text


def test_project_markdown_relative_links_resolve() -> None:
    ignored_parts = {".venv", "node_modules", "local_recycle", ".pytest_cache", "test_docx"}
    link_pattern = re.compile(r"!?\[[^\]]*\]\(([^)]+)\)")
    broken: list[tuple[str, str]] = []

    for path in ROOT.rglob("*.md"):
        if ignored_parts.intersection(path.relative_to(ROOT).parts):
            continue
        text = path.read_text(encoding="utf-8")
        for match in link_pattern.finditer(text):
            target = match.group(1).strip()
            if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            relative_target = unquote(target.split("#", 1)[0]).strip("<>")
            if relative_target and not (path.parent / relative_target).exists():
                broken.append((str(path.relative_to(ROOT)), target))

    assert not broken, broken


def test_agents_delegate_concrete_regressions_to_owned_checklists() -> None:
    root_agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
    wps_agents = (ROOT / "apps" / "wps" / "AGENTS.md").read_text(encoding="utf-8")

    assert "docs/DOCX_REGRESSION_CHECKLIST.md" in root_agents
    assert "docs/WPS_REGRESSION_CHECKLIST.md" in root_agents
    assert "WPS_REGRESSION_CHECKLIST.md" in wps_agents
    assert "## 公文结构排版回归" not in root_agents


def test_architecture_doc_contains_web_and_sdk_mermaid_flows() -> None:
    text = (ROOT / "docs" / "ARCHITECTURE.md").read_text(encoding="utf-8")

    assert text.count("```mermaid") >= 2
    assert "flowchart TD" in text
    assert "Web 处理链" in text
    assert "SDK 与宿主适配链" in text
    assert "_task_process_subprocess" in text
    assert "RecognitionRequest" in text
    assert "RecognitionBinding" in text


def test_architecture_documentation_does_not_add_runtime_dag_dependency() -> None:
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


def test_document_configuration_and_diagnostics_have_stable_owners() -> None:
    style_config = ROOT / "src" / "docxtool" / "document" / "style_config.py"
    source = style_config.read_text(encoding="utf-8")
    assert "PyQt5" not in source
    assert "read_rules_from_table" not in source
    assert "read_page_settings" not in source

    from docxtool.document.configuration.models import StyleRule as OwnedStyleRule
    from docxtool.document.diagnostics.logging import logger as OwnedLogger
    from docxtool.document.style_config import StyleRule, logger

    assert StyleRule is OwnedStyleRule
    assert logger is OwnedLogger


def test_wps_control_protocol_helpers_are_extracted_without_changing_facade() -> None:
    from apps.wps.control import server
    from apps.wps.control.transport import protocol

    assert server._client_disconnected is protocol.client_disconnected
    assert server._error_code is protocol.error_code
    assert server._safe_log_details is protocol.safe_log_details
    assert server._safe_warnings is protocol.safe_warnings
    assert server._ControlClientDisconnected is protocol.ControlClientDisconnected


def test_sdk_model_validation_boundary_has_no_module_import_cycle() -> None:
    """SDK protocol models stay importable without loading the validator facade."""
    sdk_root = ROOT / "src" / "docxtool" / "sdk"
    owned = {"models", "validation", "manifest"}
    graph: dict[str, set[str]] = {name: set() for name in owned}

    for name in owned:
        tree = ast.parse((sdk_root / f"{name}.py").read_text(encoding="utf-8"))
        for node in tree.body:
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                target = node.module.split(".", 1)[0]
                if target in owned:
                    graph[name].add(target)

    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(name: str) -> None:
        if name in visiting:
            raise AssertionError(f"SDK module import cycle detected at {name}")
        if name in visited:
            return
        visiting.add(name)
        for dependency in graph[name]:
            visit(dependency)
        visiting.remove(name)
        visited.add(name)

    for module_name in owned:
        visit(module_name)

    validation_tree = ast.parse((sdk_root / "validation.py").read_text(encoding="utf-8"))
    direct_imports = {
        node.module
        for node in validation_tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module
    }
    assert "models" not in direct_imports
    assert "manifest" not in direct_imports

def test_api_docs_describe_config_contract_semantics() -> None:
    """API.md 必须描述 canonical-first punctuation、table_format 与 output_suffix 契约。"""
    api = (ROOT / "docs" / "API.md").read_text(encoding="utf-8")

    # punctuation canonical-first 契约
    assert "punctuation.enabled` 显式出现时（无论 `true` 或 `false`），以它为准" in api
    assert "`punctuation.enabled` 完全没有出现时，才回退读取 `features.punctuation_enabled`" in api
    assert "仅为兼容旧客户端" in api
    assert "两者不是两个可同时生效的独立" in api
    # table_format fail-fast 契约
    assert "当前版本不支持表格格式化" in api
    assert "显式传 `true` 时配置校验返回" in api
    assert "表格始终按原样复制" in api
    # output_suffix 契约
    assert "`工作报告_最终版.docx`" in api
    assert "历史默认后缀 `_排版文件`" in api
    # grid_alignment canonical 字符串
    assert '"grid_alignment": "文字对齐字符网络"' in api
    assert "不是布尔值" in api

def test_wps_node_tests_have_one_canonical_gate() -> None:
    """WPS Node 测试必须只有一个正式入口，CI 与 verify.ps1 共用，缺失必失败。"""
    runner = (ROOT / "apps/wps/tests/run-node-tests.mjs").read_text(encoding="utf-8")
    for test_name in ("host-runtime.test.mjs", "taskpane-runtime.test.mjs", "reader-ui.test.mjs", "format-settings.test.mjs"):
        assert f'import "./{test_name}"' in runner

    verify = (ROOT / "apps/wps/scripts/verify.ps1").read_text(encoding="utf-8")
    assert "node --test \"apps/wps/tests/run-node-tests.mjs\"" in verify
    assert "Test-Path -LiteralPath \"apps/wps/tests/format-settings.test.mjs\"" not in verify
    assert "wps-runtime.test.mjs" not in verify

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    assert "node --test apps/wps/tests/run-node-tests.mjs" in ci
    assert "reader-ui.test.mjs" not in ci.replace("run-node-tests.mjs", "")

def test_ci_node_tests_are_outside_python_matrix_and_not_duplicated() -> None:
    """Node 测试必须单独执行一次；recognition decoder 不得在同一 job 重复执行。"""
    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")

    node_steps = ci.count("node --test ")
    # WPS runner + worker-routing + frontend-format-config 各一次
    assert node_steps == 3
    assert ci.count("node --test apps/wps/tests/run-node-tests.mjs") == 1
    assert ci.count("node --test tests/worker-routing.test.mjs") == 1
    assert ci.count("node --test tests/frontend-format-config.test.mjs") == 1

    # decoder 只由全量 pytest 收集，不允许单独重复步骤
    assert "python -m pytest tests/test_recognition_decoder.py" not in ci
    assert "run: python -m pytest" in ci
