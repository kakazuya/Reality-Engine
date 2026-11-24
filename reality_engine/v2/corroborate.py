"""T-242: corroborate earnings-call numbers and guidance against filings we hold (deterministic, no model).

Shivam's ruling (24 Nov 2026, in ``docs/DEVELOPER_GUIDE.md``): a call NUMBER or GUIDANCE row never earns
``verified`` from the page check alone; it earns it when a filing we hold states the same thing.
``observations.apply_transcript_number_gate`` writes the ``transcript_number:`` reason.  This module is the other
half: it copies the observation DB (never edits the input), matches each transcript call row against the company's
store, and rewrites the reason to ``corroborated: <table>.<metric> <period> <basis> = <value> (<pre|post>_call)``.

Measure map (``NUMBER_MAP``): call measure -> [(store table, metric/line_item, value_kind)], order = citation
preference (XBRL first, so the same figure in ``fin_quarter_xbrl`` and ``ratio_panel`` cites the XBRL row).  Kinds:
``money`` (1% relative), ``pct`` (0.05 absolute) and ``num`` (1% relative; capacity/volume, unit family must
match).  Only measures with a filed counterpart are mapped; the rest are counted as ``no_counterpart``:

- ``revenue_from_operations``, ``pat`` -> ``fin_quarter_xbrl`` then ``ratio_panel``;
- ``profit_before_tax`` -> ``fin_quarter_xbrl.pbt``; ``total_income`` -> ``fin_quarter_xbrl.total_income``;
- ``ebitda`` -> ``ratio_panel.ebitda`` (there is no XBRL EBITDA line);
- ``ebitda_margin``, ``pat_margin``, ``revenue_growth_yoy``, ``pat_growth_yoy`` -> the ``*_pct`` ``ratio_panel``
  metrics;
- ``order.book``, ``order.intake``, ``capex`` -> ``kpi_series`` (``order_book``, ``order_intake``, ``capex``);
- ``capacity.total``, ``capacity.utilisation``, ``volume.production``, ``volume.sales`` -> ``kpi_series``
  (``capacity``, ``utilisation``, ``production_kt``, ``shipments_kt``), matched only when the unit families agree;
- everything else (``revenue.mix``, ``mix.share``, ``ebitda_growth_yoy``, ...) has no filed counterpart and is
  left alone.

Number rule: same symbol, same normalised period (``Q2 FY27`` -> ``Q2FY27``; an empty period never matches) and a
compatible basis (a stated basis is required; an empty one takes consolidated, then standalone, and the citation
names the one that matched).  Values are compared as ``value * scale`` on both sides, so a crore call number meets
an XBRL rupee.  A row with ``value_high`` matches any filed value inside the range.  A filed row is ``pre_call``
when its ``known_at`` is at most one day after the call row's ``known_at``, otherwise ``post_call`` (still a
corroboration; the citation says the filing came later).  Currency never crosses (a USD filing never corroborates
a rupee number).

Guidance rule (``GUIDANCE_MAP``): same symbol and target period in the store's ``guidance`` table, ``said_on``
within 120 days of the call, and low/high within 1% (0.05 absolute for percentages).  Sparse store guidance just
leaves rows unmatched; no source is invented.

CLI: ``python -m reality_engine.v2.corroborate --obs <db> --stores-root <dir> --out <db> [--limit-symbols N]``
prints a JSON summary.  Inputs are opened ``mode=ro``; only ``--out`` (a copy) is written.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import re
import sqlite3
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reality_engine.db.readonly import connect_ro

SAMPLE_SEED = 2424
GUIDANCE_WINDOW_DAYS = 120
REASON_PREFIX = "corroborated: "
TRANSCRIPT_NUMBER_PREFIX = "transcript_number:"

# call measure -> [(store table, metric/line_item, value_kind)]; order = citation preference (XBRL first).
NUMBER_MAP: dict[str, list[tuple[str, str, str]]] = {
    "revenue_from_operations": [("fin_quarter_xbrl", "revenue_from_operations", "money"),
                                ("ratio_panel", "revenue_from_operations", "money")],
    "pat": [("fin_quarter_xbrl", "pat", "money"), ("ratio_panel", "pat", "money")],
    "profit_before_tax": [("fin_quarter_xbrl", "pbt", "money")],
    "total_income": [("fin_quarter_xbrl", "total_income", "money")],
    "ebitda": [("ratio_panel", "ebitda", "money")],          # no XBRL EBITDA line
    "ebitda_margin": [("ratio_panel", "ebitda_margin_pct", "pct")],
    "pat_margin": [("ratio_panel", "pat_margin_pct", "pct")],
    "revenue_growth_yoy": [("ratio_panel", "revenue_growth_yoy_pct", "pct")],
    "pat_growth_yoy": [("ratio_panel", "pat_growth_yoy_pct", "pct")],
    "order.book": [("kpi_series", "order_book", "money")],
    "order.intake": [("kpi_series", "order_intake", "money")],
    "capex": [("kpi_series", "capex", "money")],
    "capacity.total": [("kpi_series", "capacity", "num")],
    "capacity.utilisation": [("kpi_series", "utilisation", "pct")],
    "volume.production": [("kpi_series", "production_kt", "num")],
    "volume.sales": [("kpi_series", "shipments_kt", "num")],
}

# call guidance measure -> store guidance metric (metric names that exist in the stores' guidance table).
GUIDANCE_MAP: dict[str, str] = {
    "revenue_growth_yoy": "revenue_growth",
    "ebitda_margin": "ebitda_margin",
    "capex": "capex",
    "order.intake": "order_intake",
    "nim": "nim",
    "credit_cost": "credit_cost",
    "ebitda_per_tonne": "ebitda_per_tonne",
    "cost_of_production": "cost_of_production",
    "opex_to_nti": "opex_to_nti",
}

_KEY_COL = {"fin_quarter_xbrl": "line_item", "ratio_panel": "metric", "kpi_series": "metric"}
_CALL_BASES = ("consolidated", "standalone")

_TONNAGE_RE = re.compile(r"\bkt\b|kiloton|tonnes?\b|tons?\b|mtpa|\btpa\b|\btpd\b", re.I)
_POWER_RE = re.compile(r"\bmw\b|\bgw\b|megawatts?|gigawatts?|kilowatts?", re.I)
_BPS_RE = re.compile(r"\bbps\b|basis\s*points?", re.I)
_PCT_RE = re.compile(r"%|percent|\bpct\b", re.I)
_MONEY_RE = re.compile(r"crore|lakh|million|billion|\binr\b|\brs\.?\b|₹|usd|\$", re.I)
_PER_UNIT_RE = re.compile(r"(?:^|[^a-z])per(?:[^a-z]|$)|/", re.I)

# store guidance units -> the scale that turns the printed low/high into base units (rupees / plain percent).
_UNIT_SCALE = {"inr": 1.0, "inr_cr": 1e7, "inr_lakh": 1e5, "inr_mn": 1e6, "inr_bn": 1e9,
               "usd": 1.0, "usd_mn": 1e6, "usd_bn": 1e9, "pct": 1.0, "bps": 1.0}


def norm_period(period: str | None) -> str:
    """``Q2 FY27`` / ``q2fy27`` -> ``Q2FY27``; empty stays empty."""
    return re.sub(r"\s+", "", str(period or "").upper())


def unit_family(unit: str | None) -> str:
    """Coarse unit family for a cross-source comparison: money, pct, bps, tonnage, power, per_unit, other."""
    u = (unit or "").strip().lower()
    if not u:
        return ""
    if _PER_UNIT_RE.search(u):
        return "per_unit"
    for fam, pattern in (("tonnage", _TONNAGE_RE), ("power", _POWER_RE), ("bps", _BPS_RE),
                         ("pct", _PCT_RE), ("money", _MONEY_RE)):
        if pattern.search(u):
            return fam
    return "other"


def unit_currency(unit: str | None) -> str:
    """``usd`` / ``inr`` / ``""`` (unknown) for a unit string."""
    u = (unit or "").strip().lower()
    if "usd" in u or "$" in u:
        return "usd"
    if re.search(r"\binr\b|\brs\.?\b|₹|rupee", u):
        return "inr"
    return ""


def _close(a: float, b: float, kind: str) -> bool:
    """The brief's tolerance: 0.05 absolute for percentages, 1% relative for money/numbers."""
    if kind in ("pct", "bps"):
        return abs(a - b) <= 0.05
    if b == 0:
        return a == 0
    return abs(a - b) <= 0.01 * abs(b)


