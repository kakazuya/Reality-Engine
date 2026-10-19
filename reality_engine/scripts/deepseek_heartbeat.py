"""DeepSeek heartbeat (Shivam, 2026-10-20): wakes DeepSeek, never Claude. Run hourly by the Windows task
RealityEngine-DeepSeekHeartbeat (scripts/run_deepseek_heartbeat.cmd); no Claude session is involved.

1. Mechanical, no LLM, every hour: if a transcript reader (Beam / MiniMax, prompt v3) is not running and its log does not
   end in RUN_COMPLETE, restart it with the same command (hidden, detached). Logged to the hotline.
2. Off-peak only (15:30-06:30 IST, Shivam's DeepSeek rule): run DeepSeek (dsh, xhigh, account 2) with the heartbeat brief:
   check the jobs, spot-check fresh reader output, append one status entry to data/hotline/hotline.md. If something needs
   the orchestrator (a decision, a fix DeepSeek may not make, a repeated failure), DeepSeek writes
   data/hotline/needs_claude.md; the next Claude session reads that first (DeepSeek cannot open a Claude session).

    python -m reality_engine.scripts.deepseek_heartbeat [--no-llm]
"""
import argparse
import datetime as dt
import subprocess
import sys
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[2]
LOGS = ROOT / "reality_engine/data/logs"
HOT = ROOT / "reality_engine/data/hotline"
PY = sys.executable.replace("pythonw.exe", "python.exe")
KEYS = "OPENCODE_GO_API_KEY,OPENCODE_GO_API_KEY_2"
READERS = {   # name: (model, args, reader log)
    "beam": ("beam-free", "--shard 1,2,3/4 --workers 32", "concall_beam-free.log"),
    "minimax": ("minimax-m3.1-flash-free~high", "--shard 0/4 --workers 16 --max-out 64000",
                "concall_minimax-m3.1-flash-free.log"),
}
BRIEF = """Heartbeat (hourly, you are DeepSeek; Claude is NOT running). Read reality_engine/data/hotline/README.md, then
generated/context_now.md and the newest entries of hotline.md. Check: (1) Beam and MiniMax transcript readers
(concall_facts.db cc_docs: ok / error / error_json counts and seconds in the last hour per model, prompt v3 in
checks_json, vq_checked present); (2) the other jobs in context_now (embeddings, Drive upload, PIB) for stalls or
errors; (3) spot-check 3 items from 2 docs read in the last hour against the source transcript for meaning (scope,
analyst-only numbers, period, direction), the review_readers_2.md way. Append ONE short entry to hotline.md
('### <time IST> DeepSeek heartbeat': rates, errors, spot-check verdict). If anything needs Claude (a decision, a code
fix, the same failure twice, material errors in the spot-check), also write reality_engine/data/hotline/needs_claude.md
(overwrite): what, evidence, what you propose. Do not edit code, databases or running jobs. Keep the entry under 12 lines."""


def ist():
    return dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30)))


def note(text):
    with (HOT / "hotline.md").open("a", encoding="utf-8") as f:
        f.write(f"\n### {ist():%Y-%m-%d %H:%M} IST heartbeat (script)\n{text}\n")


def running(model):
    for p in psutil.process_iter(["name", "cmdline"]):
        try:
            cmd = " ".join(p.info["cmdline"] or [])
            if "concall_deepseek" in cmd and f"--model {model}" in cmd:
                return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def last_line(log):
    f = LOGS / log
    if not f.exists():
        return ""
    lines = f.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    return lines[-1] if lines else ""


def restart_dead_readers():
    for name, (model, extra, log) in READERS.items():
        if running(model) or "RUN_COMPLETE" in last_line(log):
            continue
        args = (f'"{PY}" -u -m reality_engine.scripts.concall_deepseek --model {model} --prompt prompt_v3.md '
                f'--reread-models {model} --since 2000-01-01 --all-companies --keys {KEYS} {extra} '
                f'>> reality_engine\\data\\logs\\concall_{name}.out.log 2>> reality_engine\\data\\logs\\concall_{name}.err.log')
        subprocess.Popen(["conhost.exe", "--headless", "cmd.exe", "/c", args], cwd=ROOT,
                         creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP)
        note(f"{name} reader ({model}) was not running and not complete; restarted. Last log line: {last_line(log)[:200]}")


def off_peak():
    t = ist().time()
    return t >= dt.time(15, 30) or t < dt.time(6, 30)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true")
    a = ap.parse_args()
    restart_dead_readers()
    if a.no_llm or not off_peak():
        return
    out = ROOT / f"reality_engine/data/dsh_tasks/heartbeat_{ist():%Y%m%d_%H%M}.md"
    subprocess.run([PY, "-m", "reality_engine.scripts.run_deepseek_harness", "--model", "deepseek-v4.1-flash",
                    "--allow-paid", "--permission", "workspace-write", "--timeout", "1500", "--out-file", str(out),
                    "--task", BRIEF], cwd=ROOT, timeout=1800)


if __name__ == "__main__":
    main()
