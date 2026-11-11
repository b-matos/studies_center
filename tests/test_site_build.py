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
    studies_dir = tmp_path / "studies"
    studies_dir.mkdir()
    events_csv = tmp_path / "events" / "events.csv"
    events_csv.parent.mkdir()
    events_csv.write_text(
        "id,start_date,end_date,ambito,tipo,title_pt,title_en,description_pt,description_en,"
        "primary_source_url,secondary_source_url,access_date,temas,verificado\n"
        "e1,2020-03-01,,PT,pandemia_ou_crise_sanitaria,Covid,Covid,x,x,https://dgs.pt,,2026-01-01,saude,sim\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "SITE_DIR", site_dir)
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod, "STUDIES_DIR", studies_dir)
    monkeypatch.setattr(mod, "EVENTS_CSV", events_csv)
    return mod, site_dir, studies_dir


def _make_study(studies_dir: Path, slug: str, status: str = "published") -> Path:
    study_dir = studies_dir / slug
    study_dir.mkdir()
    (study_dir / "study.yml").write_text(
        yaml.safe_dump(
            {
                "title_pt": f"Estudo {slug}",
                "title_en": f"Study {slug}",
                "summary_pt": "Resumo.",
                "summary_en": "Summary.",
                "date": "2026-11-07",
                "status": status,
            },
            allow_unicode=True,
        ),
        encoding="utf-8",
    )
    (study_dir / "report.pt.qmd").write_text("# Relatório\n\nTexto.", encoding="utf-8")
    (study_dir / "report.en.qmd").write_text("# Report\n\nText.", encoding="utf-8")
    return study_dir


def test_write_index_excludes_teste_studies(build_mod) -> None:
    mod, site_dir, studies_dir = build_mod
    _make_study(studies_dir, "publicado-1", status="published")
    _make_study(studies_dir, "teste-1", status="test")

    studies = mod.load_studies()
    mod.write_index(studies, "pt")

    index_text = (site_dir / "index.pt.qmd").read_text(encoding="utf-8")
    assert "publicado-1" in index_text
    assert "teste-1" not in index_text


def test_copy_study_pages_injects_output_file_front_matter(build_mod) -> None:
    mod, site_dir, studies_dir = build_mod
    _make_study(studies_dir, "saude-portugal")
    studies = mod.load_studies()
    mod.copy_study_pages(studies[0])

    pt_copy = (site_dir / "studies" / "saude-portugal" / "index.pt.qmd").read_text(encoding="utf-8")
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
    assert 'url=pt/' in text  # relative, so it also works under a Pages subpath


def test_export_events_json(build_mod) -> None:
    mod, site_dir, _ = build_mod
    mod.export_events_json()
    data = json.loads((site_dir / "events.json").read_text(encoding="utf-8"))
    assert len(data) == 1
    assert data[0]["id"] == "e1"


def test_export_open_clean_data_excludes_nc_licensed_sources(build_mod) -> None:
    mod, site_dir, studies_dir = build_mod
    study_dir = _make_study(studies_dir, "saude-portugal")
    (study_dir / "sources.csv").write_text(
        "id,axis,name,organisation,url,format,license,temporal_coverage,geographic_coverage,status,exclusion_reason,verification_date\n"
        "f1,mortalidade,x,INE,https://ine.pt,csv,CC-BY,2000-2020,PT,tested,,2026-01-01\n"
        "f2,mortalidade,y,OMS,https://who.int,csv,CC-BY-NC,2000-2020,PT,tested,,2026-01-01\n",
        encoding="utf-8",
    )
    clean_dir = study_dir / "data" / "clean"
    clean_dir.mkdir(parents=True)
    pd.DataFrame(
        {
            "date": ["2020-01-01", "2020-01-01"],
            "region": ["", ""],
            "sex": ["", ""],
            "age": ["", ""],
            "indicator": ["x", "y"],
            "value": [1.0, 2.0],
            "unit": ["n", "n"],
            "source_id": ["f1", "f2"],
        }
    ).to_parquet(clean_dir / "dados.parquet")

    studies = mod.load_studies()
    mod.copy_study_pages(studies[0])

    out_csv = site_dir / "studies" / "saude-portugal" / "open_data.csv"
    assert out_csv.exists()
    df = pd.read_csv(out_csv)
    assert set(df["source_id"]) == {"f1"}


def test_charts_js_only_reads_canonical_column_names() -> None:
    """charts.js reads the long-format JSON rows; a stale column name silently empties every chart."""
    import re

    from common.normalize import CANONICAL_COLUMNS

    js = (REPO_ROOT / "site" / "assets" / "charts.js").read_text(encoding="utf-8")
    used = set(re.findall(r"\b[abdr]\.(\w+)\b", js))
    row_fields = used & {"data", "date", "valor", "value", "regiao", "region", "unidade", "unit", "sexo", "sex"}
    assert row_fields <= set(CANONICAL_COLUMNS), f"stale column names in charts.js: {row_fields - set(CANONICAL_COLUMNS)}"


