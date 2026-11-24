"""Ensure no Python source files contain stray ASCII control characters."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOTS = ("reality_engine", "plugins")
SKIP_DIRS = {".git", "worktrees", "__pycache__", "venv", ".venv", "venvs", ".venvs"}
FORBIDDEN_BYTES = frozenset(range(0x00, 0x09)) | frozenset({0x0B, 0x0C}) | frozenset(range(0x0E, 0x20))


def _should_skip_dir(name: str) -> bool:
    return name in SKIP_DIRS or name.startswith(("venv", ".venv"))


def test_no_control_chars_in_python_sources() -> None:
    hits: list[str] = []
    for rel_root in SCAN_ROOTS:
        base = ROOT / rel_root
        if not base.exists():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = sorted(d for d in dirnames if not _should_skip_dir(d))
            for fn in sorted(filenames):
                if not fn.endswith(".py"):
                    continue
                fp = Path(dirpath) / fn
                data = fp.read_bytes()
                if not any(b in FORBIDDEN_BYTES for b in data):
                    continue
                rel = fp.relative_to(ROOT).as_posix()
                for line_no, line in enumerate(data.split(b"\n"), 1):
                    bad = sorted(f"0x{b:02x}" for b in line if b in FORBIDDEN_BYTES)
                    if bad:
                        hits.append(f"{rel}:{line_no} ({', '.join(bad)})")
    assert not hits, "Control characters found in Python files:\n" + "\n".join(hits)
