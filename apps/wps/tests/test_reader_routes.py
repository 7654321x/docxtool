from __future__ import annotations

import http.client
import json
from pathlib import Path
import threading

from apps.reader import ReaderPaths, ReaderService
from apps.wps.control import reader_routes
from apps.wps.control import server as server_module


def _reader_service(tmp_path: Path) -> ReaderService:
    root = tmp_path / "reader-data"
    return ReaderService(
        ReaderPaths(
            root=root,
            books_dir=root / "books",
            database_path=root / "reader.db",
            temp_dir=root / "temp",
        )
    )


def _request(server, method, path, *, body=None, token="token", headers=None):
    connection = http.client.HTTPConnection(
        "127.0.0.1", server.server_address[1], timeout=5
    )
    request_headers = {"Authorization": f"Bearer {token}"}
    request_headers.update(headers or {})
    try:
        connection.request(method, path, body=body, headers=request_headers)
        response = connection.getresponse()
        return response.status, json.loads(response.read().decode("utf-8"))
    finally:
        connection.close()


def _running_server(tmp_path, *, allowed_origin="", account_runtime=None):
    server = server_module.create_server(
        tmp_path,
        "token",
        0,
        account_runtime=account_runtime,
        reader_service=_reader_service(tmp_path),
        allowed_origin=allowed_origin,
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _close_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=3)


def test_reader_routes_use_existing_loopback_authorization_and_origin(tmp_path):
    server, thread = _running_server(tmp_path, allowed_origin="http://127.0.0.1:3889")
    try:
        status, payload = _request(server, "GET", "/v1/reader/state", token="wrong")
        assert (status, payload["error_code"]) == (401, "WPS_CONTROL_UNAUTHORIZED")

        status, payload = _request(
            server,
            "GET",
            "/v1/reader/state",
            headers={"Origin": "http://untrusted.invalid"},
        )
        assert (status, payload["error_code"]) == (403, "WPS_CONTROL_ORIGIN_REJECTED")

        status, payload = _request(
            server,
            "GET",
            "/v1/reader/state",
            headers={"Origin": "http://127.0.0.1:3889"},
        )
        assert status == 200
        assert payload["data"]["books"] == []
    finally:
        _close_server(server, thread)


def test_reader_routes_import_bounded_content_without_hostbridge_or_account(tmp_path, monkeypatch):
    class AccountRuntime:
        def authorize_format(self, _request_id):
            raise AssertionError("Reader must not authorize formatting")

        def summary(self):
            raise AssertionError("Reader route must not query account summary")

    events = []
    monkeypatch.setattr(reader_routes, "log_event", lambda *_args, **_kwargs: events.append((_args, _kwargs)))
    server, thread = _running_server(tmp_path, account_runtime=AccountRuntime())
    secret_body = "SECRET_BOOK_TEXT_123456\n" + "正文" * 14_000
    try:
        status, payload = _request(
            server,
            "POST",
            "/v1/reader/import",
            body=secret_body.encode("utf-8"),
            headers={
                "Content-Type": "text/plain; charset=utf-8",
                "X-DocxTool-Reader-Filename": "private-source.txt",
                "X-DocxTool-Request-Id": "reader-import-1",
            },
        )
        assert status == 200
        book = payload["data"]["book"]
        assert "stored_filename" not in book
        assert book["display_name"] == "private-source"
        assert server.command_monitor.busy is False

        status, content = _request(
            server,
            "GET",
            f"/v1/reader/content?book_id={book['id']}&chapter_index=0&limit=12000",
        )
        assert status == 200
        assert len(content["data"]["text"]) == 12_000
        assert content["data"]["end_offset"] < content["data"]["chapter_end_offset"]
        logged = repr(events)
        assert "SECRET_BOOK_TEXT_123456" not in logged
        assert "private-source.txt" not in logged
        assert str(tmp_path) not in logged
    finally:
        _close_server(server, thread)


def test_reader_import_hard_limit_and_reader_routes_are_not_bridge_or_account_adapters(tmp_path):
    server, thread = _running_server(tmp_path)
    try:
        status, payload = _request(
            server,
            "POST",
            "/v1/reader/import",
            body=b"",
            headers={
                "Content-Type": "text/plain",
                "Content-Length": str(reader_routes.READER_IMPORT_MAX_BYTES + 1),
                "X-DocxTool-Reader-Filename": "book.txt",
            },
        )
        assert (status, payload["error_code"]) == (400, "READER_FILE_TOO_LARGE")
    finally:
        _close_server(server, thread)

    source = Path(reader_routes.__file__).read_text(encoding="utf-8")
    assert "HostBridge" not in source
    assert "CommandMonitor" not in source
    assert "account_runtime" not in source
    assert "authorize_format" not in source


def test_reader_requests_do_not_log_full_book_identifier_or_query(monkeypatch, tmp_path):
    captured = []
    monkeypatch.setattr(
        server_module,
        "log_event",
        lambda *_args, **_kwargs: captured.append((_args, _kwargs)),
    )
    server, thread = _running_server(tmp_path)
    try:
        status, payload = _request(
            server,
            "POST",
            "/v1/reader/import",
            body="正文".encode("utf-8"),
            headers={
                "Content-Type": "text/plain",
                "X-DocxTool-Reader-Filename": "private-source.txt",
            },
        )
        assert status == 200
        book_id = payload["data"]["book"]["id"]
        status, _payload = _request(
            server,
            "GET",
            f"/v1/reader/content?book_id={book_id}&chapter_index=0&limit=1",
        )
        assert status == 200
        logged = repr(captured)
        assert book_id not in logged
        assert "private-source.txt" not in logged
    finally:
        _close_server(server, thread)


def test_reader_route_navigates_adjacent_paragraph_without_crossing_chapter(tmp_path):
    server, thread = _running_server(tmp_path)
    try:
        status, payload = _request(
            server,
            "POST",
            "/v1/reader/import",
            body="第一章\n段1\n\n段2\n第二章\n段3".encode(),
            headers={
                "Content-Type": "text/plain",
                "X-DocxTool-Reader-Filename": "book.txt",
            },
        )
        assert status == 200
        book_id = payload["data"]["book"]["id"]
        status, state = _request(server, "GET", "/v1/reader/state")
        assert status == 200
        first_chapter = state["data"]["chapters"][0]

        status, payload = _request(
            server,
            "POST",
            "/v1/reader/navigate",
            body=json.dumps({
                "book_id": book_id,
                "chapter_index": 0,
                "text_offset": first_chapter["start_offset"],
                "direction": 1,
            }),
        )
        assert (status, payload["data"]["target_offset"]) == (200, first_chapter["start_offset"] + 4)
    finally:
        _close_server(server, thread)
