"""T-218: every build part stamps the store with the code that built it, what it wrote and what it read.

A store is repaired one part at a time (Shivam, 16 Nov 2026: modular, never a whole-store rebuild).  To know which
part of which store is behind, ``build`` writes one ``part_stamp`` row per part it finishes:

    part | code_hash | out_hash | inputs | built_at (UTC) | seconds | git_head

* ``code_hash``: hash over ``PART_FILES[part]``: the part's own module, the lexicon and map files it reads, and
  the helpers that decide its rows.  A shared file is named with the functions the part uses
  (``../gap_loop/prepare.py::store_copies,_read_sqlite``), so a fix to one helper marks only the parts that call
  it.  Shared plumbing (``schema``, ``profile``, ``raw_store``) is left out on purpose: a migration must not mark
  every part of every store stale.
* ``out_hash``: hash of the rows the part wrote (``PART_TABLES[part]``), taken as it finished.
* ``inputs``: the ``out_hash`` of every part it reads from (``UPSTREAM``), as they stood when it ran.

``stale(conn)`` gives the parts of one store that need a re-run and why:
* ``never stamped``: the store was built before stamps existed, or the part never ran;
* ``code changed``: a file or function of the part differs from the build;
* ``<part> output changed``: a part it reads from has since written different rows;
* ``after <part>``: a part it reads from is itself stale.
A part that is re-run and writes the same rows leaves its readers fresh: a repair stops where the change stops.

``profile`` and ``docs_collect`` are not build parts (they write the profile JSON and ``pages.db``); the repair
runner (``scripts/store_repair.py``) runs and stamps them with ``write(..., out_hash=...)``.  New raw data is a
different question (the fetch record answers it), not a stamp.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]

# The order one company is built in (``build --part all`` order, with the two steps before it).
ORDER = ("profile", "docs_collect", "registry", "ocr", "pages", "stores", "comparatives", "preferred", "ratios",
         "transcripts", "kpi", "segments", "guidance", "notes", "events", "checks", "atoms")
# What the Telegram recipe runs for every company; ``ocr`` and ``atoms`` are stamped only where they were run.
RECIPE = tuple(p for p in ORDER if p not in ("ocr", "atoms"))

PART_FILES: dict[str, tuple[str, ...]] = {
    "profile": ("make_profile.py", "sector_map.yaml", "lender.py"),
    "docs_collect": ("docs_collect.py", "doc_identity.py", "call_dates.py",
                     "../gap_loop/prepare.py::DOC_TYPES,MIN_PAGE_CHARS,_clean_page,_date_of,_title"),
    "registry": ("registry.py", "doc_identity.py", "call_dates.py", "../gap_loop/prepare.py::_read_duckdb,_snapshot"),
    "ocr": ("ocr.py",),
    "pages": ("registry.py",),
    "stores": ("stores.py", "statements.py",
               "../gap_loop/prepare.py::store_copies,duck_copies,_read_duckdb,_read_sqlite,_snapshot"),
    "comparatives": ("comparatives.py", "lexicon/results_lines.yaml", "../v2/page_words.py"),
    "preferred": ("preferred.py",),
    "ratios": ("ratios.py",),
    "transcripts": ("transcripts.py", "lexicon/topics.yaml", "lexicon/business_abbrev.txt", "en_vocab.txt"),
    "kpi": ("kpi.py", "lexicon/*.yaml"),
    "segments": ("xbrl_segments.py", "../gap_loop/prepare.py::_read_sqlite"),
    "guidance": ("guidance.py", "lexicon/dimensions.yaml"),
    "notes": ("notes.py", "notes_lexicon.yaml"),
    "events": ("events.py", "order_wins.py"),
    "checks": ("row_checks.py", "row_checks_vocab.yaml", "number_check.py"),
    "atoms": ("atoms.py",),
}

# part -> the tables it writes; ``table-prefix*`` drops the columns with that prefix (written by a later part).
PART_TABLES: dict[str, tuple[str, ...]] = {
    "profile": (), "docs_collect": (), "ocr": (),          # files outside the store: the runner gives the hash
    "registry": ("company", "doc", "doc_alias"),
    "pages": ("doc_page",),
    "stores": ("fin_quarter_xbrl-preferred*", "fin_annual_line", "share_capital", "shp_category", "shp_holder",
               "shp_pledge", "dividend_event", "price_delivery", "bulk_block_deal", "insider_trade", "index_price"),
    "comparatives": ("fin_quarter_printed-preferred*",),
    "preferred": ("fin_quarter_xbrl", "fin_quarter_printed"),
    "ratios": ("ratio_panel", "valuation_daily", "formula"),
    "transcripts": ("transcript_statement", "transcript_question"),
    "kpi": ("kpi_series",),
    "segments": ("kpi_series",),
    "guidance": ("guidance",),
    "notes": ("rating_event", "concentration", "related_party_txn"),
    "events": ("event", "order_win"),
    "checks": ("row_check", "row_check_fail"),
    "atoms": ("page_atom",),
}

# part -> the parts whose rows (or files) it reads.  ``segments`` is the last writer of kpi_series, so the readers
# of KPI rows name it, not ``kpi``: a KPI re-run that ends in the same rows after ``segments`` leaves them fresh.
UPSTREAM: dict[str, tuple[str, ...]] = {
    "profile": (),
    "docs_collect": ("profile",),
    "registry": ("profile", "docs_collect"),
    "ocr": ("docs_collect",),
    "pages": ("registry", "docs_collect", "ocr"),
    "stores": ("registry",),
    "comparatives": ("pages", "stores"),
    "preferred": ("stores", "comparatives"),
    "ratios": ("stores", "preferred"),
    "transcripts": ("pages",),
    "kpi": ("pages", "profile"),
    "segments": ("kpi",),
    "guidance": ("pages", "transcripts", "segments", "stores"),
    "notes": ("pages",),
    "events": ("pages",),
    "checks": ("guidance", "segments", "preferred", "profile"),
    "atoms": ("pages", "checks"),
}

COLUMNS = ("part", "code_hash", "out_hash", "inputs", "built_at", "seconds", "git_head")
DDL = ("CREATE TABLE IF NOT EXISTS part_stamp (part TEXT PRIMARY KEY, code_hash TEXT NOT NULL, out_hash TEXT, "
       "inputs TEXT, built_at TEXT NOT NULL, seconds REAL, git_head TEXT)")


# --- code hash ---------------------------------------------------------------------------------------------------

def _git_bytes(*args: str) -> bytes | None:
    try:
        done = subprocess.run(["git", *args], cwd=str(REPO), capture_output=True, stdin=subprocess.DEVNULL,
                              timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _disk(rel: str) -> bytes | None:
    path = REPO / rel
    return path.read_bytes() if path.is_file() else None


def _names_source(data: bytes, names: list[str]) -> bytes:
    """The source of the named top-level functions, classes and assignments of a module, in name order."""
    text = data.decode("utf-8", errors="replace").replace("\r\n", "\n")
    found: dict[str, str] = {}
    for node in ast.parse(text).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            targets = [node.name]
        elif isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            targets = [node.target.id]
        else:
            continue
        for name in targets:
            if name in names:
                found[name] = ast.get_source_segment(text, node) or ""
    return "\n".join(f"{name}\n{found.get(name, '<missing>')}" for name in sorted(names)).encode()


def _rel(spec_path: str) -> str:
    return (HERE / spec_path).resolve().relative_to(REPO).as_posix()


def _hash(part: str, reader: Callable[[str], bytes | None], lister: Callable[[str, str], list[str]]) -> str:
    digest = hashlib.sha1()
    for spec in PART_FILES[part]:
        path, _, names = spec.partition("::")
        if "*" in path:
            folder = _rel(str(Path(path).parent))
            rels = sorted(lister(folder, Path(path).name))
        else:
            rels = [_rel(path)]
        for rel in rels:
            data = reader(rel)
            digest.update(f"{rel}::{names}".encode())
            if data is None:
                digest.update(b"<missing>")
            elif names:
                digest.update(_names_source(data, names.split(",")))
            else:
                digest.update(data.replace(b"\r\n", b"\n"))
    return digest.hexdigest()[:16]


def part_files(part: str) -> list[Path]:
    """The files on disk behind ``part``'s code hash; a listed file that is not there is an error."""
    files: list[Path] = []
    for spec in PART_FILES[part]:
        path = spec.partition("::")[0]
        found = sorted((HERE / path).parent.glob(Path(path).name)) if "*" in path else [(HERE / path).resolve()]
        if not found or not all(f.is_file() for f in found):
            raise FileNotFoundError(f"part_stamp: {part} lists {spec}, which is not there")
        files.extend(found)
    return sorted(set(files))


