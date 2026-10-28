"""Stratified 60-company pilot universe (golden-rule step 4, tasks/pilot60).

    python -m reality_engine.pilot.universe60
    python -m reality_engine.pilot.universe60 --as-of 2026-09-30 --t1 .tmp/pilot_all

Buckets (task brief, 2026-10-28): market cap at ``--as-of`` (2026-09-30) from the T1
``company_state_daily`` build — large = top 100 by mcap, mid+small = 101-750, micro =
the rest — with traded value > 0 on >= 200 FY26 sessions (px_nse/px_bse).  Stratify by
sector so each bucket covers as many sectors as possible, preferring companies that
hold every FY25+ doc type; large/mid must hold >= 1 concall and >= 1 AR.

Outputs (tasks/pilot60/):
  UNIVERSE.csv        60 rows: isin, symbol, bucket, sector, doc counts by type
  SECTOR_BUCKET.md    sector x bucket table
  T2_ISINS.txt        the 60 + the 30 regression ISINs (the T2 chunk set)

Sector labels follow decision 8: our own label first (``company_industry.sector``,
resolved by ISIN), the BSE umbrella in its own column when the sector pilot labelled
the company.  Read-only on every DB.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA_ROOT = Path(os.environ.get("REALITY_DATA_ROOT", REPO / "reality_engine" / "data"))
OUT_DIR = REPO / "tasks" / "pilot60"
AS_OF = "2026-09-30"
FY26_START, FY26_END = "2025-04-01", "2026-03-31"
FY25_CUTOFF = "2024-04-01"
BUCKET_SIZES = {"LARGE": 10, "MID-SMALL": 20, "MICRO": 30}
DOC_TYPES = ("annual_report", "concall", "deck", "results_notes", "announcement")
REG_ISIN_RE = re.compile(r"\|\s*\d+\s*\|\s*(INE[A-Z0-9]{9})\s*\|")


def ro(path: Path) -> sqlite3.Connection:
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(path, timeout_s=90)
    con.row_factory = sqlite3.Row
    return con


def t1_market(t1: Path) -> sqlite3.Connection:
    path = t1 / "market_state_pilot.db"
    if not path.is_file():
        raise SystemExit(f"missing {path}: run python -m reality_engine.pilot.build_t1 "
                         f"--universe all --out {t1}")
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

STEP = {"MICRO": 0, "MID-SMALL": 1, "LARGE": 2}


def mcap_ranks(mcon: sqlite3.Connection, as_of: str, tiers: dict[str, str],
               log=print) -> dict[str, dict]:
    """Latest session <= as_of, ranked by mcap_cr.

    A company whose computed bucket and held tier differ by two steps (LARGE vs
    MICRO) is a broken mcap row (paid-up/face parse), not a re-tiering: it is
    dropped and the surviving list is re-ranked so the top 100 stays 100 names.
    """
    day = mcon.execute("SELECT MAX(date) FROM company_state_daily WHERE date <= ?",
                       (as_of,)).fetchone()[0]
    if not day:
        raise SystemExit("company_state_daily is empty: rebuild T1")
    print(f"mcap snapshot session: {day}")
    rows = mcon.execute(
        "SELECT isin, mcap_cr FROM company_state_daily WHERE date = ? AND mcap_cr > 0 "
        "ORDER BY mcap_cr DESC", (day,)).fetchall()
    kept, rejected = [], []
    for rank, (isin, mcap) in enumerate(rows, 1):
        bucket = "LARGE" if rank <= 100 else ("MID-SMALL" if rank <= 750 else "MICRO")
        held = tiers.get(isin)
        if held and abs(STEP[held] - STEP[bucket]) >= 2:
            rejected.append((isin, bucket, held, mcap, rank))
            continue
        kept.append((isin, mcap))
    out = {}
    for rank, (isin, mcap) in enumerate(kept, 1):
        bucket = "LARGE" if rank <= 100 else ("MID-SMALL" if rank <= 750 else "MICRO")
        out[isin] = {"mcap_cr": mcap, "rank": rank, "bucket": bucket}
    if rejected:
        log(f"dropped {len(rejected)} broken mcap rows (two steps from the held tier), e.g. "
            + ", ".join(f"{i}[{b} vs {h}]" for i, b, h, _, _ in rejected[:5]))
    return out


def traded_sessions(ranks: dict[str, dict]) -> dict[str, int]:
    """FY26 sessions with traded value > 0 (NSE or BSE), entity-level px_daily."""
    import duckdb
    snaps = sorted((DATA_ROOT / "snapshots").glob("truth_*.duckdb"))
    if not snaps:
        raise SystemExit("no truth snapshot for the FY26 traded-session rule")
    con = duckdb.connect(str(snaps[-1]), read_only=True)
    try:
        rows = con.execute(
            "SELECT isin, COUNT(*) FROM ("
            " SELECT isin, date FROM px_nse WHERE date BETWEEN ? AND ? AND value_inr > 0"
            " UNION SELECT isin, date FROM px_bse WHERE date BETWEEN ? AND ? AND value_inr > 0"
            ") GROUP BY isin", [FY26_START, FY26_END, FY26_START, FY26_END]).fetchall()
    finally:
        con.close()
    return {r[0]: int(r[1]) for r in rows}


COARSE = {"", "other", "unclassified", "general diversified", "diversified"}
TIER_TO_BUCKET = {"LARGE": "LARGE", "MID": "MID-SMALL", "SMALL": "MID-SMALL",
                  "MICRO": "MICRO"}


def held_tiers() -> dict[str, str]:
    """Held mcap tier (master_companies) -> our bucket, to reject a broken mcap row."""
    ei = ro(DATA_ROOT / "equity_intelligence.db")
    out = {}
    try:
        for isin, tier in ei.execute("SELECT isin, market_cap_tier FROM master_companies"):
            if tier:
                out[isin] = TIER_TO_BUCKET.get(str(tier).upper(), "")
    finally:
        ei.close()
    return out


def sector_map(mcon: sqlite3.Connection) -> dict[str, dict]:
    """our label (NSE sector, by ISIN) + the BSE umbrella where the pilot labelled it."""
    out = {}
    try:
        for isin, sector, industry, macro in mcon.execute(
                "SELECT isin, sector, industry, macro FROM company_sector_pit"):
            if (sector or "").strip().lower() in COARSE:
                sector = industry or sector
            out[isin] = {"sector": sector or industry or macro, "bse_sector": ""}
    except sqlite3.Error:
        pass
    ei = ro(DATA_ROOT / "equity_intelligence.db")
    for isin, sector, industry in ei.execute(
            "SELECT isin, sector, industry FROM master_companies"):
        if (sector or "").strip().lower() in COARSE:
            sector = industry or sector
        row = out.setdefault(isin, {"sector": sector or industry or "Unclassified",
                                    "bse_sector": ""})
        if not row.get("sector"):
            row["sector"] = sector or industry or "Unclassified"
    ei.close()
    label = REPO / "tasks" / "sector_pilot" / "sector_label_pilot.csv"
    if label.is_file():
        for row in csv.DictReader(label.open(encoding="utf-8")):
            if row["isin"] in out:
                out[row["isin"]]["bse_sector"] = row.get("bse_sector") or ""
    return out


def doc_counts(isins: list[str], symbols: dict[str, str]) -> dict[str, dict]:
    """FY25+ documents per ISIN and type, from the same registries the T2 build reads."""
    q = ",".join("?" * len(isins))
    counts: dict[str, dict] = {i: dict.fromkeys(DOC_TYPES, 0) for i in isins}
    ar = ro(DATA_ROOT / "ar_facts.db")
    for isin, n in ar.execute(
            f"SELECT isin, COUNT(*) FROM ar_docs WHERE isin IN ({q}) AND filed_at >= ? "
            f"GROUP BY isin", isins + [FY25_CUTOFF]):
        counts[isin]["annual_report"] = n
    ar.close()
    ei = ro(DATA_ROOT / "equity_intelligence.db")
    for doc_type, key in (("CONCALL_TRANSCRIPT", "concall"),
                          (("FINANCIAL_RESULT", "RESULTS"), "results_notes")):
        types = (doc_type,) if isinstance(doc_type, str) else doc_type
        for isin, n in ei.execute(
                f"SELECT isin, COUNT(*) FROM corporate_documents WHERE isin IN ({q}) "
                f"AND doc_type IN ({','.join('?' * len(types))}) "
                f"AND COALESCE(bse_dissem_ts, publication_date) >= ? GROUP BY isin",
                isins + list(types) + [FY25_CUTOFF]):
            counts[isin][key] = n
    ei.close()
    dk = ro(DATA_ROOT / "deck_figures.db")
    for isin, n in dk.execute(
            f"SELECT isin, COUNT(*) FROM deck_sources WHERE isin IN ({q}) AND known_at >= ? "
            f"GROUP BY isin", isins + [FY25_CUTOFF]):
        counts[isin]["deck"] = n
    dk.close()
    ann = ro(DATA_ROOT / "bse_announcements.db")
    by_symbol = {sym: isin for isin, sym in symbols.items() if sym and isin in counts}
    syms = sorted(by_symbol)
    if syms:
        for sym, n in ann.execute(
                f"SELECT symbol, COUNT(*) FROM ann WHERE symbol IN ({','.join('?' * len(syms))}) "
                f"AND DissemDT >= ? GROUP BY symbol", syms + [FY25_CUTOFF]):
            if by_symbol.get(sym) in counts:
                counts[by_symbol[sym]]["announcement"] = n
    ann.close()
    return counts


def regression_isins() -> list[str]:
    spec = REPO / "tasks" / "arch_v3" / "PILOT_SPEC.md"
    if not spec.is_file():
        return []
    return REG_ISIN_RE.findall(spec.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------

def score(docs: dict) -> float:
    """Prefer companies holding every doc type, then more documents."""
    have = sum(1 for t in DOC_TYPES if docs[t] > 0)
    return have * 1000 + min(50, docs["annual_report"] + docs["concall"] + docs["deck"])


def select(ranks: dict[str, dict], traded: dict[str, int], sectors: dict[str, dict],
           docs: dict[str, dict], required: set[str]) -> list[dict]:
    """Greedy sector round-robin inside each bucket.

    The 60 are a pure stratified sample.  The bank-regression ISINs are NOT forced in:
    the T2 set is the union of the 60 and every bank-named regression ISIN, so those
    answers stay covered without unbalancing the 10/20/30 buckets.
    """
    chosen: list[dict] = []
    for bucket, size in BUCKET_SIZES.items():
        pool = []
        for isin, info in ranks.items():
            if info["bucket"] != bucket or traded.get(isin, 0) < 200:
                continue
            d = docs.get(isin, dict.fromkeys(DOC_TYPES, 0))
            if bucket in ("LARGE", "MID-SMALL") and (d["concall"] < 1 or d["annual_report"] < 1):
                continue
            pool.append((isin, sector(sectors, isin), d, score(d)))
        picked: set[str] = set()
        while len(picked) < size:
            sector_count = Counter(r["sector"] for r in chosen if r["bucket"] == bucket)
            best, best_key = None, None
            for isin, sec, d, sc in pool:
                if isin in picked:
                    continue
                key = (sector_count[sec], -sc)
                if best_key is None or key < best_key:
                    best, best_key = (isin, sec, d), key
            if best is None:
                break
            isin, sec, d = best
            picked.add(isin)
            chosen.append({"isin": isin, "bucket": bucket, "sector": sec, "docs": d,
                           "required": isin in required,
                           **{k: ranks[isin][k] for k in ("mcap_cr", "rank")}})
    return chosen


def sector(sectors: dict[str, dict], isin: str) -> str:
    return (sectors.get(isin) or {}).get("sector") or "Unclassified"


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def write_outputs(chosen: list[dict], sectors: dict[str, dict], reg: list[str]) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    order = {"LARGE": 0, "MID-SMALL": 1, "MICRO": 2}
    chosen = sorted(chosen, key=lambda r: (order[r["bucket"]], r["sector"], r["isin"]))
    fields = ["isin", "symbol", "bucket", "sector", "bse_sector", "mcap_cr", "mcap_rank",
              *DOC_TYPES, "required_regression"]
    with (OUT_DIR / "UNIVERSE.csv").open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for row in chosen:
            writer.writerow({
                "isin": row["isin"], "symbol": row.get("symbol", ""), "bucket": row["bucket"],
                "sector": row["sector"], "bse_sector": sectors.get(row["isin"], {}).get("bse_sector", ""),
                "mcap_cr": round(row["mcap_cr"], 1), "mcap_rank": row["rank"],
                **row["docs"], "required_regression": int(row["required"])})
    table: Counter = Counter((r["bucket"], r["sector"]) for r in chosen)
    buckets = list(BUCKET_SIZES)
    secs = sorted({r["sector"] for r in chosen})
    lines = ["# Sector x bucket (pilot-60)", "",
             "| sector | " + " | ".join(buckets) + " | total |",
             "|---|" + "---:|" * (len(buckets) + 1)]
    for sec in secs:
        vals = [table[(b, sec)] for b in buckets]
        lines.append(f"| {sec} | " + " | ".join(str(v) for v in vals) + f" | {sum(vals)} |")
    totals = [sum(1 for r in chosen if r["bucket"] == b) for b in buckets]
    lines.append("| **total** | " + " | ".join(f"**{v}**" for v in totals)
                 + f" | **{len(chosen)}** |")
    lines += ["", f"sectors covered: {len(secs)}"]
    (OUT_DIR / "SECTOR_BUCKET.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    t2 = sorted({r["isin"] for r in chosen} | set(reg))
    (OUT_DIR / "T2_ISINS.txt").write_text("\n".join(t2) + "\n", encoding="utf-8")
    print(f"UNIVERSE.csv: {len(chosen)} rows, {len(secs)} sectors; T2 set: {len(t2)} ISINs")
    for b in buckets:
        print(f"  {b}: {totals[buckets.index(b)]}")


def main(argv: list[str] | None = None) -> int:
    global OUT_DIR
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(OUT_DIR))
    ap.add_argument("--t1", default=str(REPO / ".tmp" / "pilot_all"))
    ap.add_argument("--as-of", default=AS_OF)
    args = ap.parse_args(argv)
    OUT_DIR = Path(args.out)
    mcon = t1_market(Path(args.t1))
    ranks = mcap_ranks(mcon, args.as_of, held_tiers())
    print(f"listed with mcap > 0 and a consistent held tier: {len(ranks)}")
    traded = traded_sessions(ranks)
    print(f"FY26 traded > 0 on >= 200 sessions: {sum(1 for n in traded.values() if n >= 200)}")
    sectors = sector_map(mcon)
    required = set(regression_isins())
    symbols = {}
    ei = ro(DATA_ROOT / "equity_intelligence.db")
    for isin, sym in ei.execute("SELECT isin, nse_symbol FROM master_companies"):
        symbols[isin] = sym or ""
    ei.close()
    counts = doc_counts(list(ranks), symbols)
    chosen = select(ranks, traded, sectors, counts, required)
    for row in chosen:
        row["symbol"] = symbols.get(row["isin"], "")
    write_outputs(chosen, sectors, regression_isins())
    mcon.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
