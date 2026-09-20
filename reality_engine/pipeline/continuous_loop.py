"""
Continuous Loop — 30-minute harness check + unattended agent iteration pass.

Two phases per run:

1. ``check``  — read-only health snapshot of the whole loop (data freshness,
   nightly chain health, Wave B validation-harness progress, dense-substrate
   counts, uncommitted work, previous handoff) rendered to a markdown brief
   under ``data/logs/loop/<date>/brief_<HHMM>.md``.
2. ``iterate`` — spawn a headless agent pass (``omp -p``) seeded with the
   standing prompt + the brief + the rolling ``STATE.md`` handoff, capture its
   transcript, and append a run record to ``run_log.jsonl``.

This module is **read-only against the DB** — the agent pass, not the driver,
decides what to write (via the repo's own repository/harness APIs).

Reused conventions: exclusive lock file with stale-break (same pattern as
``pipeline/nightly_alpha.py``, shorter window so a dead 30-minute slot frees
itself), IST clock + trading-day calendar from ``pipeline/catchup_scheduler.py``.

Owns ONLY this file, ``reality_engine/agent/prompts/continuous_loop.md`` and
``reality_engine/scripts/run_continuous_loop.cmd``. Never edits peer modules.
"""

from __future__ import annotations

import argparse
import errno
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Allow direct execution (`python reality_engine/pipeline/continuous_loop.py`).
_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

logger = logging.getLogger("reality_engine.continuous_loop")

LOOP_SUBDIR = "loop"
LOCK_NAME = "continuous.lock"
STATE_NAME = "STATE.md"
RUN_LOG_NAME = "run_log.jsonl"
SESSIONS_SUBDIR = "sessions"
AGENT_LOG_SUBDIR = "agent"

# One slot. A lock older than this is dead (crashed run) and is broken.
STALE_LOCK_SECONDS = 45 * 60
DEFAULT_MAX_TIME = "20m"
AGENT_TIMEOUT_GRACE_SECONDS = 300
TASK_NAME = "RealityEngine-ContinuousLoop"
TASK_INTERVAL_MINUTES = 30
MAX_BRIEF_STATE_CHARS = 12_000
LOG_TAIL_LINES = 60

COUNT_TABLES: Tuple[str, ...] = (
    "master_companies",
    "daily_price_delivery",
    "raw_documents",
    "document_chunks",
    "company_distilled_parameters",
    "business_model_profiles",
    "moat_evaluations",
    "model_explainer_rankings",
    "eod_scrip_calls",
    "model_validation_scores",
    "model_lens_weight_proposals",
    "regulatory_political_risks",
    "ripple_effects",
)


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
def repo_root() -> Path:
    return _PROJECT_ROOT


def default_loop_dir() -> Path:
    from reality_engine import config

    return Path(config.DATA_DIR) / "logs" / LOOP_SUBDIR


def prompt_file() -> Path:
    return _PROJECT_ROOT / "reality_engine" / "agent" / "prompts" / "continuous_loop.md"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


