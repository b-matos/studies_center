from pathlib import Path

from common.csv_io import read_csv, write_csv
from common.schemas import Claim, DataSource


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "sources.csv"
    rows = [
        DataSource(
            id="f1",
            axis="mortalidade",
            name="Óbitos por causa de morte",
            organisation="INE",
            url="https://www.ine.pt/exemplo",
            format="JSON",
            license="CC-BY",
            temporal_coverage="1990-2023",
            geographic_coverage="PT, NUTS II",
            status="tested",
            exclusion_reason=None,
            verification_date="2026-11-07",
        )
    ]
    write_csv(path, DataSource, rows)
    loaded = read_csv(path, DataSource)
    assert len(loaded) == 1
    assert loaded[0].id == "f1"
    assert loaded[0].status == "tested"
    assert loaded[0].exclusion_reason is None


def test_claim_requires_id_pattern() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Claim(
            id="not-a-valid-id",
            type="fact",
            text_pt="x",
            text_en="x",
            value=None,
            unit=None,
            source_id="f1",
            url="https://example.com",
            access_date="2026-11-07",
            excerpt="algo",
            source_nature="primary",
            location="intro",
        )
