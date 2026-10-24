"""Shared helpers for the toolbelt CLIs.

Data resolution follows the worker convention: gitignored databases live under
``REALITY_DATA_ROOT`` when it is set (the main checkout's ``reality_engine/data``),
otherwise under this worktree's ``reality_engine/data``.  Nothing here writes to a
live database; callers open files with :func:`reality_engine.db.readonly.connect_ro`.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Sequence

from reality_engine.db.readonly import connect_ro

REPO_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = REPO_ROOT / "reality_engine" / "data"
_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")


def data_root() -> Path:
    """Directory holding the live SQLite stores (``REALITY_DATA_ROOT`` wins)."""
    env = os.environ.get("REALITY_DATA_ROOT")
    return Path(env) if env else DATA_DIR


def resolve_db(name_or_path: str) -> Path:
    """Resolve ``equity_intelligence``, ``ar_facts.db`` or an explicit path."""
    raw = str(name_or_path)
    p = Path(raw).expanduser()
    if p.exists():
        return p
    if p.is_absolute() or "/" in raw or "\\" in raw or p.suffix.lower() == ".db":
        if not p.is_absolute():
            for base in (data_root(), REPO_ROOT, Path.cwd()):
                if (base / p).exists():
                    return base / p
        return p if p.is_absolute() else data_root() / p
    return data_root() / f"{raw}.db"


def connect(name_or_path: str, timeout_s: float = 60.0):
    """Open a store read-only with the toolbelt's 60 s statement budget."""
    path = resolve_db(name_or_path)
    if not path.exists():
        raise FileNotFoundError(f"database not found: {path} (set REALITY_DATA_ROOT)")
    return connect_ro(path, timeout_s=timeout_s)


def quote_ident(name: str) -> str:
    """Quote a SQLite identifier after rejecting anything that is not one."""
    if not _IDENT.fullmatch(name or ""):
        raise ValueError(f"invalid SQL identifier: {name!r}")
    return f'"{name}"'


def parse_pages(spec: str | None, page_count: int) -> list[int]:
    """``3,5-7`` / ``all`` -> 1-based page numbers, validated against the PDF."""
    if not spec or spec.strip().lower() == "all":
        return list(range(1, page_count + 1))
    out: list[int] = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            start, end = int(a), int(b)
        else:
            start = end = int(part)
        if start < 1 or end > page_count or start > end:
            raise ValueError(f"page range {part!r} outside 1..{page_count}")
        out.extend(range(start, end + 1))
    return sorted(set(out))


def _cell(value: Any, width: int = 80) -> str:
    if value is None:
        return "-"
    if isinstance(value, (dict, list)):
        text = json.dumps(value, ensure_ascii=False, default=str)
    else:
        text = str(value)
    text = text.replace("\n", " ")
    return text if len(text) <= width else text[: width - 1] + "…"


def format_table(rows: Sequence[dict[str, Any]], columns: Sequence[str] | None = None) -> str:
    """Plain aligned table for ``--format table``; JSON stays the default."""
    if not rows:
        return "(no rows)"
    cols = list(columns or rows[0].keys())
    body = [[_cell(row.get(col)) for col in cols] for row in rows]
    widths = [max(len(col), *(len(line[i]) for line in body)) for i, col in enumerate(cols)]
    lines = ["  ".join(col.ljust(widths[i]) for i, col in enumerate(cols))]
    lines.append("  ".join("-" * w for w in widths))
    lines.extend("  ".join(line[i].ljust(widths[i]) for i in range(len(cols))) for line in body)
    return "\n".join(lines)


def format_kv(obj: dict[str, Any]) -> str:
    """Two-column view of a summary object (nested values stay JSON)."""
    rows = [{"key": k, "value": v} for k, v in obj.items()]
    return format_table(rows, ["key", "value"])


def print_result(obj: dict[str, Any], fmt: str = "json", columns: Sequence[str] | None = None) -> None:
    """JSON by default; ``--format table`` prints the main list plus a summary."""
    if fmt != "table":
        print(json.dumps(obj, indent=2, ensure_ascii=False, default=str))
        return
    rows: list[dict[str, Any]] | None = None
    row_key = ""
    for key in ("rows", "documents", "items", "files", "results", "pages"):
        if isinstance(obj.get(key), list):
            rows, row_key = obj[key], key
            break
    if rows is None:
        print(format_kv(obj))
        return
    print(format_table(rows, columns))
    summary = {k: v for k, v in obj.items() if k != row_key and k not in ("schema",)}
    if summary:
        print("\n" + format_kv(summary))


def add_format(parser) -> None:
    parser.add_argument("--format", choices=("json", "table"), default="json",
                        help="output format (default: json)")


def main_guard(fn) -> None:
    """``python -m ...`` entry point: turn a plain exception into a clean exit 1."""
    try:
        raise SystemExit(fn())
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}, indent=2))
        raise SystemExit(1)
