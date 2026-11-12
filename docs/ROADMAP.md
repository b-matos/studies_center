# Roadmap and ideas

Ideas for evolving the platform, in the order I would do them. The short list of hardening items is in the
[README](../README.md#improvement-ideas); this file holds the larger directions and the reasoning behind them.
Nothing here is committed work: each item says what it reuses, what is new and what could go wrong.

## Priorities

| # | Item | Why now | Effort |
| --- | --- | --- | --- |
| 1 | Human review gate before publishing | More output modes make an unreviewed `published` riskier | Small |
| 2 | Evals for the agents | Needed before adding modes without regressions | Medium |
| 3 | `/mito`: claim checking | Best return: reuses nearly everything, cheaper and more shareable than a study | Medium |
| 4 | Living studies (scheduled re-extraction) | Keeps published numbers true; almost no token cost | Small |
| 5 | Citation and discovery (DOI, RSS, share cards) | Cheap credibility | Small |
| 6 | Automatic counter-argument and limitations | Strengthens principle 3 | Medium |
| 7 | Maps and regional breakdowns | Visual appeal; `common/geo.py` is the start | Medium |
| 8 | `/impacto`: policy impact analysis | Differentiating, but short annual series limit it | Large |

## 1. Human review gate

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

NUTS III and municipality levels, choropleths in the chart component, and a rule for when a regional comparison is
meaningful (enough population per unit, comparable periods). Needs the full NUTS lists in `common/geo.py`.

## 8. `/impacto`: policy impact analysis

Interrupted time series with placebo tests and, where a comparison group exists, difference-in-differences or
synthetic control, to support evidence grade B with an explicit method. Powerful but demanding: most series here are
annual and short, so the command should refuse when there are too few points before the intervention.

## Other ideas, not scheduled

- **Orchestrator in code** with the Claude Agent SDK, keeping agents and hooks (already in the README).
- **dados.gov.pt as a source** is implemented; next is the first study that exercises its full cycle (extract,
  manifest, provenance chain).
- **A reader glossary and "what we know" index** linking studies through the shared events catalogue.
- **Accessibility pass:** alt text and a table alternative for every chart, keyboard navigation of the chart controls.
- **Self-host Plotly** to remove the last third-party request from the public site.
- **Per-agent metrics view** (attempts, failures per phase, cost per quality point) from `usage.csv` and `state.json`.
