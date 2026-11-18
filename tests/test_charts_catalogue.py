"""The JavaScript chart catalogue (site/assets/charts.js), exercised with a stub DOM and a stub Plotly."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_chart_catalogue_builds_every_kind_with_alt_text_and_data_table() -> None:
    result = subprocess.run(["node", "tests/js/charts.test.mjs"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "charts catalogue: ok" in result.stdout
