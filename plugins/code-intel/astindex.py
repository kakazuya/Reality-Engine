"""AST + text index for code-intel: the language-server-free fast path.

One JSON cache per checkout under ``<root>/.tmp/`` holds, per Python file in
the pyright include roots, its ``(mtime, size, ctime)`` signature, module
docstring and symbol outline.  A file is re-parsed only when its signature
changes, so a warm answer is one ``stat`` sweep plus a cache read, and it is
never older than the disk: no didOpen / didChange round trip, no index the
server forgot to refresh.  Name references are a direct scan of the indexed
files' text (a substring search is cheaper than caching every identifier).

Used by ``plugins/code-intel/ci.py`` (the worker CLI) and by
``server/core.py`` as the fallback when a language-server position turns out to
be stale.
"""
from __future__ import annotations

import ast
import json
import os
import re
import zlib
from pathlib import Path

INDEX_VERSION = 4
CACHE_NAME = "code-intel-index.json"
SNIPPET_LINES = 5
# A per-file bloom over its word tokens, so a name search reads only the files
# that may contain the name (10% false positives, never a false negative).
BLOOM_BITS = 2048
BLOOM_BYTES = BLOOM_BITS // 8
BLOOM_SEED = 0x9E3779B1
TOKEN = re.compile(r"\w+")
# Directories pyright never parses (pyrightconfig.json ``exclude``) plus the
# checkout's own caches: walking them would index test fixtures and data scripts.
SKIP_PARTS = {"__pycache__", ".tmp", ".venv", "venv", "node_modules", "data",
              "runtime", "build", "dist", ".git", ".cache"}
DEFAULT_ROOTS = ("reality_engine", "plugins")
# pyrightconfig.json lists only ``plugins/*/server``; this plugin's own modules
# (ci.py, astindex.py) belong to the program too, so keep them searchable.
EXTRA_ROOTS = ("plugins/code-intel",)


# --------------------------------------------------------------------------- scan
def pyright_roots(root: Path) -> list[str]:
    """Exactly what ``pyrightconfig.json`` includes: the files pyright will analyse."""
    root = Path(root)
    roots: list[str] = []
    config = root / "pyrightconfig.json"
    if config.is_file():
        try:
            data = json.loads(config.read_text(encoding="utf-8"))
            include = data.get("include") if isinstance(data, dict) else None
            for item in include or []:
                if not isinstance(item, str):
                    continue
                name = item.replace("\\", "/").rstrip("/")
                if name and (root / name).is_dir():
                    roots.append(name)
        except (OSError, ValueError):
            roots = []
    if not roots:
        roots = [name for name in DEFAULT_ROOTS if (root / name).is_dir()]
    return roots


def include_roots(root: Path) -> list[str]:
    """The index's scope: pyright's program plus this plugin's own modules."""
    roots = pyright_roots(root)
    for name in EXTRA_ROOTS:
        if (root / name).is_dir() and not any(name == other or name.startswith(other + "/")
                                              for other in roots):
            roots.append(name)
    return roots


def _walk(root: Path, rel_root: str):
    """Yield ``(path, signature)`` for the Python files below ``rel_root``.

    ``DirEntry.stat()`` comes with the directory listing on Windows, so the
    freshness sweep does not pay a second stat syscall per file.
    """
    stack = [root / rel_root]
    while stack:
        current = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_dir(follow_symlinks=False):
                    if entry.name not in SKIP_PARTS and not entry.name.startswith("."):
                        stack.append(Path(entry.path))
                    continue
                if not entry.name.endswith(".py"):
                    continue
                info = entry.stat()
            except OSError:
                continue
            yield Path(entry.path), (info.st_mtime_ns, info.st_size, info.st_ctime_ns)


def _signature(path: Path) -> tuple[int, int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_ctime_ns)


def scan(root: Path) -> dict[str, tuple[int, int, int]]:
    """``relpath -> signature`` for every Python file in the include roots (~25 ms)."""
    root = Path(root).resolve()
    out: dict[str, tuple[int, int, int]] = {}
    for rel_root in include_roots(root):
        for path, signature in _walk(root, rel_root):
            try:
                rel = path.relative_to(root).as_posix()
            except ValueError:
                continue
            if rel in out or SKIP_PARTS & set(Path(rel).parts):
                continue
            out[rel] = signature
    try:
        for path in root.glob("*.py"):
            signature = _signature(path)
            if signature is not None:
                out[path.name] = signature
    except OSError:
        pass
    return out


