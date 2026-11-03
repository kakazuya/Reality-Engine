"""ACCEPT or REJECT one loop, from the two runs' measurements and the guards json (GOAL section 3).

A loop is accepted only when A1-dev rises, A1-hidden and every company hold, A3 provenance is >= 98 % on the
rows the branch added, A4 counts do not rise, A5 passes (no network, no company literals, no protected file
touched) and A6 is green.  Every reason is printed; the exit code is 1 on REJECT.

``--base`` / ``--cand`` take the ``answerable.py`` outputs, repeat them to pass the dev and the hidden run
(the dev/hidden split is told by each file's own ``hidden`` flag).  ``--guards-base`` is the base's guards json;
without it A4 and A7 cannot be compared and say so in the notes.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

A3_MIN = 0.98
A7_MAX_RISE = 1.20
A1_GAIN_FOR_COST = 0.01


def _split(reports: list[dict[str, Any]]) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    dev = next((r for r in reports if not r.get("hidden")), None)
    hidden = next((r for r in reports if r.get("hidden")), None)
    return dev, hidden


def _reports(side: dict[str, Any] | list[dict[str, Any]]) -> list[dict[str, Any]]:
    return side if isinstance(side, list) else [side]


def decide(base: dict[str, Any] | list[dict[str, Any]], cand: dict[str, Any] | list[dict[str, Any]],
           guards: dict[str, Any], guards_base: dict[str, Any] | None = None) -> dict[str, Any]:
    reasons: list[str] = []
    notes: list[str] = []
    base_dev, base_hidden = _split(_reports(base))
    cand_dev, cand_hidden = _split(_reports(cand))

    # A1: dev up, hidden not down, no company down
    dev_gain = 0.0
    if base_dev is None or cand_dev is None:
        reasons.append("A1 dev: not measured on both sides")
    else:
        before = base_dev["a1"]["total"]["rate"]
        after = cand_dev["a1"]["total"]["rate"]
        dev_gain = round(after - before, 4)
        if after <= before:
            reasons.append(f"A1 dev not up: {before:.2%} -> {after:.2%}")
        for symbol, block in sorted(base_dev["a1"]["companies"].items()):
            other = cand_dev["a1"]["companies"].get(symbol)
            if other is None:
                reasons.append(f"A1 dev: company {symbol} missing from the candidate")
            elif other["rate"] < block["rate"]:
                reasons.append(f"A1 dev: company {symbol} down {block['rate']:.2%} -> {other['rate']:.2%}")
    hidden_before = hidden_after = None
    if base_hidden is None or cand_hidden is None:
        reasons.append("A1 hidden: not measured on both sides")
    else:
        hidden_before = base_hidden["a1"]["total"]["rate"]
        hidden_after = cand_hidden["a1"]["total"]["rate"]
        if hidden_after < hidden_before:
            reasons.append(f"A1 hidden down: {hidden_before:.2%} -> {hidden_after:.2%}")
        for symbol, block in sorted(base_hidden["a1"]["companies"].items()):
            other = cand_hidden["a1"]["companies"].get(symbol)
            if other is None:
                reasons.append(f"A1 hidden: company {symbol} missing from the candidate")
            elif other["rate"] < block["rate"]:
                reasons.append(f"A1 hidden: company {symbol} down {block['rate']:.2%} -> {other['rate']:.2%}")

    # A3 provenance
    a3 = (guards.get("a3") or {})
    rate = a3.get("rate")
    if a3.get("checked") == 0 or rate is None:
        notes.append("A3: no added rows to check")
    elif not a3.get("ok", rate >= A3_MIN):
        reasons.append(f"A3 provenance {rate:.2%} < {A3_MIN:.0%} on {a3.get('checked')} rows")

    # A5 build
    a5 = (guards.get("a5") or {})
    if not a5.get("ok"):
        detail = [f"{len(a5.get('literals') or [])} literals", f"{len(a5.get('protected') or [])} protected"]
        failed = [b.get("part") for b in a5.get("builds") or [] if int(b.get("returncode") or 0) != 0]
        if failed:
            detail.append("build parts failed: " + ", ".join(str(p) for p in failed))
        reasons.append("A5 failed: " + "; ".join(detail))

    # A6 tests
    a6 = (guards.get("a6") or {})
    if a6.get("ok") is not True:
        reasons.append(f"A6 tests not green ({a6.get('ok')})")

    # A4 counts must not rise
    if guards_base is None:
        notes.append("A4/A7 not compared: no --guards-base")
    else:
        before = (guards_base.get("a4") or {}).get("counts") or {}
        after = (guards.get("a4") or {}).get("counts") or {}
        for key, value in sorted(after.items()):
            old = before.get(key)
            if isinstance(value, (int, float)) and isinstance(old, (int, float)) and value > old:
                reasons.append(f"A4 {key} up: {old} -> {value}")
        # A7 cost: not up more than 20 % without an A1 dev gain of at least one point
        old_timing = guards_base.get("a7") or {}
        new_timing = guards.get("a7") or {}
        for key in ("build_seconds", "pages_read"):
            old, new = old_timing.get(key), new_timing.get(key)
            if not isinstance(old, (int, float)) or not isinstance(new, (int, float)) or not old:
                continue
            if new > old * A7_MAX_RISE and dev_gain < A1_GAIN_FOR_COST:
                reasons.append(f"A7 {key} up {old:g} -> {new:g} with only {dev_gain:.2%} A1 gain")
    verdict = "ACCEPT" if not reasons else "REJECT"
    return {"verdict": verdict, "reasons": reasons, "notes": notes,
            "a1": {"dev_rate": [_rate(base_dev), _rate(cand_dev)],
                   "hidden_rate": [hidden_before, hidden_after], "dev_gain": dev_gain}}


def _rate(report: dict[str, Any] | None) -> float | None:
    return None if report is None else report["a1"]["total"]["rate"]


def _load(paths: list[str]) -> list[dict[str, Any]]:
    return [json.loads(Path(path).read_text(encoding="utf-8")) for path in paths]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="decide", description="ACCEPT or REJECT a night loop")
    parser.add_argument("--base", action="append", required=True, help="base answerable json (dev and hidden)")
    parser.add_argument("--cand", action="append", required=True, help="candidate answerable json (dev and hidden)")
    parser.add_argument("--guards", required=True, help="candidate guards json")
    parser.add_argument("--guards-base", default="", help="base guards json, to compare A4 and A7")
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    guards = _load([args.guards])[0]
    guards_base = _load([args.guards_base])[0] if args.guards_base else None
    report = decide(_load(args.base), _load(args.cand), guards, guards_base)
    print(f"{report['verdict']}")
    for reason in report["reasons"]:
        print(f"  REASON {reason}")
    for note in report["notes"]:
        print(f"  note {note}")
    hidden = report["a1"]["hidden_rate"]
    print(f"  A1 dev gain {report['a1']['dev_gain']:+.2%}, hidden {hidden[0]} -> {hidden[1]}")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["verdict"] == "ACCEPT" else 1


if __name__ == "__main__":
    sys.exit(main())
