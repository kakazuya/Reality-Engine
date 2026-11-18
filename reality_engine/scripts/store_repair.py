"""T-218: repair one part of a built store, never the whole store (Shivam, 16 Nov 2026).

``python -m reality_engine.scripts.store_repair --stale --root D:/RealityEngine/tg_build``
    every store under the root and the parts built by older code (``pilot3/part_stamp.py``), with the reason.
``python -m reality_engine.scripts.store_repair --baseline auto --root <root> [--stores c01]``
    a store built before stamps existed is stamped with the code of the last commit before its file was written.
``python -m reality_engine.scripts.store_repair --part guidance --root <root> --stores c01,c02 [--note R-003]``
    re-run the part on each named store, then each part that reads from it, in build order, for as long as the
    rows it reads really changed (a part that wrote the same rows stops the chain).  ``--part stale`` re-runs
    whatever ``--stale`` lists for that store.  ``--no-dependants`` runs the named parts only.
``python -m reality_engine.scripts.store_repair --accept <run id> --root <root> --stores c01 [--accept-stale]``
    put a refused result in place after its diff was read by hand (refuses if the live store changed since the run,
    or if the run has no ``live_fingerprint`` unless ``--accept-stale`` is given after a hand check).
``python -m reality_engine.scripts.store_repair note add|set|list ...``
    the store-repair notes: one entry per defect (``tasks/store_repair/notes.jsonl`` + generated ``INDEX.md``).

One repair, per store:
1. copy the store to ``<store dir>/repair/<run id>/before.db`` (and the profile JSON beside it);
2. run each planned part as a child process on the live store, under the RAM and time watchdog of
   ``tg_measure_build.run_step`` (the build finds its OCR database and review files by the store's own name);
3. diff before against after with ``store_diff.diff_store``;
4. **gate**: a part that failed, or a table that lost a row (``removed`` > 0, or a served row no longer served),
   refuses the result: the store is put back as it was, ``live_fingerprint`` (post-checkpoint SHA-256 of the
   restored db) is recorded in ``run.json``, and the result is kept as ``after.db`` beside the diff, so a
   hand-read can ``--accept`` it without paying for the build again.  ``--approve-loss`` skips the row gate.
5. **accept**: ``--accept`` re-checkpoints the live store, recomputes its SHA-256, and refuses if it differs from
   ``live_fingerprint`` or ``run.json`` has none (old runs need ``--accept-stale`` after a hand check), so an accept
   never silently undoes a repair that ran in between.
A store is opened by one repair at a time (``repair.lock``).  Every run appends one line to ``<root>/repair_log.jsonl``.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import sys
import time
from pathlib import Path

from reality_engine.pilot3 import part_stamp
from reality_engine.scripts import store_diff

REPO = Path(__file__).resolve().parents[2]
NOTES_DIR = REPO / "tasks" / "store_repair"
STATUSES = ("open", "fix_written", "fixed", "wontfix")
NOTE_FIELDS = ("question", "store", "part", "symptom", "cause", "missing", "fix", "next", "status", "code", "tables",
               "tags", "scope", "kind", "kind_why", "companies_hit", "companies_of", "hit_basis", "trial_failed",
               "trial_companies")
# Shivam 16 Nov: every fix is located and written up like a notebook cell: what was wrong in the store and why, the
# fix, the code it lives in (``code``: file::function, comma list), the store tables it touches (``tables``), free
# ``tags`` to find it by, and whether it is a ``general`` rule or holds for one ``company`` only.
LIST_FIELDS = ("code", "tables", "tags")
SCOPES = ("general", "company")
# Shivam 17 Nov: every defect carries a severity and a criticality score, and fixes go in priority order.
#   severity    = how many companies the defect hits (companies_hit of companies_of; hit_basis says how it was
#                 counted: 'scan' of every store's tables, 'trial' graded answers, or 'suspect' unconfirmed scan hits);
#   criticality = what the defect does to the data (kind) and why (kind_why): 'wrong' (a row or reply is served as
#                 true and is not: the answer is wrong without warning) 3, 'corrupt' (the source text itself is
#                 damaged, e.g. a jumbled text layer, so rows read from it are lost or wrong) 2, 'missed' (the data is
#                 absent: the answer says not found) 1;
#   priority    = criticality x (companies hit + trial questions failed): more companies and more failed trial
#                 questions move a fix up; a wrong row outranks a missing one of the same reach.
KINDS = ("wrong", "corrupt", "missed")
CRITICALITY = {"wrong": 3, "corrupt": 2, "missed": 1}
INT_FIELDS = ("companies_hit", "companies_of", "trial_failed", "trial_companies")
HIT_BASES = ("scan", "trial", "suspect")
GRID_XLSX = REPO / "reports" / "store_repair_grid.xlsx"


# --- stores ------------------------------------------------------------------------------------------------------

def find_stores(root: Path) -> list[dict]:
    """Every ``<name>_profile.json`` under ``root`` with its ``<name>.db`` beside it, by name."""
    stores = []
    for profile in sorted(Path(root).rglob("*_profile.json")):
        if "repair" in profile.parts[len(Path(root).parts):]:
            continue
        name = profile.name[: -len("_profile.json")]
        db = profile.with_name(f"{name}.db")
        if db.is_file():
            stores.append({"name": name, "dir": profile.parent, "db": db, "profile": profile})
    return stores


def pick(stores: list[dict], names: str | None) -> list[dict]:
    if not names:
        return stores
    wanted = [n.strip() for n in names.split(",") if n.strip()]
    by_name = {s["name"]: s for s in stores}
    missing = [n for n in wanted if n not in by_name]
    if missing:
        raise SystemExit(f"no such store under the root: {', '.join(missing)}")
    return [by_name[n] for n in wanted]


def _is_locked_error(exc: sqlite3.OperationalError) -> bool:
    msg = str(exc).lower()
    return "locked" in msg or "busy" in msg


def stale_of(db: Path, hashes: dict[str, str]) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True, timeout=120)
    try:
        conn.execute("PRAGMA busy_timeout=120000")
        return part_stamp.stale(conn, hashes)
    finally:
        conn.close()


def current_hashes() -> dict[str, str]:
    return {part: part_stamp.code_hash(part) for part in part_stamp.ORDER}


def file_outs(store: dict) -> dict[str, str]:
    """Output hashes of the two steps that write files, not store tables: the profile JSON and ``pages.db``."""
    text = store["profile"].read_text(encoding="utf-8")
    outs = {"profile": hashlib.sha1(json.dumps(json.loads(text), sort_keys=True).encode()).hexdigest()[:16]}
    pages = Path(json.loads(text).get("pages_db") or store["dir"] / "pages.db")
    if pages.is_file():
        conn = sqlite3.connect(f"file:{pages.as_posix()}?mode=ro", uri=True)
        try:
            outs["docs_collect"] = "|".join(part_stamp.table_hash(conn, t) for t in ("doc", "doc_page"))
        finally:
            conn.close()
    return outs


# --- one repair --------------------------------------------------------------------------------------------------

def step_cmd(part: str, store: dict) -> list[str]:
    py = sys.executable
    if part == "profile":
        data = json.loads(store["profile"].read_text(encoding="utf-8"))
        cmd = [py, "-m", "reality_engine.pilot3.make_profile", *[c["symbol"] for c in data["companies"]],
               "--name", store["name"], "--root", str(store["dir"]), "--out", str(store["profile"])]
        for flag, key in (("--raw-root", "raw_root"), ("--window-start", "window_start"),
                          ("--compute-start", "compute_start")):
            if data.get(key):
                cmd += [flag, str(data[key])]
        return cmd
    if part == "docs_collect":
        return [py, "-m", "reality_engine.pilot3.docs_collect", "--profile", str(store["profile"])]
    return [py, "-m", "reality_engine.pilot3.build", "--profile", str(store["profile"]), "--out", str(store["db"]),
            "--part", part]


def default_runner(part: str, cmd: list[str], log: Path, ram_gb: float, timeout_s: float) -> dict:
    from reality_engine.scripts.tg_measure_build import run_step

    return run_step(part, cmd, log, interval_s=1.0, ram_gb=ram_gb, timeout_s=timeout_s)


def _store_ocr_dbs(store: dict) -> list[Path]:
    from reality_engine.pilot3 import build

    paths = [Path(p) for p in build.ocr_inputs(store["db"])]
    ocr_dir = store["dir"] / "ocr"
    if ocr_dir.is_dir():
        for p in sorted(ocr_dir.glob("*.db")):
            if p not in paths:
                paths.append(p)
    return [p for p in paths if p.is_file()]


def _ocr_pages(ocr_dbs) -> set[tuple[str, int]]:
    pages: set[tuple[str, int]] = set()
    for path in ocr_dbs or ():
        p = Path(path)
        if not p.is_file():
            continue
        con = sqlite3.connect(f"file:{p.as_posix()}?mode=ro", uri=True, timeout=30)
        try:
            for dk, pg in con.execute("SELECT DISTINCT doc_key, page FROM ocr_page"):
                if dk is not None and pg is not None:
                    pages.add((str(dk), int(pg)))
        except sqlite3.Error:
            pass
        finally:
            con.close()
    return pages


def _fin_quarter_printed_drops(before_db: Path, after_db: Path, ocr_dbs=()) -> tuple[int, int]:
    """Count ``(unconfirmed_drops, blocking_drops)`` among removed ``fin_quarter_printed`` rows.

    A removed row whose old ``check_status`` was ``'unchecked'`` and whose ``(doc_key, page)`` has OCR rows is
    an ``unconfirmed_drop`` (R-013); a removed ``CHECK_OK`` row is non-blocking only when an equal-value row
    for ``(symbol, basis, line_item, period_end, period_type)`` exists after.  Every other removal blocks."""
    from collections import Counter
    from reality_engine.pilot3.comparatives import CHECK_OK

    table = "fin_quarter_printed"
    base = store_diff.connect_ro(before_db, timeout_s=120)
    head = store_diff.connect_ro(after_db, timeout_s=120)
    try:
        if not store_diff._has_table(base, table):
            return 0, 0
        bc = store_diff._columns(base, table)
        hc = store_diff._columns(head, table) if store_diff._has_table(head, table) else []
        cols = list(dict.fromkeys([*bc, *hc]))

        def aligned(rows, table_cols):
            idx = {c: i for i, c in enumerate(table_cols)}
            return [tuple(store_diff._norm(r[idx[c]]) if c in idx else None for c in cols) for r in rows]

        base_rows = aligned(store_diff._fetch(base, table, bc), bc)
        head_rows = aligned(store_diff._fetch(head, table, hc), hc) if hc else []
    finally:
        base.close()
        head.close()

    keep = [i for i, c in enumerate(cols) if c not in store_diff.IGNORED_COLUMNS]

    def row_hash(row):
        return store_diff._hash(tuple(row[i] for i in keep))

    head_counts = Counter(row_hash(r) for r in head_rows)
    removed_rows: list[tuple] = []
    for row in base_rows:
        h = row_hash(row)
        if head_counts[h] > 0:
            head_counts[h] -= 1
        else:
            removed_rows.append(row)
    if not removed_rows:
        return 0, 0

    idx = {c: i for i, c in enumerate(cols)}
    after_values: dict[tuple, list] = {}
    for row in head_rows:
        key = tuple(row[idx[c]] if c in idx else None
                    for c in ("symbol", "basis", "line_item", "period_end", "period_type"))
        after_values.setdefault(key, []).append(row[idx["value"]] if "value" in idx else None)

    ocr_pages = _ocr_pages(ocr_dbs)
    unconfirmed_drops = 0
    blocking_drops = 0
    for row in removed_rows:
        status = row[idx["check_status"]] if "check_status" in idx else None
        dk = row[idx["doc_key"]] if "doc_key" in idx else None
        pg = row[idx["page"]] if "page" in idx else None
        if status == "unchecked" and dk is not None and pg is not None and (str(dk), int(pg)) in ocr_pages:
            unconfirmed_drops += 1
        elif status in CHECK_OK:
            key = tuple(row[idx[c]] if c in idx else None
                        for c in ("symbol", "basis", "line_item", "period_end", "period_type"))
            old_val = row[idx["value"]] if "value" in idx else None
            candidates = after_values.get(key, ())
            if old_val is None:
                matched = any(v is None for v in candidates)
            else:
                matched = any(v is not None and abs(float(v) - float(old_val)) <= 1e-6 * max(
                    1.0, abs(float(v)), abs(float(old_val))) for v in candidates)
            if not matched:
                blocking_drops += 1
        else:
            blocking_drops += 1
    return unconfirmed_drops, blocking_drops


def losses(diff: dict, before_db: Path | None = None, after_db: Path | None = None, ocr_dbs=()) -> list[dict]:
    """Tables of a ``diff_store`` report that lost a row or a served row."""
    out = []
    for name, table in sorted(diff["tables"].items()):
        removed = int(table.get("removed") or 0)
        lost = int((table.get("served") or {}).get("lost") or 0)
        if removed or lost:
            entry = {"table": name, "removed": removed, "served_lost": lost, "added": int(table.get("added") or 0),
                     "changed": int(table.get("changed") or 0)}
            if name == "fin_quarter_printed" and removed and before_db is not None and after_db is not None:
                unconfirmed_drops, blocking_drops = _fin_quarter_printed_drops(before_db, after_db, ocr_dbs)
                entry["unconfirmed_drops"] = unconfirmed_drops
                if not lost and not blocking_drops:
                    entry["non_blocking"] = True
            out.append(entry)
    return out


def _has_blocking_losses(loss_entries: list[dict]) -> bool:
    blocking = False
    for entry in loss_entries:
        if not entry.pop("non_blocking", False):
            blocking = True
    return blocking


def summary_of(diff: dict) -> dict:
    return {name: {k: int(t.get(k) or 0) for k in ("removed", "added", "changed")}
            for name, t in sorted(diff["tables"].items())
            if t.get("removed") or t.get("added") or t.get("changed")}


def _live_fingerprint(db: Path) -> str:
    """SHA-256 of the live store file after a WAL checkpoint."""
    store_diff._checkpoint(db)
    digest = hashlib.sha256()
    with open(db, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _restore(store: dict, run_dir: Path, keep_after: bool) -> None:
    """Put the store and its profile back as they were; keep the refused result as ``after.db`` when asked."""
    try:
        for suffix in ("-wal", "-shm"):
            Path(f"{store['db']}{suffix}").unlink(missing_ok=True)
    except OSError:
        # Another reader still holds -wal/-shm open (e.g. on Windows): restore pages via SQLite's backup API.
        src = sqlite3.connect(f"file:{(run_dir / 'before.db').as_posix()}?mode=ro", uri=True, timeout=30)
        dst = sqlite3.connect(store["db"], timeout=30)
        try:
            dst.execute("PRAGMA busy_timeout=30000")
            src.backup(dst)
        finally:
            dst.close()
            src.close()
        shutil.copy2(run_dir / "before_profile.json", store["profile"])
        return
    if keep_after:
        shutil.copy2(store["db"], run_dir / "after.db")
        shutil.copy2(store["profile"], run_dir / "after_profile.json")
    shutil.copy2(run_dir / "before.db", store["db"])
    shutil.copy2(run_dir / "before_profile.json", store["profile"])


def repair_store(store: dict, parts: list[str], run_id: str, approve_loss: bool = False, runner=None,
                 ram_gb: float = 4.0, timeout_s: float = 2400.0, forced=None, hashes=None) -> dict:
    """Re-run ``parts`` (already in build order) on one store behind the diff gate; returns the run record.

    ``forced`` are the parts that run whatever their stamp says (default: all of ``parts``); every other part runs
    only if it is stale when its turn comes, so a re-run that wrote the same rows stops the chain there."""
    runner = default_runner if runner is None else runner
    run_dir = store["dir"] / "repair" / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    lock = store["dir"] / "repair.lock"
    try:
        fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        return {"store": store["name"], "run": run_id, "parts": parts, "outcome": "locked",
                "detail": f"{lock} exists: another repair holds this store (delete it if that run is dead)"}
    os.close(fd)
    started = time.time()
    record = {"store": store["name"], "run": run_id, "parts": parts, "steps": [], "outcome": "", "losses": [],
              "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "git_head": part_stamp.git_head()}
    try:
        store_diff.copy_store(store["db"], run_dir / "before.db")
        shutil.copy2(store["profile"], run_dir / "before_profile.json")
        for part in parts:
            ran = [step["part"] for step in record["steps"] if "skipped" not in step]
            if (forced is not None and part not in forced and not any(part_stamp.rewrites(r, part) for r in ran)
                    and part not in stale_of(store["db"], hashes or {})):
                record["steps"].append({"part": part, "skipped": "inputs unchanged"})
                continue
            row = runner(part, step_cmd(part, store), run_dir / f"{part}.log", ram_gb, timeout_s)
            record["steps"].append({k: row.get(k) for k in ("part", "seconds", "rc", "peak_rss_mb", "ram_stop",
                                                              "timed_out")})
            if row.get("rc") != 0 or row.get("ram_stop") or row.get("timed_out"):
                record.update(outcome="failed", detail=f"{part}: rc={row.get('rc')} {row.get('tail5') or ''}"[:600])
                _restore(store, run_dir, keep_after=False)
                return record
            if part in ("profile", "docs_collect"):       # not build parts: the runner stamps them itself
                conn = sqlite3.connect(store["db"], timeout=120)
                try:
                    conn.execute("PRAGMA busy_timeout=120000")
                    part_stamp.write(conn, part, row.get("seconds"), out=file_outs(store).get(part, ""))
                finally:
                    conn.close()
        store_diff._checkpoint(store["db"])
        diff = store_diff.diff_store(run_dir / "before.db", store["db"])
        (run_dir / "diff.json").write_text(json.dumps(diff, indent=1, default=str), encoding="utf-8")
        record["diff"] = summary_of(diff)
        record["losses"] = losses(diff, run_dir / "before.db", store["db"], _store_ocr_dbs(store))
        if _has_blocking_losses(record["losses"]) and not approve_loss:
            record.update(outcome="refused", detail=f"rows lost; read {run_dir / 'diff.json'}, then --accept {run_id}")
            _restore(store, run_dir, keep_after=True)
            record["live_fingerprint"] = _live_fingerprint(store["db"])
        else:
            record["outcome"] = "repaired"
        return record
    except sqlite3.OperationalError as exc:
        if not _is_locked_error(exc):
            raise
        if (run_dir / "before.db").is_file() and (run_dir / "before_profile.json").is_file():
            try:
                _restore(store, run_dir, keep_after=False)
            except Exception as restore_exc:  # noqa: BLE001 - keep multi-store run alive even if restore hits lock
                record.update(outcome="skipped: database locked",
                              detail=f"{exc}; restore failed: {restore_exc}"[:600])
                return record
        record.update(outcome="skipped: database locked", detail=str(exc)[:600])
        return record
    finally:
        record["seconds"] = round(time.time() - started, 1)
        (run_dir / "run.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
        lock.unlink(missing_ok=True)
        _prune(store["dir"] / "repair", keep=run_id)


def _prune(repair_dir: Path, keep: str, backups: int = 2) -> None:
    """Keep the logs and diffs of every run, but the database copies of the newest ``backups`` runs only."""
    runs = sorted((d for d in repair_dir.iterdir() if d.is_dir()), key=lambda d: d.name, reverse=True)
    for old in [d for d in runs if d.name != keep][backups - 1:]:
        for name in ("before.db", "after.db"):
            (old / name).unlink(missing_ok=True)


def accept(store: dict, run_id: str, accept_stale: bool = False) -> dict:
    """Put a refused run's ``after.db`` in place (after a hand-read of its diff), if the live store is unchanged."""
    run_dir = store["dir"] / "repair" / run_id
    after = run_dir / "after.db"
    if not after.is_file():
        return {"store": store["name"], "run": run_id, "outcome": "nothing to accept", "detail": f"no {after}"}
    run_json = run_dir / "run.json"
    record = json.loads(run_json.read_text(encoding="utf-8")) if run_json.is_file() else {
        "store": store["name"], "run": run_id
    }
    recorded_fp = record.get("live_fingerprint")
    current_fp = _live_fingerprint(store["db"])
    if not recorded_fp:
        if not accept_stale:
            return {
                "store": store["name"],
                "run": run_id,
                "outcome": "refused",
                "detail": (
                    f"{store['name']} run {run_id}: no live_fingerprint in run.json (old run) — cannot verify "
                    "whether the live store changed after this run (another repair or part ran); "
                    "re-run the repair instead (or pass --accept-stale after a hand check)"
                ),
            }
    elif current_fp != recorded_fp:
        return {
            "store": store["name"],
            "run": run_id,
            "outcome": "refused",
            "detail": (
                f"{store['name']} run {run_id}: the live store changed after this run "
                "(another repair or part ran); re-run the repair instead"
            ),
        }
    for suffix in ("-wal", "-shm"):
        Path(f"{store['db']}{suffix}").unlink(missing_ok=True)
    shutil.copy2(after, store["db"])
    shutil.copy2(run_dir / "after_profile.json", store["profile"])
    after.unlink()
    record.update(outcome="repaired", accepted_at=time.strftime("%Y-%m-%dT%H:%M:%S"), accepted_by_hand=True)
    if accept_stale and not recorded_fp:
        record["accepted_stale"] = True
    run_json.write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    return record


