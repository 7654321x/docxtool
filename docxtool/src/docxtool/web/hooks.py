"""Runtime access to the Web compatibility composition root."""

from __future__ import annotations

import importlib
from types import ModuleType
from typing import MutableMapping


_APP_PROVIDER: ModuleType | None = None


def register_app_provider(module: ModuleType) -> None:
    """Register the current app module without copying its mutable globals."""
    global _APP_PROVIDER
    _APP_PROVIDER = module


def app_provider() -> ModuleType:
    """Return the registered app, importing the composition root lazily if needed."""
    if _APP_PROVIDER is None:
        importlib.import_module("docxtool.web.app")
    if _APP_PROVIDER is None:  # pragma: no cover - defensive import contract
        raise RuntimeError("docxtool.web.app did not register its compatibility provider")
    return _APP_PROVIDER


def sync_app_namespace(target: MutableMapping[str, object]) -> None:
    """Refresh one legacy namespace so app-level monkeypatches remain effective."""
    for name, value in vars(app_provider()).items():
        if not name.startswith("__"):
            target[name] = value
