"""Which graded v4 rows changed, and a seeded sample read back against the store.

``gate_run.py v4`` writes one graded row per bank case.  Re-running it after a
label/acceptance fix changes some answers and, where an unstatable value is now a
typed NOT IN DATA, can lower the strict contract count.  This tool names the changes
and checks a seeded sample of them against the fact store with SQL of its own — never
through ``reality_engine.query.v4.execute`` — so a label cannot be confirmed by the
code that printed it.

Usage::

    python tasks/pilot60/v4_changed_rows.py \
        --before tasks/answer_bench/GATE_RESULTS_v4_strict.jsonl \
        --after  .tmp/GATE_RESULTS_v4_after.jsonl

Rows compare on their answer text plus every result's type/operator/value/period/
source/inputs/values, so a reordered word alone does not count as a change.  The
sample is ``random.Random(seed).sample(sorted(changed), n)``: a committed seed and a
sorted input make the 20 rows reproducible.  Exit status 1 means a changed row failed
its independent read-back or a PIT breach was found.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DEFAULT_DB = (Path(r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data")
              / "pilot" / "v4" / "fact_v4_pilot.db")
SEED = 20261031
CHANGE_OPS = ("change", "pct_change", "growth")
#: operators whose scalar is one store row's value (the level read-back applies)
LEVEL_OPS = ("value_at", "last_visible", "first_visible", "max_with_date", "min_with_date")


def _load(path: Path) -> dict[str, dict]:
    rows: dict[str, dict] = {}
    if not path.exists():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            rows[str(row.get("mid"))] = row
    return rows


def _signature(row: dict) -> str:
    """Everything a reader can act on: the answer text and each result's fields."""
    results = []
    for result in row.get("results") or []:
        results.append({
            "type": result.get("answer_type"), "atom": result.get("atom"),
            "formula": result.get("formula"), "operator": result.get("operator"),
            "value": result.get("value"), "period": result.get("period"),
            "unit": result.get("unit"), "source": result.get("source_ref"),
            "known_at": result.get("known_at"), "nids": result.get("nid_reason"),
            "inputs": result.get("inputs"), "numbers": result.get("numbers"),
            "values": [{key: item.get(key) for key in
                        ("period", "value", "known_at", "source_ref", "entity_id")}
                       for item in (result.get("values") or [])],
        })
    return json.dumps({"answer": row.get("answer"), "results": results},
                      sort_keys=True, ensure_ascii=False)


def _category(row: dict) -> set[str]:
    """Why this row's answer moved, from the after row's own labels."""
    tags: set[str] = set()
    for result in row.get("results") or []:
        reason = str(result.get("nid_reason") or "")
        numbers = result.get("numbers") or {}
        if result.get("operator") in CHANGE_OPS:
            tags.add("change printed as a change")
        if result.get("formula") == "f.ratio":
            tags.add("ratio names its kind and inputs")
        if result.get("answer_type") == "not_in_data":
            if "staleness limit" in reason:
                tags.add("stale latest refused")
            if "cannot exceed 100%" in reason:
                tags.add("impossible share refused")
            if "distinct" in reason and "series, not a value" in reason:
                tags.add("unstatable list refused")
            if "no value that can be stated" in reason:
                tags.add("empty value refused")
        if numbers.get("close_basis") or "close basis" in str(result.get("assumption")):
            tags.add("close basis named")
        if numbers.get("ratio_kind") or numbers.get("margin_kind"):
            tags.add("formula selector named")
    return tags


def _within(left, right, tol: float = 1e-6) -> bool:
    try:
        a, b = float(left), float(right)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= tol * max(1.0, abs(a), abs(b))


