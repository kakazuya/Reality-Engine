"""Back up the project databases to Google Drive (Shivam 2026-10-19: uploads only 05:00-13:00 IST, every day).

Why: ~70 GB of databases (weeks of LLM reading) lived only on one physical disk (C: and D: share it); the PDF archive on
Drive did not include them.

One backup SET = a dated folder gdrive:InfoDiffusion_archive/db_backups/<YYYY-MM-DD>/ holding, per database, 7-Zip
volumes <db>.7z.001, .002 ... (1 GB each, fast LZMA2) made from a consistent SQLite online-backup copy (safe while
jobs write). Cadence: a new set when the last complete set is >= 7 days old (big DBs); small DBs (< 1 GB) every day.
Each run: (1) continue the unfinished set first; (2) else start a new one; (3) upload with rclone --bwlimit and stop at
13:00 IST (--max-duration, soft cutoff, so a part in flight finishes); parts already on Drive are skipped, so a set
spreads over several mornings; (4) when a database's parts are all uploaded and `rclone check` (MD5) passes, its local
parts are deleted. State: reality_engine/data/backups/state.json. Log: data/logs/db_backup.log.
Scheduled task 'RealityEngine-DBBackup' daily 05:00.

    python -m reality_engine.scripts.backup_dbs_to_drive [--dry-run]
"""
import argparse
import datetime as dt
import json
import shutil
import sqlite3
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine/data"
STAGE = DATA / "backups"
STATE = STAGE / "state.json"
LOG = DATA / "logs/db_backup.log"
RCLONE = r"C:\Users\warri\AppData\Local\Microsoft\WinGet\Packages\Rclone.Rclone_Microsoft.Winget.Source_8wekyb3d8bbwe\rclone-v1.75.1-windows-amd64\rclone.exe"
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
REMOTE = "gdrive:InfoDiffusion_archive/db_backups"
DBS = [DATA / "concall_facts.db", DATA / "results_xbrl.db", DATA / "deck_figures.db", DATA / "ar_facts.db",
       DATA / "equity_intelligence.db", ROOT / "analysis/bse_announcements.db"]
STOP_AT = dt.time(13, 0)
BWLIMIT = "1.5M"
SMALL = 1 << 30


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with LOG.open("a", encoding="utf-8") as fh:
        fh.write(line + "\n")


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {"sets": {}, "last_full": None}


def save_state(s):
    STAGE.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(s, indent=1))


def snapshot_and_pack(db, set_dir):
    """consistent copy via the SQLite online-backup API, then 7-Zip volumes; the plain copy is removed"""
    set_dir.mkdir(parents=True, exist_ok=True)
    copy = set_dir / db.name
    src = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=600)
    dst = sqlite3.connect(copy)
    # one step (pages=-1): a stepwise backup restarts whenever another connection writes, so with the PIB / EOD jobs
    # writing every second a 39 GB copy would never finish; a single step reads one consistent snapshot instead
    with dst:
        src.backup(dst, pages=-1)
    src.close(); dst.close()
    subprocess.run([SEVENZIP, "a", "-t7z", "-mx1", "-mmt=4", "-v1g", str(set_dir / f"{db.stem}.7z"), str(copy)],
                   check=True, stdout=subprocess.DEVNULL)
    copy.unlink()
    return sorted(p.name for p in set_dir.glob(f"{db.stem}.7z.*"))


def upload(set_dir, remote_dir):
    now = dt.datetime.now()
    stop = dt.datetime.combine(now.date(), STOP_AT)
    secs = int((stop - now).total_seconds())
    if secs < 300:
        log("outside the upload window (05:00-13:00); not uploading"); return False
    r = subprocess.run([RCLONE, "copy", str(set_dir), remote_dir, "--bwlimit", BWLIMIT, "--transfers", "2",
                        "--max-duration", f"{secs}s", "--cutoff-mode", "soft", "--drive-chunk-size", "32M",
                        "--tpslimit", "8", "--log-level", "NOTICE", "--log-file", str(LOG)])
    return r.returncode == 0


def verify_and_clean(set_dir, remote_dir, st, set_name):
    r = subprocess.run([RCLONE, "check", str(set_dir), remote_dir, "--one-way", "--log-level", "ERROR",
                        "--log-file", str(LOG)])
    if r.returncode == 0:
        for p in set_dir.glob("*.7z.*"):
            p.unlink()
        st["sets"][set_name]["complete"] = True
        log(f"set {set_name}: all parts on Drive and MD5-checked; local parts deleted")
        return True
    log(f"set {set_name}: check found missing/differing parts (rc {r.returncode}); will resume next run")
    return False


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if not (dt.time(5, 0) <= dt.datetime.now().time() < STOP_AT) and not a.dry_run:
        log("started outside 05:00-13:00; nothing to do"); return
    st = load_state()
    open_sets = [k for k, v in st["sets"].items() if not v.get("complete")]
    if open_sets:
        name = sorted(open_sets)[0]
        log(f"continuing unfinished set {name}")
    else:
        name = dt.date.today().isoformat()
        last_full = st.get("last_full")
        full = not last_full or (dt.date.today() - dt.date.fromisoformat(last_full)).days >= 7
        dbs = [d for d in DBS if d.exists() and (full or d.stat().st_size < SMALL)]
        log(f"new set {name}: {'full' if full else 'small DBs only'} -> {[d.name for d in dbs]}")
        if a.dry_run:
            return
        free = shutil.disk_usage(STAGE.parent).free
        if free < 1.2 * max(d.stat().st_size for d in dbs) + (20 << 30):
            log(f"not enough free disk ({free >> 30} GB) to stage a copy; skipping"); return
        st["sets"][name] = {"dbs": [], "complete": False, "full": full}
        save_state(st)
        set_dir = STAGE / name
        for d in dbs:
            parts = snapshot_and_pack(d, set_dir)
            st["sets"][name]["dbs"].append({"db": d.name, "parts": parts, "src_bytes": d.stat().st_size})
            save_state(st)
            log(f"packed {d.name}: {len(parts)} part(s)")
        if full:
            st["last_full"] = name
        save_state(st)
    if a.dry_run:
        return
    set_dir = STAGE / name
    remote_dir = f"{REMOTE}/{name}"
    upload(set_dir, remote_dir)
    verify_and_clean(set_dir, remote_dir, st, name)
    save_state(st)


if __name__ == "__main__":
    main()
