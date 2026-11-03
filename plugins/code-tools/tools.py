"""Run-and-exit code tools for dsh workers: a file outline and a one-shot type check.

Neither call keeps a process alive: ``outline`` walks one file with ``ast``
(milliseconds) and ``typecheck`` runs basedpyright once and lets it exit.  This
replaces the code-intel language server (retired 4 Nov 2026: a resident
``basedpyright-langserver`` cost ~800 MB per worker and 1.5% of tool calls).
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

TIMEOUT_SECONDS = 120
PROJECT_FILE = "pyrightconfig.json"


def outline(path: str | Path) -> list[dict[str, Any]]:
    """Symbols in one Python file, in source order.

    Each entry is ``{name, kind, line, end_line, parent, doc}``: ``kind`` is
    "class", "function" or "method", ``parent`` the enclosing class name ("" at
    module level) and ``doc`` the first line of the docstring ("" when none).
    The walk keeps defs nested in ``if``/``try``/``with`` blocks, which is what
    a reader sees.  Raises ``SyntaxError`` on unparsable source.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)

    def first_doc(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> str:
        doc = ast.get_docstring(node, clean=True) or ""
        return doc.splitlines()[0].strip() if doc else ""

    symbols: list[dict[str, Any]] = []

    def walk(nodes, parent: str = "") -> None:
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({
                    "name": node.name,
                    "kind": "method" if parent else "function",
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "parent": parent,
                    "doc": first_doc(node),
                })
            elif isinstance(node, ast.ClassDef):
                symbols.append({
                    "name": node.name,
                    "kind": "class",
                    "line": node.lineno,
                    "end_line": getattr(node, "end_lineno", node.lineno),
                    "parent": parent,
                    "doc": first_doc(node),
                })
                walk(node.body, node.name)
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):
                    block = getattr(node, field, None)
                    if isinstance(block, list) and block and isinstance(block[0], ast.AST):
                        walk(block, parent)

    walk(tree.body)
    return symbols


def _basedpyright() -> str:
    """The basedpyright CLI: PATH first, else beside the running interpreter."""
    found = shutil.which("basedpyright")
    if found:
        return found
    scripts = Path(sys.executable).parent / ("Scripts" if os.name == "nt" else "bin")
    for name in ("basedpyright.exe", "basedpyright"):
        if (scripts / name).exists():
            return str(scripts / name)
    raise FileNotFoundError("basedpyright not found on PATH")


def _kill_tree(proc: subprocess.Popen) -> None:
    """Kill the wrapper and, on Windows, the node child it spawned."""
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True, check=False)
        else:
            proc.kill()
        proc.wait(timeout=10)
    except Exception:
        pass


def _relative(file: str, root: Path) -> str:
    try:
        return Path(file).resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return Path(file).as_posix()


def typecheck(paths, root: str | Path | None = None,
              timeout: int = TIMEOUT_SECONDS) -> dict[str, Any]:
    """Run basedpyright once over ``paths`` and return its errors, then exit.

    ``root`` is the checkout whose ``pyrightconfig.json`` supplies the project
    settings (default: ``CODE_TOOLS_ROOT``, else the current directory).
    Returns ``{errors: [{file, line, message}], error_count, seconds}``;
    ``error_count`` is basedpyright's own summary count.  Raises
    ``FileNotFoundError`` without the CLI and ``TimeoutError`` past ``timeout``.
    """
    root = Path(root or os.environ.get("CODE_TOOLS_ROOT") or Path.cwd()).resolve()
    files = []
    for name in paths:
        path = Path(name)
        files.append(str((root / path).resolve() if not path.is_absolute() else path.resolve()))
    cmd = [_basedpyright(), *files, "--outputjson"]
    project = root / PROJECT_FILE
    if project.exists():
        cmd += ["--project", str(project)]
    started = time.monotonic()
    proc = subprocess.Popen(cmd, cwd=str(root), stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, text=True, encoding="utf-8",
                            errors="replace")
    try:
        out, err = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        raise TimeoutError(f"basedpyright did not finish in {timeout}s") from None
    seconds = round(time.monotonic() - started, 2)
    payload = out[out.find("{"):] if "{" in out else ""
    try:
        data = json.loads(payload)
    except ValueError:
        raise RuntimeError(
            f"basedpyright returned no JSON (exit {proc.returncode}): {err.strip()[:300]}"
        ) from None
    errors = []
    for diag in data.get("generalDiagnostics") or []:
        if diag.get("severity") != "error":
            continue
        start = (diag.get("range") or {}).get("start") or {}
        errors.append({
            "file": _relative(str(diag.get("file") or ""), root),
            "line": int(start.get("line") or 0) + 1,
            "message": str(diag.get("message") or "").strip()[:500],
        })
    summary = data.get("summary") or {}
    return {
        "errors": errors,
        "error_count": int(summary.get("errorCount", len(errors))),
        "seconds": seconds,
    }
