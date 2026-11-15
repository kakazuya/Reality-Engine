"""T-218: repair one part of a built store, never the whole store (Shivam, 16 Nov 2026).

``python -m reality_engine.scripts.store_repair --stale --root D:/RealityEngine/tg_build``
    every store under the root and the parts built by older code (``pilot3/part_stamp.py``), with the reason.
``python -m reality_engine.scripts.store_repair --baseline auto --root <root> [--stores c01]``
    a store built before stamps existed is stamped with the code of the last commit before its file was written.
``python -m reality_engine.scripts.store_repair --part guidance --root <root> --stores c01,c02 [--note R-003]``
    re-run the part on each named store, then each part that reads from it, in build order, for as long as the
    rows it reads really changed (a part that wrote the same rows stops the chain).  ``--part stale`` re-runs
    whatever ``--stale`` lists for that store.  ``--no-dependants`` runs the named parts only.
``python -m reality_engine.scripts.store_repair --accept <run id> --root <root> --stores c01``
    put a refused result in place after its diff was read by hand.
``python -m reality_engine.scripts.store_repair note add|set|list ...``
    the store-repair notes: one entry per defect (``tasks/store_repair/notes.jsonl`` + generated ``INDEX.md``).

One repair, per store:
1. copy the store to ``<store dir>/repair/<run id>/before.db`` (and the profile JSON beside it);
2. run each planned part as a child process on the live store, under the RAM and time watchdog of
   ``tg_measure_build.run_step`` (the build finds its OCR database and review files by the store's own name);
3. diff before against after with ``store_diff.diff_store``;
4. **gate**: a part that failed, or a table that lost a row (``removed`` > 0, or a served row no longer served),
   refuses the result: the store is put back as it was and the result is kept as ``after.db`` beside the diff, so a
   hand-read can ``--accept`` it without paying for the build again.  ``--approve-loss`` skips the row gate.
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
NOTE_FIELDS = ("question", "store", "part", "symptom", "cause", "fix", "status")


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


def stale_of(db: Path, hashes: dict[str, str]) -> dict[str, str]:
    conn = sqlite3.connect(f"file:{db.as_posix()}?mode=ro", uri=True)
    try:
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


def losses(diff: dict) -> list[dict]:
    """Tables of a ``diff_store`` report that lost a row or a served row."""
    out = []
    for name, table in sorted(diff["tables"].items()):
        removed = int(table.get("removed") or 0)
        lost = int((table.get("served") or {}).get("lost") or 0)
        if removed or lost:
            out.append({"table": name, "removed": removed, "served_lost": lost, "added": int(table.get("added") or 0),
                        "changed": int(table.get("changed") or 0)})
    return out


def summary_of(diff: dict) -> dict:
    return {name: {k: int(t.get(k) or 0) for k in ("removed", "added", "changed")}
            for name, t in sorted(diff["tables"].items())
            if t.get("removed") or t.get("added") or t.get("changed")}


def _restore(store: dict, run_dir: Path, keep_after: bool) -> None:
    """Put the store and its profile back as they were; keep the refused result as ``after.db`` when asked."""
    for suffix in ("-wal", "-shm"):
        Path(f"{store['db']}{suffix}").unlink(missing_ok=True)
    if keep_after:
        shutil.copy2(store["db"], run_dir / "after.db")
        shutil.copy2(store["profile"], run_dir / "after_profile.json")
    shutil.copy2(run_dir / "before.db", store["db"])
    shutil.copy2(run_dir / "before_profile.json", store["profile"])


def repair_store(store: dict, parts: list[str], run_id: str, approve_loss: bool = False, runner=default_runner,
                 ram_gb: float = 4.0, timeout_s: float = 2400.0, forced=None, hashes=None) -> dict:
    """Re-run ``parts`` (already in build order) on one store behind the diff gate; returns the run record.

    ``forced`` are the parts that run whatever their stamp says (default: all of ``parts``); every other part runs
    only if it is stale when its turn comes, so a re-run that wrote the same rows stops the chain there."""
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
                conn = sqlite3.connect(store["db"])
                try:
                    part_stamp.write(conn, part, row.get("seconds"), out=file_outs(store).get(part, ""))
                finally:
                    conn.close()
        store_diff._checkpoint(store["db"])
        diff = store_diff.diff_store(run_dir / "before.db", store["db"])
        (run_dir / "diff.json").write_text(json.dumps(diff, indent=1, default=str), encoding="utf-8")
        record["diff"] = summary_of(diff)
        record["losses"] = losses(diff)
        if record["losses"] and not approve_loss:
            record.update(outcome="refused", detail=f"rows lost; read {run_dir / 'diff.json'}, then --accept {run_id}")
            _restore(store, run_dir, keep_after=True)
        else:
            record["outcome"] = "repaired"
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


def accept(store: dict, run_id: str) -> dict:
    """Put a refused run's ``after.db`` in place (after a hand-read of its diff)."""
    run_dir = store["dir"] / "repair" / run_id
    after = run_dir / "after.db"
    if not after.is_file():
        return {"store": store["name"], "run": run_id, "outcome": "nothing to accept", "detail": f"no {after}"}
    for suffix in ("-wal", "-shm"):
        Path(f"{store['db']}{suffix}").unlink(missing_ok=True)
    shutil.copy2(after, store["db"])
    shutil.copy2(run_dir / "after_profile.json", store["profile"])
    after.unlink()
    record = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    record.update(outcome="repaired", accepted_at=time.strftime("%Y-%m-%dT%H:%M:%S"), accepted_by_hand=True)
    (run_dir / "run.json").write_text(json.dumps(record, indent=1, default=str), encoding="utf-8")
    return record


