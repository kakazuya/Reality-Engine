"""Generate the worker context pack (``tasks/worker_context/CONTEXT.md``).

A new DeepSeek worker spends its first 40-100 tool calls rediscovering the repo,
the databases and the test commands.  This builder turns that orientation into
one generated file: repo map (module docstrings), data map (catalog cache, never
``COUNT(*)`` on the 50 GB DB), query rules, test map, sandbox limits, conventions
and recent decisions.  Full column lists go to ``schemas/<db>.md``.

Read-only on every database.  Deterministic: two runs differ only in the header
timestamp (and git HEAD).  Full column lists are written from
``plugins/reality-data/server/catalog_cache.json``; missing row counts fall back
to ``sqlite_stat1`` / ``MAX(rowid)``, then a bounded ``COUNT(*)`` for tables and
views without a rowid.

    python -m reality_engine.scripts.build_worker_context
"""
from __future__ import annotations

import argparse
import ast
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
STATE_RELATIVE = Path("tasks") / "STATE.md"
MAX_TOKENS = 20_000

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
SKIP_DIRS = {"tests", "fixtures", "__pycache__", "runtime", "node_modules", ".git"}

SECRET_ASSIGN = re.compile(r"(?i)\b(api[_-]?key|token|secret|password)\b(\s*[=:]\s*)\S+")
SECRET_VALUE = re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}\b")


def _safe(text: str) -> str:
    """Redact secret assignments/values from dynamic repo text."""
    return SECRET_VALUE.sub("sk-***", SECRET_ASSIGN.sub(r"\1\2***", str(text)))


def _first_doc_line(path: Path) -> str:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return ""
    doc = ast.get_docstring(tree) or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return _safe(line)[:120]
    return ""


def _module_paths(root: Path) -> list[tuple[str, Path]]:
    """Every reality_engine/**/*.py (no tests/fixtures) plus plugins/*/server/*.py."""
    paths: list[tuple[str, Path]] = []
    engine = root / "reality_engine"
    if engine.is_dir():
        for path in sorted(engine.rglob("*.py")):
            relative = path.relative_to(root)
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            paths.append((relative.as_posix(), path))
    plugins = root / "plugins"
    if plugins.is_dir():
        for path in sorted(plugins.glob("*/server/*.py")):
            relative = path.relative_to(root)
            if any(part in SKIP_DIRS for part in relative.parts):
                continue
            paths.append((relative.as_posix(), path))
    return paths


def _dir_purpose(directory: Path) -> str:
    core = directory / "server" / "core.py"
    if core.is_file():
        line = _first_doc_line(core)
        if line:
            return line
    if directory.name == "scripts" and directory.parent.name == "reality_engine":
        return "Operational job scripts: one module per data job; most-referenced list below"
    candidates = sorted(directory.glob("*.py")) + sorted(directory.glob("server/*.py"))
    for path in candidates:
        line = _first_doc_line(path)
        if line:
            return line
    return ""


def _clip(text: str, limit: int) -> str:
    text = _safe(text)
    return text if len(text) <= limit else text[:limit].rstrip() + " …"


def _count_files(base: Path, pattern: str) -> int:
    """Count files under ``base``, pruning SKIP_DIRS (ignored runtime fixtures)."""
    return sum(
        1
        for path in base.rglob(pattern)
        if not (set(path.relative_to(base).parts[:-1]) & SKIP_DIRS)
    )


