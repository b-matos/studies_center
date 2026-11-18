# Agent evals

The platform's deterministic code is covered by `tests/`. This folder tests the **agents**: does the `historian` ever grade a
coincidence above C, does the `writer` invent a number, does the `verifier` catch a corrupted claim? A change to a prompt or a
model can break these silently, so they are measured before and after.

## How it works

1. **Fixtures are synthetic and built by code** (`fixtures.py`): a tiny fictional study with known traps, so a correct answer
   is known exactly. No binary files in git, and nothing from the real studies.
2. **One sandbox per run** (`sandbox.py`): a copy of the working tree (your edited `.claude/agents/*.md` is what gets
   evaluated) plus the fixture. The real `studies/`, `events/` and git history are never touched.
3. **One agent per run** (`run.py`): `claude -p --agent <name>` headlessly, with the case's tools (the web is denied where a case
   is meant to be offline).
4. **Graders are code** (`graders.py`): no model judges the output. Each result is `critical` (breaks a platform principle) or
   `quality`.
5. **Results are history** (`results/runs.csv`): one row per grader per run, with cost and tokens. `report.py` compares batches.

## Cases

| Agent | Case | What it checks |
| --- | --- | --- |
| `historian` | `coincidence_traps` | Events whose source only says they happened are never graded above C; an unrelated old event is never linked; no invented events; the event whose source states the effect is recognised (A or B); writes only its own files |
| `writer` | `write_pt_en` | The phase 6 check passes; every number traces to an input; no invented URL; PT and EN use the same claim ids; no causal wording about coincidence-only events |
| `writer` | `write_en_only` | The English unit alone: translates an existing Portuguese report, reuses every claim id, leaves `claims.csv` and the PT report untouched, adds or drops no figure, and is really English. Used to decide whether a cheaper model can write this unit |
| `verifier` | `injected_faults` | Four injected faults (altered date, dead URL, excerpt on another page, altered number) are all failed, and intact claims are not; only `verification_status` changes |

## Commands

```bash
uv run python -m evals.run historian --dry-run      # build and grade the sandbox without running the agent (no tokens)
uv run python -m evals.run historian                # one real run (costs tokens)
uv run python -m evals.run writer --n 3             # three runs: agents vary, read the pass rate and the worst case
uv run python -m evals.run verifier --model sonnet  # override the agent's model, for example to test a cheaper one
uv run python -m evals.report                       # latest batch vs the previous one, per grader
```

A real run exits non-zero if any `critical` grader failed. Commit `results/runs.csv` after a meaningful batch; the raw streams
in `results/logs/` are git-ignored.

## Adding a case

Write it in `cases/<agent>.yaml` (fixture options, prompt, tools, graders). If it needs a new check, add a function to
`graders.py`, register it in `GRADERS`, and add a test to `tests/test_evals.py` that shows it accepts good output **and**
rejects each kind of bad output: a grader that cannot fail is worse than none.

## Known limits

- The verifier case needs `WebFetch` to reach `127.0.0.1`; if the tool refuses local addresses the run will show low recall
  (a finding about the case, not about the agent). Check the first real run.
- Three cases cover three agents. The `planner`, `data-researcher`, `extractor` and `analyst` have none yet; the analyst's
  chart choices are partly checked by `common.chartkinds` already.
- Fixtures are tiny on purpose; they test judgement rules, not scale.

## Decisions taken from the evals

- **`historian` prompt** (Nov 2026): the first runs showed event_links.csv written without its required columns and a grade B for an
  event whose source only says it happened; the prompt now spells out the columns and ties the grade to the registered excerpt
  (33% to 100% valid files, 0% to 100% no overclaiming).
- **English unit on Sonnet** (Nov 2026): `write_en_only` passed 10 of 10 graders in 3 of 3 runs with both models, at $0.06 against
  $0.10 per run, so the `/study` skill launches the writer's `en` unit with Sonnet. The fixture is small (8 claims); if a real
  study shows drift in the English report, rerun the case on a larger fixture before reverting.