# --- notes -------------------------------------------------------------------------------------------------------

def read_notes(notes_dir: Path = NOTES_DIR) -> list[dict]:
    path = notes_dir / "notes.jsonl"
    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write_notes(notes: list[dict], notes_dir: Path = NOTES_DIR) -> None:
    notes_dir.mkdir(parents=True, exist_ok=True)
    (notes_dir / "notes.jsonl").write_text(
        "".join(json.dumps(n, ensure_ascii=False) + "\n" for n in notes), encoding="utf-8", newline="\n")
    lines = ["# Store-repair notes (generated from notes.jsonl by `store_repair note`; do not edit by hand)", "",
             "One entry per store defect: the question that exposed it, the part, the cause, the fix, the stores "
             "repaired. Stores are named by their build folder, never by company.", "",
             "| id | status | part | symptom | cause | fix | stores repaired |", "|---|---|---|---|---|---|---|"]
    for n in notes:
        cells = [n["id"], n["status"], n.get("part") or "", n.get("symptom") or "", n.get("cause") or "",
                 n.get("fix") or "", ", ".join(n.get("repaired") or [])]
        lines.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
    lines += ["", "## Questions that exposed them", ""]
    lines += [f"- {n['id']} ({n.get('store') or '-'}): {n.get('question') or '-'}" for n in notes]
    (notes_dir / "INDEX.md").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def note_add(fields: dict, notes_dir: Path = NOTES_DIR) -> dict:
    notes = read_notes(notes_dir)
    number = max((int(n["id"].split("-")[1]) for n in notes), default=0) + 1
    note = {"id": f"R-{number:03d}", "opened": time.strftime("%Y-%m-%d"), "status": "open", "repaired": [], "runs": [],
            **{k: v for k, v in fields.items() if v}}
    notes.append(note)
    write_notes(notes, notes_dir)
    return note


def note_set(note_id: str, fields: dict, repaired=(), run: str | None = None, notes_dir: Path = NOTES_DIR) -> dict:
    notes = read_notes(notes_dir)
    for note in notes:
        if note["id"] == note_id:
            note.update({k: v for k, v in fields.items() if v})
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
    change.add_argument("id")
    change.add_argument("--repaired", default="", help="comma list of stores repaired for this defect")
    for p in (add, change):
        for name in NOTE_FIELDS:
            p.add_argument(f"--{name}", default=None, choices=STATUSES if name == "status" else None)
    args = ap.parse_args(argv)
    fields = {name: getattr(args, name, None) for name in NOTE_FIELDS}
    if args.cmd == "add":
        if not (fields["part"] and fields["symptom"]):
            raise SystemExit("note add needs at least --part and --symptom")
        print(json.dumps(note_add(fields), indent=1, ensure_ascii=False))
    elif args.cmd == "set":
        print(json.dumps(note_set(args.id, fields, [s for s in args.repaired.split(",") if s]), indent=1,
                         ensure_ascii=False))
    else:
        for n in read_notes():
            print(f"{n['id']} {n['status']:<11} {n.get('part') or '-':<12} {n.get('symptom') or ''}"
                  f"  [repaired: {', '.join(n.get('repaired') or []) or '-'}]")
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
    if args.accept:
        if not args.stores:
            raise SystemExit("--accept needs --stores")
        records = [accept(store, args.accept) for store in pick(stores, args.stores)]
    elif args.part:
        if not args.stores:
            raise SystemExit("--part needs --stores: one company at a time (ruling 15 Nov), name the stores")
        run_id = time.strftime("%Y%m%dT%H%M%S")
        records = []
        for store in pick(stores, args.stores):
            if args.part == "stale":
                behind = stale_of(store["db"], hashes)
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
