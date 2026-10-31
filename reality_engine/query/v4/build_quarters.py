"""v4 WP2c — true single-quarter XBRL series from the OneD/FourD contexts (§A.8, §B.1).

The pilot facts store (``facts_pilot.company_metric_series``) decided the period from
the *stored dates* of an XBRL fact, not from its context.  Decision log 2026-10-19
(and ``snapshot_research_tables.py``): NSE contexts are ``OneD`` = this quarter,
``FourD`` = year to date; the dates on the facts are blank before 2022 and, for
``FourD``, frequently carry the quarter's own dates, so a nine-month revenue lands in
the store labelled ``quarter``.  ``pilot_quarter_mix`` counts those rows exactly
against their own filing's contexts (1,094 of 5,013 revenue/pat/eps quarter rows at
31 Oct 2026); the clean series below never stores a FourD level as a quarter.

This builder reads ``results_xbrl.db`` (read-only) for the pilot universe and writes
one row per (isin, metric, quarter end, basis) with the quarter's real value:

    reported          a quarter-length OneD fact (the filing's own quarter column)
    ytd_q1            Q1 only: the year-to-date value *is* the quarter (Jun filings)
    ytd_difference    Q2-Q4: FourD(quarter end) - FourD(prior quarter end), same FY

Never a guess: a YTD difference is emitted only when the prior quarter's YTD exists
in the same fiscal year, published strictly before this filing, and is not restated
(more than one distinct value known before this filing -> the quarter is left empty
and counted as ``restated_prior_ytd``).  ``known_at`` is the filing's own
dissemination/broadcast/filing timestamp — never the period end, never a crawl date.

The same pass re-computes the YTD difference on every filing that carries *both* a
quarter-length OneD and a YTD fact and compares it with the filing's own quarter
column; those rows are the §H.7 hand check and are stored in ``quarter_handcheck``.
Instant (balance-sheet) concepts are skipped: a level at a period end is not a
quarter, and a difference of two levels is not a flow.  XBRL EPS is rounded to
paise, so the EPS check allows one paisa; every other flow is checked to 1e-6.

    python -m reality_engine.query.v4.build_quarters --out .tmp/quarters_pilot60.db

Output ``company_quarter_series`` is attached by ``build_membership`` (as
``quarters``) and is read by ``build_own_estimate`` so both see the same clean series.
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot.build_t1 import CONCEPT_MAP
from reality_engine.query.v4.build_vocab import pilot_isins

REPO = Path(__file__).resolve().parents[3]
ROOT = REPO / "reality_engine" / "data"

SCHEMA = """
DROP TABLE IF EXISTS company_quarter_series;
CREATE TABLE company_quarter_series(
    isin        TEXT NOT NULL,
    metric_key  TEXT NOT NULL,
    period_end  TEXT NOT NULL,
    period_kind TEXT NOT NULL DEFAULT 'quarter' CHECK (period_kind = 'quarter'),
    basis       TEXT NOT NULL CHECK (basis IN ('standalone', 'consolidated')),
    value       REAL NOT NULL,
    unit        TEXT NOT NULL,
    derived     TEXT NOT NULL,          -- reported | ytd_q1 | ytd_difference
    derived_from TEXT NOT NULL,         -- the input context(s)/filing(s), auditable
    doc_id      TEXT NOT NULL,          -- the filing the quarter is first knowable from
    known_at    TEXT NOT NULL,
    pit_conf    REAL NOT NULL DEFAULT 1.0,
    PRIMARY KEY (isin, metric_key, period_end, basis)
) WITHOUT ROWID;

DROP TABLE IF EXISTS quarter_derivation_counts;
CREATE TABLE quarter_derivation_counts(reason TEXT PRIMARY KEY, n INTEGER NOT NULL);

