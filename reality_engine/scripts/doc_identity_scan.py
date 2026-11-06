"""Identity scan over ``corporate_documents`` (T-093): read-only, bounded, one verdict per document.

Every document gets a ``doc_identity`` verdict (company, fiscal year, type, date) from its first pages and its filing
record: no model call, no store write.  A row whose file is only in the Drive archive is ``on_drive`` unless
``--fetch-drive`` asks for a bounded sample; a row in neither place is ``not_held``.

    python -m reality_engine.scripts.doc_identity_scan --symbols KEC,INFY --processes 6
    python -m reality_engine.scripts.doc_identity_scan --limit 2000 --processes 6 --drive none
    python -m reality_engine.scripts.doc_identity_scan --symbols KEC --fetch-drive 10

``--processes N`` runs N shard processes (rows where ``id % N = i``) and merges their CSVs; the shards write files and
inherit stdout, because this sandbox denies the named pipes ``multiprocessing.Pool`` needs.  Writes a Markdown report
and a CSV under ``--report-dir`` (default ``D:\\RealityEngine\\reports``).  ``--identity-db`` optionally appends the
verdict rows to the ``doc_identity`` table of a pilot build database (never the main store).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import doc_identity
from reality_engine.pilot3.doc_identity import DRIVE_FETCH_LIMIT, FileIndex, check_row, main_store

COLUMNS = ("id", "symbol", "isin", "doc_type", "bse_subcat", "doc_date", "created_at", "bse_dissem_ts",
           "publication_date", "pit_source", "local_file_path", "sha256_hash")
CSV_FIELDS = ("id", "symbol", "doc_type", "bse_subcat", "doc_date", "date", "filing_date", "file_where", "verdict",
              "company", "company_reason", "fiscal_year", "fiscal_year_reason", "type", "type_reason", "text_chars",
              "linked_url", "duplicate_of", "sha256", "sample_weight")
DRIVE_CACHE = Path(".tmp") / "doc_identity_drive_index.json"


def _select_sql(symbols: tuple[str, ...], limit: int | None, doc_types: tuple[str, ...] = (),
                subcats: tuple[str, ...] = ()) -> tuple[str, list]:
    sql = f"SELECT {', '.join(COLUMNS)} FROM corporate_documents"
    params: list = []
    where = []
    if symbols:
        where.append(f"symbol IN ({','.join('?' * len(symbols))})")
        params += list(symbols)
    if doc_types:
        where.append(f"doc_type IN ({','.join('?' * len(doc_types))})")
        params += list(doc_types)
    if subcats:
        where.append(f"bse_subcat IN ({','.join('?' * len(subcats))})")
        params += list(subcats)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY id"
    if limit:
        sql += " LIMIT ?"
        params.append(limit)
    return sql, params


def rows_for(conn: sqlite3.Connection, symbols: tuple[str, ...], limit: int | None, ids: list[int] | None = None,
             doc_types: tuple[str, ...] = (), subcats: tuple[str, ...] = ()):
    """The selected rows; ``ids`` is a shard's own list (one bounded ``IN`` query per 500)."""
    if ids is not None:
        for i in range(0, len(ids), 500):
            batch = ids[i:i + 500]
            for row in conn.execute(
                    f"SELECT {', '.join(COLUMNS)} FROM corporate_documents WHERE id IN ({','.join('?' * len(batch))})"
                    " ORDER BY id", batch):
                yield {name: row[name] for name in COLUMNS}
        return
    sql, params = _select_sql(symbols, limit, doc_types, subcats)
    for row in conn.execute(sql, params):
        yield {name: row[name] for name in COLUMNS}


def selected_ids(conn: sqlite3.Connection, symbols: tuple[str, ...], limit: int | None,
                 doc_types: tuple[str, ...] = (), subcats: tuple[str, ...] = ()) -> list[int]:
    sql, params = _select_sql(symbols, limit, doc_types, subcats)
    return [r[0] for r in conn.execute(sql.replace(f"SELECT {', '.join(COLUMNS)}", "SELECT id"), params)]


