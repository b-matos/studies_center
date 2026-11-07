"""Tests for .claude/hooks/guard_writes.py, the PreToolUse hook that keeps each estudo
subagent inside its own output files (see .claude/agents/*.md's "Escreves em ..." contracts).

Loaded via importlib under a private name, same reasoning as tests/test_site_build.py for
`site/build.py`: a module literally named `hooks` or similar could otherwise shadow stdlib.
Tested by calling main() with stdin/argv faked, and checking the resulting SystemExit code.
"""
from __future__ import annotations

import importlib.util
import io
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_guard_module():
    spec = importlib.util.spec_from_file_location(
        "studies_guard_writes", REPO_ROOT / ".claude" / "hooks" / "guard_writes.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _run(module, monkeypatch, *, agent_type: str | None, tool_name: str, file_path: str) -> int:
    payload = {"agent_type": agent_type, "tool_name": tool_name, "tool_input": {"file_path": file_path}}
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    with pytest.raises(SystemExit) as exc_info:
        module.main()
    return exc_info.value.code


@pytest.fixture
def guard(monkeypatch: pytest.MonkeyPatch):
    module = _load_guard_module()
    monkeypatch.setattr(module, "PROJECT_ROOT", REPO_ROOT)
    return module


def test_unscoped_agent_type_is_allowed(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    # The main orchestrating session has no agent_type in ALLOWLIST, so it is never gated.
    code = _run(
        guard, monkeypatch, agent_type=None, tool_name="Write",
        file_path=str(REPO_ROOT / "estudos" / "x" / "estado.json"),
    )
    assert code == 0


def test_non_write_edit_tool_is_allowed(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(
        guard, monkeypatch, agent_type="redator", tool_name="Read",
        file_path=str(REPO_ROOT / "estudos" / "x" / "dados" / "clean" / "f1.parquet"),
    )
    assert code == 0


def test_redator_can_write_its_own_files(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    for rel in ["estudos/x/relatorio.pt.qmd", "estudos/x/relatorio.en.qmd", "estudos/x/afirmacoes.csv"]:
        code = _run(guard, monkeypatch, agent_type="redator", tool_name="Write", file_path=str(REPO_ROOT / rel))
        assert code == 0, rel


def test_redator_cannot_write_quebras(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(
        guard, monkeypatch, agent_type="redator", tool_name="Write",
        file_path=str(REPO_ROOT / "estudos" / "x" / "quebras.csv"),
    )
    assert code == 2


def test_verificador_can_update_afirmacoes_but_not_the_report(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    ok_code = _run(
        guard, monkeypatch, agent_type="verificador", tool_name="Write",
        file_path=str(REPO_ROOT / "estudos" / "x" / "afirmacoes.csv"),
    )
    assert ok_code == 0

    ok_code = _run(
        guard, monkeypatch, agent_type="verificador", tool_name="Write",
        file_path=str(REPO_ROOT / "estudos" / "x" / "verificacao.md"),
    )
    assert ok_code == 0

    blocked_code = _run(
        guard, monkeypatch, agent_type="verificador", tool_name="Edit",
        file_path=str(REPO_ROOT / "estudos" / "x" / "relatorio.pt.qmd"),
    )
    assert blocked_code == 2


def test_path_outside_project_root_is_blocked(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(guard, monkeypatch, agent_type="redator", tool_name="Write", file_path="/etc/passwd")
    assert code == 2


def test_historiador_can_write_shared_eventos_catalogue(guard, monkeypatch: pytest.MonkeyPatch) -> None:
    code = _run(
        guard, monkeypatch, agent_type="historiador", tool_name="Write",
        file_path=str(REPO_ROOT / "eventos" / "eventos.csv"),
    )
    assert code == 0
