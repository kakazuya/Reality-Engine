"""T-201: one command that says what a branch changes in a store, row by row.

    python -m reality_engine.scripts.store_diff --store <db> --profile <json> \\
        --parts transcripts,kpi,guidance,ratios --base main --head <branch|worktree path> --out <dir>

The source store is copied twice (``<out>/base.db``, ``<out>/head.db``) and never opened for writing: a copy is
checkpointed and left in ``journal_mode=DELETE``, then each side's own code rebuilds the named parts on its own copy
(``git worktree add --detach`` for a ref, a given path otherwise; hidden subprocesses, no shell).  Every table both
copies hold is diffed by a key per table (``KEYS``); a table without a spec is compared as whole rows by hash.  The
report says, per table and per symbol, what was removed, added and changed by column, plus the rows the serving
tools would no longer return (a guidance row whose ``entity`` now names a subsidiary, a row its check verdict now
quarantines).  ``STORE_DIFF.md`` and ``store_diff.json`` land in ``--out``.

Gates fail the run (exit 1): a part that fails on head but not on base; a ``--golden`` CSV row (``table,<key
columns>,value``) lost or changed; a table whose removed+changed share is above ``--max-churn`` (default 2 %) in a
store other than ``--target``.  Verdict tables (``row_check`` / ``row_check_fail``) are not row-diffed: their ids
point at rows a rebuild renumbers.  Their serving effect is what the diff measures, and their coverage per table is
reported beside it.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

from reality_engine.db.readonly import connect_ro

ROOT = Path(__file__).resolve().parents[2]
LIMIT = 10                      # sampled rows per table in the report
SKIP_TABLES = {"row_check", "row_check_fail"}      # verdicts: compared through their serving effect, not row ids
IGNORED_COLUMNS = {"id", "row_id", "revision_of"}  # intra-store pointers a rebuild renumbers

# The key of one row per table (T-201).  A column named here is the row's identity across the two builds; every
# other column is compared.  ``value`` is rounded by ``_norm``, so float noise is not a change.
# Tables not named here are compared as whole rows by hash.
KEYS: dict[str, tuple[str, ...]] = {
    "company": ("symbol", "isin"),
    "doc": ("doc_key",),
    "doc_page": ("doc_key", "page"),
    "doc_alias": ("symbol", "alias_key"),
    "kpi_series": ("symbol", "metric", "dimension", "value", "doc_key", "page"),
    "guidance": ("symbol", "metric", "target_period", "low", "high", "doc_key", "page"),
    "ratio_panel": ("symbol", "metric", "fiscal_period", "basis"),
    "transcript_statement": ("doc_key", "page", "seq"),
    "share_capital": ("symbol", "as_of_date", "basis", "event", "count_basis"),
    "shp_category": ("symbol", "quarter_end", "category", "pct_basis"),
    "dividend_event": ("symbol", "ex_date", "kind", "fiscal_year"),
    "event": ("symbol", "kind", "event_date", "doc_key", "page"),
    "formula": ("formula_id",),
}
SERVED_BY_ENTITY = {"guidance"}    # the serving lookup hides a guidance row whose entity names another issuer

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0


# --- rows --------------------------------------------------------------------------------------------------------

def _norm(value):
    if isinstance(value, float):
        return None if value != value else round(value, 6)      # NaN -> NULL, no float noise in a key
    if isinstance(value, bytes):
        return value.hex()
    return value


def _quote(name: str) -> str:
    return '"' + str(name).replace('"', '""') + '"'


def _has_table(conn, table: str) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone() is not None


def _columns(conn, table: str) -> list[str]:
    return [r[1] for r in conn.execute(f"PRAGMA table_info({_quote(table)})")]


def _tables(conn) -> list[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'").fetchall()
    return sorted(r[0] for r in rows if r[0] not in SKIP_TABLES and "_fts" not in r[0])


def _fetch(conn, table: str, columns: list[str]) -> list[tuple]:
    if not columns:
        return []
    return conn.execute(f"SELECT {','.join(_quote(c) for c in columns)} FROM {_quote(table)}").fetchall()


def _hash(values) -> str:
    return hashlib.sha1(repr(values).encode("utf-8", "surrogatepass")).hexdigest()[:16]


def _display(value, limit: int = 240):
    if isinstance(value, float):
        return round(value, 6)
    if isinstance(value, str) and len(value) > limit:
        return value[:limit] + "..."
    return value


def _trim(value, limit: int = 160):
    text = " ".join(str(value or "").split())
    return text[:limit] + "..." if len(text) > limit else text


# --- served -------------------------------------------------------------------------------------------------------

def _quarantined(conn, table: str) -> set:
    if not _has_table(conn, "row_check"):
        return set()
    return {r[0] for r in conn.execute("SELECT row_id FROM row_check WHERE tbl=? AND status='quarantined'", (table,))}


def _served(table: str, cols: list[str], row: tuple, quarantined: set) -> tuple[bool, str]:
    """What the serving lookup would return: no quarantine verdict, and for guidance the group's own target only."""
    if "id" in cols and row[cols.index("id")] in quarantined:
        return False, "row_check"
    if table in SERVED_BY_ENTITY and "entity" in cols and (row[cols.index("entity")] or "") != "":
        return False, "entity"
    return True, ""


