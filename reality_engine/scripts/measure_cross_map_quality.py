"""Measure cross-map quality: does an anchor's neighbourhood land in its own industry?

Objective, substrate-grounded metric (no hand-labelled pairs):
``master_companies.industry`` is treated as ground truth and we ask how many of
an anchor's top-k analogs share it. Reported for BOTH cross-maps side by side so
the business-substance map is judged on the same footing as the financial one —
and stratified by how much text each anchor actually has, because coverage (not
method) is what limits the business map today.

    python -m reality_engine.scripts.measure_cross_map_quality --top-k 10
"""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from reality_engine.db.database import db_manager  # noqa: E402
from reality_engine.processing import business_peer_graph as bpg  # noqa: E402


def _industry_map(conn) -> dict:
    out = {}
    for sym, ind in conn.execute(
        "SELECT nse_symbol, industry FROM master_companies WHERE nse_symbol IS NOT NULL"
    ):
        if ind:
            out[str(sym).upper()] = str(ind).strip().lower()
    return out


def _precision(conn, table: str, anchor_col: str, peer_col: str, top_k: int, industries: dict,
               min_peers: int = 5) -> dict:
    per_anchor = []
    for anchor, in conn.execute(f"SELECT DISTINCT {anchor_col} FROM {table}"):
        a = str(anchor).upper()
        ia = industries.get(a)
        if not ia:
            continue
        peers = [str(r[0]).upper() for r in conn.execute(
            f"SELECT {peer_col} FROM {table} WHERE {anchor_col}=? ORDER BY rank LIMIT ?", (anchor, top_k))]
        known = [p for p in peers if p in industries]
        if len(known) < min_peers:
            continue
        hits = sum(1 for p in known if industries[p] == ia)
        per_anchor.append(hits / len(known))
    if not per_anchor:
        return {"anchors": 0}
    return {
        "anchors": len(per_anchor),
        "precision_at_k": round(statistics.mean(per_anchor), 4),
        "median": round(statistics.median(per_anchor), 4),
        "zero_precision_share": round(sum(1 for p in per_anchor if p == 0) / len(per_anchor), 4),
    }


def _business_precision_by_coverage(conn, industries: dict, top_k: int) -> dict:
    """Business map precision, stratified by anchor chunk count (coverage proxy)."""
    buckets: dict = defaultdict(list)
    rows = conn.execute(
        "SELECT anchor_symbol, anchor_chunks FROM company_business_graph "
        "GROUP BY anchor_symbol"
    ).fetchall()
    for anchor, chunks in rows:
        a = str(anchor).upper()
        ia = industries.get(a)
        if not ia:
            continue
        peers = [str(r[0]).upper() for r in conn.execute(
            "SELECT peer_symbol FROM company_business_graph WHERE anchor_symbol=? ORDER BY rank LIMIT ?",
            (anchor, top_k))]
        known = [p for p in peers if p in industries]
        if len(known) < 5:
            continue
        hits = sum(1 for p in known if industries[p] == ia)
        band = "1000+" if chunks >= 1000 else "300-999" if chunks >= 300 else "50-299" if chunks >= 50 else "<50"
        buckets[band].append(hits / len(known))
    order = ["1000+", "300-999", "50-299", "<50"]
    return {
        band: {
            "anchors": len(v),
            "precision_at_k": round(statistics.mean(v), 4),
        }
        for band in order if (v := buckets.get(band))
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=10)
    args = ap.parse_args(argv)

    with db_manager.session() as conn:
        industries = _industry_map(conn)
        print(f"symbols with an industry label: {len(industries):,}")

        fin = _precision(conn, "company_peer_graph", "anchor_symbol", "peer_symbol", args.top_k, industries)
        bus = _precision(conn, "company_business_graph", "anchor_symbol", "peer_symbol", args.top_k, industries)
        print(f"\nprecision@{args.top_k} (share of top-k analogs in the anchor's own industry)")
        print(f"  financial shape   : {json.dumps(fin)}")
        print(f"  business substance: {json.dumps(bus)}")
        print(f"\nbusiness map by anchor coverage:")
        for band, stats in _business_precision_by_coverage(conn, industries, args.top_k).items():
            print(f"  {band:9s} {json.dumps(stats)}")
        print(f"\nrandom baseline ≈ 1 / industries_in_corpus")
        print(f"  industries labelled in corpus: {len(set(industries.values()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