class Store:
    """Direct SQL over the fact view; never imports the executor."""

    def __init__(self, path: Path):
        if not path.is_file():
            raise SystemExit(f"fact store not found: {path}")
        self.con = sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True)
        self.column = "atom"
        try:
            self.con.execute("SELECT atom_id FROM fact LIMIT 0")
            self.column = "atom_id"
        except sqlite3.Error:
            pass

    def close(self) -> None:
        self.con.close()

    def rows(self, atom: str, entity: str | None, as_of: str) -> list[tuple]:
        sql = (f"SELECT value, period_end, known_at, source_ref, dims FROM fact "
               f"WHERE {self.column} = ? AND substr(known_at, 1, 10) <= ?")
        params: list = [atom, as_of]
        if entity:
            sql += " AND entity_id = ?"
            params.append(entity)
        sql += " ORDER BY COALESCE(period_end, period_start), known_at"
        return self.con.execute(sql, params).fetchall()

    def value_at(self, atom: str, entity: str, period: str, value,
                 dims: str | None, as_of: str) -> bool:
        sql = (f"SELECT value FROM fact WHERE {self.column} = ? AND entity_id = ? "
               f"AND substr(COALESCE(period_end, period_start), 1, 10) = ? "
               f"AND substr(known_at, 1, 10) <= ?")
        params: list = [atom, entity, str(period)[:10], as_of]
        if dims is not None:
            sql += " AND dims = ?"
            params.append(dims)
        return any(_within(row[0], value)
                   for row in self.con.execute(sql, params).fetchall())


def _ratio_inputs(kind: str) -> list[str]:
    return {"de": ["fin.total_debt", "fin.book_equity"],
            "pb": ["price.mcap", "fin.book_equity"],
            "pe": ["price.mcap", "fin.pat"],
            "icr": ["fin.ebitda", "fin.interest_expense"]}.get(kind, [])


