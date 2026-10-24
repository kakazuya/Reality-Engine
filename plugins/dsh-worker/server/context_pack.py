"""Worker context pack: attach the generated repo/data map to every brief.

``reality_engine/scripts/build_worker_context.py`` writes
``tasks/worker_context/CONTEXT.md``.  This module owns the standing header, the
26-hour staleness rule, the bounded regeneration and the brief lint.  It never
runs a model and never fails a start: a missing, stale or unregenerable pack is
a warning in the job record, and the worker is launched anyway.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CONTEXT_RELATIVE = Path("tasks") / "worker_context" / "CONTEXT.md"
TEMPLATE_RELATIVE = Path("tasks") / "worker_context" / "BRIEF_TEMPLATE.md"
MAX_PACK_AGE_HOURS = 26.0
REGENERATE_TIMEOUT_SECONDS = 60
BUILDER_MODULE = "reality_engine.scripts.build_worker_context"
# The builder stamps its own git HEAD and absolute data root on line 3.  A pack
# committed from another checkout has a fresh mtime on clone but neither matches,
# so mtime alone would call it current.
PACK_HEADER = re.compile(
    r"(?m)^Generated:.*?git HEAD: `(?P<head>[^`]*)`.*?data root: `(?P<data>[^`]*)`"
)

# At most 15 lines: the worker reads CONTEXT.md once, then only task files.
STANDING_HEADER = """\
## Worker context pack (auto-attached)
Read the context pack FIRST, before any other orientation: {pack}
It is the generated repo/data/test/sandbox map for this checkout; do not rediscover it file by file.
Budget: reach your first useful edit within <= 25 tool calls. Read the pack once, then only the files the task names.
The pack is generated, so the repo wins if they disagree; note the drift in your report.
Brief contract (when you write briefs): {template}
Final report format: 1) what changed (files, one line each) 2) how verified (commands + exact pass counts)
3) anything the controller must install/run outside the sandbox 4) open problems 5) tool calls before first edit / total.
"""


def pack_path(repo_root: Path) -> Path:
    return Path(repo_root).resolve() / CONTEXT_RELATIVE


def _aware(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _git_head(repo_root: Path) -> str:
    """Short HEAD of ``repo_root``, or "" when git cannot answer."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return completed.stdout.strip() if completed.returncode == 0 else ""


def _header_mismatch(path: Path, repo_root: Path, data_root: Path) -> bool:
    """True when the pack header names another HEAD or another data root."""
    try:
        with Path(path).open(encoding="utf-8", errors="replace") as handle:
            head_lines = "".join(handle.readline() for _ in range(8))
    except OSError:
        return True
    match = PACK_HEADER.search(head_lines)
    if match is None:
        return True
    if Path(match.group("data")) != Path(data_root).resolve():
        return True
    head = _git_head(repo_root)
    stamped = match.group("head").strip()
    return bool(head) and stamped not in {"", "unknown"} and stamped != head


def is_stale(
    path: Path,
    now: datetime | None = None,
    max_age_hours: float = MAX_PACK_AGE_HOURS,
    repo_root: Path | None = None,
    data_root: Path | None = None,
) -> bool:
    """A missing pack is stale; a future mtime (clock skew) is not.

    When ``repo_root`` and ``data_root`` are given, a header naming a different
    git HEAD or data root is stale too (a fresh checkout clones an old pack with
    an unmodified mtime).
    """
    try:
        modified = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
    except OSError:
        return True
    if repo_root is not None and data_root is not None:
        if _header_mismatch(Path(path), Path(repo_root).resolve(), Path(data_root)):
            return True
    age = _aware(now) - modified
    return age > timedelta(hours=max_age_hours)


