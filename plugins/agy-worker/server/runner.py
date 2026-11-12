"""Detached runner for one agy-worker job (T-112): runs agy headless in the job's workspace, streams its events to
events.jsonl, enforces the timeout, writes exit.json, then auto-commits a non-empty worktree diff."""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agy_core as core  # noqa: E402


def main(d: Path) -> None:
    job = json.loads((d / "job.json").read_text(encoding="utf-8"))
    ws = Path(job["workspace"])
    brief = (d / "brief.md").read_text(encoding="utf-8")
    cmd = [str(core.AGY), "-p", brief, "--model", core.MODEL, "--mode", "accept-edits", "--output-format",
           "stream-json", "--print-timeout", f"{job['timeout_seconds']}s", "--disable-slash-commands"]
    if job.get("bypass_permissions", True):  # Shivam, 8 Nov: run agy headless with permissions bypassed
        cmd.append("--dangerously-skip-permissions")
    if job.get("conversation_id"):
        cmd += ["--conversation", job["conversation_id"]]
    env = dict(__import__("os").environ, AGY_JOB_WORKSPACE=str(ws), PYTHONUTF8="1")
    outcome, rc = "completed", None
    with open(d / "events.jsonl", "w", encoding="utf-8") as out, open(d / "stderr.log", "w", encoding="utf-8") as err:
        p = subprocess.Popen(cmd, cwd=ws, stdout=out, stderr=err, env=env, creationflags=core.CREATE_NO_WINDOW)
        (d / "agy.pid").write_text(str(p.pid))
        try:
            rc = p.wait(timeout=job["timeout_seconds"] + 120)
        except subprocess.TimeoutExpired:
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            outcome = "timeout"
    if rc not in (0, None) and outcome == "completed":
        outcome = "failed"
    info = {"outcome": outcome, "exit_code": rc, "ended_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    if job.get("branch"):
        core._git("add", "-A", cwd=ws)
        if core._git("diff", "--cached", "--quiet", cwd=ws).returncode:
            msg = f"agy-worker {job['job_id']} ({core.MODEL}): {outcome}\n\nNo-ticket: worker branch, reviewed before merge"
            c = core._git("-c", "user.name=kakazuya (Wolf agy-worker)", "commit", "-q", "-m", msg, cwd=ws)
            info["committed"] = c.returncode == 0
    (d / "exit.json").write_text(json.dumps(info), encoding="utf-8")
    mark_ended(d, info)


def mark_ended(d: Path, info: dict) -> None:
    """job.json's phase follows exit.json (T-200): a watcher keyed on job.json saw finished jobs as 'running'."""
    path = d / "job.json"
    try:
        job = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    job.update(phase="ended", outcome=info.get("outcome"), ended_at=info.get("ended_at"))
    path.write_text(json.dumps(job, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
