"""Tests for server/publish.py: commit and push of a published study, with safety conditions."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
import yaml

from server import publish


def _git(cwd: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    remote = tmp_path / "remote.git"
    _git(tmp_path, "init", "--bare", "-b", "main", str(remote))
    root = tmp_path / "work"
    root.mkdir()
    _git(root, "init", "-b", "main")
    _git(root, "config", "user.email", "t@example.com")
    _git(root, "config", "user.name", "t")
    (root / "README.md").write_text("x", encoding="utf-8")
    _git(root, "add", ".")
    _git(root, "commit", "-m", "init")
    _git(root, "remote", "add", "origin", str(remote))
    _git(root, "push", "origin", "main")
    monkeypatch.setenv("STUDIES_AUTO_PUSH", "1")
    return root


def _study(root: Path, slug: str = "demo", *, status: str = "published", phases: tuple[int, ...] = (1, 8)) -> None:
    d = root / "studies" / slug
    d.mkdir(parents=True)
    (d / "study.yml").write_text(yaml.safe_dump({"status": status}), encoding="utf-8")
    (d / "state.json").write_text(json.dumps({"completed_phases": list(phases)}), encoding="utf-8")
    (d / "report.pt.qmd").write_text("texto", encoding="utf-8")


async def test_disabled_by_default(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("STUDIES_AUTO_PUSH")
    _study(repo)
    assert await publish.publish_study("demo", repo) == ""


async def test_not_published_does_nothing(repo: Path) -> None:
    _study(repo, status="in_progress")
    assert await publish.publish_study("demo", repo) == ""
    _study(repo, "other", phases=(1, 2))
    assert await publish.publish_study("other", repo) == ""


async def test_commits_and_pushes(repo: Path) -> None:
    _study(repo)
    msg = await publish.publish_study("demo", repo)
    assert "push feito" in msg
    assert _git(repo, "log", "-1", "--format=%s") == "fase 8 (publicação): demo"
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/main")


async def test_already_committed_only_pushes(repo: Path) -> None:
    _study(repo)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "fase 8 (publicação): demo")
    assert "push feito" in await publish.publish_study("demo", repo)
    assert _git(repo, "rev-parse", "HEAD") == _git(repo, "rev-parse", "origin/main")


async def test_dirty_tree_outside_study_blocks_push(repo: Path) -> None:
    _study(repo)
    (repo / "README.md").write_text("changed", encoding="utf-8")
    msg = await publish.publish_study("demo", repo)
    assert "alterações por commitar" in msg
    assert _git(repo, "rev-parse", "origin/main") != _git(repo, "rev-parse", "HEAD")


async def test_wrong_branch_blocks_push(repo: Path) -> None:
    _study(repo)
    _git(repo, "checkout", "-b", "feature")
    assert "não 'main'" in await publish.publish_study("demo", repo)


async def test_missing_remote_blocks_push(repo: Path) -> None:
    _study(repo)
    _git(repo, "remote", "remove", "origin")
    assert "não existe" in await publish.publish_study("demo", repo)
