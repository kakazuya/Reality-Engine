"""Run on the HP: OCR pages planned by plan.jsonl with Microsoft TextRecognizer, 300 DPI grayscale.

A plan row is ``{"symbol","doc_key","page","pdf"}`` (``pdf`` relative to ``--docs``); the older
proto3 form ``{"file_name","page"}`` still works.  Writes one row per page to ``--out`` (gzip
JSONL) in the current folder: ``id`` = ``symbol|doc_key|page``, the plan row carried through, the
page text, ``mean_confidence``, ``low_conf_numbers``, ``seconds`` and an ``error`` for a page that
failed even after the driver's two retries (kept, never dropped silently).

Batches are resumable: each batch's rows are saved to ``parts/<start>.jsonl`` and its images are
deleted, so a restart picks up where it stopped and the disk stays free.
"""
import argparse
import gzip
import json
import re
import shutil
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

try:
    from reality_engine.scripts import hp_ocr_large as ocr
except ImportError:                      # HP run folder: the driver is copied next to this file
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import hp_ocr_large as ocr

BATCH = 200
NUMBER = re.compile(r"\(?(\d[\d,]*(?:\.\d+)?)\)?%?")
LOW_CONF = 0.9  # tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md: numbers at 0.9 or above were 98.03% right


def key(row: dict) -> str:
    if "doc_key" in row:
        return f"{row['symbol']}|{row['doc_key']}|{row['page']}"
    return f"{row['file_name'][:-4]}_{row['page']:04d}"


def page_row(row: dict, got: dict) -> dict:
    words = [word for line in got.get("line_rows") or [] for word in line.get("words") or []]
    scored = [word for word in words if word.get("confidence") is not None]
    scores = [float(word["confidence"]) for word in scored]
    low = [word["text"].strip() for word in scored
           if float(word["confidence"]) < LOW_CONF and NUMBER.fullmatch((word.get("text") or "").strip())]
    return {**row, "id": key(row), "text": got.get("text") or "",
            "line_rows": got.get("line_rows") or [],
            "mean_confidence": round(sum(scores) / len(scores), 4) if scores else None,
            "low_conf_numbers": low, "seconds": got.get("seconds"), "error": got.get("error")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("name")
    ap.add_argument("limit", nargs="?", type=int, default=0)
    ap.add_argument("--docs", default=r"C:\RE\raw\proto3_docs", help="folder the plan's pdf paths are relative to")
    ap.add_argument("--plan", default=None, help="default <docs>/plan.jsonl")
    ap.add_argument("--out", default="ocr_pages.jsonl.gz")
    ap.add_argument("--log", default=None, help="append progress lines here (a task has no console)")
    ap.add_argument("--summary", default=None, help="write run totals as JSON here")
    args = ap.parse_args()
    docs = Path(args.docs)
    plan_path = Path(args.plan) if args.plan else docs / "plan.jsonl"
    plan = [json.loads(line) for line in plan_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if args.limit:
        plan = plan[:args.limit]
    log_path = Path(args.log) if args.log else None

    def note(message: str) -> None:
        print(message, flush=True)
        if log_path:
            with open(log_path, "a", encoding="utf-8") as handle:
                handle.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {message}\n")

    started = time.time()
    note(f"start plan={plan_path} pages={len(plan)}")
    parts = Path("parts")
    parts.mkdir(exist_ok=True)
    for start in range(0, len(plan), BATCH):
        part = parts / f"{start:06d}.jsonl"
        if part.exists():
            continue
        batch = plan[start:start + BATCH]
        name = f"{args.name}-{start:06d}"
        images = ocr.WORK / name / "images"
        images.mkdir(parents=True, exist_ok=True)
        entries = [{"id": key(row), "image": str(images / f"{start + index:06d}.png")}
                   for index, row in enumerate(batch)]
        jobs = [(key(row), str(docs / (row.get("pdf") or row["file_name"])), row["page"] - 1, 300,
                 entry["image"], "gray") for row, entry in zip(batch, entries)]
        t0 = time.time()
        failed_render: dict[str, str] = {}
        with ProcessPoolExecutor(max_workers=4) as pool:
            futures = [pool.submit(ocr._render_job, job) for job in jobs]
            for future, entry in zip(futures, entries):
                try:
                    future.result()
                except Exception as ex:      # one unrenderable page must not lose the whole batch
                    failed_render[entry["id"]] = f"render {type(ex).__name__}: {ex}"
        ok = [entry for entry in entries if entry["id"] not in failed_render]
        try:
            got = {row["id"]: row for row in ocr.run_entries(name, ok, batch=BATCH)} if ok else {}
        except Exception as ex:              # a helper failure keeps the batch, as error rows
            got = {}
            for entry in ok:
                failed_render.setdefault(entry["id"], f"{type(ex).__name__}: {ex}")
        got.update({entry_id: {"error": error} for entry_id, error in failed_render.items()})
        temp = part.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(page_row(row, got.get(key(row)) or {"error": "no row"}),
                                          ensure_ascii=False) + "\n" for row in batch), encoding="utf-8")
        temp.replace(part)
        shutil.rmtree(ocr.WORK / name, ignore_errors=True)
        errors = sum(1 for row in batch if (got.get(key(row)) or {}).get("error"))
        note(f"pages {start + len(batch)} of {len(plan)} in {time.time() - t0:.0f}s, errors {errors}")
    failed = blank = total = 0
    with gzip.open(args.out, "wt", encoding="utf-8") as handle:
        for part in sorted(parts.glob("*.jsonl")):
            for line in part.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                total += 1
                failed += bool(row["error"])
                blank += not row["text"]
                handle.write(line + "\n")
    summary = {"pages": total, "plan_pages": len(plan), "failed": failed, "blank": blank,
               "seconds": round(time.time() - started, 1)}
    if args.summary:
        Path(args.summary).write_text(json.dumps(summary, indent=1), encoding="utf-8")
    note("pages {pages} failed {failed} blank {blank} in {seconds}s".format(**summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
