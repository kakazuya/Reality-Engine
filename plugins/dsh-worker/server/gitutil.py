"""Bounded git helpers: working-tree snapshots, worktrees and auto-commit.

Nothing here pushes, resets or switches branches in the main checkout.  Worktree
creation is the only main-checkout mutation, and it is always explicit
(``start_worker(use_worktree=true)``).
"""
from __future__ import annotations

import os
import re
import stat
import subprocess
from pathlib import Path
from typing import Any

MAX_ENTRIES = 2000
# The empty tree.  Git can resolve it without the object being present for the
# SHA-1 object format (every checkout in this repository); a SHA-256 repository
# would refuse the command, which fails closed.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"
FILE_ATTRIBUTE_REPARSE_POINT = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


class GitError(RuntimeError):
    """A git command needed for worktree setup/commit failed."""


def _hidden() -> int:
    return 0x08000000 if os.name == "nt" else 0


# One entry per code path git could take from repository config/attributes.
# These are passed to EVERY trusted invocation, not only to the commit: a
# worker-writable checkout may set any of them, and a snapshot must not execute
# worker code either.  Command-line config wins over repository-local config,
# including values pulled in with include.path.
_SAFE_GIT_CONFIG = (
    # Hooks (pre-commit, post-checkout, post-index-change, ...) live in the git
    # dir, which a repo-root worker can write; point them at the null device.
    "-c",
    f"core.hooksPath={os.devnull}",
    # fsmonitor names a program/hook git runs on status/index refresh.
    "-c",
    "core.fsmonitor=false",
    # sshCommand and external diff programs are executed by git.
    "-c",
    "core.sshCommand=",
    "-c",
    "diff.external=",
    # Attribute files can select filter/diff/merge drivers; --attr-source (below)
    # replaces the in-tree files and this drops the configured global one.
    "-c",
    f"core.attributesFile={os.devnull}",
    # Commit signing runs gpg.program; a worker commit is never signed.
    "-c",
    "commit.gpgSign=false",
    "-c",
    "gpg.program=",
    # Editors are not launched for -m commits, but neutralise them anyway.
    "-c",
    "core.editor=",
    "-c",
    "sequence.editor=",
    # An empty pager means no pager process is started at all.
    "-c",
    "core.pager=",
)
# Environment hardening for every trusted invocation: no system/global config
# (host hooksPath/filter/gpg/fsmonitor), no credential prompt, and attributes
# read from the empty tree instead of any in-tree/info attribute file.
_SAFE_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ATTR_SOURCE": EMPTY_TREE,
    "GIT_PAGER": "",
}
_GIT_ENV_KEYS = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_COMMON_DIR",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
)


