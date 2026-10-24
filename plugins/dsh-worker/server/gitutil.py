"""Bounded git helpers: working-tree snapshots, worktrees and auto-commit.

Nothing here pushes, resets or switches branches in the main checkout.  Worktree
creation is the only main-checkout mutation, and it is always explicit
(``start_worker(use_worktree=true)``).
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

MAX_ENTRIES = 2000


class GitError(RuntimeError):
    """A git command needed for worktree setup/commit failed."""


def _hidden() -> int:
    return 0x08000000 if os.name == "nt" else 0


def _git(repo: Path, args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            ["git", "-C", str(repo), *args],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            creationflags=_hidden(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"git unavailable: {type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def worktrees(repo_root: Path) -> list[dict[str, Any]]:
    """Registered worktrees of ``repo_root`` (empty when it is not a git repo)."""
    code, out, _err = _git(repo_root, ["worktree", "list", "--porcelain"])
    if code != 0:
        return []
    entries: list[dict[str, Any]] = []
    current: dict[str, Any] = {}
    for line in out.splitlines():
        if not line.strip():
            if current:
                entries.append(current)
                current = {}
            continue
        key, _, value = line.partition(" ")
        if key == "worktree":
            current["path"] = value
        elif key == "HEAD":
            current["head"] = value
        elif key == "branch":
            current["branch"] = value.removeprefix("refs/heads/")
        elif key == "detached":
            current["detached"] = True
    if current:
        entries.append(current)
    return entries


def worktree_add(
    repo_root: Path, path: Path, branch: str, base_ref: str = "HEAD"
) -> dict[str, Any]:
    """``git worktree add <path> -b <branch> <base>``; raises ``GitError``."""
    if path.exists():
        raise GitError(f"worktree path already exists: {path}")
    code, out, err = _git(repo_root, ["rev-parse", "--verify", f"{base_ref}^{{commit}}"])
    if code != 0:
        raise GitError(f"base ref {base_ref!r} is not a commit: {(err or out).strip()[:300]}")
    base_commit = out.strip().splitlines()[-1] if out.strip() else ""
    if not base_commit:
        raise GitError(f"base ref {base_ref!r} did not resolve to a commit")
    path.parent.mkdir(parents=True, exist_ok=True)
    code, out, err = _git(
        repo_root, ["worktree", "add", "-b", branch, str(path), base_commit]
    )
    if code != 0:
        raise GitError(f"git worktree add failed: {(err or out).strip()[:500]}")
    return {
        "path": str(path),
        "branch": branch,
        "base": base_ref,
        "base_commit": base_commit,
    }


def worktree_remove(repo_root: Path, path: Path, branch: str | None = None) -> None:
    """Best-effort cleanup used only before a worker was ever spawned."""
    _git(repo_root, ["worktree", "remove", "--force", str(path)])
    if branch:
        _git(repo_root, ["branch", "-D", branch])


def commit_worktree(
    worktree: Path,
    *,
    job_id: str,
    subject: str,
    base_commit: str | None = None,
) -> dict[str, Any]:
    """Commit every change in ``worktree``; no commit on an empty diff.

    The commit author/committer come from the repository's git config.  A git
    failure is returned as data, never raised: a finished worker must not be
    reclassified because its post-run commit failed.
    """
    worktree = Path(worktree)
    result: dict[str, Any] = {
        "committed": False,
        "branch": None,
        "base": base_commit,
        "head": None,
        "commits": None,
        "files_changed": None,
        "files_changed_paths": [],
        "message": subject,
        "trailer": f"DSH-Job: {job_id}",
    }

    def fail(step: str, err: str) -> dict[str, Any]:
        result["error"] = f"{step}: {err.strip()[:400] or 'git failed'}"
        return result

    code, out, err = _git(worktree, ["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return fail("rev-parse --abbrev-ref", err or out)
    result["branch"] = out.strip()
    code, out, err = _git(worktree, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if code != 0:
        return fail("git status", err or out)
    dirty = bool(out.replace("\0", "").strip())
    if dirty:
        code, out, err = _git(worktree, ["add", "-A"])
        if code != 0:
            return fail("git add -A", err or out)
        code, out, err = _git(
            worktree, ["commit", "-m", subject, "-m", f"DSH-Job: {job_id}"]
        )
        if code != 0:
            return fail("git commit", err or out)
        result["committed"] = True
    else:
        result["reason"] = "no_changes"
    code, out, err = _git(worktree, ["rev-parse", "HEAD"])
    if code != 0:
        return fail("rev-parse HEAD", err or out)
    result["head"] = out.strip()
    if base_commit and result["head"]:
        code, out, _err = _git(
            worktree, ["rev-list", "--count", f"{base_commit}..{result['head']}"]
        )
        if code == 0 and out.strip().isdigit():
            result["commits"] = int(out.strip())
        code, out, _err = _git(
            worktree,
            ["diff", "--name-only", "-z", f"{base_commit}..{result['head']}"],
        )
        if code == 0:
            paths = [p for p in out.split("\0") if p]
            result["files_changed"] = len(paths)
            result["files_changed_paths"] = sorted(paths)[:MAX_ENTRIES]
    return result


# -------------------------------------------------------------- merge queue
def rev_parse(repo: Path, ref: str) -> str | None:
    code, out, _err = _git(repo, ["rev-parse", "--verify", f"{ref}^{{commit}}"])
    if code != 0 or not out.strip():
        return None
    return out.strip().splitlines()[-1]


def current_branch(repo: Path) -> str | None:
    code, out, _err = _git(repo, ["symbolic-ref", "--quiet", "--short", "HEAD"])
    return out.strip() if code == 0 and out.strip() else None


def is_ancestor(repo: Path, ancestor: str, descendant: str) -> bool:
    code, _out, _err = _git(repo, ["merge-base", "--is-ancestor", ancestor, descendant])
    return code == 0


def merge_base(repo: Path, left: str, right: str) -> str | None:
    code, out, _err = _git(repo, ["merge-base", left, right])
    return out.strip() if code == 0 and out.strip() else None


def changed_paths(repo: Path, revision_range: str) -> list[str]:
    code, out, _err = _git(repo, ["diff", "--name-only", "-z", revision_range])
    if code != 0:
        return []
    return [path for path in out.split("\0") if path]


def status_paths(repo: Path) -> tuple[set[str], set[str]]:
    """Return (tracked-dirty paths, untracked paths) for a checkout."""
    code, out, _err = _git(repo, ["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if code != 0:
        raise GitError("git status failed while checking the target checkout")
    tracked: set[str] = set()
    untracked: set[str] = set()
    tokens = out.split("\0")
    index = 0
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if not token or len(token) < 4:
            continue
        code2 = token[:2]
        path = token[3:]
        if code2 == "??":
            untracked.add(path)
        else:
            tracked.add(path)
        if code2[:1] in ("R", "C") and index < len(tokens):
            index += 1  # rename/copy source token
    return tracked, untracked


def merge_in_progress(repo: Path) -> bool:
    code, _out, _err = _git(repo, ["rev-parse", "--quiet", "--verify", "MERGE_HEAD"])
    return code == 0


def merge_no_ff(
    repo: Path,
    branch: str,
    message: str,
    mergiraf: str | None = None,
    attributes_file: Path | None = None,
) -> tuple[int, str, str]:
    args = ["merge", "--no-ff", "-m", message]
    if mergiraf and attributes_file is not None:
        driver = (
            f'"{mergiraf}" merge --git %O %A %B -s %S -x %X -y %Y -p %P -l %L'
        )
        args = [
            "-c",
            f"merge.mergiraf.driver={driver}",
            "-c",
            f"core.attributesFile={attributes_file}",
            *args,
        ]
    return _git(repo, [*args, branch], timeout=120.0)


def conflicted_paths(repo: Path) -> list[str]:
    code, out, _err = _git(repo, ["diff", "--name-only", "--diff-filter=U", "-z"])
    if code != 0:
        return []
    return [path for path in out.split("\0") if path]


def conflict_hunks(repo: Path, path: str, limit: int = 10) -> dict[str, Any]:
    """Count combined-diff hunks for one conflicted file (bounded summary)."""
    code, out, _err = _git(repo, ["diff", "--cc", "--unified=0", "--", path])
    if code != 0:
        return {"hunks": 0, "headers": []}
    headers = [line.strip()[:200] for line in out.splitlines() if line.startswith("@@")]
    return {"hunks": len(headers), "headers": headers[:limit]}


def abort_merge(repo: Path) -> bool:
    code, _out, _err = _git(repo, ["merge", "--abort"])
    return code == 0


def reset_hard(repo: Path, head: str) -> bool:
    code, _out, _err = _git(repo, ["reset", "--hard", head], timeout=120.0)
    return code == 0


def count_commits(repo: Path, revision_range: str) -> int | None:
    code, out, _err = _git(repo, ["rev-list", "--count", revision_range])
    if code != 0 or not out.strip().isdigit():
        return None
    return int(out.strip())


def delete_branch(repo: Path, branch: str, force: bool = False) -> tuple[bool, str]:
    flag = "-D" if force else "-d"
    code, out, err = _git(repo, ["branch", flag, branch])
    return code == 0, (out or err).strip()[:300]


def remove_worktree_path(repo: Path, path: Path) -> tuple[bool, str]:
    code, out, err = _git(repo, ["worktree", "remove", str(path)], timeout=120.0)
    return code == 0, (out or err).strip()[:500]


def remove_worktree_registration(repo: Path) -> None:
    _git(repo, ["worktree", "prune"])


def remote_url(repo: Path, remote: str = "origin") -> str | None:
    code, out, _err = _git(repo, ["remote", "get-url", remote])
    return out.strip() if code == 0 and out.strip() else None


def push_ref(repo: Path, remote: str, target: str, timeout: float = 120.0) -> tuple[int, str, str]:
    return _git(repo, ["push", remote, target], timeout=timeout)


def mergiraf_path(environ: dict[str, str] | None = None) -> str | None:
    """Detect mergiraf on PATH; never installs or configures anything globally.

    ``DSH_WORKER_MERGIRAF=0`` (or an empty value) disables detection, which the
    offline tests use; a path overrides the PATH lookup.
    """
    import shutil

    env = os.environ if environ is None else environ
    override = env.get("DSH_WORKER_MERGIRAF")
    if override is not None:
        if override.strip() in ("", "0", "false", "off"):
            return None
        candidate = Path(override).expanduser()
        return str(candidate) if candidate.is_file() else None
    path = env.get("PATH")
    return shutil.which("mergiraf", path=path) if path else shutil.which("mergiraf")


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
