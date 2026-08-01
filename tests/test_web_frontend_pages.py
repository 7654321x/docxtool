from __future__ import annotations

import io

from docxtool.web.frontend_pages import frontend_index_candidates, load_frontend_index_html


def _resource_path(*parts: str) -> str:
    """传入资源路径片段，返回测试用的拼接路径。"""
    return "/resources/" + "/".join(parts)


def test_frontend_index_candidates_use_packaged_pages_path() -> None:
    candidates = frontend_index_candidates(_resource_path)

    assert candidates == ["/resources/frontend/pages/index.html"]


def test_load_frontend_index_html_reads_first_existing_candidate() -> None:
    opened: list[tuple[str, str, str]] = []

    def _open_file(path: str, mode: str, encoding: str):
        """记录打开参数并返回测试 HTML 文本流。"""
        opened.append((path, mode, encoding))
        return io.StringIO("<!doctype html><html></html>")

    html = load_frontend_index_html(
        resource_path_func=_resource_path,
        exists=lambda path: True,
        open_file=_open_file,
    )

    assert html == "<!doctype html><html></html>"
    assert opened == [("/resources/frontend/pages/index.html", "r", "utf-8")]


def test_load_frontend_index_html_returns_none_when_file_missing() -> None:
    def _missing_open(path: str, mode: str, encoding: str):
        """模拟文件读取时被删除，始终抛出 FileNotFoundError。"""
        raise FileNotFoundError(path)

    html = load_frontend_index_html(
        resource_path_func=_resource_path,
        exists=lambda path: False,
        open_file=_missing_open,
    )

    assert html is None
