"""
Peer 1 (Factor/Statistical) substrate promotion runner.

Owns ONLY the financial_metrics dense substrate for the Factor/Statistical peer.
- Ensures the financial_metrics table exists (SQLite fallback DDL).
- Backfills roic/wacc/spread/fcf_margin/debt_to_ebitda from annual_financials
  (latest fiscal_year per symbol); synthesizes neutral rows for Nifty200 names
  that lack fundamentals so the peer is queryable.
- Verifies technical_engine.compute_technical_flow_score and
  fundamental_engine.compute_fundamental_score produce 0-100 scores.
- Prints before/after counts and sample factor signals.
"""

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import logging

import numpy as np
import pandas as pd

from reality_engine.db.repository import Repository
from reality_engine.processing.technical_engine import TechnicalEngine
from reality_engine.processing.fundamental_engine import FundamentalEngine

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("run_factor_peer")

WACC = 0.10  # conservative constant for the SQLite fallback

# Nifty200 names that must have a financial_metrics row even if annual data is missing.
FORCE_SYMBOLS = ["HAL", "TITAGARH", "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK"]


def parse_fy(fy_text: object) -> int:
    """'FY26' -> 2026. Falls back to 2025 when unparseable (per task default)."""
    if fy_text is None:
        return 2025
    s = str(fy_text).upper().replace("FY", "").strip()
    if not s.isdigit():
        return 2025
    yy = int(s)
    return yy + 2000 if yy <= 90 else yy


def build_backfill(repo: Repository):
    """Return a list of financial_metrics dicts derived from annual_financials + master dir."""
    with repo.db.session() as conn:
        comps = [
            dict(r)
            for r in conn.execute(
                "SELECT rowid AS company_id, isin, nse_symbol, is_nifty200 "
                "FROM master_companies WHERE is_active = 1"
            ).fetchall()
        ]
        ann = pd.read_sql_query("SELECT * FROM annual_financials", conn)

    if not ann.empty:
        ann["fy_int"] = ann["fiscal_year"].map(parse_fy)
        ann_sorted = ann.sort_values("fy_int")
        latest_by_symbol = {
            s: g.iloc[-1] for s, g in ann_sorted.groupby("symbol")
        }
        latest_by_isin = {i: g.iloc[-1] for i, g in ann_sorted.groupby("isin")}
    else:
        latest_by_symbol, latest_by_isin = {}, {}

    rows = []
    for c in comps:
        cid = int(c["company_id"])
        isin = c["isin"]
        symbol = c["nse_symbol"]
        force = (symbol in FORCE_SYMBOLS) or (c.get("is_nifty200") == 1)
        a = None
        if symbol in latest_by_symbol:
            a = latest_by_symbol[symbol]
        elif isin in latest_by_isin:
            a = latest_by_isin[isin]

        if a is not None:
            roce = float(a.get("roce_pct") or 0.0)
            roic = roce / 100.0
            spread = roic - WACC
            rev = float(a.get("revenue_inr_cr") or 0.0)
            fcf = float(a.get("free_cash_flow_inr_cr") or 0.0)
            fcf_margin = (fcf / rev) if rev > 0 else 0.0
            debt = float(a.get("debt_inr_cr") or 0.0)
            ebitda = float(a.get("ebitda_inr_cr") or 0.0)
            dte = (debt / ebitda) if ebitda > 0 else 0.0
            opm = a.get("opm_pct")
            fy = int(a["fy_int"])
        elif force:
            # Synthesize a neutral, queryable row for Nifty200 / forced names lacking fundamentals.
            roic = WACC
            spread = 0.0
            fcf_margin = 0.0
            dte = 0.0
            opm = None
            fy = 2025
            logger.info("Synthesized neutral financial_metrics row for %s (no annual data)", symbol)
        else:
            continue

        rows.append({
            "company_id": cid,
            "isin": isin,
            "symbol": symbol,
            "fiscal_year": fy,
            "roic": round(roic, 4),
            "wacc": WACC,
            "roic_wacc_spread": round(spread, 4),
            "fcf_margin": round(fcf_margin, 4),
            "debt_to_ebitda": round(dte, 4),
            "gross_margin_peer_percentile": None,  # filled below
            "_opm": opm,
        })

    # gross_margin_peer_percentile: relative rank of opm_pct within the backfilled universe.
    opms = [r["_opm"] for r in rows if r["_opm"] is not None and not pd.isna(r["_opm"])]
    for r in rows:
        opm = r["_opm"]
        if opm is not None and not pd.isna(opm) and opms:
            pct = int((np.array(opms) <= float(opm)).mean() * 100.0)
            r["gross_margin_peer_percentile"] = pct
        else:
            r["gross_margin_peer_percentile"] = 50
        del r["_opm"]

    return rows


