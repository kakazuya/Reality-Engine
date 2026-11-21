"""T-233 fast fix loop: check one pipeline's output DB against the hand-graded golden set.

Every Wolf read (``D:/RealityEngine/t230/wolf_read_*.md``, ``t228/...``, ``t231/...``) was parsed into
``reality_engine/tests/golden/<pipeline>.jsonl``: one line per graded row or page, keyed by what the
document itself prints (store, ``doc_key``, page, the row's label and printed value), never by the
database id, which a rebuild changes.  ``--db`` is matched against those keys and reports::

    still right      a RIGHT row is present and every field the read graded still holds
    newly broken     a RIGHT row vanished or a graded field changed  (the only failing class)
    fixed            a WRONG/MINOR row now meets the corrected value the read states
    still wrong      a WRONG/MINOR row is unchanged
    changed          a WRONG/MINOR row moved but not to the stated fix  (review it by hand)
    gone             a WRONG/MINOR row is no longer emitted  (often a fix; read the diff)
    ambiguous        the identity matched more than one row and none matches the expectation

``--baseline`` adds the global diff (rows added / removed / status changed, by measure, node or kind).
The whole run is model-free and takes seconds.

Usage::

    python -m reality_engine.scripts.regress observations --db D:/RealityEngine/t230/obs_91.db
    python -m reality_engine.scripts.regress claims --db out/claims.db --baseline main/claims.db --json
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence, cast

from reality_engine.db.readonly import connect_ro

DEFAULT_GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "golden"

NUMERIC = frozenset({
    "value", "scale", "value_low", "value_high", "amount_inr_cr", "amount_usd_mn",
    "capacity_value", "price_per_share", "share_pct", "adjusted",
})


@dataclass(frozen=True)
class Pipeline:
    """What a pipeline's golden file needs to know about its output DB."""

    name: str
    table: str
    group: str                      # the column a global diff counts by (measure / node / kind)
    allowed: frozenset[str]         # every row field a golden line may name
    diff_key: tuple[str, ...]       # the one content key the baseline diff is computed on


PIPELINES: dict[str, Pipeline] = {
    "observations": Pipeline(
        name="observations", table="observation", group="measure",
        diff_key=("symbol", "doc_key", "page", "measure", "printed_label", "value_text"),
        allowed=frozenset({
            "symbol", "doc_key", "page", "measure", "printed_label", "value_text", "unit", "scale",
            "period", "period_kind", "entity_scope", "stage", "basis", "adjusted", "geography",
            "printed_axis", "series_title", "status",
        })),
    "claims": Pipeline(
        name="claims", table="claim", group="node",
        diff_key=("store", "doc_key", "page", "known_at", "quote"),
        allowed=frozenset({
            "store", "symbol", "doc_key", "page", "source_kind", "node", "segment", "sign", "value_low",
            "value_high", "unit", "period_norm", "order_kind", "scope_part", "known_at", "status",
            "effective_period", "quote", "revises", "dup_of",
        })),
    "events": Pipeline(
        name="events", table="event", group="kind",
        diff_key=("store", "doc_key", "kind", "seq"),
        allowed=frozenset({
            "store", "symbol", "doc_key", "filing_date", "seq", "kind", "amount_inr_cr", "amount_usd_mn",
            "value_text", "capacity_value", "capacity_unit", "order_kind", "customer",
            "execution_months", "share_pct", "status", "known_at",
        })),
}

# A pseudo-field is not a column: match the row's printed identity in SQL.
SQL_FIELD: dict[str, str] = {"quote": "substr(quote_span, 1, 160)"}


# ------------------------------------------------------------------ matching
def _norm(value: Any) -> Any:
    if isinstance(value, str):
        return " ".join(value.split()).casefold()
    return value


def _num_eq(got: Any, want: Any) -> bool:
    try:
        return abs(float(got) - float(want)) <= max(1e-6, abs(float(want)) * 1e-9)
    except (TypeError, ValueError):
        return False


def field_matches(row: Mapping[str, Any], field: str, want: Any) -> bool:
    """Does ``row[field]`` satisfy ``want`` (a value, a list of allowed values, or ``<nonempty>``)?"""
    got = row.get(field)
    if want is None:
        return got is None
    if want == "<nonempty>":
        return got not in (None, "") and not (field in NUMERIC and _num_eq(got, 0))
    if isinstance(want, list):
        return any(field_matches(row, field, item) for item in want)
    if field in NUMERIC:
        return _num_eq(got, want)
    return _norm(got) == _norm(want)


