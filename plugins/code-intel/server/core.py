"""code-intel: LSP-backed code intelligence over the reality-engine checkout.

Every tool answers from one long-lived ``basedpyright-langserver --stdio`` child
(definition / references / hover / workspace symbols / diagnostics), except the
module outline and module map, which read the file with ``ast`` (instant, and
they still work while the language server is warming).

All paths returned to the caller are relative to the repo root, every tool is
bounded (timeouts + result caps) and errors come back as ``{ok: false, error}``
rather than raising through MCP.
"""
from __future__ import annotations

import datetime
import os
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parent
PLUGIN_DIR = SERVER_DIR.parent
for _entry_dir in (SERVER_DIR, PLUGIN_DIR):   # ``lsp.py`` is here, ``astindex.py`` beside it
    if str(_entry_dir) not in sys.path:
        sys.path.insert(0, str(_entry_dir))

from lsp import LspClient, LspError, path_to_uri, uri_to_path  # noqa: E402
import astindex  # noqa: E402  (stdlib only, never starts a server)

REPO_ROOT = Path(os.environ.get("CODE_INTEL_REPO_ROOT") or SERVER_DIR.parents[2]).resolve()
CACHE_DIR = SERVER_DIR / ".cache"
LIFECYCLE_LOG = CACHE_DIR / "lifecycle.log"
LANG_SERVER_LOG = CACHE_DIR / "langserver.log"

REQUEST_TIMEOUT = float(os.environ.get("CODE_INTEL_TIMEOUT", "30"))
DIAGNOSTICS_TIMEOUT = float(os.environ.get("CODE_INTEL_DIAGNOSTICS_TIMEOUT", "25"))
COLD_INDEX_WAIT = float(os.environ.get("CODE_INTEL_COLD_INDEX_WAIT", "5"))
COLD_INDEX_WINDOW = 120.0
MAX_REFERENCES = 500
MAX_SYMBOLS = 300
MAX_DIAGNOSTIC_FILES = 20
MAX_DIAGNOSTICS_PER_FILE = 100
MAX_MODULES = 300
MAX_HOVER_CHARS = 4000
MAX_SYNC_FILES = int(os.environ.get("CODE_INTEL_MAX_SYNC_FILES", "40"))
SYNC_TIMEOUT = 10.0
SNIPPET_LINES = 5
HOT_FILES = ("reality_engine/db/readonly.py", "reality_engine/config.py")

SYMBOL_KINDS = {1: "file", 2: "module", 3: "namespace", 4: "package", 5: "class", 6: "method",
                7: "property", 8: "field", 9: "constructor", 10: "enum", 11: "interface",
                12: "function", 13: "variable", 14: "constant", 15: "string", 16: "number",
                17: "boolean", 18: "array", 19: "object", 20: "key", 21: "null",
                22: "enum_member", 23: "struct", 24: "event", 25: "operator", 26: "type_param"}
SEVERITIES = {1: "error", 2: "warning", 3: "info", 4: "hint"}
# directories that are never part of the pyright program (see pyrightconfig.json)
SKIP_PARTS = {"__pycache__", ".tmp", ".venv", "venv", "node_modules", "data", "runtime", "build", "dist"}


class CodeIntelError(Exception):
    def __init__(self, code: str, message: str, **extra) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.extra = extra

    def as_dict(self) -> dict:
        out = {"code": self.code, "message": self.message}
        out.update(self.extra)
        return out


def lifecycle(event: str) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with LIFECYCLE_LOG.open("a", encoding="utf-8") as fh:
            fh.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} pid={os.getpid()} {event}\n")
    except OSError:
        pass


# --------------------------------------------------------------------------- language server
_PYTHON_CANDIDATES: list[Path] = []
for _candidate in (Path(sys.executable),
                   REPO_ROOT / ".tmp" / "lspvenv" / "Scripts" / "python.exe",
                   REPO_ROOT / ".tmp" / "lspvenv" / "bin" / "python",
                   REPO_ROOT / ".venv" / "Scripts" / "python.exe",
                   REPO_ROOT / ".venv" / "bin" / "python"):
    if _candidate.exists() and _candidate not in _PYTHON_CANDIDATES:
        _PYTHON_CANDIDATES.append(_candidate)