def _run_git(
    argv: list[str],
    *,
    cwd: str | None = None,
    timeout: float = 30.0,
    env: dict[str, str] | None = None,
) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(
            argv,
            cwd=cwd,
            capture_output=True,
            text=True,
            # Git for Windows prints repository paths as UTF-8.  Decoding with the
            # process locale (cp1252 on a non-UTF-8 host) corrupts any non-ASCII
            # path, so an unchanged workspace compares unequal to the identity
            # captured at start and every commit is refused as "moved".
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            creationflags=_hidden(),
            env=env,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", f"git unavailable: {type(exc).__name__}: {exc}"
    return completed.returncode, completed.stdout, completed.stderr


def _git(repo: Path, args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
    return _run_git(["git", "-C", str(repo), *args], timeout=timeout)


def _git_env() -> dict[str, str]:
    env = {key: value for key, value in os.environ.items() if key not in _GIT_ENV_KEYS}
    env.update(_SAFE_GIT_ENV)
    return env


_ATTR_SOURCE_SUPPORTED: bool | None = None
_ATTR_DRIVER = re.compile(r"(?:^|\s)(?:filter|diff|merge)=", re.MULTILINE)


def _attr_source_supported() -> bool:
    """Whether this git accepts ``--attr-source`` (Git 2.40+; detected, cached)."""
    global _ATTR_SOURCE_SUPPORTED
    if _ATTR_SOURCE_SUPPORTED is None:
        try:
            completed = subprocess.run(
                ["git", f"--attr-source={EMPTY_TREE}", "--version"],
                capture_output=True,
                timeout=10,
                creationflags=_hidden(),
                env=_git_env(),
            )
            _ATTR_SOURCE_SUPPORTED = completed.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            _ATTR_SOURCE_SUPPORTED = False
    return _ATTR_SOURCE_SUPPORTED


def _attributes_driver_error(git_dir: str, work_tree: str) -> str | None:
    """Refuse to touch a checkout whose attributes select an external driver.

    ``--attr-source`` replaces in-tree ``.gitattributes``, but git still reads
    ``<git_dir>/info/attributes`` (there is no config switch for it) and a
    repo-root job can write it.  Older git also cannot replace in-tree
    attributes, so scan them, bounded, and refuse any ``filter=``/``diff=``/
    ``merge=`` selection rather than run a worker-controlled program.
    """
    info = Path(git_dir) / "info" / "attributes"
    try:
        if info.is_file() and _ATTR_DRIVER.search(
            info.read_text(encoding="utf-8", errors="replace")[:65_536]
        ):
            return "git_attributes_driver_refused"
    except OSError:
        return "git_attributes_driver_refused"
    if _attr_source_supported():
        return None
    seen = 0
    for root, dirs, files in os.walk(work_tree):
        dirs[:] = [name for name in dirs if name != ".git"]
        seen += len(files)
        if seen > 20_000:
            # Cannot prove the attributes are inert; fail closed.
            return "git_attributes_scan_incomplete"
        if ".gitattributes" not in files:
            continue
        try:
            text = (Path(root) / ".gitattributes").read_text(
                encoding="utf-8", errors="replace"
            )[:65_536]
        except OSError:
            return "git_attributes_driver_refused"
        if _ATTR_DRIVER.search(text):
            return "git_attributes_driver_refused"
    return None


def _identity_git_config(identity: Any) -> list[str]:
    """Checkout settings captured at start that affect working-tree content/commit.

    The hardened runner ignores global/system config, so ``core.autocrlf`` /
    ``core.eol`` must be replayed from the identity; otherwise a worktree
    checked out with CRLF looks fully modified and every commit rewrites whole
    files.  ``user.name``/``user.email`` are replayed for the same reason: this
    repository keeps its author identity in the global config, which the
    hardened runner deliberately does not read.  The values come from the
    manager's pre-launch capture, never from the worker-writable repository
    config read at commit time; each is a single bounded argv value.
    """
    if not isinstance(identity, dict):
        return []
    options: list[str] = []
    for key in ("core.autocrlf", "core.eol", "user.name", "user.email"):
        value = identity.get(key)
        if (
            isinstance(value, str)
            and 0 < len(value) <= 200
            and "\x00" not in value
            and "\r" not in value
            and "\n" not in value
        ):
            options += ["-c", f"{key}={value}"]
    return options


def _trusted_git(
    git_dir: str,
    work_tree: str,
    args: list[str],
    timeout: float = 30.0,
    identity: Any = None,
) -> tuple[int, str, str]:
    """Run git against a stored git dir/work tree with repo code paths disabled."""
    argv = ["git", f"--git-dir={git_dir}", f"--work-tree={work_tree}"]
    if _attr_source_supported():
        # Read attributes from the empty tree: in-tree .gitattributes cannot
        # select a filter=/diff=/merge= driver.
        argv.append(f"--attr-source={EMPTY_TREE}")
    argv += [*_SAFE_GIT_CONFIG, *_identity_git_config(identity), *args]
    return _run_git(argv, cwd=work_tree, timeout=timeout, env=_git_env())


def _path_key(path: Any) -> str:
    candidate = Path(path)
    try:
        candidate = candidate.resolve()
    except (OSError, RuntimeError, ValueError):
        candidate = candidate.absolute()
    return os.path.normcase(os.path.normpath(str(candidate)))


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


def worktree_git_dirs(
    workspace: Path,
) -> tuple[Path | None, Path | None, Path | None]:
    """Return ``(git_dir, common_dir, toplevel)`` for a checkout.

    ``(None, None, None)`` when ``workspace`` is not inside a git checkout.  A
    linked worktree's ``git_dir`` is ``<main>/.git/worktrees/<name>`` while its
    own ``.git`` is a file; ``toplevel`` lets the caller reject an arbitrary
    subdirectory of a checkout (git would otherwise walk up to its root).
    """
    code, out, _err = _git(Path(workspace), ["rev-parse", "--absolute-git-dir"])
    if code != 0 or not out.strip():
        return None, None, None
    git_dir = Path(out.strip())
    code, out, _err = _git(Path(workspace), ["rev-parse", "--show-toplevel"])
    if code != 0 or not out.strip():
        return git_dir, None, None
    toplevel = Path(out.strip())
    code, out, _err = _git(Path(workspace), ["rev-parse", "--git-common-dir"])
    if code != 0 or not out.strip():
        return git_dir, None, toplevel
    common = Path(out.strip())
    if not common.is_absolute():
        common = Path(workspace) / common
    return git_dir, common, toplevel


def checkout_identity(workspace: Path) -> dict[str, Any] | None:
    """Capture a checkout's real git identity BEFORE a worker can touch it.

    The manager calls this outside the sandbox and persists the result in
    ``job.json``.  The supervisor later commits only against these stored paths:
    ``<workspace>/.git`` is worker-writable, so it must never be the source of
    the git dir.  ``None`` when the workspace is not a checkout or HEAD is
    detached (nothing to commit to).
    """
    workspace = Path(workspace)
    try:
        git_dir, common, toplevel = worktree_git_dirs(workspace)
    except (OSError, RuntimeError, ValueError):
        return None
    if git_dir is None or common is None or toplevel is None:
        return None
    code, out, _err = _git(workspace, ["symbolic-ref", "--quiet", "HEAD"])
    if code != 0 or not out.strip():
        return None
    head_ref = out.strip()
    identity: dict[str, Any] = {
        "git_dir": _path_key(git_dir),
        "common_dir": _path_key(common),
        "toplevel": _path_key(toplevel),
        "head_ref": head_ref,
        "branch": (
            head_ref.removeprefix("refs/heads/")
            if head_ref.startswith("refs/heads/")
            else None
        ),
    }
    # Replay the checkout's author identity and line-ending settings on the
    # hardened runner (which ignores global/system config); otherwise an
    # autocrlf checkout commits every CRLF file as changed and a repository
    # whose identity lives only in the global config cannot commit at all.
    for key in ("core.autocrlf", "core.eol", "user.name", "user.email"):
        code, out, _err = _git(workspace, ["config", "--get", key])
        if code == 0 and out.strip():
            identity[key] = out.strip()
    return identity


def _git_pointer(worktree: Path) -> Path | None:
    """Resolve ``<worktree>/.git`` as data; never trust it, only compare it."""
    dot = Path(worktree) / ".git"
    try:
        if dot.is_dir():
            return dot
        if not dot.is_file():
            return None
        text = dot.read_text(encoding="utf-8", errors="replace")[:4096]
    except OSError:
        return None
    value = text.strip()
    if not value.startswith("gitdir:"):
        return None
    target = Path(value.partition(":")[2].strip())
    if not target.is_absolute():
        target = dot.parent / target
    return target


def identity_error(
    worktree: Path,
    identity: Any,
    repo_root: Path | str | None,
    *,
    allow_main_checkout: bool = False,
) -> str | None:
    """Return why ``identity`` may not be used for a commit/snapshot, else ``None``.

    ``allow_main_checkout`` is only for the read-only snapshot path: the main
    checkout may be snapshotted through its stored identity, but it is never a
    commit target.
    """
    if not isinstance(identity, dict):
        return "git_identity_missing"
    stored: dict[str, str] = {}
    for key in ("git_dir", "common_dir", "toplevel"):
        value = identity.get(key)
        if not isinstance(value, str) or not value:
            return "git_identity_missing"
        stored[key] = _path_key(value)
    if _path_key(worktree) != stored["toplevel"]:
        return "git_workspace_moved"
    if repo_root is None:
        return "git_identity_missing"
    main_git = _path_key(Path(repo_root) / ".git")
    if stored["common_dir"] != main_git:
        # A commit may only ever land in this repository's object store.
        return "git_common_dir_untrusted"
    if stored["git_dir"] == main_git and not allow_main_checkout:
        # The main checkout is never a worker commit target.
        return "git_main_checkout_refused"
    pointer = _git_pointer(worktree)
    if pointer is None or _path_key(pointer) != stored["git_dir"]:
        # The worker rewrote .git (fake gitdir / another repository).
        return "git_dir_tampered"
    return None


def _parse_status_paths(
    output: str, limit: int | None = None
) -> tuple[list[str], bool]:
    """Paths from ``git status --porcelain=v1 -z`` (both sides of a rename)."""
    tokens = output.split("\0")
    paths: list[str] = []
    index = 0
    truncated = False
    while index < len(tokens):
        token = tokens[index]
        index += 1
        if len(token) < 4:
            continue
        code = token[:2]
        paths.append(token[3:])
        if code[:1] in ("R", "C") and index < len(tokens):
            # The rename/copy source follows as its own NUL-delimited token.
            paths.append(tokens[index])
            index += 1
        if limit is not None and len(paths) >= limit:
            truncated = True
            break
    return paths, truncated


def _is_reparse_point(path: Path) -> bool:
    """True for a symlink or a Windows reparse point (junction, mount, ...)."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    if stat.S_ISLNK(info.st_mode):
        return True
    return bool(getattr(info, "st_file_attributes", 0) & FILE_ATTRIBUTE_REPARSE_POINT)


def reparse_point_path(work_tree: Path, paths: list[str]) -> str | None:
    """First status path whose leaf or any ancestor inside the worktree is a link.

    ``git add -A`` follows a junction/symlink and would stage files from outside
    the workspace.  ``status --untracked-files=all`` lists ``link/secret.txt``,
    so every path component (not just the leaf) is checked with ``lstat``.
    """
    root = Path(work_tree)
    for relative in paths:
        parts = [
            part
            for part in relative.replace("\\", "/").split("/")
            if part not in ("", ".")
        ]
        if (
            not parts
            or ".." in parts
            or Path(relative).is_absolute()
            or ":" in parts[0]
        ):
            return relative or "?"
        current = root
        for part in parts:
            current = current / part
            if _is_reparse_point(current):
                return relative
    return None


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
    git: dict[str, Any] | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, Any]:
    """Commit every change in the checkout recorded by the MANAGER.

    ``git`` is the identity captured before the worker started
    (``checkout_identity``) and is the only source of the git dir and work
    tree, so a worker that rewrites ``<workspace>/.git`` cannot redirect the
    commit or run its own hooks.  Hooks, fsmonitor, ssh and external diff are
    neutralised and ``--no-verify`` is passed; a missing or tampered identity
    is refused, never re-derived from the worker's checkout.

    A git failure is returned as data, never raised: a finished worker must not
    be reclassified because its post-run commit failed.
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

    refusal = identity_error(worktree, git, repo_root)
    if refusal is not None:
        result["reason"] = refusal
        result["error"] = f"refused: {refusal}"
        return result
    assert isinstance(git, dict)  # identity_error guarantees this
    git_dir = str(git["git_dir"])
    stored_tree = str(git["toplevel"])

    def trust(args: list[str], timeout: float = 30.0) -> tuple[int, str, str]:
        return _trusted_git(git_dir, stored_tree, args, timeout, identity=git)

    code, out, err = trust(["symbolic-ref", "--quiet", "HEAD"])
    if code != 0 or not out.strip():
        return fail("symbolic-ref HEAD", err or "HEAD is detached or unreadable")
    head_ref = out.strip()
    recorded_head = git.get("head_ref")
    if not (
        head_ref.startswith("refs/heads/dsh/")
        or (isinstance(recorded_head, str) and head_ref == recorded_head)
    ):
        return fail("branch guard", f"HEAD {head_ref!r} is not the job's dsh branch")
    code, out, err = trust(["rev-parse", "--abbrev-ref", "HEAD"])
    if code != 0:
        return fail("rev-parse --abbrev-ref", err or out)
    result["branch"] = out.strip()
    code, out, err = trust(["status", "--porcelain=v1", "-z", "--untracked-files=all"])
    if code != 0:
        return fail("git status", err or out)
    dirty = bool(out.replace("\0", "").strip())
    if dirty:
        attribute_error = _attributes_driver_error(git_dir, stored_tree)
        if attribute_error is not None:
            result["reason"] = attribute_error
            result["error"] = f"refused: {attribute_error}"
            return result
        changed, _truncated = _parse_status_paths(out)
        linked = reparse_point_path(worktree, changed)
        if linked is not None:
            # ``git add -A`` follows a junction/symlink and would stage data from
            # outside the workspace; refuse instead of including it.
            result["reason"] = "reparse_point_in_workspace"
            result["error"] = f"refused: reparse_point_in_workspace: {linked[:300]}"
            return result
        code, out, err = trust(["add", "-A"])
        if code != 0:
            return fail("git add -A", err or out)
        code, out, err = trust(
            ["commit", "--no-verify", "-m", subject, "-m", f"DSH-Job: {job_id}"]
        )
        if code != 0:
            return fail("git commit", err or out)
        result["committed"] = True
    else:
        result["reason"] = "no_changes"
    code, out, err = trust(["rev-parse", "HEAD"])
    if code != 0:
        return fail("rev-parse HEAD", err or out)
    result["head"] = out.strip()
    if base_commit and result["head"]:
        code, out, _err = trust(["rev-list", "--count", f"{base_commit}..{result['head']}"])
        if code == 0 and out.strip().isdigit():
            result["commits"] = int(out.strip())
        code, out, _err = trust(
            ["diff", "--name-only", "-z", f"{base_commit}..{result['head']}"]
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


def snapshot(
    workspace: Path,
    *,
    identity: Any = None,
    repo_root: Path | str | None = None,
    timeout: float = 10.0,
) -> dict[str, Any]:
    """Return a bounded ``git status --porcelain`` snapshot through a stored identity.

    ``<workspace>/.git`` is worker-writable, so the snapshot never lets git
    derive a git dir from it: ``identity`` is the checkout identity the manager
    captured before the worker started, and the command runs through
    ``_trusted_git`` with hooks/fsmonitor/filters/gpg neutralised.  A missing
    identity (legacy job records), a moved workspace or a rewritten pointer
    means no git process runs at all and the snapshot is reported unavailable.
    The snapshot is a working-tree comparison, not attribution: another process
    may edit the same checkout.
    """
    refusal = identity_error(
        Path(workspace), identity, repo_root, allow_main_checkout=True
    )
    if refusal is not None:
        return {"available": False, "reason": refusal, "paths": []}
    assert isinstance(identity, dict)  # identity_error guarantees this
    git_dir = str(identity["git_dir"])
    stored_tree = str(identity["toplevel"])
    try:
        code, out, err = _trusted_git(
            git_dir,
            stored_tree,
            ["status", "--porcelain=v1", "-z", "--untracked-files=all"],
            timeout,
            identity=identity,
        )
    except (OSError, subprocess.TimeoutExpired):
        return {"available": False, "reason": "git_unavailable", "paths": []}
    if code != 0:
        return {
            "available": False,
            "reason": "git_status_failed",
            "paths": [],
            "error": (err or out).strip()[:300],
        }
    paths, truncated = _parse_status_paths(out, MAX_ENTRIES)
    return {
        "available": True,
        "root": stored_tree,
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
