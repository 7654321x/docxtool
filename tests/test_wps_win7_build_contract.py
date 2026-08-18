from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_wps_build_uses_python_38_and_the_win7_schema_dependency() -> None:
    build_script = (ROOT / "apps" / "wps" / "scripts" / "build-exe.ps1").read_text(
        encoding="utf-8"
    )
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    lock_text = "\n".join(
        (ROOT / filename).read_text(encoding="utf-8")
        for filename in ("requirements.lock", "requirements-dev.lock")
    )

    assert 'pythonVersion -ne "3.8"' in build_script
    assert 'jsonschema==4.17.3' in pyproject
    assert 'jsonschema==4.17.3' in lock_text
    for forbidden in ("rpds-py==", "referencing==", "jsonschema-specifications=="):
        assert forbidden not in lock_text


def test_wps_build_refreshes_the_project_metadata_before_freezing() -> None:
    build_script = (ROOT / "apps" / "wps" / "scripts" / "build-exe.ps1").read_text(
        encoding="utf-8"
    )

    assert "--force-reinstall" in build_script
    assert "--no-build-isolation" in build_script
    assert "metadata.version('docxtool')" in build_script
    assert "WPS_BUILD_PACKAGE_VERSION_MISMATCH" in build_script
