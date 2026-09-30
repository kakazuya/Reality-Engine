"""
Apply analysis/proposed_changes.csv to corporate_documents (additive, reversible).

Never overwrites doc_date / event_date / event_source (the crawl stamp stays auditable).
Adds columns and fills them only where the row still matches the snapshot:
  call_date, publication_date, pit_source, pit_tier, pit_applied_at

Usage:
  python analysis/apply_pit_repair.py            # dry run (default), read-only
  python analysis/apply_pit_repair.py --apply    # ALTER + UPDATE in one transaction
  python analysis/apply_pit_repair.py --rollback # NULL the new columns for repaired rows
"""
from __future__ import annotations

import csv
import json
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

DB = "reality_engine/data/equity_intelligence.db"
PROPOSED = Path("analysis/proposed_changes.csv")
SNAPSHOT = Path("analysis/snapshot_before_dates.jsonl")
NEW_COLS = [("call_date", "TEXT"), ("publication_date", "TEXT"),
            ("pit_source", "TEXT"), ("pit_tier", "INTEGER"), ("pit_applied_at", "TEXT")]


def load():
    snap = {}
    with SNAPSHOT.open(encoding="utf-8") as fh:
        for line in fh:
            r = json.loads(line)
            snap[r["corp_id"]] = r
    by_id = {}
    with PROPOSED.open(encoding="utf-8", newline="") as fh:
        for r in csv.DictReader(fh):
            by_id.setdefault(int(r["corp_id"]), {})[r["field"]] = r
    return snap, by_id


def main() -> int:
    mode = "apply" if "--apply" in sys.argv else "rollback" if "--rollback" in sys.argv else "dry"
    snap, by_id = load()
    con = sqlite3.connect(DB if mode != "dry" else f"file:{DB}?mode=ro",
                          uri=(mode == "dry"), timeout=600)
    cols = {r[1] for r in con.execute("PRAGMA table_info(corporate_documents)")}

    if mode == "rollback":
        with con:
            n = con.executemany(
                "UPDATE corporate_documents SET call_date=NULL, publication_date=NULL,"
                " pit_source=NULL, pit_tier=NULL, pit_applied_at=NULL WHERE id=?",
                [(i,) for i in by_id]).rowcount
        print(f"rolled back {n:,} rows")
        return 0

    # Guard: live row must still equal the snapshot (event_date/source untouched).
    live = {r[0]: r for r in con.execute(
        "SELECT id, event_date, event_source, doc_type FROM corporate_documents WHERE id IN (%s)"
        % ",".join(str(i) for i in by_id))}
    drift, missing, ok = [], [], []
    for cid in by_id:
        lv, sn = live.get(cid), snap.get(cid)
        if not lv or not sn:
            missing.append(cid)
        elif lv[1] != sn["event_date"] or lv[2] != sn["event_source"] or lv[3] != "CONCALL_TRANSCRIPT":
            drift.append(cid)
        else:
            ok.append(cid)
    print(f"docs in proposal: {len(by_id):,}  ok: {len(ok):,}  drifted: {len(drift):,}  missing: {len(missing):,}")

    updates = []
    for cid in ok:
        f = by_id[cid]
        call, pub = f.get("call_date"), f.get("publication_date")
        primary = call or pub
        updates.append((call["proposed_value"] if call else None,
                        pub["proposed_value"] if pub else None,
                        primary["event_source_proposed"], int(primary["date_tier"]), cid))
    print(f"rows to update: {len(updates):,}  "
          f"with call_date: {sum(1 for u in updates if u[0]):,}  "
          f"with publication_date: {sum(1 for u in updates if u[1]):,}")

    if mode == "dry":
        print("missing new columns:", [c for c, _ in NEW_COLS if c not in cols])
        print("DRY RUN - nothing written. Re-run with --apply.")
        return 0

    stamp = datetime.now().isoformat(timespec="seconds")
    with con:
        for name, typ in NEW_COLS:
            if name not in cols:
                con.execute(f"ALTER TABLE corporate_documents ADD COLUMN {name} {typ}")
        n = con.executemany(
            "UPDATE corporate_documents SET call_date=?, publication_date=?, pit_source=?,"
            f" pit_tier=?, pit_applied_at='{stamp}' WHERE id=? AND event_source='doc_date'",
            updates).rowcount
    print(f"updated {n:,} rows at {stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