# --------------------------------------------------------------------------- index
def module_symbols(text: str) -> tuple[list[dict], str]:
    """Outline one module: (symbols, module docstring).  Raises ``SyntaxError``.

    The walk keeps defs nested in ``if``/``try``/``with`` blocks and names a
    method's class as its container, so the outline matches what a reader sees.
    """
    tree = ast.parse(text)

    def first_doc(node) -> str:
        doc = ast.get_docstring(node, clean=True) or ""
        return doc.splitlines()[0].strip() if doc else ""

    symbols: list[dict] = []

    def walk(nodes, prefix: str = "") -> None:
        container = prefix.rstrip(".")
        for node in nodes:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append({"name": node.name, "container": container,
                                "kind": "method" if prefix else "function", "line": node.lineno,
                                "end_line": getattr(node, "end_lineno", node.lineno),
                                "doc": first_doc(node)})
            elif isinstance(node, ast.ClassDef):
                symbols.append({"name": node.name, "container": container, "kind": "class",
                                "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno),
                                "doc": first_doc(node)})
                walk(node.body, prefix + node.name + ".")
            else:
                for field in ("body", "orelse", "finalbody", "handlers"):
                    block = getattr(node, field, None)
                    if isinstance(block, list) and block and isinstance(block[0], ast.AST):
                        walk(block, prefix)

    walk(tree.body)
    return symbols, first_doc(tree)


def _bloom(text: str) -> str:
    """Hex bloom over the file's word tokens: cheap, compact 'name is not here'."""
    bits = bytearray(BLOOM_BYTES)
    for token in set(TOKEN.findall(text)):
        encoded = token.encode("utf-8")
        for value in (zlib.crc32(encoded), zlib.crc32(encoded, BLOOM_SEED)):
            position = value % BLOOM_BITS
            bits[position >> 3] |= 1 << (position & 7)
    return bits.hex()


def _maybe_contains(bloom: str | None, name: str) -> bool:
    if not bloom:
        return True                    # no filter recorded: search the file
    try:
        data = bytes.fromhex(bloom)
    except ValueError:
        return True
    encoded = name.encode("utf-8")
    for value in (zlib.crc32(encoded), zlib.crc32(encoded, BLOOM_SEED)):
        position = value % BLOOM_BITS
        if not data[position >> 3] & (1 << (position & 7)):
            return False
    return True


def _index_text(text: str) -> dict:
    try:
        symbols, module_doc = module_symbols(text)
    except SyntaxError:
        symbols, module_doc = [], ""       # still searchable by text
    return {"doc": module_doc, "lines": len(text.splitlines()),
            "symbols": symbols, "bloom": _bloom(text)}


def _cache_path(root: Path) -> Path:
    return root / ".tmp" / CACHE_NAME


