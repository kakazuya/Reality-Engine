"""The one election of a preferred financial figure (T-090).

``fin_quarter_xbrl`` and ``fin_quarter_printed`` state the same (symbol, line_item, fiscal_period, basis) more than
once: the filing that first printed it, and a later filing whose comparative column restates it.  One rule picks
the figure a reader should use, and it has one home here, so the build and ``pilot3_fin`` cannot drift:

    the newest ``known_at`` wins; a tie on the filing date goes to the better evidence (XBRL 5, a printed cell
    XBRL confirmed 4, a repeated print 2, a page-arithmetic match 1, unchecked 0), then to the first stored row.

An XBRL row suppresses the printed rows of the same key: ``pilot3_fin`` treats the XBRL line as the evidence and a
printed cell for the same quarter as its duplicate.  A printed row whose token is not one printed number is not a
figure at all (``displayable_printed``), so it never competes.

``elect(rows)`` applies the rule to the rows a lookup has already filtered, and ``apply(conn)`` writes the same rule
into ``preferred_from`` / ``preferred_to`` on both tables: a row is preferred at day D when
``preferred_from <= D`` and (``preferred_to IS NULL`` or ``preferred_to > D``).  The windows of one key tile its
timeline, so plain SQL elects the same row ``pilot3_fin`` returns, point in time.
"""
from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable

from reality_engine.pilot3 import profile, schema

QUARTER_TABLES = ("fin_quarter_xbrl", "fin_quarter_printed")
CHECK_RANK = {"xbrl_ok": 4, "repeat_ok": 2, "sum_ok": 1}
_CLEAN_CELL = re.compile(r"\(?-?\d[\d,]*(?:\.\d+)?\)?")

# One row per stored figure, both tables, for the symbols in ``_pref_scope``.  ``rank`` is the evidence rank the
# lookup uses; a printed row's raw token is carried so the same displayable-cell test can run here.
_UNION = """
SELECT 'x' AS src, rowid AS rid, symbol, line_item, fiscal_period AS period,
       COALESCE(basis, 'not_stated') AS basis, known_at, 5 AS rank, NULL AS check_status, NULL AS raw_token
FROM fin_quarter_xbrl
WHERE known_at IS NOT NULL AND symbol IN (SELECT symbol FROM _pref_scope)
UNION ALL
SELECT 'p', rowid, symbol, line_item, fiscal_period, basis, known_at,
       CASE check_status WHEN 'xbrl_ok' THEN 4 WHEN 'repeat_ok' THEN 2 WHEN 'sum_ok' THEN 1 ELSE 0 END,
       check_status, raw_token
FROM fin_quarter_printed
WHERE known_at IS NOT NULL AND basis IN ('standalone', 'consolidated')
  AND symbol IN (SELECT symbol FROM _pref_scope)
"""


def same_value(a: dict, b: dict) -> bool:
    """Two statements of a figure with no material difference (scale normalised)."""
    av, bv = (a["value"] or 0.0) * (a.get("scale") or 1.0), (b["value"] or 0.0) * (b.get("scale") or 1.0)
    return abs(av - bv) <= max(1e-9, 1e-6 * max(abs(av), abs(bv)))


def displayable_printed(check_status: str | None, raw_token: str | None) -> bool:
    """May this printed cell be shown as a figure?  A checked row yes; an unchecked one only when its raw token is
    one number: a token carrying letters or a currency word ("9,176 cr") is not a figure, while a restated
    comparative may fail the page's arithmetic (e.g. Bajaj's Q2 FY26 restatement) and is still a figure."""
    if check_status in ("xbrl_ok", "sum_ok", "repeat_ok"):
        return True
    return bool(_CLEAN_CELL.fullmatch(re.sub(r"\s+", "", str(raw_token or ""))))


def evidence_rank(table: str | None, check_status: str | None) -> int:
    """How firm one statement of a figure is: XBRL 5, a printed cell XBRL confirmed 4, a repeated print 2."""
    if table == "fin_quarter_xbrl":
        return 5
    return CHECK_RANK.get(str(check_status or ""), 0)


def order_key(row: dict) -> tuple:
    """The ascending key whose last row of a (measure, period, basis) group is the preferred figure.

    The final key is ``-rowid``: when one filing printed the line twice with the same evidence, the FIRST stored
    row is preferred, which is what ``pilot3_fin`` did before the rule moved here (T-090 keeps its answers)."""
    return (str(row["_known_at"]), evidence_rank(row.get("_table"), row.get("_check")),
            -(row.get("_rowid") or 0))


