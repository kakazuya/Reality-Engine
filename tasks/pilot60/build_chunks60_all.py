"""Sharded build of the pilot-60 T2 chunk store, then one merged store.

    python tasks/pilot60/build_chunks60_all.py [--shards 6]

The reviewed builder is single-threaded (~10 s per annual report), so the T2 ISINs
are split across N processes writing separate stores; they are merged afterwards into
``.tmp/pilot60/chunks_v3_pilot.db`` with chunk ids remapped (doc ids are content
hashes, so they never collide).  The merged FTS index is filled by the chunk triggers.

Writes per-shard logs and coverage under ``.tmp/pilot60/``; the merged
``tasks/pilot60/coverage.json`` + ``chunks_build.json`` are summed.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
OUT = REPO / "tasks" / "pilot60"
T2 = OUT / "T2_ISINS.txt"
WORK = REPO / ".tmp" / "pilot60"
FINAL = WORK / "chunks_v3_pilot.db"
REMAPPED = ("chunk", "chunk_tag", "chunk_entity")
PLAIN = ("tag_vocab", "coverage_scorecard", "build_run", "chunk_vec_ref", "result_note")


def split(isins: list[str], shards: int) -> list[list[str]]:
    return [isins[i::shards] for i in range(shards)]


def columns(con: sqlite3.Connection, table: str) -> list[str]:
    return [r[1] for r in con.execute(f"PRAGMA table_info({table})")]


def merge(shard_dbs: list[Path]) -> dict:
    """Shard 0 is the base file; every other shard is copied in with chunk-id offsets.

    The same original can reach two shards (a registry row filed under two ISINs);
    its chunks are copied once, keyed by doc_id.
    """
    if FINAL.exists():
        FINAL.unlink()
    FINAL.parent.mkdir(parents=True, exist_ok=True)
    for suffix in ("-wal", "-shm"):
        side = Path(str(FINAL) + suffix)
        if side.exists():
            side.unlink()
    shutil.copyfile(shard_dbs[0], FINAL)
    con = sqlite3.connect(FINAL)
    con.execute("PRAGMA journal_mode=WAL")
    for i, shard in enumerate(shard_dbs):
        if i:
            con.execute("ATTACH DATABASE ? AS s", (str(shard),))
            con.execute("DROP TABLE IF EXISTS temp.new_docs")
            con.execute("CREATE TEMP TABLE new_docs AS SELECT doc_id FROM s.doc "
                        "EXCEPT SELECT doc_id FROM main.doc")
            con.execute("INSERT OR IGNORE INTO main.doc SELECT * FROM s.doc "
                        "WHERE doc_id IN (SELECT doc_id FROM temp.new_docs)")
            offset = con.execute("SELECT COALESCE(MAX(chunk_id), 0) FROM chunk").fetchone()[0]
            cols = columns(con, "chunk")
            select = ", ".join(f"chunk_id+{offset}" if c == "chunk_id" else c for c in cols)
            con.execute(f"INSERT INTO main.chunk ({', '.join(cols)}) SELECT {select} "
                        f"FROM s.chunk WHERE doc_id IN (SELECT doc_id FROM temp.new_docs)")
            for table in ("chunk_tag", "chunk_entity"):
                cols = columns(con, table)
                select = ", ".join(f"t.chunk_id+{offset}" if c == "chunk_id" else f"t.{c}"
                                   for c in cols)
                con.execute(f"INSERT INTO main.{table} ({', '.join(cols)}) "
                            f"SELECT {select} FROM s.{table} t JOIN s.chunk c "
                            f"ON c.chunk_id = t.chunk_id "
                            f"WHERE c.doc_id IN (SELECT doc_id FROM temp.new_docs)")
            for table in PLAIN:
                try:
                    con.execute(f"INSERT OR IGNORE INTO main.{table} SELECT * FROM s.{table}")
                except sqlite3.OperationalError:
                    pass
            con.commit()
            con.execute("DROP TABLE IF EXISTS temp.new_docs")
            con.execute("DETACH DATABASE s")
        con.commit()
    counts = {"docs": con.execute("SELECT COUNT(*) FROM doc").fetchone()[0],
              "chunks": con.execute("SELECT COUNT(*) FROM chunk").fetchone()[0],
              "tags": con.execute("SELECT COUNT(*) FROM chunk_tag").fetchone()[0],
              "fts_rows": con.execute("SELECT COUNT(*) FROM chunk_fts").fetchone()[0],
              "shards": len(shard_dbs)}
    # one build_run row summarising the sharded build
    con.execute("INSERT INTO build_run (run_id, started_at, ended_at, doc_type, docs_in, "
                "docs_ok, docs_failed, chunks_out, tags_out, notes) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)",
                (time.strftime("pilot60-sharded-%Y%m%d-%H%M%S"),
                 time.strftime("%Y-%m-%dT%H:%M:%S"), time.strftime("%Y-%m-%dT%H:%M:%S"),
                 "all", counts["docs"], counts["docs"], 0, counts["chunks"], counts["tags"],
                 json.dumps({"shards": len(shard_dbs)})))
    con.commit()
    con.close()
    return counts


def merge_reports(shard_dirs: list[Path]) -> None:
    coverage = {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "cutoff": "2024-04-01",
                "by_isin": {}, "totals": {}}
    build = {"docs": 0, "chunks": 0, "by_type": {}, "docs_no_file": 0, "elapsed_s": 0,
             "db_bytes": 0}
    for shard_dir in shard_dirs:
        cov = shard_dir / "coverage.json"
        if cov.is_file():
            data = json.loads(cov.read_text(encoding="utf-8"))
            coverage["by_isin"].update(data.get("by_isin") or {})
            for dt, tot in (data.get("totals") or {}).items():
                agg = coverage["totals"].setdefault(dt, {"expected": 0, "found": 0})
                agg["expected"] += tot["expected"]
                agg["found"] += tot["found"]
        stats = shard_dir / "chunks_build.json"
        if stats.is_file():
            data = json.loads(stats.read_text(encoding="utf-8"))
            for key in ("docs", "chunks", "docs_no_file", "known_at_mismatches"):
                build[key] = build.get(key, 0) + int(data.get(key) or 0)
            build["elapsed_s"] = max(build["elapsed_s"], float(data.get("elapsed_s") or 0))
            for dt, n in (data.get("by_type") or {}).items():
                build["by_type"][dt] = build["by_type"].get(dt, 0) + n
    if FINAL.is_file():
        build["db_bytes"] = FINAL.stat().st_size
    (OUT / "coverage.json").write_text(json.dumps(coverage, indent=1), encoding="utf-8")
    (OUT / "chunks_build.json").write_text(json.dumps(build, indent=1), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shards", type=int, default=max(2, min(6, (os.cpu_count() or 4) // 2)))
    args = ap.parse_args(argv)
    isins = [x.strip() for x in T2.read_text(encoding="utf-8").splitlines() if x.strip()]
    WORK.mkdir(parents=True, exist_ok=True)
    shards = split(isins, args.shards)
    procs, dbs, dirs = [], [], []
    started = time.perf_counter()
    for i, shard in enumerate(shards):
        isin_file = WORK / f"shard_{i}.isins"
        isin_file.write_text("\n".join(shard) + "\n", encoding="utf-8")
        out_dir = OUT / f"shard_{i}"
        out_dir.mkdir(parents=True, exist_ok=True)
        db = WORK / f"shard_{i}.db"
        for path in (db, Path(str(db) + "-wal"), Path(str(db) + "-shm")):
            if path.exists():
                path.unlink()
        env = dict(os.environ, REALITY_CHUNKS_V3=str(db),
                   REALITY_T2_ISINS_FILE=str(isin_file), REALITY_PILOT60_OUT=str(out_dir))
        log = (WORK / f"shard_{i}.log").open("w", encoding="utf-8")
        procs.append(subprocess.Popen([sys.executable, str(OUT / "build_chunks60.py")],
                                      env=env, stdout=log, stderr=subprocess.STDOUT,
                                      cwd=str(REPO)))
        dbs.append(db)
        dirs.append(out_dir)
        print(f"shard {i}: {len(shard)} ISINs -> {db.name}")
    failed = []
    for i, proc in enumerate(procs):
        code = proc.wait()
        print(f"shard {i}: exit {code}")
        if code:
            failed.append(i)
    if failed:
        print(f"shards failed: {failed}; see .tmp/pilot60/shard_<i>.log")
        return 1
    counts = merge(dbs)
    merge_reports(dirs)
    print(f"merged in {time.perf_counter() - started:.0f}s: {counts} -> {FINAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
