"""Crash recovery: bring every job back after a reboot or power cut, with nobody logged in (Shivam 2026-10-19).

Runs from the scheduled task 'RealityEngine-BootRecover' (at startup, S4U = runs without a logon and without a stored
password; pythonw directly, no wscript: Bitdefender quarantined the wscript/VBS startup launcher as malware on
2026-10-19). Safe to run any time: a job already running or finished is skipped.

  1 readers at once      watchdog, PDF upload (rclone), Gemma re-embed (GPU duty 0.6; reads the DB only)
  2 smoke check          if Windows logged an unexpected shutdown (event 6008) since this boot, or --check: open
                         every database (SQLite rolls back an unfinished write on open) and read its schema and the
                         first row of every table; seconds, not the ~1 h a full quick_check took (Shivam 2026-10-20:
                         full checks after every crash waste too much time; 3 cuts x 6 DBs never found damage)
  3 writers              only if every smoke check is ok: PIB backfill, policy register, shareholding, circuit hits /
                         bands, NSE industry, PIB regional sample, DB backup staging (--pack-only)
  4 full check, behind   a detached `--full-check` process runs PRAGMA quick_check on every DB at low CPU / disk
                         priority while the jobs run; also weekly (Sunday ~02:00, started by deepseek_heartbeat).
                         On a failure it stops the writer jobs and writes data/hotline/needs_claude.md.
A failed smoke check starts no writer. Results: data/logs/boot_recover_status.json (smoke) and
data/logs/db_full_check.json (full), both shown in the watchdog report. Log: data/logs/boot_recover.log.

    python -m reality_engine.scripts.boot_recover [--check] [--dry-run]
    python -m reality_engine.scripts.boot_recover --full-check      # the background full check (low priority)
"""
import argparse
import datetime as dt
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "reality_engine" / "data"
LOGS = DATA / "logs"
SCRIPTS = ROOT / "reality_engine" / "scripts"
PY = Path(sys.executable).with_name("python.exe")
PYW = Path(sys.executable).with_name("pythonw.exe")
LOG = LOGS / "boot_recover.log"
STATUS = LOGS / "boot_recover_status.json"
DBS = [DATA / "concall_facts.db", ROOT / "analysis" / "bse_announcements.db", DATA / "results_xbrl.db",
       DATA / "deck_figures.db", DATA / "ar_facts.db", DATA / "equity_intelligence.db"]
NO_WINDOW = 0x08000000 | 0x00000008   # CREATE_NO_WINDOW | DETACHED_PROCESS


def tail(path, n=4000):
    try:
        with open(path, "rb") as fh:
            fh.seek(0, 2)
            fh.seek(max(0, fh.tell() - n))
            return fh.read().decode("utf-8", "replace")
    except OSError:
        return ""


def reembed_done():
    try:
        import numpy as np
        return bool(np.load(DATA / "vector_index_gemma" / "done.npy").all())
    except Exception:  # noqa: BLE001
        return False


# name, kind (reader / writer), command, process-match substrings (any), done() -> bool
JOBS = [
    ("watchdog", "reader", [str(PYW), "-u", "-m", "reality_engine.scripts.resource_watchdog"], ["resource_watchdog"],
     lambda: False),
    ("pdf_upload", "reader", ["cmd.exe", "/c", str(SCRIPTS / "run_pdf_upload.cmd")], ["run_pdf_upload", "1A3MOQnFsYw27"],
     lambda: "rc 0 0 0" in tail(LOGS / "pdf_upload.passes.log", 200).strip().splitlines()[-1:][0]
     if tail(LOGS / "pdf_upload.passes.log", 200).strip() else False),
    ("reembed", "reader", ["cmd.exe", "/c", str(SCRIPTS / "run_reembed_gemma.cmd")], ["reembed_gemma"], reembed_done),
    ("pib_backfill", "writer", ["cmd.exe", "/c", str(SCRIPTS / "run_pib_backfill.cmd")], ["pib_feed --start 2021"],
     lambda: False),
    ("policy_register", "writer", ["cmd.exe", "/c", str(SCRIPTS / "run_policy_register.cmd")], ["policy_register"],
     lambda: False),
    ("shareholding", "writer", ["cmd.exe", "/c", str(SCRIPTS / "run_shareholding.cmd")], ["fetch_shareholding"],
     lambda: "parsed: [(" in tail(LOGS / "shareholding.log") and "shp xbrl done" in tail(LOGS / "shareholding.log", 20000)),
    ("nse_pr", "writer", ["cmd.exe", "/c", str(SCRIPTS / "run_nse_pr.cmd")], ["fetch_nse_pr"],
     lambda: "done (" in tail(LOGS / "nse_pr.log", 400)),
    ("nse_industry", "writer", ["cmd.exe", "/c", str(SCRIPTS / "run_nse_industry.cmd")], ["fetch_nse_industry"],
     lambda: "done (" in tail(LOGS / "nse_industry.log", 400)),
    ("pib_regional_sample", "writer",
     ["cmd.exe", "/c", str(SCRIPTS / "run_pib_regional.cmd"), "--start", "2026-09-26", "--end", "2026-10-05"],
     ["pib_regional"], lambda: "2026-09-26 releases" in tail(LOGS / "pib_regional.log", 20000)),
    ("db_backup_pack", "writer", [str(PYW), "-u", "-m", "reality_engine.scripts.backup_dbs_to_drive", "--pack-only"],
     ["backup_dbs_to_drive"], lambda: False),
]


