"""Random row samples from a live SQLite store without scanning it.

``rowid``-range sampling keeps a 50 GB evidence query cheap: one indexed
``rowid >= ?`` lookup per pick instead of ``ORDER BY RANDOM()``.  ``--schema``
prints columns, indexes and the ``sqlite_stat1`` row estimate so a worker knows
what it is sampling before it samples.

Examples:
    python -m reality_engine.toolbelt.sample_rows --db equity_intelligence \\
        --table insider_trades_v2 --n 5
    python -m reality_engine.toolbelt.sample_rows --db equity_intelligence \\
        --table corporate_documents --where "doc_type='ANNUAL_REPORT'" --stratify symbol --n 20

    from reality_engine.toolbelt.sample_rows import sample
    rows = sample("equity_intelligence", "insider_trades_v2", n=5)["rows"]
"""
from __future__ import annotations

import argparse
import random
import sqlite3
from typing import Any, Sequence

from ._common import add_format, connect, main_guard, print_result, quote_ident

# A filtered rowid range can be sparse; cap the attempts so a bad --where does
# not turn one sample into a scan.  Returns fewer than --n in that case.
_ATTEMPTS_PER_ROW = 50
# Fallback only for WITHOUT ROWID tables: refuse on big tables per the tool's
# contract (no ORDER BY RANDOM() scans over live data).
_MAX_RANDOM_FALLBACK = 100_000


def _table_info(con, table: str) -> list[dict[str, Any]]:
    cols = con.execute(f"PRAGMA table_info({quote_ident(table)})").fetchall()
    return [{"name": r[1], "type": r[2], "notnull": bool(r[3]), "default": r[4], "pk": bool(r[5])}
            for r in cols]


def _indexes(con, table: str) -> list[dict[str, Any]]:
    out = []
    for seq, name, unique, origin, partial in con.execute(f"PRAGMA index_list({quote_ident(table)})").fetchall():
        names = [r[2] for r in con.execute(f"PRAGMA index_info({quote_ident(name)})").fetchall()]
        out.append({"name": name, "unique": bool(unique), "origin": origin,
                    "partial": bool(partial), "columns": names})
    return out


def _row_estimate(con, table: str) -> tuple[int | None, str | None]:
    try:
        # ANALYZE writes one row per index; the table row (idx IS NULL) is
        # optional, so fall back to any index row's first stat number.
        row = con.execute(
            "SELECT stat FROM sqlite_stat1 WHERE tbl=? ORDER BY (idx IS NULL) DESC, idx LIMIT 1",
            (table,)).fetchone()
    except sqlite3.OperationalError:  # ANALYZE was never run
        row = None
    if row and row[0]:
        try:
            return int(str(row[0]).split()[0]), "sqlite_stat1"
        except (ValueError, IndexError):
            pass
    if not _has_rowid(con, table):
        return None, None
    try:
        top = con.execute(f"SELECT max(rowid) FROM {quote_ident(table)}").fetchone()[0]
        return (int(top) if top is not None else 0), "max(rowid)"
    except sqlite3.OperationalError:
        return None, None


def _has_rowid(con, table: str) -> bool:
    try:
        con.execute(f"SELECT rowid FROM {quote_ident(table)} LIMIT 0")
        return True
    except sqlite3.OperationalError:
        return False


def schema(db: str, table: str) -> dict[str, Any]:
    """Columns, indexes and the sqlite_stat1 row estimate for ``table``."""
    con = connect(db)
    try:
        cols = _table_info(con, table)
        if not cols:
            raise ValueError(f"table not found: {table}")
        estimate, source = _row_estimate(con, table)
        return {
            "db": str(db),
            "table": table,
            "columns": cols,
            "indexes": _indexes(con, table),
            "row_estimate": estimate,
            "row_estimate_source": source,
            "rowid": _has_rowid(con, table),
        }
    finally:
        con.close()


def _pick_columns(cols: str | None, available: Sequence[str]) -> list[str]:
    if not cols:
        return list(available)
    wanted = [c.strip() for c in cols.split(",") if c.strip()]
    missing = [c for c in wanted if c not in available]
    if missing:
        raise ValueError(f"unknown column(s): {', '.join(missing)}; available: {', '.join(available)}")
    return wanted


