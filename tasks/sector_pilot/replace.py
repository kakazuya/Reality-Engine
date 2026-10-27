"""Replace sample rows that have no traceable FY2024-25 business evidence.

The replacement is the next draw of the same stratum from the same seeded
sampler (sampling.draw with the thin ISINs excluded); every swap is recorded in
replacements.csv.  Only after a replacement passes the evidence check is it
written back to sample.json / sample.csv and evidence.json.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import evidence
import sampling

OUT = Path(__file__).resolve().parent


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def main():
    sample = load("sample.json")["rows"]
    ev = load("evidence.json")
    thin = [r for r in sample if not ev.get(r["isin"], {}).get("sources")]
    print("thin rows:", [(r["symbol"], r["isin"]) for r in thin])
    if not thin:
        print("nothing to replace")
        return

    fresh, rejects = sampling.draw(exclude={r["isin"] for r in thin})
    old_isins = {r["isin"] for r in sample}
    spare_a = [r for r in fresh if r["bucket"].startswith("A") and r["isin"] not in old_isins]
    spare_b = [r for r in fresh if r["bucket"].startswith("B") and r["isin"] not in old_isins]
    print(f"spares A={len(spare_a)} B={len(spare_b)}")

    swaps = []
    for row in thin:
        from_a = row["bucket"].startswith("A")
        pool = spare_a if from_a else spare_b
        pick, new_ev = None, None
        # same-sector first, then any
        ordered = sorted(pool, key=lambda x: (from_a and x["nse_sector"] != row["nse_sector"]))
        for cand in ordered:
            trial = evidence.gather(cand["isin"])
            if trial["sources"]:
                pick, new_ev = cand, trial
                pool.remove(cand)
                break
        if pick is None:
            print("NO REPLACEMENT for", row["symbol"], row["isin"])
            continue
        idx = sample.index(row)
        pick = dict(pick, isn=row["isn"])
        sample[idx] = pick
        ev[pick["isin"]] = new_ev
        swaps.append({
            "position": row["isn"], "bucket": row["bucket"],
            "old_isin": row["isin"], "old_symbol": row["symbol"],
            "new_isin": pick["isin"], "new_symbol": pick["symbol"],
            "new_sector": pick["nse_sector"], "reason": "no_locally_held_FY2024-25_evidence",
            "new_evidence_kinds": pick["evidence_kinds"],
        })
        print(f"swapped {row['symbol'] or row['isin']} -> {pick['symbol'] or pick['isin']}")

    (OUT / "sample.json").write_text(json.dumps({
        "seed": sampling.SEED, "fy_cutoff": sampling.FY_CUTOFF,
        "n": len(sample), "rejects": rejects, "rows": sample}, indent=1), encoding="utf-8")
    (OUT / "evidence.json").write_text(json.dumps(ev, indent=1, ensure_ascii=False),
                                       encoding="utf-8")
    with (OUT / "replacements.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(swaps[0]) if swaps else ["position"])
        w.writeheader()
        for s in swaps:
            w.writerow(s)
    # rewrite the list CSV
    fields = [k for k in sample[0] if k != "segments_found"] + ["segments_found"]
    with (OUT / "sample.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for row in sample:
            row = dict(row)
            row["segments_found"] = "; ".join(row["segments_found"])
            w.writerow({k: row.get(k, "") for k in fields})
    print(f"replaced {len(swaps)}; final n={len(sample)} "
          f"A={sum(1 for r in sample if r['bucket'].startswith('A'))} "
          f"multi={sum(1 for r in sample if r['multi_segment'])} "
          f"sectors={len({r['nse_sector'] for r in sample if r['nse_sector']})}")


if __name__ == "__main__":
    main()