# ---------------------------------------------------------------------------
# Lock (separate window from nightly.lock so the two never block each other)
# ---------------------------------------------------------------------------
def acquire_lock(lock_path: Path) -> int:
    """Acquire the exclusive loop lock; raise RuntimeError if held."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        age = time.time() - lock_path.stat().st_mtime
        if age > STALE_LOCK_SECONDS:
            logger.warning("breaking stale loop lock (%.0fs old): %s", age, lock_path)
            lock_path.unlink(missing_ok=True)
    try:
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError as exc:
        if exc.errno == errno.EEXIST:
            raise RuntimeError(f"loop lock held: {lock_path}") from exc
        raise
    os.write(fd, f"{os.getpid()} {_utc_now_iso()}\n".encode("utf-8"))
    return fd


def release_lock(fd: int, lock_path: Path) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    Path(lock_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Health collection (read-only)
# ---------------------------------------------------------------------------
def _default_db():
    from reality_engine.db.database import db_manager

    return db_manager


def _query_one(conn, sql: str, params: Sequence[Any] = ()) -> Optional[Tuple]:
    try:
        return conn.execute(sql, tuple(params)).fetchone()
    except Exception as exc:  # missing table/column on a partially built DB
        logger.debug("loop health query failed (%s): %s", sql.split()[0:3], exc)
        return None


def _table_count(conn, table: str) -> Optional[int]:
    row = _query_one(conn, f"SELECT COUNT(*) FROM {table}")
    return int(row[0]) if row else None


def _missing_trading_days(db, now=None) -> List[str]:
    try:
        from reality_engine.pipeline.catchup_scheduler import get_missing_trading_days

        return list(get_missing_trading_days(db_manager=db, today=(now.date() if now else None)))
    except Exception as exc:
        logger.debug("missing-trading-day probe failed: %s", exc)
        return []


def _nightly_status(loop_dir: Path) -> Dict[str, Any]:
    """Latest ``data/logs/nightly_<date>.json`` chain-health file."""
    from reality_engine import config

    log_dir = Path(config.DATA_DIR) / "logs"
    out: Dict[str, Any] = {"health_file": None, "age_hours": None}
    try:
        files = sorted(log_dir.glob("nightly_*.json"))
    except OSError:
        return out
    if not files:
        return out
    latest = max(files, key=lambda p: p.stat().st_mtime)
    out["health_file"] = str(latest)
    out["age_hours"] = round((time.time() - latest.stat().st_mtime) / 3600.0, 1)
    try:
        payload = json.loads(latest.read_text(encoding="utf-8"))
    except Exception:
        return out
    stages = payload.get("stages") or {}
    failed = sorted(n for n, v in stages.items() if (v or {}).get("status") == "failed")
    out.update(
        {
            "date_ist": payload.get("date_ist"),
            "part": payload.get("part"),
            "exit_code": payload.get("exit_code"),
            "failed_stages": failed,
            "checkpoint_passed": (payload.get("checkpoint") or {}).get("passed"),
            "top20_overlap": payload.get("top20_overlap"),
        }
    )
    return out


def _reports_status() -> Dict[str, Any]:
    from reality_engine import config

    reports = Path(config.REPORTS_DIR)
    out: Dict[str, Any] = {"latest_alpha_json": None, "age_hours": None}
    try:
        files = sorted(reports.glob("**/daily_alpha_*.json"))
    except OSError:
        return out
    if not files:
        return out
    latest = max(files, key=lambda p: p.stat().st_mtime)
    out["latest_alpha_json"] = str(latest)
    out["age_hours"] = round((time.time() - latest.stat().st_mtime) / 3600.0, 1)
    return out


def _git_status() -> Dict[str, Any]:
    repo = repo_root()
    out: Dict[str, Any] = {"branch": None, "head": None, "dirty_files": 0, "untracked": 0}

    def _git(*args: str) -> Optional[str]:
        try:
            proc = subprocess.run(
                ["git", "-C", str(repo), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except Exception as exc:
            logger.debug("git %s failed: %s", args[0], exc)
            return None
        return proc.stdout if proc.returncode == 0 else None

    head = _git("log", "-1", "--format=%h %ad %s", "--date=short")
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    porcelain = _git("status", "--porcelain")
    if head is not None:
        out["head"] = head.strip()
    if branch is not None:
        out["branch"] = branch.strip()
    if porcelain is not None:
        lines = [ln for ln in porcelain.splitlines() if ln.strip()]
        out["dirty_files"] = sum(1 for ln in lines if not ln.startswith("??"))
        out["untracked"] = sum(1 for ln in lines if ln.startswith("??"))
    return out


def collect_health(db_manager=None, loop_dir: Optional[Path] = None, now=None) -> Dict[str, Any]:
    """Read-only snapshot of everything the loop needs to decide its next move."""
    from reality_engine.pipeline.catchup_scheduler import now_ist

    loop_dir = Path(loop_dir) if loop_dir else default_loop_dir()
    now_ist_dt = now or now_ist()
    health: Dict[str, Any] = {
        "generated_at": _utc_now_iso(),
        "date_ist": now_ist_dt.date().isoformat(),
        "time_ist": now_ist_dt.strftime("%H:%M"),
        "loop_dir": str(loop_dir),
    }

    db = None
    try:
        db = db_manager or _default_db()
    except Exception as exc:
        logger.warning("loop health: DB unavailable (%s)", exc)

    if db is not None:
        try:
            with db.session() as conn:
                price = _query_one(conn, "SELECT MAX(date), COUNT(*) FROM daily_price_delivery")
                health["price"] = {
                    "latest_date": str(price[0])[:10] if price and price[0] else None,
                    "rows": int(price[1]) if price else 0,
                }
                calls = _query_one(
                    conn,
                    "SELECT COUNT(*), MAX(date), MAX(CASE WHEN target_price IS NOT NULL "
                    "THEN date END) FROM eod_scrip_calls",
                )
                health["calls"] = {
                    "rows": int(calls[0]) if calls else 0,
                    "latest_date": str(calls[1])[:10] if calls and calls[1] else None,
                    "latest_thesis_date": str(calls[2])[:10] if calls and calls[2] else None,
                }
                scores = _query_one(
                    conn,
                    "SELECT COUNT(*), MAX(asof_date) FROM model_validation_scores",
                )
                health["validation"] = {
                    "scored_rows": int(scores[0]) if scores else 0,
                    "latest_scored_date": str(scores[1])[:10] if scores and scores[1] else None,
                    "lens_weight_proposals": _table_count(conn, "model_lens_weight_proposals"),
                    "pending_call_dates": _pending_call_dates(conn),
                }
                health["tables"] = {t: _table_count(conn, t) for t in COUNT_TABLES}
        except Exception as exc:
            logger.warning("loop health: DB queries failed (%s)", exc)

        missing = _missing_trading_days(db, now_ist_dt)
        health["price"]["missing_trading_days"] = missing[-10:]
        health["price"]["missing_count"] = len(missing)

    health["nightly"] = _nightly_status(loop_dir)
    health["reports"] = _reports_status()
    health["git"] = _git_status()
    health["loop"] = {
        "state_file": str(loop_dir / STATE_NAME),
        "state_mtime": None,
        "run_index": 0,
        "last_runs": [],
    }
    state_path = loop_dir / STATE_NAME
    if state_path.exists():
        health["loop"]["state_mtime"] = datetime.fromtimestamp(
            state_path.stat().st_mtime, tz=timezone.utc
        ).replace(microsecond=0).isoformat()
    runs = recent_runs(loop_dir, limit=5)
    health["loop"]["last_runs"] = runs
    health["loop"]["run_index"] = _run_count(loop_dir) + 1
    return health


def _pending_call_dates(conn, limit: int = 10) -> List[Dict[str, Any]]:
    """Call dates with no validation scores yet — the harness' open work queue."""
    try:
        cur = conn.execute(
            """
            SELECT c.date AS d,
                   COUNT(*) AS n,
                   SUM(CASE WHEN c.target_price IS NOT NULL THEN 1 ELSE 0 END) AS theses
            FROM eod_scrip_calls c
            LEFT JOIN (SELECT DISTINCT asof_date FROM model_validation_scores) v
                   ON v.asof_date = c.date
            WHERE v.asof_date IS NULL
            GROUP BY c.date
            ORDER BY c.date DESC
            LIMIT ?
            """,
            (int(limit),),
        )
        return [
            {
                "asof_date": str(r[0])[:10],
                "calls": int(r[1] or 0),
                "theses": int(r[2] or 0),
            }
            for r in cur.fetchall()
        ]
    except Exception as exc:
        logger.debug("pending call-date probe failed: %s", exc)
        return []


