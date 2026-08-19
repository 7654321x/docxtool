"""运行时版本解析。

本模块是 Python 包版本的唯一运行时入口。Web、SDK、CLI 和诊断输出都应
调用 ``package_version()``，不要再维护自己的版本常量。wheel 安装后以
包元数据为准；源码目录直接运行且尚未安装包时，才使用源码内的回退值。
这样可以同时覆盖“已安装制品”和“本地源码调试”两种可验证场景。
"""

from __future__ import annotations

from importlib import metadata

_SOURCE_VERSION = "5.6.3"


def package_version() -> str:
    """返回对外展示的 DocxTool 包版本。

    返回值只表达发布版本，例如 ``2.9``。构建日期、Git revision、协议版本
    和识别引擎版本都不是包版本，应在调用方使用独立字段承载。
    """
    try:
        return metadata.version("docxtool")
    except metadata.PackageNotFoundError:
        return _SOURCE_VERSION


__all__ = ["package_version"]
