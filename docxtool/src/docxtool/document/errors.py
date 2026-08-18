"""Shared document-layer exceptions.

异常定义放在独立模块，避免导入器、配置、版头和 Engine 之间为了共享
异常类型而互相导入。旧的 ``style_config`` 名称由兼容 facade 继续导出。
"""

from __future__ import annotations


class ConfigValidationError(ValueError):
    """格式配置字段不符合约定。"""

    def __init__(self, field_path: str, reason: str):
        self.code = "FORMAT_CONFIG_INVALID"
        self.field = field_path
        self.reason = reason
        super().__init__(f"{self.code}: {field_path}: {reason}")


class FormatterError(Exception):
    """所有排版相关异常的基类。"""


class DocumentImportError(FormatterError):
    """文档导入阶段异常。"""


class StyleError(FormatterError):
    """样式应用阶段异常。"""


class ExportError(FormatterError):
    """文档导出阶段异常。"""


# 兼容旧调用方；新代码应使用 DocumentImportError，避免遮蔽 builtins.ImportError。
ImportError = DocumentImportError


__all__ = [
    "ConfigValidationError",
    "FormatterError",
    "DocumentImportError",
    "ImportError",
    "StyleError",
    "ExportError",
]
