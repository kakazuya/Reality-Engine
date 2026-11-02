"""Run gap-loop answer sessions on the HP laptop (Shivam, 2 Nov: headless claude -p there too).

Only answer and re-answer units go to the HP: they read the company database and write nothing back, so a copy
made before each answer stage is enough.  Fix units write ``doc_text`` and stay on this laptop.
The HP's Claude CLI signs in through its own ``CLAUDE_CODE_OAUTH_TOKEN`` user variable, set by
Shivam; nothing here reads or copies a key.  Every call is plain ``ssh``/``scp``: no window opens
on the HP.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path

from reality_engine.gap_loop.company import current

HOST = "zen7s@100.78.87.112"  # Tailscale; machines/HP_LAPTOP.md


def hp_sandbox() -> str:
    """The sandbox folder on the HP for the active company: C:\\RE\\sandbox\\<symbol lower>_loop."""
    return current().hp_sandbox


CLAUDE = r"C:\Users\zen7s\.local\bin\claude.exe"
SSH = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]
SCP = ["scp", "-q", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15"]


def _run(cmd: list[str], timeout: int = 600) -> subprocess.CompletedProcess:
    from reality_engine.scripts.session_runner import hidden_console
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout, **hidden_console())


def _remote_path(name: str) -> str:
    return f"{HOST}:{(hp_sandbox() + chr(92) + name).replace(chr(92), '/')}"


def sync_db(sandbox: Path) -> str | None:
    """Copy a consistent snapshot of the company database to the HP.  Returns an error line, or None."""
    active = current()
    snap = Path(tempfile.gettempdir()) / f"{active.symbol.lower()}_gap_loop_snapshot.db"
    sandbox_dir = hp_sandbox()
    try:
        src = sqlite3.connect(Path(sandbox) / active.db_name)
        dst = sqlite3.connect(snap)
        src.backup(dst)
        dst.close()
        src.close()
        made = _run(SSH + [HOST, f"mkdir {sandbox_dir}\\prompts {sandbox_dir}\\state 2>nul & echo ok"], 60)
        if "ok" not in made.stdout:
            return f"HP not reachable: {(made.stderr or made.stdout)[:200]}"
        mcp = Path(tempfile.gettempdir()) / f"{active.symbol.lower()}_gap_loop_mcp.json"
        mcp.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
        for local, name in ((snap, active.db_name), (mcp, "mcp.json")):
            copied = _run(SCP + [str(local), _remote_path(name)], 900)
            if copied.returncode:
                return f"scp {name} failed: {copied.stderr[:200]}"
    except (OSError, sqlite3.Error, subprocess.SubprocessError) as exc:
        return f"sync failed: {type(exc).__name__}: {exc}"
    return None


def build_remote_cmd(unit_id: str, model: str, allowed: tuple[str, ...], disallowed: tuple[str, ...],
                     max_turns: int) -> list[str]:
    """The ssh command: the prompt file is piped into ``claude -p`` on the HP, stream-json comes back."""
    sandbox_dir = hp_sandbox()
    line = (f'cd /d {sandbox_dir} && type prompts\\{unit_id}.txt | "{CLAUDE}" -p --model {model} '
            f"--effort medium --output-format stream-json --verbose --max-turns {max_turns} "
            f'--allowedTools "{",".join(allowed)}" --disallowedTools "{",".join(disallowed)}" '
            f"--strict-mcp-config --mcp-config {sandbox_dir}\\mcp.json --no-session-persistence")
    return SSH + [HOST, line]


def run_remote(unit, model: str, tier: int) -> dict:
    """One answer session on the HP, in the same shape as ``tiers._run_claude``."""
    from reality_engine.gap_loop import tiers
    from reality_engine.scripts.session_runner import child_env, parse_json_block, run_session

    started = tiers._iso()
    there = replace(unit, sandbox=Path(hp_sandbox()))
    prompt = tiers.fix_prompt(there) if unit.stage == "fix" else tiers.answer_prompt(there)
    local = Path(unit.sandbox) / "state" / "remote_prompts" / f"{unit.id}.txt"
    local.parent.mkdir(parents=True, exist_ok=True)
    local.write_text(prompt, encoding="utf-8")
    copied = _run(SCP + [str(local), _remote_path(f"prompts\\{unit.id}.txt")], 120)
    if copied.returncode:
        return {"tier": tier, "model": model, "started": started, "ended": tiers._iso(), "ok": False,
                "payload": None, "error": f"HP prompt copy failed: {copied.stderr[:200]}",
                "over_limit": False, "limited": False, "session": None, "job_id": None}
    allowed = tuple(t for t in tiers.ALLOWED_TOOLS if not t.startswith("mcp__"))
    cmd = build_remote_cmd(unit.id, model, allowed, tiers.DISALLOWED_TOOLS, tiers.MAX_TURNS)
    session = run_session(cmd, unit.sandbox, env=child_env({"KEC_GAP_LOOP": "1"}), model=model,
                          label=f"HP {unit.id}", description=tiers.describe(unit),
                          transcript=tiers.transcript_path(unit, model, started))
    payload = parse_json_block(session.final)
    error = session.error
    if payload is None and not error:
        error = "no valid JSON block" if not session.over_limit else "over context limit"
    return {
        "tier": tier, "model": model, "started": started, "ended": tiers._iso(),
        "ok": payload is not None and not session.over_limit and not error,
        "payload": payload, "error": error, "over_limit": session.over_limit,
        "limited": session.limited, "session": session, "job_id": None, "host": "hp",
    }


def run_tier1(unit, logfile=None) -> dict:
    from reality_engine.scripts.session_runner import MODEL
    return run_remote(unit, MODEL, 1)


def run_tier2(unit, logfile=None) -> dict:
    from reality_engine.gap_loop.tiers import SONNET
    return run_remote(unit, SONNET, 2)
