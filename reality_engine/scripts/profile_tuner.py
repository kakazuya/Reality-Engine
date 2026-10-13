"""Overnight profile tuner (2026-10-13, Shivam: "do the same for the Zen models when they come back"). Runs detached
(run_profile_tuner.cmd) until every pending exhaustive-prompt test is decided, then exits.

For each pending test (TESTS below): keep an `ar_queue drive` running for it (Zen tests start only when Zen answers again);
when every piece is answered or failed, score it (ar_queue.test_score). PASS = must-find 25/25, numbers not in the text
< 1%, regrouped numbers < 0.5%, unanswered pieces <= 2%, and more facts than the model's plain-prompt baseline. A pass
switches the model's profile to prompt "exhaustive" (reader_profiles.json) and restarts the worker that uses it (its
launcher loop brings it back with the new profile). Every decision goes to tasks/ar_study/READER_FINDINGS.md and
reality_engine/data/logs/profile_tuner.log.
"""
import json
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import psutil

from reality_engine.scripts import ar_queue

ROOT = Path(__file__).resolve().parents[2]
PROFILES = Path(__file__).with_name("reader_profiles.json")
FINDINGS = ROOT / "tasks" / "ar_study" / "READER_FINDINGS.md"
LOG = ROOT / "reality_engine" / "data" / "logs" / "profile_tuner.log"
# run, profile key(s) switched on a pass, worker process marker restarted, plain-prompt baseline facts, needs Zen
DONE_ALREADY = {"t-g31-ex", "t-lcgo-ex"}   # decided by Claude 2026-10-13 06:55 (see READER_FINDINGS.md)
TESTS = [
    ("t-g31-ex", ["gemma-4-31b-it"], "scripts.ingest_annual_reports ", 2638, False),
    ("t-lcgo-ex", ["longcat-2.5-preview-free", "longcat-2.5-preview-free@zen"], "scripts.ingest_annual_reports ", 2000, False),
    ("t-bunny-ex", ["space-bunny-free"], "--route zen", 9872, True),
    ("t-muse13-ex", ["muse-spark-1.3-contributor-free"], "--route zen", 5080, True),
    ("t-pickle-ex", ["big-pickle"], "--route zen", 9459, True),
]
WORKERS = {"t-g31-ex": 6, "t-lcgo-ex": 6, "t-bunny-ex": 2, "t-muse13-ex": 2, "t-pickle-ex": 2}


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def finding(msg):
    with open(FINDINGS, "a", encoding="utf-8") as f:
        f.write(f"- {datetime.now():%Y-%m-%d %H:%M} (profile_tuner) {msg}\n")


def driving(run):
    for p in psutil.process_iter(["cmdline"]):
        c = p.info["cmdline"] or []
        if "drive" in c and "--run" in c and run in c[c.index("--run") + 1].split(","):
            return True
    return False