_IMPORT_CACHE: dict[tuple[str, str], bool] = {}
_SHIM = "from {pkg}.langserver import main; main()"


def _can_import(python: Path, package: str) -> bool:
    key = (str(python), package)
    if key not in _IMPORT_CACHE:
        try:
            done = subprocess.run([str(python), "-c", f"import {package}.langserver"],
                                  capture_output=True, timeout=30)
            _IMPORT_CACHE[key] = done.returncode == 0
        except (OSError, subprocess.SubprocessError):
            _IMPORT_CACHE[key] = False
    return _IMPORT_CACHE[key]


def langserver_command() -> list[str] | None:
    """Where to find a language server: explicit env, PATH, then an importable package."""
    explicit = os.environ.get("CODE_INTEL_LANG_SERVER")
    if explicit:
        return [explicit, "--stdio"]
    for name in ("basedpyright-langserver", "pyright-langserver"):
        found = shutil.which(name)
        if found:
            return [found, "--stdio"]
    for python in _PYTHON_CANDIDATES:
        for package in ("basedpyright", "pyright"):
            if _can_import(python, package):
                return [str(python), "-c", _SHIM.format(pkg=package), "--stdio"]
    return None


INSTALL_HINT = ("python -m pip install basedpyright --timeout 120 --retries 5  "
                "(then re-run; or set CODE_INTEL_LANG_SERVER to a basedpyright-langserver binary)")


class _Server:
    client: LspClient | None = None
    restarts = 0
    started_at: float | None = None


_server = _Server()
_start_lock = threading.Lock()

_diag_cond = threading.Condition()
_diag: dict[str, tuple[int, list]] = {}
_opened_lock = threading.Lock()
# normalised path -> {"version": last didChange version, "sig": (mtime, size, ctime), "uri": str}
# ``sig`` is what the language server was last given, so a disk edit that never
# went through the editor is detectable without trusting the server's index.
_opened: dict[str, dict] = {}
_sync_lock = threading.Lock()
_disk_snapshot: dict[str, tuple[int, int, int]] | None = None   # scan at server start / last sync
_last_head: str | None = None                                    # git HEAD at that scan


def _diag_key(path: Path | str) -> str:
    # pyright normalises file URIs (c%3A vs C:), so match on the path, not the URI.
    return os.path.normcase(str(Path(path).resolve()))


def _on_diagnostics(uri: str, items: list) -> None:
    key = _diag_key(uri_to_path(uri))
    with _diag_cond:
        seq = _diag.get(key, (0, []))[0] + 1
        _diag[key] = (seq, items)
        _diag_cond.notify_all()


def _diag_seq(path: Path | str) -> int:
    with _diag_cond:
        return _diag.get(_diag_key(path), (0, []))[0]


def _wait_diagnostics(path: Path | str, since: int, timeout: float) -> list:
    key = _diag_key(path)
    deadline = time.monotonic() + timeout
    with _diag_cond:
        while True:
            seq, items = _diag.get(key, (0, []))
            if seq > since:
                return items
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodeIntelError("lsp_timeout", f"no diagnostics for {_rel(path)} within {timeout:.0f}s")
            _diag_cond.wait(remaining)


def _seed_file() -> Path | None:
    """pyright builds its program lazily; one opened file is what triggers the index.

    Without this, ``workspace/symbol`` answers ``[]`` instantly on a cold server.
    """
    for name in HOT_FILES:
        if (REPO_ROOT / name).is_file():
            return REPO_ROOT / name
    for path in sorted(REPO_ROOT.rglob("*.py")):
        if not (SKIP_PARTS & set(path.parts)):
            return path
    return None


