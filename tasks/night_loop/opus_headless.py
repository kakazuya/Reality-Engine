"""Opus 5.5 headless analysis session on the Wolf account (Shivam, 10 Nov 2026: spare usage goes to the hardest
reading/judgement work DeepSeek cannot do alone). Ops script, not product code.

  python tasks/night_loop/opus_headless.py start <name> <brief.md> [--hours 3]
  python tasks/night_loop/opus_headless.py status <name>

No worktree and no code edits: the session reads stores read-only (MCP reality-data, p3ask, sqlite read-only) and writes
only the output files its brief names, under D:/RealityEngine/reports or D:/RealityEngine/night_loop/opus/<name>/.
Launched hidden through Win32_Process.Create so it survives the caller. Transcript, log, status and the final answer
go to D:/RealityEngine/night_loop/opus/<name>/. Not a code worker slot (it changes no code).
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = Path(r"D:\RealityEngine\night_loop\opus")
MODEL = "claude-opus-5-5"


def _dir(name):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def start(name, brief, hours):
    d = _dir(name)
    (d / "status.json").write_text(json.dumps({"name": name, "phase": "starting", "brief": str(Path(brief).resolve())}))
    cmdline = f'"{sys.executable}" "{Path(__file__).resolve()}" run {name} "{Path(brief).resolve()}" --hours {hours}'
    ps = ("$h = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ShowWindow=[uint16]0}; "
          "$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='"
          + cmdline.replace("'", "''") + "'; CurrentDirectory='" + str(REPO)
          + "'; ProcessStartupInformation=$h}; $r.ProcessId")
    pid = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    print(json.dumps({"started": name, "pid": pid, "status": str(d / "status.json")}))


def run(name, brief, hours):
    sys.path.insert(0, str(REPO))
    from reality_engine.scripts import session_runner as sr
    d = _dir(name)
    st = json.loads((d / "status.json").read_text())
    st.update(phase="running", started=time.strftime("%Y-%m-%dT%H:%M:%S"))
    (d / "status.json").write_text(json.dumps(st))
    prompt = (f"You are Claude Opus doing a headless analysis job for the Wolf session. Read the brief {brief} and do "
              f"it. Stores and the repo are READ-ONLY to you: never write a database, never edit repo files, never "
              f"commit, merge or push, no subagents, no paid embedding calls, never read D:/Shivam_Private or print "
              f"keys. Write only the output files the brief names. Keep your context lean: query narrowly, read pages "
              f"in pieces. End with the short report the brief asks for.")
    servers = json.loads((REPO / ".mcp.json").read_text())["mcpServers"]
    servers = {k: servers[k] for k in ("reality-data",) if k in servers}
    (d / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
    cmd = [sr.CLAUDE, "-p", prompt, "--model", MODEL, "--effort", "high",
           "--output-format", "stream-json", "--verbose", "--max-turns", "400", "--dangerously-skip-permissions",
           "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", str(d / "mcp.json"),
           "--disallowedTools", "Agent,Edit,NotebookEdit,Bash(git commit:*),Bash(git push:*),Bash(git merge:*)"]
    env = sr.child_env({"CLAUDE_CONFIG_DIR": r"C:\Users\warri\.claude-neo"})
    res = sr.run_session(cmd, REPO, run_seconds=int(hours * 3600), context_limit=600_000, model=MODEL,
                         env=env, label=f"opus {name}", description=f"opus headless {name}",
                         transcript=d / "transcript.jsonl", logfile=d / "session.log")
    (d / "result.md").write_text(res.final or "", encoding="utf-8")
    st.update(phase="finished", done=True, ended=time.strftime("%Y-%m-%dT%H:%M:%S"),
              ok=not res.error and not res.over_limit, error=res.error, over_limit=res.over_limit,
              limited=res.limited, peak_context=res.peak, result=str(d / "result.md"))
    (d / "status.json").write_text(json.dumps(st))


def status(name):
    p = OUT / name / "status.json"
    return json.loads(p.read_text()) if p.exists() else {"name": name, "phase": "unknown"}


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("start"); s.add_argument("name"); s.add_argument("brief"); s.add_argument("--hours", type=float, default=3)
    r = sub.add_parser("run"); r.add_argument("name"); r.add_argument("brief"); r.add_argument("--hours", type=float, default=3)
    t = sub.add_parser("status"); t.add_argument("name")
    a = ap.parse_args()
    if a.cmd == "start":
        start(a.name, a.brief, a.hours)
    elif a.cmd == "run":
        run(a.name, a.brief, a.hours)
    else:
        print(json.dumps(status(a.name), indent=1))


if __name__ == "__main__":
    main()