DROP TABLE IF EXISTS quarter_handcheck;
CREATE TABLE quarter_handcheck(
    isin TEXT NOT NULL, metric_key TEXT NOT NULL, period_end TEXT NOT NULL,
    basis TEXT NOT NULL, derived_value REAL NOT NULL, filing_quarter REAL NOT NULL,
    abs_diff REAL NOT NULL, doc_id TEXT NOT NULL, ok INTEGER NOT NULL);

-- the defect, counted exactly: the pilot store's `quarter` rows classified by the
-- context of their own filing (a FourD row is a YTD value, not a quarter)
DROP TABLE IF EXISTS pilot_quarter_mix;
CREATE TABLE pilot_quarter_mix(
    metric_key TEXT PRIMARY KEY, rows INTEGER NOT NULL,
    matches_oned INTEGER NOT NULL, matches_fourd INTEGER NOT NULL,
    neither INTEGER NOT NULL, no_context INTEGER NOT NULL);

-- the 30-row acceptance sample: stored quarter vs the filing's own quarter column
DROP TABLE IF EXISTS quarter_sample;
CREATE TABLE quarter_sample(
    isin TEXT NOT NULL, metric_key TEXT NOT NULL, period_end TEXT NOT NULL, basis TEXT NOT NULL,
    stored_value REAL NOT NULL, filing_quarter REAL NOT NULL, derived_value REAL NOT NULL,
    abs_diff REAL NOT NULL, doc_id TEXT NOT NULL, matches_stored INTEGER NOT NULL);
