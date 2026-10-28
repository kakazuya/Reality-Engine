"""Score the independent 80-claim check (precision, recall, Wilson lower bounds).

Reads ``review_all.json`` (the drawn sample and the extractor's emitted targets) and
``labels_all.json`` (the hand judgement: per-claim false positives and misses), and
prints/returns the mapping-level precision/recall with the 95% Wilson lower bound.

    python tasks/macro_pilot/score_all.py [--sheet review_all.json]

Read-only; writes nothing unless ``--json`` names an output path.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent
Z = 1.96


def wilson_lower(successes: int, total: int, z: float = Z) -> float:
    """95% Wilson score-interval lower bound for a binomial proportion."""
    if total <= 0:
        return 0.0
    p = successes / total
    denominator = 1 + z * z / total
    centre = (p + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(p * (1 - p) / total + z * z / (4 * total * total)) / denominator
    return max(0.0, centre - margin)


def score(sheet: dict, labels: dict) -> dict:
    rows = sheet["claims"]
    by_claim = {str(row["claim_id"]): row for row in rows}
    notes = labels.get("claims", {})
    emitted = sum(len(row["emitted"]) for row in rows)
    fp = 0
    tp = emitted
    missed: list[dict] = []
    fp_rows: list[dict] = []
    for claim_id, note in notes.items():
        row = by_claim.get(str(claim_id))
        if row is None:
            continue
        keys = {f"{target['target_kind']}:{target['target_id']}" for target in row["emitted"]}
        for key in note.get("fps", []):
            if key in keys:
                fp += 1
                fp_rows.append({"claim_id": int(claim_id), "target": key,
                                "reason": note.get("notes", "")})
            else:
                raise SystemExit(f"label error: FP {key} not emitted on claim {claim_id}")
        for key in note.get("misses", []):
            if key not in keys:
                missed.append({"claim_id": int(claim_id), "target": key,
                               "reason": note.get("notes", "")})
    tp = emitted - fp
    fn = len(missed)
    precision = tp / emitted if emitted else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    by_source: dict[str, dict] = {}
    for row in rows:
        group = by_source.setdefault(row["source_type"], {"claims": 0, "emitted": 0})
        group["claims"] += 1
        group["emitted"] += len(row["emitted"])
    return {
        "claims": len(rows), "emitted": emitted, "tp": tp, "fp": fp, "fn": fn,
        "precision": round(precision, 4), "precision_wilson_lower": round(
            wilson_lower(tp, emitted), 4),
        "recall": round(recall, 4), "recall_wilson_lower": round(
            wilson_lower(tp, tp + fn), 4),
        "false_positives": fp_rows, "misses": missed, "by_source": by_source,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sheet", default=str(HERE / "review_all.json"))
    ap.add_argument("--labels", default=str(HERE / "labels_all.json"))
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    sheet = json.loads(Path(args.sheet).read_text(encoding="utf-8"))
    labels = json.loads(Path(args.labels).read_text(encoding="utf-8"))
    result = score(sheet, labels)
    if args.json:
        Path(args.json).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({key: result[key] for key in
                      ("claims", "emitted", "tp", "fp", "fn", "precision",
                       "precision_wilson_lower", "recall", "recall_wilson_lower")},
                     indent=1))
    for row in result["false_positives"]:
        print(f"FP claim {row['claim_id']}: {row['target']} — {row['reason']}")
    for row in result["misses"]:
        print(f"FN claim {row['claim_id']}: {row['target']} — {row['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
