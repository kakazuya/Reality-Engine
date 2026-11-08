"""T-121: document canary -- a fixed, stratified sample of documents from companies no pilot build holds.

    python -m reality_engine.pilot3.doc_canary --out .tmp/canary [--per-cell 3] [--seed 0]

A pilot build improves the extractors against the companies its profile names; when another company changes its
document format (a new results layout, a scanned deck) that then shows up as silently missing rows rather than as
a failure.  This canary picks documents from the ``pilot60_history`` manifest (through ``raw_store``, so a PDF the
D drive does not hold comes from the T-102 Drive manifest) for companies in NO pilot profile, one cell per
document type x filing year 2019-2026, ``--per-cell`` documents per cell.  Each cell is ordered by a hash of
``--seed`` and the document's own identity, so the same seed picks the same documents on every machine and in any
manifest order.

Each document is read exactly the way a build reads it: the same text read (``docs_collect._extract``), RapidOCR
for a page with no text layer (``ocr.ocr_page``, as ``--part ocr`` writes it), and the KPI extractor's own page
reader (``kpi.run`` over a ``pages.db`` of the sample, with the OCR pages attached).  It writes into ``--out``:

* ``canary.csv``: one row per document -- doc, type, year, pages, text_pages_pct (text pages %), ocr_pages,
  mean_ocr_conf, numbers_per_page (numbers read per page, ``kpi.VAL_RX``), kpi_rows (KPI rows per doc), error.
* ``summary.csv``: one row per type x year -- the same measures aggregated over the cell.
* ``work/``: the sample's ``pages.db``, ``ocr.db`` and ``kpi.db`` (kept for inspection; safe to delete).

A later run reads the previous ``summary.csv`` before overwriting it and prints every cell whose text coverage or
KPI rows per document fell by more than ``DROP`` (20%) against it: a format change is then a visible drop, not a
silent one.  No model call; OCR is CPU RapidOCR only.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
import sqlite3
import sys
from collections import defaultdict
from pathlib import Path

from reality_engine import raw_store
from reality_engine.db.readonly import connect_ro
from reality_engine.pilot3 import REAL_DB, docs_collect, kpi, ocr

RAW_MANIFEST = Path(r"D:\RealityEngine\raw\pilot60_history\manifest.csv")
PROFILE_DIR = Path(__file__).resolve().parents[2] / "tasks" / "night_loop"
YEARS = range(2019, 2027)                     # filing years the canary stratifies over
DROP = 0.20                                   # a cell fell when coverage or rows/doc is down 20%
CANARY_COLS = ("doc", "type", "year", "pages", "text_pages_pct", "ocr_pages", "mean_ocr_conf",
               "numbers_per_page", "kpi_rows", "error")
SUMMARY_COLS = ("type", "year", "docs", "pages", "text_pages_pct", "ocr_pages", "mean_ocr_conf",
                "numbers_per_page", "kpi_rows_per_doc")


def _year(value: str | None) -> int:
    try:
        return int(str(value or "")[:4])
    except ValueError:
        return 0


def pilot_symbols(profile_dir: Path | str = PROFILE_DIR, default_db: Path | str | None = None) -> set[str]:
    """Every company the extractors were built against: the companies of every pilot profile JSON of this checkout
    and of the default pilot3 database's ``company`` table.  The canary must not read one of them."""
    out: set[str] = set()
    for path in sorted(Path(profile_dir).glob("*profile*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        raw_companies = data.get("companies") if isinstance(data, dict) else None
        for company in raw_companies or ():
            symbol = str(company.get("symbol") or "").strip().upper()
            if symbol:
                out.add(symbol)
    try:
        con = connect_ro(str(default_db or REAL_DB), timeout_s=30)
        try:
            cur = con.execute("SELECT symbol FROM company")
            rows = (cur.fetchall() if cur is not None else None) or ()
            for row in rows:
                symbol = str(row[0]).strip().upper()
                if symbol:
                    out.add(symbol)
        finally:
            con.close()
    except Exception:          # no default database on this machine: the profiles alone decide
        pass
    return out


def candidates(store: raw_store.RawStore, pilot: set[str], manifest: Path | str = RAW_MANIFEST) -> list[dict]:
    """The manifest rows a canary may read: ``status='ok'``, a document bucket, a filing year 2019-2026, a company
    in no pilot profile, and a file ``raw_store`` can serve (local or from Drive).  One row per filing (newsid)."""
    found: dict[tuple[str, str], dict] = {}
    with Path(manifest).open(encoding="utf-8", errors="replace", newline="") as fh:
        for row in csv.DictReader(fh):
            if str(row.get("status") or "").strip().lower() != "ok":
                continue
            symbol = str(row.get("symbol_at_time") or "").strip().upper()
            doc_type = docs_collect.BUCKET_TYPES.get(str(row.get("bucket") or "").strip().lower())
            year = _year(row.get("dissem_ts"))
            local = str(row.get("local_path") or "").strip()
            if not symbol or symbol in pilot or doc_type is None or year not in YEARS or not local:
                continue
            path = Path(local)
            if not store.exists(path):
                continue
            newsid = str(row.get("newsid") or path.stem)
            found.setdefault((symbol, newsid), {
                "symbol": symbol, "doc_type": doc_type, "year": year, "path": path,
                "known_at": str(row.get("dissem_ts") or ""), "sha256": str(row.get("sha256") or ""),
                "newsid": newsid})
    return list(found.values())


def pick(rows: list[dict], per_cell: int, seed: int) -> dict[tuple[str, int], list[dict]]:
    """One cell per document type x filing year with ``per_cell`` documents: the same seed picks the same documents
    whatever order the manifest lists them in (each cell is ordered by a hash of the seed and document identity)."""
    cells: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        cells[(row["doc_type"], row["year"])].append(row)
    chosen = {}
    for cell in sorted(cells):
        members = sorted(cells[cell], key=lambda r: (r["symbol"], r["known_at"], r["newsid"]))
        if len(members) > per_cell:
            members = sorted(members, key=lambda r: hashlib.sha1(
                f"{seed}:{r['symbol']}:{r['newsid']}".encode("utf-8")).hexdigest())[:per_cell]
        chosen[cell] = sorted(members, key=lambda r: (r["known_at"], r["symbol"], r["newsid"]))
    return chosen


def _doc_key(row: dict) -> str:
    return f"{row['symbol']}/{row['doc_type']}/{row['newsid']}.pdf"


def _display(row: dict, store: raw_store.RawStore) -> str:
    """The document as the manifest names it: its path below the raw root, else symbol/newsid."""
    root = store.roots.get("raw")
    try:
        return row["path"].relative_to(root).as_posix() if root else row["path"].as_posix()
    except ValueError:
        return f"{row['symbol']}/{row['newsid']}"


def measure(chosen: dict, out: Path, store: raw_store.RawStore, dpi: int = 300,
            device: str = "cpu") -> dict[str, dict]:
    """Read every chosen document like a build does; returns ``{doc_key: row}`` with the canary measures filled in
    except ``kpi_rows`` (the KPI extractor reads the whole sample in one run afterwards)."""
    work = Path(out) / "work"
    pdfs = work / "pdfs"
    pdfs.mkdir(parents=True, exist_ok=True)
    for name in ("pages.db", "ocr.db", "kpi.db"):
        for suffix in ("", "-wal", "-shm"):
            Path(f"{work / name}{suffix}").unlink(missing_ok=True)
    pages_con = docs_collect.connect_out(work / "pages.db")      # the collector's own doc/doc_page schema + FTS
    ocr_con = sqlite3.connect(work / "ocr.db")
    ocr_con.executescript(ocr.SCHEMA)
    records: dict[str, dict] = {}
    for row in sorted((d for members in chosen.values() for d in members),
                      key=lambda d: (d["known_at"], d["symbol"], d["newsid"])):
        key = _doc_key(row)
        record = {"doc": _display(row, store), "type": row["doc_type"], "year": row["year"], "pages": 0,
                  "text_pages_pct": 0.0, "ocr_pages": 0, "mean_ocr_conf": None, "numbers_per_page": 0.0,
                  "kpi_rows": 0, "error": ""}
        records[key] = record
        local = pdfs / f"{row['symbol']}_{row['newsid']}.pdf"
        try:
            with store.local(row["path"]) as source:      # local file, or the Drive copy for this one document
                shutil.copyfile(source, local)
        except Exception as exc:                          # missing on Drive: a cell must not silently lose its file
            record["error"] = f"{type(exc).__name__}: {exc}"[:160]
            continue
        pages, stats = docs_collect._extract(pages_con, key, local, row["known_at"])
        pages_con.execute("INSERT OR REPLACE INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (key, row["symbol"], "", row["doc_type"], row["newsid"], (row["known_at"] or "")[:10],
                           row["known_at"], str(local), row["sha256"], pages, "{}", "canary"))
        record["error"] = stats["error"]
        conf: list[float] = []
        if stats["needs_ocr"]:
            try:
                fitz = ocr._fitz()
                pdf = fitz.open(str(local))
            except Exception as exc:      # the document cannot be rendered at all: not a format signal
                record["error"] = f"{type(exc).__name__}: {exc}"[:160]
                pdf = None
            if pdf is not None:
                try:
                    for number, text, method in pages_con.execute(
                            "SELECT page, text, method FROM doc_page WHERE doc_key=? AND method='needs_ocr' "
                            "ORDER BY page", (key,)).fetchall():
                        try:
                            got, words, page_conf, boxes = ocr.ocr_page(pdf[number - 1], dpi, device)
                        except Exception:     # one damaged page: it stays needs_ocr and counts as textless
                            continue
                        if not boxes:                     # nothing read: a build leaves the page needs_ocr too
                            continue
                        pages_con.execute("UPDATE doc_page SET text=?, method='ocr_rapid' WHERE doc_key=? AND page=?",
                                          (got, key, number))
                        ocr_con.execute("INSERT OR REPLACE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                                        (row["symbol"], key, number, row["doc_type"], row["known_at"], got,
                                         json.dumps(words, separators=(",", ":")), round(page_conf, 4), boxes,
                                         dpi, 0.0, "ocr_rapid"))
                        conf.append(page_conf)
                finally:
                    pdf.close()
        pages_con.commit()
        ocr_con.commit()
        measured = pages_con.execute("SELECT text FROM doc_page WHERE doc_key=? ORDER BY page", (key,)).fetchall()
        record["pages"] = len(measured) or pages
        text_pages = sum(1 for (text,) in measured if len((text or "").strip()) >= docs_collect.MIN_PAGE_CHARS)
        numbers = sum(1 for (text,) in measured if text for _ in kpi.VAL_RX.finditer(text))
        if record["pages"]:
            record["text_pages_pct"] = round(100.0 * text_pages / record["pages"], 1)
            record["numbers_per_page"] = round(numbers / record["pages"], 2)
        record["ocr_pages"] = len(conf)
        record["mean_ocr_conf"] = round(sum(conf) / len(conf), 3) if conf else None
    pages_con.close()          # the KPI extractor opens pages.db read-only
    ocr_con.close()
    kpi.run(str(work / "kpi.db"), sorted({d["symbol"] for members in chosen.values() for d in members}), None,
            raw_root=None, ocr_db=[str(work / "ocr.db")], pages_db=work / "pages.db")
    verdict = sqlite3.connect(work / "kpi.db")
    try:
        counts = dict(verdict.execute("SELECT doc_key, COUNT(*) FROM kpi_series GROUP BY doc_key"))
    finally:
        verdict.close()
    for key, record in records.items():
        record["kpi_rows"] = counts.get(key, 0)
    return records