def _client(timeout: float = REQUEST_TIMEOUT) -> LspClient:
    with _start_lock:
        client = _server.client
        if client is not None and client.alive:
            return client
        if client is not None:
            _server.restarts += 1
            lifecycle(f"langserver died (restart {_server.restarts})")
            client.stop()
        command = langserver_command()
        if command is None:
            raise CodeIntelError("lsp_missing", "no basedpyright-langserver / pyright-langserver found",
                                 install=INSTALL_HINT)
        fresh = LspClient(REPO_ROOT, command, log_path=LANG_SERVER_LOG)
        fresh.diagnostics_handler = _on_diagnostics
        try:
            fresh.start(timeout=max(timeout, 60.0))
        except LspError as exc:
            fresh.stop()
            extra = {"install": INSTALL_HINT} if exc.code == "lsp_missing" else {}
            raise CodeIntelError(exc.code, exc.message, **extra) from exc
        _server.client = fresh
        _server.started_at = time.monotonic()
        with _opened_lock:
            _opened.clear()          # a new process has no open documents
        with _diag_cond:
            _diag.clear()            # ... and no diagnostics for them either
        _reset_sync()                # disk baseline: the fresh server reads from disk now
        lifecycle(f"langserver up pid={fresh.pid()} {fresh.server_info.get('name', '')} "
                   f"{fresh.server_info.get('version', '')}")
        seed = _seed_file()
        if seed is not None:
            _open(fresh, seed)
            # pyright builds the program asynchronously; the first diagnostics for the
            # opened file mean the index exists and workspace/symbol can answer.
            try:
                _wait_diagnostics(seed, 0, max(timeout, 60.0))
            except CodeIntelError:
                pass
        return fresh


def _call(method: str, params: dict, timeout: float = REQUEST_TIMEOUT):
    """Run one LSP request; a dead child is restarted once and the request retried."""
    for attempt in (1, 2):
        try:
            return _client(timeout).request(method, params, timeout=timeout)
        except LspError as exc:
            if attempt == 1 and exc.code in ("lsp_died", "lsp_closed"):
                lifecycle(f"{method} failed ({exc.code}); restarting language server")
                continue
            raise CodeIntelError(exc.code, exc.message) from exc
    raise CodeIntelError("lsp_died", "language server exited twice in a row")


def warm() -> None:
    """Start the language server and force the first parse before a worker asks."""
    started = time.monotonic()
    try:
        client = _client(timeout=180)
        client.request("workspace/symbol", {"query": "connect_ro"}, timeout=240)
        lifecycle(f"warm done in {time.monotonic() - started:.1f}s")
    except (CodeIntelError, LspError) as exc:
        lifecycle(f"warm failed after {time.monotonic() - started:.1f}s: {exc}")


def close() -> None:
    with _start_lock:
        if _server.client is not None:
            _server.client.stop()
            _server.client = None


# --------------------------------------------------------------------------- helpers
def _rel(path: Path | str) -> str:
    try:
        return Path(path).resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return Path(path).as_posix()


def _path(value: str) -> Path:
    candidate = Path(value)
    return candidate if candidate.is_absolute() else (REPO_ROOT / candidate)


def _lines(path: Path) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []


def _line_text(path: Path, line0: int) -> str:
    lines = _lines(path)
    return lines[line0].strip() if 0 <= line0 < len(lines) else ""


def _snippet(path: Path, line0: int, radius: int = SNIPPET_LINES) -> list[str]:
    lines = _lines(path)
    start = max(0, line0 - 1)
    stop = min(len(lines), line0 + radius)
    return [f"{i + 1}: {lines[i]}" for i in range(start, stop)]


def _sig(path: Path) -> tuple[int, int, int] | None:
    try:
        info = path.stat()
    except OSError:
        return None
    return (info.st_mtime_ns, info.st_size, info.st_ctime_ns)