def _repo_map(root: Path, data_root: Path, out_dir: Path) -> str:
    lines = ["## 1. Repo map", "", "Top-level tree to depth 2 (tests/fixtures skipped):", "```"]
    skip_out = out_dir.resolve()
    for family in ("reality_engine", "plugins", "tasks", "skills"):
        base = root / family
        if not base.is_dir():
            continue
        lines.append(f"{family}/")
        for child in sorted(base.iterdir()):
            if not child.is_dir() or child.name in SKIP_DIRS or child.name.startswith("."):
                continue
            if child.resolve() == skip_out:
                continue
            purpose = _dir_purpose(child) if family != "tasks" else ""
            if not purpose:
                continue  # leaf dirs with no module docstring
            count = _count_files(child, "*.py") if family != "tasks" else len(
                list(child.glob("*.md"))
            )
            unit = "md" if family == "tasks" else "py"
            lines.append(f"  {child.name}/ ({count} {unit}) — {purpose}")
    for child in sorted(root.iterdir()):
        if child.is_dir() and child.name not in SKIP_DIRS and not child.name.startswith(".") \
                and child.name not in {"reality_engine", "plugins", "tasks", "skills"}:
            purpose = _dir_purpose(child)
            if purpose:
                lines.append(f"{child.name}/ ({len(list(child.iterdir()))} entries) — {purpose}")
    lines += ["```", "",
              "Module one-liners (first docstring line, clipped; `__init__.py` and modules "
              "without a docstring skipped):", ""]

    grouped: dict[str, list[tuple[str, str]]] = {}
    for relative, path in _module_paths(root):
        if path.name == "__init__.py":
            continue
        purpose = _first_doc_line(path)
        if not purpose:
            continue
        parent = str(Path(relative).parent.as_posix())
        grouped.setdefault(parent, []).append((relative, _clip(purpose, 100)))
    for parent in sorted(grouped):
        entries = grouped[parent]
        if parent == "reality_engine/scripts":
            # 120+ one-file jobs; the ranked few below are the useful orientation.
            lines.append(
                f"- `{parent}/` — {len(entries)} data-job modules (one per data job); "
                "most-referenced ranked below."
            )
            continue
        lines.append(f"### {parent}/")
        for relative, purpose in entries:
            lines.append(f"- `{relative}` — {purpose}")
        lines.append("")

    scripts = _top_scripts(root, data_root)
    if scripts:
        lines += ["### Most-referenced scripts", "",
                  "Ranked by mentions in `tasks/STATE.md`, `plugins/dsh-worker/jobs.yaml` "
                  "and the 20 newest `tasks/dsh_tasks/*.md` briefs:", ""]
        for stem, count, purpose in scripts:
            lines.append(f"- `reality_engine/scripts/{stem}.py` ({count} refs) — {purpose}")
        lines.append("")
    lines += [
        "### Tools",
        "",
        "- Toolbelt (`reality_engine/toolbelt/README.md`; `python -m reality_engine.toolbelt.<tool>`, "
        "read-only): `coverage_peek --symbol X`, `find_docs --symbol X`, "
        "`sample_rows --db <db> --table <t> --n 5`, `job_peek <job>`, "
        "`render_pages --pdf <f> --pages 3,5-7`, `drive_fetch`, `cost_ledger`, `mod_test`.",
        "- Code-intel MCP (`mcp__code-intel__*`) — use before grep: `module_map(package)`, "
        "`symbols(file= | query=)`, `definition(symbol)`, `references(symbol)`, "
        "`callers(fn)`, `hover(file,line)`, `diagnostics(files= | changed=True)`.",
    ]
    return "\n".join(lines).rstrip()


def _top_scripts(root: Path, data_root: Path, limit: int = 12) -> list[tuple[str, int, str]]:
    texts: list[str] = []
    for path in (root / STATE_RELATIVE, root / "plugins" / "dsh-worker" / "jobs.yaml"):
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    briefs = sorted((root / "tasks" / "dsh_tasks").glob("*.md"))[-20:]
    for path in briefs:
        try:
            texts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    blob = "\n".join(texts)
    scripts_dir = root / "reality_engine" / "scripts"
    counts: dict[str, int] = {}
    if scripts_dir.is_dir():
        for path in scripts_dir.glob("*.py"):
            hits = blob.count(path.stem)
            if hits:
                counts[path.stem] = hits
    ranked = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]
    return [(stem, hits, _first_doc_line(scripts_dir / f"{stem}.py") or "(no docstring)")
            for stem, hits in ranked]


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
    root: Path, data_root: Path, cache: dict[str, Any], descriptions: dict[str, Any]
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


def _coverage(info: dict[str, Any]) -> str:
    coverage = info.get("date_coverage")
    if not isinstance(coverage, dict):
        return ""
    return f"{coverage.get('min')}..{coverage.get('max')}"


