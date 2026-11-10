import hashlib
from pathlib import Path

import httpx
import pytest

from common import download


class _FakeResponse:
    def __init__(self, content: bytes) -> None:
        self.content = content

    def raise_for_status(self) -> None:
        return None


class _FakeClient:
    def __init__(self, content: bytes, **kwargs) -> None:
        self._content = content

    def __enter__(self) -> "_FakeClient":
        return self

    def __exit__(self, *exc) -> None:
        return None

    def get(self, url: str) -> _FakeResponse:
        return _FakeResponse(self._content)


def test_download_writes_file_and_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"indicador,valor\n2020,100\n"
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _FakeClient(content, **kwargs))

    dest = download.download(tmp_path, "https://example.com/dados.csv", "dados.csv")

    assert dest.read_bytes() == content
    entries = download.read_manifest(tmp_path)
    assert len(entries) == 1
    assert entries[0].file == "dados.csv"
    assert entries[0].sha256 == hashlib.sha256(content).hexdigest()

    problems = download.verify_manifest(tmp_path)
    assert problems == []


def test_verify_manifest_detects_tampering(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"original"
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _FakeClient(content, **kwargs))
    dest = download.download(tmp_path, "https://example.com/dados.csv", "dados.csv")

    dest.write_bytes(b"tampered")

    problems = download.verify_manifest(tmp_path)
    assert len(problems) == 1
    assert "hash mismatch" in problems[0]


def test_verify_manifest_detects_missing_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    content = b"original"
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: _FakeClient(content, **kwargs))
    dest = download.download(tmp_path, "https://example.com/dados.csv", "dados.csv")
    dest.unlink()

    problems = download.verify_manifest(tmp_path)
    assert len(problems) == 1
    assert "missing raw file" in problems[0]
