"""T-239: load hy4 observations (decks, AR, transcripts) and T-231 events into a Telegram store.

Usage:
    python -m reality_engine.scripts.load_observations --store <path.db> [--symbol SYM]
    python -m reality_engine.scripts.load_observations --all [--root D:/RealityEngine/tg_build]
"""
from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
import time
from pathlib import Path

# Entries that share a source form an ordered priority list (T-242, 24 Nov, Eagle): for each symbol the FIRST db that
# holds rows for it is loaded, so the gated T-242 reads (transcript prompt v3, deck whose-figure prompt) replace the
# older reads company by company as hy4 reaches them, and a company not read yet keeps its older rows.
OBS_SOURCES = [
    ("deck_fy27", "D:/RealityEngine/hy4_out/obs_decks_fy27.db", "deck"),
    ("deck", "D:/RealityEngine/t230/obs_91_j.db", "deck"),
    # Shivam 26 Nov 2026: load every read; an output whose latest graded sample is >10% W+J loads unverified
    ("annual_report_fy27", "D:/RealityEngine/hy4_out/obs_ar_fy27.db", "annual_report"),
    ("annual_report", "D:/RealityEngine/t230/obs_ar_91_m.db", "annual_report"),
    ("results_fy27", "D:/RealityEngine/hy4_out/obs_results_fy27.db", "results"),
    ("transcript_fy27_v3", "D:/RealityEngine/hy4_out/obs_transcripts_fy27_v3.db", "transcript"),
    ("transcript_394_v3", "D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db", "transcript"),
    ("transcript", "D:/RealityEngine/t238/obs_transcripts_91o.db", "transcript"),
]
# T-242 (25 Nov, Eagle): a SUPPLEMENT is loaded BESIDE its source's primary db, never instead of it. hy4 read the deck
# pages twice: obs_decks_fy27.db read every page whose text layer parsed, obs_decks_wide.db re-read the few-figure and
# jumbled-text pages (text_source='text_layer_jumbled'), and the wide page set holds every fy27 page (4,185 of 7,566),
# so only its remaining pages are added. A supplement row keeps source='deck' (the tools filter by it), carries its db
# in `reader` (the row's read provenance, e.g. "hy4-flash-free [obs_decks_wide]") and gets observation_id offset by
# 10,000,000: both dbs number from 1, so the offset keeps ids unique in obs_fact and names the wide rows in the tools'
# provenance.row_id.  (key, db, source, id offset)
SUPPLEMENTS = [
    ("deck_wide", "D:/RealityEngine/hy4_out/obs_decks_wide.db", "deck", 10_000_000),
]
EVENTS_DB = "D:/RealityEngine/t231/events.db"            # the last fallback
# T-242 filing_events, round 7 (25 Nov); same first-db-with-rows rule per symbol.  Whatever a db says, a row is
# loaded `verified` only when its kind is in the CURRENT filing_events.VERIFIED_KINDS (see _gate_event_rows), so an
# older db (t231, round 6) can never serve a kind that has since failed its grade as verified.
EVENTS_PRIORITY = [
    "C:/RealityEngine/t242/orderwin_r7d/events_r7d_fresh5.db",
    "C:/RealityEngine/t242/orderwin_r7d/events_r7d_fresh4.db",
    "C:/RealityEngine/t242/orderwin_r7d/events_r7d_fresh3.db",
    "C:/RealityEngine/t242/fresh6/events_r7_fresh6.db",
]


def _gate_event_rows(cols: list[str], rows: list[tuple]) -> tuple[list[tuple], int]:
    """Re-apply the live per-kind gate: a `verified` row whose kind is not in VERIFIED_KINDS becomes `unverified`."""
    from reality_engine.research.filing_events import VERIFIED_KINDS
    if "status" not in cols or "kind" not in cols:
        return rows, 0
    si, ki = cols.index("status"), cols.index("kind")
    out, moved = [], 0
    for r in rows:
        if r[si] == "verified" and r[ki] not in VERIFIED_KINDS:
            r = (*r[:si], "unverified", *r[si + 1:])
            moved += 1
        out.append(r)
    return out, moved

