"""Human review gate: a study is published only after its author approves this exact version.

The pipeline verifies claims by code, but it cannot judge whether a report is balanced, well framed or worth
publishing, and the About page says verification does not replace editorial review. So phase 8 no longer publishes:

    verified  ->  status: ready_for_review  ->  approve  ->  status: published   (+ review.json)

`review.json` records who approved, when, which checklist items were ticked, and a digest of the content that was
approved (reports, claims, chart registry, titles). The public build and the auto-push only treat a study as published
when `review.json` exists and its digest still matches the files, so an edit after approval, or an agent writing
`status: published` by itself, never reaches the public site: the study goes back to `ready_for_review`.

Requesting changes reopens the study at a phase (the writing phase by default) with the reviewer's comment in
`decisions.md`, which the `/study` flow reads before anything else.

    uv run python -m common.review show <slug>                       # the checklist, computed from the files
    uv run python -m common.review approve <slug> --by NAME --confirm-all
    uv run python -m common.review changes <slug> "what to change" [--phase 6]
    uv run python -m common.review legacy <slug> --by NAME          # a study published before this gate existed
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

from common.csv_io import read_csv
from common.schemas import Claim, DataSource, EventLink

REPO = Path(__file__).resolve().parent.parent
STUDIES_ROOT = REPO / "studies"
REVIEW_FILE = "review.json"
READY, PUBLISHED = "ready_for_review", "published"
LIMITATIONS = re.compile(r"^#{1,4}\s.*(limita|limitations)", re.IGNORECASE | re.MULTILINE)
DIGEST_FILES = ("report.pt.qmd", "report.en.qmd", "claims.csv", "analysis/charts.yml")
DIGEST_META = ("title_pt", "title_en", "summary_pt", "summary_en")
CHECKS = ("report_pt", "report_en", "limitations", "removed_claims", "strong_links", "licences", "editorial")


class ReviewError(Exception):
    pass


def _study(slug: str, root: Path | None = None) -> Path:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", slug or ""):
        raise ReviewError("invalid study slug")
    path = (root or STUDIES_ROOT) / slug
    if not (path / "study.yml").exists():
        raise ReviewError(f"unknown study '{slug}'")
    return path


def read_meta(study_dir: Path) -> dict:
    return yaml.safe_load((study_dir / "study.yml").read_text(encoding="utf-8")) or {}


def set_status(study_dir: Path, status: str) -> None:
    meta = read_meta(study_dir)
    meta["status"] = status
    (study_dir / "study.yml").write_text(yaml.safe_dump(meta, allow_unicode=True, sort_keys=False), encoding="utf-8")


def content_digest(study_dir: Path) -> str:
    """Hash of what a reader would see: the reports, the claims, the chart registry and the titles."""
    h = hashlib.sha256()
    for name in DIGEST_FILES:
        path = study_dir / name
        h.update(name.encode() + b"\0" + (path.read_bytes() if path.exists() else b"") + b"\0")
    meta = read_meta(study_dir)
    h.update(json.dumps({k: meta.get(k) for k in DIGEST_META}, ensure_ascii=False, sort_keys=True).encode())
    return h.hexdigest()


def read_review(study_dir: Path) -> dict | None:
    path = study_dir / REVIEW_FILE
    try:
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
    except ValueError:
        return None


def is_approved(study_dir: Path) -> bool:
    """True only when review.json exists and still matches the content (an edit after approval un-approves)."""
    review = read_review(study_dir)
    return bool(review and review.get("approved_at") and review.get("approved_by") and review.get("digest") == content_digest(study_dir))


def mark_ready(study_dir: Path) -> str:
    """After the pipeline's last phase: a study is `ready_for_review`, never self-published. Returns the status."""
    status = read_meta(study_dir).get("status")
    if status == "test":
        return "test"
    if status == PUBLISHED and is_approved(study_dir):
        return PUBLISHED
    set_status(study_dir, READY)
    return READY


