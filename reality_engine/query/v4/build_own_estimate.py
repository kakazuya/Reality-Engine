"""v4 WP2b — our own estimates and the measured in-line band (§A.8, §H.7).

An ``own_estimate`` is a first-class measured object: the company's own quarterly
series, a declared trend rule, the exact input rows, and the moment we could first
have computed it.  No paid consensus feed: where the series exists, the estimate
exists.

    python -m reality_engine.query.v4.build_own_estimate --out .tmp/v4.db
    python -m reality_engine.query.v4.build_own_estimate --replay-check .tmp/v4.db

The rule (declared, deterministic, no fitted constant hidden in a notebook):

    estimate = value(same quarter last year) * (1 + DAMP * median(last <=4 YoY growths))

``DAMP = 0.75`` is the damped-trend factor; the rule's own out-of-sample error is
measured on the same walk-forward and written to ``own_estimate_band`` as
``p75_abs_pct``, so a bad rule shows up as a wide band instead of a quiet miss.
Where fewer than three usable YoY growths exist the estimate is the seasonal-naive
level (growth 0) and says so in ``inputs_json``.

PIT: an estimate for a target quarter is built only from rows whose ``known_at`` is
strictly before the target's own filing time, and ``known_at = as_of`` = the latest
input publication.  :func:`replay_check` proves no estimate reads anything later
than its ``as_of``; a re-estimate never rewrites a row (PK includes ``as_of``).

WP2c (31 Oct 2026): the input series is now the true single-quarter series from
``build_quarters.py`` (OneD reported, or FourD minus the prior-quarter YTD), not the
pilot store's date-inferred quarter rows that mixed annual/YTD values into the
quarter column.  Both series are walked forward on the same rule so the report can
print the band width and the scale-mixed share **before and after** the fix; the
stored ``own_estimate``/``own_estimate_band`` are the after-fix ones.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
import sqlite3
from datetime import date
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.query.v4.build_vocab import pilot_isins

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
QUARTERS_DB = Path(".tmp") / "quarters_pilot60.db"

# Beat/miss atoms the estimate layer serves (§A.8). The series keys are the
# pilot store's own metric_key words.
ATOMS: dict[str, str] = {"revenue": "fin.revenue", "pat": "fin.pat", "eps": "fin.eps"}
BEAT_MISS_ATOMS = ("fin.revenue", "fin.pat")
DAMP = 0.75
MIN_GROWTHS = 3
BAND_PCT_FLOOR = 0.5
BAND_MIN_OBS = 8
RULE = ("seasonal_naive x (1 + DAMP * median(last<=4 YoY growths)); DAMP=0.75; "
        "growth pairs need a positive base, else the seasonal-naive level is used")

SCHEMA = """
CREATE TABLE IF NOT EXISTS own_estimate(
  isin TEXT NOT NULL,
  est_atom TEXT NOT NULL,
  period_end TEXT NOT NULL,
  value REAL,
  unit TEXT,
  method TEXT NOT NULL,
  inputs_json TEXT NOT NULL,
  n_obs INTEGER,
  confidence REAL,
  known_at TEXT NOT NULL,
  as_of TEXT NOT NULL,
  basis TEXT,
  realised REAL,
  realised_known_at TEXT,
  abs_pct_err REAL,
  band_pct REAL,
  reading TEXT,
  series_source TEXT,
  PRIMARY KEY (isin, est_atom, period_end, as_of));
CREATE INDEX IF NOT EXISTS ix_own_est_atom ON own_estimate(est_atom, period_end);
CREATE TABLE IF NOT EXISTS own_estimate_band(
  est_atom TEXT NOT NULL,
  mcap_bucket TEXT NOT NULL,
  n_obs INTEGER NOT NULL,
  mape REAL NOT NULL,
  p75_abs_pct REAL NOT NULL,
  band_pct REAL NOT NULL,
  fallback TEXT,
  measured_from TEXT NOT NULL,
  as_of TEXT NOT NULL,
  PRIMARY KEY (est_atom, mcap_bucket, as_of));
