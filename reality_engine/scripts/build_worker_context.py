"""Generate the worker context pack (``tasks/worker_context/CONTEXT.md``).

The pack is deliberately an index, not an orientation manual: it says how to look
things up (code-intel for code, reality-data for data), how to query, how to pick
and run tests, the sandbox limits, the conventions and where live state lives.  A
worker reads it once, then only the files its brief names.

Full column lists go beside it in ``schemas/<db>.md``.  Read-only on every
database.  Deterministic: two runs differ only in the header timestamp (and git
HEAD).  Missing row counts fall back to ``sqlite_stat1`` / ``MAX(rowid)``, then a
bounded ``COUNT(*)`` for tables and views without a rowid.  The pack must stay at
or under ``MAX_BYTES`` (20,000 bytes, about 5k tokens).

    python -m reality_engine.scripts.build_worker_context
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "tasks" / "worker_context"
DATA_ROOT = Path(
    os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data")
).resolve()
CACHE_RELATIVE = Path("plugins") / "reality-data" / "server" / "catalog_cache.json"
DESCRIPTIONS_RELATIVE = Path("plugins") / "reality-data" / "catalog_descriptions.yaml"
MAX_BYTES = 20_000

DB_ORDER = [
    "truth_duckdb",
    "equity_intelligence",
    "ar_facts",
    "deck_figures",
    "concall_facts",
    "results_xbrl",
    "bse_announcements",
]
DEMO_TABLES = {
    "business_model_profiles_demo", "seed_countries_demo", "seed_industries_demo",
}
PREFERRED_KEYS = (
    "isin", "symbol", "nse_symbol", "bse_symbol", "date", "period_end", "period",
    "fiscal_year", "known_at_utc", "known_at", "published_date", "filed_at",
    "doc_id", "chunk_id", "id", "file", "metric", "item", "concept", "source_type",
    "prid", "newsid", "sc_code", "scripcode",
)
# Small but essential tables that must survive the "top 60 by rows" cut.
KEY_TABLES = {
    "master_companies", "security_master", "symbol_isin_history", "corporate_documents",
    "raw_documents", "document_chunks", "intelligence_fts", "daily_price_delivery",
    "insider_trades_v2", "shareholding", "quarterly_financials", "annual_financials",
    "ar_docs", "ar_facts", "cc_docs", "cc_items", "filings", "ann", "deck_sources",
    "pages", "facts", "events", "pib_releases", "policy_events", "fii_dii_cash",
    "nse_master", "px_nse_adj", "px_bse_adj", "results_filings",
}
AUTO_DESCRIPTIONS = {
    "raw_documents": "Search-layer document registry (title, type, date, URL).",
    "document_chunks": "Indexed text chunks with embeddings and symbol/date.",
    "intelligence_fts": "FTS5 index over document chunks (lexical search).",
    "corporate_documents": "Corporate filing registry with PIT dates and local paths.",
    "px_nse": "NSE daily OHLCV, delivery quantity/percent and traded value.",
    "px_nse_adj": "NSE daily bars with cumulative split/dividend adjustment factors.",
    "px_bse": "BSE daily OHLCV, delivery and traded value.",
    "px_bse_adj": "BSE daily bars with cumulative adjustment factors.",
    "security_master": "Canonical equity identity: ISIN, NSE/BSE symbols and listing dates.",
    "symbol_isin_history": "Symbol/ISIN validity windows (splits, renames, delistings).",
    "master_companies": "Legacy company identity table (ISIN anchor).",
    "ar_facts": "Annual-report extracted facts with page, quote, period and basis.",
    "ar_docs": "Annual-report document register.",
    "results_xbrl": "XBRL results facts with concept, context and period.",
    "results_filings": "XBRL filing register with dissemination time and trading ISIN.",
    "filings": "XBRL filing register with dissemination time and trading ISIN.",
    "deck_facts": "Investor-presentation metrics by page.",
    "deck_sources": "Presentation/deck source registry with URLs and PIT dates.",
    "cc_docs": "Concall transcript document register.",
    "cc_items": "Concall guidance/KPI items with quotes and direction.",
    "ann": "BSE announcements with headline, category and dissemination time.",
    "events": "Unified company event ledger keyed by ISIN and known-at time.",
    "pib_releases": "PIB press releases with publication and posting times.",
    "policy_events": "Extracted policy events with stage, sectors and effective dates.",
    "quarterly_financials": "Quarterly revenue/PAT/margin table with XBRL source path.",
    "annual_financials": "Annual revenue/EBITDA/PAT/leverage table by fiscal year.",
    "daily_price_delivery": "Daily price + delivery + technical indicators by symbol.",
    "shareholding": "Quarterly shareholding pattern (promoter/FII/DII/retail).",
    "insider_trades_v2": "PIT insider trades (known_at is the point-in-time key).",
    "facts": "Extracted item/value facts with page, quote and period.",
    "pages": "Deck page register (known_at, source, page number).",
}
SECRET_ASSIGN = re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b(\s*[=:]\s*)\S+")
SECRET_VALUE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")


def _safe(text: str) -> str:
    """Redact secret assignments/values from dynamic repo text."""
    return SECRET_VALUE.sub("sk-***", SECRET_ASSIGN.sub(r"\1\2***", str(text)))


def _load_cache(root: Path) -> dict[str, Any]:
    path = root / CACHE_RELATIVE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _load_descriptions(root: Path) -> dict[str, Any]:
    path = root / DESCRIPTIONS_RELATIVE
    if not path.is_file():
        return {}
    try:
        import yaml  # type: ignore

        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _skip_table(name: str) -> bool:
    low = name.lower()
    if low in DEMO_TABLES or low.startswith("sqlite_"):
        return True
    if low.endswith("_placeholder_archive") or low.startswith("fts_main_"):
        return True
    return bool(re.search(r"_fts_(config|content|data|docsize|idx)$", low))


def _auto_description(db_key: str, table: str) -> str:
    return AUTO_DESCRIPTIONS.get(
        table, f"{db_key} table {table!r} (auto-described; inspect columns in schemas/)."
    )


def _key_columns(columns: list[list[str]] | list[tuple[str, str]]) -> list[str]:
    names = [str(col[0]) for col in columns]
    lowered = {name.lower(): name for name in names}
    picked = [lowered[key] for key in PREFERRED_KEYS if key in lowered]
    return (picked or names)[:8]


def _fallback_rows(db_path: Path, tables: set[str]) -> dict[str, tuple[int, bool]]:
    """Rows from sqlite_stat1, else MAX(rowid); views get a bounded COUNT(*)."""
    out: dict[str, tuple[int, bool]] = {}
    if not db_path.is_file() or not tables:
        return out
    deadline = [time.monotonic() + 1.5]
    try:
        connection = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True, timeout=2.0)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA temp_store = MEMORY")
        connection.set_progress_handler(lambda: 1 if time.monotonic() > deadline[0] else 0, 20000)
    except sqlite3.Error:
        return out
    try:
        try:
            for table, stat in connection.execute("SELECT tbl, stat FROM sqlite_stat1"):
                if table in tables:
                    parts = str(stat).split()
                    if parts:
                        out[table] = (int(parts[0]), True)
        except (sqlite3.Error, ValueError):
            pass
        for table in sorted(tables):
            if table in out:
                continue
            try:
                row = connection.execute(f'SELECT max(rowid) FROM "{table}"').fetchone()
            except sqlite3.Error:
                row = None
            if row and row[0] is not None:
                out[table] = (int(row[0]), True)
                continue
            # Views (and WITHOUT ROWID tables) have no rowid: COUNT(*) is the only
            # exact answer, so bound it per table instead of scanning a huge view.
            # ponytail: fixed 3 s per table; a cold cache can still time out a
            # borderline view, so rows stay "?" rather than slowing the build.
            deadline[0] = time.monotonic() + 3.0
            try:
                counted = connection.execute(f'SELECT count(*) FROM "{table}"').fetchone()
            except sqlite3.Error:
                continue
            if counted and counted[0] is not None:
                out[table] = (int(counted[0]), False)
    finally:
        connection.close()
    return out


def _databases(
    data_root: Path, cache: dict[str, Any], descriptions: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    cached = cache.get("databases") or {}
    result: dict[str, Any] = {}
    missing: list[str] = []
    for db_key in DB_ORDER:
        entry = cached.get(db_key)
        if not isinstance(entry, dict):
            missing.append(db_key)
            continue
        kind = entry.get("kind") or ("duckdb" if db_key == "truth_duckdb" else "sqlite")
        if kind == "duckdb":
            files = sorted((data_root / "snapshots").glob("*.duckdb"))
            file_path = files[-1] if files else Path(entry.get("path") or "")
        else:
            file_path = data_root / f"{db_key}.db"
            if not file_path.is_file():
                file_path = Path(entry.get("path") or file_path)
        curated_db = descriptions.get(db_key) if isinstance(descriptions, dict) else None
        curated_db = curated_db if isinstance(curated_db, dict) else {}
        curated_tables = curated_db.get("tables") if isinstance(curated_db.get("tables"), dict) else {}
        tables: dict[str, Any] = {}
        missing_rows: set[str] = set()
        for table, info in (entry.get("tables") or {}).items():
            if not isinstance(info, dict) or info.get("error") or _skip_table(table):
                continue
            curated = curated_tables.get(table) if isinstance(curated_tables, dict) else None
            curated = curated if isinstance(curated, dict) else {}
            rows = info.get("rows")
            if rows is None and kind == "sqlite":
                missing_rows.add(table)
            tables[table] = {
                "rows": rows,
                "rows_approx": bool(info.get("rows_approx", rows is None)),
                "columns": info.get("columns") or [],
                "key_columns": curated.get("key_columns") or _key_columns(info.get("columns") or []),
                "description": curated.get("description") or _auto_description(db_key, table),
                "date_coverage": info.get("date_coverage"),
            }
        if missing_rows:
            for table, (rows, approx) in _fallback_rows(file_path, missing_rows).items():
                tables[table]["rows"] = rows
                tables[table]["rows_approx"] = approx
        result[db_key] = {
            "kind": kind,
            "path": file_path,
            "size": file_path.stat().st_size if file_path.is_file() else None,
            "description": curated_db.get("description") or "",
            "tables": tables,
        }
    return result, missing


def _human_size(size: int | None) -> str:
    if not size:
        return "?"
    if size >= 2**30:
        return f"{size / 2**30:.1f} GB"
    return f"{size / 2**20:.0f} MB"


def _human_rows(rows: int | None, approx: bool = False) -> str:
    if rows is None:
        return "?"
    if rows >= 1_000_000:
        text = f"{rows / 1_000_000:.1f}M"
    elif rows >= 1_000:
        text = f"{rows / 1_000:.1f}k"
    else:
        text = str(rows)
    return ("~" if approx else "") + text


def _repo_lookup() -> str:
    return """## 1. Repo: look it up

