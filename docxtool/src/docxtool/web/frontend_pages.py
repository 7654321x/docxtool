"""前端页面资源读取辅助。

本模块只负责定位和读取打包后的前端 HTML，不处理 HTTP 响应、不访问任务或 DOCX。
"""

from __future__ import annotations

import os
from typing import Callable

from docxtool.paths import resource_path


def frontend_index_candidates(resource_path_func: Callable[..., object] = resource_path) -> list[str]:
    """传入资源路径函数，返回前端首页候选文件路径列表。"""
    return [str(resource_path_func("frontend", "pages", "index.html"))]


def load_frontend_index_html(
    *,
    resource_path_func: Callable[..., object] = resource_path,
    exists: Callable[[str], bool] = os.path.exists,
    open_file: Callable[..., object] = open,
) -> str | None:
    """传入路径解析、存在性检查和打开函数，返回首页 HTML；缺失时返回 None。"""
    candidates = frontend_index_candidates(resource_path_func)
    path = next((candidate for candidate in candidates if exists(candidate)), candidates[-1])
    try:
        with open_file(path, "r", encoding="utf-8") as file_obj:
            return file_obj.read()
    except FileNotFoundError:
        return None
