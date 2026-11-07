from pathlib import Path

from comum.csv_io import read_csv, write_csv
from comum.schemas import Afirmacao, FonteDados


def test_write_then_read_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "fontes.csv"
    rows = [
        FonteDados(
            id="f1",
            eixo="mortalidade",
            nome="Óbitos por causa de morte",
            organismo="INE",
            url="https://www.ine.pt/exemplo",
            formato="JSON",
            licenca="CC-BY",
            cobertura_temporal="1990-2023",
            cobertura_geografica="PT, NUTS II",
            estado="testada",
            motivo_exclusao=None,
            data_verificacao="2026-11-07",
        )
    ]
    write_csv(path, FonteDados, rows)
    loaded = read_csv(path, FonteDados)
    assert len(loaded) == 1
    assert loaded[0].id == "f1"
    assert loaded[0].estado == "testada"
    assert loaded[0].motivo_exclusao is None


def test_afirmacao_requires_id_pattern() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        Afirmacao(
            id="not-a-valid-id",
            tipo="facto",
            texto_pt="x",
            texto_en="x",
            valor=None,
            unidade=None,
            fonte_id="f1",
            url="https://example.com",
            data_acesso="2026-11-07",
            excerto="algo",
            natureza_fonte="primaria",
            localizacao="intro",
        )