# ---------------------------------------------------------------------------
# Brief + handoff state
# ---------------------------------------------------------------------------
def read_state(loop_dir: Optional[Path] = None) -> str:
    path = (Path(loop_dir) if loop_dir else default_loop_dir()) / STATE_NAME
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except Exception as exc:
        logger.warning("could not read loop state %s: %s", path, exc)
        return ""


def render_brief(health: Dict[str, Any], state_text: str = "") -> str:
    """Markdown brief: facts first, then deterministic next-action candidates."""
    lines: List[str] = []
    add = lines.append
    add(f"# Continuous loop brief — {health.get('date_ist')} {health.get('time_ist')} IST")
    add("")
    add(f"- run index: **{health.get('loop', {}).get('run_index')}**")
    add(f"- generated: {health.get('generated_at')}")
    add("")

    price = health.get("price") or {}
    calls = health.get("calls") or {}
    val = health.get("validation") or {}
    nightly = health.get("nightly") or {}
    reports = health.get("reports") or {}
    git = health.get("git") or {}

    add("## Data freshness")
    add(f"- latest price bar: `{price.get('latest_date')}` ({price.get('rows')} rows)")
    add(
        f"- missing trading days after that bar: **{price.get('missing_count')}**"
        + (f" → {', '.join(price.get('missing_trading_days') or [])}" if price.get("missing_trading_days") else "")
    )
    add(f"- EOD scrip calls: {calls.get('rows')} rows, latest `{calls.get('latest_date')}`")
    add(f"- latest thesis-bearing call date: `{calls.get('latest_thesis_date')}`")
    add("")

    add("## Wave B validation harness")
    add(f"- scored rows: {val.get('scored_rows')} (latest scored asof `{val.get('latest_scored_date')}`)")
    add(f"- lens-weight proposals on file: {val.get('lens_weight_proposals')}")
    pending = val.get("pending_call_dates") or []
    if pending:
        add("- call dates with **no** scores yet (open harness queue):")
        for p in pending:
            add(f"  - `{p['asof_date']}` — {p['calls']} calls, {p['theses']} with target/SL")
    else:
        add("- call dates with no scores yet: none")
    add("")

    add("## Nightly chain (Wave A)")
    add(f"- health file: `{nightly.get('health_file')}` (age {nightly.get('age_hours')}h)")
    if nightly.get("date_ist"):
        add(
            f"- part `{nightly.get('part')}` for {nightly.get('date_ist')} → exit_code "
            f"**{nightly.get('exit_code')}**, checkpoint passed: {nightly.get('checkpoint_passed')}"
        )
        add(f"- failed stages: {nightly.get('failed_stages') or 'none'}")
        add(f"- top-20 legacy/ensemble overlap: {nightly.get('top20_overlap')}")
    add("")

    add("## Reports")
    add(f"- latest alpha export: `{reports.get('latest_alpha_json')}` (age {reports.get('age_hours')}h)")
    add("")

    tables = health.get("tables") or {}
    if tables:
        add("## Dense substrate / tables")
        add("| table | rows |")
        add("| --- | --- |")
        for name in COUNT_TABLES:
            add(f"| `{name}` | {tables.get(name)} |")
        add("")

    add("## Working tree")
    add(f"- branch `{git.get('branch')}` @ `{git.get('head')}`")
    add(f"- modified: {git.get('dirty_files')}, untracked: {git.get('untracked')}")
    add("")

    last_runs = (health.get("loop") or {}).get("last_runs") or []
    if last_runs:
        add("## Recent loop runs")
        for r in last_runs:
            add(
                f"- #{r.get('run_index')} {r.get('started_at')} — phase `{r.get('phase')}` "
                f"rc={r.get('rc')} {r.get('duration_seconds')}s"
                + (f" — {r.get('note')}" if r.get("note") else "")
            )
        add("")

    add("## Candidate next actions (deterministic hints — you choose)")
    hints: List[str] = []
    if price.get("missing_count"):
        hints.append(
            f"data gap: {price['missing_count']} missing trading day(s) — "
            "`python -m reality_engine.pipeline.catchup_scheduler --mode auto`"
        )
    if nightly.get("exit_code") not in (None, 0):
        hints.append(f"nightly exited {nightly['exit_code']} — inspect failed stages {nightly.get('failed_stages')}")
    if pending:
        hints.append(
            f"{len(pending)} call date(s) unscored — run "
            "`reality_engine.processing.validation_harness.score_predictions(<asof>)` for dates that now have enough forward bars"
        )
    if val.get("lens_weight_proposals"):
        hints.append(
            f"{val['lens_weight_proposals']} lens-weight proposal(s) pending — "
            "`fit_lens_weights` more cohorts, then decide deliberately on `apply_calibration` (never blind)"
        )
    if git.get("dirty_files"):
        hints.append(f"{git['dirty_files']} modified file(s) uncommitted — finish or commit the in-flight slice")
    if not hints:
        hints.append("no mechanical gap detected — pick the highest-value open item from STATE.md / tasks/todo.md")
    for h in hints:
        add(f"- {h}")
    add("")

    state = (state_text or "").strip()
    add(f"## Previous handoff (`{STATE_NAME}`)")
    if state:
        if len(state) > MAX_BRIEF_STATE_CHARS:
            state = state[:MAX_BRIEF_STATE_CHARS] + "\n… [truncated]"
        add("")
        add(state)
    else:
        add("_none yet — first run: establish the baseline and write it._")
    add("")
    return "\n".join(lines) + "\n"