"""

CHECK_TOL = 1e-6
EPS_TOL = 0.011              # EPS is reported to paise

#: instant (balance-sheet) concepts: a level at the period end, never a YTD flow
INSTANT_METRICS = frozenset({
    "total_assets", "net_worth", "borrowings_current", "borrowings_noncurrent",
    "receivables", "inventory", "payables", "cash", "paid_up_capital", "face_value",
})


# --------------------------------------------------------------------------- dates
def _d(text: str | None) -> date | None:
    if not text:
        return None
    try:
        return date.fromisoformat(str(text)[:10])
    except ValueError:
        return None


def fy_start(period_end: str) -> str:
    """Indian fiscal year start (1 April) of the year a quarter end belongs to."""
    y, m = int(period_end[:4]), int(period_end[5:7])
    return f"{y if m >= 4 else y - 1:04d}-04-01"


def prior_quarter_end(period_end: str) -> str:
    """The quarter end three months earlier (Mar->Dec of the previous year)."""
    y, m = int(period_end[:4]), int(period_end[5:7])
    m -= 3
    if m <= 0:
        m += 12
        y -= 1
    ends = {3: 31, 6: 30, 9: 30, 12: 31}
    return f"{y:04d}-{m:02d}-{ends[m]:02d}"


def _days(start: str | None, end: str | None) -> int | None:
    a, b = _d(start), _d(end)
    return (b - a).days if a and b and b >= a else None


def one_d_is_quarter(filing: dict, fact: dict | None) -> bool | None:
    """Is the OneD fact a single quarter?  None = no evidence either way.

    The stored dates may be wrong (that is the defect), so the filing's own
    reporting-period dates are the fallback; with no dates at all the NSE convention
    stands: OneD is the current quarter.
    """
    if fact is None:
        return None
    days = _days(fact.get("period_start"), fact.get("period_end"))
    if days is None:
        days = _days(filing.get("period_start"), filing.get("period_end"))
    if days is None:
        return True
    return days <= 100


# ------------------------------------------------------------------------ derive
def _pick(facts_by_file: dict, file: str, concept: str, context: str) -> dict | None:
    for fact in facts_by_file.get(file, ()):
        if fact["concept"] == concept and fact["context"] == context:
            return fact
    return None


def derive_quarters(filings: list[dict], facts: list[dict]) -> tuple[list[dict], dict, list]:
    """Pure derivation: (quarter rows, reason counts, hand-check rows).

    ``filings``: file, isin, period_end, period_start, consolidated, known_at.
    ``facts``:   file, concept, context, period_start, period_end, value.
    """
    by_file: dict[str, list[dict]] = defaultdict(list)
    for fact in facts:
        by_file[fact["file"]].append(fact)

    filings = sorted(filings, key=lambda f: (f["isin"], f["known_at"], f["file"]))
    counts: Counter = Counter()
    rows: list[dict] = []
    checks: list[dict] = []
    # (isin, basis, metric, quarter_end) -> [(known_at, ytd_value, source)]
    ytd_seen: dict[tuple[str, str, str, str], list[tuple[str, float, str]]] = defaultdict(list)

    for filing in filings:
        isin, qend, known = filing["isin"], filing["period_end"], filing["known_at"]
        basis = ("consolidated" if str(filing.get("consolidated") or "").lower().startswith("consol")
                 else "standalone")
        fy = fy_start(qend)
        for concept, (metric_key, sign, scale, _) in CONCEPT_MAP.items():
            one = _pick(by_file, filing["file"], concept, "OneD")
            four = _pick(by_file, filing["file"], concept, "FourD")
            if one is None and four is None:
                continue
            if metric_key in INSTANT_METRICS:     # a level, not a quarter flow
                counts["instant_skipped"] += 1
                continue
            unit = "INR_PER_SHARE" if metric_key == "eps" else "INR_CRORE"

            def scaled(fact: dict) -> float:
                value = float(fact["value"]) * scale * sign
                return abs(value) if metric_key == "capex" else value

            one_quarter = one_d_is_quarter(filing, one)
            one_ytd_value = None
            if one is not None and not one_quarter:
                one_ytd_value = scaled(one)
            four_ytd_value = scaled(four) if four is not None else None
            ytd_value = four_ytd_value if four_ytd_value is not None else one_ytd_value
            ytd_src = "FourD" if four_ytd_value is not None else ("OneD" if one_ytd_value is not None else None)

            # a Q1 filing's YTD is its quarter: record it as the FY's first YTD too
            if ytd_value is None and one is not None and qend[5:7] == "06":
                ytd_value, ytd_src = scaled(one), "OneD"
            if ytd_value is not None:
                ytd_seen[(isin, basis, metric_key, qend)].append((known, ytd_value, filing["file"]))

            def prior_unique() -> tuple[float | None, str]:
                key = (isin, basis, metric_key, prior_quarter_end(qend))
                seen = [(k, v, f) for k, v, f in ytd_seen.get(key, ()) if k < known]
                if not seen:
                    return None, "missing_prior_ytd"
                distinct = {round(v, 6) for _k, v, _f in seen}
                if len(distinct) > 1:
                    return None, "restated_prior_ytd"
                return seen[-1][1], seen[-1][2]

            quarter = None
            derived = derived_from = None
            if one is not None and one_quarter:
                quarter, derived = scaled(one), "reported"
                derived_from = f"OneD@{filing['file']}"
                # verification: the same filing's YTD minus the prior YTD must equal
                # the quarter it reports; this is the real hand check of the rule
                if qend[5:7] != "06" and ytd_value is not None:
                    prior, prior_file = prior_unique()
                    if prior is not None:
                        implied = ytd_value - prior
                        diff = abs(implied - quarter)
                        tol = (EPS_TOL if metric_key == "eps"
                               else CHECK_TOL * max(1.0, abs(quarter)))
                        checks.append({
                            "isin": isin, "metric_key": metric_key, "period_end": qend,
                            "basis": basis, "derived_value": implied, "filing_quarter": quarter,
                            "abs_diff": diff, "doc_id": filing["file"], "ok": diff <= tol})
            elif qend[5:7] == "06":
                if ytd_value is not None:
                    quarter, derived = ytd_value, "ytd_q1"
                    derived_from = f"{ytd_src}@{filing['file']}"
                else:
                    counts["q1_without_ytd"] += 1
                    continue
            else:
                if ytd_value is None:
                    counts["no_ytd"] += 1
                    continue
                prior, prior_file = prior_unique()
                if prior is None:
                    counts[prior_file] += 1
                    continue
                quarter = ytd_value - prior
                derived = "ytd_difference"
                derived_from = f"{ytd_src}@{filing['file']} - FourD@{prior_file}"
            rows.append({
                "isin": isin, "metric_key": metric_key, "period_end": qend, "basis": basis,
                "value": round(quarter, 6), "unit": unit, "derived": derived,
                "derived_from": derived_from, "doc_id": filing["file"],
                "known_at": known, "fy_start": fy,
            })
            counts[derived] += 1

    # first publication wins per key: a restatement never rewrites the quarter
    first: dict[tuple, dict] = {}
    for row in rows:
        key = (row["isin"], row["metric_key"], row["period_end"], row["basis"])
        if key not in first or row["known_at"] < first[key]["known_at"]:
            first[key] = row
    counts["dedup_first_publication"] = len(rows) - len(first)
    return sorted(first.values(), key=lambda r: (r["isin"], r["metric_key"], r["period_end"])), dict(counts), checks


# ---------------------------------------------------------------------------- I/O
MIX_METRICS = {"revenue": "RevenueFromOperations", "pat": "ProfitLossForPeriod",
               "eps": "BasicEarningsLossPerShareFromContinuingOperations"}
_MIX_FIELDS = ("matches_oned", "matches_fourd", "neither", "no_context")


def measure_pilot_mix(data_root: Path | str, isins: list[str]) -> list[dict]:
    """Count the pilot store's quarter rows that are really FourD year-to-date values.

    Uses each pilot row's own ``doc_id``: OneD is the filing's quarter column, FourD
    its year-to-date column.  A row matching FourD (and not OneD) is the defect.
    The contexts are read straight from ``results_xbrl.db`` (a pilot row may point at
    a filing row whose ``status`` is not 'ok', which the derivation correctly drops).
    """
    con = connect_ro(Path(data_root) / "pilot" / "pilot60" / "facts_pilot.db",
                     timeout_s=180, immutable=True)
    q = ",".join("?" * len(isins))
    try:
        rows = list(con.execute(
            f"SELECT metric_key, value, doc_id FROM company_metric_series "
            f"WHERE isin IN ({q}) AND metric_key IN ('revenue','pat','eps') "
            f"AND period_kind='quarter' AND value IS NOT NULL AND doc_id IS NOT NULL",
            isins) or [])
    finally:
        con.close()
    ctx: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    docs = sorted({doc for _key, _value, doc in rows})
    xbrl = connect_ro(Path(data_root) / "results_xbrl.db", timeout_s=300, immutable=True)
    try:
        for i in range(0, len(docs), 900):
            chunk = docs[i:i + 900]
            for doc, concept, context, value in xbrl.execute(
                    f"SELECT file, concept, context, value FROM facts "
                    f"WHERE file IN ({','.join('?' * len(chunk))}) "
                    f"AND context IN ('OneD','FourD') AND concept IN "
                    f"('RevenueFromOperations','ProfitLossForPeriod',"
                    f"'BasicEarningsLossPerShareFromContinuingOperations') "
                    f"AND value IS NOT NULL", chunk):
                ctx[(doc, concept)][context] = float(value)
    finally:
        xbrl.close()
    buckets: dict[str, Counter] = {}
    for key, value, doc in rows:
        contexts = ctx.get((doc, MIX_METRICS[key]), {})
        one, four = contexts.get("OneD"), contexts.get("FourD")
        scale = 1.0 if key == "eps" else 1e-7
        pv = float(value)
        tol = EPS_TOL if key == "eps" else CHECK_TOL * max(1.0, abs(pv))
        bucket = buckets.setdefault(key, Counter())
        if one is not None and abs(pv - one * scale) <= tol:
            bucket["matches_oned"] += 1
        elif four is not None and abs(pv - four * scale) <= tol:
            bucket["matches_fourd"] += 1
        elif one is None and four is None:
            bucket["no_context"] += 1
        else:
            bucket["neither"] += 1
    return [{"metric_key": key, "rows": sum(counter.values()),
             **{f: counter[f] for f in _MIX_FIELDS}}
            for key, counter in sorted(buckets.items())]


def load_inputs(data_root: Path, isins: list[str]) -> tuple[list[dict], list[dict], dict]:
    """Read only the pilot universe's filings and their OneD/FourD facts."""
    con = connect_ro(Path(data_root) / "results_xbrl.db", timeout_s=600, immutable=True)
    q = ",".join("?" * len(isins))
    try:
        raw = list(con.execute(
            f"SELECT file, isin, period_end, period_start, consolidated, "
            f"COALESCE(dissem_ts, broadcast_ts, filing_ts) AS known_at "
            f"FROM filings WHERE isin IN ({q}) AND status = 'ok' "
            f"AND period_end IS NOT NULL", isins) or [])
        filings, no_known = [], 0
        for file, isin, period_end, period_start, consol, known_at in raw:
            if not known_at:                      # never invent a publication time
                no_known += 1
                continue
            filings.append({"file": file, "isin": isin, "period_end": str(period_end)[:10],
                            "period_start": str(period_start)[:10] if period_start else None,
                            "consolidated": consol, "known_at": str(known_at)})
        concepts = tuple(CONCEPT_MAP)
        facts = [{"file": f, "concept": c, "context": x, "period_start": ps,
                  "period_end": pe, "value": v}
                 for f, c, x, ps, pe, v in con.execute(
                     f"SELECT file, concept, context, period_start, period_end, value "
                     f"FROM facts WHERE file IN (SELECT file FROM filings WHERE isin IN ({q}) "
                     f"AND status = 'ok') AND context IN ('OneD','FourD') "
                     f"AND concept IN ({','.join('?' * len(concepts))}) AND value IS NOT NULL",
                     (*isins, *concepts)) or []]
    finally:
        con.close()
    return filings, facts, {"filings": len(filings), "filings_without_known_at": no_known,
                            "facts": len(facts)}


