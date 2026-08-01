import io

import pytest

from docxtool.web import app as server
from docxtool.web.stream_io import read_exact, read_exact_to_file, stream_file


def test_stream_io_reads_exact_bytes_and_matches_app_facade():
    source = io.BytesIO(b"abcdef")

    assert read_exact(source, 4) == b"abcd"
    assert server._read_exact(io.BytesIO(b"xyz"), 3) == b"xyz"


def test_stream_io_reads_to_file_and_reports_written_bytes(tmp_path):
    output = tmp_path / "nested" / "upload.bin"

    written = read_exact_to_file(io.BytesIO(b"abcdef"), str(output), 6, chunk_size=2)

    assert written == 6
    assert output.read_bytes() == b"abcdef"


def test_stream_io_rejects_invalid_or_short_body(tmp_path):
    with pytest.raises(TimeoutError, match="invalid length"):
        read_exact_to_file(io.BytesIO(b""), str(tmp_path / "upload.bin"), 0)
    with pytest.raises(TimeoutError, match="read timeout"):
        read_exact(io.BytesIO(b""), 1, timeout=0)


def test_stream_io_streams_file_to_writer(tmp_path):
    source = tmp_path / "result.bin"
    source.write_bytes(b"abcdef")
    writer = io.BytesIO()

    stream_file(str(source), writer, chunk_size=2)

    assert writer.getvalue() == b"abcdef"
