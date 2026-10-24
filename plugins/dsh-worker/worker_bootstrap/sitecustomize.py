"""Worker-only ``sitecustomize``: keep Python temp dirs usable in the sandbox.

The DSH Windows sandbox spawns commands under a ``WRITE_RESTRICTED`` token whose
restricting SIDs carry the workspace and temp capabilities.  Python 3.14's
``os.mkdir(path, 0o700)`` (and therefore ``tempfile.mkdtemp()``) creates a
directory with an explicit owner-only DACL, which cuts off the inheritable
capability ACE; the restricted token can create the directory but cannot write
inside it.  That is the 2026-10-24 ``tempfile.mkdtemp()`` failure.

This module is imported only in processes whose ``PYTHONPATH`` starts with the
worker bootstrap directory (the supervisor adds it), so it does not affect the
main checkout or the orchestrator.  It strips the 0o700 mode for directory
creation only; the directory still inherits the workspace sandbox DACL.

ponytail: the ceiling is Python processes that honour ``site`` (``python -S``
bypasses it) and non-Python tools, which create dirs with their own ACLs; a
kernel-level fix would need dsh to grant the capability to an inherited DACL.
"""
from __future__ import annotations

import os

_ORIGINAL_MKDIR = os.mkdir


def _mkdir(path, mode=0o777, *, dir_fd=None):
    # Only the restrictive mode is a problem; every other mode already inherits.
    if mode == 0o700:
        mode = 0o777
    if dir_fd is None:
        return _ORIGINAL_MKDIR(path, mode)
    return _ORIGINAL_MKDIR(path, mode, dir_fd=dir_fd)


os.mkdir = _mkdir
