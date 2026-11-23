"""Temp-directory helpers shared by the offline dsh-worker tests.

``tempfile.mkdtemp`` creates its directory with mode 0o700.  Python 3.14 maps
that mode to a Windows ACL that excludes the DSH write-sandbox's restricted
token, so every later write inside the test temp root is denied.  These helpers
create the directory with the inherited ACL instead and clean it up with retries
(worker processes may still be exiting).
"""
from __future__ import annotations

import asyncio
import os
import secrets
import shutil
import stat
import time
from pathlib import Path


def run_async(coro, timeout: float):
    """Run one MCP test coroutine with a Windows-safe event loop.

    The MCP SDK's default Proactor subprocess path needs overlapped named pipes,
    which the DSH agent sandbox denies.  A SelectorEventLoop makes the SDK use
    its subprocess.Popen fallback (anonymous pipes, still job-object contained),
    so the same MCP server/code path is exercised inside and outside the sandbox.
    """
    factory = asyncio.SelectorEventLoop if os.name == "nt" else None
    return asyncio.run(asyncio.wait_for(coro, timeout), loop_factory=factory)


def make_temp_dir(base: Path, prefix: str) -> Path:
    base.mkdir(parents=True, exist_ok=True)
    for _ in range(100):
        path = base / f"{prefix}{secrets.token_hex(6)}"
        try:
            # No mode argument: inherit the sandbox-visible parent ACL.
            os.mkdir(path)
            return path
        except FileExistsError:
            continue
    raise RuntimeError(f"could not create a unique temp dir under {base}")


def _force_remove(func, path: str, _exc) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def remove_tree(path: Path, attempts: int = 40) -> None:
    if not path.exists():
        return
    for _ in range(attempts):
        # Git creates read-only object files in a temp repo's .git directory;
        # plain rmtree(ignore_errors=True) silently leaves the whole tree.
        shutil.rmtree(path, onexc=_force_remove)
        if not path.exists():
            return
        time.sleep(0.1)

