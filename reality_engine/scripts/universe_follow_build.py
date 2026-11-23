"""T-241: build each universe company's store as soon as its filings are fetched, while the fetch still runs.

    python -m reality_engine.scripts.universe_follow_build --root D:/RealityEngine/tg_build/universe_fy27 \\
        --shards 2 --batch 5 --window-start 2026-04-01

The fetch (``fetch_pilot60_history --fetch --order company``) writes one row per listed filing into its manifest
database, ``pending`` until downloaded. A company is ready when every row of its ISIN dated on or after
``--window-start`` has left ``pending`` (ok, error, skipped or no_file) and at least one row is ``ok``. Every
``--poll`` seconds the driver rewrites ``<root>/manifest.csv`` (status ``ok`` rows of ready companies only) and
hands each idle shard the next ``--batch`` ready, unbuilt queue positions of ``<root>/universe_fy27.csv`` as one
``tg_measure_build --only`` run (its own ``--out-csv``/log per shard). A company with a ``cNN_measure.json`` is
built; ``tg_measure_build`` skips it anyway. The driver stops when no row is pending, nothing is left to build and
every shard is idle; ``<root>/follow_status.log`` records each batch and the final counts.
"""
from __future__ import annotations

import argparse
import csv
import os
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.scripts.fetch_pilot60_history import CSV_FIELDS, MANIFEST_DB  # noqa: E402
from reality_engine.scripts.tg_measure_build import company_name  # noqa: E402

CREATE_NO_WINDOW = 0x08000000


def log(root: Path, text: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    with (root / "follow_status.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def readiness(db: Path, isins: set[str], window_start: str) -> tuple[set[str], int, list[dict]]:
    """(ready ISINs, pending rows in the universe, ok rows of ready ISINs) from the fetch manifest, read-only."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=120)
    try:
        cur = con.execute(f"SELECT {','.join(CSV_FIELDS)} FROM docs WHERE dissem_ts >= ?", (window_start,))
        pending: dict[str, int] = {}
        ok: dict[str, list[dict]] = {}
        for values in cur:
            row = dict(zip(CSV_FIELDS, values))
            isin = row["isin"]
            if isin not in isins:
                continue
            if row["status"] == "pending":
                pending[isin] = pending.get(isin, 0) + 1
            elif row["status"] == "ok":
                ok.setdefault(isin, []).append(row)
    finally:
        con.close()
    ready = {i for i in ok if i not in pending}
    rows = [r for i in ready for r in ok[i]]
    return ready, sum(pending.values()), rows


def write_manifest(path: Path, rows: list[dict]) -> None:
    rows = sorted(rows, key=lambda r: (r["symbol_at_time"] or "", r["dissem_ts"] or "", r["newsid"]))
    tmp = path.with_suffix(".csv.part")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--universe", default=None, help="default <root>/universe_fy27.csv (isin, symbol columns)")
    ap.add_argument("--manifest-db", default=str(MANIFEST_DB))
    ap.add_argument("--window-start", default="2026-04-01")
    ap.add_argument("--shards", type=int, default=2)
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--poll", type=float, default=120.0)
    ap.add_argument("--once", action="store_true", help="one pass: launch what is ready, wait, exit")
    args = ap.parse_args(argv)
    root = Path(args.root)
    universe = Path(args.universe) if args.universe else root / "universe_fy27.csv"
    with universe.open(encoding="utf-8", newline="") as fh:
        queue = [r for r in csv.DictReader(fh) if str(r.get("symbol") or "").strip()]
    pos_by_isin = {str(r["isin"]).strip().upper(): i for i, r in enumerate(queue, start=1)}
    manifest = root / "manifest.csv"
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.setdefault("REALITY_DATA_ROOT", str(REPO / "reality_engine" / "data"))
    running: dict[int, tuple[subprocess.Popen, list[int]]] = {}
    claimed: set[int] = set()
    log(root, f"start: {len(queue)} companies, {args.shards} shards, batch {args.batch}")
    while True:
        for shard, (proc, batch) in list(running.items()):
            if proc.poll() is not None:
                log(root, f"shard {shard} rc={proc.returncode} batch {','.join(map(str, batch))}")
                del running[shard]
        free = [s for s in range(1, args.shards + 1) if s not in running]
        if not free:
            time.sleep(30)
            continue
        ready, pending_rows, ok_rows = readiness(Path(args.manifest_db), set(pos_by_isin), args.window_start)
        todo = sorted(pos_by_isin[i] for i in ready
                      if pos_by_isin[i] not in claimed
                      and not (root / company_name(pos_by_isin[i], None)
                               / f"{company_name(pos_by_isin[i], None)}_measure.json").is_file())
        if todo:
            write_manifest(manifest, ok_rows)
        for shard in free:
            batch, todo = todo[:args.batch], todo[args.batch:]
            if not batch:
                break
            claimed.update(batch)
            cmd = [sys.executable, "-m", "reality_engine.scripts.tg_measure_build", "--root", str(root),
                   "--universe", str(universe), "--manifest", str(manifest), "--only", ",".join(map(str, batch)),
                   "--accept-copy", "", "--window-start", args.window_start,
                   "--out-csv", str(root / f"measure_s{shard}.csv")]
            out = (root / f"build_s{shard}.log").open("a", encoding="utf-8")
            running[shard] = (subprocess.Popen(cmd, cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT,
                                               creationflags=CREATE_NO_WINDOW), batch)
            log(root, f"shard {shard} start batch {','.join(map(str, batch))} (ready {len(ready)}, "
                      f"claimed {len(claimed)}, pending rows {pending_rows})")
        if not running and (args.once or (pending_rows == 0 and not todo)):
            log(root, f"done: ready {len(ready)}, claimed {len(claimed)}, pending rows {pending_rows}")
            return 0
        time.sleep(30 if running else args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