def summarize(records: list[dict]) -> list[dict]:
    """One summary row per document type x filing year over the documents that were read (an errored document is
    not a format signal and is left out; its row in ``canary.csv`` carries the error)."""
    cells: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for record in records:
        if not record.get("error"):
            cells[(record["type"], record["year"])].append(record)
    out = []
    for doc_type, year in sorted(cells):
        members = cells[(doc_type, year)]
        pages = sum(m["pages"] for m in members)
        text = sum(m["text_pages_pct"] * m["pages"] / 100.0 for m in members)
        conf = [m["mean_ocr_conf"] for m in members if m["mean_ocr_conf"] is not None]
        rows = sum(m["kpi_rows"] for m in members)
        out.append({"type": doc_type, "year": year, "docs": len(members), "pages": pages,
                    "text_pages_pct": round(100.0 * text / pages, 1) if pages else 0.0,
                    "ocr_pages": sum(m["ocr_pages"] for m in members),
                    "mean_ocr_conf": round(sum(conf) / len(conf), 3) if conf else "",
                    "numbers_per_page": round(sum(m["numbers_per_page"] * m["pages"] for m in members) / pages, 2)
                    if pages else 0.0,
                    "kpi_rows_per_doc": round(rows / len(members), 1) if members else 0.0})
    return out


