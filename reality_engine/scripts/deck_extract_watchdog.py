"""Night watchdog for the deck-figure extractor (run_deck_extract.cmd).

Every CHECK_SEC it writes one status line (recent pages/s, free RAM, disk MB/s) to
data/logs/deck_extract_watchdog.log and acts only on clear faults:
  - extractor not running, and its last pass did not end with "nothing left" (exit 0): start it
  - extractor running but its log silent for STALE_MIN minutes (hung): kill the whole tree, start it
  - orphaned render workers (multiprocessing children of a dead extractor, in this project's folder): kill them
    (2026-10-10: 16 orphans at ~3 GB commit each pushed RAM to 98%)
  - low RAM or a saturated disk: names the processes responsible in the log; it never kills anything it did not start
Restarts are rate-limited (RESTART_GAP_MIN apart, MAX_RESTARTS per watchdog run). The extractor is launched with
the user's saved environment variables from the registry, so keys set after this shell started (KILO_API_KEY_2,
STEPFUN_API_KEY) are not lost (2026-10-11: a restart from an old shell silently dropped the second Kilo key).

Start detached:  wscript reality_engine\\scripts\\run_hidden.vbs reality_engine\\scripts\\run_deck_watchdog.cmd
Stop: end the python process running deck_extract_watchdog (the extractor keeps running).
"""
import ctypes
import logging
import os
import re
import subprocess
import sys
import time
import winreg
from datetime import datetime, timedelta
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "reality_engine" / "data" / "logs"
EXTRACT_LOG = LOGS / "extract_deck_figures.log"
PASSES_LOG = LOGS / "extract_deck_figures.passes.log"
RUN_CMD = ROOT / "reality_engine" / "scripts" / "run_deck_extract.cmd"
HIDDEN_VBS = ROOT / "reality_engine" / "scripts" / "run_hidden.vbs"
LOCK = LOGS / "deck_extract_watchdog.pid"

CHECK_SEC = 120
STALE_MIN = 20            # the cmd sleeps 5 min between passes and a pass takes ~3 min to log its first progress line
RESTART_GAP_MIN = 30
MAX_RESTARTS = 6
LOW_RAM_GB = 1.5
DISK_BUSY_MBS = 80        # sustained reads+writes above this get their top processes named
SLOW_PAGES_S = 2.0

log = logging.getLogger("deck_watchdog")


def user_env():
    """os.environ plus the machine and user variables saved in the registry (user wins, PATH merged)."""
    env = dict(os.environ)
    for hive, sub in ((winreg.HKEY_LOCAL_MACHINE, r"SYSTEM\CurrentControlSet\Control\Session Manager\Environment"),
                      (winreg.HKEY_CURRENT_USER, "Environment")):
        try:
            with winreg.OpenKey(hive, sub) as k:
                i = 0
                while True:
                    try:
                        name, val, typ = winreg.EnumValue(k, i)
                    except OSError:
                        break
                    i += 1
                    if typ == winreg.REG_EXPAND_SZ:
                        val = os.path.expandvars(val)
                    if name.upper() != "PATH":
                        env[name] = val
        except OSError:
            pass
    return env


def extractor_cmds():
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() == "cmd.exe" and "run_deck_extract.cmd" in " ".join(p.info["cmdline"] or []):
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return out


def orphan_workers():
    """multiprocessing children whose parent is gone, running in this project's folder."""
    out = []
    for p in psutil.process_iter(["name", "cmdline", "ppid"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if (p.info["name"] or "").lower() != "python.exe" or "multiprocessing.spawn" not in cmd:
                continue
            m = re.search(r"parent_pid=(\d+)", cmd)
            parent = int(m.group(1)) if m else p.info["ppid"]
            if psutil.pid_exists(parent):
                continue
            if Path(p.cwd()).resolve() == ROOT:
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            pass
    return out


def kill_tree(p):
    try:
        procs = p.children(recursive=True) + [p]
    except psutil.NoSuchProcess:
        return
    for q in procs:
        try:
            q.kill()
        except psutil.NoSuchProcess:
            pass
    psutil.wait_procs(procs, timeout=15)


def start_extractor():
    subprocess.Popen(["wscript.exe", str(HIDDEN_VBS), str(RUN_CMD)], cwd=str(ROOT), env=user_env(),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def last_pass_exit():
    try:
        lines = PASSES_LOG.read_text(encoding="utf-8", errors="replace").strip().splitlines()
        m = re.search(r"exit (-?\d+)", lines[-1]) if lines else None
        return int(m.group(1)) if m else None
    except OSError:
        return None


def recent_rate(minutes=10):
    """Pages/s from the extractor's progress lines over the last `minutes` (None if fewer than two lines)."""
    try:
        with open(EXTRACT_LOG, "rb") as f:
            f.seek(max(0, os.path.getsize(EXTRACT_LOG) - 400_000))
            tail = f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return None
    pts = []
    for line in tail:
        m = re.match(r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO pages (\d+) ", line)
        if m:
            pts.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), int(m.group(2))))
    cut = datetime.now() - timedelta(minutes=minutes)
    pts = [p for p in pts if p[0] >= cut]
    # a restart resets the counter: keep only the run that the last line belongs to
    while len(pts) > 1 and any(b[1] < a[1] for a, b in zip(pts, pts[1:])):
        i = max(i for i, (a, b) in enumerate(zip(pts, pts[1:])) if b[1] < a[1])
        pts = pts[i + 1:]
    if len(pts) < 2 or (pts[-1][0] - pts[0][0]).total_seconds() < 60:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]).total_seconds()


