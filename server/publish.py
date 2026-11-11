"""Optional auto-publish: after a run that published a study, commit what is left and push.

The push is done here, by the server, and never by an agent: `git push` is denied in
.claude/settings.json on purpose. A push to `main` triggers .github/workflows/pages.yml, which
rebuilds the public site.

Off by default. Enable it with STUDIES_AUTO_PUSH=1 in the environment of the server.

Conditions, all checked by code:
- studies/<slug>/study.yml has `status: published` and state.json lists phase 8 as completed;
- the current branch is `main` and the remote (STUDIES_PUSH_REMOTE, default `origin`) exists;
- once studies/<slug> and events/ are committed, the working tree has no other changes.
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
PUBLISH_PHASE = 8
GIT_TIMEOUT = 120


def enabled() -> bool:
    return os.environ.get("STUDIES_AUTO_PUSH") == "1"


def _is_published(root: Path, slug: str) -> bool:
    study = root / "studies" / slug
    try:
        meta = yaml.safe_load((study / "study.yml").read_text(encoding="utf-8")) or {}
        done = json.loads((study / "state.json").read_text(encoding="utf-8")).get("completed_phases", [])
    except (OSError, ValueError, yaml.YAMLError):
        return False
    return meta.get("status") == "published" and PUBLISH_PHASE in done


async def _git(root: Path, *args: str) -> tuple[int, str]:
    process = await asyncio.create_subprocess_exec(
        "git", "-C", str(root), *args,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
    )
    try:
        out, _ = await asyncio.wait_for(process.communicate(), timeout=GIT_TIMEOUT)
    except TimeoutError:
        process.kill()
        return 124, f"git {args[0]} excedeu {GIT_TIMEOUT}s"
    return process.returncode or 0, out.decode("utf-8", "replace").strip()


async def publish_study(slug: str, root: Path = ROOT) -> str:
    """Commit and push a published study. Returns a one-line message for the queue page ("" = nothing to do)."""
    if not enabled() or not _is_published(root, slug):
        return ""

    remote = os.environ.get("STUDIES_PUSH_REMOTE", "origin")
    code, branch = await _git(root, "rev-parse", "--abbrev-ref", "HEAD")
    if code or branch != "main":
        return f"push não feito: o branch atual é '{branch}', não 'main'"
    code, _ = await _git(root, "remote", "get-url", remote)
    if code:
        return f"push não feito: o remote '{remote}' não existe"

    paths = [f"studies/{slug}", *(["events"] if (root / "events").exists() else [])]
    code, out = await _git(root, "add", "--", *paths)
    if code:
        return f"push não feito: git add falhou ({out})"
    if (await _git(root, "diff", "--cached", "--quiet"))[0]:  # something staged
        code, out = await _git(root, "commit", "-m", f"fase {PUBLISH_PHASE} (publicação): {slug}")
        if code:
            return f"push não feito: git commit falhou ({out})"

    code, out = await _git(root, "status", "--porcelain")
    if out:
        return "push não feito: há alterações por commitar fora deste estudo"

    code, out = await _git(root, "push", remote, "main")
    if code:
        return f"push falhou: {out.splitlines()[-1] if out else code}"
    return "estudo publicado: push feito, o site atualiza em instantes"
