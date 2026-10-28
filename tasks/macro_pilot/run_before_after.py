"""Before / after: RIPPLE on the 58 policy-rooted ripple200 master-bank cases.

"Before" is the planner as held today (policy_events free-text sectors -> LIKE over
master_companies).  "After" points the same planner at the pilot claim-target DB
(``REALITY_MACRO_PILOT_DB``).  Only the RIPPLE hop is run: the other hops of these
cases are blocked by stage-3 tables that this pilot does not build, so running the
whole chain would measure those tables, not this one.

    python tasks/macro_pilot/run_before_after.py [--db .tmp/pilot/macro_pilot.db]

Writes ``tasks/macro_pilot/ripple_before_after.json`` and prints the summary.
Read-only on every live database.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from reality_engine.query import route  # noqa: E402
from reality_engine.query.ctx import Ctx  # noqa: E402
from reality_engine.query.planners import ripple  # noqa: E402

ROOT_RE = re.compile(r"policy|budget|rbi|repo|mpc|tariff|duty|fta|pli|fdi|mgnregs|subsid|"
                     r"scheme|section 232|regulation|gst|rate cut|bps", re.I)
ASK_RE = re.compile(r"\b(repo|policy|budget|tariff|duty|duties|fdi|ecb|collateral-free|grant|"
                    r"grants|scheme|pli|mgnregs|insurance opened|capital outlay|liquidity|"
                    r"rate cut|subsidy|regulator|rbi|mpc)\b", re.I)
ENV = "REALITY_MACRO_PILOT_DB"


def policy_roots() -> list[dict]:
    path = REPO / "tasks" / "master_bank" / "MASTER_BANK.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("source_bank") != "ripple200":
            continue
        root = str(((row.get("chain") or [{}])[0]).get("from") or "")
        if (str(row.get("template") or "").startswith("policy_events")
                or ROOT_RE.search(root) or ASK_RE.search(str(row.get("question") or ""))):
            out.append(row)
    return out


def run(cases: list[dict], pilot: sqlite3.Connection | None = None) -> list[dict]:
    ctx = Ctx()
    rows = []
    try:
        for case in cases:
            plan = route(case)
            as_of = str(plan["as_of"])
            hop = ripple.plan(plan["slots"], as_of, ctx)
            matched = None
            try:
                policies = ripple._policy(ctx, plan["slots"], as_of)
                matched = policies[0]["id"] if policies else None
            except Exception:  # noqa: BLE001 - the hop already carries the failure
                matched = None
            targets = [row for row in hop.get("rows") or []
                       if str(row.get("ref") or "").startswith("daily_price_delivery:")]
            state = None
            if pilot is not None and matched is not None:
                has_claim = pilot.execute("SELECT 1 FROM macro_claim WHERE claim_id=?",
                                          (matched,)).fetchone()
                count = pilot.execute("SELECT COUNT(*) FROM macro_claim_target WHERE claim_id=?",
                                      (matched,)).fetchone()
                state = ("not_in_pilot" if not has_claim
                         else f"pilot_targets={count[0] if count else 0}")
            rows.append({
                "mid": case["mid"], "archetype": case.get("archetype"),
                "question": str(case.get("question") or "")[:220],
                "as_of": as_of, "ok": bool(hop["ok"]), "why": hop.get("why"),
                "gap": hop.get("gap"), "detail": str(hop.get("detail") or "")[:400],
                "policy_id": matched,
                "policy_ref": (f"policy_events:{matched}" if matched else None),
                "claim_state": state, "targets": len(targets),
                "target_refs": [row.get("ref") for row in targets][:10],
            })
    finally:
        ctx.close()
    return rows


def by_mode(rows: list[dict]) -> dict:
    return {
        "cases": len(rows),
        "ripple_ok": sum(1 for row in rows if row["ok"]),
        "gaps": dict(Counter(row["gap"] or "none" for row in rows)),
        "no_policy_match": sum(1 for row in rows if not row["policy_ref"]),
        "target_cases": sum(1 for row in rows if row["targets"]),
        "targets_total": sum(row["targets"] for row in rows),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=str(REPO / ".tmp" / "pilot" / "macro_pilot.db"))
    ap.add_argument("--out", default=str(HERE / "ripple_before_after.json"))
    args = ap.parse_args(argv)
    cases = policy_roots()
    saved = os.environ.pop(ENV, None)
    try:
        before = run(cases)
        os.environ[ENV] = args.db
        pilot = sqlite3.connect(args.db)
        try:
            after = run(cases, pilot)
        finally:
            pilot.close()
    finally:
        os.environ.pop(ENV, None)
        if saved:
            os.environ[ENV] = saved

    before_by = {row["mid"]: row for row in before}
    unblocked = [row["mid"] for row in after if row["ok"] and not before_by[row["mid"]]["ok"]]
    regressed = [row["mid"] for row in after if not row["ok"] and before_by[row["mid"]]["ok"]]
    payload = {
        "policy_rooted_cases": len(cases),
        "before": by_mode(before), "after": by_mode(after),
        "unblocked": unblocked, "regressed": regressed,
        "by_archetype": {
            arch: {
                "cases": len([c for c in cases if c.get("archetype") == arch]),
                "before_ok": len([r for r in before if r["archetype"] == arch and r["ok"]]),
                "after_ok": len([r for r in after if r["archetype"] == arch and r["ok"]]),
            }
            for arch in sorted({str(c.get("archetype")) for c in cases})
        },
        "rows": {"before": before, "after": after},
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, indent=1), encoding="utf-8")

    print(f"policy-rooted ripple200 cases: {len(cases)}")
    for mode in ("before", "after"):
        counts = payload[mode]
        print(f"{mode:6s} RIPPLE ok {counts['ripple_ok']}/{counts['cases']}  "
              f"target cases {counts['target_cases']}  gaps {counts['gaps']}")
    print(f"unblocked ({len(unblocked)}): {', '.join(unblocked) or 'none'}")
    print(f"regressed ({len(regressed)}): {', '.join(regressed) or 'none'}")
    print(f"written: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