def stratified_sample(conn: sqlite3.Connection, symbols: tuple[str, ...], doc_types: tuple[str, ...],
                      subcats: tuple[str, ...], n: int, seed: int) -> tuple[list[int], dict[str, float]]:
    """``n`` random documents allocated by ``doc_type`` in proportion to the table; ``{doc_type: weight}``."""
    import random
    where, params, sql = [], [], f"SELECT {', '.join(COLUMNS)} FROM corporate_documents"
    if symbols:
        where.append(f"symbol IN ({','.join('?' * len(symbols))})")
        params += list(symbols)
    if doc_types:
        where.append(f"doc_type IN ({','.join('?' * len(doc_types))})")
        params += list(doc_types)
    if subcats:
        where.append(f"bse_subcat IN ({','.join('?' * len(subcats))})")
        params += list(subcats)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    counts = conn.execute(sql.replace(f"SELECT {', '.join(COLUMNS)}", "SELECT doc_type, COUNT(*)") + clause +
                          " GROUP BY doc_type", params).fetchall()
    total = sum(c for _, c in counts) or 1
    ids: list[int] = []
    weights: dict[str, float] = {}
    pool_sql = sql.replace(f"SELECT {', '.join(COLUMNS)}", "SELECT id") + clause + \
        (" AND " if where else " WHERE ") + "doc_type=? ORDER BY id"
    for doc_type, count in counts:
        quota = max(1, round(n * count / total))
        pool = [r[0] for r in conn.execute(pool_sql, [*params, doc_type])]
        picked = random.Random(f"{seed}:{doc_type}").sample(pool, min(quota, len(pool)))
        ids.extend(picked)
        weights[doc_type] = len(pool) / len(picked) if picked else 0.0
    return ids, weights


def annotate(results: list[dict], conn: sqlite3.Connection, weights: dict[str, float]) -> None:
    """``duplicate_of`` (lowest id of the same company + sha) and the sample weight, in place."""
    hashes = sorted({r["sha256"].lower() for r in results if r["sha256"]})
    first: dict[tuple[str, str], int] = {}
    for i in range(0, len(hashes), 500):
        batch = hashes[i:i + 500]
        for symbol, sha, min_id in conn.execute(
                "SELECT symbol, lower(sha256_hash), MIN(id) FROM corporate_documents WHERE lower(sha256_hash) IN "
                f"({','.join('?' * len(batch))}) GROUP BY symbol, lower(sha256_hash)", batch):
            first[(symbol, sha)] = min_id
    for r in results:
        r["sample_weight"] = round(weights.get(r["doc_type"], 1.0), 4)
        sha = (r["sha256"] or "").lower()
        if sha:
            min_id = first.get((r["symbol"], sha))
            r["duplicate_of"] = min_id if min_id and min_id != r["id"] else None


def duplicate_counts(conn: sqlite3.Connection) -> dict:
    """Rows that share a sha256 with another row of the same company, by type; cross-symbol hashes stay separate."""
    by_type = dict(conn.execute(
        "WITH f AS (SELECT symbol, lower(sha256_hash) sha, MIN(id) first_id FROM corporate_documents "
        "WHERE sha256_hash IS NOT NULL GROUP BY symbol, lower(sha256_hash)) "
        "SELECT d.doc_type, COUNT(*) FROM corporate_documents d JOIN f ON d.symbol=f.symbol AND "
        "lower(d.sha256_hash)=f.sha WHERE d.id<>f.first_id GROUP BY d.doc_type"))
    groups = conn.execute(
        "SELECT COUNT(*) FROM (SELECT symbol, lower(sha256_hash) FROM corporate_documents WHERE sha256_hash IS NOT NULL "
        "GROUP BY symbol, lower(sha256_hash) HAVING COUNT(*)>1)").fetchone()[0]
    cross = conn.execute(
        "SELECT COUNT(*) FROM (SELECT lower(sha256_hash) FROM corporate_documents WHERE sha256_hash IS NOT NULL "
        "GROUP BY lower(sha256_hash) HAVING COUNT(DISTINCT symbol)>1)").fetchone()[0]
    return {"by_type": by_type, "groups": groups, "cross_symbol_hashes": cross}


def cover_letter_stats(results: list[dict]) -> dict:
    rows = [r for r in results if str(r.get("type_reason") or "").startswith("cover_letter")]
    return {"rows": len(rows), "projected": round(sum(r.get("sample_weight", 1.0) for r in rows), 1),
            "with_link": sum(1 for r in rows if r.get("linked_url")),
            "by_type": dict(Counter(r["doc_type"] for r in rows)),
            "companies": sorted({r["symbol"] for r in rows})}