Do not survey the repo. The brief names the files; read those and edit.
- code-intel MCP (`mcp__code-intel__*`): `module_map(package)` — one line of purpose per module.
- `symbols(file=...)` — a module outline; `symbols(query=...)` — name search across the workspace.
- `definition(symbol)`, `references(symbol)`, `callers(fn)`, `hover(file, line)` — where a symbol is defined and every use.
- `diagnostics(files=[...] | changed=True)` — type/import errors; run it on every changed file before reporting.
- No MCP? `python plugins/code-intel/ci.py <cmd>` returns the same JSON."""


def _data_lookup(data_root: Path, missing: list[str]) -> str:
    lines = [
        "## 2. Data: look it up",
        "",
        f"Data root: `{data_root}` (`REALITY_DATA_ROOT`, read-only from a worktree; never write "
        "without an explicit instruction).",
        "- `catalog()` — every DB, table, row count and coverage; `catalog(db=\"...\")` for one DB.",
        "- `schema(table, db=\"...\")` — columns, types and indexes for one table.",
        "- `resolve`, `price`, `delivery`, `holding`, `facts`, `docs`, `search_docs` answer the usual "
        "company questions directly; `sql` is the bounded read-only escape hatch.",
        "- Never run `COUNT(*)` on `equity_intelligence.db`; use the catalog row counts.",
        "- Full column lists: `schemas/<db>.md` beside this pack.",
    ]
    if missing:
        lines.append(
            f"- Catalog entries missing: {', '.join(missing)} (run `catalog(refresh=true)`)."
        )
    return "\n".join(lines)


def _write_schemas(out_dir: Path, databases: dict[str, Any]) -> list[str]:
    schemas_dir = out_dir / "schemas"
    schemas_dir.mkdir(parents=True, exist_ok=True)
    written: list[str] = []
    for db_key in DB_ORDER:
        db = databases.get(db_key)
        if db is None or not db["tables"]:
            continue
        lines = [f"# {db_key} schema", "", f"File: `{db['path']}` ({_human_size(db['size'])})", ""]
        if db["description"]:
            lines += [db["description"], ""]
        for table in sorted(db["tables"]):
            info = db["tables"][table]
            lines.append(f"## {table}")
            lines.append(
                f"rows: {_human_rows(info['rows'], info['rows_approx'])} · "
                f"key columns: {', '.join(info['key_columns']) or '—'}"
            )
            if info["description"]:
                lines.append(info["description"])
            lines.append("")
            for column in info["columns"]:
                if isinstance(column, (list, tuple)) and column:
                    name = column[0]
                    kind = column[1] if len(column) > 1 else ""
                    lines.append(f"- `{name}` {kind}".rstrip())
            lines.append("")
        path = schemas_dir / f"{db_key}.md"
        path.write_text(_safe("\n".join(lines).rstrip()) + "\n", encoding="utf-8")
        written.append(str(path))
    return written


def _how_to_query() -> str:
    return """## 3. How to query