DOC_TYPE = {"deck": "deck", "annual_report": "annual_report", "transcript": "transcript", "results": "results"}

# T-242 (24 Nov): Sonnet verdicts on UNVERIFIED rows, keyed by the source db's observation_id (sonnet_settle.py).
# confirm / fix-with-fields -> check_status 'model_checked' (graded 29R/1P/0W each on the deck pilot); reject ->
# 'model_rejected' and unsure -> 'model_unsure' are advisory only: the row is still served, never deleted.
# The hy4 row's own fields are never changed; a fix's corrected fields sit in check_fields (JSON).
CHECKS: dict[str, list[str]] = {
    "D:/RealityEngine/hy4_out/pilot_decks_entity.db": ["D:/RealityEngine/t242/sonnet_settle/pilot_decks/verdicts.jsonl"],
    "D:/RealityEngine/hy4_out/obs_decks_fy27.db": ["D:/RealityEngine/t242/sonnet_settle/decks_fy27/verdicts.jsonl"],
}
# T-242 26 Nov (Shivam: review and improve, never block): every hy4 output DB also takes the filed-XBRL verdicts.
XBRL_CHECKS_DIR = Path("D:/RealityEngine/checks/xbrl")
for _key, _db, _src in OBS_SOURCES:
    if "/hy4_out/" in _db:
        CHECKS.setdefault(_db, []).append(str(XBRL_CHECKS_DIR / f"{Path(_db).stem}.jsonl"))
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
            if verdict.startswith("xbrl_"):     # T-242 26 Nov: filed-XBRL cross-check (reality_engine/v2/xbrl_crosscheck.py)
                fx = {"filed_value": v.get("filed"), "filed_basis": v.get("basis")}
                if verdict == "xbrl_unit_fix":
                    fx["scale"] = v.get("fix_scale")
                out[rid] = (verdict, json.dumps(fx, ensure_ascii=False), str(v.get("evidence") or "")[:500],
                            "xbrl_crosscheck")
                continue
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


_SELECT_CACHE: dict[str, str] = {}


def _select_list(db_path: str, obs_cols: list[str]) -> str:
    """The SELECT list for one source db: a column it lacks (an older read without provenance) comes back NULL."""
    if db_path not in _SELECT_CACHE:
        have = set(_cols(db_path, "observation"))
        _SELECT_CACHE[db_path] = ",".join(f'"{c}"' if c in have else f'NULL AS "{c}"' for c in obs_cols)
    return _SELECT_CACHE[db_path]


def _ro(path):
    # 26 Nov: hy4 loops now write these DBs while loads run (reading never stops): wait for the writer's lock
    return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=300)


def _create_tables(con, obs_cols):
    col_defs = []
    for c in obs_cols:
        col_defs.append(f'"{c}"')
    col_defs += ['"source" TEXT', '"doc_type" TEXT']
    con.execute(f'CREATE TABLE IF NOT EXISTS obs_fact ({", ".join(col_defs)})')
    have = {r[1] for r in con.execute("PRAGMA table_info(obs_fact)")}
    for c in obs_cols:                  # 26 Nov: read provenance columns (read_model, read_gateway, ...) join later
        if c not in have:
            con.execute(f'ALTER TABLE obs_fact ADD COLUMN "{c}"')
    for c in CHECK_COLS:
        if c not in have:
            con.execute(f'ALTER TABLE obs_fact ADD COLUMN "{c}" TEXT')
    con.execute("""CREATE TABLE IF NOT EXISTS obs_measure_new (
        new_id TEXT, definition TEXT, driver_node TEXT, observations INTEGER,
        pages INTEGER, examples TEXT, first_known_at TEXT, source TEXT)""")
    ev_cols: list[str] = []                         # the union of every events db's columns, in first-seen order
    for ev_db in [*EVENTS_PRIORITY, EVENTS_DB]:
        if Path(ev_db).is_file():
            ev_cols += [c for c in _cols(ev_db, "event") if c not in ev_cols]
    ev_defs = [f'"{c}"' for c in ev_cols]
    con.execute(f'CREATE TABLE IF NOT EXISTS filing_event ({", ".join(ev_defs)})')
    have = {r[1] for r in con.execute("PRAGMA table_info(filing_event)").fetchall()}
    for c in ev_cols:
        if c not in have:                            # an older store: add the round-3/4 columns (customer_desc, ...)
            con.execute(f'ALTER TABLE filing_event ADD COLUMN "{c}"')


