"""Filesystem paths used by the Docxtool package."""

from __future__ import annotations

import os
from importlib import resources
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parent


def _is_source_tree() -> bool:
    return PACKAGE_ROOT.parent.name == "src" and PACKAGE_ROOT.parents[1].joinpath("pyproject.toml").exists()


def _user_data_root() -> Path:
    override = os.environ.get("DOCXTOOL_HOME")
    if override:
        return Path(override)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base).joinpath("docxtool")
        return Path.home().joinpath("AppData", "Local", "docxtool")
    base = os.environ.get("XDG_STATE_HOME")
    if base:
        return Path(base).joinpath("docxtool")
    return Path.home().joinpath(".local", "state", "docxtool")


PROJECT_ROOT = PACKAGE_ROOT.parents[1] if _is_source_tree() else _user_data_root()


def project_path(*parts: str) -> Path:
    return PROJECT_ROOT.joinpath(*parts)


def resource_path(*parts: str) -> Path:
    return project_path("resources", *parts)


def var_path(*parts: str) -> Path:
    return project_path("var", *parts)


def default_format_config_path() -> Path:
    override = os.environ.get("DOCXTOOL_CONFIG_PATH") or os.environ.get("FORMAT_CONFIG_PATH")
    if override:
        return Path(override)
    return Path(resources.files("docxtool.resources").joinpath("config/default-format.json"))


def runtime_dir(kind: str, env_name: str) -> Path:
    override = os.environ.get(env_name)
    if override:
        return Path(override)
    return var_path(kind)
