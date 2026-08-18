from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
def _relative_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts
    }


def test_deployment_python_source_is_an_exact_root_mirror() -> None:
    root_source = ROOT / "src" / "docxtool"
    deployment_source = ROOT / "docxtool" / "src" / "docxtool"

    assert _relative_files(deployment_source) == _relative_files(root_source)
    for relative_path in _relative_files(root_source):
        assert (deployment_source / relative_path).read_bytes() == (
            root_source / relative_path
        ).read_bytes()


def test_deployment_non_python_runtime_files_match_root_sources() -> None:
    for relative_path in (
        Path("server.py"),
        Path("pyproject.toml"),
        Path("requirements.lock"),
        Path("scripts/generate_secrets.py"),
    ):
        assert (ROOT / "docxtool" / relative_path).read_bytes() == (
            ROOT / relative_path
        ).read_bytes()

    root_frontend = ROOT / "resources" / "frontend"
    deployment_frontend = ROOT / "docxtool" / "resources" / "frontend"
    assert _relative_files(deployment_frontend) == _relative_files(root_frontend)
    for relative_path in _relative_files(root_frontend):
        assert (deployment_frontend / relative_path).read_bytes() == (
            root_frontend / relative_path
        ).read_bytes()