def _sample_where(con, table: str, columns: list[str], where: str | None,
                  params: tuple[Any, ...], n: int, rng: random.Random,
                  distinct: bool = True) -> list[dict[str, Any]]:
    t = quote_ident(table)
    sel = ", ".join(quote_ident(c) for c in columns)
    clause = where or "1=1"
    lo, hi = con.execute(f"SELECT min(rowid), max(rowid) FROM {t} WHERE {clause}", params).fetchone()
    if lo is None:
        return []
    seen: set[int] = set()
    rows: list[dict[str, Any]] = []
    for _ in range(max(n * _ATTEMPTS_PER_ROW, n)):
        if len(rows) >= n:
            break
        pick = rng.randint(int(lo), int(hi))
        got = con.execute(
            f"SELECT rowid AS __rowid__, {sel} FROM {t} WHERE rowid >= ? AND ({clause}) "
            "ORDER BY rowid LIMIT 1", (pick, *params)).fetchone()
        if got is None:
            continue
        rid = int(got[0])
        if distinct and rid in seen:
            continue
        seen.add(rid)
        rows.append(dict(zip(columns, got[1:])))
        if not distinct and len(rows) >= n:
            break
    return rows


def _sample_without_rowid(con, table: str, columns: list[str], where: str | None,
                          params: tuple[Any, ...], n: int) -> list[dict[str, Any]]:
    # ponytail: bounded fallback only; WITHOUT ROWID tables are small here.
    # Upgrade path: hash the primary key and sample key prefixes.
    estimate, _ = _row_estimate(con, table)
    if estimate is not None and estimate > _MAX_RANDOM_FALLBACK:
        raise ValueError(f"{table} has no rowid and {estimate:,} rows; narrow --where or --stratify")
    sel = ", ".join(quote_ident(c) for c in columns)
    clause = where or "1=1"
    rows = con.execute(f"SELECT {sel} FROM {quote_ident(table)} WHERE {clause} "
                       "ORDER BY RANDOM() LIMIT ?", (*params, n)).fetchall()
    return [dict(zip(columns, r)) for r in rows]


def sample(db: str, table: str, where: str | None = None, cols: str | None = None,
           n: int = 20, seed: int = 7, stratify: str | None = None) -> dict[str, Any]:
    """Return up to ``n`` random rows; ``stratify`` gives each distinct value a share.

    Stratification is equal-allocation (``n // distinct values`` each, at least
    one), not proportional: distinct-value counts are avoided because they are
    exactly the unindexed ``GROUP BY`` this tool exists to replace.
    """
    if n < 1:
        raise ValueError("--n must be >= 1")
    con = connect(db)
    try:
        available = [c["name"] for c in _table_info(con, table)]
        if not available:
            raise ValueError(f"table not found: {table}")
        columns = _pick_columns(cols, available)
        rng = random.Random(seed)
        params: tuple[Any, ...] = ()
        if not _has_rowid(con, table):
            rows = _sample_without_rowid(con, table, columns, where, params, n)
        elif not stratify:
            rows = _sample_where(con, table, columns, where, params, n, rng)
        else:
            if stratify not in available:
                raise ValueError(f"unknown --stratify column: {stratify}")
            base = f"({where})" if where else None
            stmt = f"SELECT DISTINCT {quote_ident(stratify)} FROM {quote_ident(table)}"
            if base:
                stmt += f" WHERE {base}"
            values = [r[0] for r in con.execute(stmt + " LIMIT 1000", params).fetchall()]
            per = max(1, n // max(1, len(values)))
            rows = []
            for value in values:
                cond = f"{quote_ident(stratify)} IS ?"
                merged = f"{base} AND {cond}" if base else cond
                rows.extend(_sample_where(con, table, columns, merged, (value,), per, rng))
                if len(rows) >= n:
                    break
            rows = rows[:n]
        return {
            "db": str(db),
            "table": table,
            "columns": columns,
            "n": len(rows),
            "requested": n,
            "seed": seed,
            "where": where,
            "stratify": stratify,
            "rows": rows,
        }
    finally:
        con.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m reality_engine.toolbelt.sample_rows",
        description="Read-only random sample (rowid ranges) or schema of a SQLite table.")
    ap.add_argument("--db", required=True, help="DB name (equity_intelligence, ar_facts, ...) or path")
    ap.add_argument("--table", required=True, help="table name")
    ap.add_argument("--where", help="SQL predicate, e.g. \"doc_type='ANNUAL_REPORT'\"")
    ap.add_argument("--cols", help="comma-separated column list (default: all)")
    ap.add_argument("--n", type=int, default=20, help="rows to return (default: 20)")
    ap.add_argument("--seed", type=int, default=7, help="RNG seed (default: 7)")
    ap.add_argument("--stratify", help="column whose distinct values each get a share")
    ap.add_argument("--schema", action="store_true", help="print columns, indexes, row estimate")
    add_format(ap)
    args = ap.parse_args(argv)
    result = schema(args.db, args.table) if args.schema else sample(
        args.db, args.table, where=args.where, cols=args.cols, n=args.n,
        seed=args.seed, stratify=args.stratify)
    print_result(result, args.format,
                 columns=args.cols.split(",") if args.cols else None)
    return 0


if __name__ == "__main__":
    main_guard(main)