def test_public_index_lists_only_published_studies(build_mod) -> None:
    mod, site_dir, studies_dir = build_mod
    _make_study(studies_dir, "done-1", status="published")
    _make_study(studies_dir, "wip-1", status="in_progress")
    _make_study(studies_dir, "teste-1", status="test")

    studies = mod.load_studies()
    mod.write_index(studies, "en", {"published"})
    text = (site_dir / "index.en.qmd").read_text(encoding="utf-8")
    assert "done-1" in text
    assert "wip-1" not in text
    assert "teste-1" not in text

    mod.write_index(studies, "en", {"published", "test"})
    assert "teste-1" in (site_dir / "index.en.qmd").read_text(encoding="utf-8")


def test_write_public_profiles_drops_queue(build_mod) -> None:
    mod, site_dir, _ = build_mod
    for lang, other in (("pt", "en"), ("en", "pt")):
        (site_dir / f"_quarto-{lang}.yml").write_text(
            yaml.safe_dump({
                "project": {"output-dir": f"_site/{lang}", "render": [f"index.{lang}.qmd", f"queue.{lang}.qmd"]},
                "website": {"navbar": {
                    "left": [{"href": f"index.{lang}.qmd", "text": "A"}, {"href": f"queue.{lang}.qmd", "text": "Q"}],
                    "right": [{"text": other.upper(), "href": f"/{other}/"}],
                }},
            }),
            encoding="utf-8",
        )

    mod.write_public_profiles()

    cfg = yaml.safe_load((site_dir / "_quarto-pt-public.yml").read_text(encoding="utf-8"))
    assert cfg["project"]["output-dir"] == "_site_public/pt"
    assert cfg["project"]["render"] == ["index.pt.qmd"]
    assert [i["href"] for i in cfg["website"]["navbar"]["left"]] == ["index.pt.qmd"]


def test_public_assets_leave_out_queue_script(build_mod) -> None:
    mod, site_dir, _ = build_mod
    assets_src = site_dir / "assets"
    assets_src.mkdir()
    (assets_src / "lang-switch.js").write_text("// js", encoding="utf-8")
    (assets_src / "queue.js").write_text("// queue", encoding="utf-8")
    (site_dir / "_site_public").mkdir()

    mod.copy_shared_assets("_site_public", public=True)
    assert (site_dir / "_site_public" / "assets" / "lang-switch.js").exists()
    assert not (site_dir / "_site_public" / "assets" / "queue.js").exists()


def test_index_card_shows_title_and_summary_and_links_only_studies_with_a_report(build_mod) -> None:
    mod, site_dir, studies_dir = build_mod
    _make_study(studies_dir, "has-report", status="published")
    pending = _make_study(studies_dir, "no-report", status="in_progress")
    (pending / "report.pt.qmd").unlink()

    mod.write_index(mod.load_studies(), "pt")
    text = (site_dir / "index.pt.qmd").read_text(encoding="utf-8")
    assert "Estudo has-report" in text and "Resumo." in text  # title_pt / summary_pt, not the slug
    assert 'href="studies/has-report/index.html"' in text
    assert 'href="studies/no-report/index.html"' not in text
    assert "study-card-pending" in text and "Estudo no-report" in text


def test_study_header_links_the_shared_data_directory(build_mod) -> None:
    mod, _, studies_dir = build_mod
    _make_study(studies_dir, "demo-1")
    study = mod.load_studies()[0]
    text = mod._inject_study_header("---\ntitle: x\n---\nbody", study, "en", has_data=True)
    assert 'href="../../../data/demo-1/open_data.csv"' in text
    assert 'href="../../../data/demo-1/open_data_sources.csv"' in text


def test_publish_open_data_copies_once_for_both_languages(build_mod) -> None:
    mod, site_dir, _ = build_mod
    out = site_dir / "studies" / "demo-1"
    out.mkdir(parents=True)
    (out / "open_data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (out / "open_data_sources.csv").write_text("id\ns1\n", encoding="utf-8")
    (site_dir / "_site").mkdir()

    mod.publish_open_data("_site")
    mod.publish_open_data("_site")  # rebuilds replace the folder

    shared = site_dir / "_site" / "data" / "demo-1"
    assert sorted(f.name for f in shared.iterdir()) == ["open_data.csv", "open_data_sources.csv"]


def test_build_lock_makes_a_second_build_wait(build_mod) -> None:
    import threading

    mod, _, _ = build_mod
    entered = threading.Event()

    def second_build() -> None:
        with mod.build_lock():
            entered.set()

    with mod.build_lock():
        thread = threading.Thread(target=second_build, daemon=True)
        thread.start()
        assert not entered.wait(0.4)  # blocked while the first build holds the lock
    assert entered.wait(3)
    thread.join(3)