def _data_map(root: Path, data_root: Path, databases: dict[str, Any], missing: list[str]) -> str:
    lines = ["## 2. Data map", "",
             f"Data root: `{data_root}` (`REALITY_DATA_ROOT`; read-only from a worktree). "
             "Never write without an explicit instruction.", "",
             "| DB | file | size | tables | use |", "|---|---|---|---|---|"]
    uses = {
        "truth_duckdb": "Point-in-time research snapshot (adjusted prices, facts, policy).",
        "equity_intelligence": "Main search/data DB: documents, chunks+FTS, prices, flows, substrate.",
        "ar_facts": "Annual-report extraction: item/value rows with page, quote, period, basis.",
        "deck_figures": "Investor-presentation facts by page, sources and URLs.",
        "concall_facts": "Concall extraction: documents and guidance/KPI items with quotes.",
        "results_xbrl": "NSE XBRL results: filings, facts, trading-ISIN map.",
        "bse_announcements": "BSE announcement feed with dissemination timestamps.",
    }
    for db_key in DB_ORDER:
        db = databases.get(db_key)
        if db is None:
            lines.append(f"| {db_key} | MISSING FROM CATALOG | ? | ? | {uses.get(db_key, '')} |")
            continue
        name = db["path"].name if isinstance(db["path"], Path) else str(db["path"])
        lines.append(
            f"| {db_key} | `{name}` | {_human_size(db['size'])} | {len(db['tables'])} | "
            f"{db['description'] or uses.get(db_key, '')} |"
        )
    if missing:
        lines += ["", f"Catalog entries missing: {', '.join(missing)} (run the reality-data "
                      "`catalog(refresh=true)` tool)."]
    lines += ["", "Top 60 tables (key tables first, then by row count; full lists in `schemas/`):", "",
              "| table | rows | key columns | what it is | coverage |",
              "|---|---|---|---|---|"]
    ranked: list[tuple[int, int, int, str, str, dict[str, Any]]] = []
    for db_index, db_key in enumerate(DB_ORDER):
        db = databases.get(db_key)
        if db is None:
            continue
        for table, info in db["tables"].items():
            ranked.append((
                1 if table in KEY_TABLES else 0,
                int(info["rows"] or 0),
                -db_index,
                db_key,
                table,
                info,
            ))
    ranked.sort(key=lambda item: (-item[0], -item[1], -item[2], item[4]))
    for _key, _rows, _db_order, db_key, table, info in ranked[:60]:
        columns = ", ".join(f"`{col}`" for col in info["key_columns"][:5]) or "—"
        lines.append(
            f"| {db_key}.{table} | {_human_rows(info['rows'], info['rows_approx'])} | {columns} | "
            f"{info['description']} | {_coverage(info)} |"
        )
    lines += ["", "Row counts are the 2026-10-24 catalog measurements (exact for the large "
                  "tables, `~` = sqlite_stat1/MAX(rowid) estimate). **Never run `COUNT(*)` on "
                  "`equity_intelligence.db`**; use the cache or `sqlite_stat1`."]
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

Open SQLite read-only; never a bare `sqlite3.connect`:

```python
import os
from pathlib import Path
from reality_engine.db.readonly import connect_ro
DATA = Path(os.environ["REALITY_DATA_ROOT"])  # or repo/reality_engine/data
con = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)  # mode=ro + query_only
```

The `reality-data` MCP tools (prefer them over ad-hoc SQL):

| tool | use it when |
|---|---|
| `catalog` | first call: DB/table/row/coverage map (already summarized here). |
| `resolve` | symbol/name/ISIN -> canonical identity and ISIN history. |
| `price` | OHLCV, delivery %, traded value, adjustment factors for one range. |
| `facts` | annual-report / XBRL / deck / concall / guidance facts for a company. |
| `search_docs` | hybrid vector+FTS text search over concalls, decks, ARs, announcements. |
| `sql` | bounded read-only SELECT/WITH when the typed tools do not fit. |

Rules that prevent wrong answers:
- `document_chunks` is 2.9M rows: never correlated subqueries or unindexed `GROUP BY` on it.
- `corporate_documents.doc_date` is the **crawl date**, never a filing date; use
  `publication_date` / `bse_dissem_ts` / `call_date` for PIT work.
- Point-in-time: anything used for research carries `known_at` (or `known_at_utc`);
  never use data that was not known at the decision time.
- Trust layer (AGENTS.md §3.13): exclude `substrate_quarantine` keys and `*_demo` /
  `seed_*_demo` tables before showing substrate rows to a model; report degradation
  counts alongside the answer.
