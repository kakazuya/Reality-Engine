"""Hand-grade 20 newly answered v4 "latest" rows, reading each value back independently.

The seed is committed here (``SEED``) so the sample is reproducible: newly answered means a
part measured in ``--after`` that was NOT IN DATA for the same case and measure in
``--before``.  Every picked value is re-read from the v4 fact store with a fresh read-only
connection and a direct SQL query (atom, entity, period_end, known_at <= as_of), so a bug in
the executor cannot vouch for itself.

    python tasks/pilot60/latest_handcheck.py \
        --before <old GATE_RESULTS_v4.jsonl> --after tasks/answer_bench/GATE_RESULTS_v4.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sqlite3
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SEED = 20261031
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or REPO / "reality_engine" / "data")
DEFAULT_STORE = DATA / "pilot" / "v4" / "fact_v4_pilot.db"
#: the baseline run may live only in the main checkout: ``tasks/answer_bench`` there
DEFAULT_BEFORE = (DATA / "pilot" / "pilot60").parents[3] / "tasks" / "answer_bench" \
    / "GATE_RESULTS_v4.jsonl"
DEFAULT_AFTER = REPO / "tasks" / "answer_bench" / "GATE_RESULTS_v4.jsonl"
OURS = ("hold", "fin", "price", "flows", "macro")


def load(path: Path) -> dict[str, dict[str, dict]]:
    out: dict[str, dict[str, dict]] = {}
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            parts = {str(result.get("atom")): result for result in row.get("results") or []
                     if result.get("atom")}
            out[str(row.get("mid"))] = {"parts": parts, "as_of": row.get("as_of"),
                                        "question": row.get("question")}
    return out


def measure(part: dict | None) -> bool:
    return bool(part and part.get("answer_type") == "measured"
                and part.get("operator") in ("value_at", "last_visible")
                and part.get("value") is not None and part.get("period")
                and part.get("isin"))


def read_back(store: Path, atom: str, entity: str, period: str, as_of: str,
              dims: dict) -> dict | None:
    """The newest row for atom/entity/period known by as_of, filtered on the part's dims."""
    conn = sqlite3.connect(f"file:{store.as_posix()}?mode=ro&immutable=1", uri=True)
    try:
        rows = conn.execute(
            "SELECT value, unit, known_at, source_ref, period_end, dims FROM fact "
            "WHERE atom_id = ? AND entity_id = ? AND substr(period_end, 1, 10) = ? "
            "AND substr(known_at, 1, 10) <= ? ORDER BY known_at DESC",
            (atom, entity, period[:10], as_of[:10])).fetchall()
    except sqlite3.Error:
        rows = conn.execute(
            "SELECT value, unit, known_at, source_ref, period_end, dims FROM fact "
            "WHERE atom = ? AND entity_id = ? AND substr(period_end, 1, 10) = ? "
            "AND substr(known_at, 1, 10) <= ? ORDER BY known_at DESC",
            (atom, entity, period[:10], as_of[:10])).fetchall()
    finally:
        conn.close()
    wanted = {str(key).lower(): str(value).lower() for key, value in (dims or {}).items()
              if key != "period_kind"}   # the atom's own grain is not a stored dim here
    for value, unit, known_at, source_ref, period_end, raw_dims in rows:
        got = {}
        for piece in str(raw_dims or "").split(";"):
            if "=" in piece:
                key, item = piece.split("=", 1)
                got[key.strip().lower()] = item.strip().lower()
        if any(got.get(key) != item for key, item in wanted.items() if key in got):
            continue
        return {"value": value, "unit": unit, "known_at": str(known_at)[:10],
                "source_ref": source_ref, "period": str(period_end)[:10],
                "rows": len(rows)}
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--before", type=Path, default=DEFAULT_BEFORE)
    parser.add_argument("--after", type=Path, default=DEFAULT_AFTER)
    parser.add_argument("--store", type=Path, default=DEFAULT_STORE)
    parser.add_argument("--n", type=int, default=20)
    args = parser.parse_args(argv)
    before, after = load(args.before), load(args.after)
    pool = []
    for mid, row in after.items():
        old = before.get(mid) or {"parts": {}}
        for atom, part in row["parts"].items():
            if atom.split(".", 1)[0] not in OURS or not measure(part):
                continue
            if measure(old["parts"].get(atom)):
                continue
            pool.append((mid, atom, part, row))
    pool.sort(key=lambda item: (item[0], item[1]))
    picked = random.Random(SEED).sample(pool, min(args.n, len(pool)))
    lines = ["# latest-reading hand grade", "",
             f"seed {SEED} · pool {len(pool)} newly answered period-atom parts · "
             f"picked {len(picked)}", "",
             "| mid | atom | entity | value | period | known_at | store re-read | ok |",
             "|---|---|---|---|---|---|---|---|"]
    failures = 0
    for mid, atom, part, row in sorted(picked, key=lambda item: (item[0], item[1])):
        as_of = str(row.get("as_of") or "")[:10]
        got = read_back(args.store, atom, str(part.get("isin")), str(part.get("period")),
                        as_of, part.get("dims") or {}) if part.get("isin") else None
        if part.get("formula"):
            got = None
        same_value = got is not None and got["value"] is not None and \
            float(got["value"]) == float(part.get("value"))
        same_unit = got is not None and str(got["unit"]) == str(part.get("unit"))
        same_known = got is not None and got["known_at"] == str(part.get("known_at"))[:10]
        pit_ok = got is not None and got["known_at"] <= as_of
        ok = bool(got and same_value and same_unit and same_known and pit_ok)
        failures += 0 if ok else 1
        lines.append(
            f"| {mid} | {atom} | {part.get('isin')} | {part.get('value')} | "
            f"{part.get('period')} | {str(part.get('known_at'))[:10]} | "
            f"{(str(got['value']) + ' ' + str(got['unit']) + ' known ' + got['known_at'])
               if got else 'NO ROW'} | {'yes' if ok else 'NO'} |")
    lines += ["", f"failures: {failures}", ""]
    text = "\n".join(lines)
    print(text)
    out = REPO / ".tmp" / "LATEST_HANDGRADE.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n", encoding="utf-8")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
