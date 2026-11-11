"""T-180: score free-model table transcription runs against the position-settled reference cells.

Script only: never calls a model.  Reads saved run dirs (``<page_id>.rows.json`` +
``transcribe_log.csv``) and one-page PDFs, and writes one row per reader+input, split
(dev/frozen/all) and per doc type.

    python -m reality_engine.v2.reader_score --pages <pages.csv> --pdf-pages <dir> \
        --runs <dir>... [--pair a b]... --out <xlsx>
"""
from __future__ import annotations

import argparse
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from reality_engine.v2 import reference_geom as rg
from reality_engine.v2 import reference_pages as rp
from reality_engine.v2 import reference_vote as rv

_load_pages_csv = rp._load_pages_csv
_load_run_rows = rp._load_run_rows
_norm_value = rp._norm_value
label_key = rv.label_key
col_key = rv.col_key
same_label = rv.same_label
_doc_type_norm = rp._doc_type_norm


def _read_log(run_dir: Path) -> dict[str, dict[str, str]]:
    log_path = run_dir / "transcribe_log.csv"
    out: dict[str, dict[str, str]] = {}
    if not log_path.exists():
        return out
    with log_path.open(newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            out[row["page_id"]] = row
    return out


def build_reference(pages_csv: Any, pdf_pages: Any, runs: list[Any]) -> list[dict[str, Any]]:
    """Reference cells = position-settled cells (settled_by in script+position/position) over ALL runs."""
    meta_rows = _load_pages_csv(Path(pages_csv))
    pdf_dir = Path(pdf_pages)
    run_dirs = [Path(r) for r in runs]
    out: list[dict[str, Any]] = []
    for meta in meta_rows:
        pid = meta["page_id"]
        pdf = pdf_dir / f"{pid}.pdf"
        words = rg.page_words(pdf) if pdf.exists() else None
        run_rows = [_load_run_rows(rd, pid) for rd in run_dirs]
        cells, _unread = rg.settle_page(run_rows, words)
        for c in cells:
            if c.get("settled_by") in ("script+position", "position"):
                out.append({
                    "page_id": pid,
                    "split": (meta.get("split") or "").strip(),
                    "doc_type": _doc_type_norm(meta.get("doc type", "")),
                    "lk": label_key(c["row_label"]),
                    "norm": _norm_value(c["value_text"]),
                    "ck": col_key(c["col_header"]),
                })
    return out


def _score_one(run_dir: Path, pages_csv: Path, pdf_pages: Path,
               ref_cells: list[dict[str, Any]]) -> dict[str, Any]:
    meta_rows = _load_pages_csv(pages_csv)
    meta_by_pid = {m["page_id"]: m for m in meta_rows}
    ref_by_page: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for rc in ref_cells:
        ref_by_page[rc["page_id"]].append(rc)

    log_info = _read_log(run_dir)
    present = {p.name.replace(".rows.json", "") for p in run_dir.glob("*.rows.json")}

    page_metrics: list[dict[str, Any]] = []
    cells_all: list[dict[str, Any]] = []
    conflicts: Counter[str] = Counter()

    for meta in meta_rows:
        pid = meta["page_id"]
        if pid not in present:
            continue
        pdf = pdf_pages / f"{pid}.pdf"
        words = rg.page_words(pdf) if pdf.exists() else None
        run_rows = _load_run_rows(run_dir, pid)
        cells, unread = rg.settle_page([run_rows], words)

        located = sum(1 for c in cells if c.get("row_ok") is True)
        verified = sum(1 for c in cells if c.get("settled_by") in ("script+position", "position"))
        for c in cells:
            if c.get("conflict"):
                conflicts[str(c["conflict"])] += 1

        ref_on_page = ref_by_page.get(pid, [])
        run_norm = [{"lk": label_key(c["row_label"]), "norm": _norm_value(c["value_text"]),
                     "ck": col_key(c["col_header"])} for c in cells]
        matched = 0
        for rc in ref_on_page:
            for rn in run_norm:
                if rn["norm"] != rc["norm"]:
                    continue
                if not (rn["lk"] == rc["lk"] or same_label(rn["lk"], rc["lk"])):
                    continue
                if rc["ck"] and rn["ck"] and rc["ck"] != rn["ck"]:
                    continue
                matched += 1
                break

        for c in cells:
            cells_all.append({
                "page_id": pid,
                "lk": label_key(c["row_label"]),
                "norm": _norm_value(c["value_text"]),
                "ck": col_key(c["col_header"]),
                "verified": c.get("settled_by") in ("script+position", "position"),
            })

        recall_page = (matched / len(ref_on_page)) if ref_on_page else 0.0
        page_metrics.append({
            "page_id": pid,
            "split": (meta.get("split") or "").strip(),
            "doc_type": _doc_type_norm(meta.get("doc type", "")),
            "rows": len(run_rows),
            "located": located,
            "verified": verified,
            "unread": len(unread),
            "ref": len(ref_on_page),
            "matched": matched,
            "recall": recall_page,
        })

    total_ref = sum(pm["ref"] for pm in page_metrics)
    total_matched = sum(pm["matched"] for pm in page_metrics)
    located_total = sum(pm["located"] for pm in page_metrics)
    verified_total = sum(pm["verified"] for pm in page_metrics)

    readers = {li.get("reader") for li in log_info.values() if li.get("reader")}
    inputs = {li.get("input") for li in log_info.values() if li.get("input")}
    reader = (next(iter(readers)) if len(readers) == 1 else (",".join(sorted(x for x in readers if x)) if readers else run_dir.name))
    input_mode = (next(iter(inputs)) if len(inputs) == 1 else (",".join(sorted(x for x in inputs if x)) if inputs else ""))
    if not reader:
        reader = run_dir.name
    if not input_mode:
        low = run_dir.name.lower()
        if "layimg" in low or "lay_img" in low or "layoutimage" in low or "layout_image" in low:
            input_mode = "layout_image"
        else:
            for cand in ("layout", "image", "text"):
                if cand in low:
                    input_mode = cand
                    break
        if not input_mode:
            input_mode = ""

    secs_all = [float(li.get("seconds", 0) or 0) for li in log_info.values()
                if li.get("seconds") not in (None, "")]
    pages_with_error_all = sum(1 for li in log_info.values() if (li.get("error") or "").strip())

    return {
        "run": run_dir.name,
        "run_dir": str(run_dir),
        "reader": reader,
        "input": input_mode,
        "pages_done": len(page_metrics),
        "pages_with_error": pages_with_error_all,
        "rows_given": sum(pm["rows"] for pm in page_metrics),
        "located": located_total,
        "verified": verified_total,
        "precision_verified": (verified_total / located_total if located_total else 0.0),
        "recall": (total_matched / total_ref if total_ref else 0.0),
        "unread": sum(pm["unread"] for pm in page_metrics),
        "ref_cells": total_ref,
        "matched": total_matched,
        "mean_seconds": (sum(secs_all) / len(secs_all) if secs_all else 0.0),
        "in_tok": sum(int(li.get("in_tok", 0) or 0) for li in log_info.values()),
        "out_tok": sum(int(li.get("out_tok", 0) or 0) for li in log_info.values()),
        "conflicts": dict(conflicts),
        "page_metrics": page_metrics,
        "cells": cells_all,
        "log_info": log_info,
    }


def score_run(run_dir: Any, pages_csv: Any, pdf_pages: Any,
              ref_cells: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Score one run dir. ref_cells optional; builds reference if None (using [run_dir])."""
    rd = Path(run_dir)
    pc = Path(pages_csv)
    pp = Path(pdf_pages)
    if ref_cells is None:
        ref_cells = build_reference(pc, pp, [rd])
    return _score_one(rd, pc, pp, ref_cells)


# aliases
score = score_run
score_one = score_run


def _make_row(run_result: dict[str, Any], pms: list[dict[str, Any]], split_label: str,
              doc_type_label: str | None = None) -> dict[str, Any]:
    log_info = run_result.get("log_info") or _read_log(Path(run_result["run_dir"]))
    subset_pages = {pm["page_id"] for pm in pms}
    subset_log = {pid: info for pid, info in log_info.items() if pid in subset_pages}
    located_total = sum(pm["located"] for pm in pms)
    verified_total = sum(pm["verified"] for pm in pms)
    total_ref = sum(pm["ref"] for pm in pms)
    total_matched = sum(pm["matched"] for pm in pms)
    secs = [float(i.get("seconds", 0) or 0) for i in subset_log.values()
            if i.get("seconds") not in (None, "")]
    pages_with_error = sum(1 for i in subset_log.values() if (i.get("error") or "").strip())
    return {
        "run": run_result["run"],
        "reader": run_result["reader"],
        "input": run_result["input"],
        "split": split_label,
        "doc_type": (doc_type_label if doc_type_label is not None else "all"),
        "pages_done": len(pms),
        "pages_with_error": pages_with_error,
        "rows_given": sum(pm["rows"] for pm in pms),
        "located": located_total,
        "verified": verified_total,
        "precision_verified": (verified_total / located_total if located_total else 0.0),
        "recall": (total_matched / total_ref if total_ref else 0.0),
        "unread": sum(pm["unread"] for pm in pms),
        "ref_cells": total_ref,
        "matched": total_matched,
        "mean_seconds": (sum(secs) / len(secs) if secs else 0.0),
        "in_tok": sum(int(i.get("in_tok", 0) or 0) for i in subset_log.values()),
        "out_tok": sum(int(i.get("out_tok", 0) or 0) for i in subset_log.values()),
    }


def _match_cell(a: dict[str, Any], bcell: dict[str, Any]) -> bool:
    if a["page_id"] != bcell["page_id"]:
        return False
    if a["norm"] != bcell["norm"]:
        return False
    if not (a["lk"] == bcell["lk"] or same_label(a["lk"], bcell["lk"])):
        return False
    if a["ck"] and bcell["ck"] and a["ck"] != bcell["ck"]:
        return False
    return True


def consistency(a: Any, b: Any) -> tuple[float, float]:
    """Share of A's verified cells that B also gives, and reverse."""
    ra = a if isinstance(a, dict) and "cells" in a else None
    rb = b if isinstance(b, dict) and "cells" in b else None
    # allow paths
    if ra is None:
        raise ValueError("consistency expects scored run results")
    if rb is None:
        raise ValueError("consistency expects scored run results")
    a_verified = [c for c in ra["cells"] if c.get("verified")]
    b_cells = rb["cells"]
    b_verified = [c for c in rb["cells"] if c.get("verified")]
    a_cells = ra["cells"]

    def share(src_verified, other_cells):
        if not src_verified:
            return 0.0
        n = 0
        for c in src_verified:
            if any(_match_cell(c, oc) for oc in other_cells):
                n += 1
        return n / len(src_verified)

    return (share(a_verified, b_cells), share(b_verified, a_cells))


pair_consistency = consistency


def run(pages_csv: Any, pdf_pages: Any, runs: list[Any], out: Any,
        pairs: list[tuple[Any, Any]] | None = None) -> dict[str, Any]:
    pc = Path(pages_csv)
    pp = Path(pdf_pages)
    run_dirs = [Path(r) for r in runs]
    ref_cells = build_reference(pc, pp, run_dirs)
    # score all runs (and pair dirs)
    results_by_path: dict[str, dict[str, Any]] = {}
    for rd in run_dirs:
        results_by_path[str(rd)] = _score_one(rd, pc, pp, ref_cells)
    all_run_results = [results_by_path[str(rd)] for rd in run_dirs]

    if pairs:
        for a, b in pairs:
            for p in (a, b):
                sp = str(Path(p))
                if sp not in results_by_path:
                    results_by_path[sp] = _score_one(Path(p), pc, pp, ref_cells)

    # build rows
    readers_rows: list[dict[str, Any]] = []
    by_type_rows: list[dict[str, Any]] = []
    pages_rows: list[dict[str, Any]] = []

    for rr in all_run_results:
        pms = rr["page_metrics"]
        # readers: by split (dev, frozen, all)
        for split in ("dev", "frozen", "all"):
            if split == "all":
                sub = pms
            else:
                sub = [pm for pm in pms if pm["split"] == split]
            if not sub and split != "all":
                continue
            readers_rows.append(_make_row(rr, sub, split, None))
        # by_type: by doc_type (all splits)
        for dt in ("deck", "results", "annual_report", "all"):
            if dt == "all":
                sub = pms
            else:
                sub = [pm for pm in pms if pm["doc_type"] == dt]
            if not sub and dt != "all":
                continue
            by_type_rows.append(_make_row(rr, sub, "all", dt))
        # pages
        for pm in pms:
            pages_rows.append({
                "run": rr["run"],
                "page": pm["page_id"],
                "doc_type": pm["doc_type"],
                "split": pm["split"],
                "rows": pm["rows"],
                "located": pm["located"],
                "verified": pm["verified"],
                "recall": pm["recall"],
                "unread": pm["unread"],
            })

    # write xlsx
    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    from openpyxl import Workbook
    wb = Workbook()
    # readers
    ws = wb.active
    assert ws is not None
    ws.title = "readers"
    rcols = ["run", "reader", "input", "split", "pages_done", "pages_with_error", "rows_given",
             "located", "verified", "precision_verified", "recall", "unread", "ref_cells", "matched",
             "mean_seconds", "in_tok", "out_tok"]
    ws.append(rcols)
    for row in readers_rows:
        ws.append([row[c] for c in rcols])
    # by_type
    bt = wb.create_sheet("by_type")
    bcols = ["run", "reader", "input", "doc_type", "pages_done", "pages_with_error", "rows_given",
             "located", "verified", "precision_verified", "recall", "unread", "ref_cells", "matched",
             "mean_seconds", "in_tok", "out_tok"]
    bt.append(bcols)
    for row in by_type_rows:
        bt.append([row[c] for c in bcols])
    # pages
    pg = wb.create_sheet("pages")
    pcols = ["run", "page", "doc_type", "split", "rows", "located", "verified", "recall", "unread"]
    pg.append(pcols)
    for row in pages_rows:
        pg.append([row[c] for c in pcols])

    tmp = out_path.with_name(out_path.stem + f".{__import__('os').getpid()}.xlsx")
    wb.save(tmp)
    __import__("os").replace(tmp, out_path)

    # csv of readers sheet beside it
    csv_path = out_path.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=rcols)
        w.writeheader()
        for row in readers_rows:
            w.writerow({c: row[c] for c in rcols})

    # pair consistency
    pair_results = []
    if pairs:
        for a, b in pairs:
            ra = results_by_path[str(Path(a))]
            rb = results_by_path[str(Path(b))]
            ab, ba = consistency(ra, rb)
            pair_results.append((str(Path(a)), str(Path(b)), ab, ba))
            print(f"pair {Path(a).name} -> {Path(b).name}: {ab:.4f}; {Path(b).name} -> {Path(a).name}: {ba:.4f}")

    # print readers table
    print("run input split pages_done verified precision_verified recall unread")
    for row in readers_rows:
        print(f"{row['run']} {row['input']} {row['split']} {row['pages_done']} {row['verified']} "
              f"{row['precision_verified']:.4f} {row['recall']:.4f} {row['unread']}")

    return {
        "out": str(out_path),
        "csv": str(csv_path),
        "ref_cells": len(ref_cells),
        "runs": all_run_results,
        "pairs": pair_results,
        "readers_rows": readers_rows,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="T-180: score reader transcription runs")
    ap.add_argument("--pages", required=True, type=Path)
    ap.add_argument("--pdf-pages", required=True, type=Path)
    ap.add_argument("--runs", nargs="+", required=True, type=Path)
    ap.add_argument("--pair", nargs=2, action="append", default=None)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    pairs = [(a, b) for a, b in (args.pair or [])]
    run(args.pages, args.pdf_pages, args.runs, args.out, pairs=pairs)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
