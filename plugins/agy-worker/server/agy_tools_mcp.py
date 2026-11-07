"""agy-tools MCP (T-112): the only command runner a Gemini agy worker gets, because agy's headless mode cannot be
given a shell allow-rule. run_check runs one allowlisted command (no shell) in the job workspace named by the
AGY_JOB_WORKSPACE env the runner sets, else the server's cwd."""
from __future__ import annotations

import os
import shlex
import subprocess
import sys
from pathlib import Path

from mcp.server import MCPServer

ALLOWED = [
    ["python", "-m", "pytest"], ["python", "-m", "ruff"], ["python", "-m", "basedpyright"], ["basedpyright"],
    ["python", "-m", "py_compile"],
    ["git", "status"], ["git", "diff"], ["git", "log"], ["git", "show"],
]
server = MCPServer(name="agy-tools", version="0.1.0")


def workspace() -> Path:
    return Path(os.environ.get("AGY_JOB_WORKSPACE") or os.getcwd())


def allowed(argv: list[str]) -> bool:
    """A listed prefix, or `python -m reality_engine.<module>` (repo code, same trust as running its tests)."""
    if len(argv) >= 3 and argv[:2] == ["python", "-m"] and argv[2].startswith("reality_engine."):
        return True
    return any(argv[: len(a)] == a for a in ALLOWED)


@server.tool(name="run_check", description=(
    "Run ONE allowed command in your workspace and get exit code, stdout and stderr tails. Allowed prefixes: "
    "python -m pytest, python -m ruff, python -m basedpyright, basedpyright, python -m py_compile, "
    "python -m reality_engine.<any module>, git status/diff/log/show. No pipes, redirects or chaining. "
    "Timeout 900 s."))
def run_check(command: str) -> dict:
    try:
        argv = shlex.split(command, posix=False)
    except ValueError as exc:
        return {"ok": False, "error": f"cannot parse: {exc}"}
    if not argv or not allowed(argv) or any(t in command for t in ("|", "&", ";", ">", "<", "`")):
        return {"ok": False, "error": "not allowed", "allowed": [" ".join(a) for a in ALLOWED]}
    if argv[0] == "python":
        argv[0] = sys.executable
    ws = workspace()
    env = dict(os.environ, PYTHONPATH=str(ws), PYTHONUTF8="1")
    try:
        r = subprocess.run(argv, cwd=ws, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=900, env=env)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout after 900 s"}
    return {"ok": r.returncode == 0, "exit_code": r.returncode, "cwd": str(ws), "stdout": r.stdout[-6000:],
            "stderr": r.stderr[-3000:]}


@server.tool(name="where", description="The workspace path your checks run in.")
def where() -> dict:
    return {"workspace": str(workspace()), "env_set": bool(os.environ.get("AGY_JOB_WORKSPACE"))}


if __name__ == "__main__":
    server.run("stdio")
