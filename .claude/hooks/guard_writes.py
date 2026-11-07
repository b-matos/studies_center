#!/usr/bin/env python3
"""PreToolUse hook: restrict each estudo subagent to its own output files.

Reads the hook JSON (agent_type, tool_name, tool_input) from stdin. For Write/Edit calls
made by one of our named subagents, the target path must match that agent's allowlist
below — this is the enforcement layer behind the per-agent "Escreves em ..." contracts in
.claude/agents/*.md. Exit 0 to allow, exit 2 (with a reason on stderr) to block.

Paths are matched against the project-relative path, so the allowlist is independent of
where the repo is checked out. Patterns use `<slug>` as a wildcard for the study folder name.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Each pattern is a regex matched against the path relative to PROJECT_ROOT (posix separators).
ALLOWLIST: dict[str, list[str]] = {
    "planeador": [r"^estudos/[^/]+/plano\.md$"],
    "pesquisador-dados": [r"^estudos/[^/]+/fontes\.csv$"],
    "extrator": [
        r"^estudos/[^/]+/dados/raw/.+$",
        r"^estudos/[^/]+/dados/raw_manifest\.csv$",
        r"^estudos/[^/]+/dados/clean/.+\.parquet$",
    ],
    "analista": [
        r"^estudos/[^/]+/analise/.+$",
        r"^estudos/[^/]+/quebras\.csv$",
    ],
    "historiador": [
        r"^eventos/eventos\.csv$",
        r"^estudos/[^/]+/ligacoes_eventos\.csv$",
    ],
    "redator": [
        r"^estudos/[^/]+/relatorio\.(pt|en)\.qmd$",
        r"^estudos/[^/]+/afirmacoes\.csv$",
        r"^estudos/[^/]+/estudo\.yml$",
    ],
    "verificador": [r"^estudos/[^/]+/verificacao\.md$"],
}

GUARDED_TOOLS = {"Write", "Edit"}


def _relative_path(file_path: str) -> str | None:
    try:
        return Path(file_path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return None


def main() -> None:
    payload = json.load(sys.stdin)
    agent_type = payload.get("agent_type")
    tool_name = payload.get("tool_name")
    tool_input = payload.get("tool_input", {})

    if tool_name not in GUARDED_TOOLS or agent_type not in ALLOWLIST:
        sys.exit(0)  # not a write/edit, or not one of our scoped subagents (e.g. the main session)

    file_path = tool_input.get("file_path", "")
    rel_path = _relative_path(file_path)
    if rel_path is None:
        print(f"guard_writes: '{agent_type}' cannot write outside the project root: {file_path}", file=sys.stderr)
        sys.exit(2)

    patterns = ALLOWLIST[agent_type]
    if not any(re.match(p, rel_path) for p in patterns):
        print(
            f"guard_writes: '{agent_type}' is not allowed to write to '{rel_path}'. "
            f"Allowed patterns: {patterns}",
            file=sys.stderr,
        )
        sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