def verdict_coverage(conn) -> dict:
    if not _has_table(conn, "row_check"):
        return {}
    out: dict = {}
    for tbl, status, count in conn.execute("SELECT tbl, status, COUNT(*) FROM row_check GROUP BY 1, 2 ORDER BY 1, 2"):
        out.setdefault(tbl, {})[status] = count
    return out


# --- diff --------------------------------------------------------------------------------------------------------

def _symbol(cols: list[str], row: tuple) -> str:
    return str(row[cols.index("symbol")]) if "symbol" in cols else "-"


def _sample(cols, row, key_cols, key_values) -> dict:
    out = {"symbol": _symbol(cols, row),
           "key": dict(zip(key_cols, (_display(v) for v in key_values)))}
    for name in ("page", "doc_key"):
        if name in cols:
            out[name] = row[cols.index(name)]
    if "quote" in cols:
        out["quote"] = _trim(row[cols.index("quote")])
    return out


def _served_sample(cols, row, key_cols, key_values, reason) -> dict:
    out = _sample(cols, row, key_cols, key_values)
    out["why"] = reason
    return out


def diff_table(base, head, table: str) -> dict:
    """One table's keyed diff between two open read-only connections."""
    have_base, have_head = _has_table(base, table), _has_table(head, table)
    bc = _columns(base, table) if have_base else []
    hc = _columns(head, table) if have_head else []
    cols = list(dict.fromkeys([*bc, *hc]))

    def aligned(rows, table_cols):
        idx = {c: i for i, c in enumerate(table_cols)}
        return [tuple(_norm(r[idx[c]]) if c in idx else None for c in cols) for r in rows]

    base_rows = aligned(_fetch(base, table, bc), bc)
    head_rows = aligned(_fetch(head, table, hc), hc)
    key_cols = [c for c in KEYS.get(table, ()) if c in cols]
    if not key_cols:
        return _hash_diff(table, cols, base_rows, head_rows)

    kidx = [cols.index(c) for c in key_cols]
    compared = [i for i, c in enumerate(cols) if c not in key_cols and c not in IGNORED_COLUMNS]

    def key_of(row):
        return tuple(row[i] for i in kidx)

    base_by: dict = {}
    head_by: dict = {}
    for row in base_rows:
        base_by.setdefault(key_of(row), []).append(row)
    for row in head_rows:
        head_by.setdefault(key_of(row), []).append(row)

    qb, qh = _quarantined(base, table), _quarantined(head, table)
    removed = added = changed = lost = 0
    columns: dict = {}
    by_symbol: dict = {}
    samples: list = []
    lost_samples: list = []

    def count(sym, field, n=1):
        row = by_symbol.setdefault(sym, {"removed": 0, "added": 0, "changed": 0})
        row[field] += n

    for key in sorted(set(base_by) | set(head_by), key=repr):
        bl = sorted(base_by.get(key, []), key=repr)
        hl = sorted(head_by.get(key, []), key=repr)
        for br, hr in zip(bl, hl):
            sym = _symbol(cols, hr)
            diff = [i for i in compared if br[i] != hr[i]]
            if diff:
                changed += 1
                count(sym, "changed")
                for i in diff:
                    columns[cols[i]] = columns.get(cols[i], 0) + 1
                if len(samples) < LIMIT:
                    sample = _sample(cols, hr, key_cols, key)
                    sample["changes"] = [{"column": cols[i], "base": _display(br[i]), "head": _display(hr[i])}
                                         for i in diff[:4]]
                    samples.append(sample)
            base_served, _ = _served(table, cols, br, qb)
            head_served, reason = _served(table, cols, hr, qh)
            if base_served and not head_served:
                lost += 1
                if len(lost_samples) < LIMIT:
                    lost_samples.append(_served_sample(cols, hr, key_cols, key, reason))
        for br in bl[len(hl):]:
            removed += 1
            count(_symbol(cols, br), "removed")
            if _served(table, cols, br, qb)[0]:
                lost += 1
                if len(lost_samples) < LIMIT:
                    lost_samples.append(_served_sample(cols, br, key_cols, key, "gone"))
            if len(samples) < LIMIT:
                samples.append(_sample(cols, br, key_cols, key, ))
        for hr in hl[len(bl):]:
            added += 1
            count(_symbol(cols, hr), "added")

    return {"table": table, "mode": "keyed", "key": list(key_cols),
            "base_rows": len(base_rows), "head_rows": len(head_rows),
            "removed": removed, "added": added, "changed": changed,
            "columns": columns, "by_symbol": by_symbol, "samples": samples,
            "served": {"lost": lost, "samples": lost_samples},
            "churn_pct": _churn(len(base_rows), removed + changed)}