def drive_size(index: FileIndex, results: list[dict]) -> dict:
    """Projected bytes of the on-drive sample (index sizes); the missing rows' size is unknown."""
    sizes = []
    for r in results:
        if r["file_where"] != "drive":
            continue
        entry = index.drive_files.get((r.get("extra") or {}).get("remote") or "")
        if entry and entry.get("size"):
            sizes.append((int(entry["size"]), r.get("sample_weight", 1.0), r["doc_type"]))
    total = sum(size * weight for size, weight, _ in sizes)
    projected = sum(w for _, w, _ in sizes)
    per_type = defaultdict(float)
    for size, weight, doc_type in sizes:
        per_type[doc_type] += size * weight
    return {"observed": len(sizes), "projected_files": round(projected, 1),
            "projected_bytes": int(total), "avg_mb": round(total / 1e6 / projected, 2) if projected else 0,
            "by_type_bytes": {k: int(v) for k, v in per_type.items()}}


def run_rows(conn: sqlite3.Connection, rows: list[dict], index: FileIndex, log=print) -> list[dict]:
    results = []
    started = time.time()
    for i, row in enumerate(rows, 1):
        result = check_row(conn, row, index=index)
        results.append({"id": row["id"], "symbol": row["symbol"], "doc_type": row["doc_type"],
                        "bse_subcat": row["bse_subcat"] or "", "doc_date": row["doc_date"] or "",
                        "sha256": row["sha256_hash"] or "", "duplicate_of": None, "sample_weight": 1.0,
                        **result.row(), "file_where": result.extra.get("where", ""), "extra": result.extra})
        if i % 100 == 0:
            log(f"{i}/{len(rows)}")
    log(f"scanned {len(rows)} in {round(time.time() - started, 1)} s")
    return results


def drive_folders(rows: list[dict], cap: int = 200) -> list[str]:
    """The Drive folders the stored paths of these rows point at, deduplicated (listing only, never a download)."""
    from reality_engine.toolbelt.drive_fetch import local_to_remote
    folders, seen = [], set()
    for row in rows:
        if not row["local_file_path"]:
            continue
        try:
            rel = local_to_remote(row["local_file_path"])
        except ValueError:
            continue
        folder = rel.rsplit("/", 1)[0] if "/" in rel else ""
        if folder and folder not in seen:
            seen.add(folder)
            folders.append(folder)
    return folders[:cap]


def _alternate_folder(folder: str) -> str:
    """``pdfs/X`` -> ``D_pdfs/X`` and back: the two stored-path families of the same archive."""
    if folder.startswith("pdfs/"):
        return "D_pdfs/" + folder[len("pdfs/"):]
    if folder.startswith("D_pdfs/"):
        return "pdfs/" + folder[len("D_pdfs/"):]
    return ""


def warm_drive(index: FileIndex, rows: list[dict], log=print, refresh: bool = False) -> dict:
    folders = drive_folders(rows)
    started, listed, failed = time.time(), 0, 0
    for folder in folders:
        if refresh and folder in (index.archive.get("folders") or {}):
            index.archive["folders"].pop(folder, None)
        try:
            before = len(index.drive_files)
            index.add_drive_folder(folder)
            listed += 1
            if len(index.drive_files) == before:
                log(f"drive: {folder} empty")
        except Exception as exc:          # offline or missing folder: the report says so, never a guess
            failed += 1
            log(f"drive: {folder} failed: {type(exc).__name__}: {str(exc)[:120]}")
            info = {"at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "files": {},
                    "error": f"{type(exc).__name__}: {str(exc)[:200]}"}
            alternate = _alternate_folder(folder)
            if alternate:                 # the same company's files sometimes sit under the other prefix
                try:
                    index.add_drive_folder(alternate)
                    files = index.archive["folders"].get(alternate, {}).get("files", {})
                    info.update(alternate=alternate, alternate_files=len(files))
                except Exception as exc2:
                    info.update(alternate=alternate, alternate_error=f"{type(exc2).__name__}: {str(exc2)[:120]}")
            index.archive.setdefault("folders", {})[folder] = info
    index.reindex_drive()
    index.save(DRIVE_CACHE)
    return {"folders": len(folders), "listed": listed, "failed": failed, "seconds": round(time.time() - started, 1)}