def io_snapshot():
    snap = {}
    for p in psutil.process_iter(["name"]):
        try:
            c = p.io_counters()
            snap[p.pid] = (p.info["name"], c.read_bytes + c.write_bytes)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return snap


def main():
    LOGS.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(filename=LOGS / "deck_extract_watchdog.log", level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    if LOCK.exists():
        try:
            other = int(LOCK.read_text())
            if psutil.pid_exists(other) and "deck_extract_watchdog" in " ".join(psutil.Process(other).cmdline()):
                print(f"watchdog already running (pid {other})"); return
        except (ValueError, OSError, psutil.Error):
            pass
    LOCK.write_text(str(os.getpid()))
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)   # keep the PC awake while the watchdog runs
    log.info("watchdog started (pid %d)", os.getpid())
    restarts, last_restart = 0, 0.0
    disk_prev, io_prev, t_prev = psutil.disk_io_counters(), io_snapshot(), time.time()
    busy_streak = 0
    while True:
        time.sleep(CHECK_SEC)
        now = time.time(); dt = now - t_prev
        disk = psutil.disk_io_counters(); io = io_snapshot()
        mbs = ((disk.read_bytes - disk_prev.read_bytes) + (disk.write_bytes - disk_prev.write_bytes)) / dt / 1e6
        ram = psutil.virtual_memory().available / 1e9
        rate = recent_rate()
        cmds = extractor_cmds()
        age = (now - EXTRACT_LOG.stat().st_mtime) / 60 if EXTRACT_LOG.exists() else 1e9
        log.info("extractor %s | %s pages/s (10 min) | log age %.1f min | RAM free %.1f GB | disk %.0f MB/s",
                 "running" if cmds else "NOT RUNNING", f"{rate:.1f}" if rate is not None else "-", age, ram, mbs)

        orphans = orphan_workers()
        if orphans:
            log.warning("killing %d orphaned render workers: %s", len(orphans), [o.pid for o in orphans])
            for o in orphans:
                kill_tree(o)

        if ram < LOW_RAM_GB:
            top = sorted(psutil.process_iter(["name", "memory_info"]), key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)[:6]
            log.warning("low RAM (%.1f GB free); largest: %s", ram,
                        [(p.pid, p.info["name"], round(p.info["memory_info"].rss / 1e9, 1)) for p in top if p.info["memory_info"]])

        busy_streak = busy_streak + 1 if mbs > DISK_BUSY_MBS else 0
        if busy_streak >= 3:
            deltas = sorted(((v[1] - io_prev.get(pid, (None, v[1]))[1]) / dt / 1e6, pid, v[0]) for pid, v in io.items())[::-1][:5]
            log.warning("disk busy for %d checks (%.0f MB/s); top processes MB/s: %s", busy_streak, mbs,
                        [(round(d, 1), pid, n) for d, pid, n in deltas])

        if rate is not None and rate < SLOW_PAGES_S and cmds and age < STALE_MIN:
            log.warning("slow: %.1f pages/s over the last 10 min", rate)

        fault = None
        if not cmds:
            ex = last_pass_exit()
            if ex == 0:
                log.info("extractor finished (last pass exit 0); nothing to do")
            else:
                fault = f"not running (last pass exit {ex})"
        elif age >= STALE_MIN:
            fault = f"log silent for {age:.0f} min (hung)"
        if fault:
            if restarts >= MAX_RESTARTS:
                log.error("%s, but %d restarts already done; leaving it for a human", fault, restarts)
            elif now - last_restart < RESTART_GAP_MIN * 60:
                log.warning("%s; last restart %.0f min ago, waiting", fault, (now - last_restart) / 60)
            else:
                log.warning("%s; restarting the extractor", fault)
                for c in cmds:
                    kill_tree(c)
                time.sleep(5)
                for o in orphan_workers():
                    kill_tree(o)
                start_extractor()
                restarts += 1; last_restart = time.time()
        disk_prev, io_prev, t_prev = disk, io, now


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log.exception("watchdog crashed")
        sys.exit(1)