def elect(rows: list[dict]) -> list[dict]:
    """One preferred figure per measure, period and basis, alternatives labelled (T-088, moved here in T-090).

    When several filings state the same line for the same period, the newest filing known at ``as_of`` wins (its
    comparative column is the restated figure), and it is marked ``restated`` when it differs from the first
    printing.  A tie on the filing date goes to the better evidence (XBRL, then a checked printed cell); a
    ``sum_ok`` cell only means an identity on the page held, so it never outranks an XBRL-confirmed one."""
    groups: dict[tuple, list[dict]] = {}
    passthrough: list[dict] = []
    for row in rows:
        known = row.get("_known_at")
        if not known:
            passthrough.append(row)
            continue
        groups.setdefault((row["measure"], row["period"], row["basis"]), []).append(row)
    out = list(passthrough)
    for candidates in groups.values():
        candidates.sort(key=order_key)
        first, preferred = candidates[0], candidates[-1]
        row = dict(preferred)
        alternatives = []
        for other in candidates[:-1]:
            if any(same_value(other, alt) for alt in alternatives):
                continue
            alt = {"value": other["value"], "unit": other["unit"], "scale": other["scale"],
                   "filing_date": str(other["_known_at"])[:10], "role": other.get("column_role") or "xbrl",
                   "definition": other["definition"], "provenance": other["provenance"]}
            if "value_inr" in other:
                alt["value_inr"] = other["value_inr"]
            if other.get("_check"):
                alt["check_status"] = other["_check"]
            alternatives.append(alt)
        row["preferred"] = True
        row["restated"] = not same_value(preferred, first)
        if alternatives:
            row["alternatives"] = alternatives
        out.append(row)
    return [{k: v for k, v in row.items() if not k.startswith("_")} for row in out]


def ensure_columns(conn: sqlite3.Connection) -> None:
    """Add ``preferred_from`` / ``preferred_to`` to a quarter table built before T-090 (additive, never dropped)."""
    for table in QUARTER_TABLES:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (table,)).fetchone():
            continue
        have = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for column in ("preferred_from", "preferred_to"):
            if column not in have:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} TEXT")


def apply(conn: sqlite3.Connection, symbols: Iterable[str] | None = None) -> dict[str, Any]:
    """Write the preferred windows for ``symbols`` (default: the build's companies) into both quarter tables.

    One pass over the union of the two tables, grouped by (symbol, line_item, period, basis): where an XBRL row
    exists for the key it is the candidate set (the printed twins are its duplicates), else the displayable printed
    rows are.  The max of ``order_key`` at each distinct ``known_at`` is preferred from that instant until the next
    one.  ``symbols`` limits the run exactly like the other build parts."""
    ensure_columns(conn)
    missing = [name for name in QUARTER_TABLES
               if not conn.execute("SELECT 1 FROM sqlite_master WHERE name=?", (name,)).fetchone()]
    if missing:      # a build without ``comparatives`` keeps no printed table: nothing to elect across
        return {"skipped": f"{', '.join(missing)} not in this database"}
    wanted = [str(s).strip().upper() for s in (symbols if symbols is not None else profile.symbols()) if s]
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _pref_scope(symbol TEXT PRIMARY KEY)")
    conn.execute("DELETE FROM _pref_scope")
    conn.executemany("INSERT OR IGNORE INTO _pref_scope VALUES (?)", [(s,) for s in wanted])
    conn.execute("CREATE TEMP TABLE IF NOT EXISTS _pref_window(src TEXT, rid INTEGER, frm TEXT, tto TEXT, "
                 "PRIMARY KEY (src, rid)) WITHOUT ROWID")
    conn.execute("DELETE FROM _pref_window")
    groups: dict[tuple, list[sqlite3.Row]] = {}
    factory, conn.row_factory = conn.row_factory, sqlite3.Row    # build() opens the db without a row factory
    try:
        candidates = conn.execute(_UNION).fetchall()
    finally:
        conn.row_factory = factory
    for row in candidates:
        groups.setdefault((row["symbol"], row["period"], row["basis"], row["line_item"]), []).append(row)
    windows = []
    for candidates in groups.values():
        xbrl = [r for r in candidates if r["src"] == "x"]
        pool = xbrl or [r for r in candidates if displayable_printed(r["check_status"], r["raw_token"])]
        pool.sort(key=lambda r: (r["known_at"], r["rank"], -r["rid"]))
        for index, row in enumerate(pool):
            following = pool[index + 1]["known_at"] if index + 1 < len(pool) else None
            if following is not None and following <= row["known_at"]:
                continue                 # another row at the same instant wins the tie
            windows.append((row["src"], row["rid"], row["known_at"], following))
    conn.executemany("INSERT INTO _pref_window VALUES (?,?,?,?)", windows)
    for src, table in (("x", "fin_quarter_xbrl"), ("p", "fin_quarter_printed")):
        conn.execute(f"UPDATE {table} SET preferred_from=w.frm, preferred_to=w.tto FROM _pref_window w "
                     f"WHERE w.src=? AND w.rid={table}.rowid "
                     f"AND symbol IN (SELECT symbol FROM _pref_scope)", (src,))
        conn.execute(f"UPDATE {table} SET preferred_from=NULL, preferred_to=NULL "
                     f"WHERE symbol IN (SELECT symbol FROM _pref_scope) "
                     f"AND rowid NOT IN (SELECT rid FROM _pref_window WHERE src=?)", (src,))
    schema.ensure_views(conn)
    conn.commit()
    current = conn.execute("SELECT COUNT(*) FROM fin_quarter_current").fetchone()[0]
    return {"symbols": len(wanted), "windows": len(windows), "current": current}