def diff_fields(row: Mapping[str, Any], want: Mapping[str, Any]) -> list[str]:
    """The golden fields this row does not satisfy, as ``field: got != want``."""
    return [f"{field}: {row.get(field)!r} != {value!r}" for field, value in want.items()
            if not field_matches(row, field, value)]


def _sql_where(key: Mapping[str, Any], keep_empty: bool = False) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for field, want in key.items():
        if want is None or (want == "" and not keep_empty):
            continue
        column = SQL_FIELD.get(field, field)
        if field in NUMERIC:
            clauses.append(f"ABS(COALESCE({column}, 0) - ?) <= 1e-6")
            params.append(float(want))
        elif isinstance(want, int) and not isinstance(want, bool):
            clauses.append(f"{column}=?")
            params.append(want)
        else:
            clauses.append(f"{column}=?")
            params.append(want)
    return (" AND ".join(clauses) or "1=1"), params


def find_rows(con: sqlite3.Connection, pipeline: Pipeline, entry: Mapping[str, Any]) -> tuple[list[dict[str, Any]], str]:
    """Rows matching the entry's strict key, else its looser identity (``[]``, ``"missing"``)."""
    con.row_factory = sqlite3.Row
    for part, label in (("key", "strict"), ("identity", "identity")):
        key = {field: value for field, value in (entry.get(part) or {}).items() if field in pipeline.allowed}
        if not key:
            continue
        where, params = _sql_where(key)
        try:
            rows = [dict(row) for row in con.execute(f"SELECT * FROM {pipeline.table} WHERE {where}", params)]
        except sqlite3.Error as exc:
            raise SystemExit(f"golden {part} does not match the {pipeline.table} schema: {exc}") from exc
        if rows:
            return rows, label
    return [], "missing"


def _pick(rows: list[dict[str, Any]], expect: Mapping[str, Any], wrong: Mapping[str, Any]) -> dict[str, Any]:
    """The matched row closest to the golden expectation, then to its graded fields, then the first."""
    if len(rows) == 1:
        return rows[0]
    return min(rows, key=lambda row: (len(diff_fields(row, expect)) if expect else 0,
                                      len(diff_fields(row, wrong)) if wrong else 0))


# ------------------------------------------------------------------ grading
def grade_entry(con: sqlite3.Connection, pipeline: Pipeline, entry: Mapping[str, Any]) -> dict[str, Any]:
    """One golden line's verdict against the DB."""
    out: dict[str, Any] = {"grade": entry.get("grade", ""), "kind": entry.get("kind", "row"),
                           "source": entry.get("source", ""), "defect": entry.get("defect", ""),
                           "note": entry.get("note", ""), "detail": []}
    if entry.get("kind") == "page":
        return _grade_page(con, pipeline, entry, out)
    rows, matched = find_rows(con, pipeline, entry)
    if not rows:
        out["verdict"] = "newly_broken" if entry.get("grade") == "RIGHT" else "gone"
        out["detail"] = ["no row matches the golden key or identity"]
        return out
    row = _pick(rows, entry.get("expect") or {}, entry.get("wrong") or {})
    out["matched"] = matched
    out["row"] = {field: row.get(field) for field in
                  ("symbol", "doc_key", "page", "measure", "node", "kind", "value_text", "status")
                  if field in row}
    if matched == "identity":
        strict = entry.get("key") or {}
        out["detail"].append("key changed: " + ", ".join(
            f"{field}: {strict[field]!r} -> {row.get(field)!r}" for field in strict
            if field in row and not field_matches(row, field, strict[field])))
    if entry.get("grade") == "RIGHT":
        bad = diff_fields(row, entry.get("expect") or {})
        if entry.get("status") == "verified" and row.get("status") != "verified":
            bad.append(f"status: {row.get('status')!r} != 'verified'")
        if matched == "identity":
            bad.append("the strict key no longer matches")
        if bad:
            out["verdict"] = "newly_broken"
            out["detail"] += bad
        else:
            out["verdict"] = "still_right"
        return out
    # WRONG / MINOR: a stated fix makes it fixed; any movement is worth a look; else unchanged.
    expect = entry.get("expect") or {}
    if expect and not diff_fields(row, expect):
        out["verdict"] = "fixed"
        return out
    wrong = entry.get("wrong") or {}
    moved = diff_fields(row, wrong) if wrong else []
    out["verdict"] = "changed" if moved or matched == "identity" else "still_wrong"
    out["detail"] += moved
    return out