def _hash_diff(table: str, cols: list[str], base_rows: list[tuple], head_rows: list[tuple]) -> dict:
    """No key spec: whole rows, by hash (a table the codebase adds tomorrow is still diffed, not skipped)."""
    keep = [i for i, c in enumerate(cols) if c not in IGNORED_COLUMNS]

    def hashes(rows):
        return Counter(_hash(tuple(r[i] for i in keep)) for r in rows)

    bc, hc = hashes(base_rows), hashes(head_rows)
    gone_hashes, new_hashes = bc - hc, hc - bc
    gone = [r for r in base_rows if _hash(tuple(r[i] for i in keep)) in gone_hashes]
    new = [r for r in head_rows if _hash(tuple(r[i] for i in keep)) in new_hashes]
    by_symbol: dict = {}
    for row in gone:
        sym = _symbol(cols, row)
        by_symbol.setdefault(sym, {"removed": 0, "added": 0, "changed": 0})["removed"] += 1
    for row in new:
        sym = _symbol(cols, row)
        by_symbol.setdefault(sym, {"removed": 0, "added": 0, "changed": 0})["added"] += 1
    samples = [_sample(cols, row, [], ()) for row in gone[:LIMIT]]
    return {"table": table, "mode": "row_hash", "key": [],
            "base_rows": len(base_rows), "head_rows": len(head_rows),
            "removed": sum(gone_hashes.values()), "added": sum(new_hashes.values()), "changed": 0,
            "columns": {}, "by_symbol": by_symbol, "samples": samples,
            "served": {"lost": 0, "samples": []},
            "churn_pct": _churn(len(base_rows), sum(gone_hashes.values()))}


def _churn(total: int, touched: int) -> float:
    if total:
        return round(100.0 * touched / total, 2)
    return 100.0 if touched else 0.0


def diff_store(base_db: Path, head_db: Path, tables=None) -> dict:
    """Every table both stores hold, keyed, in one report dict."""
    base = connect_ro(base_db, timeout_s=600)
    head = connect_ro(head_db, timeout_s=600)
    try:
        names = sorted(set(_tables(base)) | set(_tables(head)))
        if tables:
            wanted = {t.strip() for t in tables}
            names = [t for t in names if t in wanted]
        return {"tables": {name: diff_table(base, head, name) for name in names},
                "verdicts": {"base": verdict_coverage(base), "head": verdict_coverage(head)}}
    finally:
        base.close()
        head.close()