def log(msg):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line, flush=True)
    try:
        with LOG.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def running(patterns):
    me = psutil.Process().pid
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
        except (psutil.Error, TypeError):
            continue
        if p.info["pid"] != me and "boot_recover" not in cl and any(s in cl for s in patterns):
            return p.info["pid"]
    return None


def start(kind, dry):
    out = []
    for name, k, cmd, patterns, done in JOBS:
        if k != kind:
            continue
        pid = running(patterns)
        if pid:
            out.append((name, f"already running (pid {pid})")); continue
        try:
            if done():
                out.append((name, "finished earlier; not started")); continue
        except Exception:  # noqa: BLE001
            pass
        if dry:
            out.append((name, "would start")); continue
        subprocess.Popen(cmd, cwd=str(ROOT), creationflags=NO_WINDOW, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, close_fds=True)
        out.append((name, "started"))
        time.sleep(3)
    for name, what in out:
        log(f"  {kind} {name}: {what}")
    return out


def unclean_shutdown():
    """True when Windows logged 'previous shutdown was unexpected' (6008) after this boot started."""
    boot = dt.datetime.fromtimestamp(psutil.boot_time())
    q = ("Get-WinEvent -FilterHashtable @{LogName='System'; Id=6008; StartTime=[datetime]'" + boot.isoformat() +
         "'} -MaxEvents 1 -ErrorAction SilentlyContinue | % { $_.TimeCreated.ToString('s') }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", q], capture_output=True, text=True,
                       creationflags=0x08000000)
    return bool(r.stdout.strip())


def smoke_check(db):
    """Open the DB (read-write, so SQLite replays / rolls back a crash-interrupted write), read the schema and the
    first row of every table. Catches a broken header, schema or root pages in seconds; deep damage is left to the
    background quick_check."""
    con = sqlite3.connect(db, timeout=600)
    try:
        tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tables:
            con.execute(f'SELECT * FROM "{t}" LIMIT 1').fetchall()
        return len(tables)
    finally:
        con.close()


def check_dbs(full=False):
    res = {}
    for db in DBS:
        if not db.exists():
            continue
        t0 = time.time()
        try:
            if full:
                con = sqlite3.connect(db, timeout=600)
                r = con.execute("PRAGMA quick_check").fetchall()
                con.close()
                ok, result = r == [("ok",)], str(r[:3])[:300]
            else:
                ok, result = True, f"smoke ok ({smoke_check(db)} tables)"
        except Exception as e:  # noqa: BLE001
            ok, result = False, repr(e)[:300]
        res[db.name] = {"ok": ok, "result": result, "seconds": round(time.time() - t0)}
        log(f"  {'quick_check' if full else 'smoke'} {db.name}: {result} ({res[db.name]['seconds']}s)")
    return res


FULL_STATUS = LOGS / "db_full_check.json"
NEEDS_CLAUDE = DATA / "hotline" / "needs_claude.md"


