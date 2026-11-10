"""Download a source file, store it under data/raw/, and record it in the manifest.

data/raw/ is gitignored (see .gitignore). What is committed is data/raw_manifest.csv,
which lets anyone re-fetch the raw files while the source stays online, and lets
common.checks detect if a previously-downloaded file has drifted from its recorded hash.
"""
from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx

MANIFEST_FIELDS = ["url", "file", "download_date", "sha256", "bytes"]


@dataclass
class ManifestEntry:
    url: str
    file: str
    download_date: str
    sha256: str
    bytes: int


def _manifest_path(study_dir: Path) -> Path:
    return study_dir / "data" / "raw_manifest.csv"


def read_manifest(study_dir: Path) -> list[ManifestEntry]:
    path = _manifest_path(study_dir)
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return [ManifestEntry(**row) for row in csv.DictReader(f)]


def write_manifest(study_dir: Path, entries: list[ManifestEntry]) -> None:
    path = _manifest_path(study_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=MANIFEST_FIELDS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry.__dict__)


def download(study_dir: Path, url: str, filename: str, *, timeout: float = 60.0) -> Path:
    """Fetch `url`, save it to data/raw/<filename>, and append a manifest entry."""
    raw_dir = study_dir / "data" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    dest = raw_dir / filename

    with httpx.Client(follow_redirects=True, timeout=timeout) as client:
        response = client.get(url)
        response.raise_for_status()
        dest.write_bytes(response.content)

    digest = hashlib.sha256(dest.read_bytes()).hexdigest()
    entries = [e for e in read_manifest(study_dir) if e.file != filename]
    entries.append(
        ManifestEntry(
            url=url,
            file=filename,
            download_date=date.today().isoformat(),
            sha256=digest,
            bytes=dest.stat().st_size,
        )
    )
    write_manifest(study_dir, entries)
    return dest


def verify_manifest(study_dir: Path) -> list[str]:
    """Return a list of problems: missing files or files whose hash no longer matches."""
    problems = []
    for entry in read_manifest(study_dir):
        path = study_dir / "data" / "raw" / entry.file
        if not path.exists():
            problems.append(f"missing raw file: {entry.file} (run download again)")
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry.sha256:
            problems.append(f"hash mismatch for {entry.file}: expected {entry.sha256}, got {digest}")
    return problems