def code_hash(part: str) -> str:
    """Hash of the part's files (and named functions) on disk; line endings are normalised."""
    return _hash(part, _disk, lambda folder, pattern: [p.relative_to(REPO).as_posix()
                                                       for p in (REPO / folder).glob(pattern)])


def code_hash_at(part: str, commit: str) -> str:
    """``code_hash`` of the part as the files stood at ``commit`` (a file not there yet hashes as missing)."""
    def lister(folder: str, pattern: str) -> list[str]:
        listed = (_git_bytes("ls-tree", "--name-only", commit, folder + "/") or b"").decode().splitlines()
        return [name for name in listed if Path(name).match(pattern)]

    return _hash(part, lambda rel: _git_bytes("show", f"{commit}:{rel}"), lister)


def git_head() -> str:
    out = _git_bytes("rev-parse", "--short", "HEAD")
    return out.decode().strip() if out else ""


def commit_before(when_epoch: float, ref: str = "HEAD") -> str:
    """The last commit on ``ref`` made before ``when_epoch`` (short hash; empty when there is none)."""
    out = _git_bytes("rev-list", "-1", f"--before={int(when_epoch)}", ref)
    return out.decode().strip()[:10] if out else ""


# --- output hash -------------------------------------------------------------------------------------------------

def table_hash(conn: sqlite3.Connection, spec: str) -> str:
    """Order-free hash of one table's rows (``table-prefix*`` leaves out the columns with that prefix)."""
    table, _, drop = spec.partition("-")
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
        return "absent"
    cols = [r[1] for r in conn.execute(f'PRAGMA table_info("{table}")')
            if not (drop and r[1].startswith(drop.rstrip("*")))]
    total, count = 0, 0
    for row in conn.execute(f'SELECT {", ".join(chr(34) + c + chr(34) for c in cols)} FROM "{table}"'):
        total ^= int.from_bytes(hashlib.blake2b(repr(row).encode(), digest_size=8).digest(), "big")
        count += 1
    return f"{count}:{total:016x}"


