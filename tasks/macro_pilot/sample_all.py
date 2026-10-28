"""Draw the independent 80-claim check from the full run (seed 20261029).

Excludes the 300 claims of the stratified pilot, stratifies by source class and
writes ``review_all.json``: the claim text, its source document's identifying
fields (and the PIB body where the store has one) and the targets the extractor
emitted.  Judgement (``labels_all.json``) is written by hand, not by this script.

    python tasks/macro_pilot/sample_all.py [--n 80] [--seed 20261029]

Read-only on every database; writes only under tasks/macro_pilot/.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
sys.path.insert(0, str(REPO))

from reality_engine.db.readonly import connect_ro  # noqa: E402

SOURCE_CLASS = {
    "Union_Budget": "union_budget",
    "Economic_Survey": "economic_survey",
    "PIB_Press_Release": "pib",
    "PIB_Circular": "pib",
}


def source_class(source_type: str) -> str:
    if source_type in SOURCE_CLASS:
        return SOURCE_CLASS[source_type]
    if source_type.startswith("State_Budget"):
        return "state_budget"
    if source_type.startswith("RBI"):
        return "rbi"
    return "other"


def allocate(frames: dict[str, list[dict]], n: int, floor: int = 4) -> dict[str, int]:
    """Proportional to source size, with a small floor so a thin source is not 1 claim."""
    total = sum(len(rows) for rows in frames.values())
    out = {key: min(floor, len(rows)) for key, rows in frames.items()}
    if sum(out.values()) > n:
        out = {key: 0 for key in frames}
    remaining = n - sum(out.values())
    ratio = {key: remaining * len(frames[key]) / total for key in frames}
    for key in frames:
        out[key] += int(ratio[key])
    order = sorted(frames, key=lambda key: (-(ratio[key] - int(ratio[key])),
                                            -len(frames[key]), key))
    index = 0
    while sum(out.values()) < n and index < 100000:
        key = order[index % len(order)]
        if out[key] < len(frames[key]):
            out[key] += 1
        index += 1
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--seed", type=int, default=20261029)
    ap.add_argument("--all-db", default=str(REPO / ".tmp" / "pilot_all" / "macro_all.db"))
    ap.add_argument("--pilot-db", default=str(REPO / ".tmp" / "pilot" / "macro_pilot.db"))
    ap.add_argument("--out", default=str(HERE / "review_all.json"))
    ap.add_argument("--ids-from", default=None,
                    help="re-read the claim ids of an existing sheet (post-fix pass)")
    args = ap.parse_args(argv)

    pilot = sqlite3.connect(args.pilot_db)
    pilot_ids = {row[0] for row in pilot.execute("SELECT claim_id FROM macro_claim")}
    pilot.close()

    full = sqlite3.connect(args.all_db)
    full.row_factory = sqlite3.Row
    docs = {row["doc_id"]: dict(row) for row in
            full.execute("SELECT doc_id, source, doc_type, issuer, title, event_date, "
                         "known_at FROM macro_doc")}
    claims = [dict(row) for row in full.execute(
        "SELECT claim_id, doc_id, policy_type, instrument, direction, magnitude_value, "
        "magnitude_unit, effective_date, effective_pit_conf, quote, known_at, stratum, "
        "quote_ok FROM macro_claim ORDER BY claim_id")]
    targets: dict[int, list[dict]] = {}
    for row in full.execute("SELECT claim_id, target_kind, target_id, direction, evidence "
                            "FROM macro_claim_target ORDER BY claim_id, target_kind, target_id"):
        targets.setdefault(row["claim_id"], []).append(dict(row))
    full.close()

    frames: dict[str, list[dict]] = {}
    for claim in claims:
        if claim["claim_id"] in pilot_ids:
            continue
        doc = docs.get(claim["doc_id"], {})
        claim["source_type"] = doc.get("source", "")
        frames.setdefault(source_class(claim["source_type"]), []).append(claim)

    rng = random.Random(args.seed)
    if args.ids_from:
        previous = json.loads(Path(args.ids_from).read_text(encoding="utf-8"))
        wanted = {int(row["claim_id"]) for row in previous["claims"]}
        picked = [row for rows in frames.values() for row in rows
                  if row["claim_id"] in wanted]
        picked.sort(key=lambda row: row["claim_id"])
        quota = {"reused_sheet": len(picked)}
    else:
        quota = allocate(frames, args.n)
        picked = []
        for key in sorted(frames):
            rows = sorted(frames[key], key=lambda row: row["claim_id"])
            choice = rng.sample(rows, min(quota[key], len(rows)))
            picked.extend(sorted(choice, key=lambda row: row["claim_id"]))

    # Source document body for the PIB claims (the store keeps the press-release text).
    bodies: dict[str, str] = {}
    inputs: dict[int, dict] = {}
    try:
        con = connect_ro(Path(os.environ["REALITY_DATA_ROOT"]) / "equity_intelligence.db",
                         timeout_s=120)
        for claim in picked:
            doc_id = str(claim["doc_id"])
            if doc_id.startswith("pib:"):
                prid = int(doc_id.split(":", 1)[1])
                row = con.execute("SELECT body FROM pib_releases WHERE prid=?",
                                  (prid,)).fetchone()
                if row and row[0]:
                    bodies[doc_id] = str(row[0])
            row = con.execute(
                "SELECT sectors, companies, products, new_value, old_value, "
                "amount_inr_crore, unit FROM policy_events WHERE id=?",
                (claim["claim_id"],)).fetchone()
            if row:
                inputs[claim["claim_id"]] = {
                    "sectors": row[0], "companies": row[1], "products": row[2],
                    "new_value": row[3], "old_value": row[4],
                    "amount_inr_crore": row[5], "unit": row[6]}
        con.close()
    except Exception as exc:  # noqa: BLE001 - judging can fall back to the claim quote
        print(f"pib body unavailable: {type(exc).__name__}: {exc}")

    sheet = []
    for claim in picked:
        doc = docs.get(claim["doc_id"], {})
        sheet.append({
            "claim_id": claim["claim_id"], "doc_id": claim["doc_id"],
            "source_type": claim["source_type"], "doc_type": doc.get("doc_type"),
            "issuer": doc.get("issuer"), "doc_title": doc.get("title"),
            "known_at": claim["known_at"], "policy_type": claim["policy_type"],
            "instrument": claim["instrument"], "direction": claim["direction"],
            "magnitude": [claim["magnitude_value"], claim["magnitude_unit"]],
            "effective_date": claim["effective_date"],
            "effective_pit_conf": claim["effective_pit_conf"],
            "quote_ok": claim["quote_ok"], "quote": claim["quote"],
            "inputs": inputs.get(claim["claim_id"]),
            "doc_body_excerpt": (bodies.get(claim["doc_id"]) or "")[:1500] or None,
            "emitted": targets.get(claim["claim_id"], []),
        })
    HERE.joinpath(Path(args.out).name).write_text(
        json.dumps({"seed": args.seed, "n": len(sheet), "quota": quota, "claims": sheet},
                   indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"seed": args.seed, "n": len(sheet), "quota": quota,
                      "pilot_excluded": len(pilot_ids), "written": args.out}, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