- One writer per SQLite DB; read-only connections only unless the task says write."""


def _tests_section(root: Path) -> str:
    mapping: dict[str, set[str]] = {}
    tests_dir = root / "reality_engine" / "tests"
    if tests_dir.is_dir():
        for test in sorted(tests_dir.glob("test_*.py")):
            try:
                text = test.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            modules: set[str] = set()
            for match in re.finditer(
                r"(?m)^\s*from\s+(reality_engine[\w.]*)\s+import\s+([^\n(]+)", text
            ):
                base = match.group(1)
                for name in match.group(2).split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if not re.fullmatch(r"\w+", name or ""):
                        continue
                    if (root / base.replace(".", "/") / name).with_suffix(".py").is_file():
                        modules.add(f"{base}.{name}")
                    elif (root / base.replace(".", "/")).with_suffix(".py").is_file():
                        modules.add(base)
            for match in re.finditer(r"(?m)^\s*import\s+(reality_engine[\w.]*)", text):
                modules.add(match.group(1))
            for module in modules:
                if module.startswith("reality_engine.tests"):
                    continue
                mapping.setdefault(module, set()).add(test.name)
    lines = [
        "## 4. Tests",
        "",
        "Exact commands (run the narrow module first; the whole-repo discovery is slow):",
        "",
        "```bash",
        'python -m unittest discover -s reality_engine/tests -p "test_*.py"',
        "python -m unittest reality_engine.tests.test_dsh_worker_plugin "
        "reality_engine.tests.test_dsh_worker_stress",
        "claude plugin validate <abs mod dir>",
        "claude plugin test --file <abs test file> <abs mod dir>",
        "```",
        "",
        "Data-touching tests must use in-memory/temp fixtures, never the live DBs.",
        "",
        "| module | its test file |",
        "|---|---|",
    ]
    for module in sorted(mapping):
        lines.append(f"| `{module}` | {', '.join(sorted(mapping[module]))} |")
    return "\n".join(lines)


def _sandbox_section(root: Path) -> str:
    return """## 5. Sandbox limits + workarounds

Digest only; full rules in `tasks/worker_context/SANDBOX.md` (read it before installing, writing outside the workspace, committing or launching).

| `permission` | dsh mode / approval | effect |
|---|---|---|
| `read-only` | `read-only`, `ask` | no writes; confined pwsh gets no temp dir, so `tempfile.mkdtemp()` fails |
| `workspace-write` | `workspace-write`, `ask` | writes under the session cwd plus a private per-session temp |
| `danger-full-access` | `danger-full-access`, `never` | unconfined |

- Writable root = session cwd only; there is no extra-writable-roots setting, and a junction to `REALITY_DATA_ROOT` does not help (the resolved target is checked).
- Temp/caches: `.tmp/` (`TMP`/`TEMP`, pip/uv/npm caches). Never `%LOCALAPPDATA%\\Temp`. `pip install --target .tmp/x ...`; optional `.venv-<task>`.
- `write_scope='data'`: needs `confirm_data_write=true` + `writes=[...]` + `approved_by`; runs `danger-full-access` exactly like `full` (`confirm_full_access=true`) — policy, not enforcement. A mutating main-checkout worker needs `confirm_repo_root_write=true`.
- Commit: write `.tmp/commit.request.json` `{"message": ...}` -> `.tmp/commit.result.json`; direct `git commit` is denied.
- Detached launch (data/full only): write `.tmp/launch.request.json` (`cmd`, `log`, `cwd`, `env`) -> `.tmp/launch.result.json`.
- Nested-sandbox demos cannot run from a confined token; see `tasks/worker_context/sandbox_probe.py`."""


def _conventions_section() -> str:
    return """## 6. Conventions

- Storage (AGENTS.md §3.2): local files only. SQLite in WAL mode holds the live data
  (`equity_intelligence.db`, `ar_facts.db`, `deck_figures.db`, `concall_facts.db`,
  `results_xbrl.db`, `bse_announcements.db`); the dated DuckDB snapshot is read-only and
  used for PIT research/backtests. PostgreSQL/pgvector is not installed and not used.
