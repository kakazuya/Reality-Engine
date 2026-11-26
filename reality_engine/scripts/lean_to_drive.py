"""T-245 (Shivam 26 Nov 2026): move data-heavy folders off the MSI to Drive so the laptop stays a lean cloud box.

For each planned item: ``rclone copy --checksum`` to ``gdrive:InfoDiffusion_archive/lean_2026-11-26/<dest>``, then
``rclone check --one-way --checksum`` (every local file present on Drive with the same hash), and only then delete the
local copy (Python, never a shell rm). A path on the keep list (``C:/RealityEngine/t242/T-245_keep_local.txt`` plus
``KEEP`` below) is never copied or deleted. Default is a dry run that prints the plan with sizes; ``--go`` executes.
Anything written in the last 24 h is skipped (it may be in use). Every step is logged as JSON lines to ``C:/RealityEngine/t242/T-245_lean.log``.

Raw document folders go through ``reality_engine.scripts.raw_to_drive`` instead (md5 dedupe against the whole archive,
the msi_raw layout raw_store reads from, never deletes a database).

    python -m reality_engine.scripts.lean_to_drive            # plan
    python -m reality_engine.scripts.lean_to_drive --go       # copy, verify, delete
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

DEST_ROOT = "gdrive:InfoDiffusion_archive/lean_2026-11-26"
LOG = Path("C:/RealityEngine/t242/T-245_lean.log")
KEEP_FILE = Path("C:/RealityEngine/t242/T-245_keep_local.txt")
# live stores the reality-data tools serve (D:/RealityEngine/stores.json) and loader sources: never moved
KEEP = [
    "C:/RealityEngine/tg_build/universe_fy27", "C:/RealityEngine/tg_build/full394", "C:/RealityEngine/tg_build/measure10",
    "D:/RealityEngine/tg_build/measure10", "D:/RealityEngine/hy4_out/obs_", "D:/RealityEngine/checks",
    "C:/RealityEngine/t230/obs_91_j.db", "C:/RealityEngine/t230/obs_ar_91_m.db", "C:/RealityEngine/t238/obs_transcripts_91o.db",
    "C:/RealityEngine/p20/p20new.db", "C:/RealityEngine/pilot10/pilot10.db", "C:/RealityEngine/n10/n10.db",
    "C:/RealityEngine/q12/q12.db", "C:/RealityEngine/u8/u8.db", "C:/RealityEngine/bluestar/bluestar.db",
    "C:/RealityEngine/aurobindo/aurobindo.db", "D:/RealityEngine/stores.json",
]
# (local folder or file glob, Drive sub-folder): data-heavy, not served, not read by a running loop
PLAN = [
    ("D:/RE_backup", "RE_backup"),
    ("D:/RealityEngine/backups", "RealityEngine_backups"),
    ("D:/RealityEngine/rebuild_2026-11-11", "rebuild_2026-11-11"),
    ("D:/RealityEngine/hf_cache", "hf_cache"),
    ("D:/RealityEngine/hy4_out/*_before_*", "hy4_out_before"),
    ("C:/RealityEngine/t225_resettle", "t225_resettle"),
    ("C:/RealityEngine/t235", "t235"),
    ("C:/RealityEngine/t242/*", "t242"),
    ("C:/RealityEngine/hy4_quota", "hy4_quota"),
    ("C:/RealityEngine/tg_build/decks403", "tg_build_decks403"),
]


def _keep_list() -> list[str]:
    extra = []
    if KEEP_FILE.is_file():
        for line in KEEP_FILE.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line and not line.startswith(".tmp"):
                extra.append(line.rstrip("/"))
    return [k.replace("\\", "/").lower() for k in KEEP + extra]


RECENT_HOURS = 24      # anything written in the last day may be in use (graders, rechecks, unseen sets): never moved


def recent(path: Path) -> bool:
    import time  # noqa: PLC0415
    cutoff = time.time() - RECENT_HOURS * 3600
    if path.is_file():
        return path.stat().st_mtime > cutoff
    return path.stat().st_mtime > cutoff or any(f.stat().st_mtime > cutoff for f in path.rglob("*") if f.is_file())


def kept(path: Path, keep: list[str]) -> bool:
    p = path.as_posix().lower()
    return any(p.startswith(k) or k.startswith(p + "/") for k in keep)


def expand(pattern: str) -> list[Path]:
    if "*" in pattern:
        base, glob = pattern.rsplit("/", 1)
        return sorted(Path(base).glob(glob))
    return [Path(pattern)] if Path(pattern).exists() else []


def size_mb(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size // 2**20
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) // 2**20


def _log(rec: dict) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec | {"at": dt.datetime.now().isoformat(timespec="seconds")}) + "\n")


def _rclone(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["rclone", *args], capture_output=True, text=True, encoding="utf-8", errors="replace",
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def move(path: Path, dest: str) -> dict:
    target = f"{DEST_ROOT}/{dest}/{path.name}" if path.is_dir() else f"{DEST_ROOT}/{dest}"
    src = str(path)
    copy = _rclone("copy", src, target, "--checksum", "--transfers", "4") if path.is_dir() else \
        _rclone("copy", src, target, "--checksum")
    if copy.returncode != 0:
        return {"path": src, "step": "copy", "ok": False, "err": copy.stderr[-400:]}
    check = _rclone("check", src, target, "--one-way", "--checksum") if path.is_dir() else \
        _rclone("check", str(path.parent), target, "--one-way", "--checksum", "--include", path.name)
    if check.returncode != 0:
        return {"path": src, "step": "check", "ok": False, "err": check.stderr[-400:]}
    if path.is_dir():
        shutil.rmtree(path)
    else:
        os.remove(path)
    return {"path": src, "step": "deleted", "ok": True, "drive": target}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--go", action="store_true", help="copy, verify and delete (default: plan only)")
    args = ap.parse_args(argv)
    keep = _keep_list()
    total = 0
    for pattern, dest in PLAN:
        for path in expand(pattern):
            if kept(path, keep):
                print(f"KEEP  {path}")
                continue
            if recent(path):
                print(f"RECENT {path} (written in the last {RECENT_HOURS} h; next pass)")
                continue
            mb = size_mb(path)
            total += mb
            if not args.go:
                print(f"MOVE  {mb:>8,} MB  {path} -> {DEST_ROOT}/{dest}")
                continue
            rec = move(path, dest) | {"mb": mb}
            _log(rec)
            print(json.dumps(rec), flush=True)
    print(f"total {total:,} MB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