Read-only; never a bare `sqlite3.connect`:

```python
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro
DATA = Path(os.environ["REALITY_DATA_ROOT"])
con = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)  # mode=ro + query_only
```

- Prefer the typed `reality-data` tools; `sql` is the bounded read-only escape hatch.
- `document_chunks` is ~2.9M rows: no correlated subqueries, no unindexed `GROUP BY`.
- `corporate_documents.doc_date` is the crawl date, never a filing date; use
  `publication_date` / `bse_dissem_ts` / `call_date` for PIT work.
- Point in time: use only rows known at the decision time (`known_at`/`known_at_utc`).
- Trust layer: exclude `substrate_quarantine` keys and `*_demo`/`seed_*_demo` tables before
  showing substrate rows; state degradation counts next to the answer."""


def _tests_section() -> str:
    return """## 4. Pick and run tests

Find the test file for a module (grep the module name under `reality_engine/tests/test_*.py`),
then run the narrowest selection:

```bash
python -m pytest reality_engine/tests/test_<name>.py -q
python -m pytest reality_engine/tests -q -k "<keyword>"
python -m pytest reality_engine/tests -q          # full suite, slow
```

- Run the narrowed test first; run the full suite once before reporting.
- Data-touching tests use in-memory or temp fixtures, never the live DBs; no paid or network calls.
- A bug fix leaves one runnable check behind; new behaviour gets its own test."""


def _sandbox_section() -> str:
    return """## 5. Sandbox limits + workarounds