def write_brief(loop_dir: Path, health: Dict[str, Any], state_text: str = "") -> Path:
    day_dir = Path(loop_dir) / str(health.get("date_ist") or "unknown")
    day_dir.mkdir(parents=True, exist_ok=True)
    stamp = str(health.get("time_ist") or "0000").replace(":", "")
    path = day_dir / f"brief_{stamp}.md"
    path.write_text(render_brief(health, state_text), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Run log
# ---------------------------------------------------------------------------
def _run_log_path(loop_dir: Path) -> Path:
    return Path(loop_dir) / RUN_LOG_NAME


def _run_count(loop_dir: Path) -> int:
    path = _run_log_path(loop_dir)
    if not path.exists():
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            return sum(1 for ln in f if ln.strip())
    except OSError:
        return 0


def append_run_log(loop_dir: Path, record: Dict[str, Any]) -> Path:
    path = _run_log_path(loop_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")
    return path


def recent_runs(loop_dir: Optional[Path] = None, limit: int = 5) -> List[Dict[str, Any]]:
    path = _run_log_path(Path(loop_dir) if loop_dir else default_loop_dir())
    if not path.exists():
        return []
    rows: List[Dict[str, Any]] = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for ln in f:
                ln = ln.strip()
                if not ln:
                    continue
                try:
                    rows.append(json.loads(ln))
                except Exception:
                    continue
    except OSError:
        return []
    return rows[-limit:]


# ---------------------------------------------------------------------------
# Agent pass
# ---------------------------------------------------------------------------
def session_exists(session_dir: Path) -> bool:
    try:
        return any(p.is_file() for p in Path(session_dir).rglob("*"))
    except OSError:
        return False


def build_agent_command(
    brief_path: Path,
    loop_dir: Optional[Path] = None,
    prompt_path: Optional[Path] = None,
    marker: str = "",
    max_time: str = DEFAULT_MAX_TIME,
    resume: Optional[bool] = None,
) -> List[str]:
    """Build the headless ``omp`` invocation for one iteration pass."""
    loop_dir = Path(loop_dir) if loop_dir else default_loop_dir()
    prompt_path = Path(prompt_path) if prompt_path else prompt_file()
    session_dir = loop_dir / SESSIONS_SUBDIR
    if resume is None:
        resume = session_exists(session_dir)
    cmd: List[str] = [
        os.environ.get("OMP_BIN", "omp"),
        "-p",
        "--cwd",
        str(repo_root()),
        "--session-dir",
        str(session_dir),
        "--auto-approve",
        "--no-title",
        "--max-time",
        max_time,
    ]
    if resume:
        cmd.append("--continue")
    cmd.append(f"@{prompt_path}")
    cmd.append(f"@{brief_path}")
    cmd.append(marker or "Continuous loop iteration pass.")
    return cmd


def run_agent(
    cmd: Sequence[str],
    timeout_seconds: int,
    log_path: Optional[Path] = None,
) -> Dict[str, Any]:
    started = time.time()
    try:
        proc = subprocess.run(
            list(cmd),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        rc, out, err = proc.returncode, proc.stdout or "", proc.stderr or ""
        timed_out = False
    except subprocess.TimeoutExpired as exc:
        rc, timed_out = 124, True
        out = (exc.stdout or "") if isinstance(exc.stdout, str) else ""
        err = ((exc.stderr or "") if isinstance(exc.stderr, str) else "") + "\n[loop] hard timeout"
    except FileNotFoundError as exc:
        rc, timed_out, out, err = 127, False, "", f"omp not found: {exc}"
    if log_path is not None:
        try:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_path.write_text(out + ("\n--- stderr ---\n" + err if err else ""), encoding="utf-8")
        except OSError as exc:
            logger.warning("could not write agent log %s: %s", log_path, exc)
    return {
        "rc": rc,
        "timed_out": timed_out,
        "duration_seconds": round(time.time() - started, 1),
        "stdout_tail": "\n".join(out.splitlines()[-LOG_TAIL_LINES:]),
        "stderr_tail": "\n".join(err.splitlines()[-LOG_TAIL_LINES:]),
        "log_file": str(log_path) if log_path else None,
    }


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
def resolve_timeout(max_time: str) -> int:
    """`20m` / `90s` / `1200` → seconds, plus a hard-kill grace."""
    text = str(max_time).strip().lower()
    multipliers = {"s": 1, "m": 60, "h": 3600}
    try:
        if text and text[-1] in multipliers:
            base = int(float(text[:-1]) * multipliers[text[-1]])
        else:
            base = int(float(text))
    except (ValueError, IndexError):
        base = int(float(DEFAULT_MAX_TIME[:-1]) * 60)
    return max(60, base + AGENT_TIMEOUT_GRACE_SECONDS)


def run_once(
    phase: str = "iterate",
    loop_dir: Optional[Path] = None,
    db_manager=None,
    max_time: str = DEFAULT_MAX_TIME,
    notify: bool = False,
    agent_runner=None,
    now=None,
) -> Dict[str, Any]:
    """One loop tick. ``phase='check'`` stops after the brief."""
    loop_dir = Path(loop_dir) if loop_dir else default_loop_dir()
    loop_dir.mkdir(parents=True, exist_ok=True)
    lock_path = loop_dir / LOCK_NAME
    started = time.time()
    record: Dict[str, Any] = {
        "started_at": _utc_now_iso(),
        "phase": phase,
        "run_index": None,
        "rc": None,
    }

    try:
        fd = acquire_lock(lock_path)
    except RuntimeError as exc:
        logger.warning("loop tick skipped: %s", exc)
        record.update({"rc": 2, "note": "lock held — previous tick still running"})
        append_run_log(loop_dir, record)
        return {"phase": phase, "skipped": True, "reason": str(exc)}

    try:
        health = collect_health(db_manager=db_manager, loop_dir=loop_dir, now=now)
        record["run_index"] = health["loop"]["run_index"]
        state_text = read_state(loop_dir)
        brief = write_brief(loop_dir, health, state_text)
        record["brief_file"] = str(brief)
        record["health"] = {
            "latest_price_date": (health.get("price") or {}).get("latest_date"),
            "missing_trading_days": (health.get("price") or {}).get("missing_count"),
            "pending_validation_dates": len((health.get("validation") or {}).get("pending_call_dates") or []),
            "scored_rows": (health.get("validation") or {}).get("scored_rows"),
            "nightly_exit_code": (health.get("nightly") or {}).get("exit_code"),
            "dirty_files": (health.get("git") or {}).get("dirty_files"),
        }

        if phase == "check":
            record.update({"rc": 0, "note": "check-only"})
            result = {"phase": phase, "brief_file": str(brief), "health": record["health"]}
        else:
            marker = (
                f"Continuous loop run #{health['loop']['run_index']} "
                f"({health['date_ist']} {health['time_ist']} IST). "
                "Follow the standing prompt; the attached brief is this run's state."
            )
            cmd = build_agent_command(brief, loop_dir=loop_dir, marker=marker, max_time=max_time)
            runner = agent_runner or run_agent
            stamp = str(health.get("time_ist") or "0000").replace(":", "")
            agent_log = loop_dir / str(health["date_ist"]) / AGENT_LOG_SUBDIR / f"agent_{stamp}.log"
            if agent_runner is None:
                agent = runner(cmd, timeout_seconds=resolve_timeout(max_time), log_path=agent_log)
            else:
                agent = runner(cmd, timeout_seconds=resolve_timeout(max_time))
            record.update(
                {
                    "rc": agent.get("rc"),
                    "duration_seconds": agent.get("duration_seconds"),
                    "timed_out": agent.get("timed_out"),
                    "agent_log": agent.get("log_file"),
                }
            )
            result = {
                "phase": phase,
                "brief_file": str(brief),
                "health": record["health"],
                "agent": agent,
            }

        record.setdefault("duration_seconds", round(time.time() - started, 1))
        append_run_log(loop_dir, record)

        if notify:
            result["notified"] = _notify(health, record)
        return result
    finally:
        release_lock(fd, lock_path)


def _notify(health: Dict[str, Any], record: Dict[str, Any]) -> bool:
    try:
        from reality_engine.reporting.notifier import send_telegram

        val = health.get("validation") or {}
        msg = (
            f"Reality Engine loop #{record.get('run_index')} ({record.get('phase')}) rc={record.get('rc')}\n"
            f"price bar { (health.get('price') or {}).get('latest_date') }, "
            f"missing days {(health.get('price') or {}).get('missing_count')}, "
            f"unscored call dates {len(val.get('pending_call_dates') or [])}, "
            f"scored rows {val.get('scored_rows')}, "
            f"nightly rc {(health.get('nightly') or {}).get('exit_code')}, "
            f"dirty { (health.get('git') or {}).get('dirty_files')}"
        )
        return bool(send_telegram(msg))
    except Exception as exc:
        logger.warning("loop notify failed: %s", exc)
        return False


# ---------------------------------------------------------------------------
# Scheduled task management (Windows Task Scheduler; cron guidance elsewhere)
# ---------------------------------------------------------------------------
def _task_command() -> str:
    scripts = repo_root() / "reality_engine" / "scripts"
    return f'wscript.exe "{scripts / "run_hidden.vbs"}" "{scripts / "run_continuous_loop.cmd"}"'


def install_task(interval_minutes: int = TASK_INTERVAL_MINUTES) -> Dict[str, Any]:
    if os.name != "nt":
        return {
            "ok": False,
            "reason": "not Windows — add a crontab entry instead",
            "cron": f"*/{interval_minutes} * * * * cd {repo_root()} && python -m reality_engine.pipeline.continuous_loop --agent",
        }
    cmd = [
        "schtasks",
        "/create",
        "/tn",
        TASK_NAME,
        "/sc",
        "MINUTE",
        "/mo",
        str(int(interval_minutes)),
        "/tr",
        _task_command(),
        "/f",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "ok": proc.returncode == 0,
        "command": " ".join(cmd),
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


def uninstall_task() -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows"}
    proc = subprocess.run(
        ["schtasks", "/delete", "/tn", TASK_NAME, "/f"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {"ok": proc.returncode == 0, "stdout": (proc.stdout or "").strip(), "stderr": (proc.stderr or "").strip()}


def task_status() -> Dict[str, Any]:
    if os.name != "nt":
        return {"ok": False, "reason": "not Windows"}
    proc = subprocess.run(
        ["schtasks", "/query", "/tn", TASK_NAME, "/fo", "LIST", "/v"],
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "ok": proc.returncode == 0,
        "registered": proc.returncode == 0,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Continuous 30-minute loop: harness check + unattended agent iteration pass."
    )
    parser.add_argument("--check", action="store_true", help="Health brief only; never spawns the agent")
    parser.add_argument("--agent", action="store_true", help="Check + headless agent iteration pass (what the scheduler runs)")
    parser.add_argument("--max-time", default=DEFAULT_MAX_TIME, help=f"Agent pass cap (default {DEFAULT_MAX_TIME})")
    parser.add_argument("--loop-dir", default=None, help="Override the loop state directory")
    parser.add_argument("--notify", action="store_true", help="Send the Telegram digest (no-op without creds)")
    parser.add_argument("--install", action="store_true", help=f"Register the {TASK_INTERVAL_MINUTES}-minute Windows scheduled task")
    parser.add_argument("--uninstall", action="store_true", help="Delete the scheduled task")
    parser.add_argument("--status", action="store_true", help="Show scheduled-task status")
    parser.add_argument("--verbose", action="store_true", help="Debug logging")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.install:
        res = install_task()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.uninstall:
        res = uninstall_task()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1
    if args.status:
        res = task_status()
        print(json.dumps(res, indent=2))
        return 0 if res.get("ok") else 1

    phase = "iterate" if args.agent else "check"
    loop_dir = Path(args.loop_dir) if args.loop_dir else None
    result = run_once(phase=phase, loop_dir=loop_dir, max_time=args.max_time, notify=args.notify)
    if result.get("skipped"):
        print(json.dumps({"skipped": True, "reason": result.get("reason")}, indent=2))
        return 2
    print(json.dumps({k: v for k, v in result.items() if k != "agent"}, indent=2, default=str))
    if "agent" in result:
        agent = result["agent"]
        print(f"\n[loop] agent rc={agent.get('rc')} in {agent.get('duration_seconds')}s")
        if agent.get("stdout_tail"):
            print("\n--- agent output (tail) ---\n" + agent["stdout_tail"])
        if agent.get("stderr_tail"):
            print("\n--- agent stderr (tail) ---\n" + agent["stderr_tail"])
        return 0 if agent.get("rc") == 0 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
