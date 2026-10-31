"""Rebuild the pilot stores so price.close is the traded close, check them, install, re-run the gate.

Steps stop at the first failure and leave the live stores as they were:
T1 into a scratch folder, compare, back up, swap market_state_pilot.db; fact store into a scratch
folder, compare, back up, swap; then the gate and the rule grade.  Log: .tmp/traded_close.log.
"""

from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
DATA = REPO / "reality_engine" / "data"
PILOT = DATA / "pilot" / "pilot60"
V4 = DATA / "pilot" / "v4"
SCRATCH = REPO / ".tmp" / "traded_close"
BACKUP = Path(r"D:\RealityEngine\backups\before_traded_close_20261031")
#: an atom may not lose more than this share of its rows; a larger loss stops the install
MAX_LOSS = 0.005


def log(text: str) -> None:
    print(f"{datetime.now():%H:%M:%S} {text}", flush=True)


def run(*args: str) -> None:
    log("run " + " ".join(args))
    env = dict(os.environ, REALITY_DATA_ROOT=str(DATA), PYTHONIOENCODING="utf-8")
    subprocess.run([sys.executable, *args], cwd=REPO, env=env, check=True)


def counts(path: Path, sql: str) -> dict:
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return dict(con.execute(sql).fetchall())
    finally:
        con.close()


def compare(old: dict, new: dict, what: str) -> None:
    lost = {key: (n, new.get(key, 0)) for key, n in old.items()
            if new.get(key, 0) < n * (1 - MAX_LOSS)}
    log(f"{what}: {sum(old.values()):,} -> {sum(new.values()):,} rows, "
        f"new keys {sorted(set(new) - set(old))[:10]}")
    if lost:
        raise SystemExit(f"{what}: rows lost, install stopped: {lost}")


def swap(new: Path, live: Path) -> None:
    BACKUP.mkdir(parents=True, exist_ok=True)
    shutil.copy2(live, BACKUP / live.name)
    os.replace(new, live)
    log(f"installed {live.name}, backup in {BACKUP}")


def main() -> int:
    t1 = SCRATCH / "t1"
    t1.mkdir(parents=True, exist_ok=True)
    run("-m", "reality_engine.pilot.build_t1", "--universe", "pilot", "--out", str(t1))
    per_table = ("SELECT name, (SELECT 1) FROM sqlite_master WHERE type='table'")
    old_tables, new_tables = counts(PILOT / "market_state_pilot.db", per_table), counts(t1 / "market_state_pilot.db", per_table)
    missing = set(old_tables) - set(new_tables)
    if missing:
        raise SystemExit(f"T1 tables missing, install stopped: {sorted(missing)}")
    daily = "SELECT 'rows', COUNT(*) FROM company_state_daily"
    compare(counts(PILOT / "market_state_pilot.db", daily), counts(t1 / "market_state_pilot.db", daily), "company_state_daily")
    swap(t1 / "market_state_pilot.db", PILOT / "market_state_pilot.db")

    fact = SCRATCH / "fact"
    fact.mkdir(parents=True, exist_ok=True)
    for name in ("quarters_pilot60.db", "shp_xbrl_pilot.db"):
        shutil.copy2(V4 / name, fact / name)
    run("-m", "reality_engine.query.v4.build_membership", "--root", str(DATA),
        "--out", str(fact / "fact_v4_pilot.db"))
    per_atom = "SELECT atom, COUNT(*) FROM fact GROUP BY atom"
    compare(counts(V4 / "fact_v4_pilot.db", per_atom), counts(fact / "fact_v4_pilot.db", per_atom), "fact")
    close = counts(fact / "fact_v4_pilot.db",
                   "SELECT period_end, value FROM fact WHERE atom='price.close' "
                   "AND entity_id='INE752E01010' AND period_end='2023-09-11'")
    if close.get("2023-09-11") != 264.5:
        raise SystemExit(f"POWERGRID 2023-09-11 close should be 264.5, got {close}")
    log("POWERGRID 2023-09-11 close 264.5, the traded close")
    swap(fact / "fact_v4_pilot.db", V4 / "fact_v4_pilot.db")

    run("tasks/pilot60/gate_run.py", "v4", "--fresh")
    run("tasks/pilot60/gate_run.py", "v4truth", "--panel-seed", "20261035")
    log("DONE")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