# --- copies and builds -------------------------------------------------------------------------------------------

def run_hidden(cmd: list[str], cwd: Path, log_path: Path) -> int:
    """Run a subprocess with no window and no shell; its output goes to a log file (never a pipe).

    A pipe is also what the confined Windows sandbox refuses for an external program, so redirecting to a file keeps
    this tool runnable where the controller runs it."""
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "w", encoding="utf-8") as log:
        try:
            return subprocess.run(cmd, cwd=str(cwd), stdin=subprocess.DEVNULL, stdout=log,
                                  stderr=subprocess.STDOUT, shell=False,
                                  creationflags=CREATE_NO_WINDOW).returncode
        except OSError as exc:
            log.write(f"\n[start failed] {exc}\n")
            return 127


def copy_store(src: Path, dest: Path) -> float:
    """A consistent copy of ``src`` at ``dest``; the source is only read (byte copy, never opened by sqlite).

    The copy carries the source's ``-wal`` when present (the database recovery then replays it); the ``-shm`` is
    rebuilt on open, so it is not copied.  The copy itself is checkpointed and set to ``journal_mode=DELETE``: a
    side build then works on one clean file."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    started = time.time()
    for suffix in ("", "-wal", "-shm"):
        Path(f"{dest}{suffix}").unlink(missing_ok=True)
    shutil.copy2(src, dest)
    if Path(f"{src}-wal").is_file():
        shutil.copy2(f"{src}-wal", f"{dest}-wal")
    _checkpoint(dest)
    return round(time.time() - started, 1)


def _checkpoint(path: Path) -> None:
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        con.execute("PRAGMA journal_mode=DELETE")
    finally:
        con.close()


def build_side(db: Path, parts: list[str], cwd: Path, profile: str, out: Path, side: str,
               runner=run_hidden) -> dict:
    """Run each named part with that side's code, on that side's copy.  A failed part is a result, not a crash."""
    results: dict = {}
    for part in parts:
        log = out / "logs" / f"{side}-{part}.log"
        cmd = [sys.executable, "-m", "reality_engine.pilot3.build",
               "--profile", profile, "--out", str(db), "--part", part]
        started = time.time()
        code = runner(cmd, Path(cwd), log)
        results[part] = {"exit": code, "seconds": round(time.time() - started, 1), "log": str(log)}
    return results


def build_gates(base: dict, head: dict) -> list[dict]:
    """A part that fails on head but not on base loses work; any other failure is reported, not gated."""
    gates = []
    for part, result in head.items():
        if result["exit"] != 0 and base.get(part, {}).get("exit", 1) == 0:
            gates.append({"gate": "build", "part": part, "exit": result["exit"], "log": result["log"]})
    return gates


def _worktree(repo: Path, ref: str, dest: Path, out: Path) -> Path:
    dest = dest.resolve()
    if dest.exists():
        shutil.rmtree(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["git", "-C", str(repo), "worktree", "add", "--detach", str(dest), ref]
    code = run_hidden(cmd, repo, out / "logs" / f"worktree-{dest.name}.log")
    if code != 0:
        raise RuntimeError(f"git worktree add {ref} failed (exit {code}); see {out / 'logs'}")
    return dest


def _remove_worktree(repo: Path, dest: Path, out: Path) -> None:
    run_hidden(["git", "-C", str(repo), "worktree", "remove", "--force", str(dest)],
               repo, out / "logs" / f"worktree-remove-{dest.name}.log")
    shutil.rmtree(dest, ignore_errors=True)


def side_checkout(ref: str, repo: Path, out: Path, label: str) -> tuple[Path, bool]:
    """A given directory is used as-is; a ref gets a detached temporary worktree.  (path, created)."""
    path = Path(ref).expanduser()
    if path.is_dir():
        return path.resolve(), False
    return _worktree(repo, ref, out / "worktrees" / label, out), True


# --- gates and output --------------------------------------------------------------------------------------------

def _same_number(left, right) -> bool:
    try:
        return abs(float(left) - float(right)) <= 1e-9 * max(1.0, abs(float(right)))
    except (TypeError, ValueError):
        return str(left) == str(right)


def golden_gates(head_db: Path, golden_csv: str | None) -> list[dict]:
    """The ``--golden`` rows the head store lost or changed: ``table,<key columns>,value``."""
    if not golden_csv:
        return []
    gates = []
    con = connect_ro(head_db, timeout_s=120)
    try:
        with open(golden_csv, newline="", encoding="utf-8") as handle:
            for line, spec in enumerate(csv.DictReader(handle), start=2):
                spec = {k: v for k, v in spec.items() if k and v not in (None, "")}
                table = spec.pop("table", "")
                expected = spec.pop("value", None)
                if not table or expected is None:
                    gates.append({"gate": "golden", "line": line, "why": "needs table and value columns"})
                    continue
                where = " AND ".join(f"{_quote(c)}=?" for c in spec)
                try:
                    cursor = con.execute(f"SELECT value FROM {_quote(table)}" + (f" WHERE {where}" if where else ""),
                                         tuple(spec.values()))
                    rows = cursor.fetchall() if cursor is not None else []
                except sqlite3.Error as exc:
                    gates.append({"gate": "golden", "line": line, "table": table, "why": f"query failed: {exc}"})
                    continue
                if not rows:
                    gates.append({"gate": "golden", "line": line, "table": table, "why": "row lost", "key": spec})
                elif not any(_same_number(r[0], expected) for r in rows):
                    gates.append({"gate": "golden", "line": line, "table": table, "why": "value changed",
                                  "key": spec, "expected": expected,
                                  "found": [_display(r[0]) for r in rows[:3]]})
    finally:
        con.close()
    return gates


def churn_gates(tables: dict, max_churn: float, store: Path, target: str | None) -> list[dict]:
    """Churn above the cap is a loss unless the caller named this store as the one meant to change."""
    if _is_target(store, target):
        return []
    return [{"gate": "churn", "table": name, "churn_pct": info["churn_pct"], "max_churn": max_churn}
            for name, info in tables.items() if info["churn_pct"] > max_churn]


def _is_target(store: Path, target: str | None) -> bool:
    if not target:
        return False
    named = Path(target)
    if named.name.lower() in (store.name.lower(), store.stem.lower()):
        return True
    try:
        return named.resolve() == store.resolve()
    except OSError:
        return False


def _write_markdown(report: dict, path: Path) -> None:
    lines = ["# STORE_DIFF", "",
             f"- store: `{report['store']}`",
             f"- base: `{report['base']['ref']}` ({report['base']['path']})",
             f"- head: `{report['head']['ref']}` ({report['head']['path']})",
             f"- parts: {', '.join(report['parts'])}",
             f"- generated: {report['generated_at']}",
             f"- gates: **{len(report['gates'])}**", "", "## Builds", "",
             "| side | part | exit | seconds |", "|---|---|---|---|"]
    for side in ("base", "head"):
        for part, result in report["builds"][side].items():
            lines.append(f"| {side} | {part} | {result['exit']} | {result['seconds']} |")
    lines += ["", "## Tables", "",
              "| table | base | head | removed | added | changed | churn % | no longer served |",
              "|---|---|---|---|---|---|---|---|"]
    for name, info in report["tables"].items():
        lines.append(f"| {name} | {info['base_rows']} | {info['head_rows']} | {info['removed']} | "
                     f"{info['added']} | {info['changed']} | {info['churn_pct']} | {info['served']['lost']} |")
    lines += ["", "## Gates", ""]
    if not report["gates"]:
        lines.append("none")
    else:
        for gate in report["gates"]:
            lines.append(f"- **{gate['gate']}**: " + ", ".join(f"{k}={v}" for k, v in gate.items()
                                                               if k not in ("gate", "log", "key")))
            if gate.get("key"):
                lines.append(f"  - key: {gate['key']}")
    lines += ["", "## Changed rows (sampled)", ""]
    for name, info in report["tables"].items():
        if not info["samples"] and not info["served"]["samples"]:
            continue
        lines += [f"### {name} ({info['changed']} changed, {info['removed']} removed, {info['served']['lost']} "
                  f"no longer served)", ""]
        for sample in info["samples"][:LIMIT]:
            changes = "; ".join(f"{c['column']}: {_display(c['base'])} -> {_display(c['head'])}"
                                for c in sample.get("changes", []))
            lines.append(f"- {sample['symbol']} {sample['key']}" + (f" — {changes}" if changes else " — removed")
                         + (f" (page {sample['page']})" if sample.get("page") is not None else "")
                         + (f' — "{sample["quote"]}"' if sample.get("quote") else ""))
        for sample in info["served"]["samples"]:
            lines.append(f"- {sample['symbol']} {sample['key']} — no longer served ({sample['why']})")
        lines.append("")
    lines += ["## Check verdicts", ""]
    for side in ("base", "head"):
        coverage = report["verdicts"][side]
        lines.append(f"- {side}: " + (", ".join(f"{tbl} " + "/".join(f"{k} {v}" for k, v in counts.items())
                                                for tbl, counts in coverage.items()) or "none"))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--store", required=True, help="the source store; it is copied and never opened for writing")
    ap.add_argument("--profile", required=True, help="build profile JSON (companies, pages db, raw root)")
    ap.add_argument("--parts", default="guidance",
                    help="comma list of build parts to rebuild on both copies (default: guidance)")
    ap.add_argument("--base", default="main", help="a git ref (worktree made) or a checkout path")
    ap.add_argument("--head", default="HEAD", help="a git ref (worktree made) or a checkout path")
    ap.add_argument("--out", required=True, help="output directory: copies, logs, STORE_DIFF.md, store_diff.json")
    ap.add_argument("--target", default=None,
                    help="the store this run means to change; its churn is not gated (name or path)")
    ap.add_argument("--max-churn", type=float, default=2.0, help="max removed+changed share per table, percent")
    ap.add_argument("--golden", default=None, help="CSV of rows that must survive: table,<key columns>,value")
    args = ap.parse_args(argv)

    started = time.time()
    store = Path(args.store).expanduser().resolve()
    if not store.is_file():
        ap.error(f"store not found: {store}")
    profile = str(Path(args.profile).expanduser().resolve())
    out = Path(args.out).expanduser().resolve()
    out.mkdir(parents=True, exist_ok=True)
    parts = [p.strip() for p in args.parts.split(",") if p.strip()]
    if not parts:
        ap.error("--parts names no part")

    created: list[Path] = []
    try:
        base_cwd, base_new = side_checkout(args.base, ROOT, out, "base")
        if base_new:
            created.append(base_cwd)
        head_cwd, head_new = side_checkout(args.head, ROOT, out, "head")
        if head_new:
            created.append(head_cwd)

        copies = {"base": out / "base.db", "head": out / "head.db"}
        copy_seconds = {side: copy_store(store, db) for side, db in copies.items()}
        builds = {side: build_side(copies[side], parts, cwd, profile, out, side)
                  for side, cwd in (("base", base_cwd), ("head", head_cwd))}

        diff = diff_store(copies["base"], copies["head"])
        gates = build_gates(builds["base"], builds["head"])
        gates += golden_gates(copies["head"], args.golden)
        gates += churn_gates(diff["tables"], args.max_churn, store, args.target)

        report = {
            "store": str(store),
            "base": {"ref": args.base, "path": str(base_cwd)},
            "head": {"ref": args.head, "path": str(head_cwd)},
            "parts": parts,
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "seconds": {"total": round(time.time() - started, 1), "copy": copy_seconds},
            "builds": builds,
            "tables": diff["tables"],
            "verdicts": diff["verdicts"],
            "gates": gates,
        }
        (out / "store_diff.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
        _write_markdown(report, out / "STORE_DIFF.md")
        print(json.dumps({"out": str(out), "tables": len(report["tables"]),
                          "changes": sum(t["removed"] + t["added"] + t["changed"] for t in report["tables"].values()),
                          "gates": len(gates), "seconds": report["seconds"]}, indent=1))
        return 1 if gates else 0
    finally:
        for path in created:
            _remove_worktree(ROOT, path, out)


if __name__ == "__main__":
    sys.exit(main())