def _num(x: float) -> str:
    return f"{x:.15g}"


def _date(text: str | None) -> dt.date | None:
    head = str(text or "")[:10]
    try:
        return dt.date.fromisoformat(head)
    except ValueError:
        return None


def _is_post(filed_known: str | None, call_known: str | None) -> bool:
    """True when the filing was not yet knowable one day after the call (``post_call``)."""
    fd, cd = _date(filed_known), _date(call_known)
    if fd is None or cd is None:
        return True
    return fd > cd + dt.timedelta(days=1)


def _bases(call_basis: str | None) -> tuple[str, ...]:
    b = (call_basis or "").strip().lower()
    return (b,) if b in _CALL_BASES else _CALL_BASES


def _looks_like_transcript(doc_key: str | None) -> bool:
    k = str(doc_key or "").lower()
    return "concall" in k or "transcript" in k


def _copy_db_backup(src_path: Path, dst_path: Path) -> None:
    """SQLite backup API: a consistent copy that never writes ``src_path``."""
    if src_path.resolve() == dst_path.resolve():
        raise ValueError("--out must be a copy path distinct from --obs")
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    for suf in ("", "-wal", "-shm"):
        p = Path(str(dst_path) + suf)
        if p.exists():
            p.unlink()
    src = connect_ro(src_path, timeout_s=30.0)
    try:
        dst = sqlite3.connect(str(dst_path))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()