Full rules: `tasks/worker_context/SANDBOX.md`.

| `permission` | dsh mode / approval | effect |
|---|---|---|
| `read-only` | `read-only`, `ask` | no writes; confined pwsh gets no temp dir, so `tempfile.mkdtemp()` fails |
| `workspace-write` | `workspace-write`, `ask` | writes under the session cwd plus a private per-session temp |
| `danger-full-access` | `danger-full-access`, `never` | unconfined |

- Writable root = session cwd only; a junction to `REALITY_DATA_ROOT` does not help (the resolved target is checked).
- Temp/caches: `.tmp/` (`TMP`/`TEMP`, pip/uv/npm caches); never `%LOCALAPPDATA%\\Temp`; `pip install --target .tmp/x ...`.
- `write_scope='data'` needs `confirm_data_write=true` + `writes`; it runs as `danger-full-access` (policy, not enforcement). A repo-root mutator needs `confirm_repo_root_write=true`.
- Commit: write `.tmp/commit.request.json` `{"message": ...}` -> `.tmp/commit.result.json`; direct `git commit` is denied.
- Detached launch: write `.tmp/launch.request.json` (`cmd`, `log`, `cwd`, `env`) -> `.tmp/launch.result.json`."""


def _conventions_section() -> str:
    return """## 6. Conventions