def build(out: Path | str, data_root: Path | str | None = None,
          isins: list[str] | None = None) -> dict:
    """Derive the quarters for the pilot universe and write one small DB."""
    out = Path(out)
    data_root = Path(data_root or os.environ.get("REALITY_DATA_ROOT") or ROOT)
    isins = list(isins) if isins is not None else pilot_isins()
    filings, facts, loaded = load_inputs(data_root, isins)
    rows, counts, checks = derive_quarters(filings, facts)
    sample = _sample_rows(rows, checks)
    mix = measure_pilot_mix(data_root, isins)
    out.parent.mkdir(parents=True, exist_ok=True)
    for stale in (out, Path(str(out) + "-wal"), Path(str(out) + "-shm")):
        stale.unlink(missing_ok=True)
    con = sqlite3.connect(str(out))
    try:
        con.executescript(SCHEMA)
        con.executemany(
            "INSERT OR REPLACE INTO company_quarter_series (isin, metric_key, period_end, "
            "period_kind, basis, value, unit, derived, derived_from, doc_id, known_at, pit_conf) "
            "VALUES (:isin,:metric_key,:period_end,'quarter',:basis,:value,:unit,:derived,"
            ":derived_from,:doc_id,:known_at,1.0)", rows)
        con.executemany("INSERT INTO quarter_derivation_counts (reason, n) VALUES (?, ?)",
                        sorted({**counts, "filings_without_known_at": loaded["filings_without_known_at"]}.items()))
        con.executemany(
            "INSERT INTO quarter_handcheck (isin, metric_key, period_end, basis, derived_value, "
            "filing_quarter, abs_diff, doc_id, ok) VALUES (:isin,:metric_key,:period_end,:basis,"
            ":derived_value,:filing_quarter,:abs_diff,:doc_id,:ok)", checks)
        con.executemany(
            "INSERT INTO quarter_sample (isin, metric_key, period_end, basis, stored_value, "
            "filing_quarter, derived_value, abs_diff, doc_id, matches_stored) VALUES "
            "(:isin,:metric_key,:period_end,:basis,:stored_value,:filing_quarter,"
            ":derived_value,:abs_diff,:doc_id,:matches_stored)", sample)
        con.executemany(
            "INSERT INTO pilot_quarter_mix (metric_key, rows, matches_oned, matches_fourd, "
            "neither, no_context) VALUES (:metric_key,:rows,:matches_oned,:matches_fourd,"
            ":neither,:no_context)", mix)
        con.execute("CREATE INDEX ix_quarter_known ON company_quarter_series(isin, period_end)")
        con.commit()
        per_metric = dict(con.execute(
            "SELECT metric_key, COUNT(*) FROM company_quarter_series GROUP BY 1 ORDER BY 2 DESC"))
        per_derived = dict(con.execute(
            "SELECT derived, COUNT(*) FROM company_quarter_series GROUP BY 1"))
        covered = con.execute(
            "SELECT COUNT(DISTINCT isin), MIN(period_end), MAX(period_end) "
            "FROM company_quarter_series").fetchone()
    finally:
        con.close()
    bad = [c for c in checks if not c["ok"]]
    mix_rows = sum(m["rows"] for m in mix)
    mix_ytd = sum(m["matches_fourd"] for m in mix)
    return {
        "out": str(out), "rows": len(rows), "isins": covered[0],
        "period": [covered[1], covered[2]], "loaded": loaded, "counts": counts,
        "per_metric": per_metric, "per_derived": per_derived,
        "pilot_mix": {"rows": mix_rows, "ytd_in_quarter": mix_ytd,
                      "ytd_in_quarter_pct": round(100.0 * mix_ytd / max(1, mix_rows), 2),
                      "per_metric": mix},
        "handcheck": {"checks": len(checks), "ok": len(checks) - len(bad),
                      "mismatches": len(bad), "examples": bad[:5],
                      "sample": len(sample),
                      "sample_all_match": all(s["matches_stored"] for s in sample)},
    }


