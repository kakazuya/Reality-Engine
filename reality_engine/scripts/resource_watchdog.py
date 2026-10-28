"""Machine-wide resource watchdog: keeps the long jobs alive and records every case of wasted compute.

Runs permanently (started at logon from the Windows Startup folder, see install_startup()). Every CHECK_SEC it:
  - keeps each managed job (JOBS) alive ONLY when that is explicitly allowed (see "Who may be started" below);
    otherwise a stopped/hung job is recorded as an incident and left alone
  - kills orphaned multiprocessing workers left in this project's folder by a dead parent
    (2026-10-10: 16 orphaned render workers at ~3 GB commit each pushed RAM to 98%)
  - records WASTE INCIDENTS, naming the process and the numbers:
      disk_hog    one process reading/writing more than DISK_HOG_MBS for 3 checks in a row
                  (2026-10-11: the extractor re-read its 5 GB queue every second, ~135 MB/s, run fell to 0.4 pages/s)
      cpu_hog     machine CPU above CPU_BUSY_PCT for 3 checks; the top processes are named
      low_ram     available RAM under LOW_RAM_GB; the largest processes are named
      low_disk    free space under DISK_FREE_MIN_GB on C: or on the D: volume holding D:\\RealityEngine
      job_slow    a managed job below its slow_rate, with what the job itself was waiting on (readers idle or full)
      job_hung / job_stopped / orphans_killed / restart_limit
It never kills anything except orphans in this project and the managed jobs it restarts.

Who may be started (2026-10-24, laptop safety):
  - restarts are opt-in: a job needs "auto_restart": True (default False)
  - a job tagged paid / gpu / pc_only is NEVER auto-started, whatever its flag says: a human starts those
    (`paid` = spends an external model API budget, free-tier quotas included; `pc_only` = needs the PC's corpus)
  - profile "laptop" (env REALITY_WATCHDOG_PROFILE=laptop, or --install-startup --profile laptop) is monitor-only:
    no managed job and no side job (new_reader_check, ar_review) is started, and the laptop is not kept awake
Every refusal is recorded with its reason. To let the PC restart a job again: auto_restart True there, drop its
paid/gpu/pc_only tag (that is the explicit OK), and run with profile "pc".

Laptop values (2026-10-24: 8 logical cores, 16 GiB RAM, C: 460 GB SSD + D: 931 GB with our PDFs in
D:\\RealityEngine): CPU >= 90% for 3 checks (6 min), RAM free < 1.5 GB, disk I/O >= 50 MB/s for 3 checks,
free space < 20 GB on C: / < 30 GB on D:. Only D:\\RealityEngine is ours: nothing else on D: is scanned or touched.

Output (all in reality_engine/data/logs/):
  resource_watchdog.log            one status line per check plus every action
  resource_incidents.jsonl         one JSON line per incident (kind, first/last seen, count, details)
  resource_watchdog_report.md      rolling report (current status + incidents of the last 48 h); a Claude Code
                                   SessionStart hook prints it into every new session (print_report())

Start now:   wscript reality_engine\\scripts\\run_hidden.vbs reality_engine\\scripts\\run_resource_watchdog.cmd
Report:      python -m reality_engine.scripts.resource_watchdog --report
Dry run:     python -m reality_engine.scripts.resource_watchdog --once --dry-run   (one check, acts on nothing)
Stop:        end the python process running resource_watchdog (managed jobs keep running)
"""
import argparse
import ctypes
import json
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
SCRIPTS = ROOT / "reality_engine" / "scripts"
HIDDEN_VBS = SCRIPTS / "run_hidden.vbs"
LOCK = LOGS / "resource_watchdog.pid"
STATE = LOGS / "resource_watchdog_state.json"
INCIDENTS = LOGS / "resource_incidents.jsonl"
REPORT = LOGS / "resource_watchdog_report.md"

CHECK_SEC = 120
READER_REPORT = LOGS / "reader_watch_report.md"
QUERY_SPEED_REPORT = LOGS / "query_speed_report.md"
BOOT_STATUS = LOGS / "boot_recover_status.json"   # boot_recover.py (crash recovery), 2026-10-19   # query_speed_check.py (nightly in run_eod_market), 2026-10-19
AR_REVIEW_EVERY = 200   # ar_review.py after this many newly finished annual reports (Shivam 2026-10-13)
STUCK_MIN = 30  # a managed job reading no pages (and no second readings) this long is restarted as hung
HANDLE_HOG = 200_000   # open handles in one process (explorer ~7k, our main run ~4k; the 10-17 orphan finds held ~3 M each)
RETIRED_READERS = {"Cat Jam"}   # gone from Zen and Go (2026-10-16); a drop there is no news
READER_CHECK_EVERY_S = 2 * 3600   # new_reader_check.py runs every 2 h (OpenCode posts free models at any hour; 2026-10-13 Cat Jam came at 23:29)
RESTART_GAP_MIN = 30
MAX_RESTARTS_PER_DAY = 6
LOW_RAM_GB = 1.5
DISK_HOG_MBS = 50
CPU_BUSY_PCT = 90
REPORT_HOURS = 48

# Machine profile: "pc" (historic behaviour) or "laptop" (monitor only). Env wins over the file written by
# --install-startup; anything that is not "pc" is treated as monitor-only, so a typo cannot start paid work.
PROFILE_ENV = "REALITY_WATCHDOG_PROFILE"
PROFILE_FILE = LOGS / "resource_watchdog_profile.txt"
DEFAULT_PROFILE = "pc"
HAZARD_TAGS = frozenset({"paid", "gpu", "pc_only"})   # never auto-started, whatever auto_restart says

