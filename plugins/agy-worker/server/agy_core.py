"""agy-worker core (T-112): run Antigravity CLI (`agy`) coding jobs headless in a Wolf- worktree, like dsh-worker.

Model is pinned to gemini-3.8-flash-medium (Shivam's ruling, 7 Nov 2026). One job = one `agy -p <brief>` run with
`--output-format stream-json`, launched by a detached runner (runner.py) so it survives this server; the runner
writes events.jsonl, then exit.json, then auto-commits the worktree diff. Status is parsed from events.jsonl only.

Job layout: <runtime>/jobs/<job_id>/{job.json, brief.md, events.jsonl, stderr.log, exit.json, runner.pid}
"""
from __future__ import annotations

import json
import os
import re
import secrets
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

MODEL = "gemini-3.8-flash-medium"
SERVER_DIR = Path(__file__).resolve().parent
REPO = Path(os.environ.get("AGY_WORKER_REPO_ROOT", SERVER_DIR.parents[2]))
RUNTIME = Path(os.environ.get("AGY_WORKER_RUNTIME", SERVER_DIR.parent / "runtime"))
WORKTREES = Path(os.environ.get("AGY_WORKER_WORKTREES", REPO.parent / "IDM-worktrees"))
AGY = Path(os.environ.get("AGY_BIN", Path(os.environ.get("LOCALAPPDATA", "")) / "agy" / "bin" / "agy.exe"))
BRANCH_PREFIX = "Wolf-agy-"
CREATE_NO_WINDOW, DETACHED, NEW_GROUP, BREAKAWAY = 0x08000000, 0x00000008, 0x00000200, 0x01000000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _git(*args: str, cwd: Path = REPO) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, encoding="utf-8")


def job_dir(job_id: str) -> Path:
    if not re.fullmatch(r"[0-9TZ]+-[0-9a-f]{8}", job_id):
        raise ValueError(f"bad job id {job_id!r}")
    return RUNTIME / "jobs" / job_id


def _load(job_id: str) -> dict:
    return json.loads((job_dir(job_id) / "job.json").read_text(encoding="utf-8"))