def fetch_sample(index: FileIndex, results: list[dict], count: int, dest: Path) -> dict:
    """Download at most ``count`` on-drive files to measure seconds/file; check each one's text after the fetch."""
    from reality_engine.toolbelt import drive_fetch
    on_drive = [r for r in results if r["verdict"] == "on_drive"][:max(0, min(count, DRIVE_FETCH_LIMIT))]
    if not on_drive:
        return {"files": 0, "fetched": 0, "seconds": 0.0, "seconds_per_file": 0.0}
    dest.mkdir(parents=True, exist_ok=True)
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    rows: dict[int, sqlite3.Row] = {}
    for item in on_drive:
        row = conn.execute("SELECT * FROM corporate_documents WHERE id=?", (item["id"],)).fetchone()  # type: ignore[union-attr]
        if row is not None:
            rows[item["id"]] = row
    remotes = []
    for item in on_drive:
        remote = (item.get("extra") or {}).get("remote") or doc_identity.resolve_file(rows[item["id"]], index)[2]
        remotes.append(remote)
    started, ok = time.time(), 0
    batch = drive_fetch.fetch([r for r in remotes if r], dest=dest, dry_run=False,
                              index_path=index.index_path or DRIVE_CACHE)
    for item, record in zip(on_drive, batch["items"]):
        if record.get("status") == "ok" and record.get("dest") and Path(record["dest"]).exists():
            fetched = Path(record["dest"])
            checked = check_row(conn, rows[item["id"]], index=index, fetch=lambda _remote: fetched)
            item.update(checked.row(), file_where="drive_fetched")
            ok += 1
    conn.close()
    elapsed = time.time() - started
    return {"files": len(on_drive), "fetched": ok, "seconds": round(elapsed, 1),
            "seconds_per_file": round(elapsed / len(on_drive), 2)}


def _summary(results: list[dict], elapsed: float) -> dict:
    by_type = defaultdict(Counter)
    where = defaultdict(Counter)
    checks = {name: Counter(r[name] for r in results) for name in ("company", "fiscal_year", "type", "date")}
    for r in results:
        by_type[r["doc_type"]][r["verdict"]] += 1
        where[r["doc_type"]][r["file_where"]] += 1
    return {"n": len(results), "seconds": round(elapsed, 1),
            "per_1000": round(elapsed * 1000 / len(results), 1) if results else 0.0,
            "verdicts": dict(Counter(r["verdict"] for r in results)),
            "by_type": {k: dict(v) for k, v in sorted(by_type.items(), key=lambda kv: -sum(kv[1].values()))},
            "where": {k: dict(v) for k, v in sorted(where.items(), key=lambda kv: -sum(kv[1].values()))},
            "checks": {k: dict(v) for k, v in checks.items()}}


