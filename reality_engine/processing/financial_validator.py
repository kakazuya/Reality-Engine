"""Task 7: Financial secondary validation ROIC>WACC spread>0.05 only after moat/policy
+
Residual denominator handling: synthetic ETF/BEES/liquid/rights instruments are
excluded from the operating-equity completeness denominator (never filled with zeros).
See reality_engine/processing/instrument_classifier.py for deterministic rules.
"""

from typing import Any, Dict, List, Optional

def is_financially_valid(roic: float, wacc: float, fcf_margin: float = None) -> bool:
    spread = roic - wacc
    return spread > 0.05


# ---------------------------------------------------------------------------
# Annual-financial denominator validation (operating-equity only)
# ---------------------------------------------------------------------------
def validate_annual_financial_denominator(conn) -> Dict[str, Any]:
    """Validate annual financial completeness over the operating-equity universe only.

    Synthetic instruments (ETFs/BEES/liquid/rights/INE_AUTO placeholders) are
    excluded from the denominator. Never fabricates financial facts or inserts zeros.

    Args:
        conn: sqlite3.Connection or DB-API connection with execute().

    Returns:
        dict with operating_total, synthetic_total, covered, missing,
        coverage_pct_operating, synthetic_excluded, total_active.
        Falls back to empty counts if tables absent.
    """
    try:
        from reality_engine.processing.instrument_classifier import is_operating_equity
    except Exception:
        def is_operating_equity(rec):  # type: ignore
            return True

    def _scalar(sql: str, params=()):
        try:
            row = conn.execute(sql, params).fetchone()
            return row[0] if row else 0
        except Exception:
            return 0

    def _rows(sql: str, params=()):
        try:
            return conn.execute(sql, params).fetchall()
        except Exception:
            return []

    # Fetch master universe (active only)
    try:
        master_rows = _rows("SELECT * FROM master_companies WHERE is_active=1")
        # sqlite3.Row vs tuple handling: convert to dict via keys if available
        comps: List[Dict[str, Any]] = []
        for r in master_rows:
            try:
                comps.append(dict(r))
            except Exception:
                # fallback: r is tuple with known order? Skip.
                continue
        # If dict conversion failed due to tuple, try via description
        if not comps and master_rows:
            try:
                cols = [d[0] for d in conn.execute("SELECT * FROM master_companies WHERE is_active=1").description]
                for r in master_rows:
                    comps.append({k: v for k, v in zip(cols, r)})
            except Exception:
                pass
    except Exception:
        comps = []

    operating = [c for c in comps if is_operating_equity(c)]
    synthetic = [c for c in comps if not is_operating_equity(c)]
    operating_total = len(operating)
    synthetic_total = len(synthetic)

    # Covered operating: has annual_financials row (join on isin or symbol)
    try:
        annual_rows = _rows("SELECT DISTINCT isin, symbol FROM annual_financials")
        annual_isins = set()
        annual_symbols = set()
        for r in annual_rows:
            try:
                d = dict(r)
                if d.get("isin"):
                    annual_isins.add(str(d["isin"]).strip().upper())
                if d.get("symbol"):
                    annual_symbols.add(str(d["symbol"]).strip().upper())
            except Exception:
                # tuple fallback
                if len(r) >= 2:
                    if r[0]:
                        annual_isins.add(str(r[0]).strip().upper())
                    if r[1]:
                        annual_symbols.add(str(r[1]).strip().upper())
    except Exception:
        annual_isins = set()
        annual_symbols = set()

    covered = 0
    for c in operating:
        isin_u = str(c.get("isin") or "").strip().upper()
        sym_u = str(c.get("nse_symbol") or "").strip().upper()
        if (isin_u and isin_u in annual_isins) or (sym_u and sym_u in annual_symbols):
            covered += 1

    missing = max(0, operating_total - covered)
    coverage_pct = round(100.0 * covered / operating_total, 2) if operating_total else 0.0
    return {
        "operating_total": operating_total,
        "synthetic_total": synthetic_total,
        "total_active": operating_total + synthetic_total,
        "covered": covered,
        "missing": missing,
        "coverage_pct_operating": coverage_pct,
        "synthetic_excluded": synthetic_total,
    }


def discover_microcap_official_filing_candidates(conn, limit: int = 12) -> List[Dict[str, Any]]:
    """Identify operating microcaps missing annual_financials for official filing recovery.

    Deterministic, no network. Returns up to *limit* (default 12) active operating
    equities with no annual_financials row, ordered by nse_symbol ASC. Each record
    includes suggested_source hint (bse_official if bse_code present else nse_official).

    Args:
        conn: sqlite3.Connection with master_companies and annual_financials.
        limit: max candidates (default 12).

    Never fabricates zeros; only identifies candidates for BSE/NSE official XBRL fetch.
    """
    try:
        from reality_engine.processing.instrument_classifier import is_operating_equity
    except Exception:
        def is_operating_equity(rec):  # type: ignore
            return True

    limit = max(1, int(limit))
    try:
        rows = conn.execute("SELECT * FROM master_companies WHERE is_active=1 ORDER BY nse_symbol ASC").fetchall()
        comps: List[Dict[str, Any]] = []
        for r in rows:
            try:
                comps.append(dict(r))
            except Exception:
                continue
        if not comps and rows:
            try:
                cols = [d[0] for d in conn.execute("SELECT * FROM master_companies WHERE is_active=1 ORDER BY nse_symbol ASC").description]
                for r in rows:
                    comps.append({k: v for k, v in zip(cols, r)})
            except Exception:
                pass
    except Exception:
        comps = []

    operating = [c for c in comps if is_operating_equity(c)]
    # Build annual key sets
    try:
        annual_rows = conn.execute("SELECT DISTINCT isin, symbol FROM annual_financials").fetchall()
        annual_isins = set()
        annual_symbols = set()
        for r in annual_rows:
            try:
                d = dict(r)
                if d.get("isin"):
                    annual_isins.add(str(d["isin"]).strip().upper())
                if d.get("symbol"):
                    annual_symbols.add(str(d["symbol"]).strip().upper())
            except Exception:
                if len(r) >= 2:
                    if r[0]:
                        annual_isins.add(str(r[0]).strip().upper())
                    if r[1]:
                        annual_symbols.add(str(r[1]).strip().upper())
    except Exception:
        annual_isins = set()
        annual_symbols = set()

    out: List[Dict[str, Any]] = []
    for c in operating:
        isin_u = str(c.get("isin") or "").strip().upper()
        sym_u = str(c.get("nse_symbol") or "").strip().upper()
        has_annual = (isin_u and isin_u in annual_isins) or (sym_u and sym_u in annual_symbols)
        if not has_annual:
            rec = dict(c)
            rec["suggested_source"] = "bse_official" if rec.get("bse_code") else "nse_official"
            rec["reason_missing"] = "no_annual_row"
            out.append(rec)
            if len(out) >= limit:
                break
    return out


if __name__ == "__main__":
    tests=[(0.18,0.10,True),(0.06,0.05,False),(0.12,0.08,False)]
    for roic,wacc,exp in tests:
        print(roic, wacc, is_financially_valid(roic,wacc), "expect", exp)
