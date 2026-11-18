# Roadmap and ideas

Ideas for evolving the platform, in the order I would do them. The short list of hardening items is in the
[README](../README.md#improvement-ideas); this file holds the larger directions and the reasoning behind them.
Nothing here is committed work: each item says what it reuses, what is new and what could go wrong.

## Priorities

| # | Item | Why now | Effort |
| --- | --- | --- | --- |
| 1 | Human review gate before publishing | **Done** (see section 1) | Small |
| 2 | Evals for the agents | Needed before adding modes without regressions | Medium |
| 3 | `/mito`: claim checking | Best return: reuses nearly everything, cheaper and more shareable than a study | Medium |
| 4 | Living studies (scheduled re-extraction) | Keeps published numbers true; almost no token cost | Small |
| 5 | Citation and discovery (DOI, RSS, share cards) | Cheap credibility | Small |
| 6 | Automatic counter-argument and limitations | Strengthens principle 3 | Medium |
| 7 | Maps and regional breakdowns | **Mostly done** (NUTS II/III maps); municipalities pending | Medium |
| 8 | `/impacto`: policy impact analysis | Differentiating, but short annual series limit it | Large |
| 9 | Recent news as context | Helps readers; needs items 1 and 4 first | Medium |
| 10 | Reader questions and "more detail" requests | Phased: no live model first | Small, then Large |
| 11 | Chart catalogue and chart choice | **Done** (see section 11): improves every study | Medium |
| 12 | Share page (infographic card) | Makes a study easy to share; depends on item 11 | Medium |
| 13 | Study search and tag filters | Readers can find studies as their number grows; Quarto text search already exists | Small |

## 1. Human review gate

**Status: implemented** (`common/review.py`, the Queue page, `review.json`). The text below is the original plan; what
shipped differs in one way: approval is bound to a digest of the content, so editing after approval removes it.

Today phase 8 sets `status: published` by itself, while the About page says automatic verification does not replace
editorial review. Add a state between verified and published:

- `status: ready_for_review` after phase 7; phase 8 builds the preview but does not publish.
- The Queue page shows a checklist (read both reports, the limitations, the removed claims, the grade-A links) and
  an **Approve** button that sets `published` and records who approved and when.
- `STUDIES_AUTO_PUSH` only pushes approved studies. The licence gate and verification stay in code; this adds the
  one judgement that code cannot make.
- If the author reviews every study, the About page can then say so truthfully.

## 2. Evals for the agents

Only deterministic code is tested today. Frozen fixtures (a commit per phase already exists for each study) plus code
graders: inject errors into a verified report to measure the `verifier`'s recall and false positives; give the
`historian` coincidence-only cases that must be grade C; give the `writer` numbers outside `claims.csv`. Run each
case three times, store results in `evals/results/`, and compare before and after any prompt or model change.
It also tells which agents can move from Opus to Sonnet.

## 3. `/mito <claim>`: claim checking

A command that starts from an assertion ("Portugal has the lowest life expectancy in the EU") instead of a topic.

**Reuses:** data-researcher, extractor, provenance chain, verifier, `claims.csv`, the bilingual page, the licence gate.

**What is new**

| Phase | What happens |
| --- | --- |
| 1. Decompose | The claim becomes testable hypotheses. Before looking at any data, fix what "true" would mean (metric, period, comparison group, threshold). This is committed, so the test cannot be chosen after seeing the data. |
| 2-3. Sources, extraction | Same as a study, but with one or two axes. |
| 4. Compute | A script computes the test statistic from `data/clean/`. |
| 5. Verdict | Chosen by rule from the pre-registered thresholds, applied by code. The model only writes the explanation. |
| 6-8. Write, verify, publish | A short page (about 600 words): the verdict, three numbers, one chart, the limitations. |

**Verdict scale:** true, partly true, misleading (true but out of context), false, not enough data. "Not enough data" is
a legitimate outcome and must never be forced into another one.

**Editorial rules**

- Do not attribute the claim to a person or a party (defamation risk). Use "the idea circulates that...".
- An ambiguous claim stops at `pending.md` and the author decides how to read it.
- Same evidence-grade language as studies: a verdict never asserts a cause that no source states.
- A new content type in `study.yml` (`kind: myth`), a distinct card on the index, and its own section in the nav.

**Open questions:** health myths only, or also sensitive political topics (fiscal policy, immigration)? The latter
needs stronger editorial rules and the review gate above. Who proposes myths: only the author, or readers through a
GitHub issue? Accepting outside text needs validation and a manual triage, to avoid abuse and prompt injection.

## 4. Living studies

A scheduled GitHub Action (monthly) repeats `common.extract` and compares the raw files' SHA-256 with the manifest.

- A revised series triggers re-analysis only for that study and shows "updated on" plus what changed in the headline
  numbers.
- A published claim that no longer recomputes opens an alert instead of staying silently wrong.
- Keep raw snapshots (release assets or a bucket) so an old report stays verifiable after a source revises its data.
- Cost is almost only network time; tokens are spent only when something changed.

## 5. Citation and discovery

DOI per study (a GitHub release archived by Zenodo), a "How to cite" block, RSS, Open Graph cards for sharing, a
per-study revision log (version and date), and a public methodology page that explains how claims are verified.

## 6. Automatic counter-argument and limitations

- A `critic` agent tries to refute the conclusions and proposes alternative readings; the writer must answer each one
  or state it as a limitation.
- A limitations section generated by code: short series, breaks with no linked event, correlations that are not
  significant after correction, series the analysis derived rather than took from a source.

## 7. Maps and regional breakdowns

**Status: NUTS II and III implemented** for NUTS 2021 and 2024 (`common/geo.py`, boundaries in `site/assets/geo/`, the `map`
chart kind, code rules for a meaningful comparison). **Pending:** municipality (concelho) boundaries and maps, which need
the DGT's CAOP (large; its licence must be checked and the file simplified), and a population-aware rule for small units.
The text below is the original plan.

NUTS III and municipality levels, choropleths in the chart component, and a rule for when a regional comparison is
meaningful (enough population per unit, comparable periods). Needs the full NUTS lists in `common/geo.py`.

## 8. `/impacto`: policy impact analysis

Interrupted time series with placebo tests and, where a comparison group exists, difference-in-differences or
synthetic control, to support evidence grade B with an explicit method. Powerful but demanding: most series here are
annual and short, so the command should refuse when there are too few points before the intervention.

## 9. Recent news as context

A "Recent context" section on a study page: relevant news about the topic, so a reader sees what happened after the
study was written.

- Strictly context. Always `source_nature = news`; never used to support a grade A or B link, and never a claim in
  `claims.csv`. Each entry is a link, the outlet, the date and one neutral sentence in our own words (no copied text).
- Outlets come from an allow-list of credible sources; a news item that makes a factual claim points to the primary
  source when one exists.
- Candidates are found by a scheduled job (the living-studies Action) and land in the Queue as proposals. Nothing is
  published without approval, so it depends on the review gate (item 1) and on item 4.
- Risks: editorial bias in what is chosen (keep the allow-list and the criteria public), copyright (links and short
  paraphrase only), paywalled or JavaScript pages the verifier cannot open (record the date accessed and keep the
  entry out of `claims.csv`), and dilution of the data-first identity (a short list, not a news feed).

## 10. Reader questions and "more detail" requests

Staged, so that the principle "no claim without a source" is never traded for convenience.

1. **No live model.** Filters on the charts (region, sex, age) already give much of the "more detail". Add an
   "Ask for more detail" button that opens a GitHub issue from a template. The author triages; an accepted request
   becomes an addendum to the study produced by the normal pipeline, with its own claims and verification.
2. **Extractive Q&A, only if there is demand.** A small backend answers using only the study's verified claims and
   series: it quotes claim ids with their sources and says "I don't know" by default. Needs a hard cost cap, rate
   limits, protection against prompt injection, an AI notice, and a policy of not storing personal data or questions
   beyond what is needed.
3. **Generative answers are out of scope**: they would be new text the pipeline has not verified.

## 11. Chart catalogue and chart choice

**Status: implemented** (kinds, per-chart `kind`/`why`, code checks, writer guide, gallery in `docs/charts-gallery.html`).
Still open from this item: a choropleth (needs the geography work in item 7). The text below is the original plan.

The chart component (`site/assets/charts.js`) has two chart types, `timeSeries` and `ranking`, plus a table. In the first
real study that meant 21 line charts and 6 rankings. The writer is told never to hand-write Plotly, which is right
(every chart gets the same legend, tooltips, zoom, PNG download and event overlay), so the answer is a bigger
catalogue behind the same shell, not looser code.

- **New types**, each with the shell above and a table alternative: grouped bars, stacked bars, stacked area,
  slope chart (before and after), dumbbell (two dates per region), small multiples (one series per panel), scatter
  with the year as colour, heatmap (year by region) and, once geography is in place, a choropleth.
- **Who chooses.** The `analyst` knows the data: it records `kind` and a one-line `why` for every chart in
  `charts.yml`. The `writer` may switch to another type that is allowed for that data shape, and decides which
  charts to show and in what order. The set of allowed types is derived from the data's shape by code.
- **Checks in code** (phase 4 and phase 6): a line chart needs enough points (6 or more); no pie or stacked bars with
  many categories; bars start at zero; more than 8 series become small multiples; every chart has a title, a unit on
  the axis, alt text and a table alternative.
- **A guide in `writer.md`**: question to chart type (evolution, comparison, composition, ranking, before and after,
  relation between two variables, regional distribution).

## 12. Share page (infographic card)

A page per study (`/share/<slug>`) in a vertical card format, and a 1200x630 image for social networks. Both are
generated by code, never drawn by hand.

- **Content:** the title, three key numbers, one main chart, the evidence-grade sentence ("coincided with") and the
  attribution (sources, licence, study address).
- **Integrity rule:** every number on the card references a `claims.csv` id that is already `confirmed`, and its value is
  copied from the claim, never typed. The author picks them in `study.yml` (`share: [c012, c040, c101]`) and the
  build refuses ids that are not confirmed. A card keeps the caveat next to the number, not only the number.
- **Look: nothing that reads as AI-generated.** No gradients or glow, no glassmorphism, no emoji or decorative icons,
  no sparkle marks, no stock or generated illustrations, no rounded cards with a coloured left border, no purple-blue
  palette, no generic "feature grid". Aim for the restraint of a statistics office or a newspaper data desk: the
  site's own type (Fraunces and Inter), one accent colour, a strict grid, large figures, generous whitespace, thin
  rules and real data-ink. Ornament has to carry information or go.
- **Disclosure stays, plainly.** Transparency about AI assistance is a legal and ethical commitment (see the About page),
  separate from the look: one short line of plain text ("Written with AI assistance and verified by code; see
  About"), with no AI-themed visual.
- Other checks: alt text for the image, contrast, no truncated axes, and the licence line on the card.
- The visual direction can be iterated on the Claude Design canvas, adding a card artboard there.

## 13. Study search and tag filters

A static site can filter and search entirely in the browser, over files generated at build time.

**What exists.** Quarto's built-in full-text search is already on (the "Procurar" box in the navbar, backed by a
`search.json` of about 55 KB with one entry per study section, in each language). What is missing is tags and filters on the
index page: `study.yml` has no tags today.

**Plan**

1. **`studies.json` and filters on the index (first).** `site/build.py` already reads every `study.yml`; it also writes a
   `studies.json` with title, summary, date, content type (study, and later myth), tags and sources. The index page gets a
   text box and filter chips (topic, provider, year, type), in plain JavaScript with no dependencies and no third-party
   requests. Filters and text combine, and the state lives in the URL (`?topic=health&q=mortality`) so a filtered view can
   be shared.
2. **Tags come from code, not from typing.** Topics from the axes in `plan.md`, providers from `sources.csv` (INE, Eurostat,
   DGS...), regions and period from the data. The `planner` may propose 3 to 6 topic tags, and the code validates them against
   a controlled list, so "saúde", "Saude" and "saúde pública" never become different labels.
3. **Text search inside studies.** Keep Quarto's for now (fine for dozens of studies) and improve what it indexes (chart
   titles, perhaps the verified claims). Move to Pagefind (indexes the final HTML, scales better, supports filters) only when
   the number of studies makes the Quarto index heavy; self-host its files to avoid third-party requests.
4. **Cheap extras.** Topic pages (`/pt/topics/health.html`) generated from the same tags, good for sharing and search engines,
   and "related studies" by shared tags and sources.

**Limits.** Client-side search loads the whole index: fine up to a few hundred studies. There is no semantic search without a
backend; for a curated set of studies, text plus tags is enough. Indexing `claims.csv` would let a search return verified
claims, but it makes the index bigger, so only if readers need it.

**Depends on:** nothing. It also prepares the `/mito` type (item 3), which needs its own filter value.

## Other ideas, not scheduled

- **Orchestrator in code** with the Claude Agent SDK, keeping agents and hooks (already in the README).
- **dados.gov.pt as a source** is implemented; next is the first study that exercises its full cycle (extract,
  manifest, provenance chain).
- **A reader glossary and "what we know" index** linking studies through the shared events catalogue.
- **Accessibility pass:** alt text and a table alternative for every chart, keyboard navigation of the chart controls.
- **Self-host Plotly** to remove the last third-party request from the public site.
- **Per-agent metrics view** (attempts, failures per phase, cost per quality point) from `usage.csv` and `state.json`.