def write_report(path: Path, summary: dict, results: list[dict], config: dict, drive: dict | None,
                 fetched: dict | None, extras: dict | None = None) -> None:
    extras = extras or {}
    total_rows = extras.get("total_rows") or summary["n"]
    hours = summary["per_1000"] * total_rows / 1000 / 3600
    lines = ["# Document identity scan (T-093)", "",
             f"Run {config['started']} · `{config['db']}` · read-only", "",
             f"- documents: **{summary['n']}**",
             f"- scan elapsed: **{summary['seconds']} s** · **{summary['per_1000']} s per 1,000** on "
             f"{config['processes']} process(es)",
             f"- whole table ({total_rows:,} rows) at this run's rate: **{hours:.1f} h** on "
             f"{config['processes']} process(es)",
             f"- symbols: {', '.join(config['symbols']) or 'all'}",
             f"- verdicts: {json.dumps(summary['verdicts'])}", ""]
    sample = extras.get("sample")
    if sample:
        lines += [f"Sample: **{sample['n']}** documents, stratified by doc_type, seed {sample['seed']}; "
                  f"weights {json.dumps({k: round(v, 1) for k, v in sample['weights'].items()})}", ""]
        projected = Counter()
        for r in results:
            projected[r["verdict"]] += r.get("sample_weight", 1.0)
        lines += [f"Projected whole table by verdict: {json.dumps({k: round(v) for k, v in projected.items()})}", ""]
        rate = defaultdict(lambda: [0, 0, 0])
        for r in results:
            if not r["sha256"]:
                continue
            rate[r["doc_type"]][0] += 1
            rate[r["doc_type"]][1] += 1 if r["file_where"] == "missing" else 0
            rate[r["doc_type"]][2] += 1 if r["file_where"] == "not_indexed" else 0
        lines += ["### Hashed rows in neither disk nor Drive, by type (sample)", "",
                  "| doc_type | hashed | missing (folder listed) | not_indexed (folder never listed) |",
                  "|---|---|---|---|"]
        for doc_type, (hashed, missing, not_indexed) in sorted(rate.items()):
            lines.append(f"| {doc_type} | {hashed} | {missing} | {not_indexed} |")
        lines.append("")
    cover = extras.get("cover_letters") or {}
    if cover.get("rows"):
        calls = cover["by_type"].get("CONCALL_TRANSCRIPT", 0)
        lines += [f"### Cover letters / web-link letters (refetch candidates)", "",
                  f"- rows: **{cover['rows']}** (projected **{cover['projected']}** in the table); "
                  f"{cover['with_link']} print an http(s) link",
                  f"- by type: {json.dumps(cover['by_type'])}",
                  f"- transcript cover letters: {calls} (projected "
                  f"{round(calls * (cover['projected'] / cover['rows']), 1) if cover['rows'] else 0}) — calls with no "
                  f"transcript held",
                  f"- companies: {', '.join(cover['companies'][:40])}"
                  + (f" (+{len(cover['companies']) - 40} more)" if len(cover["companies"]) > 40 else ""), ""]
    dups = extras.get("duplicates") or {}
    if dups:
        lines += ["### Same file under several rows", "",
                  f"- same-company sha groups with 2+ rows: **{dups.get('groups', 0)}**; repeated rows by type: "
                  f"{json.dumps(dups.get('by_type', {}))} (not set aside; `duplicate_of` marks the extra rows)",
                  f"- hashes under two symbols (equity + listed debt): {dups.get('cross_symbol_hashes', 0)}", ""]
    size = extras.get("drive_size") or {}
    if size.get("observed"):
        lines += ["### Drive download size (sample, stated apart)", "",
                  f"- on-drive sample rows with an index size: {size['observed']}; projected files "
                  f"**{size['projected_files']:,}**, average {size['avg_mb']} MB, total "
                  f"**{size['projected_bytes'] / 1e9:.1f} GB**",
                  f"- at 2.91 s/file (one 8-transfer batch, not sequential): "
                  f"**{size['projected_files'] * 2.91 / 3600:.1f} h**; a per-file rclone call measured 14.4 s/file",
                  ""]
    if drive is not None:
        lines += [f"Drive folder listing (stated apart, one-off index): {drive['listed']} listed, "
                  f"{drive.get('failed', 0)} failed, of {drive['folders']} in {drive['seconds']} s", ""]
        failed = {k: v for k, v in (extras.get("archive") or {}).items() if v.get("error")}
        if failed:
            lines += ["Folders that do not exist in the archive (and the other prefix):", ""]
            for folder, info in sorted(failed.items()):
                alt = info.get("alternate")
                lines.append(f"- `{folder}` — alternate `{alt}` files: {info.get('alternate_files', 'n/a')}"
                             if alt else f"- `{folder}` — no alternate prefix")
            lines.append("")
    if fetched is not None:
        lines += [f"Drive fetch sample: **{fetched.get('fetched', 0)} of {fetched['files']}** files in "
                  f"{fetched['seconds']} s (**{fetched.get('seconds_per_file', 0)} s/file**), stated apart from the "
                  f"scan seconds above", ""]
    lines += ["## Verdicts by type (and file lookup)", "", "| doc_type | verdicts | files |", "|---|---|---|"]
    for doc_type, verdicts in summary["by_type"].items():
        lines.append(f"| {doc_type} | {json.dumps(verdicts)} | {json.dumps(summary['where'].get(doc_type, {}))} |")
    lines += ["", "## Checks", ""]
    for name, counted in summary["checks"].items():
        lines.append(f"- {name}: {json.dumps(counted)}")
    lines += ["", "## Set-aside sample (first 30)", ""]
    for r in [r for r in results if r["verdict"] == "set_aside"][:30]:
        why = "; ".join(f"{f} {r[f]}: {r[f + '_reason']}" for f in ("company", "fiscal_year", "type")
                        if r[f] == "mismatch")
        lines.append(f"- id {r['id']} {r['symbol']} {r['doc_type']} — {why or r['date_reason']}"
                     + (f" | {r['linked_url']}" if r.get("linked_url") else ""))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, results: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        for r in sorted(results, key=lambda x: x["id"]):
            writer.writerow(r)


