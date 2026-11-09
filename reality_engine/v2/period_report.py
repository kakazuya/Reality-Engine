"""T-134 read-only period-engine report over a pilot3 store.

Reads ``kpi_series`` through :func:`reality_engine.db.readonly.connect_ro` (the store is never
written), maps every row into an in-memory v2 company file (one entity per symbol, one fact per
row, value in base units, the period parsed from ``fiscal_period`` with the Indian March year end)
and runs :func:`reality_engine.v2.periods.derive` once per key.  It then prints, per symbol, how
many derived facts were written, how many key+period conflicts blocked a derivation, and how many
candidate derivations were skipped (and why), followed by the SBILIFE ``ape`` rows the engine
holds.  The pilot store mixes definitions under one key, so those conflicts are the point of the
report.

Additivity comes from the unit only (percent, bps, ``x``, days and per-unit lines are never
summed); a real build tags each metric in ``label_map``.
"""
from __future__ import annotations

import argparse
import calendar
import re
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from typing import Any

from reality_engine.db.readonly import connect_ro
from reality_engine.v2 import schema
from reality_engine.v2.periods import derive, period_row

_DAY = timedelta(days=1)
_FISCAL = re.compile(r"^(Q[1-4]FY|H[12]FY|9MFY|FY)(\d{2})$")
_NOT_ADDITIVE = {"pct", "bps", "x", "days"}
# Flow metrics only: a stock (AUM, embedded value, order book, deposits, market share) has a value AT a date, so
# "Q4 = FY - 9M" is meaningless for it. kpi_series carries no stock/flow flag yet (label_map, T-133, will); until
# then a metric is additive only when its name says it is a flow over the period. Unknown metrics get YoY/QoQ only.
_FLOW_WORDS = ("revenue", "income", "premium", "ape", "gwp", "vnb", "pat", "profit", "ebit", "sales", "volume",
               "production", "offtake", "expense", "cost", "capex", "orders_received", "order_inflow", "disbursement",
               "dividend", "cash_flow", "tax", "interest", "commission")


def _add_months(day: date, months: int) -> date:
    index = day.month - 1 + months
    year = day.year + index // 12
    month = index % 12 + 1
    return date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def _fy_start_of(day: date, fy_end_month: int = 3) -> date:
    start_month = fy_end_month % 12 + 1
    return date(day.year if day.month >= start_month else day.year - 1, start_month, 1)


def _fiscal_span(text: str | None, as_of_date: str | None) -> dict[str, Any] | None:
    """Map a store ``fiscal_period`` ('Q2FY27', 'H1FY26', '9MFY26', 'FY26', 'YTD') to a period row."""
    if text == "YTD":
        if not as_of_date:
            return None
        end = date.fromisoformat(as_of_date)
        return period_row(_fy_start_of(end), end, allow_other=True)
    match = _FISCAL.match(text or "")
    if match is None:
        return None
    marker, two_digit_year = match.group(1).removesuffix("FY") or "FY", int(match.group(2))
    fy_start = date(2000 + two_digit_year - 1, 4, 1)
    if marker == "FY":
        start, end = fy_start, _add_months(fy_start, 12) - _DAY
    elif marker == "9M":
        start, end = fy_start, _add_months(fy_start, 9) - _DAY
    elif marker == "H1":
        start, end = fy_start, _add_months(fy_start, 6) - _DAY
    elif marker == "H2":
        start, end = _add_months(fy_start, 6), _add_months(fy_start, 12) - _DAY
    else:
        quarter = int(marker[1])
        start = _add_months(fy_start, 3 * (quarter - 1))
        end = _add_months(fy_start, 3 * quarter) - _DAY
    return period_row(start, end)


def _base_unit(unit: str | None) -> str:
    text = (unit or "").strip().lower()
    if text.startswith("inr"):
        return "inr"
    if text in ("percent", "%"):
        return "pct"
    return text or "na"


def _basis(value: str | None) -> str:
    return value if value in ("standalone", "consolidated", "segment") else "na"


def _additive(unit: str, metric: str = "") -> bool:
    if unit in _NOT_ADDITIVE or "_per_" in unit or unit.endswith("_pct"):
        return False
    name = metric.lower()
    if any(word in name for word in ("margin", "ratio", "share", "aum", "embedded_value", "book", "balance",
                                     "persistency", "solvency", "assets", "liabilities", "deposits", "advances")):
        return False
    return any(word in name for word in _FLOW_WORDS)


def _load_rows(source, symbol: str | None) -> list[Any]:
    sql = ("SELECT symbol, isin, metric, dimension, value, unit, scale, fiscal_period, "
           "as_of_date, basis, known_at FROM kpi_series ")
    params: list[Any] = []
    if symbol:
        sql += "WHERE symbol = ? "
        params.append(symbol)
    sql += "ORDER BY symbol, metric, dimension, basis, known_at, id"
    return source.execute(sql, params).fetchall()