# --- notes -------------------------------------------------------------------------------------------------------

def read_notes(notes_dir: Path = NOTES_DIR) -> list[dict]:
    path = notes_dir / "notes.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def scores(note: dict) -> dict:
    """severity, criticality and priority of one note (Shivam 17 Nov); empty strings where the note is not scored."""
    crit = CRITICALITY.get(note.get("kind") or "")
    hit, of = note.get("companies_hit"), note.get("companies_of")
    severity = f"{hit}/{of}" if hit is not None and of else (str(hit) if hit is not None else "")
    priority = crit * ((hit or 0) + (note.get("trial_failed") or 0)) if crit and hit is not None else ""
    return {"severity": severity, "criticality": crit or "", "priority": priority}


def by_priority(notes: list[dict]) -> list[dict]:
    """open and fix_written notes, highest priority first (unscored last), then fixed and wontfix."""
    def key(n):
        pr = scores(n)["priority"]
        return (n.get("status") not in ("open", "fix_written"), pr == "", -(pr or 0), n["id"])
    return sorted(notes, key=key)


def write_notes(notes: list[dict], notes_dir: Path = NOTES_DIR) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "notes.jsonl").write_text(
        "".join(json.dumps(n, ensure_ascii=False) + "\n" for n in notes), encoding="utf-8", newline="\n")
    def joined(value) -> str:
        return ", ".join(value) if isinstance(value, list) else str(value or "")

    lines = ["# Store-repair notes (generated from notes.jsonl by `store_repair note`; do not edit by hand)", "",
             "One entry per store defect or patch, five points each (Shivam 16 Nov): why it had to be done, what the "
             "problem was, what was missing, how it was fixed, what can come next; then the code and store tables it "
             "touches, its tags and scope, the stores repaired. Stores "
             "are named by their build folder, never by company. Grid of stores x parts: "
             "`reports/store_repair_grid.xlsx` (`store_repair note grid`).", "",
             "Order of work (Shivam 17 Nov): **severity** = companies hit (of the stores counted; basis scan / trial "
             "/ suspect), **criticality** = kind of damage: wrong 3 (served as true, answer wrong without warning), "
             "corrupt 2 (source text damaged), missed 1 (absent, answer says not found); **priority** = criticality "
             "x (companies hit + trial questions failed). Live notes are listed highest priority first.", "",
             "| id | status | kind | severity (basis) | criticality | trial failed (companies) | priority | part "
             "| scope | stores repaired |", "|---|---|---|---|---|---|---|---|---|---|"]
    for n in by_priority(notes):
        sc = scores(n)
        trial = (f"{n['trial_failed']} ({n.get('trial_companies', '-')})" if n.get("trial_failed") is not None
                 else "")
        cells = [n["id"], n["status"], n.get("kind") or "",
                 f"{sc['severity']} ({n.get('hit_basis') or '-'})" if sc["severity"] else "", sc["criticality"],
                 trial, sc["priority"], n.get("part") or "", n.get("scope") or "", joined(n.get("repaired"))]
        lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    for n in notes:
        lines += ["", f"## {n['id']} ({n['status']}, part `{n.get('part') or '-'}`, opened {n.get('opened') or '-'})",
                  "", f"1. **Why it had to be done** (question that exposed it, {n.get('store') or '-'}): "
                  f"{n.get('question') or '-'}",
                  f"2. **What the problem was:** {n.get('symptom') or '-'} **Root cause:** {n.get('cause') or '-'}",
                  f"3. **What was missing:** {n.get('missing') or '-'}",
                  f"4. **How it was fixed:** {n.get('fix') or '-'}",
                  f"5. **What can come next:** {n.get('next') or '-'}",
                  f"- **Kind:** {n.get('kind') or '-'} ({n.get('kind_why') or '-'}); **severity:** "
                  f"{scores(n)['severity'] or '-'} companies ({n.get('hit_basis') or '-'}); **criticality:** "
                  f"{scores(n)['criticality'] or '-'}; **trial questions failed:** "
                  f"{n.get('trial_failed') if n.get('trial_failed') is not None else '-'}; "
                  f"**priority:** {scores(n)['priority'] or '-'}",
                  f"- **Code:** {joined(n.get('code')) or '-'}",
                  f"- **Store tables touched:** {joined(n.get('tables')) or '-'}",
                  f"- **Tags:** {joined(n.get('tags')) or '-'}; **scope:** {n.get('scope') or '-'}",
                  f"- **Stores repaired:** {joined(n.get('repaired')) or '-'}; runs: {joined(n.get('runs')) or '-'}"]
    (notes_dir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


COMPLETENESS_COLUMNS = ["store", "symbol", "xbrl_quarters", "xbrl_latest", "printed_quarters", "shp_xbrl_quarters",
                        "shp_index_quarters", "shp_latest", "transcripts", "transcript_latest", "guidance_rows",
                        "kpi_verified", "kpi_unverified", "kpi_quarantined", "order_wins", "decks", "annual_reports",
                        "results_docs", "latest_doc", "price_latest"]


def completeness(db: Path | str, since: str = "2024-04-01") -> dict:
    """What one store holds per part, counted from its own tables (no model): the sign-off check for a company.

    Shivam 16 Nov: a company is signed off part by part; an empty count is 'not extracted' or 'not filed' and is
    told apart by the repair notes (R-002: no call filed on either exchange), never assumed."""
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

    def one(sql: str, *args):
        try:
            return conn.execute(sql, args).fetchone()[0]
        except sqlite3.Error:
            return None

    kpi = dict(conn.execute("SELECT status, COUNT(*) FROM row_check WHERE tbl='kpi_series' GROUP BY status")
               ) if one("SELECT COUNT(*) FROM sqlite_master WHERE name='row_check'") else {}
    docs = dict(conn.execute("SELECT doc_type, COUNT(*) FROM doc GROUP BY doc_type")
                ) if one("SELECT COUNT(*) FROM sqlite_master WHERE name='doc'") else {}
    out = {
        "symbol": one("SELECT group_concat(symbol) FROM company"),
        "xbrl_quarters": one("SELECT COUNT(DISTINCT period_end) FROM fin_quarter_xbrl WHERE period_end >= ? "
                             "AND julianday(period_end) - julianday(period_start) < 100", since),
        "xbrl_latest": one("SELECT MAX(period_end) FROM fin_quarter_xbrl"),
        "printed_quarters": one("SELECT COUNT(DISTINCT period_end) FROM fin_quarter_printed WHERE period_end >= ? "
                                "AND period_type = 'quarter'", since),
        "shp_xbrl_quarters": one("SELECT COUNT(DISTINCT quarter_end) FROM shp_category WHERE source_kind='xbrl'"),
        "shp_index_quarters": one("SELECT COUNT(DISTINCT quarter_end) FROM shp_category WHERE source_kind='index'"),
        "shp_latest": one("SELECT MAX(quarter_end) FROM shp_category"),
        "transcripts": docs.get("transcript", 0),
        "transcript_latest": one("SELECT MAX(filing_date) FROM doc WHERE doc_type='transcript'"),
        "guidance_rows": one("SELECT COUNT(*) FROM guidance"),
        "kpi_verified": kpi.get("verified", 0), "kpi_unverified": kpi.get("unverified", 0),
        "kpi_quarantined": kpi.get("quarantined", 0),
        "order_wins": one("SELECT COUNT(*) FROM order_win"),
        "decks": docs.get("deck", 0), "annual_reports": docs.get("annual_report", 0),
        "results_docs": docs.get("results", 0),
        "latest_doc": one("SELECT MAX(filing_date) FROM doc"),
        "price_latest": one("SELECT MAX(date) FROM price_delivery"),
    }
    conn.close()
    return out


def write_grid(root: Path, notes: list[dict] | None = None, out: Path = GRID_XLSX) -> Path:
    """Excel workbook: sheet ``grid`` has one row per store and one column per part (the notebook view: each cell
    says whether that part of that store is up to date and which notes repaired it); sheet ``notes`` lists every
    note with all its fields."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    notes = read_notes() if notes is None else notes
    wb = Workbook()
    ws = wb.active
    ws.title = "grid"
    parts = list(part_stamp.ORDER)
    ws.append(["store", *parts])
    fills = {"ok": PatternFill("solid", fgColor="D9EAD3"), "stale": PatternFill("solid", fgColor="FCE5CD")}
    for store in find_stores(root):
        try:
            conn = sqlite3.connect(f"file:{store['db']}?mode=ro", uri=True)
            stale = dict(part_stamp.stale(conn))
            conn.close()
        except Exception as exc:  # noqa: BLE001 - one unreadable store is one row saying so
            stale = {p: f"unreadable: {exc}" for p in parts}
        row = [store["name"]]
        for part in parts:
            ids = [n["id"] for n in notes if n.get("part") == part and store["name"] in (n.get("repaired") or [])]
            state = stale.get(part)
            row.append(("stale: " + state if state else "ok") + (f" | {', '.join(ids)}" if ids else ""))
        ws.append(row)
        for cell in ws[ws.max_row][1:]:
            cell.fill = fills["stale" if str(cell.value).startswith(("stale", "unreadable")) else "ok"]
    for cell in ws[1]:
        cell.font = Font(bold=True)
    done = wb.create_sheet("completeness")
    done.append(COMPLETENESS_COLUMNS)
    for store in find_stores(root):
        try:
            row = completeness(store["db"])
        except Exception as exc:  # noqa: BLE001 - one unreadable store is one row saying so
            row = {"symbol": f"unreadable: {exc}"}
        done.append([store["name"], *[row.get(c) for c in COMPLETENESS_COLUMNS[1:]]])
    for cell in done[1]:
        cell.font = Font(bold=True)
    sheet = wb.create_sheet("notes")
    columns = ["id", "status", "opened", "part", "scope", "tags", "symptom", "cause", "missing", "fix", "next", "code",
               "tables", "question", "store", "repaired", "runs", "kind", "kind_why", "severity", "hit_basis",
               "criticality", "trial_failed", "trial_companies", "priority"]
    sheet.append(columns)
    for n in by_priority(notes):
        row = {**n, **scores(n)}
        sheet.append([", ".join(row[c]) if isinstance(row.get(c), list) else row.get(c) for c in columns])
    for cell in sheet[1]:
        cell.font = Font(bold=True)
    for col, width in zip("ABCDEFGHIJKLMNOPQ", (7, 11, 11, 13, 10, 24, 50, 60, 50, 60, 50, 40, 30, 50, 12, 30, 24)):
        sheet.column_dimensions[col].width = width
    for row in sheet.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    out.parent.mkdir(parents=True, exist_ok=True)
    wb.save(out)
    return out


def tally(graded: Path, note_map: Path, notes_dir: Path = NOTES_DIR) -> dict:
    """Count each note's failed trial questions and companies from a trial's ``graded.jsonl`` and a ``{qid: note
    id}`` map (the attribution of each non-right answer to the defect behind it), and write them on the notes."""
    owner = {str(k): v for k, v in json.loads(note_map.read_text(encoding="utf-8")).items()}
    failed: dict[str, list] = {}
    for line in graded.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        if r.get("grade") in ("right", "scope_out"):
            continue
        nid = owner.get(str(r["qid"]))
        if nid is None:
            raise SystemExit(f"qid {r['qid']} ({r.get('grade')}) has no note in {note_map}")
        failed.setdefault(nid, []).append(r["symbol"])
    notes = read_notes(notes_dir)
    unknown = sorted(set(failed) - {n["id"] for n in notes})
    if unknown:
        raise SystemExit(f"map names notes that do not exist: {unknown}")
    for n in notes:
        if n["id"] in failed:
            n["trial_failed"], n["trial_companies"] = len(failed[n["id"]]), len(set(failed[n["id"]]))
    write_notes(notes, notes_dir)
    return {k: {"failed": len(v), "companies": len(set(v))} for k, v in sorted(failed.items())}


def note_add(fields: dict, notes_dir: Path = NOTES_DIR) -> dict:
    notes = read_notes(notes_dir)
    number = max((int(n["id"].split("-")[1]) for n in notes), default=0) + 1
    note = {"id": f"R-{number:03d}", "opened": time.strftime("%Y-%m-%d"), "status": "open", "repaired": [], "runs": [],
            **{k: v for k, v in fields.items() if v not in (None, "", [])}}
    notes.append(note)
    write_notes(notes, notes_dir)
    return note


def note_set(note_id: str, fields: dict, repaired=(), run: str | None = None, notes_dir: Path = NOTES_DIR) -> dict:
    notes = read_notes(notes_dir)
    for note in notes:
        if note["id"] == note_id:
            note.update({k: v for k, v in fields.items() if v not in (None, "", [])})
            note["repaired"] = sorted(set(note.get("repaired") or []) | set(repaired))
            if run and run not in note.setdefault("runs", []):
                note["runs"].append(run)
            write_notes(notes, notes_dir)
            return note
    raise SystemExit(f"no note {note_id}")


def note_main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(prog="store_repair note")
    sub = ap.add_subparsers(dest="cmd", required=True)
    add, change, _listing = sub.add_parser("add"), sub.add_parser("set"), sub.add_parser("list")
    grid = sub.add_parser("grid", help="write reports/store_repair_grid.xlsx: stores x parts, and every note")
    grid.add_argument("--root", required=True, help="folder holding the stores")
    tal = sub.add_parser("tally", help="write each note's failed trial questions/companies from a graded trial")
    tal.add_argument("--graded", required=True, help="the trial's graded.jsonl")
    tal.add_argument("--map", required=True, help="JSON {qid: note id} for every non-right answer")
    change.add_argument("id")
    change.add_argument("--repaired", default="", help="comma list of stores repaired for this defect")
    for p in (add, change):
        for name in NOTE_FIELDS:
            p.add_argument(f"--{name}", default=None,
                           choices=STATUSES if name == "status" else SCOPES if name == "scope" else
                           KINDS if name == "kind" else HIT_BASES if name == "hit_basis" else None,
                           type=int if name in INT_FIELDS else str,
                           help="comma list" if name in LIST_FIELDS else None)
    args = ap.parse_args(argv)
    if args.cmd == "grid":
        print(write_grid(Path(args.root)))
        return 0
    if args.cmd == "tally":
        print(json.dumps(tally(Path(args.graded), Path(args.map)), indent=1))
        return 0
    fields = {name: getattr(args, name, None) for name in NOTE_FIELDS}
    for name in LIST_FIELDS:
        if fields[name]:
            fields[name] = [s.strip() for s in fields[name].split(",") if s.strip()]
    if args.cmd == "add":
        if not (fields["part"] and fields["symptom"] and fields["kind"] and fields["kind_why"]
                and fields["companies_hit"] is not None and fields["companies_of"] and fields["hit_basis"]):
            raise SystemExit("note add needs --part, --symptom and the scores (Shivam 17 Nov): --kind, --kind_why, "
                             "--companies_hit, --companies_of, --hit_basis")
        print(json.dumps(note_add(fields), indent=1, ensure_ascii=False))
    elif args.cmd == "set":
        print(json.dumps(note_set(args.id, fields, [s for s in args.repaired.split(",") if s]), indent=1,
                         ensure_ascii=False))
    else:
        for n in by_priority(read_notes()):
            sc = scores(n)
            print(f"{n['id']} {n['status']:<11} p={sc['priority'] if sc['priority'] != '' else '-':<4} "
                  f"{n.get('kind') or '-':<8} sev={sc['severity'] or '-':<7} {n.get('part') or '-':<12} "
                  f"{(n.get('symptom') or '')[:90]}  [repaired: {', '.join(n.get('repaired') or []) or '-'}]")
    return 0


# --- CLI ---------------------------------------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "note":
        return note_main(argv[1:])
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", required=True, help="folder holding the stores (searched for <name>_profile.json)")
    ap.add_argument("--stale", action="store_true", help="list the parts built by older code")
    ap.add_argument("--part", default=None, help="comma list of parts to re-run, or 'stale'")
    ap.add_argument("--accept", default=None, metavar="RUN_ID", help="put a refused run's result in place")
    ap.add_argument("--accept-stale", action="store_true",
                    help="with --accept, override only for an old run without live_fingerprint after a hand check")
    ap.add_argument("--baseline", default=None, metavar="COMMIT|auto",
                    help="stamp stores built before stamps existed with that commit's code ('auto': the last "
                         "commit before the store file was written), so --stale lists only what changed since")
    ap.add_argument("--stores", default=None, help="comma list of store names (default: every store, for --stale)")
    ap.add_argument("--no-dependants", action="store_true", help="run the named parts only")
    ap.add_argument("--approve-loss", action="store_true", help="keep a result that lost rows (read the diff first)")
    ap.add_argument("--note", default=None, help="store-repair note id this run fixes (R-NNN)")
    ap.add_argument("--ram-gb", type=float, default=4.0)
    ap.add_argument("--max-part-minutes", type=float, default=40.0)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    root = Path(args.root)
    stores = find_stores(root)
    hashes = current_hashes()

    if args.baseline:
        for store in pick(stores, args.stores):
            built = store["db"].stat().st_mtime
            commit = part_stamp.commit_before(built) if args.baseline == "auto" else args.baseline
            if not commit:
                print(f"{store['name']}: no commit before the store was written; not stamped")
                continue
            conn = sqlite3.connect(store["db"])
            try:
                done = part_stamp.baseline(conn, commit, built, file_outs(store))
            finally:
                conn.close()
            print(f"{store['name']}: baseline {commit}, {len(done)} parts stamped")
        return 0
    if args.accept_stale and not args.accept:
        raise SystemExit("--accept-stale needs --accept")
    if args.accept:
        if not args.stores:
            raise SystemExit("--accept needs --stores")
        records = [accept(store, args.accept, accept_stale=args.accept_stale) for store in pick(stores, args.stores)]
    elif args.part:
        if not args.stores:
            raise SystemExit("--part needs --stores: one company at a time (ruling 15 Nov), name the stores")
        run_id = time.strftime("%Y%m%dT%H%M%S")
        records = []
        for store in pick(stores, args.stores):
            if args.part == "stale":
                try:
                    behind = stale_of(store["db"], hashes)
                except sqlite3.OperationalError as exc:
                    if not _is_locked_error(exc):
                        raise
                    records.append({"store": store["name"], "run": run_id, "parts": [],
                                    "outcome": "skipped: database locked", "detail": str(exc)[:600]})
                    continue
                parts = [p for p in part_stamp.ORDER if p in behind]
                # only a part behind for its own reason must run; the rest run if their inputs really change
                named = [p for p in parts if behind[p] in ("code changed", "never stamped")]
            else:
                named = [p.strip() for p in args.part.split(",") if p.strip()]
                unknown = [p for p in named if p not in part_stamp.ORDER]
                if unknown:
                    raise SystemExit(f"unknown part: {', '.join(unknown)}; parts: {', '.join(part_stamp.ORDER)}")
                parts = ([p for p in part_stamp.ORDER if p in named] if args.no_dependants
                         else part_stamp.dependants(named))
            if not parts:
                records.append({"store": store["name"], "run": run_id, "parts": [], "outcome": "nothing stale"})
                continue
            print(f"{store['name']}: {' -> '.join(parts)}", flush=True)
            record = repair_store(store, parts, run_id, args.approve_loss, ram_gb=args.ram_gb,
                                  timeout_s=args.max_part_minutes * 60, forced=set(named), hashes=hashes)
            records.append(record)
    elif args.stale:
        report = [{"store": s["name"], "db": str(s["db"]), "stale": stale_of(s["db"], hashes)} for s in pick(stores, args.stores)]
        if args.json:
            print(json.dumps(report, indent=1))
        else:
            for row in report:
                print(f"{row['store']}: " + ("up to date" if not row["stale"] else
                                             "; ".join(f"{p} [{why}]" for p, why in row["stale"].items())))
            print(f"{len(report)} stores under {root}; {sum(1 for r in report if r['stale'])} with stale parts")
        return 0
    else:
        raise SystemExit("give --stale, --part or --accept")

    with open(root / "repair_log.jsonl", "a", encoding="utf-8") as log:
        for record in records:
            log.write(json.dumps({k: v for k, v in record.items() if k != "steps"}, default=str) + "\n")
    done = [r["store"] for r in records if r.get("outcome") == "repaired"]
    if args.note and done:
        note_set(args.note, {}, done, records[0]["run"])
    for record in records:
        print(f"{record['store']}: {record.get('outcome')} {record.get('seconds', '')}s "
              f"{json.dumps(record.get('diff') or {})} {record.get('detail') or ''}", flush=True)
    return 0 if all(r.get("outcome") in ("repaired", "nothing stale") for r in records) else 1


if __name__ == "__main__":
    sys.exit(main())
