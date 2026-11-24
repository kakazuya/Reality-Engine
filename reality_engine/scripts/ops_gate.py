"""T-241 ops gate: Shivam's 24 Nov operating rules as checks, so they are enforced, not remembered.

Rules (``ops_rules.json``, each with its source):
- heartbeat: a live ``job_watch wait`` (25-minute heartbeats for Wolf and Eagle);
- hy4: the always-on hy4 loop is running, and no read-gate audit checkpoint waits for a grade;
- reportees: DeepSeek has a running dsh job off-peak, Hydrogen a running agy job in DeepSeek peak hours, no agy job
  off-peak, and at most ``max_code_workers`` code workers in all;
- quota: each account's weekly use is on pace for its target (and a 5-hour reading at the hand-off level says
  delegate);
- ssd_only: no database under D:/RealityEngine changed in the last hour outside the allowed folders.

``python -m reality_engine.scripts.ops_gate`` prints one ``RULE <name>: ...`` line per breach (exit 1) or ``ok``.
The Stop hook (``session_hooks.py stop``) blocks once on these lines (``cached_check``: reused for 5 minutes), so
both managers meet a breach at the end of every turn.  Every check is fast and fails open (a broken check prints a ``RULE
ops_gate`` line, never an exception).
"""
from __future__ import annotations

import datetime as dt
import fnmatch
import glob
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import job_watch  # noqa: E402

RULES = Path(__file__).with_name("ops_rules.json")


def load_rules(path: Path | None = None) -> dict[str, Any]:
    return json.loads(Path(path or RULES).read_text(encoding="utf-8"))


def in_peak(now: dt.datetime, rules: dict[str, Any]) -> bool:
    rep = rules["reportees"]
    if now.weekday() not in rep.get("peak_days", [0, 1, 2, 3, 4]):
        return False
    hm = now.strftime("%H:%M")
    return any(a <= hm < b for a, b in (span.split("-") for span in rep["peak_ist"]))


def _cmdlines() -> list[str]:
    import psutil

    out = []
    for proc in psutil.process_iter(["cmdline"]):
        try:
            out.append(" ".join(proc.info.get("cmdline") or []))
        except Exception:  # noqa: BLE001 - a process that vanished is not a breach
            continue
    return out


def running_dsh() -> int:
    """Active dsh code workers; ``start_job`` data jobs (kind ``data_job``) are not code workers."""
    now = dt.datetime.now(dt.timezone.utc)
    n = 0
    for job_dir in job_watch._recent_job_dirs(Path(job_watch.JOBS_DIR), now):
        record = job_watch._read_json(job_dir / "status.json")
        if (isinstance(record, dict) and str(record.get("phase") or "") in job_watch.ACTIVE_PHASES
                and record.get("kind") != "data_job"):
            n += 1
    return n


def hy4_outputs(rules: dict[str, Any], cmds: list[str]) -> set[str]:
    """Output DBs of hy4 reads: the rules' globs plus every ``--out`` of a running ``v2.observations``."""
    outs = {p for g in rules["hy4"]["out_globs"] for p in glob.glob(g)}
    for c in cmds:
        if "v2.observations" in c:
            m = re.search(r"--out[= ](\S+)", c)
            if m:
                outs.add(m.group(1))
    return {Path(o).as_posix() for o in outs}


def running_agy() -> int:
    return sum(1 for line in job_watch.agy_lines() if line.startswith("RUNNING agy"))


def quota_lines(rules: dict[str, Any], now: dt.datetime) -> list[str]:
    q = rules["quota"]
    out = []
    for acc in q["accounts"]:
        start, end = dt.datetime.fromisoformat(acc["from"]), dt.datetime.fromisoformat(acc["by"])
        if not (start <= now <= end):
            continue
        try:
            st = json.loads(Path(acc["config"], "usage_status.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        limits = st.get("rate_limits") or {}
        seven = (limits.get("seven_day") or {}).get("used_percentage")
        five = (limits.get("five_hour") or {}).get("used_percentage")
        if seven is not None:
            share = (now - start) / (end - start)
            expected = acc["from_pct"] + (acc["target_pct"] - acc["from_pct"]) * share
            if float(seven) < expected - q.get("slack_pct", 10):
                out.append(f"RULE quota: {acc['name']} weekly at {seven}% but the pace to {acc['target_pct']}% by "
                           f"{acc['by']} needs ~{expected:.0f}% now - start more work ({acc['source']})")
        if five is not None and float(five) >= q.get("five_hour_handoff_pct", 90):
            out.append(f"RULE quota: {acc['name']} 5-hour window at {five}% - hand work to the other manager, "
                       "Hydrogen or DeepSeek")
    return out


def _is_junction(path: str) -> bool:
    try:
        return os.path.islink(path) or Path(path).is_junction()
    except (OSError, AttributeError):
        return False


def ssd_lines(rules: dict[str, Any], now: dt.datetime) -> list[str]:
    cfg = rules["ssd_only"]
    root = Path(cfg["root"])
    allowed = set(cfg["allowed_dirs"])
    cutoff = now.timestamp() - 3600
    bad = []
    skip = set(cfg.get("skip_dirs", []))
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).relative_to(root).parts)
        if depth == 0:
            # a junction (tg_build -> C:/RealityEngine/tg_build) points at the SSD, so it is not an HDD write
            dirnames[:] = [d for d in dirnames if d not in allowed and d not in skip
                           and not _is_junction(os.path.join(dirpath, d))]
        elif depth >= cfg.get("max_depth", 3):     # tg_build/<run>/cNN/cNN.db sits at depth 3; deeper is raw files
            dirnames[:] = []
        for name in filenames:
            if not (fnmatch.fnmatch(name, "*.db") or fnmatch.fnmatch(name, "*.db-wal")):
                continue
            try:
                if os.stat(os.path.join(dirpath, name)).st_mtime > cutoff:   # a WAL DB moves its -wal file
                    bad.append(os.path.join(dirpath, name))
            except OSError:
                continue
    return [f"RULE ssd_only: database written on the HDD in the last hour: {p} ({cfg['source']})" for p in bad[:5]]