def build_store_index(stores_root: Path) -> dict[str, Path]:
    """symbol -> store DB path, read from each store's ``company`` table (one company per store).

    A store is ``<root>/cNNN/cNNN.db`` (the ``cNNN`` page-text DBs beside it are not stores)."""
    index: dict[str, Path] = {}
    for db in sorted(Path(stores_root).glob("*/*.db")):
        if db.stem != db.parent.name:
            continue
        try:
            con = connect_ro(db, timeout_s=10.0)
        except sqlite3.Error as exc:
            print(f"WARN store {db}: {exc}", file=sys.stderr)
            continue
        try:
            cur = con.execute("SELECT symbol FROM company LIMIT 1")
            assert cur is not None
            row = cur.fetchone()
        except sqlite3.Error as exc:
            print(f"WARN store {db} has no company table: {exc}", file=sys.stderr)
            row = None
        finally:
            con.close()
        if row and row[0]:
            index.setdefault(str(row[0]), db)
    return index


def _read_call_rows(obs_db: Path) -> list[dict[str, Any]]:
    con = connect_ro(obs_db, timeout_s=30.0)
    try:
        cur = con.execute(
            "SELECT observation_id, symbol, doc_key, page, measure, value, value_high, value_text, unit, "
            "scale, period, basis, record_type, status, status_reason, known_at FROM observation "
            "WHERE record_type IN ('number', 'guidance') AND status != 'quarantined' AND value IS NOT NULL "
            "ORDER BY observation_id")
        assert cur is not None
        cols = [c[0] for c in cur.description]
        rows = cur.fetchall()
        assert rows is not None
        return [dict(zip(cols, r)) for r in rows]
    finally:
        con.close()


def _load_filed(con: sqlite3.Connection, wanted: dict[str, set[str]], store: Path) \
        -> dict[tuple[str, str, str, str], list[tuple[float, float, str, str]]]:
    """(period, basis, table, key) -> [(value*scale, printed value, unit, known_at)]."""
    out: dict[tuple[str, str, str, str], list[tuple[float, float, str, str]]] = defaultdict(list)
    for table, keys in wanted.items():
        if not keys:
            continue
        key_col = _KEY_COL[table]
        marks = ",".join("?" * len(keys))
        try:
            rows = con.execute(
                f"SELECT fiscal_period, basis, {key_col}, value, unit, scale, known_at FROM {table} "
                f"WHERE {key_col} IN ({marks})", tuple(sorted(keys))).fetchall()
        except sqlite3.Error as exc:
            print(f"WARN {store} table {table}: {exc}", file=sys.stderr)
            continue
        for period, basis, key, value, unit, scale, known in rows:
            if value is None or not known:
                continue
            out[(norm_period(period), str(basis or ""), table, str(key))].append(
                (float(value) * float(scale or 1.0), float(value), str(unit or ""), str(known)))
    return out