# Free space watched: C: always, D: only through D:\RealityEngine (the laptop's PDF corpus; nothing else on D: is
# read). Floors: 20 GB on the 460 GB system SSD (Windows + SQLite WAL churn), 30 GB on D: (corpus + ar_facts.db).
DISK_FREE_MIN_GB = {"C:\\": 20.0, "D:\\": 30.0}
REALITY_DATA_DISK = Path(r"D:\RealityEngine")

# Managed jobs. `match`: text in the cmd.exe command line; `log`: the job's own log (staleness, rate);
# `done_exit`: the last line of `passes` ends with this exit code when the job has nothing left to do;
# `auto_restart`: may the watchdog restart it (opt-in, default False); `tags`: why it maybe must not (HAZARD_TAGS).
JOBS = [
    {"name": "deck-extract", "match": "run_deck_", "log": LOGS / "extract_deck_figures.log",
     "passes": LOGS / "extract_deck_figures.passes.log", "done_exit": 0, "stale_min": 20, "slow_rate": 2.0,
     "auto_restart": False, "tags": ("paid", "pc_only"),
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO pages (\d+) ",
     "second_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO pages .*?second reads (\d+)"},
    # annual-report fact extraction (2026-10-12); rate = report pages read per second
    {"name": "ar-ingest", "match": "run_ar_ingest", "log": LOGS / "ingest_annual_reports.log",
     "passes": LOGS / "ingest_annual_reports.passes.log", "done_exit": 0, "stale_min": 20, "slow_rate": 1.0,
     "auto_restart": False, "tags": ("paid",),
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO ar docs .*? pages (\d+) "},
    # annual reports, Zen route (2026-10-12): OpenCode Zen free models via `opencode run`, oldest filing first
    # annual reports, Google route (2026-10-13): Flash-Lite 3.5 on all Gemini keys; idle_ok: daily caps can idle it
    {"name": "ar-google", "match": "run_ar_google", "idle_ok": True, "log": LOGS / "ingest_annual_reports_google.log",
     "passes": LOGS / "ingest_annual_reports_google.passes.log", "done_exit": 0, "stale_min": 30, "slow_rate": 0.2,
     "auto_restart": False, "tags": ("paid",),
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO ar docs .*? pages (\d+) "},
    {"name": "ar-ggemma26", "match": "run_ar_ggemma26", "idle_ok": True, "log": LOGS / "ingest_annual_reports_google_gemma-4-26b.log",
     "passes": LOGS / "ingest_annual_reports_google_gemma-4-26b.passes.log", "done_exit": 0, "stale_min": 30, "slow_rate": 0.2,
     "auto_restart": False, "tags": ("paid",),
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO ar docs .*? pages (\d+) "},
    {"name": "ar-gflash31", "match": "run_ar_gflash31", "idle_ok": True, "log": LOGS / "ingest_annual_reports_google_3.1fl.log",
     "passes": LOGS / "ingest_annual_reports_google_3.1fl.passes.log", "done_exit": 0, "stale_min": 30, "slow_rate": 0.2,
     "auto_restart": False, "tags": ("paid",),
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO ar docs .*? pages (\d+) "},
    # idle_ok: it legitimately reads nothing while the Zen free quota is used up, so no-pages is not a hang
    {"name": "ar-zen", "match": "run_ar_zen", "idle_ok": True, "log": LOGS / "ingest_annual_reports_zen.log",
     "passes": LOGS / "ingest_annual_reports_zen.passes.log", "done_exit": 0, "stale_min": 30, "slow_rate": 0.2,
     "auto_restart": False, "tags": ("paid",),
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO ar docs .*? pages (\d+) "},
]

# Side jobs the watchdog starts on a timer (not managed, never restarted): same refusal rules, but they are not
# opt-in with auto_restart because the PC has always started them.
SIDE_JOBS = {
    "new-reader-check": {"auto_restart": True, "tags": ("network", "quota")},
    "ar-review": {"auto_restart": True},
}

log = logging.getLogger("resource_watchdog")


def machine_profile():
    """pc | laptop: env REALITY_WATCHDOG_PROFILE, else the file written by --install-startup, else pc."""
    p = os.environ.get(PROFILE_ENV, "").strip().lower()
    if not p:
        try:
            p = PROFILE_FILE.read_text(encoding="utf-8").strip().lower()
        except OSError:
            p = ""
    return p or DEFAULT_PROFILE


PROFILE = machine_profile()


def blocked_reason(job):
    """Why this job must not be started here, or None if it may. Every start/restart goes through this check."""
    why = []
    if PROFILE != "pc":
        why.append(f"profile={PROFILE} is monitor-only")
    tags = [t for t in job.get("tags", ()) if t in HAZARD_TAGS]
    if tags:
        why.append(f"tagged {'/'.join(tags)}: a human starts it, never the watchdog")
    if not job.get("auto_restart", False):
        why.append("auto_restart is off (restarts are opt-in)")
    return "; ".join(why) or None


# ---------------------------------------------------------------- helpers
def user_env():
    """os.environ plus the machine and user variables saved in the registry (so keys set after this shell started
    are passed on; 2026-10-11 a restart from an old shell silently dropped KILO_API_KEY_2)."""
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


def job_procs(job):
    out = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            if (p.info["name"] or "").lower() == "cmd.exe" and job["match"] in " ".join(p.info["cmdline"] or []):
                out.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return out


READER_DROP_EVERY_S = 30 * 60


def reader_drops():
    """Per annual-report reader family: pages in the last hour vs its best hour of the last 24 h (2026-10-15, Shivam: the
    watchdog must catch a reader slowing down by itself; Gemma 26B ran at ~5% for 13 h unnoticed because only whole jobs
    were watched). Also flags a burst of reports marked unreadable. Returns (kind, where, text) incidents."""
    import sqlite3
    out = []
    db = ROOT / "reality_engine" / "data" / "ar_facts.db"
    if not db.exists():   # laptop / fresh checkout: no AR database, so no reader rates to judge
        return out
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=60)
        since = (datetime.now() - timedelta(hours=24)).isoformat(timespec="seconds")
        fam = ("CASE WHEN model LIKE 'longcat%' THEN 'LongCat' WHEN model LIKE 'cat-jam%' THEN 'Cat Jam' "
               "WHEN model LIKE 'zen:%' THEN 'Zen' WHEN model LIKE 'gemma-4-26b%' THEN 'Gemma 26B' "
               "WHEN model LIKE 'gemma-4-31b%' THEN 'Gemma 31B' WHEN model LIKE 'gemini-3.5%' THEN 'Flash-Lite 3.5' "
               "WHEN model LIKE 'gemini-3.1%' THEN 'Flash-Lite 3.1' WHEN model LIKE 'beam%' THEN 'Beam' "
               "ELSE model END")   # 2026-10-17: ELSE was 'Flash-Lite 3.1', so Beam's pages were counted as Flash-Lite 3.1
        rows = con.execute(f"SELECT {fam}, substr(ts, 1, 13), SUM(page_to - page_from + 1) FROM ar_pieces "
                           "WHERE status='ok' AND ts >= ? GROUP BY 1, 2", (since,)).fetchall()
        last_hour = (datetime.now() - timedelta(hours=1)).strftime("%Y-%m-%dT%H")
        by = {}
        for f, h, p in rows:
            by.setdefault(f, {})[h] = p or 0
        for f, hours in by.items():
            if f in RETIRED_READERS:
                continue
            best = max(hours.values())
            now_p = hours.get(last_hour, 0)
            if best >= 3000 and now_p < 0.3 * best:   # a reader that mattered (>= 50 pages/min at its best) fell under 30%
                out.append(("reader_drop", f, f"{now_p / 60:.0f} pages/min in the last full hour vs {best / 60:.0f} at its "
                            f"best in 24 h (quota, provider outage, or our own bench/pacing: check before assuming)"))
        bad = con.execute("SELECT COUNT(*) FROM ar_docs WHERE status='unreadable' AND ts >= ?",
                          ((datetime.now() - timedelta(minutes=30)).isoformat(timespec="seconds"),)).fetchone()[0]
        if bad >= 5:
            out.append(("unreadable_burst", "ar", f"{bad} reports marked unreadable in 30 min (killed children? bad PDFs?)"))
        con.close()
    except Exception as e:
        out.append(("monitor_failed", "reader_drops", str(e)[:150]))
    return out


def in_project(p):
    """True when the process runs inside this project's folder: the only place this watchdog ever kills."""
    try:
        return Path(p.cwd()).resolve().is_relative_to(ROOT)
    except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
        return False


def orphan_workers():
    """multiprocessing children whose parent is gone, running in this project's folder. Every pattern below is
    limited to the project folder (2026-10-24: the docstring above promises never to kill outside it)."""
    out = []
    for p in psutil.process_iter(["name", "cmdline", "ppid"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            name = (p.info["name"] or "").lower()
            # 2026-10-17: four Git-bash `find / -name *hash*` and one `grep -rl ... .` outlived their shells (an agent's
            # command timeout kills bash, not the child) and held ~11.6 M handles: kernel paged pool 7.5 GB, RAM free
            # 6 -> 0.8 GB over 3 h. Read-only search tools whose parent is gone, running > 10 min, are killed.
            # Narrowed 19:50 the same day: in Git-bash pipelines (`python ... | grep -v x`) the recorded parent is often a
            # short-lived bash, so 'parent gone' alone killed a live pipeline's grep and with it the job writing into it.
            # Only a whole-disk scan or a handle hog counts now.
            if name in ("find.exe", "grep.exe", "rg.exe", "xargs.exe"):
                wide = re.search(r"\bfind(\.exe)?\"?\s+/(\s|$)", cmd) or p.num_handles() > 100_000
                if (wide and not psutil.pid_exists(p.info["ppid"]) and time.time() - p.create_time() > 600
                        and in_project(p)):
                    out.append(p)
                continue
            if name != "python.exe":
                continue
            # AR report-cutting children (ingest_annual_reports --pieces-json): orphaned, or past the parent's 3-min limit
            # (2026-10-14: three orphans read the disk at ~1 GB/s for up to 15 h after their parents were killed)
            if "--pieces-json" in cmd:
                if (not psutil.pid_exists(p.info["ppid"]) or time.time() - p.create_time() > 300) and in_project(p):
                    out.append(p)
                continue
            if "multiprocessing.spawn" not in cmd:
                continue
            m = re.search(r"parent_pid=(\d+)", cmd)
            if psutil.pid_exists(int(m.group(1)) if m else p.info["ppid"]):
                continue
            if in_project(p):
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


def start_cmd(cmdline_target):
    """Launch a .cmd (with arguments) hidden and detached, with the saved user environment."""
    wrapper = LOGS / "resource_watchdog_restart.cmd"
    # through a child cmd.exe, so the job's own command line (which job_procs() matches) is visible to the next check
    wrapper.write_text(f'@echo off\r\ncd /d "{ROOT}"\r\ncmd /c {cmdline_target}\r\n', encoding="utf-8")
    subprocess.Popen(["wscript.exe", str(HIDDEN_VBS), str(wrapper)], cwd=str(ROOT), env=user_env(),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


def restart_or_report(job, js, procs, fault, now, inc, dry_run=False):
    """The one place a managed job would be (re)started. A refused job only records the incident and the reason."""
    day = [t for t in js["restarts"] if now - t < 86400]
    js["restarts"] = day
    why = blocked_reason(job) or (None if js.get("target") else "no command line saved to start it with")
    if why:
        inc.add(fault[0], job["name"], f"{fault[1]}; NOT restarting: {why}")
    elif len(day) >= MAX_RESTARTS_PER_DAY:
        inc.add("restart_limit", job["name"], f"{fault[1]}; {len(day)} restarts in 24 h, left for a human")
    elif day and now - day[-1] < RESTART_GAP_MIN * 60:
        pass
    else:
        inc.add(fault[0], job["name"],
                f"{fault[1]}; {'would restart' if dry_run else 'restarting'}: {js['target']}")
        if dry_run:
            print(f"would restart {job['name']}: {js['target']}")
            return
        for p in procs:
            kill_tree(p)
        time.sleep(5)
        for o in orphan_workers():
            kill_tree(o)
        start_cmd(js["target"])
        js["restarts"].append(now)


def disk_paths():
    """Volumes whose free space is checked: the system drive, plus D:\\RealityEngine when it exists (the laptop's
    PDF corpus). Nothing else on D: is looked at."""
    out = [Path(os.environ.get("SystemDrive", "C:") + "\\")]
    if REALITY_DATA_DISK.exists():
        out.append(REALITY_DATA_DISK)
    return [p for p in out if p.anchor in DISK_FREE_MIN_GB]


def disk_checks():
    """(status lines, [(key, detail)]) for free space on the watched volumes; a volume under its floor is an incident."""
    lines, low = [], []
    for p in disk_paths():
        lim = DISK_FREE_MIN_GB[p.anchor]
        name = str(p).rstrip("\\")
        try:
            free = psutil.disk_usage(str(p)).free / 1e9
        except OSError as e:
            lines.append(f"disk {name}: unreadable ({e})")
            continue
        lines.append(f"disk {name} {free:.0f} GB free (min {lim:.0f})")
        if free < lim:
            low.append((str(p), f"{free:.1f} GB free, under the {lim:.0f} GB floor: free space on {name}"))
    return lines, low


def job_target(cmdline):
    """The '"x.cmd" args' part of a cmd.exe /c command line."""
    m = re.search(r'/[cC]\s+(.*)$', cmdline)
    t = (m.group(1) if m else cmdline).strip()
    if t.startswith('""') and t.endswith('"'):
        t = t[1:-1]
    return t.strip()


def last_exit(passes):
    try:
        lines = Path(passes).read_text(encoding="utf-8", errors="replace").strip().splitlines()
        m = re.search(r"exit (-?\d+)", lines[-1]) if lines else None
        return int(m.group(1)) if m else None
    except OSError:
        return None


def log_tail(path, nbytes=400_000):
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - nbytes))
            return f.read().decode("utf-8", errors="replace").splitlines()
    except OSError:
        return []


def series_rate(lines, pattern, minutes=10):
    """Per-second rate of a counter in log lines over the last `minutes` (None if too few points). A restart
    resets the counter, so only the run the last line belongs to is used."""
    pts = []
    for line in lines:
        m = re.match(pattern, line)
        if m:
            pts.append((datetime.strptime(m.group(1), "%Y-%m-%d %H:%M:%S"), int(m.group(2))))
    cut = datetime.now() - timedelta(minutes=minutes)
    pts = [p for p in pts if p[0] >= cut]
    for i in range(len(pts) - 1, 0, -1):
        if pts[i][1] < pts[i - 1][1]:
            pts = pts[i:]; break
    if len(pts) < 2 or (pts[-1][0] - pts[0][0]).total_seconds() < 60:
        return None
    return (pts[-1][1] - pts[0][1]) / (pts[-1][0] - pts[0][0]).total_seconds()


def deck_diagnosis(lines):
    """What the extractor was waiting on, from its last progress line's in-flight/limit map."""
    for line in reversed(lines):
        m = re.search(r"in flight/limit (\{.*?\})", line)
        if m:
            try:
                d = {k: tuple(map(int, v.split("/"))) for k, v in json.loads(m.group(1).replace("'", '"')).items()}
            except (ValueError, json.JSONDecodeError):
                return ""
            full = [k for k, (a, b) in d.items() if b and a >= b]
            idle = [k for k, (a, b) in d.items() if b and a <= b * 0.2]
            return f"readers full: {full or 'none'}; readers mostly idle: {idle or 'none'}"
    return ""


def io_snapshot():
    snap = {}
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            c = p.io_counters()
            snap[p.pid] = (p.info["name"], " ".join(p.info["cmdline"] or [])[:160], c.read_bytes + c.write_bytes,
                           c.read_count + c.write_count)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return snap


# 2026-10-29 (Shivam): watch every device, not just MB/s. The D: HDD sat at 100% busy on ~300 KB/s of random
# reads (a bench reading pilot DBs from the HDD) and the old MB/s-only check never fired.
DISK_BUSY_PCT = 80       # a physical disk this busy for 3 checks is an incident (busy = read+write time / wall time)
GPU_BUSY_PCT = 90
GPU_HOT_C = 85


def disk_labels():
    """PhysicalDriveN -> 'C: SSD (NVMe)' style labels, read once from Windows."""
    labels = {}
    try:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "Get-Partition | ? DriveLetter | % { '{0}|{1}|{2}' -f $_.DiskNumber, $_.DriveLetter, "
             "(Get-PhysicalDisk -DeviceNumber $_.DiskNumber -ErrorAction SilentlyContinue).MediaType }"],
            capture_output=True, text=True, timeout=30).stdout
        for line in out.splitlines():
            num, letter, media = (line.split("|") + ["", "", ""])[:3]
            if num.strip().isdigit():
                key = f"PhysicalDrive{num.strip()}"
                labels[key] = (labels.get(key, "") + f"{letter.strip()}:").strip() + (f" {media.strip()}" if media.strip() else "")
    except Exception:   # no PowerShell, a timeout, a mocked subprocess: labels are cosmetic
        pass
    return labels


def disk_busy(prev, cur, dt):
    """Per physical disk: (busy %, MB/s) between two perdisk psutil snapshots."""
    out = {}
    for name, c in cur.items():
        p = prev.get(name)
        if p is None:
            continue
        busy_ms = (c.read_time - p.read_time) + (c.write_time - p.write_time)
        mb = ((c.read_bytes - p.read_bytes) + (c.write_bytes - p.write_bytes)) / 1e6
        out[name] = (min(100.0 * busy_ms / (dt * 1000), 999.0), mb / dt)
    return out


def gpu_status():
    """[(index, name, util %, mem used MB, mem total MB, temp C)] from nvidia-smi; [] when absent."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=index,name,utilization.gpu,memory.used,memory.total,"
                              "temperature.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout
    except Exception:   # no nvidia-smi (or a mocked subprocess): no GPU line
        return []
    rows = []
    for line in out.splitlines():
        f = [x.strip() for x in line.split(",")]
        if len(f) == 6:
            try:
                rows.append((int(f[0]), f[1], float(f[2]), float(f[3]), float(f[4]), float(f[5])))
            except ValueError:
                pass
    return rows


def gpu_apps():
    try:
        out = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
                              "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return ""
    return "; ".join(" ".join(x.strip() for x in line.split(",")) + " MB" for line in out.splitlines() if line.strip())


def top_cpu(n=5):
    procs = []
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            procs.append((p.cpu_percent(None), p.pid, p.info["name"], " ".join(p.info["cmdline"] or [])[:120]))
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return sorted(procs, reverse=True)[:n]


# ---------------------------------------------------------------- incidents and report
class Incidents:
    """Deduplicated incidents: the same (kind, key) within 30 min extends one record instead of adding lines."""

    def __init__(self, dry_run=False):
        self.open = {}
        self.dry_run = dry_run

    def add(self, kind, key, detail):
        if self.dry_run:   # --dry-run: say what would be recorded, write nothing
            print(f"INCIDENT would be recorded: {kind} [{key}]: {detail}")
            return
        now = datetime.now().isoformat(timespec="seconds")
        rec = self.open.get((kind, key))
        if rec and (datetime.now() - datetime.fromisoformat(rec["last"])).total_seconds() < 1800:
            rec["last"] = now; rec["count"] += 1; rec["detail"] = detail
        else:
            rec = {"kind": kind, "key": key, "first": now, "last": now, "count": 1, "detail": detail}
            self.open[(kind, key)] = rec
            log.warning("INCIDENT %s [%s]: %s", kind, key, detail)
        self._rewrite()

    def _rewrite(self):
        """incidents.jsonl keeps closed records as written and replaces open ones by (kind, key, first)."""
        old = load_incidents()
        keys = {(r["kind"], r["key"], r["first"]) for r in self.open.values()}
        keep = [r for r in old if (r["kind"], r["key"], r["first"]) not in keys]
        cut = (datetime.now() - timedelta(days=30)).isoformat()
        rows = [r for r in keep if r["last"] >= cut] + list(self.open.values())
        tmp = INCIDENTS.with_suffix(".tmp")
        tmp.write_text("".join(json.dumps(r) + "\n" for r in sorted(rows, key=lambda r: r["first"])), encoding="utf-8")
        os.replace(tmp, INCIDENTS)


def load_incidents():
    try:
        return [json.loads(l) for l in INCIDENTS.read_text(encoding="utf-8").splitlines() if l.strip()]
    except (OSError, json.JSONDecodeError):
        return []


def write_report(status_lines):
    cut = (datetime.now() - timedelta(hours=REPORT_HOURS)).isoformat()
    inc = [r for r in load_incidents() if r["last"] >= cut]
    out = [f"# Resource watchdog report ({datetime.now():%Y-%m-%d %H:%M})", "", "## Now"] + [f"- {s}" for s in status_lines]
    out += ["", f"## Waste incidents, last {REPORT_HOURS} h ({len(inc)})"]
    if not inc:
        out.append("- none")
    for r in sorted(inc, key=lambda r: r["last"], reverse=True)[:40]:
        out.append(f"- **{r['kind']}** [{r['key']}] {r['first'][5:16]} -> {r['last'][5:16]} (x{r['count']}): {r['detail']}")
    try:   # 2-hourly new-reader check (new_reader_check.py), started from the loop in main()
        out += ["", READER_REPORT.read_text(encoding="utf-8").strip()]
    except OSError:
        pass
    try:
        out += ["", QUERY_SPEED_REPORT.read_text(encoding="utf-8").strip()]
    except OSError:
        pass
    try:
        b = json.loads(BOOT_STATUS.read_text(encoding="utf-8"))
        line = f"## Last boot recovery ({b.get('run_at')}, boot {b.get('boot')}, unclean shutdown {b.get('unclean_shutdown')})"
        lines = [line]
        if b.get("failed_checks"):
            lines.append(f"- **DATABASE CHECK FAILED {b['failed_checks']}: writer jobs NOT started**")
        started = [n for n, w in (b.get("readers") or []) + (b.get("writers") or []) if w == "started"]
        lines.append(f"- started: {started or 'none (all already running / finished)'}")
        out += [""] + lines
    except (OSError, ValueError, TypeError):
        pass
    try:   # background / weekly PRAGMA quick_check (boot_recover --full-check), 2026-10-20
        f = json.loads((LOGS / "db_full_check.json").read_text(encoding="utf-8"))
        msg = (f"**DATABASE FULL CHECK FAILED {f.get('failed')}; writers stopped {f.get('writers_stopped')}**"
               if f.get("state") == "FAILED" else f"{f.get('state')} (started {f.get('started')}, finished "
               f"{f.get('finished', '-')})")
        out += ["", f"## DB full check: {msg}"]
    except (OSError, ValueError, TypeError):
        pass
    tmp = REPORT.with_suffix(".tmp")
    tmp.write_text("\n".join(out) + "\n", encoding="utf-8")
    os.replace(tmp, REPORT)


def print_report():
    """For the Claude Code SessionStart hook: the report, plus a warning if the watchdog itself is not running."""
    alive = False
    try:
        pid = int(LOCK.read_text())
        alive = psutil.pid_exists(pid) and "resource_watchdog" in " ".join(psutil.Process(pid).cmdline())
    except (OSError, ValueError, psutil.Error):
        pass
    print("[Resource watchdog] Shivam asked that wasted compute (buggy code hogging disk/CPU/RAM, hung or orphaned jobs) "
          "is reported to him. Mention any incident below that is new or unexplained.")
    if not alive:
        print("WARNING: the resource watchdog is NOT running. Start it: "
              "wscript reality_engine\\scripts\\run_hidden.vbs reality_engine\\scripts\\run_resource_watchdog.cmd")
    try:
        age = (time.time() - REPORT.stat().st_mtime) / 60
        print(f"(report written {age:.0f} min ago)")
        print(REPORT.read_text(encoding="utf-8"))
    except OSError:
        print("no report yet")


def install_startup(profile_name=None):
    """Starts the watchdog at every logon via a script in the user's Startup folder (no admin rights needed).
    --profile also writes the machine profile the watchdog reads at start (the env var overrides it)."""
    if profile_name:
        LOGS.mkdir(parents=True, exist_ok=True)
        PROFILE_FILE.write_text(profile_name + "\n", encoding="utf-8")
        print(f"profile {profile_name} -> {PROFILE_FILE}")
    startup = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    vbs = startup / "reality_engine_resource_watchdog.vbs"
    vbs.write_text(f'CreateObject("Wscript.Shell").Run """{SCRIPTS / "run_resource_watchdog.cmd"}""", 0, False\r\n', encoding="utf-8")
    print(f"installed {vbs}")


# ---------------------------------------------------------------- main loop
def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(st):
    STATE.write_text(json.dumps(st, indent=1), encoding="utf-8")


def run(once=False, dry_run=False):
    if dry_run:
        logging.basicConfig(stream=sys.stdout, level=logging.INFO, format="%(message)s")
    else:
        LOGS.mkdir(parents=True, exist_ok=True)
        logging.basicConfig(filename=LOGS / "resource_watchdog.log", level=logging.INFO,
                            format="%(asctime)s %(levelname)s %(message)s")
        try:
            other = int(LOCK.read_text())
            if other != os.getpid() and psutil.pid_exists(other) and "resource_watchdog" in " ".join(psutil.Process(other).cmdline()):
                print(f"watchdog already running (pid {other})"); return
        except (OSError, ValueError, psutil.Error):
            pass
        LOCK.write_text(str(os.getpid()))
        if PROFILE == "pc":   # a monitor-only laptop decides its own sleep, so it is not pinned awake
            ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)   # keep the PC awake while it runs
        log.info("watchdog started (pid %d) profile %s", os.getpid(), PROFILE)
    inc, st = Incidents(dry_run), load_state()
    st.setdefault("jobs", {})
    disk_prev, io_prev, t_prev = psutil.disk_io_counters(), io_snapshot(), time.time()
    # a dry run starts no process at all, so the read-only probes (PowerShell labels, nvidia-smi) are skipped too
    perdisk_prev, labels = psutil.disk_io_counters(perdisk=True), ({} if dry_run else disk_labels())
    psutil.cpu_percent(None); top_cpu()
    if once:   # one check still needs an I/O sampling window (the 3-check streaks cannot fire on one sample)
        time.sleep(3)
    hog_streak, cpu_streak, busy_streak, gpu_streak = {}, 0, {}, {}
    while True:
        if not once:
            time.sleep(CHECK_SEC)
        now = time.time(); dt = max(now - t_prev, 0.001)
        disk, io = psutil.disk_io_counters(), io_snapshot()
        mbs = ((disk.read_bytes - disk_prev.read_bytes) + (disk.write_bytes - disk_prev.write_bytes)) / dt / 1e6
        ram = psutil.virtual_memory().available / 1e9
        cpu = psutil.cpu_percent(None)
        disk_lines, disk_low = disk_checks()
        for key, detail in disk_low:
            inc.add("low_disk", key, detail)
        status = [f"profile: {PROFILE}" + ("" if PROFILE == "pc" else " (monitor-only: nothing is started or restarted)"),
                  f"machine: CPU {cpu:.0f}% | RAM free {ram:.1f} GB ({psutil.virtual_memory().percent:.0f}% used) | "
                  + (f"disk {mbs:.0f} MB/s" if not once else "disk rate needs two checks")] + disk_lines

        # per physical disk: busy % catches random-I/O thrash that MB/s misses
        perdisk = psutil.disk_io_counters(perdisk=True)
        busy = disk_busy(perdisk_prev, perdisk, dt)
        perdisk_prev = perdisk
        status.append("disks: " + " | ".join(f"{labels.get(n, n)} busy {b:.0f}% {r:.1f} MB/s"
                                             for n, (b, r) in sorted(busy.items())))
        ops = {pid: ((v[3] - io_prev[pid][3]) / dt, v[0], v[1]) for pid, v in io.items()
               if pid in io_prev and len(v) > 3 and len(io_prev[pid]) > 3}
        for n, (b, r) in busy.items():
            busy_streak[n] = busy_streak.get(n, 0) + 1 if b >= DISK_BUSY_PCT else 0
            if busy_streak[n] >= 3:
                top = sorted(ops.items(), key=lambda kv: kv[1][0], reverse=True)[:3]
                inc.add("disk_busy", labels.get(n, n),
                        f"{b:.0f}% busy at only {r:.1f} MB/s for {busy_streak[n]} checks (random I/O?); top I/O ops: "
                        + "; ".join(f"{nm} pid {pid} {o:.0f} ops/s ({cmd[:100]})" for pid, (o, nm, cmd) in top))

        # GPU: utilisation, memory, temperature
        for idx, name, util, used, total, temp in ([] if dry_run else gpu_status()):
            status.append(f"gpu{idx} {name}: {util:.0f}% | mem {used:.0f}/{total:.0f} MB | {temp:.0f} C")
            gpu_streak[idx] = gpu_streak.get(idx, 0) + 1 if util >= GPU_BUSY_PCT else 0
            if gpu_streak[idx] >= 3:
                inc.add("gpu_hog", f"gpu{idx}", f"{util:.0f}% for {gpu_streak[idx]} checks, {temp:.0f} C; apps: {gpu_apps()}")
            if temp >= GPU_HOT_C:
                inc.add("gpu_hot", f"gpu{idx}", f"{temp:.0f} C at {util:.0f}% util; apps: {gpu_apps()}")

        # per-process disk hogs
        rates = {}
        for pid, (name, cmd, b, _ops) in io.items():
            if pid in io_prev:
                rates[pid] = ((b - io_prev[pid][2]) / dt / 1e6, name, cmd)
        for pid in list(hog_streak):
            if pid not in rates or rates[pid][0] < DISK_HOG_MBS:
                hog_streak.pop(pid)
        for pid, (r, name, cmd) in rates.items():
            if r >= DISK_HOG_MBS:
                hog_streak[pid] = hog_streak.get(pid, 0) + 1
                if hog_streak[pid] >= 3:
                    inc.add("disk_hog", f"{name} pid {pid}", f"{r:.0f} MB/s for {hog_streak[pid]} checks: {cmd}")

        cpu_streak = cpu_streak + 1 if cpu >= CPU_BUSY_PCT else 0
        tops = top_cpu()
        if cpu_streak >= 3:
            inc.add("cpu_hog", tops[0][2] if tops else "?", f"machine CPU {cpu:.0f}% for {cpu_streak} checks; top: "
                    + "; ".join(f"{n} pid {pid} {c:.0f}% ({cmd})" for c, pid, n, cmd in tops[:3]))
        if ram < LOW_RAM_GB:
            big = sorted(psutil.process_iter(["name", "memory_info"]),
                         key=lambda p: p.info["memory_info"].rss if p.info["memory_info"] else 0, reverse=True)[:5]
            inc.add("low_ram", "machine", f"{ram:.1f} GB free; largest: " + ", ".join(
                f"{p.info['name']} pid {p.pid} {p.info['memory_info'].rss / 1e9:.1f} GB" for p in big if p.info["memory_info"]))

        if time.time() - st.get("reader_drop_ts", 0) >= READER_DROP_EVERY_S:
            st["reader_drop_ts"] = time.time()
            for kind, where, text in reader_drops():
                inc.add(kind, where, text)

        for p in psutil.process_iter(["name"]):   # handle hogs fill the kernel's paged pool, invisible in RSS
            try:
                if p.num_handles() > HANDLE_HOG:
                    inc.add("handle_hog", f"{p.info['name']} pid {p.pid}",
                            f"{p.num_handles():,} handles: {' '.join(p.cmdline())[:150]}")
            except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
                pass

        orphans = orphan_workers()
        if orphans:
            inc.add("orphans_killed", "project", f"{'would kill' if dry_run else 'killed'} {len(orphans)} orphaned workers "
                    f"({sum(o.memory_info().rss for o in orphans) / 1e9:.1f} GB): {[o.pid for o in orphans]}")
            if not dry_run:
                for o in orphans:
                    kill_tree(o)

        for job in JOBS:
            js = st["jobs"].setdefault(job["name"], {"restarts": []})
            procs = job_procs(job)
            if procs:
                js["target"] = job_target(" ".join(procs[0].cmdline()))
            lines = log_tail(job["log"])
            has_log = job["log"].exists()
            age = (now - job["log"].stat().st_mtime) / 60 if has_log else 1e9
            rate = series_rate(lines, job["rate_re"]) if procs else None
            r2 = series_rate(lines, job["second_re"]) if procs and job.get("second_re") else None
            status.append(f"{job['name']}: {'running' if procs else 'not running'}"
                          + (f" | {rate:.1f} pages/s" if rate is not None else "")
                          + (f" | {r2 * 60:.0f} second readings/min" if r2 is not None else "")
                          + (f" | log age {age:.0f} min" if has_log else " | no log on this machine")
                          + (f" | {js['target']}" if procs else ""))
            if procs and rate is not None and rate < job["slow_rate"] and age < job["stale_min"] and not (r2 and r2 > 0.05):
                inc.add("job_slow", job["name"], f"{rate:.1f} pages/s (10 min); disk {mbs:.0f} MB/s, CPU {cpu:.0f}%, "
                        f"RAM free {ram:.1f} GB; {deck_diagnosis(lines)}")
            fault = None
            if not procs:
                ex = last_exit(job["passes"])
                if ex != job["done_exit"]:
                    fault = ("job_stopped", f"not running, last pass exit {ex}" if ex is not None
                             else "not running (no pass log on this machine)")
            elif age >= job["stale_min"]:
                fault = ("job_hung", f"log silent {age:.0f} min")
            # 2026-10-12: the AR run froze inside a C call for 4 h while each restart still wrote a log line, so a fresh
            # log is not proof of work: no pages (and no second readings) for STUCK_MIN also counts as hung
            busy = (rate or 0) > 0 or (r2 or 0) > 0
            if procs and rate is not None and not busy and not job.get("idle_ok"):
                js.setdefault("zero_since", now)
                if not fault and now - js["zero_since"] >= STUCK_MIN * 60:
                    fault = ("job_hung", f"no pages read for {(now - js['zero_since']) / 60:.0f} min (log still written)")
                    js["zero_since"] = now
            else:
                js.pop("zero_since", None)
            if fault:
                restart_or_report(job, js, procs, fault, now, inc, dry_run)
        if time.time() - st.get("reader_check_ts", 0) >= READER_CHECK_EVERY_S:
            st["reader_check_ts"] = time.time()
            why = blocked_reason(SIDE_JOBS["new-reader-check"])
            if why:
                status.append(f"new-reader-check: not started ({why})")
            elif dry_run:
                status.append("new-reader-check: would start")
            else:
                subprocess.Popen([sys.executable, "-m", "reality_engine.scripts.new_reader_check"], cwd=ROOT,
                                 stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                 creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
                log.info("new-reader check started")
        why = blocked_reason(SIDE_JOBS["ar-review"])
        if why:   # refused before the DB is even opened: on a laptop there are no AR facts to review
            status.append(f"ar-review: not started ({why})")
        else:
            try:   # AR extraction review after every AR_REVIEW_EVERY newly finished reports (ar_review.py)
                import sqlite3
                con = sqlite3.connect(f"file:{ROOT / 'reality_engine' / 'data' / 'ar_facts.db'}?mode=ro", uri=True, timeout=30)
                done_n = con.execute("SELECT COUNT(*) FROM ar_docs WHERE status='done'").fetchone()[0]; con.close()
                # 2026-10-14: with Cat Jam 200 reports finish in ~4 min, faster than one review runs; three reviews piled up
                # (a core each, reading ar_facts.db) and the main run fell from ~950 to ~120 pages/min. One review at a time,
                # at most hourly.
                running = any("reality_engine.scripts.ar_review" in " ".join(p.info["cmdline"] or [])
                              for p in psutil.process_iter(["cmdline"]))
                if (done_n >= st.get("ar_review_at", 0) + AR_REVIEW_EVERY and not running
                        and time.time() - st.get("ar_review_ts", 0) >= 12 * 3600):   # 2026-10-15: a run scans all facts (a core +
                    # ~0.9 GB for 30+ min, and its long read blocks the WAL checkpoint: WAL grew to ~1 GB); twice a day is enough
                    st["ar_review_at"] = done_n; st["ar_review_ts"] = time.time()
                    if dry_run:
                        status.append(f"ar-review: would start at {done_n} finished reports")
                    else:
                        subprocess.Popen([sys.executable, "-m", "reality_engine.scripts.ar_review"], cwd=ROOT,
                                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                                         | subprocess.BELOW_NORMAL_PRIORITY_CLASS)
                        log.info("AR review started at %d finished reports", done_n)
            except Exception as e:
                log.warning("AR review trigger failed: %s", e)
        if dry_run:
            print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] one check, nothing written")
            print("\n".join(status))
        else:
            save_state(st)
            log.info(" || ".join(status))
            write_report(status)
        disk_prev, io_prev, t_prev = disk, io, now
        if once:
            return


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print the report (used by the Claude Code SessionStart hook)")
    ap.add_argument("--install-startup", action="store_true", help="start the watchdog at every logon")
    ap.add_argument("--profile", choices=("pc", "laptop"), help="with --install-startup: machine profile to write")
    ap.add_argument("--once", action="store_true", help="do one check and exit")
    ap.add_argument("--dry-run", action="store_true", help="print what would be done and act on nothing (implies --once)")
    a = ap.parse_args()
    if a.report:
        print_report()
    elif a.install_startup:
        install_startup(a.profile)
    else:
        try:
            run(once=a.once or a.dry_run, dry_run=a.dry_run)
        except Exception:
            log.exception("watchdog crashed")
            sys.exit(1)