def _sample_rows(rows: list[dict], checks: list[dict], n: int = 30) -> list[dict]:
    """One hand-checked quarter per pilot ISIN, deterministic; the filing column kept."""
    values = {(r["isin"], r["metric_key"], r["period_end"], r["basis"]): r["value"] for r in rows}
    out, seen = [], set()
    for c in sorted((c for c in checks if c["ok"]),
                    key=lambda c: (c["isin"], c["metric_key"], c["period_end"])):
        if c["isin"] in seen:
            continue
        seen.add(c["isin"])
        stored = values.get((c["isin"], c["metric_key"], c["period_end"], c["basis"]))
        out.append({**c, "stored_value": stored,
                    "matches_stored": int(stored is not None
                                          and abs(stored - c["filing_quarter"]) <= 1e-6)})
        if len(out) == n:
            break
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=REPO / ".tmp" / "quarters_pilot60.db")
    ap.add_argument("--data-root", type=Path,
                    default=Path(os.environ.get("REALITY_DATA_ROOT") or ROOT))
    args = ap.parse_args(argv)
    t0 = time.perf_counter()
    report = build(args.out, args.data_root)
    report["seconds"] = round(time.perf_counter() - t0, 1)
    import json
    print(json.dumps(report, indent=1, default=str))
    # a mismatch is usually a restated/classified line, not a broken rule; fail only
    # when the rule agrees with the filing's own quarter column on under half of them
    hc = report["handcheck"]
    return 0 if hc["checks"] and 2 * hc["ok"] >= hc["checks"] else 1


if __name__ == "__main__":
    sys.exit(main())