def _wanted(number_rows: list[dict[str, Any]]) -> dict[str, set[str]]:
    wanted: dict[str, set[str]] = defaultdict(set)
    for row in number_rows:
        for table, key, _kind in NUMBER_MAP.get(str(row["measure"]), ()):
            wanted[table].add(key)
    return wanted


def _num_hit(call_value: float, call_high: float | None, unit: str | None, kind: str,
             filed_value: float, filed_unit: str | None) -> bool:
    """The 1% / 0.05 rule plus a unit-family compatibility check (never compare crore to tonnes)."""
    cfam, ffam = unit_family(unit), unit_family(filed_unit)
    if kind == "pct":
        if cfam != "pct" or ffam != "pct":
            return False
    elif kind == "money":
        if cfam not in ("money", "") or ffam != "money":
            return False
        if unit_currency(filed_unit) == "usd" and unit_currency(unit) != "usd":
            return False
    else:
        if not cfam or cfam != ffam:
            return False
    if call_high is not None and call_high > call_value:
        return call_value - 1e-9 <= filed_value <= call_high + 1e-9
    return _close(call_value, filed_value, kind)


def match_number(row: dict[str, Any],
                 filed: dict[tuple[str, str, str, str], list[tuple[float, float, str, str]]]) -> dict[str, Any] | None:
    """Best filed row for one call number, or None.  Prefers pre_call, then map order, then earliest known."""
    per = norm_period(row["period"])
    if not per:
        return None
    scale = float(row["scale"] or 1.0)
    call_value = float(row["value"]) * scale
    call_high = None if row["value_high"] is None else float(row["value_high"]) * scale
    hits: list[tuple[bool, int, int, str, str, str, str, float, str]] = []
    for mi, (table, key, kind) in enumerate(NUMBER_MAP[str(row["measure"])]):
        for bi, basis in enumerate(_bases(row["basis"])):
            for scaled, raw, unit, known in filed.get((per, basis, table, key), ()):
                if _num_hit(call_value, call_high, row["unit"], kind, scaled, unit):
                    hits.append((_is_post(known, row["known_at"]), mi, bi, known, table, key, basis, raw, unit))
    if not hits:
        return None
    hits.sort(key=lambda h: (h[0], h[1], h[2], h[3]))
    post, _mi, _bi, _known, table, key, basis, raw, unit = hits[0]
    cite = f"{REASON_PREFIX}{table}.{key} {per}"
    if basis:
        cite += f" {basis}"
    if unit:
        cite += f" = {_num(raw)} {unit}"
    else:
        cite += f" = {_num(raw)}"
    cite += f" ({'post' if post else 'pre'}_call)"
    return {"cite": cite, "table": table, "metric": key, "period": per, "basis": basis,
            "value": raw, "unit": unit, "when": "post_call" if post else "pre_call"}


