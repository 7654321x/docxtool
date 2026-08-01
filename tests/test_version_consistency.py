from __future__ import annotations

import re
from importlib import metadata
from pathlib import Path

import docxtool
from docxtool.sdk import get_sdk_manifest
from docxtool.web import app as server


ROOT = Path(__file__).resolve().parents[1]


def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    assert match is not None
    return match.group(1)


def _installed_or_source_version() -> str:
    try:
        return metadata.version("docxtool")
    except metadata.PackageNotFoundError:
        return docxtool.__version__


def test_source_version_matches_pyproject_release_version() -> None:
    assert docxtool.__version__ == _pyproject_version()


def test_web_version_payload_uses_package_version() -> None:
    expected = _installed_or_source_version()

    payload = server._version_payload()

    assert payload["version"] == expected
    assert payload["package_version"] == expected
    assert payload.get("build_version") != payload["version"]


def test_sdk_manifest_uses_same_package_version_as_web_payload() -> None:
    expected = _installed_or_source_version()

    assert get_sdk_manifest().package_version == expected
    assert server._version_payload()["package_version"] == expected
