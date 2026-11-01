"""Load the rows of ``extract_proto3.db`` that pass the write contracts into the fact store.

The extract store was built before ``reality_engine/contracts.py`` existed, so every row is
re-checked here with ``contracts.check(table, row)``; a failing row never loads.  Routing is
the declared measure map below -- one line per (extract table, measure column, key) -> the
registry atom that measure is.  A measure with no mapping is counted and listed; it is
never loaded under a nearby atom (a gross NPA is not the net NPA the ``fin.npa`` atom is).

Each loaded row keeps its ``known_at`` (the fact store's point-in-time cut is applied at
read time, so a row known after ``as_of`` is never returned), and its ``doc_id``, ``page``
and ``quote`` are kept in the additive side table ``fact_provenance`` under the fact row's
own key.  ``fact`` itself is unchanged.

    python -m reality_engine.query.v4.load_fact --extract <extract_proto3.db> --fact <copy>
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from reality_engine.contracts import VOLUME_UNITS, check
from reality_engine.pilot.extract60 import _page_numbers, row_pk

REPO = Path(__file__).resolve().parents[3]

#: (table, measure column) -> {key value: atom}; ``*`` keys the whole table (one row, one
#: measure).  Every entry names the registry atom whose ``source`` states that measure.
SOURCES: dict[str, tuple[str | None, dict[str, dict[str, str]]]] = {
    "lender_metrics": ("metric", {"value": {
        "nim_pct": "fin.nim",              # net interest margin
        "nnpa_pct": "fin.npa",             # net NPA; gross NPA (gnpa_pct) has no atom
        "credit_cost_pct": "fin.credit_cost",
        "loan_book_cr": "fin.loan_book",
        "deposits_cr": "fin.deposits",
    }}),
    "balance_sheet_lines": ("line_item", {"value_cr": {
        "total_assets": "fin.total_assets",
    }}),
    "tax_reconciliation": ("item", {"amount_cr": {
        "tax_expense": "fin.tax_expense",
        "profit_before_tax": "fin.pretax_profit",
    }}),
    "cash_flow_lines": ("line_item", {"value_cr": {
        "operating_activities": "fin.cfo",
    }}),
    "order_intake": (None, {"intake_cr": {"*": "fin.order_intake"},
                            "order_book_cr": {"*": "fin.order_book"}}),
    "company_capacity_utilisation": ("product", {"utilisation_pct": {
        "*": "fin.capacity_utilisation",
    }}),
    "unit_volume": ("product", {"quantity": {"*": "fin.unit_volume"}}),
    "company_segment_pnl": ("metric", {"value_cr": {
        "revenue": "fin.segment_value", "ebit": "fin.segment_value",
        "ebitda": "fin.segment_value", "segment_assets": "fin.segment_value",
        "segment_liabilities": "fin.segment_value", "capex": "fin.segment_value",
    }}),
}

#: the free-form operating table: the metric's own name, never a fuzzy match.
OPERATING = "company_operating_metrics"
OPERATING_BY_NAME = {"net_npa": "fin.npa", "nim": "fin.nim", "cfo": "fin.cfo",
                     "credit_cost": "fin.credit_cost", "deposits": "fin.deposits"}

#: the unit a measure carries when the row's own unit column is blank
UNITS = {"%": "%", "value_cr": "INR_CRORE", "amount_cr": "INR_CRORE",
         "intake_cr": "INR_CRORE", "order_book_cr": "INR_CRORE"}

PROVENANCE_DDL = """
CREATE TABLE IF NOT EXISTS fact_provenance(
    entity_id   TEXT NOT NULL,
    atom        TEXT NOT NULL,
    dims        TEXT NOT NULL DEFAULT '',
    period_end  TEXT NOT NULL,
    doc_id      TEXT,
    page        INTEGER,
    quote       TEXT,
    known_at    TEXT NOT NULL,
    source      TEXT NOT NULL,
    PRIMARY KEY (entity_id, atom, dims, period_end)
) WITHOUT ROWID;
"""

INSERT_FACT = ("INSERT OR IGNORE INTO fact(entity_id, atom, dims, period_start, period_end, "
               "value, unit, known_at, source_ref) VALUES (?,?,?,?,?,?,?,?,?)")
INSERT_PROVENANCE = ("INSERT OR REPLACE INTO fact_provenance(entity_id, atom, dims, period_end, "
                     "doc_id, page, quote, known_at, source) VALUES (?,?,?,?,?,?,?,?,?)")


def _dims(table: str, row: Mapping[str, Any]) -> str:
    """The dims the fact row carries: only the readings the extract row actually holds."""
    parts = []
    if row.get("basis"):
        parts.append(f"basis={row['basis']}")
    if table == "company_segment_pnl":
        if row.get("metric"):
            parts.append(f"metric={row['metric']}")
        if row.get("segment"):
            parts.append(f"segment={row['segment']}")
    elif table in ("company_capacity_utilisation", "unit_volume"):
        parts.append(f"product={row.get('product') or ''}")
    elif table == OPERATING:
        parts.append(f"metric={row.get('metric') or ''}")
    return ";".join(parts)


def _atom(table: str, column: str, row: Mapping[str, Any], key: str | None) -> str | None:
    """The atom this extract row is, per the declared map; None when it has none."""
    if table == OPERATING:
        name = str(row.get("metric") or "").strip().lower()
        atom = OPERATING_BY_NAME.get(name)
        if atom:
            return atom
        unit = str(row.get("unit") or "").strip().lower()
        return "fin.unit_volume" if unit in VOLUME_UNITS else None
    atom = SOURCES[table][1][column].get("*" if key is None else str(key).strip())
    return atom


def _row_value(row: Mapping[str, Any], column: str) -> float | None:
    value = row.get(column)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _disputed(src: sqlite3.Connection) -> set[tuple[str, str]]:
    """Rows T-040 keeps out: disputed, unless a re-read settled on the number the row stored."""
    try:
        rows = src.execute("SELECT table_name, row_pk, printed_token, resolved_value "
                           "FROM number_check WHERE status = 'disputed'").fetchall()
    except sqlite3.Error:
        return set()                      # an extract store built before the number check
    return {(row["table_name"], row["row_pk"]) for row in rows
            if not row["resolved_value"]
            or _page_numbers(str(row["resolved_value"])) != _page_numbers(str(row["printed_token"]))}


def load(extract_db: str | Path, fact_db: str | Path) -> dict[str, Any]:
    """Load every contract-passing mapped row; return the counts the run reports."""
    src = sqlite3.connect("file:" + Path(extract_db).resolve().as_posix() + "?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    dst = sqlite3.connect(str(fact_db))
    dst.executescript(PROVENANCE_DDL)
    loaded = existing = failed = number_disputed = 0
    disputed = _disputed(src)
    reasons: Counter = Counter()
    unmapped: Counter = Counter()
    atoms: Counter = Counter()
    tables = list(SOURCES) + [OPERATING]
    for table in tables:
        try:
            rows = [dict(row) for row in src.execute(f"SELECT * FROM {table}")]
        except sqlite3.Error:
            continue                      # a build that wrote no such table is not an error
        key_column = SOURCES[table][0] if table in SOURCES else "metric"
        columns = list(SOURCES[table][1]) if table in SOURCES else ["value"]
        for row in rows:
            if not str(row.get("isin") or ""):
                continue
            key = row.get(key_column) if key_column else None
            for column in columns:
                atom = _atom(table, column, row, key)
                if atom is None:
                    unmapped[(table, str(key or column))] += 1
                    continue
                if (table, row_pk(table, row)) in disputed:
                    number_disputed += 1
                    continue
                probe = dict(row)
                for other in columns:
                    if other != column:
                        probe[other] = None
                ok, reason = check(table, probe)
                if not ok:
                    failed += 1
                    reasons[str(reason)] += 1
                    continue
                value = _row_value(row, column)
                unit = str(row.get("unit") or UNITS.get(column, "") or "")
                dims = _dims(table, row)
                period = str(row.get("period_end") or "")[:10]
                if not period:                # a filing date is not the period a number is for
                    failed += 1
                    reasons["no_period_end"] += 1
                    continue
                known = str(row.get("known_at") or "")
                source_ref = (f"extract_proto3.{table}#doc={row.get('doc_id') or ''}"
                              f" p{row.get('page')}")
                before = dst.total_changes
                dst.execute(INSERT_FACT, (row["isin"], atom, dims, period, period, value,
                                          unit, known, source_ref))
                if dst.total_changes == before:
                    existing += 1
                    continue
                dst.execute(INSERT_PROVENANCE,
                            (row["isin"], atom, dims, period, row.get("doc_id"),
                             row.get("page"), row.get("quote"), known,
                             f"extract_proto3.{table}"))
                loaded += 1
                atoms[atom] += 1
    dst.commit()
    dst.close()
    src.close()
    return {"loaded": loaded, "existing": existing, "contract_failed": failed,
            "number_disputed": number_disputed,
            "contract_reasons": dict(reasons), "unmapped": dict(unmapped),
            "atoms": dict(atoms)}


def report(stats: Mapping[str, Any]) -> list[str]:
    """The run's lines: what loaded, what a contract refused, what has no mapping."""
    lines = [f"loaded {stats['loaded']} rows; already in the store {stats['existing']}",
             f"contract-failing rows not loaded {stats['contract_failed']}",
             f"disputed numbers not loaded {stats['number_disputed']}"]
    for reason, count in sorted(stats["contract_reasons"].items(), key=lambda kv: -kv[1]):
        lines.append(f"  {count:4d}  {reason}")
    lines.append(f"measures with no mapping (not loaded) "
                 f"{sum(stats['unmapped'].values())} rows, "
                 f"{len(stats['unmapped'])} measure(s)")
    for (table, key), count in sorted(stats["unmapped"].items(), key=lambda kv: -kv[1])[:20]:
        lines.append(f"  {count:4d}  {table}.{key}")
    lines.append("atoms loaded: " + ", ".join(
        f"{atom}={count}" for atom, count in sorted(stats["atoms"].items())))
    return lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--extract", help="extract store (default: the data root's "
                                          "extract_proto3.db)")
    parser.add_argument("--fact", required=True, help="fact store to load into (a copy)")
    args = parser.parse_args(argv)
    extract = Path(args.extract) if args.extract else (
        Path(__import__("os").environ.get("REALITY_DATA_ROOT")
             or REPO / "reality_engine" / "data") / "extract_proto3.db")
    stats = load(extract, args.fact)
    for line in report(stats):
        print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
