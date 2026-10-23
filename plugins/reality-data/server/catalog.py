"""Catalog of the reality-engine data map.

The model learns where data lives in one call: database, table, one-line
description, key columns, row count and date coverage.  Descriptions are
merged from ``catalog_descriptions.yaml`` when the curator provides it; without
it the catalog still works from live introspection alone.

A small on-disk cache (``catalog_cache.json``) keeps the call fast; ``refresh``
re-introspects the live files.  Counts for the largest tables are the measured
2026-10-24 values (exact), everything else is ``MAX(rowid)`` and labelled
``rows_approx``.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import sqlite3
import time
from pathlib import Path
from typing import Any

from core import (
    DATA, DUCK_KEY, ROOT, _lock as core_lock, _run_duck, _run_sqlite,
    connect_duck, connect_sqlite, db_path, provenance, quarantine,
    quarantined_doc_ids, snapshot_path,
)

PLUGIN_ROOT = Path(__file__).resolve().parents[1]
CACHE_PATH = Path(os.environ.get("REALITY_DATA_CATALOG_CACHE") or Path(__file__).with_name("catalog_cache.json"))
DESCRIPTIONS_PATH = Path(
    os.environ.get("REALITY_DATA_CATALOG_DESCRIPTIONS") or PLUGIN_ROOT / "catalog_descriptions.yaml"
)

DB_SPECS: list[tuple[str, str]] = [
    (DUCK_KEY, "duckdb"),
    ("equity_intelligence", "sqlite"),
    ("ar_facts", "sqlite"),
    ("deck_figures", "sqlite"),
    ("concall_facts", "sqlite"),
    ("results_xbrl", "sqlite"),
    ("bse_announcements", "sqlite"),
]

DB_DESCRIPTIONS = {
    DUCK_KEY: "Point-in-time truth snapshot: company identity, NSE/BSE prices and "
              "delivery, events, annual-report/deck/concall/results facts, policy/PIB.",
    "equity_intelligence": "Search layer (44 GB): raw documents, chunks + embeddings, "
                            "intelligence_fts, corporate documents, price/flow/peer tables.",
    "ar_facts": "Annual-report extraction (20 GB): item/value rows with page, quote, "
                "period and basis.",
    "results_xbrl": "NSE XBRL results: filings, facts and the trading-ISIN map.",
    "deck_figures": "Investor-presentation facts: page metrics, sources and URLs.",
    "concall_facts": "Concall extraction: documents and guidance/KPI items with quotes.",
    "bse_announcements": "BSE announcement feed with dissemination timestamps.",
}

DEMO_TABLES = {
    "business_model_profiles_demo", "seed_countries_demo", "seed_industries_demo",
}
SLOW_TABLES = {"intelligence_fts"}

# Measured exact counts (2026-10-24) for the large/key tables. MAX(rowid) is
# used for the rest and reported as rows_approx.
KNOWN_COUNTS: dict[str, dict[str, int]] = {
    "equity_intelligence": {
        "raw_documents": 34760, "document_chunks": 2260570, "intelligence_fts": 2259771,
        "corporate_documents": 127178, "daily_price_delivery": 3133449,
        "annual_financials": 12933, "quarterly_financials": 15168,
    },
    "ar_facts": {"ar_facts": 32443403, "ar_docs": 33705},
    "deck_figures": {"facts": 13569583, "pages": 815837, "deck_sources": 26391},
    "results_xbrl": {"facts": 13941210, "filings": 106613},
    "bse_announcements": {"ann": 1947087},
    "concall_facts": {"cc_docs": 9294, "cc_items": 644957},
}

# Measured coverage for the very large tables, so a refresh does not rescan
# 32M-row tables just to print a min/max. Other tables are probed live.
KNOWN_COVERAGE: dict[tuple[str, str], dict[str, Any]] = {
    (DUCK_KEY, "px_nse"): {"column": "date", "min": "2019-01-01", "max": "2026-10-19"},
    (DUCK_KEY, "px_nse_adj"): {"column": "date", "min": "2019-01-01", "max": "2026-10-19"},
    (DUCK_KEY, "px_bse"): {"column": "date", "min": "2019-01-01", "max": "2026-10-19"},
    (DUCK_KEY, "px_bse_adj"): {"column": "date", "min": "2019-01-01", "max": "2026-10-19"},
    (DUCK_KEY, "ar_facts"): {"column": "fiscal_year", "min": "2015-03-31", "max": "2026-03-31"},
    (DUCK_KEY, "ar_docs"): {"column": "filed_at", "min": "2015-03-31", "max": "2026-09-07"},
    (DUCK_KEY, "results_filings"): {"column": "period_end", "min": "2017-06-30", "max": "2026-09-30"},
    (DUCK_KEY, "deck_sources"): {"column": "known_at", "min": "2021-01-04T08:39:52.927", "max": "2026-09-29T22:49:57.223"},
    (DUCK_KEY, "cc_docs"): {"column": "filed_at", "min": "2026-01-06T21:49:52.907", "max": "2026-10-14T17:21:32.7"},
    (DUCK_KEY, "bse_ann"): {"column": "known_at_utc", "min": "2019-12-31T20:59:43.797", "max": "2026-10-19T14:10:50.513"},
    (DUCK_KEY, "pib_releases"): {"column": "release_date", "min": "2021-01-01", "max": "2026-10-19"},
    (DUCK_KEY, "events"): {"column": "known_at_utc", "min": "2018-11-29T11:36:00", "max": "2026-10-19T18:29:59"},
    ("ar_facts", "ar_facts"): {"column": "fiscal_year", "min": "2015-03-31", "max": "2026-03-31"},
    ("ar_facts", "ar_docs"): {"column": "fiscal_year", "min": "2015-03-31", "max": "2026-03-31"},
    ("results_xbrl", "filings"): {"column": "period_end", "min": "2017-06-30", "max": "2026-09-30"},
    ("deck_figures", "deck_sources"): {"column": "known_at", "min": "2021-01-04T08:39:52.927", "max": "2026-09-29T22:49:57.223"},
    ("concall_facts", "cc_docs"): {"column": "filed_at", "min": "2026-01-06T21:49:52.907", "max": "2026-10-14T17:21:32.7"},
    ("bse_announcements", "ann"): {"column": "DT_TM", "min": "2019-12-31", "max": "2026-10-19"},
}

DATE_COLUMNS: dict[tuple[str, str], str] = {
    (DUCK_KEY, "px_nse"): "date", (DUCK_KEY, "px_nse_adj"): "date",
    (DUCK_KEY, "px_bse"): "date", (DUCK_KEY, "px_bse_adj"): "date",
    (DUCK_KEY, "ar_facts"): "fiscal_year", (DUCK_KEY, "ar_docs"): "filed_at",
    (DUCK_KEY, "results_filings"): "period_end", (DUCK_KEY, "results_facts"): "period_end",
    (DUCK_KEY, "deck_facts"): "known_at_utc", (DUCK_KEY, "deck_sources"): "known_at",
    (DUCK_KEY, "cc_docs"): "filed_at", (DUCK_KEY, "cc_items"): "filed_at",
    (DUCK_KEY, "bse_ann"): "known_at_utc", (DUCK_KEY, "pib_releases"): "release_date",
    (DUCK_KEY, "policy_events"): "published_at", (DUCK_KEY, "events"): "known_at_utc",
    (DUCK_KEY, "nse_master"): "symbol", (DUCK_KEY, "symbol_isin_history"): "first_date",
    (DUCK_KEY, "fii_dii_cash"): "date", (DUCK_KEY, "index_tri"): "date",
    (DUCK_KEY, "bse_deals"): "date", (DUCK_KEY, "nse_deals"): "date",
    ("equity_intelligence", "raw_documents"): "published_date",
    ("equity_intelligence", "document_chunks"): "published_date",
    ("equity_intelligence", "intelligence_fts"): "document_date",
    ("equity_intelligence", "corporate_documents"): "doc_date",
    ("equity_intelligence", "daily_price_delivery"): "date",
    ("equity_intelligence", "ar_facts"): "fiscal_year",
    ("ar_facts", "ar_facts"): "fiscal_year", ("ar_facts", "ar_docs"): "fiscal_year",
    ("deck_figures", "deck_sources"): "known_at", ("deck_figures", "pages"): "known_at",
    ("concall_facts", "cc_docs"): "filed_at", ("concall_facts", "cc_items"): "filed_at",
    ("results_xbrl", "filings"): "period_end", ("results_xbrl", "facts"): "period_end",
    ("bse_announcements", "ann"): "DT_TM",
}

PREFERRED_KEYS = (
    "isin", "symbol", "nse_symbol", "bse_symbol", "date", "period_end", "period",
    "fiscal_year", "known_at_utc", "known_at", "published_date", "filed_at",
    "doc_id", "chunk_id", "id", "file", "metric", "item", "concept", "source_type",
    "prid", "newsid", "sc_code", "scripcode",
)


def _skip_table(name: str) -> bool:
    low = name.lower()
    if low in DEMO_TABLES or low.startswith("sqlite_"):
        return True
    if low.endswith("_placeholder_archive"):
        return True
    if low.startswith("fts_main_"):
        return True
    if re.search(r"_fts_(config|content|data|docsize|idx)$", low):
        return True
    return False


def _auto_description(db_key: str, table: str) -> str:
    known = {
        "raw_documents": "Search-layer document registry (title, type, date, URL).",
        "document_chunks": "Indexed text chunks with bge-small embeddings and symbol/date.",
        "intelligence_fts": "FTS5 index over document chunks (lexical search).",
        "corporate_documents": "Corporate filing registry with PIT dates and local paths.",
        "px_nse": "NSE daily OHLCV, delivery quantity/percent and traded value.",
        "px_nse_adj": "NSE daily bars with cumulative split/dividend adjustment factors.",
        "px_bse": "BSE daily OHLCV, delivery and traded value.",
        "px_bse_adj": "BSE daily bars with cumulative adjustment factors.",
        "security_master": "Canonical equity identity: ISIN, NSE/BSE symbols and listing dates.",
        "symbol_isin_history": "Symbol/ISIN validity windows (splits, renames, delistings).",
        "ar_facts": "Annual-report extracted facts with page, quote, period and basis.",
        "ar_docs": "Annual-report document register.",
        "results_xbrl": "XBRL results facts with concept, context and period.",
        "results_filings": "XBRL filing register with dissemination time and trading ISIN.",
        "deck_facts": "Investor-presentation metrics by page.",
        "deck_sources": "Presentation/deck source registry with URLs and PIT dates.",
        "cc_docs": "Concall transcript document register.",
        "cc_items": "Concall guidance/KPI items with quotes and direction.",
        "bse_announcements": "BSE announcements with headline, category and dissemination time.",
        "ann": "BSE announcements with headline, category and dissemination time.",
        "events": "Unified company event ledger keyed by ISIN and known-at time.",
        "pib_releases": "PIB press releases with publication and posting times.",
        "policy_events": "Extracted policy events with stage, sectors and effective dates.",
        "financials": "Financial statement rows (legacy/derived).",
        "quarterly_financials": "Quarterly revenue/PAT/margin table with XBRL source path.",
        "annual_financials": "Annual revenue/EBITDA/PAT/leverage table by fiscal year.",
        "daily_price_delivery": "Daily price + delivery + technical indicators by symbol.",
        "shareholding": "Quarterly shareholding pattern (promoter/FII/DII/retail).",
    }
    if table in known:
        return known[table]
    return f"{db_key} table {table!r} (auto-described; inspect with sql() for detail)."


def _auto_key_columns(columns: list[str]) -> list[str]:
    lowered = {c.lower(): c for c in columns}
    picked = [lowered[k] for k in PREFERRED_KEYS if k in lowered]
    if not picked:
        picked = columns[:5]
    return picked[:8]


def _columns_duck(con, table: str) -> list[tuple[str, str]]:
    return [(str(c[0]), str(c[1])) for c in con.execute(f'describe "{table}"').fetchall()]


def _columns_sqlite(con, table: str) -> list[tuple[str, str]]:
    return [(str(c[1]), str(c[2] or "")) for c in con.execute(f'pragma table_info("{table}")').fetchall()]


def _date_coverage(kind: str, db_key: str, table: str, column: str) -> dict[str, Any] | None:
    known = KNOWN_COVERAGE.get((db_key, table))
    if known and known.get("column") == column:
        return dict(known)
    try:
        sql = f'select min("{column}"), max("{column}") from "{table}"'
        if kind == "duckdb":
            _, rows = _run_duck(sql, timeout=8.0)
            row = rows[0] if rows else None
        else:
            rows = _run_sqlite(db_key, sql, timeout=8.0)
            row = rows[0] if rows else None
        if not row or (row[0] is None and row[1] is None):
            return None
        to_text = lambda v: v.isoformat() if hasattr(v, "isoformat") else str(v)
        return {"column": column, "min": to_text(row[0]), "max": to_text(row[1])}
    except Exception:
        return None


def _rows_count(con, kind: str, db_key: str, table: str) -> tuple[int | None, bool]:
    if db_key in KNOWN_COUNTS and table in KNOWN_COUNTS[db_key]:
        return KNOWN_COUNTS[db_key][table], False
    try:
        if kind == "duckdb":
            return int(con.execute(f'select count(*) from "{table}"').fetchone()[0]), False
        if table in SLOW_TABLES:
            return None, True
        row = con.execute(f'select max(rowid) from "{table}"').fetchone()
        return (int(row[0]), True) if row and row[0] is not None else (None, True)
    except Exception:
        return None, True


def _introspect(refresh: bool = False) -> dict[str, Any]:
    """Read schemas (and, on refresh, counts/ranges) from the live files."""
    out: dict[str, Any] = {"generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
                           "databases": {}}
    for db_key, kind in DB_SPECS:
        path = db_path(db_key)
        entry: dict[str, Any] = {"path": str(path), "kind": kind, "tables": {}}
        try:
            if kind == "duckdb":
                con = connect_duck()
                names = [r[0] for r in con.execute(
                    "select table_name from information_schema.tables "
                    "where table_schema = 'main' order by table_name").fetchall()]
            else:
                if not path.exists():
                    raise FileNotFoundError(str(path))
                con = connect_sqlite(db_key)
                names = [r[0] for r in con.execute(
                    "select name from sqlite_master where type in ('table','view') order by name").fetchall()]
            for table in names:
                if _skip_table(table):
                    continue
                try:
                    cols = _columns_duck(con, table) if kind == "duckdb" else _columns_sqlite(con, table)
                except Exception as exc:
                    entry["tables"][table] = {"error": f"{type(exc).__name__}: {exc}"}
                    continue
                item: dict[str, Any] = {"columns": cols}
                known = KNOWN_COUNTS.get(db_key, {}).get(table)
                if known is not None:
                    item["rows"], item["rows_approx"] = known, False
                elif refresh:
                    rows, approx = _rows_count(con, kind, db_key, table)
                    item["rows"], item["rows_approx"] = rows, approx
                date_col = DATE_COLUMNS.get((db_key, table))
                if date_col and refresh:
                    coverage = _date_coverage(kind, db_key, table, date_col)
                    if coverage:
                        item["date_coverage"] = coverage
                entry["tables"][table] = item
        except Exception as exc:
            entry["error"] = f"{type(exc).__name__}: {exc}"
        out["databases"][db_key] = entry
    return out


def _load_cache(path: Path | None = None) -> dict[str, Any] | None:
    p = Path(path) if path else CACHE_PATH
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict) and data.get("databases"):
            return data
    except (OSError, ValueError):
        return None
    return None


def _save_cache(data: dict[str, Any], path: Path | None = None) -> None:
    p = Path(path) if path else CACHE_PATH
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, indent=1, sort_keys=False), encoding="utf-8")
    os.replace(tmp, p)


def _load_descriptions(path: Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else DESCRIPTIONS_PATH
    if not p.exists():
        return {}
    try:
        import yaml  # type: ignore
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}
    except Exception as exc:
        return {"_error": f"{type(exc).__name__}: {exc}"}


def _index_summary() -> list[dict[str, Any]]:
    """Vector-index map, including the qwen8b_ar done-row coverage caveat."""
    out: list[dict[str, Any]] = []
    try:
        import query_embed
        for name in ("nemotron8b", "qwen8b_ar"):
            try:
                out.append(query_embed.index_info(name))
            except Exception as exc:
                out.append({"key": name, "available": False, "error": str(exc)})
    except Exception as exc:
        out.append({"key": "query_embed", "available": False, "error": str(exc)})
    # Legacy local bge index, shown for context; not the primary search path.
    try:
        path = DATA / "vector_index"
        meta = json.loads((path / "chunk_index_meta.json").read_text(encoding="utf-8"))
        rows = int(meta.get("rows") or 0)
        source = int(meta.get("source_chunks_at_build") or 0)
        out.append({
            "name": "vector_index",
            "key": "bge_small",
            "path": str(path),
            "model": "bge-small-en-v1.5",
            "provider": "local-onnx",
            "dim": 384,
            "rows": rows,
            "done_rows": rows,
            "coverage_pct": 100.0,
            "dtype": meta.get("dtype") or "float32",
            "tiers": [0, 1, 2, 3],
            "available": (path / "chunk_ids.npy").exists(),
            "description": (
                f"Legacy local bge-small index, 384-d; built {meta.get('built_at', '?')} from "
                f"{source:,} chunks. Stale vs the current corpus and only used when the local "
                f"ONNX embedder exists; not the primary search path."
            ),
        })
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        pass
    return out


def _quarantine_summary() -> dict[str, Any]:
    keys = quarantine()
    materialized = {table: len(vals) for table, vals in sorted(keys.items()) if vals}
    return {
        "materialized_keys": materialized,
        "excluded_ar_doc_ids": sorted(quarantined_doc_ids()),
        "synthetic_isins": materialized.get("master_companies", 0),
        "demo_tables": sorted(DEMO_TABLES),
    }


def get_catalog(refresh: bool = False, cache_path: Path | None = None,
                descriptions_path: Path | None = None) -> dict[str, Any]:
    """Return the full data map, merging curated descriptions when present."""
    cache = None if refresh else _load_cache(cache_path)
    cache_missing = cache is None
    if cache is None:
        with core_lock:  # DuckDB connections are not thread-safe
            cache = _introspect(refresh=refresh)
        if refresh:
            try:
                _save_cache(cache, cache_path)
            except OSError:
                pass
    descriptions = _load_descriptions(descriptions_path)
    desc_error = descriptions.get("_error") if isinstance(descriptions, dict) else None
    databases = []
    for db_key, kind in DB_SPECS:
        cached = (cache.get("databases") or {}).get(db_key) or {}
        db_desc = descriptions.get(db_key) if isinstance(descriptions, dict) else None
        db_desc = db_desc if isinstance(db_desc, dict) else {}
        tables = []
        for table, info in (cached.get("tables") or {}).items():
            if not isinstance(info, dict) or info.get("error"):
                continue
            curated = (db_desc.get("tables") or {}).get(table) if isinstance(db_desc.get("tables"), dict) else None
            curated = curated if isinstance(curated, dict) else {}
            cols = [c[0] for c in info.get("columns", [])]
            row = {
                "name": table,
                "description": curated.get("description") or _auto_description(db_key, table),
                "key_columns": curated.get("key_columns") or _auto_key_columns(cols),
                "notes": curated.get("notes") or "",
                # key_columns is the model-facing map; full columns stay out of
                # the one-call payload (sql() can inspect any table on demand).
                "columns": [] if curated else cols,
                "column_count": len(cols),
                "rows": info.get("rows"),
                "rows_approx": bool(info.get("rows_approx", False)),
                "date_coverage": info.get("date_coverage"),
                "curated": bool(curated),
            }
            tables.append(row)
        databases.append({
            "key": db_key,
            "kind": kind,
            "path": cached.get("path") or str(db_path(db_key)),
            "description": db_desc.get("description") or DB_DESCRIPTIONS.get(db_key, ""),
            "table_count": len(tables),
            "tables": tables,
        })
    curated_count = sum(1 for db in databases for t in db["tables"] if t["curated"])
    return {
        "snapshot": snapshot_path().name,
        "generated_at": cache.get("generated_at"),
        "cache_missing": cache_missing,
        "databases": databases,
        "indexes": _index_summary(),
        "quarantine": _quarantine_summary(),
        "descriptions": {
            "path": str(descriptions_path or DESCRIPTIONS_PATH),
            "loaded": bool(descriptions) and not desc_error,
            "curated_tables": curated_count,
            "error": desc_error,
        },
        "provenance": {
            "sources": "information_schema / sqlite_master introspection + catalog_descriptions.yaml",
            "snapshot": str(snapshot_path()),
            "read_only": True,
            "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "large_table_counts": "measured 2026-10-24; other rows are MAX(rowid), rows_approx",
        },
    }


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Build/refresh the reality-data catalog cache.")
    ap.add_argument("--refresh", action="store_true", help="re-introspect the live databases")
    ap.add_argument("--print", action="store_true", help="print the catalog instead of writing only the cache")
    args = ap.parse_args(argv)
    started = time.time()
    if not args.refresh:
        print(f"cache: {CACHE_PATH} exists={CACHE_PATH.exists()}")
        return 0
    data = _introspect(refresh=True)
    _save_cache(data)
    elapsed = round(time.time() - started, 1)
    print(f"wrote {CACHE_PATH} in {elapsed}s: "
          f"{sum(len(v.get('tables', {})) for v in data['databases'].values())} tables")
    if args.print:
        print(json.dumps(get_catalog(descriptions_path=DESCRIPTIONS_PATH), indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