def _cap_unverified(rows: list, cols: list[str], db_path: str) -> tuple[list, int]:
    """Shivam 26 Nov 2026: every read is loaded; when the source output's latest graded audit sample is more than
    10% wrong+junk (read_gate.verified_allowed), its `verified` rows load as `unverified` (served labelled)."""
    from reality_engine.v2 import read_gate  # noqa: PLC0415
    if "status" not in cols or read_gate.verified_allowed(db_path):
        return rows, 0
    si = cols.index("status")
    ri = cols.index("status_reason") if "status_reason" in cols else None
    out, n = [], 0
    for r in rows:
        if r[si] == "verified":
            r = list(r)
            r[si] = "unverified"
            if ri is not None:
                r[ri] = f"{r[ri] or ''}; graded_sample_over_10pct".lstrip("; ")
            n += 1
        out.append(r)
    return out, n


def _apply_check_status(rows: list, cols: list[str], checks: dict[int, tuple]) -> tuple[list, dict]:
    """Filed-XBRL verdicts move status: a match is served `verified` (even in a capped doc type); a contradiction or
    a unit fix is served `unverified` (the fix rides in check_fields).  The read's own fields are never changed."""
    if "status" not in cols or "observation_id" not in cols or not checks:
        return rows, {}
    si, ii = cols.index("status"), cols.index("observation_id")
    moved: Counter = Counter()
    out = []
    for r in rows:
        ck = checks.get(int(r[ii])) if r[ii] is not None else None
        verdict = ck[0] if ck else ""
        new = "verified" if verdict == "xbrl_match" else "unverified" if verdict in (
            "xbrl_contradicts", "xbrl_unit_fix") else None
        if new and r[si] != new:
            r = list(r)
            moved[f"{r[si]}->{new}"] += 1
            r[si] = new
        out.append(r)
    return out, dict(moved)