def _read_cache(root: Path) -> dict:
    try:
        return json.loads(_cache_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_cache(root: Path, index: dict) -> None:
    # ponytail: no lock — several workers may rebuild at once and the last writer
    # wins; every entry is derived from the disk, so a lost write only costs a reparse.
    path = _cache_path(root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".json.tmp")
        temp.write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
        os.replace(temp, path)
    except OSError:
        pass                                # read-only checkout: answer anyway


def load(root: Path, force: bool = False) -> dict:
    """The index for ``root``, re-parsing only files whose signature changed.

    Extra keys: ``reparsed`` (files parsed this call) and ``indexed`` (files in
    the index) — the CLI reports both so a slow call is explained.
    """
    root = Path(root).resolve()
    signatures = scan(root)
    cached = {} if force else _read_cache(root)
    if cached.get("version") != INDEX_VERSION or cached.get("root") != str(root):
        cached = {}
    previous = cached.get("files") or {}
    files: dict[str, dict] = {}
    reparsed = 0
    for rel, signature in signatures.items():
        entry = previous.get(rel)
        if entry and tuple(entry.get("sig") or ()) == signature:
            files[rel] = entry
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        entry = _index_text(text)
        entry["sig"] = list(signature)
        files[rel] = entry
        reparsed += 1
    index = {"version": INDEX_VERSION, "root": str(root), "files": files}
    if reparsed or len(files) != len(previous):
        _write_cache(root, index)
    index["reparsed"] = reparsed
    index["indexed"] = len(files)
    return index


# --------------------------------------------------------------------------- queries
def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _rank(rel: str) -> tuple[bool, str]:
    """Prefer the module over a test/task copy of the same name."""
    return ("tests/" in rel or rel.startswith("tasks/"), rel)


def _location(root: Path, rel: str, symbol: dict, lines: list[str] | None = None) -> dict:
    text_lines = _lines(root / rel) if lines is None else lines
    line0 = max(0, int(symbol.get("line") or 1) - 1)
    text = text_lines[line0] if line0 < len(text_lines) else ""
    name = symbol.get("name") or ""
    col = text.find(name) + 1
    start = max(0, line0 - 1)
    stop = min(len(text_lines), line0 + SNIPPET_LINES)
    return {"file": rel, "line": line0 + 1, "col": col or 1, "text": text.strip(),
            "name": name, "kind": symbol.get("kind") or "",
            "container": symbol.get("container") or "",
            "snippet": [f"{i + 1}: {text_lines[i]}" for i in range(start, stop)]}


def definitions(index: dict, name: str, limit: int = 10) -> list[dict]:
    """Where ``name`` is defined: exact matches first, then case-insensitive."""
    root = Path(index["root"])
    exact: list[tuple[str, dict]] = []
    loose: list[tuple[str, dict]] = []
    for rel, entry in index["files"].items():
        for symbol in entry.get("symbols") or []:
            symbol_name = symbol.get("name") or ""
            if symbol_name == name:
                exact.append((rel, symbol))
            elif symbol_name.lower() == name.lower():
                loose.append((rel, symbol))
    picked = exact or loose
    picked.sort(key=lambda item: (_rank(item[0]), item[1].get("line") or 0))
    out: list[dict] = []
    seen: set[tuple[str, int]] = set()
    cache: dict[str, list[str]] = {}
    for rel, symbol in picked:
        key = (rel, int(symbol.get("line") or 0))
        if key in seen:
            continue
        seen.add(key)
        lines = cache.get(rel)
        if lines is None:
            lines = cache[rel] = _lines(root / rel)
        out.append(_location(root, rel, symbol, lines))
        if len(out) >= limit:
            break
    return out


def references(index: dict, name: str, limit: int = 50) -> tuple[list[dict], int]:
    """Every line whose text contains ``name`` (whole identifier, declaration included).

    Returns the hits up to ``limit`` plus the total, so the caller can say
    ``truncated``.  One ``str.find`` per file: 9 MB of sources scans in ~60 ms
    and needs no identifier map in the cache.
    """
    root = Path(index["root"])
    hits: list[dict] = []
    total = 0
    for rel in sorted(index["files"]):
        if not _maybe_contains(index["files"][rel].get("bloom"), name):
            continue
        try:
            text = (root / rel).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        position = text.find(name)
        if position < 0:
            continue
        lines = text.splitlines()
        cursor = 0
        line = 1
        while position >= 0:
            before = text[position - 1:position]
            after = text[position + len(name):position + len(name) + 1]
            if not (_is_ident(before) or _is_ident(after)):
                line += text.count("\n", cursor, position)
                cursor = position
                total += 1
                if len(hits) < limit:
                    raw = lines[line - 1] if 0 < line <= len(lines) else ""
                    hits.append({"file": rel, "line": line, "col": raw.find(name) + 1,
                                 "text": raw.strip()})
            position = text.find(name, position + 1)
    return hits, total


def _is_ident(char: str) -> bool:
    return bool(char) and (char.isalnum() or char == "_")


def search_names(index: dict, query: str, limit: int = 100) -> tuple[list[dict], int]:
    """Symbols whose name contains ``query`` (case-insensitive); exact names first."""
    root = Path(index["root"])
    needle = query.lower()
    scored: list[tuple[int, int, str, dict]] = []
    for rel, entry in index["files"].items():
        for symbol in entry.get("symbols") or []:
            symbol_name = symbol.get("name") or ""
            if needle not in symbol_name.lower():
                continue
            scored.append((0 if symbol_name.lower() == needle else 1, len(symbol_name), rel, symbol))
    scored.sort(key=lambda item: (item[0], item[1], item[2], item[3].get("line") or 0))
    out: list[dict] = []
    cache: dict[str, list[str]] = {}
    for _, _, rel, symbol in scored[:limit]:
        lines = cache.get(rel)
        if lines is None:
            lines = cache[rel] = _lines(root / rel)
        out.append(_location(root, rel, symbol, lines))
    return out, len(scored)
