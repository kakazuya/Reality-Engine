"""Machine-wide resource watchdog: keeps the long jobs alive and records every case of wasted compute.

Runs permanently (started at logon from the Windows Startup folder, see install_startup()). Every CHECK_SEC it:
  - keeps each managed job (JOBS) alive: restarts it with the same command line it last ran with if it stopped
    without finishing, or if its log went silent for the job's stale_min (hung); restarts are rate-limited
  - kills orphaned multiprocessing workers left in this project's folder by a dead parent
    (2026-10-10: 16 orphaned render workers at ~3 GB commit each pushed RAM to 98%)
  - records WASTE INCIDENTS, naming the process and the numbers:
      disk_hog    one process reading/writing more than DISK_HOG_MBS for 3 checks in a row
                  (2026-10-11: the extractor re-read its 5 GB queue every second, ~135 MB/s, run fell to 0.4 pages/s)
      cpu_hog     machine CPU above CPU_BUSY_PCT for 3 checks; the top processes are named
      low_ram     available RAM under LOW_RAM_GB; the largest processes are named
      job_slow    a managed job below its slow_rate, with what the job itself was waiting on (readers idle or full)
      job_hung / job_stopped / orphans_killed / restart_limit
It never kills anything except orphans in this project and the managed jobs it restarts.

Output (all in reality_engine/data/logs/):
  resource_watchdog.log            one status line per check plus every action
  resource_incidents.jsonl         one JSON line per incident (kind, first/last seen, count, details)
  resource_watchdog_report.md      rolling report (current status + incidents of the last 48 h); a Claude Code
                                   SessionStart hook prints it into every new session (print_report())

Start now:   wscript reality_engine\\scripts\\run_hidden.vbs reality_engine\\scripts\\run_resource_watchdog.cmd
Report:      python -m reality_engine.scripts.resource_watchdog --report
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
RESTART_GAP_MIN = 30
MAX_RESTARTS_PER_DAY = 6
LOW_RAM_GB = 1.5
DISK_HOG_MBS = 50
CPU_BUSY_PCT = 90
REPORT_HOURS = 48

# Managed jobs. `match`: text in the cmd.exe command line; `log`: the job's own log (staleness, rate);
# `done_exit`: the last line of `passes` ends with this exit code when the job has nothing left to do.
JOBS = [
    {"name": "deck-extract", "match": "run_deck_", "log": LOGS / "extract_deck_figures.log",
     "passes": LOGS / "extract_deck_figures.passes.log", "done_exit": 0, "stale_min": 20, "slow_rate": 2.0,
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO pages (\d+) ",
     "second_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO pages .*?second reads (\d+)"},
    # annual-report fact extraction (2026-10-12); rate = report pages read per second
    {"name": "ar-ingest", "match": "run_ar_ingest", "log": LOGS / "ingest_annual_reports.log",
     "passes": LOGS / "ingest_annual_reports.passes.log", "done_exit": 0, "stale_min": 20, "slow_rate": 1.0,
     "rate_re": r"(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d),\d+ INFO ar docs .*? pages (\d+) "},
]

log = logging.getLogger("resource_watchdog")


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


def orphan_workers():
    """multiprocessing children whose parent is gone, running in this project's folder."""
    out = []
    for p in psutil.process_iter(["name", "cmdline", "ppid"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if (p.info["name"] or "").lower() != "python.exe" or "multiprocessing.spawn" not in cmd:
                continue
            m = re.search(r"parent_pid=(\d+)", cmd)
            if psutil.pid_exists(int(m.group(1)) if m else p.info["ppid"]):
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


def start_cmd(cmdline_target):
    """Launch a .cmd (with arguments) hidden and detached, with the saved user environment."""
    wrapper = LOGS / "resource_watchdog_restart.cmd"
    # through a child cmd.exe, so the job's own command line (which job_procs() matches) is visible to the next check
    wrapper.write_text(f'@echo off\r\ncd /d "{ROOT}"\r\ncmd /c {cmdline_target}\r\n', encoding="utf-8")
    subprocess.Popen(["wscript.exe", str(HIDDEN_VBS), str(wrapper)], cwd=str(ROOT), env=user_env(),
                     creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)


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
            snap[p.pid] = (p.info["name"], " ".join(p.info["cmdline"] or [])[:160], c.read_bytes + c.write_bytes)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass
    return snap


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

    def __init__(self):
        self.open = {}

    def add(self, kind, key, detail):
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


def install_startup():
    """Starts the watchdog at every logon via a script in the user's Startup folder (no admin rights needed)."""
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


def run():
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
    ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)   # keep the PC awake while it runs
    log.info("watchdog started (pid %d)", os.getpid())
    inc, st = Incidents(), load_state()
    st.setdefault("jobs", {})
    disk_prev, io_prev, t_prev = psutil.disk_io_counters(), io_snapshot(), time.time()
    psutil.cpu_percent(None); top_cpu()
    hog_streak, cpu_streak = {}, 0
    while True:
        time.sleep(CHECK_SEC)
        now = time.time(); dt = now - t_prev
        disk, io = psutil.disk_io_counters(), io_snapshot()
        mbs = ((disk.read_bytes - disk_prev.read_bytes) + (disk.write_bytes - disk_prev.write_bytes)) / dt / 1e6
        ram = psutil.virtual_memory().available / 1e9
        cpu = psutil.cpu_percent(None)
        status = [f"machine: CPU {cpu:.0f}% | RAM free {ram:.1f} GB | disk {mbs:.0f} MB/s"]

        # per-process disk hogs
        rates = {}
        for pid, (name, cmd, b) in io.items():
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

        orphans = orphan_workers()
        if orphans:
            inc.add("orphans_killed", "project", f"killed {len(orphans)} orphaned workers "
                    f"({sum(o.memory_info().rss for o in orphans) / 1e9:.1f} GB): {[o.pid for o in orphans]}")
            for o in orphans:
                kill_tree(o)

        for job in JOBS:
            js = st["jobs"].setdefault(job["name"], {"restarts": []})
            procs = job_procs(job)
            if procs:
                js["target"] = job_target(" ".join(procs[0].cmdline()))
            lines = log_tail(job["log"])
            age = (now - job["log"].stat().st_mtime) / 60 if job["log"].exists() else 1e9
            rate = series_rate(lines, job["rate_re"]) if procs else None
            r2 = series_rate(lines, job["second_re"]) if procs and job.get("second_re") else None
            status.append(f"{job['name']}: {'running' if procs else 'not running'}"
                          + (f" | {rate:.1f} pages/s" if rate is not None else "")
                          + (f" | {r2 * 60:.0f} second readings/min" if r2 is not None else "")
                          + f" | log age {age:.0f} min" + (f" | {js['target']}" if procs else ""))
            if procs and rate is not None and rate < job["slow_rate"] and age < job["stale_min"] and not (r2 and r2 > 0.05):
                inc.add("job_slow", job["name"], f"{rate:.1f} pages/s (10 min); disk {mbs:.0f} MB/s, CPU {cpu:.0f}%, "
                        f"RAM free {ram:.1f} GB; {deck_diagnosis(lines)}")
            fault = None
            if not procs:
                ex = last_exit(job["passes"])
                if ex != job["done_exit"] and js.get("target"):
                    fault = ("job_stopped", f"not running, last pass exit {ex}")
            elif age >= job["stale_min"]:
                fault = ("job_hung", f"log silent {age:.0f} min")
            if fault:
                day = [t for t in js["restarts"] if now - t < 86400]
                js["restarts"] = day
                if len(day) >= MAX_RESTARTS_PER_DAY:
                    inc.add("restart_limit", job["name"], f"{fault[1]}; {len(day)} restarts in 24 h, left for a human")
                elif day and now - day[-1] < RESTART_GAP_MIN * 60:
                    pass
                else:
                    inc.add(fault[0], job["name"], f"{fault[1]}; restarting: {js['target']}")
                    for p in procs:
                        kill_tree(p)
                    time.sleep(5)
                    for o in orphan_workers():
                        kill_tree(o)
                    start_cmd(js["target"])
                    js["restarts"].append(time.time())
        save_state(st)
        log.info(" || ".join(status))
        write_report(status)
        disk_prev, io_prev, t_prev = disk, io, now


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="print the report (used by the Claude Code SessionStart hook)")
    ap.add_argument("--install-startup", action="store_true", help="start the watchdog at every logon")
    a = ap.parse_args()
    if a.report:
        print_report()
    elif a.install_startup:
        install_startup()
    else:
        try:
            run()
        except Exception:
            log.exception("watchdog crashed")
            sys.exit(1)
