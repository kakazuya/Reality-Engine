"""Run one task headlessly in DeepSeek Harness (dsh) on an OpenCode Go model, so a Claude orchestrator can use it
as a worker.

    python -m reality_engine.scripts.run_deepseek_harness --model beam-free \
        --task-file task.md --out-file out.md [--cwd DIR] [--timeout 900] [--account 1|2] [--permission read-only]

dsh is installed with bun (`bun add -g @deepseek-ai/dsh`, Shivam 2026-10-20: bun only, never npm). Go needs an
`x-opencode-session: <uuid>` header on every request (else 400 MissingSessionID). dsh's pi-ai provider route takes
`headers`, so each run writes a temporary `--patch` overlay that declares an `opencode-go` route with a fresh uuid
and selects the model. The key is read from the Windows user env (OPENCODE_GO_API_KEY or _2) and never printed.

The task goes in on stdin and the final answer goes to --out-file. dsh's stderr (reasoning, `dsh: <code>` errors) goes
to <out-file>.log. The exit code is dsh's (0 = task completed, 1 = failed), 124 = timed out (process tree killed),
1 also for a refused setup (unknown/paid model, missing key), 2 = argparse usage error.
Model ids: beam-free, longcat-2.5-preview-free, minimax-m3.1-flash-free (free); deepseek-v4.1-flash is PAID on Go
and needs --allow-paid. `<id>~<effort>` sets reasoning effort (low/medium/high/xhigh/max); MiniMax defaults to
low because at default effort it can reason through its whole output budget and answer empty.
DeepSeek models always run at xhigh (Shivam 2026-10-20: never max, never below xhigh), and only off-peak: 15:30 to
06:30 IST. Outside that window a DeepSeek run is refused unless --peak-ok is passed after Shivam confirms the timing.
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reality_engine.scripts.resource_watchdog import user_env
from reality_engine.scripts.go_session import session_id   # stable x-opencode-session (Shivam's rule 2026-10-20)

DSH = Path.home() / ".bun" / "bin" / "dsh.exe"
REPO = Path(__file__).resolve().parents[2]
BASE_URL = "https://opencode.ai/zen/go/v1"
FREE = {"beam-free", "longcat-2.5-preview-free", "minimax-m3.1-flash-free"}
PAID = {"deepseek-v4.1-flash"}
REASONING = {"minimax-m3.1-flash-free": "low", "deepseek-v4.1-flash": "xhigh"}   # models that take reasoning_effort
FIXED_EFFORT = {m: "xhigh" for m in REASONING if m.startswith("deepseek")}   # DeepSeek: xhigh only
IST = timezone(timedelta(hours=5, minutes=30))


def off_peak(now=None):
    """Shivam's off-peak window for DeepSeek runs: 15:30 to 06:30 IST."""
    t = (now or datetime.now(IST)).astimezone(IST).time()
    return t >= datetime.strptime("15:30", "%H:%M").time() or t < datetime.strptime("06:30", "%H:%M").time()
EFFORTS = ("low", "medium", "high", "xhigh", "max")
KEY_ENV = {"1": "OPENCODE_GO_API_KEY", "2": "OPENCODE_GO_API_KEY_2"}


def build_patch(model, effort, key_env):
    """YAML overlay: an opencode-go route with a fresh session header, and the default model set to `model`."""
    if model in REASONING:
        efforts = "\n".join(f"              {e}: {e}" for e in EFFORTS)
        entry = f"          - id: {model}\n            reasoningEfforts:\n{efforts}"
    else:
        entry = f"          - id: {model}\n            reasoningEfforts: false"
    sel = f"    reasoningEffort: {effort}\n" if effort else ""
    return (f"- id: llm-pi-ai\n  config:\n    providers:\n      opencode-go:\n"
            f"        displayName: OpenCode Go\n        apiKeyEnv: {key_env}\n        api: openai-completions\n"
            f"        baseURL: {BASE_URL}\n        headers:\n          x-opencode-session: {session_id("dsh", model, key_env)}\n"
            f"        models:\n{entry}\n"
            f"- id: agent-default-model\n  config:\n    provider: opencode-go\n    model: {model}\n{sel}")