def _push(client: LspClient, path: Path) -> str:
    """Open the document, or push new text when it is already open.

    A repeated ``didOpen`` is ignored by pyright and would never publish fresh
    diagnostics, so an already-open file gets a full-text ``didChange`` instead.
    The signature is stored with the text: it is the server's copy, not the disk.
    """
    uri = path_to_uri(path)
    key = _diag_key(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        text = ""
    signature = _sig(path)
    with _opened_lock:
        entry = _opened.get(key)
        version = (entry["version"] if entry else 0) + 1
        _opened[key] = {"version": version, "sig": signature, "uri": uri}
    try:
        if entry is None:
            client.notify("textDocument/didOpen", {"textDocument": {
                "uri": uri, "languageId": "python", "version": 1, "text": text}})
        else:
            client.notify("textDocument/didChange", {
                "textDocument": {"uri": uri, "version": version},
                "contentChanges": [{"text": text}]})
    except LspError as exc:
        raise CodeIntelError(exc.code, exc.message) from exc
    return uri


def _open(client: LspClient, path: Path) -> str:
    """Open/re-send a file unconditionally: diagnostics needs the push to fire."""
    return _push(client, path)


def _fresh(client: LspClient, path: Path) -> str:
    """Push the file only when the server's copy is older than the disk."""
    key = _diag_key(path)
    signature = _sig(path)
    with _opened_lock:
        entry = _opened.get(key)
    if entry is not None and signature is not None and entry["sig"] == signature:
        return entry["uri"]
    return _push(client, path)


def _head() -> str | None:
    """This checkout's git HEAD (None outside a git repo or for a nested fixture)."""
    try:
        done = subprocess.run(["git", "-C", str(REPO_ROOT), "rev-parse", "--show-toplevel", "HEAD"],
                              capture_output=True, text=True, timeout=SYNC_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode != 0:
        return None
    lines = done.stdout.split()
    if len(lines) < 2:
        return None
    try:
        toplevel = Path(lines[0]).resolve()
    except OSError:
        return None
    return lines[1] if toplevel == REPO_ROOT else None


def _git_changes(old: str, new: str) -> list[str]:
    """Python files a commit range touched; [] when git cannot answer."""
    try:
        done = subprocess.run(["git", "-C", str(REPO_ROOT), "diff", "--name-only", old, new, "--"],
                              capture_output=True, text=True, timeout=SYNC_TIMEOUT)
    except (OSError, subprocess.SubprocessError):
        return []
    if done.returncode != 0:
        return []
    return [line.strip() for line in done.stdout.splitlines() if line.strip().endswith(".py")]


def _reset_sync() -> None:
    """Baseline for the next sync: the disk as a freshly started server will read it."""
    global _disk_snapshot, _last_head
    try:
        snapshot = astindex.scan(REPO_ROOT)
    except (OSError, ValueError):
        snapshot = {}
    head = _head()
    with _sync_lock:
        _disk_snapshot = snapshot
        _last_head = head


def _sync_changes() -> int:
    """Make the language server's view of changed files match the disk.

    The server keeps the text it was first given: a git merge, a worker edit or
    another session's write never reaches it through an editor event.  Catches
    both the mtime/size/ctime moved since the last sweep and a moved git HEAD
    (a merge or checkout leaves files with fresh mtimes but a clean status, and
    status-only detection would miss it).  Returns how many files were pushed;
    capped so one huge merge cannot stall a tool call.
    """
    global _disk_snapshot, _last_head
    try:
        snapshot = astindex.scan(REPO_ROOT)
    except (OSError, ValueError):
        return 0
    with _sync_lock:
        previous, previous_head = _disk_snapshot, _last_head
    if previous is None:
        _reset_sync()
        return 0
    changed = {rel for rel, signature in snapshot.items() if previous.get(rel) != signature}
    head = _head()
    if head and previous_head and head != previous_head:
        changed.update(rel for rel in _git_changes(previous_head, head)
                       if not astindex.SKIP_PARTS & set(Path(rel).parts))
    with _sync_lock:
        _disk_snapshot = snapshot
        _last_head = head
    client = _server.client
    if client is None or not client.alive:
        return 0                     # nothing to feed yet; the next start reads from disk
    pushed = 0
    failed: list[str] = []
    for rel in sorted(changed)[:MAX_SYNC_FILES]:
        path = REPO_ROOT / rel
        if not path.is_file():
            continue
        try:
            _fresh(client, path)
            pushed += 1
        except CodeIntelError:
            failed.append(rel)
    if failed:
        # a failed push must not be recorded as synced, or the stale copy is forever
        with _sync_lock:
            for rel in failed:
                if rel in previous:
                    snapshot[rel] = previous[rel]
                else:
                    snapshot.pop(rel, None)
    return pushed


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT)
        return True
    except (ValueError, OSError):
        return False


def _location(path: Path, line0: int, char0: int) -> dict:
    return {"file": _rel(path), "line": line0 + 1, "col": char0 + 1, "text": _line_text(path, line0)}


def _loc_from_lsp(location: dict) -> dict | None:
    if "targetUri" in location:  # LocationLink (definition may answer with links)
        location = {"uri": location["targetUri"],
                    "range": location.get("targetSelectionRange") or location.get("targetRange") or {}}
    try:
        path = uri_to_path(location["uri"])
    except (KeyError, ValueError):
        return None
    start = location.get("range", {}).get("start", {})
    return _location(path, int(start.get("line", 0)), int(start.get("character", 0)))


def _kind_name(kind: object) -> str:
    return SYMBOL_KINDS.get(kind if isinstance(kind, int) else 0, "unknown")


def _search_symbols(query: str, timeout: float) -> list[dict]:
    def search() -> list[dict]:
        hits = _call("workspace/symbol", {"query": query}, timeout=timeout) or []
        return [hit for hit in hits if isinstance(hit, dict) and isinstance(hit.get("location"), dict)]

    hits = search()
    if hits or _server.started_at is None or \
            time.monotonic() - _server.started_at > COLD_INDEX_WINDOW:
        return hits
    # A language server that was just started answers workspace/symbol from a
    # partially built index: the first cold call on the fixture returned [] and
    # needed ~1.5 s.  Poll briefly instead of reporting not_found.
    # ponytail: bounded poll instead of a pyright "index ready" signal; raise
    # CODE_INTEL_COLD_INDEX_WAIT on a slower box.
    deadline = time.monotonic() + COLD_INDEX_WAIT
    while not hits and time.monotonic() < deadline:
        time.sleep(min(0.5, max(0.0, deadline - time.monotonic())))
        hits = search()
    return hits


def _pick_symbol(hits: list[dict], symbol: str) -> dict | None:
    """Prefer an exact name, then a case-insensitive one, and always a repo file over stdlib."""
    exact = [h for h in hits if h.get("name") == symbol]
    loose = [h for h in hits if str(h.get("name", "")).lower() == symbol.lower()]
    pool = exact or loose or hits
    if not pool:
        return None
    return sorted(pool, key=lambda h: (_inside_repo(uri_to_path(h["location"]["uri"])),
                                       "site-packages" not in h["location"]["uri"]), reverse=True)[0]


def _name_position(hit: dict, symbol: str) -> tuple[Path, int, int]:
    """Point at the symbol *name* on its definition line, not at ``def``/``class``."""
    location = hit["location"]
    path = uri_to_path(location["uri"])
    start = location.get("range", {}).get("start", {})
    line0 = int(start.get("line", 0))
    lines = _lines(path)
    text = lines[line0] if 0 <= line0 < len(lines) else ""   # raw: keep the indent
    index = text.find(symbol)
    return path, line0, index if index >= 0 else int(start.get("character", 0))


def _ast_index() -> dict | None:
    """The mtime-invalidated ast index, or None when the checkout cannot be indexed."""
    try:
        return astindex.load(REPO_ROOT)
    except (OSError, ValueError):
        return None


def _hit_is_stale(hit: dict) -> bool:
    """True when the server points at a line that no longer holds the name.

    pyright's workspace index can hold the text it was first given; a position
    from it is only trusted when the disk agrees.
    """
    name = str(hit.get("name") or "")
    location = hit.get("location") or {}
    if not name or "uri" not in location:
        return False
    try:
        path = uri_to_path(location["uri"])
    except ValueError:
        return False
    start = (location.get("range") or {}).get("start") or {}
    return name not in _line_text(path, int(start.get("line", 0)))


def _ast_definition(symbol: str) -> list[dict]:
    index = _ast_index()
    return astindex.definitions(index, symbol) if index else []


def _ast_references(symbol: str, limit: int) -> dict | None:
    index = _ast_index()
    if not index:
        return None
    hits, total = astindex.references(index, symbol, limit=limit)
    if not total:
        return None
    return {"ok": True, "symbol": symbol, "count": len(hits), "limit": limit,
            "truncated": total > len(hits), "references": hits, "source": "ast"}


def _ast_symbols(query: str, limit: int) -> tuple[list[dict], int]:
    index = _ast_index()
    if not index:
        return [], 0
    return astindex.search_names(index, query, limit=limit)


def _changed_python_files(limit: int = 50) -> list[Path]:
    try:
        done = subprocess.run(["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--untracked-files=all"],
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        raise CodeIntelError("git_failed", f"git status failed: {exc}") from exc
    if done.returncode != 0:
        raise CodeIntelError("git_failed", (done.stderr or "git status failed").strip()[:400])
    files: list[Path] = []
    for line in done.stdout.splitlines():
        raw = line[3:].strip()
        if " -> " in raw:
            raw = raw.split(" -> ", 1)[1]
        raw = raw.strip('"')
        if not raw.endswith(".py"):
            continue
        path = REPO_ROOT / raw
        if SKIP_PARTS & set(Path(raw).parts):  # scratch/data dirs are not in the program
            continue
        if path.is_file() and path not in files:
            files.append(path)
        if len(files) >= limit:
            break
    return files


def _in_program(path: Path) -> bool:
    """Is the file in the pyright program (pyrightconfig.json ``include``)?

    Pyright never publishes diagnostics for a file outside the include roots, so
    waiting for them would burn the whole diagnostics budget on a timeout.
    """
    try:
        rel = path.resolve().relative_to(REPO_ROOT).as_posix()
    except (ValueError, OSError):
        return False
    if "/" not in rel:
        return True                  # a root-level module is part of the program
    roots = astindex.pyright_roots(REPO_ROOT)
    if not roots:
        return True
    return any(rel == root or rel.startswith(root + "/") for root in roots)


def _module_outline(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        symbols, module_doc = astindex.module_symbols(text)
    except SyntaxError as exc:
        raise CodeIntelError("syntax_error", f"{_rel(path)}:{exc.lineno}: {exc.msg}") from exc
    return {"file": _rel(path), "language": "python", "lines": len(text.splitlines()),
            "module_doc": module_doc, "count": len(symbols), "symbols": symbols}


# --------------------------------------------------------------------------- tools
def definition(symbol: str | None = None, file: str | None = None, line: int | None = None,
               col: int | None = None) -> dict:
    _sync_changes()
    if file and line:
        path = _path(file)
        if not path.is_file():
            raise CodeIntelError("not_found", f"no such file: {file}")
        client = _client()
        uri = _fresh(client, path)
        result = _call("textDocument/definition", {"textDocument": {"uri": uri}, "position": {
            "line": max(0, int(line) - 1), "character": max(0, int(col or 1) - 1)}})
        locations = [result] if isinstance(result, dict) else list(result or [])
        found = [loc for loc in (_loc_from_lsp(item) for item in locations
                                 if isinstance(item, dict) and "uri" in item) if loc]
        for loc in found:
            loc["snippet"] = _snippet(_path(loc["file"]), loc["line"] - 1)
        return {"ok": True, "query": {"file": _rel(path), "line": line, "col": col or 1},
                "count": len(found), "definitions": found[:MAX_REFERENCES]}

    if not symbol:
        raise CodeIntelError("bad_request", "pass symbol=... or file=...&line=...")
    hits = _search_symbols(symbol, REQUEST_TIMEOUT)
    hit = _pick_symbol(hits, symbol)
    stale = hit is not None and _hit_is_stale(hit)
    if hit is None or stale:
        replacement = _ast_definition(symbol)
        if replacement:
            return {"ok": True, "symbol": symbol, "count": len(replacement),
                    "definitions": replacement, "candidates": max(0, len(hits) - 1),
                    "source": "ast"}
        if hit is None:
            raise CodeIntelError("not_found", f"no symbol matching {symbol!r}")
    path, line0, char0 = _name_position(hit, symbol)
    location = _location(path, line0, char0)
    location["snippet"] = _snippet(path, line0)
    location["name"] = hit.get("name")
    location["kind"] = _kind_name(hit.get("kind"))
    location["container"] = hit.get("containerName") or ""
    out = {"ok": True, "symbol": symbol, "count": 1, "definitions": [location],
           "candidates": max(0, len(hits) - 1), "source": "lsp"}
    if stale:
        out["stale"] = True          # the ast index does not know this name either
    return out


def references(symbol: str | None = None, file: str | None = None, line: int | None = None,
               col: int | None = None, limit: int = 50) -> dict:
    limit = max(1, min(int(limit), MAX_REFERENCES))
    _sync_changes()
    client = _client()
    if file and line:
        path = _path(file)
        if not path.is_file():
            raise CodeIntelError("not_found", f"no such file: {file}")
        uri = _fresh(client, path)
        position = {"line": max(0, int(line) - 1), "character": max(0, int(col or 1) - 1)}
        name = None
    elif symbol:
        hits = _search_symbols(symbol, REQUEST_TIMEOUT)
        hit = _pick_symbol(hits, symbol)
        if hit is None:
            fallback = _ast_references(symbol, limit)
            if fallback is not None:
                return fallback
            raise CodeIntelError("not_found", f"no symbol matching {symbol!r}")
        path, line0, char0 = _name_position(hit, symbol)
        if symbol not in _line_text(path, line0):
            # the server's copy of the defining file is older than the disk, so a
            # position query against it would resolve whatever used to be there
            fallback = _ast_references(symbol, limit)
            if fallback is not None:
                return fallback
        uri = path_to_uri(path)
        position = {"line": line0, "character": char0}
        name = symbol
    else:
        raise CodeIntelError("bad_request", "pass symbol=... or file=...&line=...")
    found = _call("textDocument/references", {
        "textDocument": {"uri": uri}, "position": position,
        "context": {"includeDeclaration": False}}, timeout=REQUEST_TIMEOUT) or []
    locations = [loc for loc in (_loc_from_lsp(item) for item in found if isinstance(item, dict)) if loc]
    locations.sort(key=lambda loc: (loc["file"], loc["line"]))
    return {"ok": True, "symbol": name or f"{_rel(path)}:{position['line'] + 1}",
            "count": len(locations), "limit": limit, "truncated": len(locations) > limit,
            "references": locations[:limit], "source": "lsp"}


def callers(function: str, limit: int = 50) -> dict:
    limit = max(1, min(int(limit), MAX_REFERENCES))
    out = references(symbol=function, limit=MAX_REFERENCES)
    sites = [loc for loc in out["references"]
             if f"{function}(" in loc["text"] and not loc["text"].startswith(("from ", "import ", "#", "@"))]
    return {"ok": True, "function": function, "count": len(sites), "limit": limit,
            "truncated": len(sites) > limit, "callers": sites[:limit]}


def symbols(file: str | None = None, query: str | None = None, limit: int = 100) -> dict:
    limit = max(1, min(int(limit), MAX_SYMBOLS))
    if file:
        path = _path(file)
        if not path.is_file():
            raise CodeIntelError("not_found", f"no such file: {file}")
        if path.suffix != ".py":
            raise CodeIntelError("unsupported", "module outline is Python-only; use symbols(query=...) for others")
        outline = _module_outline(path)
        outline["truncated"] = outline["count"] > limit
        outline["symbols"] = outline["symbols"][:limit]
        outline["ok"] = True
        return outline
    if not query:
        raise CodeIntelError("bad_request", "pass file=... or query=...")
    _sync_changes()
    hits = _search_symbols(query, REQUEST_TIMEOUT)
    if not hits or any(_hit_is_stale(hit) for hit in hits):
        fresh_hits, total = _ast_symbols(query, limit)
        if fresh_hits:
            return {"ok": True, "query": query, "count": len(fresh_hits),
                    "truncated": total > len(fresh_hits), "symbols": fresh_hits, "source": "ast"}
    results = []
    for hit in hits[:limit]:
        location = _loc_from_lsp(hit["location"])
        if location is None:
            continue
        results.append({"name": hit.get("name"), "kind": _kind_name(hit.get("kind")),
                        "container": hit.get("containerName") or "", **location})
    return {"ok": True, "query": query, "count": len(results), "truncated": len(hits) > limit,
            "symbols": results, "source": "lsp"}


def hover(file: str, line: int, col: int = 1) -> dict:
    path = _path(file)
    if not path.is_file():
        raise CodeIntelError("not_found", f"no such file: {file}")
    _sync_changes()
    client = _client()
    uri = _fresh(client, path)
    result = _call("textDocument/hover", {"textDocument": {"uri": uri}, "position": {
        "line": max(0, int(line) - 1), "character": max(0, int(col) - 1)}})
    contents = (result or {}).get("contents")
    if isinstance(contents, dict):
        text = contents.get("value") or ""
    elif isinstance(contents, list):
        text = "\n".join(item.get("value", "") if isinstance(item, dict) else str(item) for item in contents)
    else:
        text = str(contents or "")
    text = text.strip()
    if not text:
        raise CodeIntelError("not_found", f"no hover information at {_rel(path)}:{line}:{col}")
    return {"ok": True, "file": _rel(path), "line": int(line), "col": int(col),
            "hover": text[:MAX_HOVER_CHARS], "truncated": len(text) > MAX_HOVER_CHARS}


def diagnostics(files: list[str] | None = None, changed: bool = False) -> dict:
    started = time.monotonic()
    _sync_changes()                  # a file's imports matter as much as the file
    targets: list[Path] = []
    if changed:
        targets.extend(_changed_python_files())
    for item in files or []:
        path = _path(item)
        if path.is_file() and path not in targets:
            targets.append(path)
    skipped = [_rel(path) for path in targets if not _in_program(path)]
    targets = [path for path in targets if _in_program(path)]
    if not targets:
        return {"ok": True, "files": [], "count": 0, "error_count": 0, "warning_count": 0,
                "skipped": skipped,
                "note": "no changed or listed Python files inside the pyright program"}
    truncated_files = len(targets) > MAX_DIAGNOSTIC_FILES
    targets = targets[:MAX_DIAGNOSTIC_FILES]
    client = _client()
    deadline = started + DIAGNOSTICS_TIMEOUT
    out = []
    for path in targets:
        remaining = deadline - time.monotonic()
        if remaining <= 0.5:
            raise CodeIntelError("lsp_timeout", f"diagnostics budget ({DIAGNOSTICS_TIMEOUT:.0f}s) exhausted "
                                               f"after {len(out)} of {len(targets)} files")
        since = _diag_seq(path)
        _open(client, path)
        items = _wait_diagnostics(path, since, remaining)
        entries = []
        for item in items[:MAX_DIAGNOSTICS_PER_FILE]:
            start = item.get("range", {}).get("start", {})
            entries.append({"line": int(start.get("line", 0)) + 1,
                            "col": int(start.get("character", 0)) + 1,
                            "severity": SEVERITIES.get(item.get("severity"), "error"),
                            "code": item.get("code"),
                            "message": (item.get("message") or "").strip()[:500]})
        out.append({"file": _rel(path), "count": len(entries),
                    "truncated": len(items) > len(entries), "diagnostics": entries})
    return {"ok": True, "files": out,
            "count": sum(entry["count"] for entry in out),
            "error_count": sum(1 for entry in out for d in entry["diagnostics"] if d["severity"] == "error"),
            "warning_count": sum(1 for entry in out for d in entry["diagnostics"] if d["severity"] == "warning"),
            "skipped": skipped,
            "truncated": truncated_files, "elapsed_ms": int((time.monotonic() - started) * 1000)}


def module_map(package: str = "reality_engine", limit: int = MAX_MODULES) -> dict:
    limit = max(1, min(int(limit), MAX_MODULES))
    root = _path(package)
    if not root.is_dir():
        raise CodeIntelError("not_found", f"no such directory: {package}")
    skip = SKIP_PARTS
    index = _ast_index() or {}
    cached = index.get("files") or {}
    modules = []
    for path in sorted(root.rglob("*.py")):
        if skip & set(path.relative_to(root).parts):
            continue
        rel = _rel(path)
        entry = cached.get(rel)
        if entry is not None:                # already parsed and mtime-checked by the index
            symbols = entry.get("symbols") or []
            classes = sum(1 for item in symbols if item.get("kind") == "class")
            modules.append({"file": rel, "purpose": entry.get("doc") or "(no docstring)",
                            "classes": classes, "functions": len(symbols) - classes,
                            "lines": entry.get("lines") or 0})
            if len(modules) >= limit:
                break
            continue
        try:
            outline = _module_outline(path)
        except CodeIntelError as exc:
            modules.append({"file": rel, "purpose": f"<unparsed: {exc.message}>"})
            continue
        classes = sum(1 for item in outline["symbols"] if item["kind"] == "class")
        modules.append({"file": rel, "purpose": outline["module_doc"] or "(no docstring)",
                        "classes": classes, "functions": outline["count"] - classes,
                        "lines": outline["lines"]})
        if len(modules) >= limit:
            break
    return {"ok": True, "package": _rel(root), "count": len(modules), "limit": limit,
            "truncated": len(modules) >= limit, "modules": modules}
