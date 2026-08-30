#!/usr/bin/env python3
"""
Worktree lane DB merger for Reality Engine.

Merges one lane DB back into the main DB.
- funda mode: master_companies, quarterly_financials, annual_financials, company_forensic_health
  keyed on business keys (isin etc.), never on rowid.
- filings mode: corporate_documents (UPDATE download state), raw_documents (INSERT by sha),
  document_chunks (INSERT with remapped doc_id).

Column discovery via PRAGMA table_info for BOTH DBs; column list = intersection (main order).
Missing required table in either DB -> fail that table, continue, exit 1 if any failed.
ONE transaction (BEGIN IMMEDIATE / COMMIT / ROLLBACK). --dry-run: pure SELECT counts.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Any

FUNDA_TABLES = ["master_companies", "quarterly_financials", "annual_financials", "company_forensic_health"]
FILINGS_TABLES = ["corporate_documents", "raw_documents", "document_chunks"]

# Match keys per requirement
FUNDA_KEYS: Dict[str, List[str]] = {
    "master_companies": ["isin"],
    "quarterly_financials": ["isin", "quarter_end_date"],
    "annual_financials": ["isin", "fiscal_year"],
    "company_forensic_health": ["isin", "fiscal_year"],
}

# Columns to exclude from INSERT when they are INTEGER PRIMARY KEY autoincrement
# (avoid colliding lane ids with main ids). Keep business-key PKs like isin TEXT.
EXCLUDE_PK_COLS = {
    "quarterly_financials": {"id"},
    "annual_financials": {"id"},
    "raw_documents": {"doc_id"},
    "document_chunks": {"chunk_id"},
    # corporate_documents also has id PK but filings mode uses UPDATE not INSERT, so not needed
}


def _table_exists(conn: sqlite3.Connection, db: str, table: str) -> bool:
    cur = conn.execute(f'SELECT name FROM "{db}".sqlite_master WHERE type="table" AND name=?', (table,))
    return cur.fetchone() is not None


def _get_columns(conn: sqlite3.Connection, db: str, table: str) -> List[str] | None:
    if not _table_exists(conn, db, table):
        return None
    # PRAGMA database.table_info
    try:
        rows = conn.execute(f'PRAGMA "{db}".table_info("{table}")').fetchall()
    except Exception:
        # fallback without quoting db
        rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    if not rows:
        return None
    # rows: cid, name, type, notnull, dflt_value, pk
    return [r[1] for r in rows]


def _get_table_info_rows(conn: sqlite3.Connection, db: str, table: str):
    try:
        rows = conn.execute(f'PRAGMA "{db}".table_info("{table}")').fetchall()
    except Exception:
        rows = conn.execute(f"PRAGMA table_info('{table}')").fetchall()
    return rows


def _is_sqlite_version_ge(major: int, minor: int, patch: int = 0) -> bool:
    ver = sqlite3.sqlite_version.split(".")
    try:
        maj, mi, pa = int(ver[0]), int(ver[1]), int(ver[2]) if len(ver) > 2 else 0
    except Exception:
        return False
    return (maj, mi, pa) >= (major, minor, patch)


def _intersect_cols(main_cols: List[str], lane_cols: List[str]) -> List[str]:
    return [c for c in main_cols if c in lane_cols]


def _filtered_insert_cols(table: str, intersect: List[str], main_info_rows) -> List[str]:
    # Exclude PK cols that are INTEGER autoincrement for insert
    exclude = EXCLUDE_PK_COLS.get(table, set())
    # Only exclude if that column is actually a PK integer in main schema
    # Build pk set from pragma
    pk_int_cols = set()
    for cid, name, typ, notnull, dflt, pk in main_info_rows:
        if pk == 1 and name in exclude and typ is not None and "INT" in typ.upper():
            pk_int_cols.add(name)
        elif pk == 1 and name in exclude:
            # also exclude if type is INTEGER even if typ is None or different
            # fallback: if name is in exclude and it's a PK, exclude it
            # But keep isin TEXT PK, so we check INT
            if typ and "INT" in typ.upper():
                pk_int_cols.add(name)
            elif name in {"id", "doc_id", "chunk_id"}:
                # For these specific names, treat any PK as excludable if table is in EXCLUDE list
                # This handles case where pragma type is exactly INTEGER
                pk_int_cols.add(name)
    # Actually simpler: if table in EXCLUDE_PK_COLS, exclude those names regardless of type check,
    # but keep isin. Since EXCLUDE_PK_COLS only contains id/doc_id/chunk_id, it's safe to exclude.
    # We'll just exclude them if present in intersect.
    # To respect the detailed pk check, we use pk_int_cols if populated, else fallback to exclude set.
    if pk_int_cols:
        return [c for c in intersect if c not in pk_int_cols]
    # Fallback: if we detected exclude set but pk check missed due to typ None, still exclude if name in exclude and table in EXCLUDE list
    # Check if any of the exclude names is a PK
    pk_names = {name for _, name, _, _, _, pk in main_info_rows if pk == 1}
    to_exclude = {n for n in exclude if n in pk_names}
    return [c for c in intersect if c not in to_exclude]


def merge(main_path: str | Path, lane_path: str | Path, mode: str, dry_run: bool = False) -> Dict[str, Dict[str, Any]]:
    """
    Merge lane DB into main DB.

    Args:
        main_path: path to main DB file
        lane_path: path to lane DB file
        mode: "funda" or "filings"
        dry_run: if True, only SELECT counts, no writes

    Returns:
        dict mapping table -> {inserted, updated, skipped, failed, error/message}
    """
    main_path = Path(main_path)
    lane_path = Path(lane_path)
    if mode not in ("funda", "filings"):
        raise ValueError(f"mode must be funda or filings, got {mode}")

    tables = FUNDA_TABLES if mode == "funda" else FILINGS_TABLES

    results: Dict[str, Dict[str, Any]] = {}

    # Open main DB read-write
    main_uri = f"file:{main_path.resolve().as_posix()}?mode=rw"
    # Use timeout 10 sec, isolation_level None for manual transaction
    conn = sqlite3.connect(main_uri, uri=True, timeout=10.0, isolation_level=None, check_same_thread=False)
    conn.execute("PRAGMA busy_timeout=10000;")
    conn.execute("PRAGMA foreign_keys=ON;")
    # Attach lane as read-only
    lane_uri = f"file:{lane_path.resolve().as_posix()}?mode=ro"
    lane_uri_esc = lane_uri.replace("'", "''")
    try:
        conn.execute(f"ATTACH DATABASE '{lane_uri_esc}' AS lane;")
    except Exception as e:
        # Attach failed
        conn.close()
        raise RuntimeError(f"Failed to attach lane DB {lane_path}: {e}") from e

    # Verify attach
    # If lane DB file does not exist or is not readable, ATTACH may still succeed but tables missing will be caught later.

    any_failed = False
    transaction_started = False
    exception_occurred = False

    try:
        if not dry_run:
            conn.execute("BEGIN IMMEDIATE;")
            transaction_started = True

        for table in tables:
            entry: Dict[str, Any] = {"inserted": 0, "updated": 0, "skipped": 0, "failed": False, "error": None}
            try:
                main_exists = _table_exists(conn, "main", table)
                lane_exists = _table_exists(conn, "lane", table)
                if not main_exists or not lane_exists:
                    missing = []
                    if not main_exists:
                        missing.append(f"main.{table}")
                    if not lane_exists:
                        missing.append(f"lane.{table}")
                    entry["failed"] = True
                    entry["error"] = f"Missing required table: {', '.join(missing)}"
                    any_failed = True
                    results[table] = entry
                    continue

                main_cols = _get_columns(conn, "main", table)
                lane_cols = _get_columns(conn, "lane", table)
                if main_cols is None or lane_cols is None:
                    entry["failed"] = True
                    entry["error"] = f"Could not discover columns for {table} (main or lane missing)"
                    any_failed = True
                    results[table] = entry
                    continue

                intersect = _intersect_cols(main_cols, lane_cols)
                if not intersect:
                    entry["failed"] = True
                    entry["error"] = f"No common columns for {table}: main {main_cols} lane {lane_cols}"
                    any_failed = True
                    results[table] = entry
                    continue

                main_info = _get_table_info_rows(conn, "main", table)

                if mode == "funda":
                    # Funda logic
                    keys = FUNDA_KEYS.get(table, [])
                    if not keys:
                        entry["failed"] = True
                        entry["error"] = f"No match keys defined for {table}"
                        any_failed = True
                        results[table] = entry
                        continue
                    # Validate keys are in intersect (or at least in both DBs)
                    missing_keys = [k for k in keys if k not in intersect]
                    if missing_keys:
                        entry["failed"] = True
                        entry["error"] = f"Match key(s) {missing_keys} not in common columns for {table}: {intersect}"
                        any_failed = True
                        results[table] = entry
                        continue

                    # Determine insert cols (exclude PK id where appropriate)
                    insert_cols = _filtered_insert_cols(table, intersect, main_info)
                    if not insert_cols:
                        entry["failed"] = True
                        entry["error"] = f"No insert columns after filtering PK for {table}"
                        any_failed = True
                        results[table] = entry
                        continue

                    # Ensure keys are still in insert_cols? For funda, keys must be inserted; if key was filtered out (shouldn't happen), add back
                    # But we filtered only id/doc_id/chunk_id, keys are isin etc., so fine.

                    # Total lane rows
                    total = conn.execute(f'SELECT COUNT(*) FROM "lane"."{table}"').fetchone()[0]

                    # Build IS comparisons
                    key_match = " AND ".join(f'm."{k}" IS l."{k}"' for k in keys)
                    col_list = ", ".join(f'"{c}"' for c in insert_cols)
                    select_list = ", ".join(f'l."{c}"' for c in insert_cols)

                    # Count would-be inserted
                    count_sql = f'SELECT COUNT(*) FROM "lane"."{table}" l WHERE NOT EXISTS (SELECT 1 FROM "main"."{table}" m WHERE {key_match})'
                    try:
                        would_inserted = conn.execute(count_sql).fetchone()[0]
                    except Exception as e:
                        entry["failed"] = True
                        entry["error"] = f"Count query failed for {table}: {e}"
                        any_failed = True
                        results[table] = entry
                        continue

                    skipped = total - would_inserted
                    if dry_run:
                        entry["inserted"] = would_inserted
                        entry["skipped"] = skipped
                        entry["updated"] = 0
                    else:
                        # Execute insert
                        insert_sql = f'INSERT INTO "main"."{table}" ({col_list}) SELECT {select_list} FROM "lane"."{table}" l WHERE NOT EXISTS (SELECT 1 FROM "main"."{table}" m WHERE {key_match})'
                        try:
                            conn.execute(insert_sql)
                            # Use changes() for accurate count
                            inserted = conn.execute("SELECT changes()").fetchone()[0]
                        except Exception as e:
                            # Rollback will be handled outside; mark failed and trigger rollback
                            entry["failed"] = True
                            entry["error"] = f"Insert failed for {table}: {e}"
                            any_failed = True
                            exception_occurred = True
                            results[table] = entry
                            # Break out to rollback transaction
                            break
                        entry["inserted"] = inserted
                        entry["skipped"] = total - inserted
                        entry["updated"] = 0

                else:  # filings mode
                    if table == "corporate_documents":
                        # UPDATE logic
                        # Need id column and is_processed and the four update cols
                        # Check required columns exist
                        required_for_update = ["id", "is_processed"]
                        missing_req = [c for c in required_for_update if c not in intersect and c not in main_cols]
                        # Actually check both DBs have id and is_processed
                        if "id" not in main_cols or "id" not in lane_cols:
                            entry["failed"] = True
                            entry["error"] = f"corporate_documents missing id column (main {main_cols}, lane {lane_cols})"
                            any_failed = True
                            results[table] = entry
                            continue
                        if "is_processed" not in main_cols or "is_processed" not in lane_cols:
                            entry["failed"] = True
                            entry["error"] = "corporate_documents missing is_processed column"
                            any_failed = True
                            results[table] = entry
                            continue

                        # Determine which of the 4 cols are present in both
                        desired = ["local_file_path", "sha256_hash", "file_size_bytes", "is_processed"]
                        update_cols = [c for c in desired if c in main_cols and c in lane_cols]
                        if not update_cols:
                            entry["failed"] = True
                            entry["error"] = f"No updatable columns present for corporate_documents: {intersect}"
                            any_failed = True
                            results[table] = entry
                            continue

                        # total lane processed rows
                        try:
                            total_processed = conn.execute('SELECT COUNT(*) FROM "lane"."corporate_documents" WHERE is_processed=1').fetchone()[0]
                        except Exception as e:
                            entry["failed"] = True
                            entry["error"] = f"Count lane processed failed: {e}"
                            any_failed = True
                            results[table] = entry
                            continue

                        # Would-be updated: count of matching ids where lane is_processed=1
                        try:
                            would_updated = conn.execute('SELECT COUNT(*) FROM "main"."corporate_documents" m JOIN "lane"."corporate_documents" l ON m.id = l.id WHERE l.is_processed=1').fetchone()[0]
                        except Exception as e:
                            entry["failed"] = True
                            entry["error"] = f"Would-be updated count failed: {e}"
                            any_failed = True
                            results[table] = entry
                            continue

                        if dry_run:
                            entry["updated"] = would_updated
                            entry["inserted"] = 0
                            entry["skipped"] = total_processed - would_updated
                        else:
                            # Choose UPDATE strategy based on sqlite version
                            try:
                                if _is_sqlite_version_ge(3, 33, 0):
                                    set_clause = ", ".join(f'"{c}" = l."{c}"' for c in update_cols)
                                    # Need to quote main table correctly
                                    update_sql = f'UPDATE "main"."corporate_documents" SET {set_clause} FROM "lane"."corporate_documents" AS l WHERE "main"."corporate_documents".id = l.id AND l.is_processed=1'
                                    # SQLite docs: UPDATE main.corporate_documents SET ... FROM lane.corporate_documents AS l WHERE ...
                                    # Ensure alias works; alternative without alias for target
                                    # Try alternative syntax if alias fails
                                    try:
                                        conn.execute(update_sql)
                                    except Exception as inner:
                                        # Fallback to no-alias target syntax
                                        # Use UPDATE main.corporate_documents SET ... FROM ...
                                        fallback_set = ", ".join(f'"{c}" = l."{c}"' for c in update_cols)
                                        fallback_sql = f'UPDATE "main"."corporate_documents" SET {fallback_set} FROM "lane"."corporate_documents" AS l WHERE "main"."corporate_documents".id = l.id AND l.is_processed=1'
                                        # The above is same; try correlated subquery fallback
                                        raise inner
                                else:
                                    raise RuntimeError("fallback to correlated")
                            except Exception:
                                # Correlated subquery fallback
                                # Build SET with subqueries
                                set_parts = []
                                for c in update_cols:
                                    set_parts.append(f'"{c}" = (SELECT l."{c}" FROM "lane"."corporate_documents" l WHERE l.id = "main"."corporate_documents".id AND l.is_processed=1)')
                                set_clause_corr = ", ".join(set_parts)
                                where_exists = 'WHERE EXISTS (SELECT 1 FROM "lane"."corporate_documents" l WHERE l.id = "main"."corporate_documents".id AND l.is_processed=1)'
                                update_sql_corr = f'UPDATE "main"."corporate_documents" SET {set_clause_corr} {where_exists}'
                                conn.execute(update_sql_corr)

                            updated = conn.execute("SELECT changes()").fetchone()[0]
                            entry["updated"] = updated
                            entry["inserted"] = 0
                            entry["skipped"] = total_processed - updated

                    elif table == "raw_documents":
                        # INSERT by sha
                        # Check sha column exists
                        if "sha256_hash" not in main_cols or "sha256_hash" not in lane_cols:
                            entry["failed"] = True
                            entry["error"] = "raw_documents missing sha256_hash column"
                            any_failed = True
                            results[table] = entry
                            continue

                        intersect = _intersect_cols(main_cols, lane_cols)
                        main_info = _get_table_info_rows(conn, "main", table)
                        insert_cols = _filtered_insert_cols(table, intersect, main_info)
                        if not insert_cols:
                            entry["failed"] = True
                            entry["error"] = "No insert cols for raw_documents after filtering"
                            any_failed = True
                            results[table] = entry
                            continue

                        # Counts
                        try:
                            total_lane = conn.execute('SELECT COUNT(*) FROM "lane"."raw_documents"').fetchone()[0]
                            total_null = conn.execute('SELECT COUNT(*) FROM "lane"."raw_documents" WHERE sha256_hash IS NULL').fetchone()[0]
                            # Count existing sha in main
                            existing = conn.execute('SELECT COUNT(*) FROM "lane"."raw_documents" l WHERE l.sha256_hash IS NOT NULL AND EXISTS (SELECT 1 FROM "main"."raw_documents" m WHERE m.sha256_hash = l.sha256_hash)').fetchone()[0]
                            skipped = total_null + existing
                            would_inserted = total_lane - skipped
                        except Exception as e:
                            entry["failed"] = True
                            entry["error"] = f"Count failed for raw_documents: {e}"
                            any_failed = True
                            results[table] = entry
                            continue

                        if dry_run:
                            entry["inserted"] = would_inserted
                            entry["skipped"] = skipped
                            entry["updated"] = 0
                        else:
                            col_list = ", ".join(f'"{c}"' for c in insert_cols)
                            select_list = ", ".join(f'l."{c}"' for c in insert_cols)
                            insert_sql = f'INSERT INTO "main"."raw_documents" ({col_list}) SELECT {select_list} FROM "lane"."raw_documents" l WHERE l.sha256_hash IS NOT NULL AND NOT EXISTS (SELECT 1 FROM "main"."raw_documents" m WHERE m.sha256_hash = l.sha256_hash)'
                            try:
                                conn.execute(insert_sql)
                                inserted = conn.execute("SELECT changes()").fetchone()[0]
                            except Exception as e:
                                entry["failed"] = True
                                entry["error"] = f"Insert failed for raw_documents: {e}"
                                any_failed = True
                                exception_occurred = True
                                results[table] = entry
                                break
                            entry["inserted"] = inserted
                            # Recalculate skipped as total - inserted (should match previous)
                            entry["skipped"] = total_lane - inserted
                            entry["updated"] = 0

                    elif table == "document_chunks":
                        # INSERT with remapped doc_id
                        if "doc_id" not in main_cols or "doc_id" not in lane_cols or "chunk_index" not in main_cols or "chunk_index" not in lane_cols:
                            entry["failed"] = True
                            entry["error"] = "document_chunks missing doc_id or chunk_index"
                            any_failed = True
                            results[table] = entry
                            continue

                        intersect = _intersect_cols(main_cols, lane_cols)
                        main_info = _get_table_info_rows(conn, "main", table)
                        insert_cols = _filtered_insert_cols(table, intersect, main_info)
                        if not insert_cols:
                            entry["failed"] = True
                            entry["error"] = "No insert cols for document_chunks after filtering"
                            any_failed = True
                            results[table] = entry
                            continue
                        # Ensure doc_id and chunk_index are in insert_cols (they should be, unless filtered)
                        # doc_id is excluded? No, chunk_id excluded, doc_id kept. So ensure doc_id present
                        # If doc_id not in insert_cols due to filtering, add it? But we filtered only chunk_id, so doc_id remains if present.

                        # Total lane chunks
                        try:
                            total = conn.execute('SELECT COUNT(*) FROM "lane"."document_chunks"').fetchone()[0]
                        except Exception as e:
                            entry["failed"] = True
                            entry["error"] = f"Count lane chunks failed: {e}"
                            any_failed = True
                            results[table] = entry
                            continue

                        if dry_run:
                            # Compute inserted as described for dry_run
                            try:
                                # Count new sha chunks
                                new_sha_cnt = conn.execute('''
                                    SELECT COUNT(*) FROM "lane"."document_chunks" l
                                    JOIN "lane"."raw_documents" lr ON lr.doc_id = l.doc_id
                                    LEFT JOIN "main"."raw_documents" mr ON mr.sha256_hash = lr.sha256_hash
                                    WHERE lr.sha256_hash IS NOT NULL AND mr.sha256_hash IS NULL
                                ''').fetchone()[0]
                                # Count existing sha not duplicate
                                existing_not_dup = conn.execute('''
                                    SELECT COUNT(*) FROM "lane"."document_chunks" l
                                    JOIN "lane"."raw_documents" lr ON lr.doc_id = l.doc_id
                                    JOIN "main"."raw_documents" mr ON mr.sha256_hash = lr.sha256_hash
                                    LEFT JOIN "main"."document_chunks" mc ON mc.doc_id = mr.doc_id AND mc.chunk_index = l.chunk_index
                                    WHERE mc.chunk_id IS NULL
                                ''').fetchone()[0]
                                would_inserted = new_sha_cnt + existing_not_dup
                                skipped = total - would_inserted
                            except Exception as e:
                                # Fallback simple: assume no mapping counts as skipped? Try simpler query without lane raw join
                                try:
                                    # If lane raw not available, count via _temp mapping simulation?
                                    # Just set would_inserted 0
                                    would_inserted = 0
                                    skipped = total
                                except Exception:
                                    would_inserted = 0
                                    skipped = total
                            entry["inserted"] = would_inserted
                            entry["skipped"] = skipped
                            entry["updated"] = 0
                        else:
                            # Non-dry-run: need to handle mapping temp table
                            # Create temp mapping after raw_documents insert (which already happened earlier in loop order)
                            # Ensure raw_documents table processing happened before document_chunks (it does, as tables order is corporate, raw, chunks)
                            # So at this point raw_documents already merged, mapping can be built
                            try:
                                conn.execute("DROP TABLE IF EXISTS _doc_map")
                                conn.execute("CREATE TEMP TABLE _doc_map(lane_doc_id INTEGER PRIMARY KEY, main_doc_id INTEGER)")
                                conn.execute('INSERT INTO _doc_map SELECT l.doc_id, m.doc_id FROM "lane"."raw_documents" l JOIN "main"."raw_documents" m ON m.sha256_hash = l.sha256_hash WHERE l.sha256_hash IS NOT NULL')
                            except Exception as e:
                                entry["failed"] = True
                                entry["error"] = f"Failed to build doc_id mapping: {e}"
                                any_failed = True
                                results[table] = entry
                                continue

                            # Build insert
                            col_list = ", ".join(f'"{c}"' for c in insert_cols)
                            select_parts = []
                            for c in insert_cols:
                                if c == "doc_id":
                                    select_parts.append("map.main_doc_id")
                                else:
                                    select_parts.append(f'l."{c}"')
                            select_list = ", ".join(select_parts)

                            insert_sql = f'''
                                INSERT INTO "main"."document_chunks" ({col_list})
                                SELECT {select_list}
                                FROM "lane"."document_chunks" l
                                JOIN _doc_map map ON map.lane_doc_id = l.doc_id
                                WHERE NOT EXISTS (SELECT 1 FROM "main"."document_chunks" m WHERE m.doc_id = map.main_doc_id AND m.chunk_index = l.chunk_index)
                            '''
                            try:
                                conn.execute(insert_sql)
                                inserted = conn.execute("SELECT changes()").fetchone()[0]
                            except Exception as e:
                                entry["failed"] = True
                                entry["error"] = f"Insert failed for document_chunks: {e}"
                                any_failed = True
                                exception_occurred = True
                                results[table] = entry
                                break
                            entry["inserted"] = inserted
                            entry["skipped"] = total - inserted
                            entry["updated"] = 0
                            # Clean up temp table? Keep for potential reuse but drop
                            try:
                                conn.execute("DROP TABLE IF EXISTS _doc_map")
                            except Exception:
                                pass

                results[table] = entry

            except Exception as e:
                # Unexpected exception for this table
                entry["failed"] = True
                entry["error"] = str(e)
                any_failed = True
                exception_occurred = True
                results[table] = entry
                break

        # Handle transaction completion
        if not dry_run:
            if exception_occurred:
                try:
                    conn.execute("ROLLBACK;")
                except Exception:
                    pass
            else:
                try:
                    conn.execute("COMMIT;")
                except Exception as e:
                    # Commit failure -> rollback
                    try:
                        conn.execute("ROLLBACK;")
                    except Exception:
                        pass
                    # Mark all as failed?
                    for tbl in results:
                        if not results[tbl].get("failed"):
                            results[tbl]["failed"] = True
                            results[tbl]["error"] = f"Commit failed: {e}"
                    any_failed = True
            # For missing-table only failures (no exception_occurred), we still commit (already committed)
            # But we need to ensure COMMIT was already done; above handles.

    finally:
        try:
            conn.execute("DETACH DATABASE lane;")
        except Exception:
            pass
        conn.close()

    return results


def _print_summary(results: Dict[str, Dict[str, Any]]):
    print("\n=== Merge Summary ===")
    for table, stats in results.items():
        inserted = stats.get("inserted", 0)
        updated = stats.get("updated", 0)
        skipped = stats.get("skipped", 0)
        failed = stats.get("failed", False)
        err = stats.get("error")
        status = "FAILED" if failed else "OK"
        line = f"{table}: inserted={inserted} updated={updated} skipped={skipped} failed={failed} [{status}]"
        if err:
            line += f" error={err}"
        print(line)
    failed_any = any(v.get("failed") for v in results.values())
    print(f"\nOverall: {'PARTIAL/FAILED' if failed_any else 'SUCCESS'}")
    print(f"sqlite_version={sqlite3.sqlite_version}")


def main():
    parser = argparse.ArgumentParser(description="Merge lane DB into main DB")
    parser.add_argument("--main", required=True, help="Path to main DB")
    parser.add_argument("--lane", required=True, help="Path to lane DB")
    parser.add_argument("--mode", required=True, choices=["funda", "filings"], help="Merge mode")
    parser.add_argument("--dry-run", action="store_true", help="Dry run, no writes")
    args = parser.parse_args()

    try:
        results = merge(args.main, args.lane, args.mode, dry_run=args.dry_run)
    except Exception as e:
        print(f"Merge failed with exception: {e}", file=sys.stderr)
        sys.exit(1)

    _print_summary(results)

    # Exit code 1 if any failed, else 0
    any_failed = any(v.get("failed") for v in results.values())
    # Also check for partial? If any table failed, exit 1
    sys.exit(1 if any_failed else 0)


if __name__ == "__main__":
    main()
