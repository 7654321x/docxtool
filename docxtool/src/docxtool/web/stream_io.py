"""Bounded stream reading and file streaming helpers for HTTP handlers."""

from __future__ import annotations

import os
import time


def read_exact(rfile, length: int, timeout: int = 10) -> bytes:
    """Read exactly length bytes from a request stream and return the bytes."""
    data = b""
    remaining = int(length)
    started = time.time()
    while remaining > 0:
        if time.time() - started > timeout:
            raise TimeoutError("read timeout")
        chunk = rfile.read(remaining)
        if not chunk:
            time.sleep(0.01)
            continue
        data += chunk
        remaining -= len(chunk)
    return data


def read_exact_to_file(
    rfile,
    path: str,
    length: int,
    timeout: int = 10,
    chunk_size: int = 64 * 1024,
) -> int:
    """Read exactly length bytes from a request stream into path and return bytes written."""
    if length <= 0:
        raise TimeoutError("invalid length")
    total = 0
    remaining = int(length)
    started = time.time()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as output:
        while remaining > 0:
            if time.time() - started > timeout:
                raise TimeoutError("read timeout")
            chunk = rfile.read(min(chunk_size, remaining))
            if not chunk:
                time.sleep(0.01)
                continue
            output.write(chunk)
            total += len(chunk)
            remaining -= len(chunk)
    return total


def stream_file(path: str, writer, chunk_size: int = 1024 * 1024) -> None:
    """Read a file from path in chunks and write each chunk to the response writer."""
    with open(path, "rb") as source:
        while True:
            chunk = source.read(chunk_size)
            if not chunk:
                break
            writer.write(chunk)