def start_drive(run):
    # .err.txt pieces are retried by a new drive; remove them so the run can finish cleanly
    for f in (ar_queue.QUEUE / run).glob("*.err.txt"):
        f.unlink()
    subprocess.Popen([sys.executable, "-m", "reality_engine.scripts.ar_queue", "drive", "--run", run,
                      "--workers", str(WORKERS[run])], cwd=ROOT, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
    log(f"drive started: {run}")


def zen_answers():
    try:
        p = subprocess.run([ar_queue.opencode_exe(), "run", "-m", "opencode/big-pickle", "--title", "tuner zen probe",
                            "Reply with exactly: ok"], stdin=subprocess.DEVNULL, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=120)
        return bool(re.search(r"(^|\s)ok(\s|$)", ar_queue.ANSI.sub("", p.stdout), re.I))
    except Exception:
        return False


def counts(run):
    d = ar_queue.QUEUE / run
    return (len(list(d.glob("*.prompt.txt"))), len(list(d.glob("*.out.txt"))), len(list(d.glob("*.err.txt"))))


def score(run):
    ar_queue.test_score(run)
    t = (ar_queue.QUEUE / run / "SCORE.md").read_text(encoding="utf-8")
    g = lambda pat: re.search(pat, t)
    mf = g(r"Must-find (\d+)/(\d+)"); nf = g(r"not in the text (\d+)/(\d+)"); fx = g(r"Facts extracted (\d+)")
    rg = g(r"REGROUPED numbers (\d+)/(\d+)"); un = g(r"without an answer (\d+)/(\d+)")
    return {"must": (int(mf.group(1)), int(mf.group(2))), "nf": int(nf.group(1)) / max(1, int(nf.group(2))),
            "facts": int(fx.group(1)), "regroup": int(rg.group(1)) / max(1, int(rg.group(2))),
            "unans": int(un.group(1)) / max(1, int(un.group(2))), "line": t.splitlines()[4] if len(t.splitlines()) > 4 else ""}


def restart_worker(marker):
    n = 0
    for p in psutil.process_iter(["name", "cmdline"]):
        c = " ".join(p.info["cmdline"] or [])
        if (p.info["name"] or "").lower() == "python.exe" and "ingest_annual_reports" in c:
            is_zen = "--route zen" in c; is_google = "--route google" in c
            if (marker == "--route zen" and is_zen) or (marker.endswith("ingest_annual_reports ") and not is_zen and not is_google):
                p.kill(); n += 1   # its run_ar_*.cmd loop restarts it in 30 s with the new profile
    return n


def main():
    pending = {t[0]: t for t in TESTS if t[0] not in DONE_ALREADY}
    zen_live, last_zen_check, rounds, last_retry = False, 0, {}, {}
    log("tuner started: " + ", ".join(pending))
    deadline = time.time() + 36 * 3600
    while pending and time.time() < deadline:
        if not zen_live and time.time() - last_zen_check > 1200 and any(t[4] for t in pending.values()):
            last_zen_check = time.time(); zen_live = zen_answers()
            log(f"zen probe: {'answering' if zen_live else 'still refused'}")
        for run, (_, keys, marker, base, needs_zen) in list(pending.items()):
            if run in ("t-g31-ex", "t-lcgo-ex") and rounds.get(run, 0) == 0 and driving(run):
                rounds[run] = 1   # already driven by the session that started the tuner
            if needs_zen and not zen_live:
                continue
            total, out, err = counts(run)
            if driving(run):
                continue
            # pieces that failed on a rate limit are not a model failure: wait for quota (Zen: next 00:00 UTC reset)
            # instead of scoring (2026-10-13: Space Bunny was failed with 9 pieces unanswered while Zen was out)
            limited = [f for f in (ar_queue.QUEUE / run).glob("*.err.txt")
                       if re.search(r"rate limit|429|quota", f.read_text(encoding="utf-8", errors="replace"), re.I)]
            if limited:
                if time.time() - last_retry.get(run, 0) > 3600:
                    last_retry[run] = time.time()
                    if not needs_zen or zen_live:
                        start_drive(run)
                continue
            if out < total and rounds.get(run, 0) < 3:   # (re)start the drive; at most 3 rounds, then score as is
                rounds[run] = rounds.get(run, 0) + 1; start_drive(run); continue
            s = score(run)
            ok = (s["must"][0] == s["must"][1] and s["nf"] < 0.01 and s["regroup"] < 0.005 and s["unans"] <= 0.02
                  and s["facts"] > base)
            verdict = (f"{run} ({', '.join(keys)}) exhaustive prompt: {'PASS' if ok else 'FAIL'} - must-find {s['must'][0]}/{s['must'][1]}, "
                       f"facts {s['facts']} (plain baseline {base}), not in text {s['nf']:.2%}, regrouped {s['regroup']:.2%}, "
                       f"unanswered {s['unans']:.1%}")
            log(verdict); finding(verdict)
            if ok:
                prof = json.loads(PROFILES.read_text(encoding="utf-8"))
                for k in keys:
                    if k in prof["models"]:
                        prof["models"][k]["prompt"] = "exhaustive"
                        prof["models"][k]["test"] += f"; exhaustive PASS {datetime.now():%Y-%m-%d %H:%M} ({s['facts']} facts)"
                PROFILES.write_text(json.dumps(prof, indent=2) + "\n", encoding="utf-8")
                n = restart_worker(marker)
                log(f"profile switched to exhaustive for {keys}; restarted {n} worker process(es)")
                finding(f"profile switched to exhaustive for {', '.join(keys)}; worker restarted")
            del pending[run]
        time.sleep(300)
    log("tuner finished" + (f"; undecided: {list(pending)}" if pending else ""))


if __name__ == "__main__":
    main()
