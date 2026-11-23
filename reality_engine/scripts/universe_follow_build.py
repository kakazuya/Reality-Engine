"""T-241: build each universe company's store as soon as its filings are fetched, while the fetch still runs.

    python -m reality_engine.scripts.universe_follow_build --root D:/RealityEngine/tg_build/universe_fy27 \\
        --shards 2 --batch 5 --window-start 2026-04-01

The fetch (``fetch_pilot60_history --fetch --order company``) writes one row per listed filing into its manifest
database, ``pending`` until downloaded. A company is ready when every row of its ISIN dated on or after
``--window-start`` has left ``pending`` (ok, error, skipped or no_file) and at least one row is ``ok``. Every
``--poll`` seconds it hands each idle shard the next ``--batch`` ready, unbuilt queue positions of
``<root>/universe_fy27.csv`` as one ``tg_measure_build --only`` run, with that batch's own manifest
(``<root>/manifests/batch_NNNNN_tK.csv``, status ``ok`` rows only) and its own ``<root>/shard_N/measure.csv``. A
company with a ``cNN_measure.json`` is built (its ``failed`` field is logged as FAILED PARTS); one left without a
json is relaunched up to ``--tries`` times, then given up. A STALL line is logged when pending rows stop moving
(fetch dead?). The driver stops when the universe has rows, none is pending, nothing is left to build and every
shard is idle; ``<root>/follow_status.log`` records each batch and the final counts (built, failed parts, given
up, never ready).
"""
from __future__ import annotations

import argparse
import csv
import json
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
from reality_engine.scripts.prestage_raw import stage_symbol  # noqa: E402
from reality_engine.scripts.tg_measure_build import company_name  # noqa: E402

CREATE_NO_WINDOW = 0x08000000


def log(root: Path, text: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}"
    print(line, flush=True)
    with (root / "follow_status.log").open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def readiness(db: Path, isins: set[str], window_start: str) -> tuple[set[str], int, int, dict[str, list[dict]]]:
    """(ready ISINs, pending rows, universe rows, ok rows by ISIN) from the fetch manifest db, read-only."""
    con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=120)
    try:
        cur = con.execute(f"SELECT {','.join(CSV_FIELDS)} FROM docs WHERE dissem_ts >= ?", (window_start,))
        pending: dict[str, int] = {}
        ok: dict[str, list[dict]] = {}
        total = 0
        for values in cur:
            row = dict(zip(CSV_FIELDS, values))
            isin = str(row["isin"] or "").upper()
            if isin not in isins:
                continue
            total += 1
            if row["status"] == "pending":
                pending[isin] = pending.get(isin, 0) + 1
            elif row["status"] == "ok":
                ok.setdefault(isin, []).append(row)
    finally:
        con.close()
    ready = {i for i in ok if i not in pending}
    return ready, sum(pending.values()), total, ok


def write_manifest(path: Path, rows: list[dict]) -> None:
    """One batch's own manifest (never rewritten while a shard reads it)."""
    rows = sorted(rows, key=lambda r: (r["symbol_at_time"] or "", r["dissem_ts"] or "", r["newsid"]))
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".csv.part")
    with tmp.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, path)


