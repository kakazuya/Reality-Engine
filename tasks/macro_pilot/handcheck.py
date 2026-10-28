"""Hand-check sample + precision/recall scorer for the macro_claim_target pilot.

    python tasks/macro_pilot/handcheck.py sample   # writes review_sheet.json (60 rows)
    python tasks/macro_pilot/handcheck.py score    # reads handcheck_labels.json

The sample is deterministic: 15 evenly spaced ``macro_claim_target`` rows from each
pilot stratum.  Every target of each sampled claim is listed, so the hand label can
record both wrong targets (precision) and missed targets (recall) for that claim.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DB = REPO / ".tmp" / "pilot" / "macro_pilot.db"
SHEET = HERE / "review_sheet.json"
LABELS = HERE / "handcheck_labels.json"
STRATA = ("budget", "rbi", "pib", "tariff")
PER_STRATUM = 15


def _connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    return con


def sample() -> dict:
    con = _connect()
    try:
        claims_rows = con.execute(
            "SELECT c.claim_id, c.stratum, d.source AS doc_source, d.doc_type, d.title, "
            "d.issuer, d.known_at, c.policy_type, c.instrument, c.direction, "
            "c.magnitude_value, c.magnitude_unit, c.effective_date, c.quote, c.paraphrase, "
            "c.confidence FROM macro_claim c JOIN macro_doc d ON d.doc_id = c.doc_id "
            "WHERE c.claim_id IN (SELECT claim_id FROM macro_claim_target) "
            "ORDER BY c.claim_id").fetchall()
        all_targets = con.execute(
            "SELECT claim_id, target_kind, target_id, direction, evidence "
            "FROM macro_claim_target ORDER BY claim_id, target_kind, target_id").fetchall()
    finally:
        con.close()

    by_stratum: dict[str, list[sqlite3.Row]] = {}
    for row in claims_rows:
        by_stratum.setdefault(str(row["stratum"]), []).append(row)
    chosen: list[sqlite3.Row] = []
    for stratum in STRATA:
        group = by_stratum.get(stratum) or []
        step = max(1, len(group) // PER_STRATUM)
        chosen.extend(group[::step][:PER_STRATUM])
    chosen_ids = [int(row["claim_id"]) for row in chosen]

    claims: dict[int, dict] = {}
    for row in chosen:
        claims[int(row["claim_id"])] = {
            key: row[key] for key in ("claim_id", "stratum", "doc_source", "doc_type", "title",
                                      "issuer", "known_at", "policy_type", "instrument",
                                      "direction", "magnitude_value", "magnitude_unit",
                                      "effective_date", "quote", "paraphrase", "confidence")
        }
    for row in all_targets:
        if int(row["claim_id"]) in claims:
            claims[int(row["claim_id"])].setdefault("targets", []).append({
                "target": f"{row['target_kind']}:{row['target_id']}",
                "kind": row["target_kind"], "id": row["target_id"],
                "direction": row["direction"], "evidence": row["evidence"],
            })

    sheet = {
        "db": str(DB), "claims_sampled": len(chosen),
        "rows_covered": sum(len(entry.get("targets") or []) for entry in claims.values()),
        "instructions": (
            "For every claim key in handcheck_labels.json list the emitted targets that are "
            "correct under 'tp', the ones that are wrong under 'fp' (target = 'kind:id'), and "
            "the industries the claim clearly names that were missed under 'fn' (target = "
            "'kind:id', why = the claim words that name it). A generic term (exports, all "
            "sectors, manufacturing, MSME) is not a miss."),
        "claims": claims,
    }
    SHEET.write_text(json.dumps(sheet, indent=1), encoding="utf-8")
    print(f"sampled {len(chosen)} claims covering {sheet['rows_covered']} target rows -> {SHEET}")
    print("claims by stratum: " + json.dumps(
        {s: sum(1 for r in chosen if r["stratum"] == s) for s in STRATA}))
    return sheet


def score() -> dict:
    labels = json.loads(LABELS.read_text(encoding="utf-8"))["claims"]
    con = _connect()
    try:
        strata = {int(row[0]): str(row[1]) for row in
                  con.execute("SELECT claim_id, stratum FROM macro_claim")}
        emitted = {(int(row[0]), f"{row[1]}:{row[2]}"): str(row[3]) for row in con.execute(
            "SELECT claim_id, target_kind, target_id, evidence FROM macro_claim_target")}
    finally:
        con.close()

    totals = {"tp": 0, "fp": 0, "fn": 0}
    strict_fp = 0
    per_stratum: dict[str, dict[str, int]] = {}
    problems: list[str] = []
    for key, label in labels.items():
        claim_id = int(key)
        stratum = strata.get(claim_id, "unknown")
        bucket = per_stratum.setdefault(stratum, {"tp": 0, "fp": 0, "fn": 0})
        for target in label.get("tp") or []:
            if (claim_id, target) not in emitted:
                problems.append(f"{claim_id}: labelled {target} correct but it was not emitted")
                continue
            totals["tp"] += 1
            bucket["tp"] += 1
        for target in label.get("fp") or []:
            if (claim_id, target) not in emitted:
                problems.append(f"{claim_id}: labelled {target} wrong but it was not emitted")
                continue
            totals["fp"] += 1
            bucket["fp"] += 1
        for miss in label.get("fn") or []:
            totals["fn"] += 1
            bucket["fn"] += 1
        for target in label.get("strict_fp") or []:
            if (claim_id, target) not in emitted:
                problems.append(f"{claim_id}: strict {target} was not emitted")
                continue
            strict_fp += 1
    precision = totals["tp"] / (totals["tp"] + totals["fp"]) if totals["tp"] + totals["fp"] else 0.0
    recall = totals["tp"] / (totals["tp"] + totals["fn"]) if totals["tp"] + totals["fn"] else 0.0
    strict_precision = (totals["tp"] / (totals["tp"] + totals["fp"] + strict_fp)
                        if totals["tp"] + totals["fp"] + strict_fp else 0.0)
    result = {"claims": len(labels), "totals": totals, "precision": round(precision, 4),
              "recall": round(recall, 4), "strict_fp": strict_fp,
              "strict_precision": round(strict_precision, 4),
              "per_stratum": per_stratum, "problems": problems}
    print(json.dumps(result, indent=1))
    return result


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("command", choices=("sample", "score"))
    args = ap.parse_args(argv)
    if args.command == "sample":
        sample()
        return 0
    result = score()
    return 0 if not result["problems"] else 1


if __name__ == "__main__":
    sys.exit(main())
