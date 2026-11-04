"""Sonnet 5.5 (effort medium) code worker for DeepSeek peak hours (Shivam, 4 Nov 2026). Ops script, not product code.

  python tasks/night_loop/sonnet_worker.py start <name> <brief.md> [--hours 4]
  python tasks/night_loop/sonnet_worker.py wait <name> [--seconds 540]     # blocks up to --seconds, prints status
  python tasks/night_loop/sonnet_worker.py status <name>

`start` makes worktree C:/Users/warri/Downloads/IDM-worktrees/Eagle-sonnet-<name> on branch Eagle-sonnet-<name>
from HEAD and launches the session through Win32_Process.Create (outside the caller's job object, so it survives
the caller), hidden. The session reads the brief (same seven fields as a dsh brief) and works only in that worktree.
At the end the branch is committed; status, transcript and summary go to D:/RealityEngine/night_loop/sonnet/<name>/.
It counts as one of the 2 worker slots, like a dsh worker. The wrapper merges; nobody else does.
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
TREES = Path(r"C:\Users\warri\Downloads\IDM-worktrees")
OUT = Path(r"D:\RealityEngine\night_loop\sonnet")


def _dir(name):
    d = OUT / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def start(name, brief, hours):
    tree = TREES / f"Eagle-sonnet-{name}"
    branch = f"Eagle-sonnet-{name}"
    if not tree.exists():
        subprocess.run(["git", "-C", str(REPO), "worktree", "add", str(tree), "-b", branch, "HEAD"], check=True)
    d = _dir(name)
    (d / "status.json").write_text(json.dumps({"name": name, "phase": "starting", "branch": branch,
                                               "worktree": str(tree), "brief": str(Path(brief).resolve())}))
    py = sys.executable
    cmdline = f'"{py}" "{Path(__file__).resolve()}" run {name} "{Path(brief).resolve()}" --hours {hours}'
    ps = ("$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine='"
          + cmdline.replace("'", "''") + "'; CurrentDirectory='" + str(tree) + "'}; $r.ProcessId")
    pid = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True).stdout.strip()
    print(json.dumps({"started": name, "pid": pid, "branch": branch, "worktree": str(tree), "status": str(d / "status.json")}))


def run(name, brief, hours):
    sys.path.insert(0, str(REPO))
    from reality_engine.scripts import session_runner as sr
    tree = TREES / f"Eagle-sonnet-{name}"
    d = _dir(name)
    st = json.loads((d / "status.json").read_text())
    st.update(phase="running", started=time.strftime("%Y-%m-%dT%H:%M:%S"))
    (d / "status.json").write_text(json.dumps(st))
    prompt = (f"You are a code worker (Claude Sonnet) in the git worktree {tree}. Read the brief {brief} and do it. "
              f"Edit files only inside this worktree; read the main checkout and data read-only. No subagents, no "
              f"merges, no pushes, no paid calls, never read D:/Shivam_Private or print keys. Run the brief's fast "
              f"checks one test file per process (.tmp is denied to you: use pytest tmp_path or D:/RealityEngine/pilot10/scratch). Update the docs the brief names (no docs, no merge). End with the "
              f"report the brief asks for, including a 'Docs updated:' line.")
    servers = json.loads((REPO / ".mcp.json").read_text())["mcpServers"]  # a code worker needs data and code tools only
    servers = {k: servers[k] for k in ("reality-data", "code-tools")}
    servers["code-tools"]["env"]["CODE_TOOLS_ROOT"] = str(tree).replace("\\", "/")
    (d / "mcp.json").write_text(json.dumps({"mcpServers": servers}))
    cmd = [sr.CLAUDE, "-p", prompt, "--model", "claude-sonnet-5-5", "--effort", "medium",
           "--output-format", "stream-json", "--verbose", "--max-turns", "300", "--dangerously-skip-permissions",
           "--disable-slash-commands", "--strict-mcp-config", "--mcp-config", str(d / "mcp.json"),
           "--disallowedTools", "Agent,mcp__dsh-worker__merge_worker,mcp__dsh-worker__push,Bash(git push:*),Bash(git merge:*)"]
    env = sr.child_env({"CLAUDE_CONFIG_DIR": r"C:\Users\warri\.claude", "GIT_AUTHOR_NAME": "kakazuya (Eagle)",
                        "GIT_COMMITTER_NAME": "kakazuya (Eagle)"})
    res = sr.run_session(cmd, tree, run_seconds=int(hours * 3600), context_limit=400_000, model="claude-sonnet-5-5",
                         env=env, label=f"sonnet {name}", description=f"sonnet worker {name}",
                         transcript=d / "transcript.jsonl", logfile=d / "session.log")
    subprocess.run(["git", "-C", str(tree), "add", "-A"])
    subprocess.run(["git", "-C", str(tree), "commit", "-q", "-m", f"sonnet worker {name}: work from {Path(brief).name}"])
    head = subprocess.run(["git", "-C", str(tree), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
    (d / "result.md").write_text(res.final or "", encoding="utf-8")
    st.update(phase="finished", done=True, ended=time.strftime("%Y-%m-%dT%H:%M:%S"), head=head,
              ok=not res.error and not res.over_limit, error=res.error, over_limit=res.over_limit,
              limited=res.limited, peak_context=res.peak, result=str(d / "result.md"))
    (d / "status.json").write_text(json.dumps(st))


def status(name):
    p = OUT / name / "status.json"
    return json.loads(p.read_text()) if p.exists() else {"name": name, "phase": "unknown"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=("start", "run", "wait", "status"))
    ap.add_argument("name")
    ap.add_argument("brief", nargs="?")
    ap.add_argument("--hours", type=float, default=4)
    ap.add_argument("--seconds", type=int, default=540)
    a = ap.parse_args()
    if a.action == "start":
        start(a.name, a.brief, a.hours)
    elif a.action == "run":
        run(a.name, a.brief, a.hours)
    elif a.action == "wait":
        end = time.time() + a.seconds
        while time.time() < end and not status(a.name).get("done"):
            time.sleep(15)
        print(json.dumps(status(a.name)))
    else:
        print(json.dumps(status(a.name)))


if __name__ == "__main__":
    main()
