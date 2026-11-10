"""Token usage and cost per study and per phase, from a headless `claude -p` stream.

The server feeds every stream-json event of a run to a `UsageTracker`. It learns the study
and the current phase from the orchestrator's own `common.state ...` Bash calls, counts the
tokens of every assistant message (deduplicated by message id), and at the end reconciles
with the `result` event's `modelUsage`, which is exact:

- tokens per phase are exact (summed from the messages);
- whatever `modelUsage` has beyond the messages (e.g. subagent traffic that was not
  streamed) goes to phase "unattributed", so totals always match;
- cost per model is exact (`costUSD`); its split across phases is an ESTIMATE, weighting
  each token type by its usual relative price (output 5x input, cache read 0.1x, cache
  write 2x). Cost is the API list-price equivalent, not necessarily what a subscription bills.

Rows go to studies/<slug>/usage.csv. Print a summary with:

    uv run python -m common.usage [<slug>]
"""
from __future__ import annotations

import csv
import re
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from common.checks import STUDIES_ROOT

FIELDS = [
    "run_id", "timestamp", "phase", "model",
    "input_tokens", "cache_read_tokens", "cache_creation_tokens", "output_tokens", "cost_usd",
]
TOKEN_FIELDS = ["input_tokens", "cache_read_tokens", "cache_creation_tokens", "output_tokens"]
# Relative price per token type (input = 1). Only used to split a model's exact cost.
WEIGHTS = {"input_tokens": 1.0, "cache_read_tokens": 0.1, "cache_creation_tokens": 2.0, "output_tokens": 5.0}
# stream-json (assistant usage) / modelUsage key for each of our token fields
MESSAGE_KEYS = {
    "input_tokens": "input_tokens", "cache_read_tokens": "cache_read_input_tokens",
    "cache_creation_tokens": "cache_creation_input_tokens", "output_tokens": "output_tokens",
}
MODEL_USAGE_KEYS = {
    "input_tokens": "inputTokens", "cache_read_tokens": "cacheReadInputTokens",
    "cache_creation_tokens": "cacheCreationInputTokens", "output_tokens": "outputTokens",
}
STATE_COMMAND = re.compile(r"common\.state\s+(?P<cmd>[\w-]+)\s+(?P<slug>[a-z0-9][a-z0-9-]*)(?:\s+(?P<phase>[1-8])\b)?")
PHASE_LABELS = {
    "prep": "preparation", "1": "plan", "2": "sources", "3": "extraction", "4": "analysis",
    "5": "events", "6": "writing", "7": "verification", "8": "publication", "unattributed": "unattributed (thinking, subagents)",
}


def describe_tool_use(block: dict) -> str:
    """One short human line for a tool_use block (what Claude is doing right now)."""
    name, data = block.get("name", "?"), block.get("input") or {}
    if name in {"Agent", "Task"}:
        return f"{data.get('subagent_type', 'agent')}: {data.get('description', '')}".strip(": ")
    if name == "Bash":
        return f"$ {str(data.get('command', ''))[:90]}"
    if name in {"Read", "Write", "Edit"}:
        return f"{name} {Path(str(data.get('file_path', ''))).name}"
    if name in {"WebSearch", "WebFetch"}:
        return f"{name} {str(data.get('query') or data.get('url') or '')[:80]}"
    return name


