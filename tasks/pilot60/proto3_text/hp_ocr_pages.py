"""Run on the HP: OCR the pages planned by thin_pages.py with TextRecognizer, 300 DPI grayscale.

Writes ocr_pages.jsonl.gz in the current folder, one row per page, for extract60. Works in
batches: each batch's rows are saved and its images deleted, so a restart resumes and the disk
stays free. A failed page keeps its row with empty text and an error, so nothing is lost silently.
"""
import gzip
import json
import re
import shutil
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from reality_engine.scripts import hp_ocr_large as ocr

DOCS = Path(r"C:\RE\raw\proto3_docs")
NAME = sys.argv[1]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
BATCH = 200
NUMBER = re.compile(r"\(?(\d[\d,]*(?:\.\d+)?)\)?%?")
LOW_CONF = 0.9  # tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md: numbers at 0.9 or above were 98.03% right


def key(row: dict) -> str:
    return f"{row['file_name'][:-4]}_{row['page']:04d}"


def page_row(row: dict, got: dict) -> dict:
    words = [word for line in got.get("line_rows") or [] for word in line.get("words") or []]
    scored = [word for word in words if word.get("confidence") is not None]
    scores = [float(word["confidence"]) for word in scored]
    low = [word["text"].strip() for word in scored
           if float(word["confidence"]) < LOW_CONF and NUMBER.fullmatch((word.get("text") or "").strip())]
    return {**row, "text": got.get("text") or "",
            "mean_confidence": round(sum(scores) / len(scores), 4) if scores else None,
            "low_conf_numbers": low, "error": got.get("error")}


def main() -> int:
    plan = [json.loads(line) for line in (DOCS / "plan.jsonl").read_text(encoding="utf-8").splitlines()]
    if LIMIT:
        plan = plan[:LIMIT]
    parts = Path("parts")
    parts.mkdir(exist_ok=True)
    for start in range(0, len(plan), BATCH):
        part = parts / f"{start:06d}.jsonl"
        if part.exists():
            continue
        batch = plan[start:start + BATCH]
        name = f"{NAME}-{start:06d}"
        images = ocr.WORK / name / "images"
        images.mkdir(parents=True, exist_ok=True)
        entries = [{"id": key(row), "image": str(images / f"{key(row)}.png")} for row in batch]
        jobs = [(key(row), str(DOCS / row["file_name"]), row["page"] - 1, 300, entry["image"], "gray")
                for row, entry in zip(batch, entries)]
        with ProcessPoolExecutor(max_workers=4) as pool:
            list(pool.map(ocr._render_job, jobs, chunksize=4))
        got = {row["id"]: row for row in ocr.run_entries(name, entries, batch=BATCH)}
        temp = part.with_suffix(".tmp")
        temp.write_text("".join(json.dumps(page_row(row, got.get(key(row)) or {"error": "no row"}), ensure_ascii=False) + "\n"
                                for row in batch), encoding="utf-8")
        temp.replace(part)
        shutil.rmtree(ocr.WORK / name, ignore_errors=True)
        print("pages done", start + len(batch), "of", len(plan), flush=True)
    failed = blank = total = 0
    with gzip.open("ocr_pages.jsonl.gz", "wt", encoding="utf-8") as handle:
        for part in sorted(parts.glob("*.jsonl")):
            for line in part.read_text(encoding="utf-8").splitlines():
                row = json.loads(line)
                total += 1
                failed += bool(row["error"])
                blank += not row["text"]
                handle.write(line + "\n")
    print("pages", total, "failed", failed, "blank", blank, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
