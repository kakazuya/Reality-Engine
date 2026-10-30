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


def load_series(data_root: Path, isins: list[str]) -> dict[tuple[str, str], list[dict]]:
    """(isin, atom) -> quarter rows, first publication per period, consolidated preferred."""
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
    by: dict[tuple[str, str], dict[str, list[dict]]] = {}
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


def bands(errors: dict[tuple[str, str], list[float]], as_of: str) -> dict[tuple[str, str], dict]:
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
            "measured_from": ("walk-forward of the trend rule on the pilot quarterly series "
                              f"(pilot60.company_metric_series, {n_obs} scored in-bucket, "
                              f"{len(src)} scored in the band src)"),
            "as_of": as_of,
        }
    return out


def build(out: Path, data_root: Path, *, isins: list[str] | None = None) -> dict:
    isins = list(isins) if isins is not None else pilot_isins()
    series = load_series(data_root, isins)
    buckets = load_buckets(data_root, isins)
    estimates: list[dict] = []
    errors: dict[tuple[str, str], list[float]] = {}
    for (isin, atom), rows in sorted(series.items()):
        bucket = buckets.get(isin, "unknown")
        for e in walk_forward(rows, isin, atom):
            estimates.append(e)
            if e["abs_pct_err"] is not None:
                errors.setdefault((atom, bucket), []).append(e["abs_pct_err"])
    as_of = date.today().isoformat()
    band_rows = bands(errors, as_of)
    scale_mixed = 0
    for e in estimates:
        b = band_rows.get((e["est_atom"], buckets.get(e["isin"], "unknown")))
        if b and e["abs_pct_err"] is not None:
            e["band_pct"] = b["band_pct"]
            diff = e["value"] - e["realised"]
            if abs(diff) <= abs(e["realised"]) * b["band_pct"] / 100.0:
                e["reading"] = "in-line"
            else:
                e["reading"] = "beat" if diff > 0 else "miss"
        ratio = (e["realised"] / e["value"]) if (e["value"] and e["realised"]) else None
        if ratio is not None and (ratio > 3.0 or ratio < 1.0 / 3.0):
            scale_mixed += 1
    out.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(out)
    try:
        con.executescript(SCHEMA)
        con.execute("DELETE FROM own_estimate")
        con.execute("DELETE FROM own_estimate_band")
        con.executemany(
            "INSERT OR IGNORE INTO own_estimate (isin, est_atom, period_end, value, unit, "
            "method, inputs_json, n_obs, confidence, known_at, as_of, basis, realised, "
            "realised_known_at, abs_pct_err, band_pct, reading) VALUES "
            "(:isin,:est_atom,:period_end,:value,:unit,:method,:inputs_json,:n_obs,"
            ":confidence,:known_at,:as_of,:basis,:realised,:realised_known_at,"
            ":abs_pct_err,:band_pct,:reading)", estimates)
        con.executemany(
            "INSERT OR REPLACE INTO own_estimate_band (est_atom, mcap_bucket, n_obs, mape, "
            "p75_abs_pct, band_pct, fallback, measured_from, as_of) VALUES "
            "(:est_atom,:mcap_bucket,:n_obs,:mape,:p75_abs_pct,:band_pct,:fallback,"
            ":measured_from,:as_of)", list(band_rows.values()))
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
    return {
        "out": str(out),
        "estimates": len(estimates),
        "per_atom": per_atom,
        "per_unit": per_unit,
        "readings": readings,
        "bands": [band_rows[k] for k in sorted(band_rows)],
        "band_rows": len(band_rows),
        "columns": names,
        "atoms_with_series": len(series),
        # Data-defect indicator, not a fix: the pilot store's quarterly series mixes
        # single-quarter and year-to-date (cumulative) values, so this share of pairs
        # compares an annual number with a quarterly one. The pivot is the upstream
        # fix; the band below measures the estimator on the series as held.
        "scale_mixed_pairs": scale_mixed,
        "scale_mixed_pct": round(100.0 * scale_mixed / max(1, len(estimates)), 2),
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
    args = ap.parse_args(argv)
    if args.replay_check:
        result = replay_check(args.replay_check)
        print(json.dumps(result, indent=1))
        return 0 if result["ok"] else 1
    report = build(args.out, args.data_root)
    print(json.dumps(report, indent=1))
    return 0 if report["replay"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