def read_csv(path: Path) -> list[dict]:
    if not path.is_file():
        return []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        try:
            row["sample_weight"] = float(row.get("sample_weight") or 1.0)
        except ValueError:
            row["sample_weight"] = 1.0
        row["duplicate_of"] = int(row["duplicate_of"]) if str(row.get("duplicate_of") or "").strip() else None
    return rows


def write_identity_db(path: Path, results: list[dict]) -> int:
    """Append the verdicts to a pilot build database's ``doc_identity`` table (never the main store)."""
    from reality_engine.pilot3 import schema
    conn = sqlite3.connect(path)
    try:
        schema.ensure(conn, ("doc_identity",))
        now = datetime.now(timezone.utc).isoformat(timespec="seconds")
        conn.executemany("DELETE FROM doc_identity WHERE corporate_doc_id=?", [(r["id"],) for r in results])
        columns = {row[1] for row in conn.execute("PRAGMA table_info(doc_identity)")}
        for name in ("linked_url", "duplicate_of"):       # an older build's table predates these columns
            if name not in columns:
                conn.execute(f"ALTER TABLE doc_identity ADD COLUMN {name} TEXT")
        conn.executemany(
            "INSERT INTO doc_identity (doc_key, corporate_doc_id, symbol, isin, doc_type, file_where, verdict, company,"
            " company_reason, fiscal_year, fiscal_year_reason, type, type_reason, date, date_reason, filing_date,"
            " linked_url, duplicate_of, text_chars, checked_at)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            [(r["id"], r["id"], r["symbol"], r.get("isin"), r["doc_type"], r["file_where"], r["verdict"], r["company"],
              r["company_reason"], r["fiscal_year"], r["fiscal_year_reason"], r["type"], r["type_reason"], r["date"],
              r["date_reason"], r["filing_date"], r.get("linked_url") or "", r.get("duplicate_of"),
              r["text_chars"], now) for r in results])
        conn.commit()
        return len(results)
    finally:
        conn.close()


