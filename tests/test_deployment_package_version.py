from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _version(path: Path, pattern: str) -> str:
    match = re.search(pattern, path.read_text(encoding="utf-8"), re.MULTILINE)
    assert match is not None, path
    return match.group(1)


def test_root_and_deployment_package_versions_match() -> None:
    versions = {
        _version(ROOT / "pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        _version(ROOT / "src" / "docxtool" / "version.py", r'^_SOURCE_VERSION\s*=\s*"([^"]+)"'),
        _version(ROOT / "docxtool" / "pyproject.toml", r'^version\s*=\s*"([^"]+)"'),
        _version(ROOT / "docxtool" / "src" / "docxtool" / "version.py", r'^_SOURCE_VERSION\s*=\s*"([^"]+)"'),
    }

    assert len(versions) == 1