@dataclass
class UsageTracker:
    run_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    slug: str | None = None
    phase: str = "prep"
    activity: str = ""
    tokens: dict[tuple[str, str], dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: dict.fromkeys(TOKEN_FIELDS, 0)))
    _seen: set[str] = field(default_factory=set)

    def observe(self, event: dict) -> bool:
        """Feed one stream event. Returns True when something the UI shows has changed."""
        if event.get("type") != "assistant":
            return False
        message = event.get("message") or {}
        for block in message.get("content") or []:
            if block.get("type") != "tool_use":
                continue
            self.activity = describe_tool_use(block)
            command = (block.get("input") or {}).get("command", "") if block.get("name") == "Bash" else ""
            match = STATE_COMMAND.search(command)
            if match and event.get("parent_tool_use_id") is None:
                self.slug = match["slug"]
                if match["cmd"] == "start-phase" and match["phase"]:
                    self.phase = match["phase"]
        message_id = message.get("id")
        usage = message.get("usage")
        if usage and message_id and message_id not in self._seen:
            self._seen.add(message_id)
            bucket = self.tokens[(self.phase, message.get("model", "unknown"))]
            for ours, theirs in MESSAGE_KEYS.items():
                bucket[ours] += usage.get(theirs, 0) or 0
        return True

    def total_tokens(self) -> int:
        return sum(sum(b.values()) for b in self.tokens.values())

    def finish(self, result_event: dict) -> list[dict]:
        """Reconcile with the result's modelUsage and return the rows to persist."""
        timestamp = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        model_usage: dict = result_event.get("modelUsage") or {}
        by_model: dict[str, dict[str, dict[str, int]]] = defaultdict(dict)  # model -> phase -> tokens
        for (phase, model), bucket in self.tokens.items():
            by_model[model][phase] = dict(bucket)
        for model, totals in model_usage.items():
            seen = by_model[model]
            residual = {
                f: max(0, int(totals.get(MODEL_USAGE_KEYS[f], 0) or 0) - sum(b[f] for b in seen.values()))
                for f in TOKEN_FIELDS
            }
            if any(residual.values()):
                seen["unattributed"] = residual
        rows = []
        for model, phases in by_model.items():
            exact_cost = float((model_usage.get(model) or {}).get("costUSD", 0) or 0)
            weight = {p: sum(b[f] * WEIGHTS[f] for f in TOKEN_FIELDS) for p, b in phases.items()}
            total_weight = sum(weight.values()) or 1.0
            for phase, bucket in phases.items():
                rows.append({
                    "run_id": self.run_id, "timestamp": timestamp, "phase": phase, "model": model,
                    **bucket, "cost_usd": round(exact_cost * weight[phase] / total_weight, 6),
                })
        return rows


def append_rows(slug: str, rows: list[dict]) -> None:
    if not rows:
        return
    path = STUDIES_ROOT / slug / "usage.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    is_new = not path.exists()
    with path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if is_new:
            writer.writeheader()
        writer.writerows(rows)


def summarize(slug: str) -> dict:
    """Totals and per-phase breakdown for one study (empty totals when nothing was recorded)."""
    path = STUDIES_ROOT / slug / "usage.csv"
    phases: dict[str, dict] = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                entry = phases.setdefault(row["phase"], {**dict.fromkeys(TOKEN_FIELDS, 0), "cost_usd": 0.0})
                for name in TOKEN_FIELDS:
                    entry[name] += int(row[name])
                entry["cost_usd"] += float(row["cost_usd"])
    order = list(PHASE_LABELS)
    listed = [
        {"phase": p, "name": PHASE_LABELS.get(p, p), **phases[p], "cost_usd": round(phases[p]["cost_usd"], 4)}
        for p in sorted(phases, key=lambda p: order.index(p) if p in order else 99)
    ]
    total = {name: sum(p[name] for p in listed) for name in TOKEN_FIELDS}
    return {"slug": slug, "phases": listed, **total, "cost_usd": round(sum(p["cost_usd"] for p in listed), 4)}


def summarize_all() -> list[dict]:
    if not STUDIES_ROOT.exists():
        return []
    studies = [summarize(d.name) for d in sorted(STUDIES_ROOT.iterdir()) if (d / "usage.csv").exists()]
    return studies


def _format(summary: dict) -> str:
    header = (
        f"{summary['slug']}: ${summary['cost_usd']:.2f} | in {summary['input_tokens']:,} "
        f"| cache read {summary['cache_read_tokens']:,} | cache write {summary['cache_creation_tokens']:,} "
        f"| out {summary['output_tokens']:,}"
    )
    lines = [header]
    for p in summary["phases"]:
        tokens = sum(p[f] for f in TOKEN_FIELDS)
        lines.append(f"  {p['phase']:>12} {p['name']:<13} {tokens:>12,} tokens  ~${p['cost_usd']:.2f}")
    return "\n".join(lines)


def main() -> int:
    slugs = sys.argv[1:] or [s["slug"] for s in summarize_all()]
    if not slugs:
        print("no usage recorded yet (usage.csv is written by the server's runs)")
        return 0
    for slug in slugs:
        print(_format(summarize(slug)))
    print("cost per phase is an estimate; study totals are exact (list-price equivalent)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
