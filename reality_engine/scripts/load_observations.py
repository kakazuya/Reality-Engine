"""T-239: load hy4 observations (decks, AR, transcripts) and T-231 events into a Telegram store.

Usage:
    python -m reality_engine.scripts.load_observations --store <path.db> [--symbol SYM]
    python -m reality_engine.scripts.load_observations --all [--root D:/RealityEngine/tg_build]
"""
from __future__ import annotations

import argparse
import sqlite3
import time
from pathlib import Path

OBS_SOURCES = [
    ("deck", "D:/RealityEngine/t230/obs_91_j.db", "deck"),
    ("annual_report", "D:/RealityEngine/t230/obs_ar_91_m.db", "annual_report"),
    ("transcript", "D:/RealityEngine/t238/obs_transcripts_91o.db", "transcript"),
]
EVENTS_DB = "D:/RealityEngine/t231/events.db"

DOC_TYPE = {"deck": "deck", "annual_report": "annual_report", "transcript": "transcript"}

# T-242 (24 Nov): Sonnet verdicts on UNVERIFIED rows, keyed by the source db's observation_id (sonnet_settle.py).
# confirm / fix-with-fields -> check_status 'model_checked' (graded 29R/1P/0W each on the deck pilot); reject ->
# 'model_rejected' and unsure -> 'model_unsure' are advisory only: the row is still served, never deleted.
# The hy4 row's own fields are never changed; a fix's corrected fields sit in check_fields (JSON).
CHECKS: dict[str, list[str]] = {
    "D:/RealityEngine/hy4_out/pilot_decks_entity.db": ["D:/RealityEngine/t242/sonnet_settle/pilot_decks/verdicts.jsonl"],
    "D:/RealityEngine/hy4_out/obs_decks_fy27.db": ["D:/RealityEngine/t242/sonnet_settle/decks_fy27/verdicts.jsonl"],
}
CHECK_COLS = ("check_status", "check_fields", "check_evidence", "checker")
FIX_FIELDS = ("period", "unit", "scale", "basis", "segment")


def load_checks(db_path: str) -> dict[int, tuple]:
    """observation_id -> (check_status, check_fields json, check_evidence, checker) for one source db."""
    import json
    out: dict[int, tuple] = {}
    for vf in CHECKS.get(db_path, []):
        path = Path(vf)
        if not path.is_file():
            continue
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                v = json.loads(line)
                rid = int(v["id"])
            except (ValueError, KeyError, TypeError):
                continue
            verdict = str(v.get("verdict") or "")
            fields = {k: v[k] for k in FIX_FIELDS if v.get(k) not in (None, "")}
            if verdict in ("confirm", "fix"):
                status = "model_checked"
            elif verdict == "reject":
                status = "model_rejected"
            else:
                status = "model_unsure"
            evidence = " | ".join(x for x in (str(v.get("evidence") or ""), str(v.get("header") or ""),
                                              str(v.get("why") or "")) if x)
            out[rid] = (status, json.dumps(fields, ensure_ascii=False) if fields and verdict == "fix" else None,
                        evidence[:500], str(v.get("checker") or "claude-sonnet medium"))
    return out

OBS_COLS = None  # resolved at runtime


def _cols(db_path, table):
    con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    c = [r[1] for r in con.execute(f"PRAGMA table_info({table})").fetchall()]
    con.close()
    return c


def _ro(path):
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True)


def _create_tables(con, obs_cols):
    col_defs = []
    for c in obs_cols:
        col_defs.append(f'"{c}"')
    col_defs += ['"source" TEXT', '"doc_type" TEXT']
    con.execute(f'CREATE TABLE IF NOT EXISTS obs_fact ({", ".join(col_defs)})')
    have = {r[1] for r in con.execute("PRAGMA table_info(obs_fact)")}
    for c in CHECK_COLS:
        if c not in have:
            con.execute(f'ALTER TABLE obs_fact ADD COLUMN "{c}" TEXT')
    con.execute("""CREATE TABLE IF NOT EXISTS obs_measure_new (
        new_id TEXT, definition TEXT, driver_node TEXT, observations INTEGER,
        pages INTEGER, examples TEXT, first_known_at TEXT, source TEXT)""")
    ev_cols = _cols(EVENTS_DB, "event")
    ev_defs = [f'"{c}"' for c in ev_cols]
    con.execute(f'CREATE TABLE IF NOT EXISTS filing_event ({", ".join(ev_defs)})')


