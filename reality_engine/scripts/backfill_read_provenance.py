"""Backfill read provenance on rows read before 26 Nov 2026 (Shivam: store model, gateway, harness, prompt, time).

For each observation DB: add the columns read_model / read_gateway / read_harness / prompt_fp when missing, then fill
the rows whose read_model is empty from what is known about them: the reader id they carry (``reader``), the gateway
that reader's MODELS entry is called through, the harness that ran it (every hy4 read so far ran in
``reality_engine.v2.observations`` over direct HTTP), and the prompt fingerprint ``page_reply`` stored for that page.
``read_at`` (the timestamp) is already on every row.  Rows that already carry provenance are never touched.

CLI: ``python -m reality_engine.scripts.backfill_read_provenance [db ...]`` (default: every loader source db).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

from reality_engine.scripts import load_observations as lo
from reality_engine.v2 import observations as obs
from reality_engine.v2 import reference_pages as rp

COLS = ("read_model", "read_gateway", "read_harness", "prompt_fp")


def backfill(db: str | Path, harness: str = obs.READ_HARNESS_DEFAULT) -> dict[str, int]:
    con = sqlite3.connect(str(db), timeout=600)
    have = {r[1] for r in con.execute("PRAGMA table_info(observation)")}
    for c in COLS:
        if c not in have:
            con.execute(f"ALTER TABLE observation ADD COLUMN {c} TEXT NOT NULL DEFAULT ''")
    con.commit()
    out: dict[str, int] = {}
    for (reader,) in con.execute("SELECT DISTINCT reader FROM observation WHERE read_model=''").fetchall():
        name = str(reader or "").split("@")[0]
        entry = rp.MODELS.get(f"{name}@obs") or rp.MODELS.get(name) or {}
        gateway = obs.gateway_of(entry) if entry else "unknown"
        model = str(entry.get("id") or name or "unknown")
        if gateway in ("opencode-go", "opencode-zen") and "/" not in model:
            model = f"{gateway}/{model}"
        cur = con.execute("UPDATE observation SET read_model=?, read_gateway=?, read_harness=? "
                          "WHERE read_model='' AND reader IS ?", (model, gateway, harness, reader))
        out[f"{reader} -> {model} via {gateway}"] = cur.rowcount
    if con.execute("SELECT 1 FROM sqlite_master WHERE name='page_reply'").fetchone():
        cur = con.execute("UPDATE observation SET prompt_fp = COALESCE((SELECT fingerprint FROM page_reply p "
                          "WHERE p.doc_key=observation.doc_key AND p.page=observation.page), '') "
                          "WHERE prompt_fp=''")
        out["prompt_fp filled"] = cur.rowcount
    con.commit()
    con.close()
    return out


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    dbs = argv or list(dict.fromkeys([p for _k, p, _s in lo.OBS_SOURCES] + [p for _k, p, _s, _o in lo.SUPPLEMENTS]))
    for db in dbs:
        if not Path(db).is_file():
            print(f"{db}: missing")
            continue
        print(db, backfill(db), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
