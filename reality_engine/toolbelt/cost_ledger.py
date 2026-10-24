"""Append-only paid-call ledger with a hard budget gate.

Every paid call appends one JSON line to ``tasks/ledgers/spend.jsonl``.  The
provider-reported cost wins when given; otherwise tokens are priced from the
table below (or explicit ``--price-in/--price-out``).  ``--cap`` refuses the
call *before* it happens, so a runaway worker stops at the budget instead of
discovering the overrun in a report.

Examples:
    python -m reality_engine.toolbelt.cost_ledger --add deepseek deepseek-v4.1-flash \\
        12000 800 0.0023 concall_facts job-123
    python -m reality_engine.toolbelt.cost_ledger --report --scope concall_facts
    python -m reality_engine.toolbelt.cost_ledger --cap 5 --scope concall_facts \\
        --add opencode longcat-2.5-preview-free 0 0 0 concall_facts job-123

    from reality_engine.toolbelt.cost_ledger import charge, BudgetExceeded
    charge("opencode", "longcat-2.5-preview-free", 1000, 200, 0.0,
           "concall_facts", "job-123", cap_usd=5, cap_scope="concall_facts")
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ._common import REPO_ROOT, add_format, main_guard, print_result

DEFAULT_LEDGER = REPO_ROOT / "tasks" / "ledgers" / "spend.jsonl"

# $ per 1M tokens (input, output).  Sources: concall_deepseek.py (deepseek),
# extract_deck_figures.py MODELS (the rest).  Free tiers stay 0.
PRICES: dict[str, tuple[float, float]] = {
    "deepseek-v4.1-flash": (0.15, 0.60),
    "muse-spark-1.3-contributor": (0.10, 0.20),
    "mimo-v2.6-flash": (0.14, 0.28),
    "longcat-2.5-preview-free": (0.0, 0.0),
    "step-5-preview-free": (0.0, 0.0),
    "dots-studio/dots-3-note-preview:free": (0.0, 0.0),
    "gemma-4-26b-a4b-it": (0.0, 0.0),
    "gemma-4-31b-it": (0.0, 0.0),
}


class BudgetExceeded(RuntimeError):
    """The call would push a purpose past its cap; nothing was written."""


def _ledger(path: str | Path | None) -> Path:
    return Path(path) if path else DEFAULT_LEDGER


def read_entries(ledger: str | Path | None = None) -> list[dict[str, Any]]:
    """Read valid JSONL lines; a torn last line from a crash is skipped, not fatal."""
    path = _ledger(ledger)
    if not path.exists():
        return []
    entries = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except ValueError:
                continue
            if isinstance(entry, dict):
                entries.append(entry)
    return entries


def _append(path: Path, entry: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
    # ponytail: single-writer append; upgrade to a lock if parallel jobs ever
    # charge the same purpose (the supervisor runs one worker per lane today).
    fd = os.open(path, os.O_APPEND | os.O_CREAT | os.O_WRONLY, 0o644)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


def _spent(entries: Iterable[dict[str, Any]], scope: str | None) -> float:
    total = 0.0
    for entry in entries:
        if scope and scope not in ("all", "*") and entry.get("purpose") != scope:
            continue
        try:
            total += float(entry.get("usd") or 0.0)
        except (TypeError, ValueError):
            continue
    return total


def _cost(model: str, in_tok: int, out_tok: int, usd: float | None,
          price_in: float | None, price_out: float | None) -> float:
    if usd is not None:
        return float(usd)
    key = str(model).lower()
    pin, pout = PRICES.get(key, (price_in, price_out))
    if pin is None or pout is None:
        raise ValueError(f"no price for {model!r}; pass a reported usd or --price-in/--price-out")
    return (int(in_tok) / 1_000_000.0) * float(pin) + (int(out_tok) / 1_000_000.0) * float(pout)


def charge(provider: str, model: str, in_tok: int = 0, out_tok: int = 0,
           usd: float | None = None, purpose: str = "", job_id: str = "", *,
           ledger: str | Path | None = None, cap_usd: float | None = None,
           cap_scope: str | None = None, price_in: float | None = None,
           price_out: float | None = None) -> dict[str, Any]:
    """Append one paid call; raises :class:`BudgetExceeded` before writing if capped."""
    cost = round(_cost(model, in_tok, out_tok, usd, price_in, price_out), 6)
    path = _ledger(ledger)
    if cap_usd is not None:
        spent = _spent(read_entries(path), cap_scope)
        if spent + cost > float(cap_usd) + 1e-9:
            raise BudgetExceeded(
                f"cap ${float(cap_usd):.2f} for {cap_scope or 'all'} would be exceeded: "
                f"spent ${spent:.4f}, this call ${cost:.4f}")
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "in_tok": int(in_tok),
        "out_tok": int(out_tok),
        "usd": cost,
        "purpose": purpose,
        "job_id": job_id,
    }
    _append(path, entry)
    return entry


def report(ledger: str | Path | None = None, scope: str | None = None) -> dict[str, Any]:
    """Totals overall and by provider/model/purpose/job."""
    entries = read_entries(ledger)
    if scope and scope not in ("all", "*"):
        entries = [e for e in entries if e.get("purpose") == scope]

    def bucket(key: str) -> dict[str, dict[str, Any]]:
        out: dict[str, dict[str, Any]] = {}
        for entry in entries:
            name = str(entry.get(key) or "-")
            row = out.setdefault(name, {"calls": 0, "in_tok": 0, "out_tok": 0, "usd": 0.0})
            row["calls"] += 1
            row["in_tok"] += int(entry.get("in_tok") or 0)
            row["out_tok"] += int(entry.get("out_tok") or 0)
            row["usd"] = round(row["usd"] + float(entry.get("usd") or 0.0), 6)
        return out

    total = round(sum(float(e.get("usd") or 0.0) for e in entries), 6)
    return {
        "ledger": str(_ledger(ledger)),
        "scope": scope,
        "entries": len(entries),
        "total_usd": total,
        "by_provider": bucket("provider"),
        "by_model": bucket("model"),
        "by_purpose": bucket("purpose"),
        "by_job": bucket("job_id"),
    }


def _number(value: str) -> float | None:
    return None if value.strip().lower() in ("", "-", "auto", "none") else float(value)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.cost_ledger",
        description="Append-only paid-call ledger with a pre-call budget cap.")
    ap.add_argument("--add", nargs=7, metavar=("PROVIDER", "MODEL", "IN_TOK", "OUT_TOK", "USD",
                                               "PURPOSE", "JOB_ID"),
                    help="append a call; USD may be 'auto' to price tokens")
    ap.add_argument("--cap", type=float, help="refuse the call if this would exceed the cap")
    ap.add_argument("--scope", help="purpose the cap/report applies to (default: all)")
    ap.add_argument("--report", action="store_true", help="print totals")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER), help="ledger path")
    ap.add_argument("--price-in", type=float, help="$/1M input tokens when the model is not in PRICES")
    ap.add_argument("--price-out", type=float, help="$/1M output tokens when the model is not in PRICES")
    add_format(ap)
    args = ap.parse_args(argv)
    if args.add:
        provider, model, in_tok, out_tok, usd, purpose, job_id = args.add
        try:
            entry = charge(provider, model, int(in_tok), int(out_tok), _number(usd), purpose,
                           job_id, ledger=args.ledger, cap_usd=args.cap, cap_scope=args.scope,
                           price_in=args.price_in, price_out=args.price_out)
        except BudgetExceeded as exc:
            print_result({"error": "BudgetExceeded", "detail": str(exc), "cap": args.cap,
                          "scope": args.scope}, args.format)
            return 2
        print_result({"entry": entry, "cap": args.cap, "scope": args.scope}, args.format)
        return 0
    if args.report:
        result = report(args.ledger, args.scope)
        if args.cap is not None:
            spent = _spent(read_entries(args.ledger), args.scope)
            result.update({"cap": args.cap, "spent_usd": round(spent, 6),
                           "over_cap": spent > float(args.cap) + 1e-9})
            print_result(result, args.format)
            return 2 if result["over_cap"] else 0
        print_result(result, args.format)
        return 0
    ap.error("give --add ... or --report")


if __name__ == "__main__":
    main_guard(main)
