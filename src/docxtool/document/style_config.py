"""兼容配置入口。

格式模型和校验实现位于 document.configuration；本模块继续保留历史
导入路径，避免 Web、WPS、SDK 和第三方调用方发生接口变化。
"""

from __future__ import annotations

from . import configuration as _configuration
from . import diagnostics as _diagnostics
from .configuration.models import *  # noqa: F401,F403
from .configuration.validation import *  # noqa: F401,F403
from .diagnostics.logging import *  # noqa: F401,F403
from .errors import *  # noqa: F401,F403


def __getattr__(name: str):
    for module in (_configuration, _configuration.models, _configuration.validation, _diagnostics, _diagnostics.logging):
        if hasattr(module, name):
            return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
