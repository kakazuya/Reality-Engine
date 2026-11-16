"""T-214: OCR the Telegram build's needs_ocr pages on the HP (Microsoft TextRecognizer), store by store.

Shivam 16 Nov night: the HP is lent until 06:00 IST.  For every built store ``<root>/cNN`` (one that has
``routes.csv``) and no ``ocr/ocr_textrec.db`` yet, in queue order:

1. seed ``cNN/ocr/ocr_<SYM>.db`` with an empty ``ocr_page`` row for each page ``routes.csv`` sent to
   ``needs_ocr`` (no text layer, or a jumbled one), so ``hp_ocr plan`` re-reads those pages as well as the ones
   ``ocr.pending()`` reports (doc_page method ``needs_ocr``);
2. ``hp_ocr plan`` (copies only those PDFs to the HP), ``run``, ``fetch`` into ``cNN/ocr/ocr_textrec.db``;
3. delete the local stage copy.

Stores the build has not reached yet are picked up as they appear; the loop stops at ``--until`` (HH:MM, local
time) and then runs ``hp_ocr cleanup`` (tasks and copied PDFs; the installed package stays as it was found).
Merging the OCR text into each ``pages.db`` is a later, separate repair step (rule of T-208 step 3).

    python -m reality_engine.scripts.tg_hp_ocr_night --root D:/RealityEngine/tg_build/measure10 --until 05:40
"""
from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

SEED_SCHEMA = """
CREATE TABLE IF NOT EXISTS ocr_page (
  symbol TEXT NOT NULL, doc_key TEXT NOT NULL, page INTEGER NOT NULL, doc_type TEXT, known_at TEXT,
  text TEXT NOT NULL, words_json TEXT NOT NULL, ocr_conf REAL, n_boxes INTEGER, dpi INTEGER,
  seconds REAL, method TEXT NOT NULL DEFAULT 'ocr_rapid',
  PRIMARY KEY (symbol, doc_key, page)
);
"""


def log(msg: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {msg}", flush=True)


def store_symbol(store: Path) -> str | None:
    profile = store / f"{store.name}_profile.json"
    if not profile.is_file():
        return None
    companies = json.loads(profile.read_text(encoding="utf-8")).get("companies") or []
    return companies[0]["symbol"] if companies else None


def write_seed(store: Path, symbol: str) -> tuple[Path, int]:
    """``ocr_<SYM>.db`` with one empty row per routes.csv ``needs_ocr`` page."""
    seed = store / "ocr" / f"ocr_{symbol}.db"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.unlink(missing_ok=True)
    rows = []
    with (store / "routes.csv").open(newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            if r["route"] == "needs_ocr":
                rows.append((symbol, r["doc_key"], int(r["page"]), r.get("doc_type") or None, None, "", "[]",
                             None, 0, 0, 0.0, "seed_route"))
    con = sqlite3.connect(seed)
    with con:
        con.executescript(SEED_SCHEMA)
        con.executemany("INSERT OR IGNORE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
    con.close()
    return seed, len(rows)


def hp(args: list[str], timeout: int) -> tuple[int, str]:
    cmd = [sys.executable, "-m", "reality_engine.pilot3.hp_ocr", *args]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired:
        return 124, "timeout"
    return done.returncode, (done.stdout + done.stderr)[-1500:]


def ocr_store(store: Path, symbol: str, run_timeout: int) -> dict:
    t0 = time.perf_counter()
    seed, seeded = write_seed(store, symbol)
    out_dir = store / "ocr"
    stage = out_dir / "hp_stage"
    plan = out_dir / "hp_plan.jsonl"
    rc, tail = hp(["plan", "--symbols", symbol, "--input-db", str(seed), "--pages-db", str(store / "pages.db"),
                   "--plan-out", str(plan), "--stage", str(stage)], 3600)
    result = {"store": store.name, "symbol": symbol, "seeded": seeded}
    if rc != 0:
        return {**result, "step": "plan", "rc": rc, "tail": tail}
    pages = sum(1 for _ in plan.open(encoding="utf-8")) if plan.is_file() else 0
    result["pages"] = pages
    if pages == 0:
        (out_dir / "ocr_textrec.db").touch()
        return {**result, "step": "done", "rc": 0, "seconds": round(time.perf_counter() - t0, 1)}
    rc, tail = hp(["run", "--fresh", "--timeout", str(run_timeout)], run_timeout + 120)
    if rc != 0:
        return {**result, "step": "run", "rc": rc, "tail": tail}
    rc, tail = hp(["fetch", "--plan-out", str(plan), "--gz", str(out_dir / "ocr_pages.jsonl.gz"),
                   "--out", str(out_dir / "ocr_textrec.db")], 1800)
    shutil.rmtree(stage, ignore_errors=True)
    if rc != 0:
        return {**result, "step": "fetch", "rc": rc, "tail": tail}
    con = sqlite3.connect(f"file:{out_dir / 'ocr_textrec.db'}?mode=ro", uri=True)
    n, errors = con.execute("SELECT COUNT(*), SUM(error IS NOT NULL AND error != '') FROM ocr_page").fetchone()
    con.close()
    return {**result, "step": "done", "rc": 0, "ocr_rows": n, "errors": errors or 0,
            "seconds": round(time.perf_counter() - t0, 1)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True)
    ap.add_argument("--until", default="05:40", help="local HH:MM to stop starting new stores")
    ap.add_argument("--run-timeout", type=int, default=3600)
    ap.add_argument("--poll", type=int, default=120, help="seconds between looks for newly built stores")
    args = ap.parse_args(argv)
    root = Path(args.root)
    stop_h, stop_m = map(int, args.until.split(":"))
    ledger = root / "hp_ocr_night.jsonl"
    failed: set[str] = set()
    attempts: dict[str, int] = {}

    def past_stop() -> bool:
        now = datetime.now()
        return (now.hour, now.minute) >= (stop_h, stop_m) and now.hour < 12

    while not past_stop():
        todo = [s for s in sorted(root.glob("c[0-9][0-9]"))
                if (s / "routes.csv").is_file() and not (s / "ocr" / "ocr_textrec.db").is_file()
                and s.name not in failed]
        if not todo:
            time.sleep(args.poll)
            continue
        store = todo[0]
        symbol = store_symbol(store)
        if not symbol:
            failed.add(store.name)
            continue
        log(f"{store.name} {symbol}: start")
        result = ocr_store(store, symbol, args.run_timeout)
        result["at"] = datetime.now().isoformat(timespec="seconds")
        with ledger.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(result) + "\n")
        log(f"{store.name} {symbol}: {result}")
        if result["step"] != "done":
            attempts[store.name] = attempts.get(store.name, 0) + 1
            if attempts[store.name] >= 3:       # a transient HP state (the lock probe once answered -1) gets
                failed.add(store.name)          # two more tries after a pause; a third failure skips the store
            else:
                time.sleep(args.poll)
    log("stop time reached; cleanup on the HP")
    rc, tail = hp(["cleanup"], 600)
    log(f"cleanup rc={rc} {tail[-300:]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
