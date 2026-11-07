"""Tests for site/build.py.

Loaded via importlib under a private module name (not "site.build") because a directory
literally named `site/` would otherwise shadow Python's own stdlib `site` module on
sys.path. Monkeypatches the module's ROOT/SITE_DIR/etc. constants to point at a tmp_path
tree instead of touching the real repo.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pandas as pd
import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_build_module():
    spec = importlib.util.spec_from_file_location("studies_site_build", REPO_ROOT / "site" / "build.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def build_mod(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    mod = _load_build_module()
    site_dir = tmp_path / "site"
    site_dir.mkdir()
    estudos_dir = tmp_path / "estudos"
    estudos_dir.mkdir()
    eventos_csv = tmp_path / "eventos" / "eventos.csv"
    eventos_csv.parent.mkdir()
    eventos_csv.write_text(
        "id,data_inicio,data_fim,ambito,tipo,titulo_pt,titulo_en,descricao_pt,descricao_en,"
        "fonte_primaria_url,fonte_secundaria_url,data_acesso,temas,verificado\n"
        "e1,2020-03-01,,PT,pandemia_ou_crise_sanitaria,Covid,Covid,x,x,https://dgs.pt,,2026-01-01,saude,sim\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SITE_DIR", site_dir)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "ESTUDOS_DIR", estudos_dir)
    monkeypatch.setattr(mod, "EVENTOS_CSV", eventos_csv)
    return mod, site_dir, estudos_dir


def _make_study(estudos_dir: Path, slug: str, estado: str = "publicado") -> Path:
    study_dir = estudos_dir / slug
    study_dir.mkdir()
    (study_dir / "estudo.yml").write_text(
        yaml.safe_dump(
            {
                "titulo_pt": f"Estudo {slug}",
                "titulo_en": f"Study {slug}",
                "resumo_pt": "Resumo.",
                "resumo_en": "Summary.",
                "data": "2026-11-07",
                "estado": estado,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (study_dir / "relatorio.pt.qmd").write_text("# Relatório\n\nTexto.", encoding="utf-8")
    (study_dir / "relatorio.en.qmd").write_text("# Report\n\nText.", encoding="utf-8")
    return study_dir


def test_write_index_excludes_teste_studies(build_mod) -> None:
    mod, site_dir, estudos_dir = build_mod
    _make_study(estudos_dir, "publicado-1", estado="publicado")
    _make_study(estudos_dir, "teste-1", estado="teste")

    studies = mod.load_studies()
    mod.write_index(studies, "pt")

    index_text = (site_dir / "index.pt.qmd").read_text(encoding="utf-8")
    assert "publicado-1" in index_text
    assert "teste-1" not in index_text


def test_copy_study_pages_injects_output_file_front_matter(build_mod) -> None:
    mod, site_dir, estudos_dir = build_mod
    _make_study(estudos_dir, "saude-portugal")
    studies = mod.load_studies()
    mod.copy_study_pages(studies[0])

    pt_copy = (site_dir / "estudos" / "saude-portugal" / "index.pt.qmd").read_text(encoding="utf-8")
    assert "output-file: index.html" in pt_copy
    assert "# Relatório" in pt_copy


def test_copy_shared_assets_excludes_scss_and_survives_rerender(build_mod) -> None:
    mod, site_dir, _ = build_mod
    assets_src = site_dir / "assets"
    assets_src.mkdir()
    (assets_src / "lang-switch.js").write_text("// js", encoding="utf-8")
    (assets_src / "styles.scss").write_text("/* scss */", encoding="utf-8")
    (site_dir / "_site").mkdir()

    mod.copy_shared_assets()
    dest = site_dir / "_site" / "assets"
    assert (dest / "lang-switch.js").exists()
    assert not (dest / "styles.scss").exists()

    # a second call (as happens on every rebuild) must not fail on an existing dest
    mod.copy_shared_assets()
    assert (dest / "lang-switch.js").exists()


def test_write_root_redirect(build_mod) -> None:
    mod, site_dir, _ = build_mod
    (site_dir / "_site").mkdir()
    mod.write_root_redirect()
    text = (site_dir / "_site" / "index.html").read_text(encoding="utf-8")
    assert "/pt/" in text


def test_export_eventos_json(build_mod) -> None:
    mod, site_dir, _ = build_mod
    mod.export_eventos_json()
    data = json.loads((site_dir / "eventos.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == "e1"


def test_export_open_clean_data_excludes_nc_licensed_sources(build_mod) -> None:
    mod, site_dir, estudos_dir = build_mod
    study_dir = _make_study(estudos_dir, "saude-portugal")
    (study_dir / "fontes.csv").write_text(
        "id,eixo,nome,organismo,url,formato,licenca,cobertura_temporal,cobertura_geografica,estado,motivo_exclusao,data_verificacao\n"
        "f1,mortalidade,x,INE,https://ine.pt,csv,CC-BY,2000-2020,PT,testada,,2026-01-01\n"
        "f2,mortalidade,y,OMS,https://who.int,csv,CC-BY-NC,2000-2020,PT,testada,,2026-01-01\n",
        encoding="utf-8",
    )
    clean_dir = study_dir / "dados" / "clean"
    clean_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "data": ["2020-01-01", "2020-01-01"],
            "regiao": ["", ""],
            "sexo": ["", ""],
            "idade": ["", ""],
            "indicador": ["x", "y"],
            "valor": [1.0, 2.0],
            "unidade": ["n", "n"],
            "fonte_id": ["f1", "f2"],
        }
    ).to_parquet(clean_dir / "dados.parquet")

    studies = mod.load_studies()
    mod.copy_study_pages(studies[0])

    out_csv = site_dir / "estudos" / "saude-portugal" / "dados_abertos.csv"
    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert set(df["fonte_id"]) == {"f1"}