CREATE TABLE IF NOT EXISTS own_estimate_band_prev(
  est_atom TEXT NOT NULL,
  mcap_bucket TEXT NOT NULL,
  n_obs INTEGER NOT NULL,
  mape REAL NOT NULL,
  p75_abs_pct REAL NOT NULL,
  band_pct REAL NOT NULL,
  fallback TEXT,
  measured_from TEXT NOT NULL,
  as_of TEXT NOT NULL,
  PRIMARY KEY (est_atom, mcap_bucket, as_of));
"""


def quarters(year_ago: str) -> str:
    """The same month/day one year earlier: quarter ends are date-stable."""
    y, m, d = (int(x) for x in year_ago.split("-"))
    return f"{y - 1:04d}-{m:02d}-{d:02d}"


def prev_quarter(period: str) -> str:
    """The quarter end three months earlier (Mar->Dec 31, Jun->Mar 31, ...)."""
    import calendar
    y, m = int(period[:4]), int(period[5:7])
    m -= 3
    if m <= 0:
        m += 12
        y -= 1
    return f"{y:04d}-{m:02d}-{calendar.monthrange(y, m)[1]:02d}"


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    if len(s) == 1:
        return s[0]
    k = (len(s) - 1) * p / 100.0
    lo, hi = math.floor(k), math.ceil(k)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def trend_estimate(history: list[dict], target_period: str) -> tuple[float | None, dict]:
    """Forecast ``target_period`` from ``history`` (rows with period_end < target).

    ``history`` rows are ``{period_end, value, known_at, doc_id}``.  Returns the
    estimate and the arithmetic that produced it, for ``inputs_json``.
    """
    by_period = {}
    for r in history:
        if r["period_end"] not in by_period:      # first publication wins
            by_period[r["period_end"]] = r
    base_period = quarters(target_period)
    base = by_period.get(base_period)
    if base is None or base["value"] is None:
        return None, {"rule": RULE, "reason": "no year-ago quarter in the series",
                      "rows": _rows(history)}
    growths: list[float] = []
    cur = base_period
    for _ in range(4):
        a, b = by_period.get(cur), by_period.get(quarters(cur))
        if a and b and a["value"] is not None and b["value"] is not None \
                and a["value"] > 0 and b["value"] > 0:
            growths.append(a["value"] / b["value"] - 1.0)
        cur = prev_quarter(cur)
    detail = {"rule": RULE, "base_quarter": base_period, "base_value": base["value"],
              "growths": [round(g, 6) for g in growths], "rows": _rows(history)}
    if len(growths) >= MIN_GROWTHS:
        g = statistics.median(growths)
        detail["median_yoy"] = round(g, 6)
        detail["applied_yoy"] = round(DAMP * g, 6)
        return base["value"] * (1.0 + DAMP * g), detail
    detail["median_yoy"] = None
    detail["applied_yoy"] = 0.0
    detail["fell_back"] = "seasonal_naive (fewer than 3 usable YoY growths)"
    return base["value"], detail


def _rows(history: list[dict]) -> list[list]:
    return [[r["period_end"], r["value"], r["known_at"], r.get("doc_id")] for r in history]


def _series_from_rows(rows) -> dict[tuple[str, str], list[dict]]:
    """(isin, atom) -> quarter rows, first publication per period, consolidated preferred."""
    by: dict[tuple[str, str], dict[str, dict[str, dict]]] = {}
    for isin, key, period_end, basis, value, known_at, doc_id, unit in rows:
        atom = ATOMS[key]
        by.setdefault((isin, atom), {}).setdefault(basis or "unknown", {}).setdefault(
            period_end, {"period_end": period_end, "value": float(value),
                         "known_at": known_at, "doc_id": doc_id, "unit": unit})
    out: dict[tuple[str, str], list[dict]] = {}
    for k, bases in by.items():
        basis = "consolidated" if len(bases.get("consolidated", {})) >= BAND_MIN_OBS \
            or "standalone" not in bases else "standalone"
        series = sorted(bases.get(basis, {}).values(), key=lambda r: r["period_end"])
        for r in series:
            r["basis"] = basis
        if series:
            out[k] = series
    return out


def load_series(data_root: Path, isins: list[str]) -> dict[tuple[str, str], list[dict]]:
    """Raw pilot series (before the quarter fix): the walk-forward "before" numbers."""
    q = ",".join("?" * len(isins))
    keys = tuple(ATOMS)
    con = connect_ro(data_root / "pilot" / "pilot60" / "facts_pilot.db", timeout_s=180,
                     immutable=True)
    try:
        rows = list(con.execute(
            f"SELECT isin, metric_key, period_end, basis, value, known_at, doc_id, unit "
            f"FROM company_metric_series WHERE isin IN ({q}) "
            f"AND metric_key IN ({','.join('?' * len(keys))}) AND period_kind='quarter' "
            f"AND value IS NOT NULL AND known_at IS NOT NULL "
            f"ORDER BY isin, metric_key, period_end, known_at", (*isins, *keys)) or [])
    finally:
        con.close()
    return _series_from_rows(rows)


def load_series_clean(quarters_db: Path, isins: list[str]) -> dict[tuple[str, str], list[dict]]:
    """True single-quarter series from build_quarters (OneD / YTD difference)."""
    q = ",".join("?" * len(isins))
    keys = tuple(ATOMS)
    con = connect_ro(Path(quarters_db), timeout_s=180, immutable=True)
    try:
        rows = list(con.execute(
            f"SELECT isin, metric_key, period_end, basis, value, known_at, doc_id, unit "
            f"FROM company_quarter_series WHERE isin IN ({q}) "
            f"AND metric_key IN ({','.join('?' * len(keys))}) "
            f"AND value IS NOT NULL AND known_at IS NOT NULL "
            f"ORDER BY isin, metric_key, period_end, known_at", (*isins, *keys)) or [])
    finally:
        con.close()
    return _series_from_rows(rows)


def load_buckets(data_root: Path, isins: list[str]) -> dict[str, str]:
    q = ",".join("?" * len(isins))
    con = connect_ro(data_root / "pilot" / "pilot60" / "market_state_pilot.db",
                     timeout_s=180, immutable=True)
    try:
        rows = list(con.execute(
            f"SELECT isin, date, mcap_bucket FROM company_state_daily "
            f"WHERE isin IN ({q}) ORDER BY isin, date", isins) or [])
    finally:
        con.close()
    out: dict[str, str] = {}
    for isin, _date, bucket in rows:              # last session per ISIN wins
        out[isin] = bucket or "unknown"
    return out


def walk_forward(series: list[dict], isin: str, atom: str) -> list[dict]:
    """One estimate per reported quarter, built only from what was known before it."""
    out = []
    for i, target in enumerate(series):
        if i < 8:                                  # the rule needs the last 8 quarters
            continue
        hist = [r for r in series[:i] if r["known_at"] < target["known_at"]]
        if not hist:
            continue
        as_of = max(r["known_at"] for r in hist)
        value, detail = trend_estimate(hist, target["period_end"])
        if value is None:
            continue
        realised = target["value"]
        err = (abs(value - realised) / abs(realised)) if realised else None
        out.append({
            "isin": isin, "est_atom": atom, "period_end": target["period_end"],
            "value": round(value, 6),
            "unit": target.get("unit"),
            "method": "trend",
            "inputs_json": json.dumps(detail, sort_keys=True),
            "n_obs": len(detail["rows"]),
            "confidence": None,
            "known_at": as_of, "as_of": as_of,
            "basis": target.get("basis"),
            "realised": realised, "realised_known_at": target["known_at"],
            "abs_pct_err": (round(err, 6) if err is not None else None),
            "band_pct": None, "reading": None,
        })
    return out


def bands(errors: dict[tuple[str, str], list[float]], as_of: str,
          source: str = "pilot60.company_metric_series") -> dict[tuple[str, str], dict]:
    """(atom, bucket) -> the measured band row, with the declared fallback ladder."""
    pooled_atom: dict[str, list[float]] = {}
    pooled_all: list[float] = []
    for (atom, _bucket), errs in errors.items():
        pooled_atom.setdefault(atom, []).extend(errs)
        pooled_all.extend(errs)
    out: dict[tuple[str, str], dict] = {}
    for (atom, bucket), errs in errors.items():
        fallback = None
        src, n_obs = errs, len(errs)
        if n_obs < BAND_MIN_OBS:
            fallback = "pooled_atom"
            src = pooled_atom.get(atom, [])
            if not src:
                fallback = "pooled_all"
                src = pooled_all
        p75 = percentile(src, 75) * 100.0
        out[(atom, bucket)] = {
            "est_atom": atom, "mcap_bucket": bucket,
            "n_obs": n_obs,
            "mape": round(percentile(src, 50) * 100.0, 4),
            "p75_abs_pct": round(p75, 4),
            "band_pct": round(max(p75, BAND_PCT_FLOOR), 4),
            "fallback": fallback,
            "measured_from": ("walk-forward of the trend rule on the true single-quarter "
                              f"series ({source}, {n_obs} scored in-bucket, "
                              f"{len(src)} scored in the band src)"),
            "as_of": as_of,
        }
    return out


def _walk_series(series: dict, buckets: dict[str, str]) -> tuple[list[dict], dict]:
    """Run the walk-forward rule over one (isin, atom) series map."""
    estimates: list[dict] = []
    errors: dict[tuple[str, str], list[float]] = {}
    for (isin, atom), rows in sorted(series.items()):
        bucket = buckets.get(isin, "unknown")
        for e in walk_forward(rows, isin, atom):
            estimates.append(e)
            if e["abs_pct_err"] is not None:
                errors.setdefault((atom, bucket), []).append(e["abs_pct_err"])
    return estimates, errors


def _large_miss(estimates: list[dict]) -> int:
    """Pairs whose realised/estimate ratio is beyond 3x: a large forecast miss.

    Not a scale-mix test on a clean series (a microcap PAT can legitimately move 3x),
    so it is reported as a forecast-error count; the period mix is the explicit
    ``period_mix`` evidence from ``build_quarters``.
    """
    n = 0
    for e in estimates:
        ratio = (e["realised"] / e["value"]) if (e["value"] and e["realised"]) else None
        if ratio is not None and (ratio > 3.0 or ratio < 1.0 / 3.0):
            n += 1
    return n


def load_period_mix(quarters_db: Path) -> dict:
    """The defect count before the fix and the derivation mix after it."""
    con = connect_ro(Path(quarters_db), timeout_s=60, immutable=True)
    try:
        rows = list(con.execute(
            "SELECT metric_key, rows, matches_oned, matches_fourd, neither, no_context "
            "FROM pilot_quarter_mix") or [])
        after = dict(con.execute(
            "SELECT derived, COUNT(*) FROM company_quarter_series "
            "WHERE metric_key IN ('revenue', 'pat', 'eps') GROUP BY 1") or [])
    finally:
        con.close()
    total = sum(r[1] for r in rows)
    ytd = sum(r[3] for r in rows)
    return {
        "before": {"pilot_quarter_rows": total, "ytd_in_quarter": ytd,
                   "ytd_in_quarter_pct": round(100.0 * ytd / max(1, total), 2),
                   "per_metric": [{"metric_key": r[0], "rows": r[1], "matches_oned": r[2],
                                   "matches_fourd": r[3], "neither": r[4],
                                   "no_context": r[5]} for r in rows]},
        "after": {"reported_oned": after.get("reported", 0),
                  "ytd_difference": after.get("ytd_difference", 0),
                  "ytd_in_quarter": 0},
    }


def build(out: Path, data_root: Path, *, isins: list[str] | None = None,
          quarters_db: Path | str | None = None) -> dict:
    isins = list(isins) if isins is not None else pilot_isins()
    quarters_db = Path(quarters_db) if quarters_db else None
    raw = load_series(data_root, isins)
    clean = load_series_clean(quarters_db, isins) if quarters_db and quarters_db.is_file() else raw
    source = ("quarters_pilot60.company_quarter_series" if clean is not raw
              else "pilot60.company_metric_series")
    buckets = load_buckets(data_root, isins)
    estimates, errors = _walk_series(clean, buckets)
    raw_estimates, raw_errors = _walk_series(raw, buckets)
    as_of = date.today().isoformat()
    band_rows = bands(errors, as_of, source)
    band_rows_prev = bands(raw_errors, as_of, "pilot60.company_metric_series (raw quarters)")
    for e in estimates:
        e["series_source"] = source
        b = band_rows.get((e["est_atom"], buckets.get(e["isin"], "unknown")))
        if b and e["abs_pct_err"] is not None:
            e["band_pct"] = b["band_pct"]
            diff = e["value"] - e["realised"]
            if abs(diff) <= abs(e["realised"]) * b["band_pct"] / 100.0:
                e["reading"] = "in-line"
            else:
                e["reading"] = "beat" if diff > 0 else "miss"
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    try:
        con.executescript(SCHEMA)
        con.execute("DELETE FROM own_estimate")
        con.execute("DELETE FROM own_estimate_band")
        con.execute("DELETE FROM own_estimate_band_prev")
        con.executemany(
            "INSERT OR IGNORE INTO own_estimate (isin, est_atom, period_end, value, unit, "
            "method, inputs_json, n_obs, confidence, known_at, as_of, basis, realised, "
            "realised_known_at, abs_pct_err, band_pct, reading, series_source) VALUES "
            "(:isin,:est_atom,:period_end,:value,:unit,:method,:inputs_json,:n_obs,"
            ":confidence,:known_at,:as_of,:basis,:realised,:realised_known_at,"
            ":abs_pct_err,:band_pct,:reading,:series_source)", estimates)
        insert_band = (
            "INSERT OR REPLACE INTO own_estimate_band%s (est_atom, mcap_bucket, n_obs, mape, "
            "p75_abs_pct, band_pct, fallback, measured_from, as_of) VALUES "
            "(:est_atom,:mcap_bucket,:n_obs,:mape,:p75_abs_pct,:band_pct,:fallback,"
            ":measured_from,:as_of)")
        con.executemany(insert_band % "", list(band_rows.values()))
        con.executemany(insert_band % "_prev", list(band_rows_prev.values()))
        con.commit()
        readings = dict(con.execute(
            "SELECT reading, count(*) FROM own_estimate WHERE reading IS NOT NULL "
            "GROUP BY 1").fetchall())
        per_atom = dict(con.execute(
            "SELECT est_atom, count(*) FROM own_estimate GROUP BY 1 ORDER BY 2 DESC").fetchall())
        per_unit = dict(con.execute(
            "SELECT unit, count(*) FROM own_estimate GROUP BY 1").fetchall())
        names = [r[1] for r in con.execute("PRAGMA table_info(own_estimate)")]
    finally:
        con.close()
    compare = []
    for key in sorted(set(band_rows) | set(band_rows_prev)):
        after, before = band_rows.get(key, {}), band_rows_prev.get(key, {})
        compare.append({
            "est_atom": key[0], "mcap_bucket": key[1],
            "n_obs_before": before.get("n_obs"), "n_obs_after": after.get("n_obs"),
            "p75_before": before.get("p75_abs_pct"), "p75_after": after.get("p75_abs_pct"),
            "band_before": before.get("band_pct"), "band_after": after.get("band_pct"),
        })
    after_bands = sorted(v["band_pct"] for v in band_rows.values())
    before_bands = sorted(v["band_pct"] for v in band_rows_prev.values())

    def _median(values):
        return round(percentile(values, 50), 4) if values else None

    return {
        "out": str(out),
        "quarters_db": str(quarters_db) if quarters_db else None,
        "series_source": source,
        "estimates": len(estimates),
        "estimates_before": len(raw_estimates),
        "per_atom": per_atom,
        "per_unit": per_unit,
        "readings": readings,
        "bands": [band_rows[k] for k in sorted(band_rows)],
        "band_rows": len(band_rows),
        "columns": names,
        "atoms_with_series": len(clean),
        "series_rows": {"after": sum(len(v) for v in clean.values()),
                        "before": sum(len(v) for v in raw.values())},
        "band_width_pct": {
            "before_median": _median(before_bands), "after_median": _median(after_bands),
            "before_max": before_bands[-1] if before_bands else None,
            "after_max": after_bands[-1] if after_bands else None,
            "per_atom_bucket": compare,
        },
        # Forecast-error count (not a scale test): see _large_miss.  The period mix
        # itself is the explicit period_mix evidence below.
        "large_miss_pairs": _large_miss(estimates),
        "large_miss_pct": round(100.0 * _large_miss(estimates) / max(1, len(estimates)), 2),
        "large_miss_before_pairs": _large_miss(raw_estimates),
        "large_miss_before_pct": round(
            100.0 * _large_miss(raw_estimates) / max(1, len(raw_estimates)), 2),
        "period_mix": (load_period_mix(quarters_db)
                       if quarters_db and quarters_db.is_file() else None),
        "replay": replay_check(out),
    }


def replay_check(db: Path) -> dict:
    """Prove the PIT rule: no estimate reads an input with known_at > its as_of."""
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        rows = list(con.execute(
            "SELECT isin, est_atom, period_end, as_of, known_at, inputs_json "
            "FROM own_estimate"))
    finally:
        con.close()
    bad, checked, empty = [], 0, 0
    for isin, atom, period_end, as_of, known_at, inputs_json in rows:
        detail = json.loads(inputs_json or "{}")
        inputs = detail.get("rows") or []
        if not inputs:
            empty += 1
            continue
        later = [r for r in inputs if str(r[2]) > str(as_of)]
        checked += 1
        if later or str(known_at) > str(as_of):
            bad.append({"isin": isin, "est_atom": atom, "period_end": period_end,
                        "as_of": as_of, "later_inputs": later[:3]})
    return {"checked": checked, "empty_inputs": empty, "violations": len(bad),
            "examples": bad[:5], "ok": not bad}


def estimate_at(db: Path, isin: str, est_atom: str, period_end: str,
                as_of: str) -> dict | None:
    """The estimate readable at ``as_of`` (the query-side replay path)."""
    con = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    try:
        row = con.execute(
            "SELECT value, unit, method, inputs_json, n_obs, known_at, as_of, basis, "
            "realised, band_pct, reading FROM own_estimate "
            "WHERE isin=? AND est_atom=? AND period_end=? AND known_at<=? "
            "ORDER BY known_at DESC LIMIT 1", (isin, est_atom, period_end, as_of)).fetchone()
    finally:
        con.close()
    if not row:
        return None
    detail = json.loads(row[3] or "{}")
    later = [r for r in (detail.get("rows") or []) if str(r[2]) > str(as_of)]
    return {"value": row[0], "unit": row[1], "method": row[2], "inputs": detail,
            "n_obs": row[4], "known_at": row[5], "as_of": row[6], "basis": row[7],
            "realised": row[8], "band_pct": row[9], "reading": row[10],
            "reads_future": bool(later)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--out", type=Path, default=Path(".tmp/v4.db"))
    ap.add_argument("--data-root", type=Path,
                    default=Path(os.environ.get("REALITY_DATA_ROOT", ROOT / "reality_engine" / "data")))
    ap.add_argument("--replay-check", type=Path, default=None,
                    help="run only the PIT replay check against this database")
    ap.add_argument("--quarters", type=Path, default=QUARTERS_DB,
                    help="true single-quarter store (build_quarters.py)")
    args = ap.parse_args(argv)
    if args.replay_check:
        result = replay_check(args.replay_check)
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] else 1
    report = build(args.out, args.data_root, quarters_db=args.quarters)
    print(json.dumps(report, indent=1))
    return 0 if report["replay"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