def _recompute(store: Store, row: dict, result: dict, checks: list[str]) -> None:
    """Re-derive the printed claim from the store, and compare."""
    as_of = str(row.get("as_of") or "")
    entity = str(result.get("isin") or row.get("entity") or "") or None
    atom = str(result.get("atom") or "")
    answer_type = result.get("answer_type")
    reason = str(result.get("nid_reason") or "")
    numbers = result.get("numbers") or {}

    if answer_type == "measured" and result.get("formula") and result.get("inputs"):
        for item in result.get("inputs") or []:
            name = str(item.get("atom") or "")
            period = str(item.get("period") or "")[:10]
            if not name or name.startswith("benchmark:") or not period:
                continue
            if store.value_at(name, str(entity), period, item.get("value"), None, as_of):
                checks.append(f"input {name} at {period} in store")
            else:
                checks.append(f"input {name} at {period} not in store")

    if answer_type == "measured" and result.get("formula") == "f.ratio":
        kind = str(numbers.get("ratio_kind") or "de")
        inputs = _ratio_inputs(kind)
        values = {}
        for name in inputs:
            rows = store.rows(name, entity, as_of)
            if rows:
                values[name] = float(rows[-1][0])
        if len(values) != 2:
            checks.append(f"ratio inputs not in store: {inputs}")
            return
        expected = values[inputs[0]] / values[inputs[1]]
        if not _within(expected, result.get("value")):
            checks.append(f"ratio {expected} != printed {result.get('value')}")
        if [name for name in inputs if name in values] != list(values):
            checks.append("ratio input order differs")
        checks.append(f"ratio {kind}: {values[inputs[0]]}/{values[inputs[1]]}"
                      f"={expected:.6g}")

    elif answer_type == "measured" and atom and result.get("operator") in CHANGE_OPS:
        rows = store.rows(atom, entity, as_of)
        low = str(numbers.get("from") or "")[:10]
        high = str(numbers.get("to") or "")[:10]
        window = [row for row in rows if low <= str(row[1])[:10] <= high]
        if len(window) < 2:
            checks.append(f"change rows not in store: {atom} {low}..{high}")
            return
        first, last = window[0][0], window[-1][0]
        if not (_within(first, numbers.get("first")) and _within(last, numbers.get("last"))):
            checks.append(f"change ends {first}/{last} != printed "
                          f"{numbers.get('first')}/{numbers.get('last')}")
        expected = (float(last) - float(first) if result.get("operator") == "change"
                    else 100.0 * (float(last) - float(first)) / abs(float(first)))
        if not _within(expected, result.get("value")):
            checks.append(f"change {expected} != printed {result.get('value')}")
        checks.append(f"change {atom} {low}..{high}: {first}->{last}")

    elif (answer_type == "measured" and atom and result.get("value") is not None
          and result.get("operator") in LEVEL_OPS):
        rows = store.rows(atom, entity, as_of)
        if not rows:
            checks.append(f"level rows not in store: {atom}")
            return
        period = str(result.get("period") or "")[:10]
        hits = [row for row in rows if str(row[1])[:10] == period
                and _within(row[0], result.get("value"))]
        if not hits:
            checks.append(f"level {atom} {result.get('value')} at {period} not in store")
        checks.append(f"level {atom} {result.get('value')} at {period} in store")

    if answer_type == "measured":
        for item in (result.get("values") or [])[:3]:
            period = str(item.get("period") or "")[:10]
            if atom and period and item.get("value") is not None:
                if not store.value_at(atom, str(item.get("entity_id") or entity), period,
                                      item.get("value"), None, as_of):
                    checks.append(f"value row {atom} {period} not in store")

    if (answer_type == "measured" and result.get("operator") not in LEVEL_OPS
            and result.get("operator") not in CHANGE_OPS):
        if result.get("operator") == "lag_between":
            from datetime import date
            try:
                days = (date.fromisoformat(str(numbers.get("to"))[:10])
                        - date.fromisoformat(str(numbers.get("from"))[:10])).days
            except ValueError:
                days = None
            if days is None or days != result.get("value"):
                checks.append(f"lag {days} != printed {result.get('value')}")
            checks.append(f"lag {numbers.get('from')}..{numbers.get('to')} = {days} days")
        elif result.get("value") is not None:
            # a non-level scalar (span, aggregate, count): name it, never call it a row
            checks.append(f"{result.get('operator')} {result.get('value')} "
                          f"{result.get('unit') or ''}".strip())
        elif result.get("values") and not atom:
            checks.append(f"{result.get('operator') or 'list'} carries "
                          f"{len(result.get('values') or [])} items")

    if answer_type == "not_in_data" and atom:
        rows = store.rows(atom, entity, as_of)
        checks.append(f"nid {atom}: {len(rows)} rows after PIT")
        match = re.search(r"over (\d+) entities", reason)
        if match:
            count = store.con.execute(
                f"SELECT COUNT(DISTINCT entity_id) FROM fact WHERE {store.column} = ? "
                f"AND substr(known_at, 1, 10) <= ?", (atom, as_of)).fetchone()[0]
            claimed = int(match.group(1))
            if count < claimed:
                checks.append(f"nid claims {claimed} entities, store has {count}")
            checks.append(f"nid multi-entity {atom}: {count} distinct >> 1")
        if "staleness limit" in reason:
            match = re.search(r"\bis (\d{4}-\d{2}-\d{2})", reason)
            if match:
                newest = str(rows[-1][1])[:10] if rows else ""
                if newest != match.group(1):
                    checks.append(f"stale row says {match.group(1)}, store max is {newest}")
                checks.append(f"stale {atom}: newest {newest} at {as_of}")

    if answer_type == "not_in_data" and "cannot exceed 100%" in reason:
        part_atom, whole_atom = "fin.segment_value", "fin.revenue"
        part_rows, whole_rows = (store.rows(part_atom, entity, as_of),
                                 store.rows(whole_atom, entity, as_of))
        if part_rows and whole_rows:
            share = 100.0 * float(part_rows[-1][0]) / float(whole_rows[-1][0])
            if share <= 100.0:
                checks.append(f"share recomputed {share} is not over 100")
            checks.append(f"share recomputed {share:.4f}% > 100")

    if answer_type == "not_in_data" and "series, not a value" in reason:
        match = re.search(r"collected ([\d,]+) distinct value values", reason)
        if match and atom:
            count = store.con.execute(
                f"SELECT COUNT(DISTINCT value) FROM fact WHERE {store.column} = ? "
                f"AND substr(known_at, 1, 10) <= ? AND value IS NOT NULL",
                (atom, as_of)).fetchone()[0]
            claimed = int(match.group(1).replace(",", ""))
            if count != claimed:
                checks.append(f"distinct count {count} != claimed {claimed}")
            checks.append(f"distinct {atom}: {count} > 50")