def _builder_env(repo_root: Path, data_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(repo_root) + (os.pathsep + existing if existing else "")
    env["PYTHONUTF8"] = "1"
    env["REALITY_DATA_ROOT"] = str(data_root)
    return env


def ensure_pack(
    repo_root: Path,
    data_root: Path,
    now: datetime | None = None,
    timeout: float = REGENERATE_TIMEOUT_SECONDS,
    allow_regeneration: bool = True,
) -> dict[str, Any]:
    """Return pack state, regenerating only when stale (bounded, never raises).

    ``allow_regeneration=False`` skips the builder subprocess.  The manager
    passes it while a mutating repo-root worker is active: that worker can
    rewrite the builder the unsandboxed manager would execute, so the stale
    pack is attached as-is with a warning instead.
    """
    root = Path(repo_root).resolve()
    data = Path(data_root).resolve()
    path = pack_path(root)
    info: dict[str, Any] = {
        "enabled": True,
        "path": str(path),
        "regenerated": False,
        "stale": is_stale(path, now, repo_root=root, data_root=data),
    }
    if not info["stale"]:
        return info
    if not allow_regeneration:
        info["regeneration_skipped"] = "repo_root_writer_active"
        return info
    builder = root / "reality_engine" / "scripts" / "build_worker_context.py"
    if not builder.is_file():
        info["error"] = "builder_missing"
        return info
    try:
        completed = subprocess.run(
            [sys.executable, "-m", BUILDER_MODULE],
            cwd=str(root),
            env=_builder_env(root, data),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1.0, float(timeout)),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        info["error"] = f"{type(exc).__name__}: {exc}"[:300]
        return info
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()[-300:]
        info["error"] = f"builder_exit_{completed.returncode}: {detail}"
        return info
    info["regenerated"] = True
    info["stale"] = not path.is_file()
    if info["stale"]:
        info["error"] = "builder_wrote_no_pack"
    return info


def attach_brief(
    text: str,
    *,
    repo_root: Path,
    data_root: Path,
    now: datetime | None = None,
    allow_regeneration: bool = True,
) -> tuple[str, list[str], dict[str, Any]]:
    """Prepend the standing header + absolute CONTEXT.md path to a brief."""
    info = ensure_pack(repo_root, data_root, now, allow_regeneration=allow_regeneration)
    warnings: list[str] = []
    if info.get("regeneration_skipped"):
        warnings.append(
            "context_pack: skipped regeneration while a mutating repo-root worker "
            "is active; the attached pack may be stale"
        )
    elif info.get("error"):
        warnings.append(
            f"context_pack: {info['error']} (worker launched without a fresh pack)"
        )
    elif info.get("stale"):
        warnings.append(
            "context_pack_stale: tasks/worker_context/CONTEXT.md is older than "
            f"{MAX_PACK_AGE_HOURS:g} h and could not be regenerated"
        )
    template = str(Path(repo_root).resolve() / TEMPLATE_RELATIVE)
    header = STANDING_HEADER.format(pack=info["path"], template=template)
    return f"{header}\n{text}", warnings, info


# ---------------------------------------------------------------- brief lint
_SECTIONS = {
    "Goal": re.compile(r"(?im)^\s{0,3}(#{1,6}\s*|\*\*\s*)?goal\b"),
    "Acceptance checks": re.compile(r"(?im)^\s{0,3}(#{1,6}\s*|\*\*\s*)?acceptance\b"),
    "Test command(s)": re.compile(r"(?im)^\s{0,3}(#{1,6}\s*|\*\*\s*)?test command"),
}
_TEST_COMMAND = re.compile(
    r"(?im)^\s*[-*]?\s*(python(?:\.exe)?\s+-m\s+(?:unittest|pytest)|pytest\b|"
    r"python(?:\.exe)?\s+\S+\.py|claude\s+plugin\s+(?:test|validate))"
)


def lint_brief(text: str) -> list[str]:
    """Warnings (never errors) for a brief missing the template's key sections."""
    warnings: list[str] = []
    for name, pattern in _SECTIONS.items():
        if pattern.search(text):
            continue
        if name == "Test command(s)" and _TEST_COMMAND.search(text):
            continue
        warnings.append(
            f'brief_lint: missing section "{name}" (see {TEMPLATE_RELATIVE.as_posix()})'
        )
    return warnings