def _build_memory(rows: list[Any]) -> tuple[sqlite3.Connection, dict[tuple, dict[str, Any]], int, int]:
    mem = sqlite3.connect(":memory:")
    mem.execute("PRAGMA foreign_keys = ON")
    schema.create(mem)
    entities: dict[str, int] = {}
    keys: dict[tuple, dict[str, Any]] = {}
    mapped = skipped = 0
    for row in rows:
        symbol, isin, metric, dimension, value, unit, scale = row[:7]
        period = _fiscal_span(row[7], row[8])
        if value is None or period is None:
            skipped += 1
            continue
        entity_id = entities.get(symbol)
        if entity_id is None:
            entity_id = len(entities) + 1
            entities[symbol] = entity_id
            mem.execute("INSERT INTO entity (entity_id, isin, name, kind) VALUES (?,?,?,'company')",
                        (entity_id, isin or f"SYMBOL:{symbol}", symbol))
        mem.execute("INSERT OR IGNORE INTO period VALUES (?,?,?,?,?)",
                    (period["period_id"], period["start_date"], period["end_date"],
                     period["kind"], period["fiscal_label"]))
        mapped_unit = _base_unit(unit)
        mem.execute(
            "INSERT INTO fact (entity_id, metric, dimension, period_id, basis, definition, kind, "
            "value, unit, known_at) VALUES (?,?,?,?,?,'company_stated','stated',?,?,?)",
            (entity_id, metric, dimension or "", period["period_id"], _basis(row[9]),
             float(value) * float(scale if scale is not None else 1.0), mapped_unit,
             row[10] or row[8] or "1970-01-01T00:00:00"))
        key = (symbol, metric, dimension or "", _basis(row[9]))
        info = keys.setdefault(key, {"entity_id": entity_id, "unit": mapped_unit})
        mapped += 1
    mem.commit()
    return mem, keys, mapped, skipped


def _print_ape_rows(mem: sqlite3.Connection, symbol: str) -> None:
    rows = mem.execute(
        "SELECT p.fiscal_label, p.kind, f.kind, f.definition, f.value, f.unit, f.known_at, "
        "d.formula_id, d.input_ids, f.check_detail "
        "FROM fact f JOIN entity e ON e.entity_id = f.entity_id "
        "JOIN period p ON p.period_id = f.period_id "
        "LEFT JOIN derivation d ON d.fact_id = f.fact_id "
        "WHERE e.name = ? AND f.metric = 'ape' "
        "ORDER BY p.end_date, f.kind, f.fact_id", (symbol,)).fetchall()
    print(f"\n{symbol} ape rows ({len(rows)}):")
    print(f"  {'period':16} {'kind':9} {'definition':22} {'value':>20} {'unit':5} "
          f"{'formula':30} inputs")
    for label, period_kind, fact_kind, definition, value, unit, known_at, formula, inputs, detail in rows:
        print(f"  {label:16} {period_kind:9} {definition:22} {value:>20,.2f} {unit:5} "
              f"{(formula or '-'):30} {inputs or ''}")
        if detail:
            print(f"  {'':16} {'':9} note: {detail}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="T-134 read-only period-engine report over a pilot3 store")
    parser.add_argument("--db", required=True, help="pilot3 store path (opened read-only)")
    parser.add_argument("--symbol", help="restrict the report to one symbol, e.g. SBILIFE")
    args = parser.parse_args(argv)

    source = connect_ro(args.db, timeout_s=60)
    try:
        rows = _load_rows(source, args.symbol)
    finally:
        source.close()

    mem, keys, mapped, skipped_rows = _build_memory(rows)
    print(f"{args.db}: {len(rows)} kpi rows, {mapped} mapped into {len(keys)} keys "
          f"({skipped_rows} rows skipped: no value or unparseable period)")

    totals: dict[str, dict[str, int]] = defaultdict(
        lambda: {"written": 0, "conflicts": 0, "skipped": 0, "keys": 0})
    conflicts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (symbol, metric, dimension, basis), info in keys.items():
        result = derive(mem, info["entity_id"], metric, dimension=dimension, basis=basis,
                        definition="company_stated", additive=_additive(info["unit"], metric))
        bucket = totals[symbol]
        bucket["keys"] += 1
        bucket["written"] += result["written"]
        bucket["conflicts"] += len(result["conflicts"])
        bucket["skipped"] += len(result["skipped"])
        if args.symbol:
            conflicts[symbol].extend(result["conflicts"])

    for symbol in sorted(totals):
        bucket = totals[symbol]
        print(f"{symbol}: written={bucket['written']} conflicts={bucket['conflicts']} "
              f"skipped={bucket['skipped']} keys={bucket['keys']}")
    total = {name: sum(bucket[name] for bucket in totals.values())
             for name in ("written", "conflicts", "skipped", "keys")}
    print(f"total: written={total['written']} conflicts={total['conflicts']} "
          f"skipped={total['skipped']} keys={total['keys']}")

    focus = args.symbol or "SBILIFE"
    for conflict in conflicts.get(focus, []):
        print(f"  conflict {conflict['fiscal_label']} {conflict['metric']}"
              f"[{conflict['dimension'] or 'total'}]: values={conflict['values']}")
    _print_ape_rows(mem, focus)
    mem.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