def _verification_failed_ids(study_dir: Path) -> list[str]:
    path = study_dir / "verification.md"
    if not path.exists():
        return []
    return re.findall(r"^- (c\d+): failed", path.read_text(encoding="utf-8"), flags=re.MULTILINE)


def packet(study_dir: Path) -> dict:
    """What the reviewer should look at, computed from the files (nothing typed by an agent)."""
    meta = read_meta(study_dir)
    slug = study_dir.name
    claims = read_csv(study_dir / "claims.csv", Claim)
    kept = {c.id for c in claims}
    removed = sorted(set(_verification_failed_ids(study_dir)) - kept)
    links = [link for link in read_csv(study_dir / "event_links.csv", EventLink) if link.status == "linked"]
    strong = [link for link in links if link.grade in ("A", "B")]
    sources = [s for s in read_csv(study_dir / "sources.csv", DataSource) if s.status == "tested"]
    licences: dict[str, int] = {}
    for s in sources:
        licences[s.license] = licences.get(s.license, 0) + 1
    reports = {lang: (study_dir / f"report.{lang}.qmd") for lang in ("pt", "en")}
    texts = {lang: p.read_text(encoding="utf-8") if p.exists() else "" for lang, p in reports.items()}
    lacking = [lang.upper() for lang, t in texts.items() if not LIMITATIONS.search(t)]
    charts_path = study_dir / "analysis" / "charts.yml"
    charts = (yaml.safe_load(charts_path.read_text(encoding="utf-8")) or {}) if charts_path.exists() else {}
    kinds: dict[str, int] = {}
    for entry in charts.values():
        kinds[str(entry.get("kind") or "?")] = kinds.get(str(entry.get("kind") or "?"), 0) + 1

    def item(id_: str, label_pt: str, label_en: str, detail: str, warning: bool = False) -> dict:
        return {"id": id_, "label_pt": label_pt, "label_en": label_en, "detail": detail, "warning": warning}

    checklist = [
        item("report_pt", "Li o relatório em português, do princípio ao fim", "I read the Portuguese report in full",
             f"{len(texts['pt'].split())} palavras"),
        item("report_en", "Li o relatório em inglês (ou confirmei que corresponde ao PT)", "I read the English report (or checked it matches the Portuguese)",
             f"{len(texts['en'].split())} words"),
        item("limitations", "A secção de limitações diz o que o estudo não cobre", "The limitations section says what the study does not cover",
             "secção encontrada em PT e EN" if not lacking else f"SEM secção de limitações em: {', '.join(lacking)}", warning=bool(lacking)),
        item("removed_claims", "Vi as afirmações removidas na verificação e a nota de omissão", "I saw the claims removed during verification and the omission note",
             f"{len(removed)} removida(s): {', '.join(removed[:12]) or 'nenhuma'}", warning=bool(removed)),
        item("strong_links", "Revi as ligações de grau A ou B (a linguagem causal)", "I reviewed the grade A or B links (causal wording)",
             f"{len(strong)} de {len(links)} ligações: {', '.join(l_.event_id or '?' for l_ in strong[:8]) or 'nenhuma, todas de grau C'}", warning=bool(strong)),
        item("licences", "As licenças das fontes permitem esta publicação", "The sources' licences allow this publication",
             "; ".join(f"{n}× {lic}" for lic, n in sorted(licences.items())) or "sem fontes testadas", warning=not licences),
        item("editorial", "Assumo a responsabilidade editorial por este estudo", "I take editorial responsibility for this study",
             f"{len(claims)} afirmações, {sum(c.verification_status == 'confirmed' for c in claims)} confirmadas por código · gráficos: "
             + (", ".join(f"{k} {v}" for k, v in sorted(kinds.items())) or "nenhum")),
    ]
    review = read_review(study_dir)
    return {
        "slug": slug, "title_pt": meta.get("title_pt", slug), "title_en": meta.get("title_en", slug),
        "status": meta.get("status", ""), "checklist": checklist,
        "approved": is_approved(study_dir), "stale_approval": bool(review and not is_approved(study_dir)),
        "preview": {"pt": f"/pt/studies/{slug}/index.html", "en": f"/en/studies/{slug}/index.html"},
    }