def full_check():
    """Background PRAGMA quick_check of every DB at low priority. On a failure: stop the writer jobs, tell Claude."""
    me = psutil.Process()
    try:
        me.nice(psutil.BELOW_NORMAL_PRIORITY_CLASS)
        me.ionice(psutil.IOPRIO_VERYLOW)
    except (psutil.Error, AttributeError, ValueError):
        pass
    t0 = dt.datetime.now()
    log("full check (background, low priority): start")
    FULL_STATUS.write_text(json.dumps({"started": t0.isoformat(timespec="seconds"), "state": "running"}),
                           encoding="utf-8")
    res = check_dbs(full=True)
    bad = [k for k, v in res.items() if not v["ok"]]
    out = {"started": t0.isoformat(timespec="seconds"), "finished": dt.datetime.now().isoformat(timespec="seconds"),
           "state": "FAILED" if bad else "ok", "failed": bad, "checks": res}
    if bad:
        stopped = []
        for name, k, _, patterns, _ in JOBS:
            pid = running(patterns) if k == "writer" else None
            if pid:
                try:
                    for p in [psutil.Process(pid), *psutil.Process(pid).children(recursive=True)]:
                        p.kill()
                    stopped.append(name)
                except psutil.Error:
                    pass
        out["writers_stopped"] = stopped
        log(f"  FULL CHECK FAILED {bad}: stopped writers {stopped}")
        with NEEDS_CLAUDE.open("a", encoding="utf-8") as fh:
            fh.write(f"\n# Needs Claude - {dt.datetime.now():%Y-%m-%d %H:%M} IST (boot_recover --full-check)\n"
                     f"PRAGMA quick_check FAILED on {bad}. Writer jobs stopped: {stopped}. Details: "
                     f"data/logs/db_full_check.json. Repair (or restore from the Drive backup) before restarting "
                     f"writers.\n")
    FULL_STATUS.write_text(json.dumps(out, indent=1), encoding="utf-8")
    log(f"full check done: {out['state']}")


def full_check_running():
    me = psutil.Process().pid
    for p in psutil.process_iter(["pid", "cmdline"]):
        try:
            cl = " ".join(p.info["cmdline"] or [])
        except (psutil.Error, TypeError):
            continue
        if p.info["pid"] != me and "boot_recover" in cl and "--full-check" in cl:
            return p.info["pid"]
    return None


def start_full_check():
    if full_check_running():
        return "already running"
    subprocess.Popen([str(PYW), "-u", "-m", "reality_engine.scripts.boot_recover", "--full-check"], cwd=str(ROOT),
                     creationflags=NO_WINDOW, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, close_fds=True)
    return "started"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="run the database checks even after a clean shutdown")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--wait", type=int, default=120, help="seconds to wait after boot for network / disks")
    ap.add_argument("--full-check", action="store_true", help="run the full quick_check now, at low priority")
    a = ap.parse_args()
    LOGS.mkdir(parents=True, exist_ok=True)
    if a.full_check:
        full_check()
        return
    up = time.time() - psutil.boot_time()
    if not a.dry_run and up < a.wait:
        time.sleep(a.wait - up)
    log(f"boot recover: boot {dt.datetime.fromtimestamp(psutil.boot_time()):%Y-%m-%d %H:%M}, dry_run={a.dry_run}")
    status = {"run_at": dt.datetime.now().isoformat(timespec="seconds"), "readers": start("reader", a.dry_run)}
    unclean = unclean_shutdown()
    status["unclean_shutdown"] = unclean
    boot = dt.datetime.fromtimestamp(psutil.boot_time()).isoformat(timespec="minutes")
    status["boot"] = boot
    try:
        prev = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        prev = {}
    writers_up = all(running(pt) for _, k, _, pt, _ in JOBS if k == "writer")
    checked = prev.get("boot") == boot and prev.get("checks") and not prev.get("failed_checks")
    if unclean and not a.check and (checked or writers_up):
        log(f"  integrity checks skipped: {'already passed for this boot' if checked else 'writers already running'}")
        status["checks"] = prev.get("checks") or "skipped (writers already running)"
        unclean = False
    if unclean or a.check:
        log(f"  smoke checks ({'unclean shutdown' if unclean else '--check'})")
        status["checks"] = {} if a.dry_run else check_dbs()
        bad = [k for k, v in status["checks"].items() if not v["ok"]]
    else:
        bad = []
    status["failed_checks"] = bad
    if bad:
        log(f"  CHECK FAILED {bad}: writers NOT started; repair before restarting them")
        status["writers"] = "not started"
    else:
        status["writers"] = start("writer", a.dry_run)
        if (unclean or a.check) and not a.dry_run:
            status["full_check"] = start_full_check()
            log(f"  full check in the background: {status['full_check']}")
    STATUS.write_text(json.dumps(status, indent=1, default=str), encoding="utf-8")
    log("boot recover done")


if __name__ == "__main__":
    main()