def _save(job: dict) -> None:
    (job_dir(job["job_id"]) / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")


def start(brief: str, use_worktree: bool = True, base: str | None = None, timeout_seconds: int = 3600,
          test_cmd: str | None = None) -> dict:
    """Create the worktree, write the brief, launch the detached runner; returns at once."""
    if not AGY.exists():
        return {"ok": False, "error": f"agy not found at {AGY}"}
    job_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-" + secrets.token_hex(4)
    d = job_dir(job_id)
    d.mkdir(parents=True)
    (d / "brief.md").write_text(brief, encoding="utf-8")
    workspace, branch, base_sha = REPO, None, None
    if use_worktree:
        base_sha = _git("rev-parse", base or "HEAD").stdout.strip()
        branch = BRANCH_PREFIX + job_id
        workspace = WORKTREES / branch
        r = _git("worktree", "add", "-b", branch, str(workspace), base_sha)
        if r.returncode:
            return {"ok": False, "error": "git worktree add failed", "detail": r.stderr[-800:]}
    job = {"job_id": job_id, "model": MODEL, "created_at": _now(), "workspace": str(workspace), "branch": branch,
           "base": base_sha, "timeout_seconds": timeout_seconds, "test_cmd": test_cmd, "phase": "starting"}
    _save(job)
    flags = CREATE_NO_WINDOW | NEW_GROUP | DETACHED
    cmd = [sys.executable, str(SERVER_DIR / "runner.py"), str(d)]
    try:
        p = subprocess.Popen(cmd, creationflags=flags | BREAKAWAY, close_fds=True, cwd=str(workspace))
    except OSError:
        p = subprocess.Popen(cmd, creationflags=flags, close_fds=True, cwd=str(workspace))
    job.update(phase="running", runner_pid=p.pid)
    _save(job)
    return {"ok": True, "job_id": job_id, "branch": branch, "workspace": str(workspace), "model": MODEL}


def parse_events(path: Path) -> dict:
    """Tool calls by tool, tokens, last tool, denials and the final response from an agy stream-json log."""
    tools, denied, tok = Counter(), [], Counter()
    last_tool, final, steps, errors, last_at = None, None, 0, [], None
    if not path.exists():
        return {"tool_calls": 0}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        su = e.get("step_update") or {}
        if su.get("state") == "DONE":
            steps += 1
            if su.get("usage"):
                tok.update({k: v for k, v in su["usage"].items() if isinstance(v, int)})
            if su.get("step_type") == "tool":
                name = su.get("tool_name") or "?"
                p = (su.get("tool_info") or {}).get("parameters") or {}
                if name == "call_mcp_tool":
                    name = f"mcp:{p.get('ServerName')}/{p.get('ToolName')}"
                tools[name] += 1
                last_tool = name
                err = (su.get("tool_info") or {}).get("error") or su.get("error")
                if err:
                    errors.append(str(err.get("message") if isinstance(err, dict) else err)[:300])
        if "response" in e or e.get("event") in ("result", "final"):
            final = e
        denied += e.get("denied_actions") or []
    out = {"tool_calls": sum(tools.values()), "tool_calls_by_tool": dict(tools.most_common()), "steps": steps,
           "tokens": dict(tok), "last_tool": last_tool, "denied_actions": denied[-10:], "tool_errors": errors[-5:]}
    if final:
        out["final_status"] = final.get("status")
        out["response"] = final.get("response")
        if final.get("usage"):
            out["tokens_final"] = final["usage"]
    return out


def _alive(pid: int | None) -> bool:
    if not pid:
        return False
    r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
    return str(pid) in r.stdout


def status(job_id: str) -> dict:
    job, d = _load(job_id), job_dir(job_id)
    ex = d / "exit.json"
    done = ex.exists()
    info = json.loads(ex.read_text(encoding="utf-8")) if done else {}
    if not done and not _alive(job.get("runner_pid")):
        info = {"outcome": "lost", "note": "runner process gone without exit.json"}
        done = True
    ev = parse_events(d / "events.jsonl")
    started = datetime.fromisoformat(job["created_at"])
    end = datetime.fromisoformat(info["ended_at"]) if info.get("ended_at") else datetime.now(timezone.utc)
    resp = ev.pop("response", None)
    return {"ok": True, "job_id": job_id, "model": job["model"], "done": done,
            "outcome": info.get("outcome", "running"), "elapsed_seconds": int((end - started).total_seconds()),
            "branch": job.get("branch"), **ev, "response_preview": (resp or "")[:300]}


def result(job_id: str, max_bytes: int = 20000) -> dict:
    job, d = _load(job_id), job_dir(job_id)
    st = status(job_id)
    ev = parse_events(d / "events.jsonl")
    out = {"ok": True, "job_id": job_id, "done": st["done"], "outcome": st["outcome"],
           "content": (ev.get("response") or "")[:max_bytes], "branch": job.get("branch")}
    if job.get("branch"):
        ws = Path(job["workspace"])
        out["head"] = _git("rev-parse", "HEAD", cwd=ws).stdout.strip()
        out["diff_stat"] = _git("diff", "--stat", f"{job['base']}..HEAD", cwd=ws).stdout[-3000:]
    return out


def list_jobs(limit: int = 20) -> dict:
    root = RUNTIME / "jobs"
    ids = sorted((p.name for p in root.iterdir() if p.is_dir()), reverse=True)[:limit] if root.exists() else []
    rows = []
    for i in ids:
        try:
            s = status(i)
            rows.append({k: s.get(k) for k in ("job_id", "done", "outcome", "elapsed_seconds", "tool_calls",
                                                "branch")} | {"output_tokens": s.get("tokens", {}).get("output_tokens")})
        except Exception as exc:  # a half-written job must not hide the others
            rows.append({"job_id": i, "error": str(exc)[:200]})
    return {"ok": True, "jobs": rows}


def cancel(job_id: str, confirm: bool = False) -> dict:
    if not confirm:
        return {"ok": False, "error": "cancel needs confirm=true"}
    job, d = _load(job_id), job_dir(job_id)
    pids = [job.get("runner_pid")]
    pf = d / "agy.pid"
    if pf.exists():
        pids.append(int(pf.read_text().strip() or 0))
    for pid in filter(None, pids):
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    if not (d / "exit.json").exists():
        (d / "exit.json").write_text(json.dumps({"outcome": "cancelled", "ended_at": _now()}), encoding="utf-8")
    return {"ok": True, "job_id": job_id, "cancelled": True}


def quota() -> dict:
    """The account's Gemini and Claude/GPT limits left, from `agy -p /usage` (no model call)."""
    r = subprocess.run([str(AGY), "-p", "/usage", "--model", MODEL, "--print-timeout", "60s"], capture_output=True,
                       text=True, encoding="utf-8", timeout=90, creationflags=CREATE_NO_WINDOW)
    rows = []
    for line in r.stdout.splitlines():
        parts = line.split("\t")
        if len(parts) == 4:
            rows.append({"group": parts[0], "limit": parts[1], "remaining": parts[2], "resets_at": parts[3]})
    return {"ok": bool(rows), "limits": rows, "raw": None if rows else (r.stdout + r.stderr)[-600:]}


def remove_worktree(job_id: str, delete_branch: bool = False) -> dict:
    job = _load(job_id)
    if not job.get("branch"):
        return {"ok": False, "error": "job has no worktree"}
    r = _git("worktree", "remove", "--force", job["workspace"])
    out = {"ok": r.returncode == 0, "removed": job["workspace"], "detail": r.stderr[-300:]}
    if delete_branch:
        out["branch_deleted"] = _git("branch", "-D", job["branch"]).returncode == 0
    return out



if __name__ == "__main__":  # python plugins/agy-worker/server/agy_core.py list | status <job_id> | quota
    _cmd = sys.argv[1] if len(sys.argv) > 1 else "list"
    _out = {"list": lambda: list_jobs(), "quota": quota}.get(_cmd, lambda: status(sys.argv[2]))()
    print(json.dumps(_out, indent=1))