def approve(study_dir: Path, *, by: str, checked: list[str], now: datetime | None = None) -> dict:
    """Record the approval of the current content and publish. All checklist items must be ticked."""
    by = (by or "").strip()
    if not by:
        raise ReviewError("say who approves (a name or handle)")
    missing = [c for c in CHECKS if c not in set(checked)]
    if missing:
        raise ReviewError(f"checklist not complete: {', '.join(missing)}")
    if read_meta(study_dir).get("status") == "test":
        raise ReviewError("a test study is not published")
    record = {
        "approved_by": by[:80], "approved_at": (now or datetime.now(UTC)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "checked": list(CHECKS), "digest": content_digest(study_dir), "legacy": False,
    }
    (study_dir / REVIEW_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    set_status(study_dir, PUBLISHED)
    return record


def approve_legacy(study_dir: Path, *, by: str) -> dict:
    """For a study published before the gate existed: record that, honestly, instead of pretending it was reviewed.

    Only the author runs this (command line); no agent records an approval on the author's behalf."""
    record = {
        "approved_by": by, "approved_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"), "checked": [],
        "digest": content_digest(study_dir), "legacy": True,
        "note": "published before the review gate existed; the author released it without the checklist",
    }
    (study_dir / REVIEW_FILE).write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return record


def request_changes(slug: str, comment: str, *, phase: int = 6, root: Path | None = None) -> None:
    """Reopen the study at `phase` with the reviewer's comment in decisions.md."""
    from common import state

    comment = (comment or "").strip()
    if not comment:
        raise ReviewError("say what to change")
    if len(comment) > 2000:
        raise ReviewError("comment longer than 2000 characters")
    study_dir = _study(slug, root)
    stamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    decisions = study_dir / "decisions.md"
    header = "" if decisions.exists() else "# Decisões do utilizador\n"
    with decisions.open("a", encoding="utf-8") as f:
        f.write(f"{header}\n## Revisão: alterações pedidas ({stamp})\n\n{comment}\n")
    state.reopen(slug, phase)
    set_status(study_dir, "in_progress")


def pending_reviews(root: Path | None = None) -> list[dict]:
    """Packets of every study waiting for review."""
    base = root or STUDIES_ROOT
    out = []
    for study_yml in sorted(base.glob("*/study.yml")):
        if (yaml.safe_load(study_yml.read_text(encoding="utf-8")) or {}).get("status") == READY:
            out.append(packet(study_yml.parent))
    return out


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    try:
        if args[:1] == ["show"] and len(args) == 2:
            p = packet(_study(args[1]))
            print(f"{p['slug']} | status: {p['status']} | approved: {p['approved']}")
            for c in p["checklist"]:
                print(f"[{'!' if c['warning'] else ' '}] {c['id']}: {c['label_en']}\n      {c['detail']}")
            return 0
        if args[:1] == ["approve"] and len(args) >= 2:
            by = args[args.index("--by") + 1] if "--by" in args else ""
            if "--confirm-all" not in args:
                print("approving ticks every checklist item for you: read `show` first, then repeat with --confirm-all", file=sys.stderr)
                return 2
            record = approve(_study(args[1]), by=by, checked=list(CHECKS))
            print(f"approved by {record['approved_by']} at {record['approved_at']}; status: published")
            return 0
        if args[:1] == ["legacy"] and len(args) >= 2:
            by = args[args.index("--by") + 1] if "--by" in args else ""
            if not by.strip():
                print("say who is recording this: --by NAME", file=sys.stderr)
                return 2
            record = approve_legacy(_study(args[1]), by=by.strip())
            print(f"recorded by {record['approved_by']}: {args[1]} was published before the review gate (not reviewed with the checklist)")
            return 0
        if args[:1] == ["changes"] and len(args) >= 3:
            phase = int(args[args.index("--phase") + 1]) if "--phase" in args else 6
            request_changes(args[1], args[2], phase=phase)
            print(f"reopened {args[1]} at phase {phase}; run it again from the queue")
            return 0
    except ReviewError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