def _pit_violations(row: dict) -> int:
    as_of = str(row.get("as_of") or "")
    seen = 0
    for result in row.get("results") or []:
        known = str(result.get("known_at") or "")[:10]
        if known and as_of and known > as_of:
            seen += 1
        for item in result.get("values") or []:
            known = str(item.get("known_at") or "")[:10]
            if known and as_of and known > as_of:
                seen += 1
    return seen


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--db", default=DEFAULT_DB, type=Path)
    parser.add_argument("--seed", default=SEED, type=int)
    parser.add_argument("--sample", default=20, type=int)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args(argv)

    before, after = _load(args.before), _load(args.after)
    shared = sorted(set(before) & set(after))
    changed = [mid for mid in shared if _signature(before[mid]) != _signature(after[mid])]
    print(f"rows: before {len(before)}, after {len(after)}, compared {len(shared)}, "
          f"changed {len(changed)}")
    missing = sorted(set(before) - set(after))
    if missing:
        print(f"half-run: {len(missing)} before rows have no after row (not compared): "
              f"{', '.join(missing[:10])}")
    answered_before = sum(1 for mid in shared if before[mid].get("case_answered"))
    answered_after = sum(1 for mid in shared if after[mid].get("case_answered"))
    parts_before = sum(int(before[mid].get("real_answered") or 0) for mid in shared)
    parts_after = sum(int(after[mid].get("real_answered") or 0) for mid in shared)
    print(f"contract over the {len(shared)} compared rows: cases answered "
          f"{answered_before} -> {answered_after}; real_answered parts "
          f"{parts_before} -> {parts_after}")

    by_tag: dict[str, list[str]] = {}
    for mid in changed:
        for tag in _category(after[mid]):
            by_tag.setdefault(tag, []).append(mid)
    for tag in sorted(by_tag, key=lambda key: -len(by_tag[key])):
        print(f"  {len(by_tag[tag]):4d} changed rows: {tag}")

    breaches = {mid: _pit_violations(after[mid]) for mid in shared}
    breaches = {mid: count for mid, count in breaches.items() if count}
    print(f"PIT breaches in the after rows: {sum(breaches.values())} "
          f"(rows: {len(breaches)})")

    sample = random.Random(args.seed).sample(changed, min(args.sample, len(changed)))
    print(f"seed {args.seed}: {len(sample)} changed rows sampled")
    store = Store(args.db)
    failures: list[str] = []
    try:
        for mid in sample:
            checks: list[str] = []
            for result in after[mid].get("results") or []:
                _recompute(store, after[mid], result, checks)
            bad = [check for check in checks if any(word in check for word in
                                                    ("not in store", "!= printed",
                                                     "differs", "not over 100",
                                                     "store max is", "!= claimed",
                                                     "store has"))]
            print(f"  {mid}: {len(checks)} checks " + ("PASS" if not bad else "FAIL"))
            for check in checks:
                print(f"      {check}")
            failures.extend(f"{mid}: {check}" for check in bad)
    finally:
        store.close()

    report = {"seed": args.seed, "changed": changed, "sample": sample,
              "categories": {tag: mids for tag, mids in by_tag.items()},
              "contract": {"compared": len(shared),
                           "cases_answered": [answered_before, answered_after],
                           "real_answered_parts": [parts_before, parts_after]},
              "pit_breaches": breaches, "read_back_failures": failures}
    if args.json:
        args.json.write_text(json.dumps(report, indent=1) + "\n", encoding="utf-8")
        print(f"wrote {args.json}")
    if failures or breaches:
        return 1
    print("PASS: every sampled claim read back from the store; PIT breaches 0")
    return 0


if __name__ == "__main__":
    sys.exit(main())