def _grade_page(con: sqlite3.Connection, pipeline: Pipeline, entry: Mapping[str, Any],
                out: dict[str, Any]) -> dict[str, Any]:
    """A page-level golden line: a known defect may shrink to zero, never grow past its graded count."""
    con.row_factory = sqlite3.Row
    key = {field: value for field, value in (entry.get("key") or {}).items() if field in pipeline.allowed}
    where, params = _sql_where(key)
    max_rows = int(entry.get("max", 0))
    require = entry.get("require") or {}
    if require:
        req_where, req_params = _sql_where({**key, **require}, keep_empty=True)
        found = con.execute(f"SELECT COUNT(*) FROM {pipeline.table} WHERE {req_where}", req_params).fetchone()
        out["verdict"] = "newly_broken" if not found or not found[0] else "still_right"
        out["detail"] = [] if found and found[0] else [f"required row is gone: {require}"]
        return out
    forbid = entry.get("forbid") or {}
    if not forbid:
        out["verdict"] = "still_wrong"
        out["detail"] = ["page line has neither forbid nor require"]
        return out
    bad_where, bad_params = _sql_where({**key, **forbid}, keep_empty=True)
    found = con.execute(f"SELECT COUNT(*) FROM {pipeline.table} WHERE {bad_where}", bad_params).fetchone()
    count = int(found[0]) if found else 0
    out["count"] = count
    if count == 0:
        out["verdict"] = "fixed"
    elif count <= max_rows:
        out["verdict"] = "still_wrong"
        out["detail"] = [f"{count} defect row(s), graded {max_rows}; not worse"]
    else:
        out["verdict"] = "newly_broken"
        out["detail"] = [f"{count} defect row(s), graded {max_rows}"]
    return out


# ------------------------------------------------------------------ baseline diff
def _row_key(row: Mapping[str, Any], key: Iterable[str]) -> tuple[Any, ...]:
    out: list[Any] = []
    for field in key:
        value = row.get(field)
        if field in NUMERIC:
            try:
                out.append(round(float(value), 6) if value is not None else None)
            except (TypeError, ValueError):
                out.append(None)
        else:
            out.append(_norm(value))
    return tuple(out)


def _fetch_all(con: sqlite3.Connection, sql: str) -> list[dict[str, Any]]:
    con.row_factory = sqlite3.Row
    return [dict(cast(Any, row)) for row in con.execute(sql)]


def _require_table(con: sqlite3.Connection, table: str, path: str | Path) -> None:
    found = con.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if not found:
        raise SystemExit(f"{path} is not a {table} DB: no '{table}' table")