def check(now: dt.datetime | None = None, rules: dict[str, Any] | None = None,
          cmdlines: list[str] | None = None) -> list[str]:
    now = now or dt.datetime.now()
    rules = rules or load_rules()
    lines: list[str] = []
    if not job_watch.waiter_alive(owner=job_watch.waiter_owner()):
        lines.append(f"RULE heartbeat: no live job_watch wait of this account ({job_watch.waiter_owner()}) - arm `python reality_engine/scripts/job_watch.py wait "
                     f"--timeout-seconds {rules['heartbeat']['max_timeout_s']}` in the background "
                     f"({rules['heartbeat']['source']})")
    cmds = cmdlines if cmdlines is not None else _cmdlines()
    hy4 = rules["hy4"]
    readers: dict[str, int] = {}
    for c in cmds:
        m = re.search(r"--out[= ](\S+)", c) if "v2.observations" in c else None
        if m:
            readers[m.group(1)] = readers.get(m.group(1), 0) + 1
    for out, n in sorted(readers.items()):
        if n > 1:   # a loop that survived TaskStop: two readers race on one output and lose pages (24 Nov, 3 times)
            lines.append(f"RULE hy4: {n} readers write {out} at once - kill the older loop's bash and its reader")
    if not any(hy4["loop_pattern"] in c for c in cmds):
        lines.append(f"RULE hy4: the hy4 loop ({hy4['loop_pattern']}) is not running ({hy4['source']})")
    from reality_engine.v2 import read_gate  # noqa: PLC0415
    for out in sorted(hy4_outputs(rules, cmds)):
        for bad in read_gate.pending_checkpoints(out):
            lines.append(f"RULE hy4: audit checkpoint of {out} needs a passing grade ({bad}) - its reading is "
                         "stopped until a manager who did not write its prompt grades it")
    peak = in_peak(now, rules)
    dsh, agy = running_dsh(), running_agy()
    rep = rules["reportees"]
    if not peak and dsh == 0:
        lines.append(f"RULE idle: DeepSeek has no running job off-peak - brief one ({rep['deepseek']['source']})")
    if peak and agy == 0:
        lines.append(f"RULE idle: Hydrogen has no running job in DeepSeek peak hours - brief one "
                     f"({rep['hydrogen']['source']})")
    if not peak and agy > 0:
        lines.append(f"RULE reportees: {agy} Hydrogen job(s) running off-peak; agy is for DeepSeek peak hours "
                     f"({rep['hydrogen']['source']})")
    if dsh + agy > rules["max_code_workers"]:
        lines.append(f"RULE reportees: {dsh + agy} code workers running, limit {rules['max_code_workers']}")
    lines += quota_lines(rules, now)
    lines += ssd_lines(rules, now)
    return lines


def safe_check() -> list[str]:
    try:
        return check()
    except Exception as exc:  # noqa: BLE001 - a hook must never break a session
        return [f"RULE ops_gate: the check itself failed ({type(exc).__name__}: {exc})"]


CACHE = Path(__file__).resolve().parents[2] / ".tmp" / f"ops_gate_{Path(job_watch.waiter_owner()).name.lstrip('.')}.json"   # one per account
CACHE_SECONDS = 300


def cached_check(cache: Path | None = None, max_age: int = CACHE_SECONDS) -> list[str]:
    """``safe_check`` reused for ``max_age`` seconds, so the Stop hook does not pay ~7 s on every turn."""
    path = Path(cache or CACHE)
    try:
        rec = json.loads(path.read_text(encoding="utf-8"))
        if dt.datetime.now().timestamp() - float(rec["at"]) < max_age:
            return list(rec["lines"])
    except (OSError, ValueError, KeyError, TypeError):
        pass
    lines = safe_check()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"at": dt.datetime.now().timestamp(), "lines": lines}), encoding="utf-8")
    except OSError:
        pass
    return lines


def main(argv: list[str] | None = None) -> int:
    lines = safe_check()
    try:
        CACHE.parent.mkdir(parents=True, exist_ok=True)
        CACHE.write_text(json.dumps({"at": dt.datetime.now().timestamp(), "lines": lines}), encoding="utf-8")
    except OSError:
        pass
    print("\n".join(lines) if lines else "ops_gate: ok")
    return 1 if lines else 0


if __name__ == "__main__":
    raise SystemExit(main())