def measure_of(root: Path, pos: int) -> dict | None:
    name = company_name(pos, None)
    path = root / name / f"{name}_measure.json"
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        return {"failed": "unreadable measure json"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--universe", default=None, help="default <root>/universe_fy27.csv (isin, symbol columns)")
    ap.add_argument("--manifest-db", default=str(MANIFEST_DB))
    ap.add_argument("--window-start", default="2026-04-01")
    ap.add_argument("--shards", type=int, default=2)
    ap.add_argument("--batch", type=int, default=5)
    ap.add_argument("--poll", type=float, default=120.0)
    ap.add_argument("--tries", type=int, default=2, help="launches per company before it is given up")
    ap.add_argument("--min-free-gb", type=float, default=20.0, help="passed to tg_measure_build")
    ap.add_argument("--stall-minutes", type=float, default=60.0,
                    help="log a STALL line when pending rows have not moved for this long")
    ap.add_argument("--once", action="store_true", help="one pass: launch what is ready, wait, exit")
    args = ap.parse_args(argv)
    root = Path(args.root)
    universe = Path(args.universe) if args.universe else root / "universe_fy27.csv"
    with universe.open(encoding="utf-8", newline="") as fh:
        queue = [r for r in csv.DictReader(fh) if str(r.get("symbol") or "").strip()]
    pos_by_isin = {str(r["isin"]).strip().upper(): i for i, r in enumerate(queue, start=1)}
    isin_by_pos = {v: k for k, v in pos_by_isin.items()}
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    env.setdefault("REALITY_DATA_ROOT", str(REPO / "reality_engine" / "data"))
    running: dict[int, tuple[subprocess.Popen, list[int]]] = {}
    tries: dict[int, int] = {}
    given_up: set[int] = set()
    failed_built: set[int] = set()
    last_pending, last_move = -1, time.monotonic()
    log(root, f"start: {len(queue)} companies, {args.shards} shards, batch {args.batch}, "
              f"manifest db {args.manifest_db}")
    while True:
        for shard, (proc, batch) in list(running.items()):
            if proc.poll() is None:
                continue
            del running[shard]
            missing = [pos for pos in batch if measure_of(root, pos) is None]
            bad = [pos for pos in batch if (measure_of(root, pos) or {}).get("failed")]
            failed_built.update(bad)
            for pos in missing:
                if tries.get(pos, 0) >= args.tries:
                    given_up.add(pos)
            log(root, f"shard {shard} rc={proc.returncode} batch {','.join(map(str, batch))}"
                      + (f" NOT BUILT {','.join(map(str, missing))}" if missing else "")
                      + (f" FAILED PARTS {','.join(map(str, bad))}" if bad else ""))
        free = [s for s in range(1, args.shards + 1) if s not in running]
        if not free:
            time.sleep(30)
            continue
        ready, pending_rows, total_rows, ok = readiness(Path(args.manifest_db), set(pos_by_isin), args.window_start)
        if pending_rows != last_pending:
            last_pending, last_move = pending_rows, time.monotonic()
        elif pending_rows and time.monotonic() - last_move > args.stall_minutes * 60:
            log(root, f"STALL: {pending_rows} pending rows unchanged for {args.stall_minutes:g} min; "
                      "is the fetch alive?")
            last_move = time.monotonic()
        busy = {pos for _, batch in running.values() for pos in batch}
        # a cNN folder touched in the last hour with no measure json is a build a previous driver left running
        cutoff = time.time() - 3600
        for d in root.glob("c*"):
            if d.name[1:].isdigit() and not (d / f"{d.name}_measure.json").is_file() and d.stat().st_mtime > cutoff:
                busy.add(int(d.name[1:]))
        todo = sorted(pos_by_isin[i] for i in ready
                      if pos_by_isin[i] not in busy and pos_by_isin[i] not in given_up
                      and measure_of(root, pos_by_isin[i]) is None)
        for shard in free:
            batch, todo = todo[:args.batch], todo[args.batch:]
            if not batch:
                break
            for pos in batch:
                tries[pos] = tries.get(pos, 0) + 1
            for pos in batch:   # T-241: raw folders onto the SSD before the build reads them (one HDD copy, no seeks)
                try:
                    stage_symbol(str(queue[pos - 1]["symbol"]).strip().upper())
                except OSError as exc:
                    log(root, f"prestage {queue[pos - 1]['symbol']}: {exc} (built from D:)")
            manifest = root / "manifests" / f"batch_{batch[0]:05d}_t{tries[batch[0]]}.csv"
            write_manifest(manifest, [r for pos in batch for r in ok[isin_by_pos[pos]]])
            out_dir = root / f"shard_{shard}"
            out_dir.mkdir(exist_ok=True)
            cmd = [sys.executable, "-m", "reality_engine.scripts.tg_measure_build", "--root", str(root),
                   "--universe", str(universe), "--manifest", str(manifest), "--only", ",".join(map(str, batch)),
                   "--accept-copy", "", "--window-start", args.window_start,
                   "--min-free-gb", f"{args.min_free_gb:g}", "--out-csv", str(out_dir / "measure.csv")]
            out = (root / f"build_s{shard}.log").open("a", encoding="utf-8")
            running[shard] = (subprocess.Popen(cmd, cwd=REPO, env=env, stdout=out, stderr=subprocess.STDOUT,
                                               creationflags=CREATE_NO_WINDOW), batch)
            log(root, f"shard {shard} start batch {','.join(map(str, batch))} (ready {len(ready)}, "
                      f"pending rows {pending_rows})")
        if not running and (args.once or (total_rows and pending_rows == 0 and not todo)):
            never = len(pos_by_isin) - len(ready)
            built = sum(1 for pos in pos_by_isin.values() if measure_of(root, pos) is not None)
            log(root, f"done: built {built}, with failed parts {len(failed_built)}, given up {len(given_up)}, "
                      f"never ready (no ok filing or still pending) {never}, pending rows {pending_rows}")
            return 0
        time.sleep(30 if running else args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