def _load_store(store_path: Path, symbol: str | None = None) -> dict:
    con = sqlite3.connect(str(store_path))
    con.execute("PRAGMA journal_mode=WAL")
    con.isolation_level = None
    if symbol is None:
        row = con.execute("SELECT symbol FROM company LIMIT 1").fetchone()
        symbol = row[0] if row else None
    if not symbol:
        con.close()
        return {"store": str(store_path), "error": "no symbol"}
    global OBS_COLS
    if OBS_COLS is None:
        OBS_COLS = _cols(OBS_SOURCES[0][1], "observation")
    obs_cols = OBS_COLS
    stats = {"symbol": symbol, "obs": {}, "events": 0, "measure_new": 0, "timings": {}}
    try:
        con.execute("BEGIN IMMEDIATE")
        _create_tables(con, obs_cols)
        con.execute("CREATE INDEX IF NOT EXISTS idx_obs_fact_sym_measure_period ON obs_fact(symbol, measure, period)")
        con.execute("CREATE INDEX IF NOT EXISTS idx_obs_fact_sym_rtype_known ON obs_fact(symbol, record_type, known_at)")

        placeholders = ",".join(f'"{c}"' for c in obs_cols)
        check_cols = ",".join(f'"{c}"' for c in CHECK_COLS)
        insert_sql = (f"INSERT INTO obs_fact ({placeholders}, source, doc_type, {check_cols}) "
                      f"VALUES ({','.join('?' * (len(obs_cols) + 2 + len(CHECK_COLS)))})")
        id_pos = obs_cols.index("observation_id") if "observation_id" in obs_cols else None

        for source_key, db_path, source in OBS_SOURCES:
            t0 = time.perf_counter()
            src_con = _ro(db_path)
            con.execute("DELETE FROM obs_fact WHERE symbol=? AND source=?", (symbol, source))
            rows = src_con.execute(
                f"SELECT {placeholders} FROM observation WHERE symbol=? AND status IN ('verified','unverified')",
                (symbol,)).fetchall()
            checks = load_checks(db_path) if id_pos is not None else {}
            none = (None,) * len(CHECK_COLS)
            vals = [list(r) + [source, DOC_TYPE[source]]
                    + list(checks.get(int(r[id_pos]), none) if r[id_pos] is not None else none) for r in rows]
            if vals:
                con.executemany(insert_sql, vals)
            stats["obs"][source] = len(vals)
            src_con.close()
            dt = time.perf_counter() - t0
            stats["timings"][source] = dt
            print(f"{symbol} {source}: {len(vals)} rows in {dt:.3f}s", flush=True)

        # obs_measure_new: idempotent (delete then insert union)
        t0 = time.perf_counter()
        con.execute("DELETE FROM obs_measure_new")
        seen = set()
        mn_rows = []
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
                mn_rows.append((rec.get("new_id"), rec.get("definition"), rec.get("driver_node"),
                               rec.get("observations"), rec.get("pages"), rec.get("examples"),
                               rec.get("first_known_at"), source))
            src_con.close()
        if mn_rows:
            con.executemany(
                "INSERT INTO obs_measure_new (new_id, definition, driver_node, observations, pages, examples, "
                "first_known_at, source) VALUES (?,?,?,?,?,?,?,?)", mn_rows)
        stats["measure_new"] = len(mn_rows)
        stats["timings"]["measure_new"] = time.perf_counter() - t0
        print(f"{symbol} measure_new: {len(mn_rows)} rows in {stats['timings']['measure_new']:.3f}s", flush=True)

        # filing_event
        t0 = time.perf_counter()
        con.execute("DELETE FROM filing_event WHERE symbol=?", (symbol,))
        ev_con = _ro(EVENTS_DB)
        ev_cols = [c[1] for c in ev_con.execute("PRAGMA table_info(event)").fetchall()]
        ev_placeholders = ",".join("?" * len(ev_cols))
        ev_rows = ev_con.execute(
            f"SELECT {','.join(ev_cols)} FROM event WHERE symbol=? AND status IN ('verified','unverified')",
            (symbol,)).fetchall()
        if ev_rows:
            con.executemany(f"INSERT INTO filing_event ({','.join(ev_cols)}) VALUES ({ev_placeholders})", ev_rows)
        stats["events"] = len(ev_rows)
        ev_con.close()
        stats["timings"]["events"] = time.perf_counter() - t0
        print(f"{symbol} events: {len(ev_rows)} rows in {stats['timings']['events']:.3f}s", flush=True)

        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
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
