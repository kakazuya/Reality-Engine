"""T-214: build one pilot3 store per Telegram-queue company with the script layers only, and measure it.

One company at a time, through the recipe the T-208 bullet of ``docs/DEVELOPER_GUIDE.md`` names, with no code
change under ``reality_engine/pilot3`` or ``reality_engine/v2``:

    make_profile <SYM> --name cNN --root <root>/cNN --window-start 2024-04-01 --compute-start 2019-01-01
    docs_collect --profile <root>/cNN/cNN_profile.json
    build --profile <json> --out <root>/cNN/cNN.db --part <part>   (13 parts, one log b_<part>.log each)

Each step runs as a subprocess with no console window and no shell.  Every step records its wall seconds, return
code and the peak RSS of the child tree, sampled once a second with psutil; a step whose child tree passes
``--ram-gb`` (default 4 GB) is killed and recorded as ``ram_stop``, and one that runs past ``--max-part-minutes``
(default 40) is killed and recorded as a timeout (the run then stops, per the ticket).

Per company the build also writes ``<root>/cNN/routes.csv`` with ``v2.page_route`` and records: the manifest's
``status='ok'`` files and bytes, docs, pages, pages by route, the table/chart pages that belong to a results
document whose quarter has ``fin_quarter_xbrl`` rows ("already covered by XBRL": the document's filing date falls
15-100 days after a period end the table holds), the store size on disk (db + WAL) and the row counts of the
answer tables.  Outputs: ``<root>/pilot10_measure.csv`` (one row per company), ``<root>/parts.csv``
(company x step) and ``<root>/cNN/parts.csv`` (one company's steps).  No company is named in the repo: the CSVs
stay under ``D:/RealityEngine/tg_build``.

    python -m reality_engine.scripts.tg_measure_build --root D:/RealityEngine/tg_build/measure10
    python -m reality_engine.scripts.tg_measure_build --root <root> --only 1 --force   # one company again

A company whose ``cNN_measure.json`` exists is read back, not rebuilt, unless ``--force`` is given, so a stopped
run resumes where it stopped and the aggregate still holds every earlier row.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
import time
from pathlib import Path

import psutil

REPO = Path(__file__).resolve().parents[2]
ROOT_DEFAULT = Path("D:/RealityEngine/tg_build/measure10")
DATE = "2024-04-01"
COMPUTE_START = "2019-01-01"

# The 13 script parts of the recipe, in the order T-208 ran them.  ``make_profile`` and ``docs_collect`` run
# before the first one and are measured the same way (they are most of a small build's wall time).
PARTS = ("registry", "pages", "transcripts", "kpi", "guidance", "stores", "comparatives", "preferred",
         "ratios", "segments", "notes", "checks", "events")
COUNT_TABLES = ("fin_quarter_xbrl", "fin_quarter_printed", "kpi_series", "guidance", "transcript_statement",
                "shp_category", "price_delivery")

PART_FIELDS = ("company", "symbol", "part", "seconds", "rc", "peak_rss_mb", "ram_stop", "timed_out", "log", "tail5")
MEASURE_FIELDS = (
    "company", "symbol", "sector", "raw_ok_files", "raw_ok_mb", "docs", "pages",
    "route_no_figures", "route_needs_ocr", "route_table_or_chart", "route_text_ok",
    "table_or_chart_share", "tc_pages_xbrl_covered", "tc_xbrl_share",
    "store_mb", "db_bytes", "fin_quarter_xbrl", "fin_quarter_printed", "kpi_series", "guidance",
    "transcript_statement", "shp_category", "price_delivery",
    "wall_s", "build_s", "route_s", "peak_rss_mb", "failed", "failed_tail5", "log_dir")


# ---------------------------------------------------------------------------- running one step
def _tree_rss_mb(proc: psutil.Process) -> float:
    """RSS of ``proc`` and every descendant, in MiB; 0 when the tree is already gone."""
    try:
        total = proc.memory_info().rss
    except psutil.Error:
        return 0.0
    for child in proc.children(recursive=True):
        try:
            total += child.memory_info().rss
        except psutil.Error:
            continue
    return total / 1024 / 1024


def _kill_tree(pid: int) -> None:
    try:
        p = psutil.Process(pid)
        for child in p.children(recursive=True):
            try:
                child.kill()
            except psutil.Error:
                pass
        p.kill()
    except psutil.Error:
        pass


def _tail(log_path: Path, lines: int = 5) -> str:
    try:
        text = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    return " | ".join(line.strip() for line in text[-lines:] if line.strip())


def run_step(part: str, cmd: list[str], log_path: Path, interval_s: float = 1.0, ram_gb: float = 4.0,
             timeout_s: float = 2400.0) -> dict:
    """Run one step as a child process; return its row (seconds, rc, peak RSS, ram_stop, timeout, log, tail5).

    The child tree's RSS is sampled every ``interval_s`` seconds; a sample above ``ram_gb`` GiB kills the tree and
    sets ``ram_stop``, and one past ``timeout_s`` kills it and sets ``timed_out``.  One sample a second is a floor:
    a shorter spike is not seen.  stdout+stderr go to ``log_path``; on failure ``tail5`` carries the last 5 lines.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.perf_counter()
    peak = 0.0
    ram_stop = False
    timed_out = False
    with log_path.open("wb") as fh:
        proc = subprocess.Popen(cmd, stdout=fh, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                cwd=str(REPO), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            handle = psutil.Process(proc.pid)
            while proc.poll() is None:
                peak = max(peak, _tree_rss_mb(handle))
                if ram_gb and peak > ram_gb * 1024:
                    ram_stop = True
                    _kill_tree(proc.pid)
                    break
                if timeout_s and time.perf_counter() - t0 > timeout_s:
                    timed_out = True
                    _kill_tree(proc.pid)
                    break
                time.sleep(interval_s)
        except psutil.Error:
            pass
        try:
            rc = proc.wait(timeout=120)
        except subprocess.TimeoutExpired:
            proc.kill()
            rc = proc.wait()
    return {"part": part, "seconds": round(time.perf_counter() - t0, 2), "rc": rc,
            "peak_rss_mb": round(peak, 1), "ram_stop": ram_stop, "timed_out": timed_out,
            "log": str(log_path), "tail5": _tail(log_path) if rc != 0 else ""}


# ---------------------------------------------------------------------------- writing the CSVs
def write_parts_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=PART_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_measure_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=MEASURE_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# ---------------------------------------------------------------------------- per-company measurement
def _store_mb(db: Path) -> tuple[float, int]:
    """The store's files on disk (the db plus its WAL; the shm is a 32 KB scratch map)."""
    total = 0
    for path in db.parent.glob(db.name + "*"):
        if path.name.endswith("-shm"):
            continue
        try:
            total += path.stat().st_size
        except OSError:
            pass
    return round(total / 1024 / 1024, 2), total


def _count(con, table: str) -> int:
    try:
        row = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    except Exception:
        return 0
    return int(row[0]) if row else 0


def measure_store(db: Path, routes: Path, profile_json: Path, raw_ok_files: int, raw_ok_bytes: int) -> dict:
    """The per-company numbers from the built store, its route CSV, its profile and its manifest rows."""
    from collections import Counter

    from reality_engine.db.readonly import connect_ro

    routes_rows = list(csv.DictReader(routes.open(encoding="utf-8"))) if routes.is_file() else []
    by_route = Counter(row["route"] for row in routes_rows)
    con = connect_ro(str(db))
    try:
        docs = _count(con, "doc")
        pages = _count(con, "doc_page")
        counts = {table: _count(con, table) for table in COUNT_TABLES}
        covered_cur = con.execute(
            "SELECT d.doc_key FROM doc d WHERE d.doc_type='results' AND EXISTS ("
            " SELECT 1 FROM fin_quarter_xbrl f WHERE f.symbol=d.symbol AND"
            " CAST(julianday(substr(d.known_at,1,10)) - julianday(f.period_end) AS INT) BETWEEN 15 AND 100)")
        covered_docs = {row[0] for row in ((covered_cur.fetchall() or []) if covered_cur is not None else [])}
    finally:
        con.close()
    table_chart = by_route.get("table_or_chart", 0)
    covered = sum(1 for row in routes_rows
                  if row["route"] == "table_or_chart" and row["doc_key"] in covered_docs)
    sector = ""
    try:
        data = json.loads(profile_json.read_text(encoding="utf-8"))
        sector = str(((data.get("companies") or [{}])[0]).get("sector") or "")
    except Exception:
        pass
    store_mb, db_bytes = _store_mb(db)
    return {
        "sector": sector,
        "raw_ok_files": raw_ok_files,
        "raw_ok_mb": round(raw_ok_bytes / 1024 / 1024, 1),
        "docs": docs,
        "pages": pages,
        "route_no_figures": by_route.get("no_figures", 0),
        "route_needs_ocr": by_route.get("needs_ocr", 0),
        "route_table_or_chart": table_chart,
        "route_text_ok": by_route.get("text_ok", 0),
        "table_or_chart_share": round(table_chart / pages, 3) if pages else 0,
        "tc_pages_xbrl_covered": covered,
        "tc_xbrl_share": round(covered / table_chart, 3) if table_chart else 0,
        "store_mb": store_mb,
        "db_bytes": db_bytes,
        **counts,
    }


# ---------------------------------------------------------------------------- the run
def _read_manifest(path: Path) -> tuple[list[dict], list[str]]:
    with path.open(encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.DictReader(fh)
        return list(reader), list(reader.fieldnames or ())


def _write_company_manifest(path: Path, rows: list[dict], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _ok_counts(rows: list[dict]) -> tuple[int, int]:
    ok = [r for r in rows if str(r.get("status") or "").strip().lower() == "ok"]
    return len(ok), sum(int(r["bytes"]) for r in ok if str(r.get("bytes") or "").isdigit())


def _blank_row(name: str, symbol: str, ok_files: int, ok_bytes: int, parts: list[dict],
               failed: list[str], tails: list[str], wall0: float) -> dict:
    """A measure row for a company that stopped before the store could be measured."""
    return {"company": name, "symbol": symbol, "raw_ok_files": ok_files,
            "raw_ok_mb": round(ok_bytes / 1024 / 1024, 1),
            "wall_s": round(time.perf_counter() - wall0, 1),
            "build_s": round(sum(row["seconds"] for row in parts), 1),
            "peak_rss_mb": max([row["peak_rss_mb"] for row in parts] + [0]),
            "failed": ";".join(failed), "failed_tail5": " || ".join(tails)}


def build_company(index: int, symbol: str, root: Path, manifest_rows: list[dict], fields: list[str],
                  args: argparse.Namespace) -> tuple[dict, list[dict], str]:
    """Run the recipe for one company; return (measure row, step rows, "" or the reason the run must stop)."""
    name = f"c{index:02d}"
    base = root / name
    base.mkdir(parents=True, exist_ok=True)
    mine = [row for row in manifest_rows if str(row.get("symbol_at_time") or "").strip().upper() == symbol]
    _write_company_manifest(base / "raw" / "manifest.csv", mine, fields)
    profile_json = base / f"{name}_profile.json"
    db = base / f"{name}.db"
    ok_files, ok_bytes = _ok_counts(mine)
    parts: list[dict] = []
    failed: list[str] = []
    tails: list[str] = []
    wall0 = time.perf_counter()

    def step(label: str, cmd: list[str]) -> dict:
        row = run_step(label, cmd, base / f"b_{label}.log", interval_s=1.0, ram_gb=args.ram_gb,
                       timeout_s=args.max_part_minutes * 60)
        row.update({"company": name, "symbol": symbol})
        parts.append(row)
        print(f"  {label:<14} {row['seconds']:>8.1f}s rc={row['rc']:<4} peak={row['peak_rss_mb']:>7.1f} MB"
              + (" RAM_STOP" if row["ram_stop"] else "") + (" TIMEOUT" if row["timed_out"] else ""), flush=True)
        if row["rc"] != 0 or row["ram_stop"] or row["timed_out"]:
            failed.append(f"{label}(rc={row['rc']}"
                          + (",ram_stop" if row["ram_stop"] else "")
                          + (",timeout" if row["timed_out"] else "") + ")")
            if row["tail5"]:
                tails.append(f"{label}: {row['tail5']}")
        return row

    py = sys.executable
    made = step("make_profile", [py, "-m", "reality_engine.pilot3.make_profile", symbol, "--name", name,
                                 "--root", str(base), "--window-start", DATE, "--compute-start", COMPUTE_START,
                                 "--out", str(profile_json)])
    if made["rc"] != 0 or not profile_json.is_file():
        return _blank_row(name, symbol, ok_files, ok_bytes, parts, failed, tails, wall0), parts, ""
    collected = step("docs_collect", [py, "-m", "reality_engine.pilot3.docs_collect", "--profile",
                                      str(profile_json)])
    if collected["rc"] != 0:
        return (_blank_row(name, symbol, ok_files, ok_bytes, parts, failed, tails, wall0), parts,
                "company 1 failed in docs_collect" if index == 1 else "")

    stop = ""
    for part in PARTS:
        done = step(part, [py, "-m", "reality_engine.pilot3.build", "--profile", str(profile_json),
                           "--out", str(db), "--part", part])
        if done["timed_out"]:
            stop = f"{name} {part} ran past {args.max_part_minutes:g} minutes"
            break
        if part == "registry" and done["rc"] != 0 and index == 1:
            stop = "company 1 failed in registry"
            break

    route = run_step("route", [py, "-m", "reality_engine.v2.page_route", "--store", str(db),
                               "--out", str(base / "routes.csv")], base / "b_route.log",
                     interval_s=1.0, ram_gb=args.ram_gb, timeout_s=args.max_part_minutes * 60)
    print(f"  {'route':<14} {route['seconds']:>8.1f}s rc={route['rc']:<4}", flush=True)
    if route["rc"] != 0:
        failed.append(f"route(rc={route['rc']})")
        if route["tail5"]:
            tails.append(f"route: {route['tail5']}")

    row = _blank_row(name, symbol, ok_files, ok_bytes, parts, failed, tails, wall0)
    if db.is_file():
        row.update(measure_store(db, base / "routes.csv", profile_json, ok_files, ok_bytes))
    row.update({"route_s": route["seconds"], "log_dir": str(base),
                "failed": ";".join(failed), "failed_tail5": " || ".join(tails)})
    return row, parts, stop


def run(args: argparse.Namespace) -> int:
    root = Path(args.root)
    universe = Path(args.universe) if args.universe else root / "universe10.csv"
    manifest = Path(args.manifest) if args.manifest else root / "manifest.csv"
    with universe.open(encoding="utf-8", newline="") as fh:
        queue = [row for row in csv.DictReader(fh) if str(row.get("symbol") or "").strip()]
    manifest_rows, fields = _read_manifest(manifest)
    wanted = {int(x) for x in args.only.split(",")} if args.only else set(range(1, len(queue) + 1))

    stop_reason = ""
    for index, entry in enumerate(queue, start=1):
        if index not in wanted:
            continue
        symbol = str(entry["symbol"]).strip().upper()
        name = f"c{index:02d}"
        cached = root / name / f"{name}_measure.json"
        print(f"[{name}] {symbol}", flush=True)
        if cached.is_file() and not args.force:
            row = json.loads(cached.read_text(encoding="utf-8"))
            print(f"  cached: wall {row.get('wall_s')}s, store {row.get('store_mb')} MB", flush=True)
            continue
        row, parts, stop = build_company(index, symbol, root, manifest_rows, fields, args)
        cached.write_text(json.dumps(row, indent=1), encoding="utf-8")
        write_parts_csv(parts, root / name / "parts.csv")
        print(f"  done: wall {row['wall_s']}s, store {row.get('store_mb') or 0} MB, "
              f"{row.get('pages') or 0} pages, failed={row.get('failed') or 'none'}", flush=True)
        if stop:
            stop_reason = stop
            print(f"STOP: {stop}", flush=True)
            break

    # The aggregate always holds every company already measured (a --only run refreshes its rows only).
    rows: list[dict] = []
    all_parts: list[dict] = []
    for index in range(1, len(queue) + 1):
        name = f"c{index:02d}"
        cached = root / name / f"{name}_measure.json"
        if cached.is_file():
            rows.append(json.loads(cached.read_text(encoding="utf-8")))
            company_parts = root / name / "parts.csv"
            if company_parts.is_file():
                all_parts.extend(csv.DictReader(company_parts.open(encoding="utf-8")))
    out_csv = Path(args.out_csv) if args.out_csv else root / "pilot10_measure.csv"
    write_measure_csv(rows, out_csv)
    parts_csv = out_csv.with_name("parts.csv")
    write_parts_csv(all_parts, parts_csv)
    print(f"{len(rows)} company rows -> {out_csv}\n{len(all_parts)} step rows -> {parts_csv}", flush=True)
    if args.accept_copy and out_csv.resolve() != Path(args.accept_copy).resolve():
        write_measure_csv(rows, Path(args.accept_copy))
        print(f"copy -> {args.accept_copy}", flush=True)
    if stop_reason:
        print(f"run stopped: {stop_reason}", file=sys.stderr, flush=True)
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-214: build and measure one pilot3 store per queue company")
    ap.add_argument("--root", default=str(ROOT_DEFAULT), help="folder of cNN subfolders (default %(default)s)")
    ap.add_argument("--universe", default=None, help="default <root>/universe10.csv")
    ap.add_argument("--manifest", default=None, help="default <root>/manifest.csv (status='ok' rows are read)")
    ap.add_argument("--only", default=None, help="comma list of queue positions (1-based), e.g. 1,3")
    ap.add_argument("--force", action="store_true", help="rebuild a company whose measurement JSON exists")
    ap.add_argument("--out-csv", default=None, help="default <root>/pilot10_measure.csv")
    ap.add_argument("--accept-copy", default="D:/RealityEngine/tg_build/pilot10_measure.csv",
                    help="also write the measure CSV here for the ticket's accept command ('' to skip)")
    ap.add_argument("--ram-gb", type=float, default=4.0, help="kill a step whose child tree passes this (GiB)")
    ap.add_argument("--max-part-minutes", type=float, default=40.0,
                    help="kill a step past this and stop the run (default 40)")
    args = ap.parse_args(argv)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