- Storage: local files only. SQLite in WAL holds the live data (`equity_intelligence.db`,
  `ar_facts.db`, `deck_figures.db`, `concall_facts.db`, `results_xbrl.db`,
  `bse_announcements.db`); the dated DuckDB snapshot is read-only PIT research. No PostgreSQL.
- Delivered facts are the decision substrate; `raw_documents` is audit/replay only.
- Trust layer: exclude `substrate_quarantine` keys and demo/seed tables; report degradation counts.
- Point-in-time `known_at` for every research input; newest -> oldest for backfills.
- One writer per SQLite DB; additive schema changes only; no `git stash` in worktrees.
- Match surrounding style; no unrequested abstractions.
- Paid API calls need an explicit budget in the brief; keys come from
  `reality_engine.scripts.resource_watchdog.user_env()`; never print key values.
- Docs are part of the change: update every doc that states what changed, and name your
  code files in `machines/<host>.md`."""


def _current_state_section() -> str:
    return """## 7. Current state

Current step, next action, running jobs and blockers: `tasks/STATE.md`. Shivam's rulings bind you: read `tasks/RULINGS.md`.
Trading and risk rules: `tasks/FRAMEWORK.md`. Dated decisions:
`D:\\RealityEngine\\plans\\DECISION_LOG.md`."""


def _git_head(root: Path) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        return completed.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build(
    repo_root: Path | None = None,
    data_root: Path | None = None,
    out_dir: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    root = Path(repo_root or ROOT).resolve()
    data = Path(data_root or DATA_ROOT).resolve()
    out = Path(out_dir or OUT_DIR).resolve()
    timestamp = (now or datetime.now(timezone.utc)).astimezone()
    cache = _load_cache(root)
    descriptions = _load_descriptions(root)
    databases, missing = _databases(data, cache, descriptions)

    header = "\n".join([
        "# Worker context pack",
        "",
        f"Generated: {timestamp.isoformat(timespec='seconds')} · git HEAD: `{_git_head(root)}` · "
        f"data root: `{data}`",
        "**Working rule: the brief names the files. Read those and edit them; do not survey the "
        "repo.** This pack is for looking things up, not for deciding what the repo contains; if "
        "it and the repo disagree, the repo wins.",
        "Read this once, then only the files the brief names. Staleness: regenerate with "
        "`python -m reality_engine.scripts.build_worker_context`; the `worker_context` job runs "
        "daily and a pack older than 26 h is rebuilt before a worker starts.",
    ])
    sections = [
        header,
        _repo_lookup(),
        _data_lookup(data, missing),
        _how_to_query(),
        _tests_section(),
        _sandbox_section(),
        _conventions_section(),
        _current_state_section(),
    ]
    text = _safe("\n\n".join(section.strip() for section in sections if section.strip())) + "\n"
    out.mkdir(parents=True, exist_ok=True)
    context_path = out / "CONTEXT.md"
    context_path.write_text(text, encoding="utf-8", newline="\n")
    schemas = _write_schemas(out, databases)
    chars = len(text)
    size = len(text.encode("utf-8"))
    return {
        "path": str(context_path),
        "chars": chars,
        "bytes": size,
        "tokens_estimate": round(chars / 4),
        "over_budget": size > MAX_BYTES,
        "seconds": round(time.monotonic() - started, 2),
        "databases": len(databases),
        "tables": sum(len(db["tables"]) for db in databases.values()),
        "schemas": schemas,
        "missing_databases": missing,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build tasks/worker_context/CONTEXT.md")
    parser.add_argument("--repo-root", type=Path, default=ROOT)
    parser.add_argument("--data-root", type=Path, default=None)
    parser.add_argument("--out-dir", type=Path, default=None)
    args = parser.parse_args(argv)
    stats = build(
        repo_root=args.repo_root,
        data_root=args.data_root,
        out_dir=args.out_dir,
    )
    print(
        f"wrote {stats['path']}: {stats['bytes']} bytes / {stats['tokens_estimate']} tokens est, "
        f"{stats['databases']} DBs / {stats['tables']} tables, "
        f"{len(stats['schemas'])} schema files, {stats['seconds']}s"
    )
    if stats["over_budget"]:
        print(f"WARNING: over the {MAX_BYTES}-byte budget; trim the lookup sections")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
