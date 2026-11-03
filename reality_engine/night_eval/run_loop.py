"""Launch one hidden night-loop session (``claude -p``, Opus, effort medium) through the session runner.

The prompt file is the wrapper's; the session runs headless with the worker MCP tools that could merge, push or
spawn a subagent removed, at most 150 turns and 2 hours, and its stream-json transcript lands under
``D:\\RealityEngine\\night_loop\\transcripts\\loop_NN.jsonl`` (``--transcript`` overrides it).  Prints the exit
state, turns, tokens and whether the Claude usage limit stopped it.  ``--dry-run`` prints the command instead of
running it; nothing in the test suite launches a session.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MODEL = "claude-opus-5-5"
EFFORT = "medium"
MAX_TURNS = 150
RUN_SECONDS = 7200
TRANSCRIPT_DIR = Path(r"D:\RealityEngine\night_loop\transcripts")
DISALLOWED = ("Agent", "mcp__dsh-worker__merge_worker", "mcp__dsh-worker__push",
              "Bash(git push*)", "Bash(git merge*)")


def transcript_for(n: int) -> Path:
    return TRANSCRIPT_DIR / f"loop_{n:02d}.jsonl"


def cmd_for(prompt: str, *, model: str = MODEL, max_turns: int = MAX_TURNS) -> list[str]:
    """The ``claude -p`` line: stream-json, Opus, effort medium, the forbidden tools removed."""
    from reality_engine.scripts.session_runner import build_cmd

    return build_cmd(prompt, model=model, effort=EFFORT, disallowed_tools=DISALLOWED, max_turns=max_turns)


def count_turns(transcript: Path) -> int:
    """Assistant turns in a stream-json transcript (0 when the file is missing)."""
    if not Path(transcript).is_file():
        return 0
    turns = 0
    for line in Path(transcript).read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "assistant":
            turns += 1
    return turns


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="run_loop", description="one hidden headless night-loop session")
    parser.add_argument("--n", type=int, required=True, help="loop number (NN)")
    parser.add_argument("--prompt", required=True, help="prompt file the wrapper wrote")
    parser.add_argument("--transcript", default="", help=f"default {TRANSCRIPT_DIR}\\loop_NN.jsonl")
    parser.add_argument("--log", default="", help="session log line; default beside the transcript")
    parser.add_argument("--cwd", default=str(ROOT), help="working directory of the session")
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--max-turns", type=int, default=MAX_TURNS)
    parser.add_argument("--run-seconds", type=int, default=RUN_SECONDS)
    parser.add_argument("--dry-run", action="store_true", help="print the command and the transcript path only")
    args = parser.parse_args(argv)
    prompt = Path(args.prompt).read_text(encoding="utf-8")
    cmd = cmd_for(prompt, model=args.model, max_turns=args.max_turns)
    transcript = Path(args.transcript) if args.transcript else transcript_for(args.n)
    log = Path(args.log) if args.log else transcript.with_suffix(".log")
    if args.dry_run:
        print(json.dumps({"dry_run": True, "n": args.n, "cmd": cmd, "transcript": str(transcript),
                          "log": str(log), "run_seconds": args.run_seconds, "disallowed": list(DISALLOWED)},
                         indent=2, ensure_ascii=False))
        return 0
    from reality_engine.scripts.session_runner import run_session

    try:
        log.parent.mkdir(parents=True, exist_ok=True)
        logfile: Path | None = log
    except OSError:
        logfile = None
    started = count_turns(transcript)
    result = run_session(cmd, Path(args.cwd), logfile=logfile, run_seconds=args.run_seconds,
                         transcript=transcript, label=f"night_loop_{args.n}",
                         description=f"night loop {args.n}", model=args.model)
    usage = result.usage or {}
    out = {
        "n": args.n,
        "exit": 0 if not result.error and not result.over_limit else 1,
        "error": result.error,
        "over_limit": result.over_limit,
        "limited": result.limited,
        "turns": count_turns(transcript) - started,
        "tokens": {"in": int(usage.get("input_tokens") or 0), "out": int(usage.get("output_tokens") or 0),
                   "cache_read": int(usage.get("cache_read_input_tokens") or 0),
                   "cache_write": int(usage.get("cache_creation_input_tokens") or 0)},
        "cost_usd": result.cost,
        "duration_s": round(result.duration_s, 1),
        "transcript": str(transcript),
        "final": result.final[:300],
    }
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out["exit"] == 0 and not out["limited"] else 1


if __name__ == "__main__":
    sys.exit(main())