def run_shards(args, symbols: tuple[str, ...], index: FileIndex, shards: int, ids: list[int]) -> tuple[list[dict], float]:
    """N shard processes write their own CSVs (inherited stdout: the sandbox denies multiprocessing's pipes)."""
    shard_dir = Path(".tmp") / "doc_identity_shards"
    shard_dir.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, REALITY_DRIVE_INDEX=str(DRIVE_CACHE if DRIVE_CACHE.is_file()
                                                   else (index.index_path or DRIVE_CACHE)))
    procs = []
    started = time.time()
    for i in range(shards):
        id_file = shard_dir / f"ids_{i}.json"
        id_file.write_text(json.dumps(ids[i::shards]), encoding="utf-8")
        cmd = [sys.executable, "-m", "reality_engine.scripts.doc_identity_scan",
               "--ids-file", str(id_file), "--processes", "1", "--drive", "none",
               "--csv", str(shard_dir / f"shard_{i}.csv"), "--report-dir", str(shard_dir),
               "--summary", str(shard_dir / f"shard_{i}.json")]
        procs.append(subprocess.Popen(cmd, env=env, stdout=None, stderr=None))
    codes = [p.wait() for p in procs]
    elapsed = time.time() - started
    results: list[dict] = []
    for i in range(shards):
        results.extend(read_csv(shard_dir / f"shard_{i}.csv"))
    if any(codes):
        print(f"shard exit codes {codes}", flush=True)
    return results, elapsed


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--symbols", default="", help="comma-separated; empty means the whole table")
    ap.add_argument("--doc-types", default="", help="comma-separated doc_type filter")
    ap.add_argument("--subcats", default="", help="comma-separated bse_subcat filter")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--sample", type=int, help="random sample stratified by doc_type (whole table or the filters)")
    ap.add_argument("--seed", type=int, default=20261106)
    ap.add_argument("--processes", type=int, default=1)
    ap.add_argument("--ids-file", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--drive", choices=("auto", "warm", "none"), default="auto",
                    help="warm = list stored-path folders in the archive index; auto = warm when --symbols is given")
    ap.add_argument("--refresh-drive", action="store_true", help="relist folders already in the index")
    ap.add_argument("--fetch-drive", type=int, default=0, help=f"sample downloads to time (max {DRIVE_FETCH_LIMIT})")
    ap.add_argument("--report-dir", type=Path, default=Path(r"D:\RealityEngine\reports"))
    ap.add_argument("--csv", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--summary", type=Path, help=argparse.SUPPRESS)
    ap.add_argument("--identity-db", type=Path, help="append verdicts to this pilot build database")
    args = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    started_at = datetime.now(timezone.utc)
    symbols = tuple(s.strip().upper() for s in args.symbols.split(",") if s.strip())
    doc_types = tuple(s.strip() for s in args.doc_types.split(",") if s.strip())
    subcats = tuple(s.strip() for s in args.subcats.split(",") if s.strip())
    conn = connect_ro(str(main_store()))
    conn.row_factory = sqlite3.Row
    ids_file = json.loads(args.ids_file.read_text(encoding="utf-8")) if args.ids_file else None
    weights: dict[str, float] = {}
    sample_ids = None
    if args.sample and ids_file is None:
        sample_ids, weights = stratified_sample(conn, symbols, doc_types, subcats, args.sample, args.seed)
        rows = list(rows_for(conn, symbols, None, sample_ids))
    else:
        rows = list(rows_for(conn, symbols, args.limit, ids_file, doc_types, subcats))
    print(f"{len(rows)} documents", flush=True)
    index = doc_identity.build_file_index()
    drive = None
    if args.drive == "warm" or (args.drive == "auto" and symbols):
        drive = warm_drive(index, rows, refresh=args.refresh_drive)
        print(f"drive: {drive}", flush=True)
    fetched = None
    if args.processes > 1 and ids_file is None:
        shard_ids = sample_ids or selected_ids(conn, symbols, args.limit, doc_types, subcats)
        conn.close()
        results, elapsed = run_shards(args, symbols, index, args.processes, shard_ids)
        if args.fetch_drive:
            fetched = fetch_sample(index, results, args.fetch_drive, Path(".tmp") / "doc_identity_fetch")
    else:
        started = time.time()
        results = run_rows(conn, rows, index)
        elapsed = time.time() - started
        conn.close()
    meta = connect_ro(str(main_store()))
    if weights:
        annotate(results, meta, weights)
    count_row = meta.execute("SELECT COUNT(*) FROM corporate_documents").fetchone()  # type: ignore[union-attr]
    total_rows = count_row[0] if count_row else 0
    summary = _summary(results, elapsed)
    if ids_file is not None:
        write_csv(args.csv, results)
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(json.dumps({"n": len(results), "seconds": round(elapsed, 1)}), encoding="utf-8")
        meta.close()
        return 0
    extras = {"total_rows": total_rows, "duplicates": duplicate_counts(meta),
              "cover_letters": cover_letter_stats(results), "drive_size": drive_size(index, results),
              "archive": index.archive.get("folders", {})}
    if weights:
        extras["sample"] = {"n": len(results), "seed": args.seed, "weights": weights}
    meta.close()
    stamp = started_at.strftime("%Y-%m-%d_%H%M%S")
    config = {"started": started_at.isoformat(timespec="seconds"), "db": str(main_store()),
              "processes": args.processes, "symbols": symbols}
    report = args.report_dir / f"{stamp}_doc_identity_scan.md"
    csv_path = args.report_dir / f"{stamp}_doc_identity_scan.csv"
    write_report(report, summary, results, config, drive, fetched, extras)
    write_csv(csv_path, results)
    if args.identity_db:
        print(f"identity rows written: {write_identity_db(args.identity_db, results)}")
    print(json.dumps({"verdicts": summary["verdicts"], "per_1000_s": summary["per_1000"],
                      "seconds": summary["seconds"], "report": str(report), "csv": str(csv_path)}))
    print(f"set_aside {summary['verdicts'].get('set_aside', 0)} · unknown {summary['verdicts'].get('unknown', 0)} · "
          f"on_drive {summary['verdicts'].get('on_drive', 0)} · not_held {summary['verdicts'].get('not_held', 0)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
