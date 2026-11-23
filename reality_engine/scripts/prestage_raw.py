"""T-241 (Shivam 24 Nov: the HDD only stores raw documents; operations run on the C: SSD): move a company's raw
folders from D: to the SSD just before its store is built, and junction them back, so every stored path
(``D:/RealityEngine/raw/pilot60_history/<SYM>/<bucket>/<id>.pdf``) still works while the build's many small random
reads hit the SSD. The HDD then sees one sequential copy per company instead of thousands of seeks.

    python -m reality_engine.scripts.prestage_raw --symbols ABB,TCS
    python -m reality_engine.scripts.prestage_raw --root C:/RealityEngine/tg_build/full394 \\
        --universe C:/RealityEngine/tg_build/full394/universe394.csv --ahead 2 --loop

Per ``<SYM>/<bucket>`` folder that is a real directory on D:, robocopy ``/MOVE`` copies it to
``--stage-root/<SYM>/<bucket>`` and, only when nothing is left behind (an open file stays on D:), the empty D: folder
is replaced by a junction. A folder that is already a junction is skipped. ``--loop`` watches a ``tg_measure_build``
root: for every company being built now (a ``cNN`` folder without its measure json) the next ``--ahead`` unbuilt
queue positions are staged; the shards' order is read from those in-progress folders, so no shard list is needed.
``universe_to_drive --delete`` later removes the files through the same paths, emptying the SSD copy.
"""
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.config import RAW_ROOT  # noqa: E402

CREATE_NO_WINDOW = 0x08000000
RAW = RAW_ROOT / "pilot60_history"
STAGE = Path("C:/RealityEngine/stage/pilot60_history")


def say(text: str) -> None:
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {text}", flush=True)


def stage_symbol(symbol: str, raw: Path = RAW, stage: Path = STAGE, min_free_gb: float = 40.0) -> int:
    """Move every real ``raw/<SYM>/<bucket>`` folder to ``stage`` and junction it back; returns folders moved."""
    import _winapi
    import shutil

    top = raw / symbol
    if not top.is_dir():
        return 0
    moved = 0
    for bucket in sorted(p for p in top.iterdir() if p.is_dir()):
        if os.path.isjunction(bucket):
            continue
        if shutil.disk_usage(stage.anchor or "C:/").free < min_free_gb * 1024 ** 3:
            say(f"{symbol}: SSD under {min_free_gb:g} GB free, left on D:")
            return moved
        dst = stage / symbol / bucket.name
        dst.mkdir(parents=True, exist_ok=True)
        rc = subprocess.run(["robocopy", str(bucket), str(dst), "/E", "/MOVE", "/R:1", "/W:2", "/NP", "/NFL", "/NDL",
                             "/NJH", "/NJS"], capture_output=True, creationflags=CREATE_NO_WINDOW).returncode
        left = [p for p in bucket.rglob("*") if p.is_file()] if bucket.exists() else []
        if rc >= 8 or left:
            say(f"{symbol}/{bucket.name}: robocopy rc={rc}, {len(left)} files still on D: (open?); no junction")
            continue
        if bucket.exists():
            shutil.rmtree(bucket)
        _winapi.CreateJunction(str(dst), str(bucket))
        moved += 1
    return moved


def queue(universe: Path) -> list[str]:
    with universe.open(encoding="utf-8", newline="") as fh:
        return [str(r["symbol"]).strip().upper() for r in csv.DictReader(fh) if str(r.get("symbol") or "").strip()]


def next_positions(root: Path, n_queue: int, ahead: int) -> list[int]:
    """The next ``ahead`` unbuilt positions after each company being built now."""
    def built(pos: int) -> bool:
        name = f"c{pos:02d}"
        return (root / name / f"{name}_measure.json").is_file()

    busy = sorted(int(d.name[1:]) for d in root.iterdir()
                  if d.is_dir() and d.name[:1] == "c" and d.name[1:].isdigit()
                  and not (d / f"{d.name}_measure.json").is_file())
    out: list[int] = []
    for pos in busy:
        nxt, got = pos + 1, 0
        while nxt <= n_queue and got < ahead:
            if not built(nxt) and nxt not in busy:
                out.append(nxt)
                got += 1
            nxt += 1
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--symbols", default="")
    ap.add_argument("--root", default=None)
    ap.add_argument("--universe", default=None)
    ap.add_argument("--ahead", type=int, default=2)
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--poll", type=float, default=60.0)
    ap.add_argument("--stage-root", default=str(STAGE))
    ap.add_argument("--min-free-gb", type=float, default=40.0)
    args = ap.parse_args(argv)
    stage = Path(args.stage_root)
    for sym in [s.strip().upper() for s in args.symbols.split(",") if s.strip()]:
        say(f"{sym}: {stage_symbol(sym, stage=stage, min_free_gb=args.min_free_gb)} folders staged")
    if not args.root:
        return 0
    root = Path(args.root)
    syms = queue(Path(args.universe) if args.universe else root / "universe394.csv")
    done: set[int] = set()
    while True:
        for pos in next_positions(root, len(syms), args.ahead):
            if pos in done:
                continue
            n = stage_symbol(syms[pos - 1], stage=stage, min_free_gb=args.min_free_gb)
            say(f"c{pos:02d} {syms[pos - 1]}: {n} folders staged")
            done.add(pos)
        if not args.loop:
            return 0
        time.sleep(args.poll)


if __name__ == "__main__":
    raise SystemExit(main())
