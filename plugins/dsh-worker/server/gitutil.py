"""Bounded working-tree snapshots used only as artifact hints."""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

MAX_ENTRIES = 2000


def _hidden() -> int:
    return 0x08000000 if os.name == "nt" else 0


def snapshot(workspace: Path, timeout: float = 10.0) -> dict[str, Any]:
    """Return a bounded ``git status --porcelain`` snapshot.

    The snapshot is explicitly a working-tree comparison, not a claim that the
    dsh worker made every change: another process may edit the same checkout.
    """
    try:
        root = subprocess.run(
            ["git", "-C", str(workspace), "rev-parse", "--show-toplevel"],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_hidden(),
        )
        if root.returncode != 0:
            return {"available": False, "reason": "not_a_git_worktree", "paths": []}
        status = subprocess.run(
            [
                "git",
                "-C",
                str(workspace),
                "status",
                "--porcelain=v1",
                "-z",
                "--untracked-files=all",
            ],
            capture_output=True,
            timeout=timeout,
            creationflags=_hidden(),
        )
        if status.returncode != 0:
            return {"available": False, "reason": "git_status_failed", "paths": []}
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "git_unavailable", "paths": []}
    tokens = status.stdout.decode("utf-8", "replace").split("\0")
    paths: list[str] = []
    index = 0
    truncated = False
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token:
            continue
        if len(token) < 4:
            continue
        code = token[:2]
        path = token[3:]
        paths.append(path)
        if code[:1] in ("R", "C") and index < len(tokens):
            # The rename/copy source follows as its own NUL-delimited token.
            index += 1
        if len(paths) >= MAX_ENTRIES:
            truncated = True
            break
    return {
        "available": True,
        "root": root.stdout.strip(),
        "paths": sorted(set(paths)),
        "truncated": truncated,
    }


def changed_since(baseline: dict[str, Any] | None, final: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(baseline, dict) or not baseline.get("available"):
        return {
            "available": False,
            "reason": "no_baseline",
            "paths": [],
            "note": "artifacts unavailable because the workspace was not a git worktree at start",
        }
    if not isinstance(final, dict) or not final.get("available"):
        return {
            "available": False,
            "reason": "final_snapshot_unavailable",
            "paths": [],
            "note": "final working-tree snapshot was unavailable",
        }
    before = set(baseline.get("paths") or [])
    after = set(final.get("paths") or [])
    changed = sorted(after - before)
    return {
        "available": True,
        "scope": "newly_dirty_paths_only",
        "attribution": "not_attempted",
        "paths": changed[:MAX_ENTRIES],
        "truncated": bool(final.get("truncated")) or len(changed) > MAX_ENTRIES,
        "note": (
            "Newly dirty paths only: files already dirty at start are excluded even if "
            "this worker changed them again. Concurrent edits may appear. Inspect the "
            "full working-tree diff for every change; this bounded hint is not "
            "attribution and may omit modified pre-existing dirty files."
        ),
    }