def out_hash(conn: sqlite3.Connection, part: str) -> str:
    """Hash of everything ``part`` wrote into the store; empty for a part whose output is a file outside it."""
    specs = PART_TABLES[part]
    if not specs:
        return ""
    return hashlib.sha1("|".join(f"{s}={table_hash(conn, s)}" for s in specs).encode()).hexdigest()[:16]


# --- stamps ------------------------------------------------------------------------------------------------------

def _ensure(conn: sqlite3.Connection) -> None:
    conn.execute(DDL)


def read(conn: sqlite3.Connection) -> dict[str, dict]:
    """``{part: stamp}``; empty for a store built before stamps."""
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='part_stamp'").fetchone():
        return {}
    out = {}
    for row in conn.execute(f"SELECT {', '.join(COLUMNS)} FROM part_stamp"):
        stamp = dict(zip(COLUMNS, row))
        stamp["inputs"] = json.loads(stamp["inputs"] or "{}")
        out[stamp.pop("part")] = stamp
    return out


def _put(conn: sqlite3.Connection, part: str, code: str, out: str, built: str, seconds, head: str) -> None:
    stamps = read(conn)
    inputs = {up: stamps[up]["out_hash"] for up in UPSTREAM[part] if up in stamps}
    conn.execute(f"INSERT OR REPLACE INTO part_stamp ({', '.join(COLUMNS)}) VALUES (?,?,?,?,?,?,?)",
                 (part, code, out, json.dumps(inputs, sort_keys=True), built, seconds, head))


def write(conn: sqlite3.Connection, part: str, seconds: float | None = None, head: str | None = None,
          out: str | None = None) -> None:
    """Record that ``part`` was just built by the code on disk, what it wrote and what its inputs were."""
    _ensure(conn)
    _put(conn, part, code_hash(part), out_hash(conn, part) if out is None else out,
         time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), seconds, git_head() if head is None else head)
    conn.commit()


def baseline(conn: sqlite3.Connection, commit: str, built_epoch: float, outs: dict[str, str] | None = None,
             parts=None) -> list[str]:
    """Stamp a store built BEFORE stamps existed with the code of ``commit`` (the commit it was built from).

    Only parts with no stamp are written, in build order, with ``git_head`` ``baseline:<commit>`` and the rows the
    store holds now as their output, so a later ``stale`` lists exactly the parts whose code changed since that
    commit instead of every part of the store.  ``outs`` gives the output hash of the parts that write files."""
    _ensure(conn)
    have = read(conn)
    built = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(built_epoch))
    done = []
    for part in ORDER:
        if part in have or part not in (parts or RECIPE):
            continue
        _put(conn, part, code_hash_at(part, commit), (outs or {}).get(part) or out_hash(conn, part), built, None,
             f"baseline:{commit}")
        done.append(part)
    conn.commit()
    return done


def stale(conn: sqlite3.Connection, hashes: dict[str, str] | None = None) -> dict[str, str]:
    """``{part: reason}`` for every recipe part (and every other stamped part) of this store that is behind."""
    stamps = read(conn)
    current = hashes or {}
    out: dict[str, str] = {}
    for part in ORDER:
        if part not in RECIPE and part not in stamps:
            continue
        stamp = stamps.get(part)
        if stamp is None:
            out[part] = "never stamped"
            continue
        if stamp["code_hash"] != (current.get(part) or code_hash(part)):
            out[part] = "code changed"
            continue
        for up in UPSTREAM[part]:
            if up in out:
                out[part] = f"after {up}"
                break
            if up in stamps and stamp["inputs"].get(up) != stamps[up]["out_hash"]:
                out[part] = f"{up} output changed"
                break
    return out


def rewrites(ran: str, part: str) -> bool:
    """True when ``ran`` writes a table that the later ``part`` also writes: ``part`` must then run again whatever
    the hashes say (``stores`` rewrites the quarter rows and with them the windows ``preferred`` had set)."""
    tables = {spec.partition("-")[0] for spec in PART_TABLES[ran]}
    return ORDER.index(ran) < ORDER.index(part) and any(spec.partition("-")[0] in tables for spec in PART_TABLES[part])


def dependants(parts) -> list[str]:
    """``parts`` plus every recipe part that reads from them, directly or not, in build order."""
    wanted = set(parts)
    for part in ORDER:
        if part not in wanted and part in RECIPE and any(up in wanted for up in UPSTREAM[part]):
            wanted.add(part)
    return [p for p in ORDER if p in wanted]
