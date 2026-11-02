"""The T-048 ledger: one JSON line per unit attempt, plus the totals the summary command prints."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from reality_engine.gap_loop import store

LEDGER = "state/ledger.jsonl"
ESCALATIONS = "escalations.jsonl"
TOKEN_FIELDS = ("input", "cache_read", "cache_creation", "output", "thinking")


def append(sandbox: Path, row: dict) -> Path:
    return store.append_jsonl_inside(sandbox, LEDGER, row)


def escalate(sandbox: Path, row: dict) -> Path:
    return store.append_jsonl_inside(sandbox, ESCALATIONS, row)


def read(sandbox: Path) -> list[dict]:
    path = store.inside(sandbox, LEDGER)
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows


def tokens_of(row: dict) -> dict[str, int]:
    tokens = row.get("tokens")
    return {key: int((tokens or {}).get(key) or 0) for key in TOKEN_FIELDS}


def _add_usage(totals: dict[str, int], usage: dict) -> None:
    for key, source in (("input", "input_tokens"), ("cache_read", "cache_read_input_tokens"),
                        ("cache_creation", "cache_creation_input_tokens"), ("output", "output_tokens")):
        totals[key] += int(usage.get(source) or 0)
    details = usage.get("output_tokens_details") or usage.get("cache_creation") or {}
    if isinstance(details, dict):
        for name, amount in details.items():
            if "think" in str(name).lower():
                totals["thinking"] += int(amount or 0)
    for name in ("thinking_tokens", "reasoning_tokens"):
        totals["thinking"] += int(usage.get(name) or 0)


def opus_usage(path: Path, since: str) -> dict[str, int]:
    """Sum the ``usage`` blocks of a managing Claude session's transcript after ``since``."""
    limit = datetime.fromisoformat(since.replace("Z", "+00:00")) if since else None
    totals = dict.fromkeys(TOKEN_FIELDS, 0)
    file = Path(path)
    if not file.exists():
        return totals
    for line in file.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        usage = (event.get("message") or {}).get("usage") or event.get("usage") or {}
        if not isinstance(usage, dict) or not usage:
            continue
        stamp = event.get("timestamp") or event.get("created_at")
        if limit and stamp:
            try:
                when = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
            except ValueError:
                when = None
            if when is not None and when < limit:
                continue
        _add_usage(totals, usage)
    return totals


def summary(rows: list[dict], answered: int, opus: dict[str, int] | None = None) -> dict:
    tiers: dict[int, dict] = defaultdict(lambda: {
        "units": set(), "attempts": 0, "ok": 0, "cost_usd": 0.0, "estimated": 0,
        "tokens": dict.fromkeys(TOKEN_FIELDS, 0), "models": set(), "missing_tokens": 0,
    })
    methods: Counter[str] = Counter()
    for row in rows:
        tier = int(row.get("tier") or 0)
        bucket = tiers[tier]
        bucket["units"].add(row.get("unit"))
        bucket["attempts"] += 1
        bucket["ok"] += 1 if row.get("outcome") == "ok" else 0
        bucket["cost_usd"] += float(row.get("cost_usd") or 0)
        bucket["estimated"] += 1 if row.get("cost_estimated") else 0
        bucket["models"].add(str(row.get("model") or "?"))
        token_row = tokens_of(row)
        for key in TOKEN_FIELDS:
            bucket["tokens"][key] += token_row[key]
        if not token_row["input"] and not token_row["output"]:
            bucket["missing_tokens"] += 1
        for tag in row.get("methods") or []:
            methods[str(tag)] += 1
    total_tokens = dict.fromkeys(TOKEN_FIELDS, 0)
    total_cost = 0.0
    for bucket in tiers.values():
        for key in TOKEN_FIELDS:
            total_tokens[key] += bucket["tokens"][key]
        total_cost += bucket["cost_usd"]
        bucket["units"] = len(bucket["units"])
        bucket["models"] = sorted(bucket["models"])
    return {
        "tiers": dict(sorted(tiers.items())),
        "methods": dict(methods.most_common()),
        "total_tokens": total_tokens,
        "total_cost_usd": round(total_cost, 4),
        "answered": int(answered),
        "tokens_per_answer": {key: (round(value / answered, 1) if answered else None)
                              for key, value in total_tokens.items()},
        "opus": opus,
    }


def format_summary(result: dict) -> str:
    lines = []
    for tier, bucket in result["tiers"].items():
        tokens = bucket["tokens"]
        missing = f", tokens missing on {bucket['missing_tokens']} attempt(s)" if bucket["missing_tokens"] else ""
        estimated = f", {bucket['estimated']} cost estimate(s)" if bucket["estimated"] else ""
        lines.append(
            f"tier {tier} ({', '.join(bucket['models'])}): units {bucket['units']}, attempts {bucket['attempts']}, "
            f"ok {bucket['ok']}, tokens input={tokens['input']:,} cache_read={tokens['cache_read']:,} "
            f"cache_creation={tokens['cache_creation']:,} output={tokens['output']:,} thinking={tokens['thinking']:,}, "
            f"cost ${bucket['cost_usd']:.3f}{estimated}{missing}"
        )
    if result["methods"]:
        lines.append("methods: " + ", ".join(f"{name}={count}" for name, count in result["methods"].items()))
    lines.append(f"questions answered: {result['answered']}")
    per = result["tokens_per_answer"]
    if result["answered"]:
        lines.append("tokens per question answered: " + ", ".join(f"{key}={value}" for key, value in per.items() if value is not None))
    opus = result.get("opus")
    if opus:
        lines.append("managing Claude session: " + ", ".join(f"{key}={value:,}" for key, value in opus.items())
                     + " (tokens only; its list price is not assumed)")
    lines.append(f"estimated list price (tier 1): ${result['total_cost_usd']:.3f}")
    return "\n".join(lines)