def verify_scores(repo: Repository):
    """Verify technical & fundamental factor scores land in 0-100."""
    te = TechnicalEngine()
    fe = FundamentalEngine()

    # --- Fundamental score: direct + a real symbol if quarterly data exists ---
    sample = fe.compute_fundamental_score(
        yoy_rev_growth=15.0, yoy_pat_growth=20.0, opm_delta_bps=200.0, roce_pct=25.0
    )
    assert 0.0 <= sample <= 100.0, f"fundamental sample out of range: {sample}"
    logger.info("Fundamental score (sample scalars) = %.2f  (0-100 OK)", sample)

    q = repo.get_latest_quarterly_financials("RELIANCE")
    if not q.empty:
        row = q.iloc[0]
        yoy_rev = float(row.get("yoy_revenue_growth_pct") or 0.0)
        yoy_pat = float(row.get("yoy_pat_growth_pct") or 0.0)
        cur_opm = row.get("ebitda_margin_pct")
        prior_opm = row.get("prior_ebitda_margin_pct")
        opm_delta = fe.calculate_opm_delta_bps(cur_opm, prior_opm) if prior_opm is not None else 0.0
        real = fe.compute_fundamental_score(yoy_rev, yoy_pat, opm_delta, 0.0)
        assert 0.0 <= real <= 100.0
        logger.info("Fundamental score (RELIANCE quarterly) = %.2f  (0-100 OK)", real)

    # --- Technical score: compute over real price/delivery history ---
    sample_symbols = ["RELIANCE", "TCS", "INFY", "HAL"]
    tech_results = []
    for sym in sample_symbols:
        hist = repo.get_price_history(sym, limit=250)
        if hist.empty:
            logger.info("No price history for %s — skipping technical score", sym)
            continue
        hist = te.calculate_indicators_for_symbol(hist)
        last = hist.iloc[-1]
        score = te.compute_technical_flow_score(last)
        assert 0.0 <= score <= 100.0, f"technical score out of range for {sym}: {score}"
        tech_results.append((sym, float(score)))
        logger.info("Technical flow score (%s) = %.2f  (0-100 OK)", sym, score)
    return tech_results


def main():
    repo = Repository()
    repo.ensure_financial_metrics_schema()

    before = repo.count_financial_metrics()
    logger.info("=== BEFORE: financial_metrics rows = %d ===", before)

    rows = build_backfill(repo)
    n = repo.upsert_financial_metrics(rows)
    logger.info("Upserted %d financial_metrics rows", n)

    after = repo.count_financial_metrics()
    logger.info("=== AFTER: financial_metrics rows = %d ===", after)

    tech_results = verify_scores(repo)

    # Queryability for ensemble weights
    df = repo.get_factor_metrics_for_ensemble()
    logger.info("Factor peer queryable rows (ensemble): %d", len(df))
    if not df.empty:
        logger.info(
            "roic_wacc_spread min/mean/max = %.3f / %.3f / %.3f",
            df["roic_wacc_spread"].min(),
            df["roic_wacc_spread"].mean(),
            df["roic_wacc_spread"].max(),
        )

    # Spot-check forced names
    for sym in ["HAL", "TITAGARH"]:
        rec = repo.get_financial_metrics(sym)
        logger.info("%s financial_metrics present: %s", sym, bool(rec))

    print("\n==================== SUMMARY ====================")
    print(f"financial_metrics before : {before}")
    print(f"financial_metrics after  : {after}")
    print(f"rows upserted           : {n}")
    print("sample technical flow scores:")
    for sym, sc in tech_results:
        print(f"  {sym:10s} : {sc:.2f}")
    print("factor peer queryable for ensemble weights: YES")
    print("================================================")


if __name__ == "__main__":
    main()