def diff_against(con: sqlite3.Connection, pipeline: Pipeline, baseline: str | Path,
                 golden: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Every golden row's content key: rows added, removed, or changed status since ``baseline``."""
    key_fields = list(pipeline.diff_key)
    columns = key_fields + ["status", pipeline.group]
    select = ", ".join(SQL_FIELD.get(field, field) + (f" AS {field}" if field in SQL_FIELD else "")
                       for field in columns)
    base = connect_ro(baseline, timeout_s=60)
    try:
        _require_table(base, pipeline.table, baseline)
        old = {_row_key(row, key_fields): row for row in _fetch_all(base, f"SELECT {select} FROM {pipeline.table}")}
    finally:
        base.close()
    new = {_row_key(row, key_fields): row for row in _fetch_all(con, f"SELECT {select} FROM {pipeline.table}")}
    added = [key for key in new if key not in old]
    removed = [key for key in old if key not in new]
    status_changed = [key for key in new if key in old and new[key].get("status") != old[key].get("status")]
    by_group: dict[str, int] = {}
    for key in added + removed + status_changed:
        row = new.get(key) or old.get(key) or {}
        group = str(row.get(pipeline.group) or "?")
        by_group[group] = by_group.get(group, 0) + 1
    return {"added": len(added), "removed": len(removed), "status_changed": len(status_changed),
            "by_group": dict(sorted(by_group.items(), key=lambda item: -item[1])[:10])}


# ------------------------------------------------------------------ report
def _load_golden(pipeline: str, golden_dir: str | Path = DEFAULT_GOLDEN) -> list[dict[str, Any]]:
    path = Path(golden_dir) / f"{pipeline}.jsonl"
    if not path.is_file():
        raise SystemExit(f"golden set not found: {path}")
    entries: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            entry = json.loads(line)
        except ValueError as exc:
            raise SystemExit(f"{path}:{number}: not JSON: {exc}") from exc
        entry["_line"] = number
        entries.append(entry)
    return entries


def _db_symbols(con: sqlite3.Connection, table: str) -> set[str]:
    """The company symbols an output DB actually holds (empty when the table has none or no rows)."""
    try:
        rows = con.execute(f"SELECT DISTINCT symbol FROM {table}").fetchall()
    except sqlite3.Error:
        return set()
    return {str(row[0]).strip().upper() for row in rows if row and row[0]}


def _entry_symbol(entry: Mapping[str, Any]) -> str:
    for part in ("key", "identity", "require", "forbid"):
        value = (entry.get(part) or {}).get("symbol")
        if value:
            return str(value).strip().upper()
    return ""


def applicable_golden(entries: Sequence[Mapping[str, Any]], symbols: set[str]) -> tuple[list[Mapping[str, Any]],
                                                                                        int]:
    """Golden lines about companies this DB holds; one file then serves several disjoint DBs (stage J).

    An empty symbol set (a fixture DB with no rows) or a line with no symbol keeps every line, so the gate
    never goes quiet on an empty DB.
    """
    if not symbols:
        return list(entries), 0
    kept = [entry for entry in entries if not _entry_symbol(entry) or _entry_symbol(entry) in symbols]
    return kept, len(entries) - len(kept)


def run(pipeline_name: str, db: str | Path, baseline: str | Path | None = None,
        golden_dir: str | Path = DEFAULT_GOLDEN) -> dict[str, Any]:
    """Grade one DB and return the report dict (``newly_broken`` is the gate)."""
    pipeline = PIPELINES[pipeline_name]
    con = connect_ro(db, timeout_s=60)
    try:
        _require_table(con, pipeline.table, db)
        symbols = _db_symbols(con, pipeline.table)
        loaded = _load_golden(pipeline_name, golden_dir)
        golden, skipped = applicable_golden(loaded, symbols)
        verdicts = [grade_entry(con, pipeline, entry) for entry in golden]
        diff = diff_against(con, pipeline, baseline, golden) if baseline else None
    finally:
        con.close()
    counts: dict[str, int] = {}
    for verdict in verdicts:
        counts[verdict["verdict"]] = counts.get(verdict["verdict"], 0) + 1
    report = {
        "pipeline": pipeline_name, "db": str(db), "baseline": str(baseline) if baseline else None,
        "golden": len(golden), "skipped_other_db": skipped,
        "rows": sum(1 for entry in golden if entry.get("kind", "row") == "row"),
        "pages": sum(1 for entry in golden if entry.get("kind") == "page"),
        "counts": counts, "verdicts": verdicts, "diff": diff,
        "newly_broken": counts.get("newly_broken", 0),
    }
    return report


def lines(report: Mapping[str, Any]) -> list[str]:
    counts = report["counts"]
    out = [f"T-233 regress: {report['pipeline']}  ({report['db']})",
           f"golden: {report['rows']} rows + {report['pages']} pages from reality_engine/tests/golden"
           + (f"  ({report['skipped_other_db']} lines skipped: companies not in this DB)"
              if report.get("skipped_other_db") else "")]
    order = ("still_right", "newly_broken", "fixed", "still_wrong", "changed", "gone", "ambiguous")
    out.append("  ".join(f"{name}: {counts.get(name, 0)}" for name in order if counts.get(name)))
    for verdict in report["verdicts"]:
        if verdict["verdict"] in ("newly_broken", "ambiguous", "changed"):
            detail = "; ".join(verdict.get("detail") or [])[:300]
            out.append(f"  {verdict['verdict'].upper():12s} {verdict.get('source') or verdict.get('_line')}"
                       f"  {verdict.get('defect') or ''}  {detail}")
    if report.get("diff"):
        diff = report["diff"]
        groups = ", ".join(f"{name} {count}" for name, count in diff["by_group"].items())
        out.append(f"baseline diff: added {diff['added']}, removed {diff['removed']}, "
                   f"status changed {diff['status_changed']}" + (f"  (by {report['pipeline']}: {groups})" if groups else ""))
    out.append("GATE: " + ("FAIL - newly broken rows above" if report["newly_broken"]
                           else "pass - nothing that was right is wrong now"))
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-233: golden regression check for one pipeline DB")
    parser.add_argument("pipeline", choices=sorted(PIPELINES))
    parser.add_argument("--db", required=True, help="the output DB to check (read-only)")
    parser.add_argument("--baseline", default="", help="an older output DB to diff against")
    parser.add_argument("--golden", default=str(DEFAULT_GOLDEN), help="golden JSONL directory")
    parser.add_argument("--json", action="store_true", help="print the full report as JSON")
    args = parser.parse_args(argv)
    started = time.time()
    report = run(args.pipeline, args.db, args.baseline or None, args.golden)
    report["seconds"] = round(time.time() - started, 2)
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print("\n".join(lines(report)))
        print(f"[{report['seconds']}s]")
    return 1 if report["newly_broken"] else 0


if __name__ == "__main__":
    sys.exit(main())
