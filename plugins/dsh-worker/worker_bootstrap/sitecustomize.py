"""Worker-only ``sitecustomize``: keep Python temp dirs usable in the sandbox.

The DSH Windows sandbox spawns commands under a ``WRITE_RESTRICTED`` token whose
restricting SIDs carry the workspace and temp capabilities.  Python 3.14's
``os.mkdir(path, 0o700)`` (and therefore ``tempfile.mkdtemp()``) creates a
directory with an explicit owner-only DACL, which cuts off the inheritable
capability ACE; the restricted token can create the directory but cannot write
inside it.  That is the 2026-10-24 ``tempfile.mkdtemp()`` failure.

The patch applies ONLY to a sandboxed Windows worker: ``sys.platform ==
"win32"`` and the supervisor's ``DSH_WORKER_SANDBOXED=1`` marker (set for
read-only/workspace-write jobs, never for danger-full-access).  Everywhere else
it would silently widen a 0o700 directory for an ordinary Python process, so the
default is no patch at all.  It only strips the restrictive mode for directory
creation; the directory still inherits the workspace sandbox DACL.

ponytail: the ceiling is Python processes that honour ``site`` (``python -S``
bypasses it) and non-Python tools, which create dirs with their own ACLs; a
kernel-level fix would need dsh to grant the capability to an inherited DACL.
"""
from __future__ import annotations

import os
import sys

if sys.platform == "win32" and os.environ.get("DSH_WORKER_SANDBOXED") == "1":
    _ORIGINAL_MKDIR = os.mkdir

    def _mkdir(path, mode=0o777, *, dir_fd=None):
        # Only the restrictive mode is a problem; every other mode already inherits.
        if mode == 0o700:
            mode = 0o777
        if dir_fd is None:
            return _ORIGINAL_MKDIR(path, mode)
        return _ORIGINAL_MKDIR(path, mode, dir_fd=dir_fd)

    os.mkdir = _mkdir
