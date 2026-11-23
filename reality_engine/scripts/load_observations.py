"""T-239: load hy4 observations (decks, AR, transcripts) and T-231 events into a Telegram store.

Usage:
    python -m reality_engine.scripts.load_observations --store <path.db> [--symbol SYM]
    python -m reality_engine.scripts.load_observations --all [--root D:/RealityEngine/tg_build]
"""
from __future__ import annotations

import argparse
import csv
import sqlite3
from pathlib import Path

OBS_SOURCES = [
    ("deck", "D:/RealityEngine/t230/obs_91_j.db", "deck"),
    ("annual_report", "D:/RealityEngine/t230/obs_ar_91_m.db", "annual_report"),
    ("transcript", "D:/RealityEngine/t238/obs_transcripts_91o.db", "transcript"),
]
EVENTS_DB = "D:/RealityEngine/t231/events.db"

DOC_TYPE = {"deck": "deck", "annual_report": "annual_report", "transcript": "transcript"}

OBS_COLS = None  # resolved at runtime


def _cols(db_path, table):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    con.close()
    return c


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _create_tables(con, obs_cols):
    # obs_fact
    col_defs = []
    for c in obs_cols:
        col_defs.append(f'"{c}"')
    col_defs += ['"source" TEXT', '"doc_type" TEXT']
    con.execute(f'CREATE TABLE IF NOT EXISTS obs_fact ({", ".join(col_defs)})')
    # obs_measure_new
    con.execute("""CREATE TABLE IF NOT EXISTS obs_measure_new (
        new_id TEXT, definition TEXT, driver_node TEXT, observations INTEGER,
        pages INTEGER, examples TEXT, first_known_at TEXT, source TEXT)""")
    # filing_event: copy event columns
    ev_cols = _cols(EVENTS_DB, "event")
    ev_defs = [f'"{c}"' for c in ev_cols]
    con.execute(f'CREATE TABLE IF NOT EXISTS filing_event ({", ".join(ev_defs)})')


def _load_store(store_path: Path, symbol: str | None = None) -> dict:
    con = sqlite3.connect(str(store_path))
    con.execute("PRAGMA journal_mode=WAL")
    if symbol is None:
        row = con.execute("SELECT symbol FROM company LIMIT 1").fetchone()
        symbol = row[0] if row else None
    if not symbol:
        con.close()
        return {"store": str(store_path), "error": "no symbol"}
    global OBS_COLS
    if OBS_COLS is None:
        OBS_COLS = _cols(OBS_SOURCES[0][1], "observation")
    _create_tables(con, OBS_COLS)
    # ensure event cols table exists with correct schema (recreate if missing)
    # indexes
    con.execute("CREATE INDEX IF NOT EXISTS idx_obs_fact_sym_measure_period ON obs_fact(symbol, measure, period)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_obs_fact_sym_rtype_known ON obs_fact(symbol, record_type, known_at)")
    stats = {"symbol": symbol, "obs": {}, "events": 0, "measure_new": 0}
    # obs from each source
    for source_key, db_path, source in OBS_SOURCES:
        src_con = _ro(db_path)
        # delete existing rows of this source
        con.execute("DELETE FROM obs_fact WHERE symbol=? AND source=?", (symbol, source))
        # fetch verified+unverified
        cols = OBS_COLS
        placeholders = ",".join(f'"{c}"' for c in cols)
        rows = src_con.execute(
            f"SELECT {placeholders} FROM observation WHERE symbol=? AND status IN ('verified','unverified')",
            (symbol,)).fetchall()
        inserted = 0
        for r in rows:
            vals = list(r) + [source, DOC_TYPE[source]]
            con.execute(
                f"INSERT INTO obs_fact ({placeholders}, source, doc_type) VALUES ({','.join('?'*(len(cols)+2))})",
                vals)
            inserted += 1
        stats["obs"][source] = inserted
        src_con.close()
    # obs_measure_new: load union (dedupe by new_id) from all sources
    con.execute("DELETE FROM obs_measure_new")
    seen = set()
    mn_count = 0
    for source_key, db_path, source in OBS_SOURCES:
        src_con = _ro(db_path)
        mcols = [c[1] for c in src_con.execute("PRAGMA table_info(measure_new)").fetchall()]
        rows = src_con.execute(f"SELECT {','.join(mcols)} FROM measure_new").fetchall()
        for r in rows:
            rec = dict(zip(mcols, r))
            nid = rec.get("new_id")
            if nid in seen:
                continue
            seen.add(nid)
            con.execute(
                "INSERT INTO obs_measure_new (new_id, definition, driver_node, observations, pages, examples, first_known_at, source) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (rec.get("new_id"), rec.get("definition"), rec.get("driver_node"), rec.get("observations"),
                 rec.get("pages"), rec.get("examples"), rec.get("first_known_at"), source))
            mn_count += 1
        src_con.close()
    stats["measure_new"] = mn_count
    # filing_event
    con.execute("DELETE FROM filing_event WHERE symbol=?", (symbol,))
    ev_con = _ro(EVENTS_DB)
    ev_cols = [c[1] for c in ev_con.execute("PRAGMA table_info(event)").fetchall()]
    rows = ev_con.execute(
        f"SELECT {','.join(ev_cols)} FROM event WHERE symbol=? AND status IN ('verified','unverified')",
        (symbol,)).fetchall()
    ev_placeholders = ",".join("?" * len(ev_cols))
    for r in rows:
        con.execute(f"INSERT INTO filing_event ({','.join(ev_cols)}) VALUES ({ev_placeholders})", r)
    stats["events"] = len(rows)
    ev_con.close()
    con.commit()
    con.close()
    return stats


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--store", help="path to one store db")
    ap.add_argument("--symbol", help="symbol override")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--root", default="D:/RealityEngine/tg_build")
    args = ap.parse_args()
    if args.all:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        from reality_engine.scripts.tg_trial import store_map
        smap = store_map(Path(args.root) / "measure10")
        total = 0
        for sym, db in smap.items():
            st = _load_store(Path(db), sym)
            total += 1
            print(sym, st.get("obs"), "events", st.get("events"))
        print("stores", total)
    else:
        st = _load_store(Path(args.store), args.symbol)
        print(st)


if __name__ == "__main__":
    main()