def kill_tree(pid):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--model", required=True, help="Go model id, optionally <id>~<effort>")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--task-file")
    g.add_argument("--task", help="task text inline (one orchestrator call, no task file to write first)")
    ap.add_argument("--out-file", required=True)
    ap.add_argument("--cwd", default=str(REPO), help="workspace root the agent works in (default: repo root)")
    ap.add_argument("--timeout", type=int, default=900, help="seconds before the run is killed (exit 124)")
    ap.add_argument("--account", choices=("1", "2"), default="2", help="which OpenCode Go key (default 2; account 1 is exhausted)")
    ap.add_argument("--permission", choices=("read-only", "workspace-write", "danger-full-access"),
                    default="read-only", help="dsh sandbox mode (default read-only: workers read, Claude writes)")
    ap.add_argument("--allow-paid", action="store_true", help="allow a paid Go model (needs Shivam's go-ahead)")
    ap.add_argument("--peak-ok", action="store_true",
                    help="run a DeepSeek model outside 15:30-06:30 IST (only after Shivam confirms the timing)")
    ap.add_argument("--no-refresh", action="store_true", help="skip rebuilding the hotline context files")
    a = ap.parse_args()

    model, _, effort = a.model.partition("~")
    if model not in FREE | PAID:
        sys.exit(f"unknown Go model {model!r}; known: {sorted(FREE | PAID)}")
    if model in PAID and not a.allow_paid:
        sys.exit(f"{model} is PAID on Go; pass --allow-paid only with Shivam's approval")
    if model in FIXED_EFFORT and effort and effort != FIXED_EFFORT[model]:
        sys.exit(f"{model} always runs at {FIXED_EFFORT[model]} (Shivam's rule); drop ~{effort}")
    if model.startswith("deepseek") and not off_peak() and not a.peak_ok:
        sys.exit(f"{datetime.now(IST):%H:%M} IST is outside the DeepSeek off-peak window (15:30-06:30 IST); "
                 "ask Shivam, then pass --peak-ok if he confirms")
    if effort and (model not in REASONING or effort not in EFFORTS):
        sys.exit(f"effort {effort!r} not valid for {model}")
    effort = effort or REASONING.get(model)
    task = a.task if a.task is not None else Path(a.task_file).read_text(encoding="utf-8")
    if not task.strip():
        sys.exit("task file is empty")
    if not DSH.exists():
        sys.exit(f"dsh not found at {DSH}; install with: bun add -g @deepseek-ai/dsh")

    env = user_env()
    key_env = KEY_ENV[a.account]
    if not env.get(key_env):
        sys.exit(f"{key_env} is not set")
    env["DSH_PERMISSION_MODE"] = a.permission

    # hotline (Shivam 2026-10-20): refresh the shared context before every run, so the worker reads the whole
    # conversation (session_digest) and the live machine state (worker_context), not a stale or empty picture.
    # ~/.dsh/AGENTS.md tells dsh to read tasks/hotline/ first. Failures here never block the task.
    if not a.no_refresh:
        root = Path(__file__).resolve().parents[2]
        for mod in ("session_digest", "worker_context"):
            subprocess.run([sys.executable, "-m", f"reality_engine.scripts.{mod}"], cwd=root, capture_output=True,
                           timeout=300)

    out = Path(a.out_file)
    out.parent.mkdir(parents=True, exist_ok=True)
    log = out.with_name(out.name + ".log")
    with tempfile.NamedTemporaryFile("w", suffix=".yml", delete=False, encoding="utf-8") as f:
        f.write(build_patch(model, effort, key_env))
        patch = f.name
    t0 = time.time()
    try:
        p = subprocess.Popen([str(DSH), "--profile", "headless", "--patch", patch, "-"], cwd=a.cwd, env=env,
                             stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             text=True, encoding="utf-8", errors="replace")
        try:
            stdout, stderr = p.communicate(task, timeout=a.timeout)
            rc = p.returncode
        except subprocess.TimeoutExpired:
            kill_tree(p.pid)
            stdout, stderr = p.communicate()
            stderr += f"\nrun_deepseek_harness: timed out after {a.timeout} s, process tree killed\n"
            rc = 124
    finally:
        os.unlink(patch)
    secs = time.time() - t0
    out.write_text(stdout, encoding="utf-8")
    log.write_text(f"model={model} effort={effort} account={a.account} permission={a.permission} "
                   f"cwd={a.cwd} rc={rc} secs={secs:.0f}\n{stderr}", encoding="utf-8")
    print(f"rc={rc} secs={secs:.0f} out={out} ({len(stdout)} chars) log={log}")
    if rc:
        tail = [ln for ln in stderr.splitlines() if ln.startswith(("dsh:", "run_deepseek_harness:"))
                and not ln.startswith("dsh: reasoning")]
        print("\n".join(tail[-3:]), file=sys.stderr)
    sys.exit(rc)


if __name__ == "__main__":
    main()