def match_guidance(row: dict[str, Any], store_rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Best store guidance row for one call guidance row, or None (same metric/period, 120 days, 1%)."""
    metric = GUIDANCE_MAP.get(str(row["measure"]))
    per = norm_period(row["period"])
    if not metric or not per:
        return None
    scale = float(row["scale"] or 1.0)
    call_low = float(row["value"]) * scale
    call_high = float(row["value_high"] if row["value_high"] is not None else row["value"]) * scale
    call_date = _date(row["known_at"])
    cfam = unit_family(row["unit"])
    hits: list[tuple[bool, str, dict[str, Any], float, float]] = []
    for g in store_rows:
        if str(g["metric"]) != metric or norm_period(g["target_period"]) != per:
            continue
        said = _date(g["said_on"])
        if call_date and said and abs((said - call_date).days) > GUIDANCE_WINDOW_DAYS:
            continue
        fam = unit_family(g["unit"])
        if fam != cfam:
            continue
        if fam == "money" and unit_currency(g["unit"]) == "usd" and unit_currency(row["unit"]) != "usd":
            continue
        if g["low"] is None or g["high"] is None:
            continue
        gscale = _UNIT_SCALE.get(str(g["unit"] or "").strip().lower(), 1.0)
        low, high = float(g["low"]) * gscale, float(g["high"]) * gscale
        kind = fam if fam in ("pct", "bps") else ("money" if fam == "money" else "num")
        if not (_close(call_low, low, kind) and _close(call_high, high, kind)):
            continue
        hits.append((_is_post(g["known_at"] or g["said_on"], row["known_at"]), str(g["said_on"] or ""), g, low, high))
    if not hits:
        return None
    hits.sort(key=lambda h: (h[0], h[1]))
    post, _said, g, low, high = hits[0]
    unit = str(g["unit"] or "")
    cite = f"{REASON_PREFIX}guidance.{metric} {per} = {_num(low)}"
    cite += f"-{_num(high)} {unit}" if unit else f"-{_num(high)}"
    cite += f" ({'post' if post else 'pre'}_call)"
    return {"cite": cite, "table": "guidance", "metric": metric, "period": per, "basis": "",
            "value": g["low"], "unit": unit, "when": "post_call" if post else "pre_call"}


def _new_reason(old: str | None, cite: str) -> str:
    """Drop the ``transcript_number:`` segment (the gate's reason) and add the corroboration."""
    parts = [p for p in str(old or "").split("; ") if p and not p.startswith(TRANSCRIPT_NUMBER_PREFIX)]
    return "; ".join(parts + [cite])


def run(obs_db: Path, stores_root: Path, out_db: Path, *, limit_symbols: int | None = None,
        sample_size: int = 20) -> dict[str, Any]:
    """Match transcript call rows against the stores, write the corroborated copy, return the summary."""
    t0 = time.perf_counter()
    obs_db, out_db = Path(obs_db), Path(out_db)
    index = build_store_index(Path(stores_root))
    rows = _read_call_rows(obs_db)

    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_symbol[str(row["symbol"])].append(row)
    symbols = sorted(by_symbol)
    if limit_symbols is not None:
        symbols = symbols[:max(0, int(limit_symbols))]

    stats: dict[str, Any] = {
        "obs_db": str(obs_db), "stores_root": str(stores_root), "out_db": str(out_db),
        "stores_indexed": len(index), "symbols": len(symbols),
        "rows_considered": 0, "rows_matched": 0,
        "matched_by_measure": Counter(), "by_table": Counter(),
        "pre_call": 0, "post_call": 0,
        "unmatched_with_counterpart": 0, "no_counterpart": Counter(),
        "skipped_empty_period": 0, "skipped_not_transcript": 0, "skipped_no_store": 0,
        "guidance": {"considered": 0, "matched": 0, "pre_call": 0, "post_call": 0,
                     "unmatched_with_counterpart": 0, "no_counterpart": 0},
    }
    updates: list[tuple[str, int]] = []
    matched: list[dict[str, Any]] = []

    for symbol in symbols:
        sym_rows = by_symbol[symbol]
        store = index.get(symbol)
        if store is None:
            stats["skipped_no_store"] += len(sym_rows)
            continue
        try:
            con = connect_ro(store, timeout_s=15.0)
        except sqlite3.Error as exc:
            print(f"WARN store {store}: {exc}", file=sys.stderr)
            stats["skipped_no_store"] += len(sym_rows)
            continue
        try:
            try:
                cur = con.execute("SELECT doc_key FROM doc WHERE doc_type='transcript'")
                assert cur is not None
                keys = cur.fetchall()
                assert keys is not None
                transcript_keys = {str(r[0]) for r in keys}
            except sqlite3.Error as exc:
                print(f"WARN {store} doc table: {exc}", file=sys.stderr)
                transcript_keys = set()
            call_rows = [r for r in sym_rows
                         if str(r["doc_key"]) in transcript_keys or _looks_like_transcript(r["doc_key"])]
            stats["skipped_not_transcript"] += len(sym_rows) - len(call_rows)
            number_rows = [r for r in call_rows
                           if r["record_type"] == "number" and str(r["measure"]) in NUMBER_MAP]
            filed = _load_filed(con, _wanted(number_rows), store) if number_rows else {}
            try:
                cur = con.execute("SELECT metric, target_period, low, high, unit, said_on, known_at FROM guidance")
                assert cur is not None
                grows = cur.fetchall()
                assert grows is not None
                store_guidance = [{"metric": r[0], "target_period": r[1], "low": r[2], "high": r[3],
                                   "unit": r[4], "said_on": r[5], "known_at": r[6]} for r in grows]
            except sqlite3.Error as exc:
                print(f"WARN {store} guidance: {exc}", file=sys.stderr)
                store_guidance = []
        finally:
            con.close()

        for row in call_rows:
            stats["rows_considered"] += 1
            measure = str(row["measure"])
            if row["record_type"] == "guidance":
                g = stats["guidance"]
                g["considered"] += 1
                if measure not in GUIDANCE_MAP:
                    g["no_counterpart"] += 1
                    continue
                if not norm_period(row["period"]):
                    stats["skipped_empty_period"] += 1
                    g["unmatched_with_counterpart"] += 1
                    continue
                hit = match_guidance(row, store_guidance)
                if hit is None:
                    g["unmatched_with_counterpart"] += 1
                    continue
                g["matched"] += 1
                g[hit["when"]] += 1
                stats["rows_matched"] += 1
                stats["matched_by_measure"][measure] += 1
                stats["by_table"]["guidance"] += 1
                stats[hit["when"]] += 1
            else:
                if measure not in NUMBER_MAP:
                    stats["no_counterpart"][measure] += 1
                    continue
                if not norm_period(row["period"]):
                    stats["skipped_empty_period"] += 1
                    stats["unmatched_with_counterpart"] += 1
                    continue
                hit = match_number(row, filed)
                if hit is None:
                    stats["unmatched_with_counterpart"] += 1
                    continue
                stats["rows_matched"] += 1
                stats["matched_by_measure"][measure] += 1
                stats["by_table"][hit["table"]] += 1
                stats[hit["when"]] += 1
            updates.append((_new_reason(row["status_reason"], hit["cite"]), int(row["observation_id"])))
            matched.append({"observation_id": int(row["observation_id"]), "symbol": symbol, "measure": measure,
                            "call_value_text": row["value_text"], "call_period": row["period"],
                            "call_basis": row["basis"], "matched_table": hit["table"],
                            "matched_metric": hit["metric"], "matched_value": hit["value"],
                            "matched_unit": hit["unit"], "matched_period": hit["period"],
                            "matched_basis": hit["basis"], "when": hit["when"]})

    _copy_db_backup(obs_db, out_db)
    con = sqlite3.connect(str(out_db))
    try:
        con.executemany("UPDATE observation SET status='verified', status_reason=? WHERE observation_id=?", updates)
        con.commit()
    finally:
        con.close()

    stats["elapsed_s"] = round(time.perf_counter() - t0, 2)
    stats["no_counterpart_total"] = sum(stats["no_counterpart"].values()) \
        + stats["guidance"]["no_counterpart"]
    stats["no_counterpart_measures"] = len(stats["no_counterpart"])
    stats["no_counterpart"] = dict(stats["no_counterpart"].most_common(20))
    stats["matched_by_measure"] = dict(stats["matched_by_measure"].most_common())
    stats["by_table"] = dict(stats["by_table"].most_common())
    stats["samples"] = (random.Random(SAMPLE_SEED).sample(matched, min(sample_size, len(matched)))
                        if matched else [])
    return stats


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--obs", required=True, type=Path, help="observation SQLite DB (read-only input)")
    ap.add_argument("--stores-root", required=True, type=Path, help="directory of cNNN/cNNN.db stores")
    ap.add_argument("--out", required=True, type=Path, help="output copy; the input is never written")
    ap.add_argument("--limit-symbols", type=int, default=None, help="process only the first N symbols (smoke run)")
    args = ap.parse_args(argv)
    stats = run(args.obs, args.stores_root, args.out, limit_symbols=args.limit_symbols)
    print(json.dumps(stats, indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
