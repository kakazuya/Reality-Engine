"""Re-grade pilot run results after the T1 build filled the tables CASE_MAP declared missing.

    python tasks/pilot60/regrade.py

CASE_MAP.jsonl was written before the pilot builds.  A case whose only declared blocker is
``needs_new_table:<t>`` and whose table the T1 build now provides was downgraded to
BLOCKED_SCHEMA by ``run_v0.run_case`` *after* every hop had answered (the code path only
fires on an ANSWERED row).  This script restores that ANSWERED grade and records the
change, so the pilot is not scored against a schema that now exists.  A fetch blocker is
never cleared.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tasks" / "pilot60"


def built_tables() -> set[str]:
    path = Path(__file__).resolve().parents[2] / ".tmp" / "pilot_all" / "build_result.json"
    if not path.is_file():
        return set()
    counts = json.loads(path.read_text(encoding="utf-8")).get("counts") or {}
    return {t for t, n in counts.items() if isinstance(n, int) and n > 0}


def regrade(path: Path, built: set[str]) -> dict:
    rows = [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines() if x.strip()]
    changed = {}
    for row in rows:
        blocker = str(row.get("blocker") or "")
        if row["grade"] != "BLOCKED_SCHEMA" or "CASE_MAP blocker needs_new_table:" not in blocker:
            continue
        table = blocker.split("needs_new_table:", 1)[1].split(":", 1)[0].strip()
        if table in built:
            row["grade"] = "ANSWERED"
            row["regrade"] = f"table {table} built by the whole-market T1 build"
            changed[table] = changed.get(table, 0) + 1
    path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows),
                    encoding="utf-8")
    return changed


def main() -> int:
    built = built_tables()
    print(f"T1 tables with rows: {len(built)}")
    for name in ("RESULTS_INSTANCES.jsonl", "RESULTS_ORIGINALS.jsonl"):
        path = OUT / name
        if not path.is_file():
            print(f"{name}: missing")
            continue
        changed = regrade(path, built)
        print(f"{name}: regraded {sum(changed.values())} rows {changed}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
