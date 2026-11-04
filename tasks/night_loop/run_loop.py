"""Wrapper's launcher for one headless loop session (ops script, not product code).

python tasks/night_loop/run_loop.py NN
Runs `claude -p` (Opus 5.5, effort medium, Eagle config, only the repo .mcp.json servers, no skills) hidden, with the prompt pointing at
LOOP_BRIEF.md and loops/loop_NN_brief.md; kills it at 480k context or 6 hours; stream-json transcript to
D:\\RealityEngine\\night_loop\\transcripts\\loop_NN.jsonl; prints a one-line summary.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.scripts import session_runner as sr  # noqa: E402

n = f"{int(sys.argv[1]):02d}"
prompt = (f"You are night-loop session {n}. Read tasks/night_loop/LOOP_BRIEF.md and follow it: then RULINGS, GOAL, "
          f"PILOT10, HANDOFF and tasks/night_loop/loops/loop_{n}_brief.md. Do that loop's work end to end, keep "
          f"loops/loop_{n}_report.md and HANDOFF.md updated after every milestone, commit them, then stop.")
cmd = [sr.CLAUDE, "-p", prompt, "--model", "claude-opus-5-5", "--effort", "medium",
       "--output-format", "stream-json", "--verbose", "--max-turns", "400",
       "--dangerously-skip-permissions", "--disable-slash-commands",
       "--strict-mcp-config", "--mcp-config", str(REPO / ".mcp.json"),
       "--disallowedTools", "Agent,mcp__dsh-worker__merge_worker,mcp__dsh-worker__push,Bash(git push:*),Bash(git merge:*)"]
out = Path(r"D:\RealityEngine\night_loop\transcripts")
out.mkdir(parents=True, exist_ok=True)
env = sr.child_env({"CLAUDE_CONFIG_DIR": r"C:\Users\warri\.claude", "GIT_AUTHOR_NAME": "kakazuya (Eagle)",
                    "GIT_COMMITTER_NAME": "kakazuya (Eagle)"})
res = sr.run_session(cmd, REPO, run_seconds=6 * 3600, context_limit=480_000, model="claude-opus-5-5", env=env,
                     label=f"night loop {n}", description=f"night loop {n}", transcript=out / f"loop_{n}.jsonl",
                     logfile=out / f"loop_{n}.log")
print(f"loop {n}: peak_context={res.peak} over_limit={res.over_limit} limited={res.limited} "
      f"error={(res.error or '')[:200]!r} final={(res.final or '')[-600:]!r}")
