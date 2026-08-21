import hashlib
import logging

import pytest

from apps.reader.service import MAX_CONTENT_CHARS, ReaderError, ReaderService
from apps.reader.storage import ReaderStorageError


def service(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCXTOOL_HOME", str(tmp_path / "home"))
    return ReaderService()


def test_service_imports_without_modifying_the_original_file(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    source = tmp_path / "fixture-book.txt"
    source.write_bytes("第一章 开始\r\n正文内容\n第二章 继续\n更多内容".encode("gb18030"))
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    imported = reader.import_book(source)

    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash
    assert imported.book.encoding == "gb18030"
    assert imported.book.chapter_count == 2
    assert (reader.paths.books_dir / imported.book.stored_filename).is_file()
    assert not source.with_name(imported.book.stored_filename).exists()


def test_service_keeps_book_progress_and_settings_after_restart(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    first = reader.import_bytes("第一章\n甲".encode(), "first.txt").book
    second = reader.import_bytes("第一章\n乙".encode(), "second.txt").book
    reader.save_progress(first.id, 0, 2, 0.36)
    reader.save_progress(second.id, 0, 2, 0.18)
    reader.select_book(first.id)
    reader.save_settings({"font_size": 18, "stealth_mode": True})

    restarted = ReaderService(reader.paths)

    assert restarted.get_settings().last_book_id == first.id
    assert restarted.get_settings().font_size == 18
    assert restarted.get_settings().stealth_mode is True
    assert restarted.load_progress(first.id).scroll_ratio == 0.4
    assert restarted.load_progress(second.id).scroll_ratio == 0.4


def test_service_returns_only_a_bounded_content_block_and_deletes_only_managed_copy(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    source = tmp_path / "large-book.txt"
    source.write_text("第一章\n" + "正文" * 20_000, encoding="utf-8")
    source_bytes = source.read_bytes()
    book = reader.import_book(source).book

    content = reader.get_content(book.id, 0, limit=MAX_CONTENT_CHARS)

    assert len(content.text) == MAX_CONTENT_CHARS
    assert content.end_offset < content.chapter_end_offset
    next_book = reader.delete_book(book.id)
    assert next_book is None
    assert source.read_bytes() == source_bytes
    assert not (reader.paths.books_dir / book.stored_filename).exists()
    with pytest.raises(ReaderError, match="READER_BOOK_NOT_FOUND"):
        reader.get_book(book.id)


def test_service_keeps_successive_content_window_offsets_exact(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes(("第一章\n" + "正文" * 20_000).encode(), "book.txt").book

    first = reader.get_content(book.id, 0, start_offset=0, limit=12_000)
    second = reader.get_content(book.id, 0, start_offset=first.end_offset, limit=12_000)

    assert second.start_offset == first.end_offset
    assert second.end_offset > second.start_offset


def test_service_rejects_invalid_progress_and_settings(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes("第一章\n正文".encode(), "book.txt").book

    with pytest.raises(ReaderError, match="READER_PROGRESS_INVALID"):
        reader.save_progress(book.id, 0, -1, 0)
    with pytest.raises(ReaderError, match="READER_SETTINGS_INVALID"):
        reader.save_settings({"font_size": 100})


def test_reader_navigates_non_empty_lines_without_crossing_chapters(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes("第一章\n段1\n\n段2\n第二章\n段3".encode(), "book.txt").book
    chapters = reader.list_chapters(book.id)

    assert reader.find_paragraph_target(book.id, 0, chapters[0].start_offset, 1) == chapters[0].start_offset + 4
    assert reader.find_paragraph_target(book.id, 0, chapters[0].start_offset + 4, 1) == chapters[0].start_offset + 8
    assert reader.find_paragraph_target(book.id, 0, chapters[0].start_offset + 8, 1) is None
    assert reader.find_paragraph_target(book.id, 0, chapters[0].start_offset + 4, -1) == chapters[0].start_offset
    assert reader.find_paragraph_target(book.id, 1, chapters[1].start_offset, -1) is None


def test_no_chapter_text_uses_the_same_paragraph_navigation_rule(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes("段1\n\n段2\n段3".encode(), "book.txt").book

    assert reader.find_paragraph_target(book.id, 0, 0, 1) == 4
    assert reader.find_paragraph_target(book.id, 0, 4, 1) == 7
    assert reader.find_paragraph_target(book.id, 0, 7, 1) is None


def test_settings_are_written_as_one_storage_operation(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    reader.import_bytes("正文".encode(), "book.txt")
    calls = []
    original = reader.storage.set_settings

    def capture(values):
        calls.append(dict(values))
        return original(values)

    monkeypatch.setattr(reader.storage, "set_settings", capture)
    reader.save_settings({"font_size": 18, "line_height": 1.8, "stealth_mode": True})

    assert calls == [{"font_size": 18, "line_height": 1.8, "stealth_mode": True}]


def test_import_keeps_file_and_database_consistent_when_metadata_write_fails(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)

    def fail_add(*_args, **_kwargs):
        raise ReaderStorageError()

    monkeypatch.setattr(reader.storage, "add_book", fail_add)

    with pytest.raises(ReaderError, match="READER_STORAGE_ERROR"):
        reader.import_bytes("正文".encode("utf-8"), "book.txt")

    assert reader.list_books() == []
    assert list(reader.paths.books_dir.iterdir()) == []


def test_delete_keeps_book_available_when_metadata_delete_fails(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes("正文".encode("utf-8"), "book.txt").book

    def fail_delete(*_args, **_kwargs):
        raise ReaderStorageError()

    monkeypatch.setattr(reader.storage, "delete_book", fail_delete)

    with pytest.raises(ReaderError, match="READER_STORAGE_ERROR"):
        reader.delete_book(book.id)

    assert reader.get_book(book.id) == book
    assert (reader.paths.books_dir / book.stored_filename).is_file()


def test_delete_reports_filesystem_rollback_failure(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes("正文".encode(), "book.txt").book
    original_replace = __import__("apps.reader.service", fromlist=["os"]).os.replace
    calls = []

    def replace(source, target):
        calls.append((source, target))
        if len(calls) == 2:
            raise OSError("restore failed")
        return original_replace(source, target)

    monkeypatch.setattr("apps.reader.service.os.replace", replace)
    monkeypatch.setattr(reader.storage, "delete_book", lambda *_args: (_ for _ in ()).throw(ReaderStorageError()))

    with pytest.raises(ReaderError, match="READER_DELETE_ROLLBACK_FAILED") as caught:
        reader.delete_book(book.id)

    assert getattr(caught.value, "primary_error").code == "READER_STORAGE_ERROR"
    assert type(getattr(caught.value, "rollback_error")).__name__ == "OSError"


def test_delete_succeeds_when_pending_cleanup_fails(monkeypatch, tmp_path, caplog):
    reader = service(monkeypatch, tmp_path)
    book = reader.import_bytes("正文".encode(), "book.txt").book
    original_unlink = __import__("pathlib").Path.unlink

    def fail_pending_cleanup(path, *args, **kwargs):
        if path.name.endswith(".delete"):
            raise OSError("cleanup failed")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr("pathlib.Path.unlink", fail_pending_cleanup)
    with caplog.at_level(logging.WARNING, logger="docx_tool.reader"):
        assert reader.delete_book(book.id) is None

    assert (reader.paths.temp_dir / (book.stored_filename + ".delete")).is_file()
    assert any(
        getattr(record, "event", "") == "reader.book.delete.cleanup_failed"
        for record in caplog.records
    )


def test_deleting_a_non_current_book_preserves_the_current_selection(monkeypatch, tmp_path):
    reader = service(monkeypatch, tmp_path)
    first = reader.import_bytes("甲".encode("utf-8"), "first.txt").book
    second = reader.import_bytes("乙".encode("utf-8"), "second.txt").book
    reader.select_book(first.id)

    remaining = reader.delete_book(second.id)

    assert remaining == first
    assert reader.get_settings().last_book_id == first.id