def _read_summary(path: Path) -> dict[tuple[str, int], dict]:
    if not path.is_file():
        return {}
    with path.open(encoding="utf-8", newline="") as fh:
        return {(row["type"], _year(row["year"])): row for row in csv.DictReader(fh)}


def compare(previous: dict[tuple[str, int], dict], summary: list[dict], floor: float = DROP) -> list[str]:
    """Cells whose text coverage or KPI rows per document fell by more than ``floor`` against the previous run."""
    drops = []
    for row in summary:
        old = previous.get((row["type"], row["year"]))
        if not old:
            continue
        for field, label in (("text_pages_pct", "text coverage"), ("kpi_rows_per_doc", "KPI rows/doc")):
            try:
                was, now = float(old[field]), float(row[field])
            except (KeyError, TypeError, ValueError):
                continue
            if was > 0 and now < was * (1.0 - floor):
                drops.append(f"{row['type']} {row['year']}: {label} {was:g} -> {now:g} (>= {int(floor * 100)}% drop)")
    return drops


def _write_csv(path: Path, columns: tuple, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def run(out: Path, per_cell: int = 3, seed: int = 0, manifest: Path | str = RAW_MANIFEST,
        profile_dir: Path | str = PROFILE_DIR, dpi: int = 300, device: str = "cpu") -> dict:
    """Write ``canary.csv`` and ``summary.csv`` under ``out`` and return the counts and the drops against the
    previous summary (nothing is written outside ``out``; the stores and the raw files are only read)."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    store = raw_store.default_store()
    pilot = pilot_symbols(profile_dir, REAL_DB)
    rows = candidates(store, pilot, manifest)
    chosen = pick(rows, per_cell, seed)
    previous = _read_summary(out / "summary.csv")
    records = list(measure(chosen, out, store, dpi, device).values())
    summary = summarize(records)
    _write_csv(out / "canary.csv", CANARY_COLS, records)
    _write_csv(out / "summary.csv", SUMMARY_COLS, summary)
    drops = compare(previous, summary)
    return {"documents": len(records), "cells": len(summary), "candidates": len(rows),
            "pilot_companies": len(pilot), "errors": sum(1 for r in records if r.get("error")),
            "drops": drops, "summary": summary}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n")[0])
    ap.add_argument("--out", required=True, help="output folder: canary.csv, summary.csv and work/")
    ap.add_argument("--per-cell", type=int, default=3, help="documents per document-type x filing-year cell")
    ap.add_argument("--seed", type=int, default=0, help="fixed seed: the same seed picks the same documents")
    ap.add_argument("--manifest", default=str(RAW_MANIFEST), help="pilot60_history manifest.csv")
    ap.add_argument("--profiles", default=str(PROFILE_DIR), help="folder of the pilot profile JSONs to exclude")
    ap.add_argument("--dpi", type=int, default=300)
    ap.add_argument("--device", choices=["cpu", "dml"], default="cpu")
    args = ap.parse_args(argv)
    result = run(Path(args.out), args.per_cell, args.seed, args.manifest, args.profiles, args.dpi, args.device)
    for row in result["summary"]:
        print(f"{row['type']:<16} {row['year']}  docs={row['docs']:<2} pages={row['pages']:<5} "
              f"text={row['text_pages_pct']:<5}% ocr={row['ocr_pages']:<4} conf={row['mean_ocr_conf']} "
              f"nums/page={row['numbers_per_page']:<5} kpi/doc={row['kpi_rows_per_doc']}")
    print(f"documents={result['documents']} cells={result['cells']} candidates={result['candidates']} "
          f"excluded_companies={result['pilot_companies']} errors={result['errors']}")
    for line in result["drops"]:
        print(f"DROP {line}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