def _obs_vals(rows, source: str, checks: dict[int, tuple], id_pos: int | None, id_offset: int = 0,
              reader_pos: int | None = None, reader_mark: str = "") -> list[list]:
    """obs_fact insert values: the source row, source/doc_type, and the check verdict of its ORIGINAL id."""
    none = (None,) * len(CHECK_COLS)
    out: list[list] = []
    for r in rows:
        r = list(r)
        ck = none
        if id_pos is not None and r[id_pos] is not None:
            ck = checks.get(int(r[id_pos]), none)
            r[id_pos] = int(r[id_pos]) + id_offset
        if reader_pos is not None and reader_mark:
            r[reader_pos] = f"{r[reader_pos] or ''}{reader_mark}".strip()
        out.append(r + [source, DOC_TYPE[source]] + list(ck))
    return out


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

        done_sources: set[str] = set()
        for source_key, db_path, source in OBS_SOURCES:
            if source in done_sources:
                continue                          # a higher-priority db already gave this symbol's rows
            if not Path(db_path).is_file():
                continue
            t0 = time.perf_counter()
            src_con = _ro(db_path)
            rows = src_con.execute(
                f"SELECT {_select_list(db_path, obs_cols)} FROM observation WHERE symbol=? "
                "AND status IN ('verified','unverified')",
                (symbol,)).fetchall()
            if not rows and any(s == source and k != source_key for k, _p, s in OBS_SOURCES[
                    OBS_SOURCES.index((source_key, db_path, source)) + 1:]):
                src_con.close()
                continue                          # nothing here for this symbol: try the next db of this source
            con.execute("DELETE FROM obs_fact WHERE symbol=? AND source=?", (symbol, source))
            done_sources.add(source)
            stats.setdefault("obs_db", {})[source] = db_path
            checks = load_checks(db_path) if id_pos is not None else {}
            rows, capped = _cap_unverified(rows, obs_cols, db_path)
            if capped:
                stats.setdefault("capped_unverified", {})[source] = capped
            rows, moved = _apply_check_status(rows, obs_cols, checks)
            if moved:
                stats.setdefault("check_status_moves", {})[source] = moved
            vals = _obs_vals(rows, source, checks, id_pos)
            if vals:
                con.executemany(insert_sql, vals)
            stats["obs"][source] = len(vals)
            src_con.close()
            dt = time.perf_counter() - t0
            stats["timings"][source] = dt
            print(f"{symbol} {source}: {len(vals)} rows in {dt:.3f}s", flush=True)

        # T-242 supplements: page-disjoint, so add only the pages the primary source supplied no row for
        dk = obs_cols.index("doc_key") if "doc_key" in obs_cols else None
        pg = obs_cols.index("page") if "page" in obs_cols else None
        reader_pos = obs_cols.index("reader") if "reader" in obs_cols else None
        for sup_key, sup_db, source, id_offset in SUPPLEMENTS:
            if not Path(sup_db).is_file():
                continue
            t0 = time.perf_counter()
            src_con = _ro(sup_db)
            rows = src_con.execute(
                f"SELECT {_select_list(sup_db, obs_cols)} FROM observation WHERE symbol=? "
                "AND status IN ('verified','unverified')",
                (symbol,)).fetchall()
            src_con.close()
            # drop this supplement's own rows from an earlier load, then keep the pages any db of the source supplied
            con.execute("DELETE FROM obs_fact WHERE symbol=? AND source=? AND observation_id>=?",
                        (symbol, source, id_offset))
            have = set(con.execute("SELECT doc_key, page FROM obs_fact WHERE symbol=? AND source=?",
                                   (symbol, source)).fetchall()) if dk is not None and pg is not None else set()
            rows = [r for r in rows if dk is None or pg is None or (r[dk], r[pg]) not in have]
            checks = load_checks(sup_db) if id_pos is not None else {}
            vals = _obs_vals(rows, source, checks, id_pos, id_offset=id_offset, reader_pos=reader_pos,
                             reader_mark=f" [{Path(sup_db).stem}]")
            if vals:
                con.executemany(insert_sql, vals)
            stats.setdefault("obs_db", {})[sup_key] = sup_db
            stats["obs"][sup_key] = len(vals)
            stats["timings"][sup_key] = time.perf_counter() - t0
            print(f"{symbol} {sup_key}: {len(vals)} rows in {stats['timings'][sup_key]:.3f}s", flush=True)

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
        table_cols = {c[1] for c in con.execute("PRAGMA table_info(filing_event)").fetchall()}
        ev_rows, ev_cols = [], []
        for ev_db in [*EVENTS_PRIORITY, EVENTS_DB]:
            if not Path(ev_db).is_file():
                continue
            ev_con = _ro(ev_db)
            ev_cols = [c[1] for c in ev_con.execute("PRAGMA table_info(event)").fetchall() if c[1] in table_cols]
            ev_rows = ev_con.execute(
                f"SELECT {','.join(ev_cols)} FROM event WHERE symbol=? AND status IN ('verified','unverified')",
                (symbol,)).fetchall()
            ev_con.close()
            if ev_rows:
                stats["events_db"] = ev_db
                break
        ev_rows, stats["events_ungated"] = _gate_event_rows(ev_cols, ev_rows)
        ev_placeholders = ",".join("?" * len(ev_cols))
        if ev_rows:
            con.executemany(f"INSERT INTO filing_event ({','.join(ev_cols)}) VALUES ({ev_placeholders})", ev_rows)
        stats["events"] = len(ev_rows)
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
