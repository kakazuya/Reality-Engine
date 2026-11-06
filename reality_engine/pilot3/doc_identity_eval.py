"""Score ``doc_identity`` on a hand-read gold file (T-093).

CLI: ``python -m reality_engine.pilot3.doc_identity_eval <gold.jsonl> [--min-pass N]``

One JSON object per line: ``gid``, ``doc_id`` (``corporate_documents.id``), optional ``as_symbol`` (a swapped pair: the file
is checked as this other company's), and what it must say: ``verdict`` always, and ``company``, ``fiscal_year``, ``type``,
``date`` where the gold states them.  ``note`` is why.  Read-only.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3.doc_identity import check_row, main_store

FIELDS = ("verdict", "company", "fiscal_year", "type", "date")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("gold", type=Path)
    ap.add_argument("--min-pass", type=int, default=None)
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    items = [json.loads(line) for line in args.gold.read_text(encoding="utf-8").splitlines() if line.strip()]
    passed = 0
    for item in items:
        row = conn.execute("SELECT * FROM corporate_documents WHERE id=?", (item["doc_id"],)).fetchone()
        result = check_row(conn, row, item.get("as_symbol"))
        faults = [f"{name} {getattr(result, name)} wanted {item[name]}" for name in FIELDS
                  if name in item and getattr(result, name) != item[name]]
        passed += not faults
        print(f"{item['gid']} doc {item['doc_id']} {'PASS' if not faults else 'FAIL  ' + '; '.join(faults)}")
    print(f"documents passed {passed} of {len(items)}")
    return 1 if args.min_pass is not None and passed < args.min_pass else 0


if __name__ == "__main__":
    sys.exit(main())