- Delivered (normalized) facts are the decision substrate; `raw_documents` is
  audit/replay only. Query via `connect_ro` or the `reality-data` tools; keep statements
  bounded.
- Trust layer (§3.13): exclude `substrate_quarantine` keys and demo/seed tables before
  presenting substrate rows; state degradation counts next to the answer.
- Point-in-time `known_at` for every research input; newest -> oldest for backfills.
- One writer per SQLite DB. Additive schema changes only. No `git stash` in worktrees.
- Match surrounding style; no unrequested abstractions.
- Paid API calls need an explicit budget in the brief. Keys come from
  `reality_engine.scripts.resource_watchdog.user_env()`; never print key values.
- Free models only on subscriptions; Go key 1 is dead, Go key 2 + Kilo keys 1/2
  work, and every Go call sends a stable session id."""


def _secret_marker(text: str) -> bool:
    """Drop lines carrying secret-like names; conservative on purpose."""
    text = str(text)
    return "KEY" in text or "TOKEN" in text or bool(SECRET_VALUE.search(text))


def _recent_section(root: Path, data_root: Path) -> str:
    lines = ["## 7. Recent decisions", ""]
    decisions = data_root / "hotline" / "decisions.md"
    entries: list[str] = []
    if decisions.is_file():
        for line in decisions.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                entries.append(_clip(stripped, 240))
    if entries:
        lines += ["Last 30 one-line entries from `reality_engine/data/hotline/decisions.md`:", ""]
        lines += entries[-30:]
    else:
        lines.append("`reality_engine/data/hotline/decisions.md` not found or empty.")
    state = root / STATE_RELATIVE
    if state.is_file():
        text = state.read_text(encoding="utf-8", errors="replace")
        sections = re.split(r"(?m)^## ", text)
        tail = [section for section in sections[1:] if section.strip()][-2:]
        if tail:
            lines += ["", "Last two `## ` sections of `tasks/STATE.md` (truncated):", ""]
            for section in tail:
                heading, _, body = section.partition("\n")
                body = _safe(body.strip())
                if len(body) > 2200:
                    body = body[:2200].rstrip() + "\n… (truncated; read tasks/STATE.md)"
                lines += [f"### {heading.strip()}", "", body, ""]
    return "\n".join(lines).rstrip()


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
    databases, missing = _databases(root, data, cache, descriptions)

    header = "\n".join([
        "# Worker context pack",
        "",
        f"Generated: {timestamp.isoformat(timespec='seconds')} · git HEAD: `{_git_head(root)}` · "
        f"data root: `{data}`",
        "Staleness: regenerate with `python -m reality_engine.scripts.build_worker_context`; the "
        "`worker_context` job runs daily and a pack older than 26 h is regenerated before a "
        "worker starts.",
        "Read this once. It replaces file-by-file orientation; the task brief is still the "
        "authority for what to do.",
    ])
    sections = [
        header,
        _repo_map(root, data, out),
        _data_map(root, data, databases, missing),
        _how_to_query(),
        _tests_section(root),
        _sandbox_section(root),
        _conventions_section(),
        _recent_section(root, data),
    ]
    text = _safe("\n\n".join(section.strip() for section in sections if section.strip())) + "\n"
    kept: list[str] = []
    dropped = 0
    for line in text.splitlines():
        if _secret_marker(line):
            dropped += 1
            continue
        kept.append(line)
    if dropped:
        kept += ["", f"_({dropped} line(s) omitted by the secret filter)_"]
    text = "\n".join(kept).rstrip() + "\n"
    out.mkdir(parents=True, exist_ok=True)
    context_path = out / "CONTEXT.md"
    context_path.write_text(text, encoding="utf-8")
    schemas = _write_schemas(out, databases)
    chars = len(text)
    return {
        "path": str(context_path),
        "chars": chars,
        "tokens_estimate": round(chars / 4),
        "over_budget": round(chars / 4) > MAX_TOKENS,
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
        f"wrote {stats['path']}: {stats['tokens_estimate']} tokens est "
        f"({stats['chars']} chars), {stats['databases']} DBs / {stats['tables']} tables, "
        f"{len(stats['schemas'])} schema files, {stats['seconds']}s"
    )
    if stats["over_budget"]:
        print(f"WARNING: over the {MAX_TOKENS} token budget; trim the repo map")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
