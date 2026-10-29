"""Apply the pilot (b) reclassification to the CASE_MAP statuses.

    python tasks/pilot_b/apply_reclass.py

``tasks/pilot_b/reclass.json`` (``reality_engine.pilot.build_b --verify``) moved 65
cases from class b to a: the tables they were blocked on are built and the case's
own entity/window is covered by them.  ``tasks/arch_v3/CASE_MAP.jsonl`` was written
before that build, so the bench still reads ``needs_new_fetch:*`` for those cases
and ``run_v0.run_case`` downgrades an otherwise answered case to BLOCKED_TOOL.

This rewrites only ``status`` and ``status_reason`` of the moved cases (idempotent;
a kept-b case is left alone).  The bench's own grading is unchanged: a case still
has to produce rows that pass the gate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CASE_MAP = REPO / "tasks" / "arch_v3" / "CASE_MAP.jsonl"
RECLASS = REPO / "tasks" / "pilot_b" / "reclass.json"


def main() -> int:
    reclass = json.loads(RECLASS.read_text(encoding="utf-8"))
    moved = {mid: note for mid, _table, note in reclass["moved_cases"]}
    rows, changed = [], 0
    for line in CASE_MAP.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        note = moved.get(row["mid"])
        if note is not None:
            status = "answerable_now"
            reason = f"pilot_b: {note}"
            if (row.get("status"), row.get("status_reason")) != (status, reason):
                row["status"], row["status_reason"] = status, reason
                changed += 1
        rows.append(row)
    CASE_MAP.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
                        encoding="utf-8")
    print(f"{CASE_MAP.name}: {changed} status row(s) updated, {len(moved)} moved cases")
    return 0


if __name__ == "__main__":
    sys.exit(main())
