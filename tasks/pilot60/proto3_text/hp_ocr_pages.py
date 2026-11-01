"""Run on the HP: OCR the one-page PDFs from thin_pages.py with TextRecognizer, 300 DPI grayscale.

Writes ocr_pages.jsonl.gz in the current folder, one row per page, for extract60's T-034 overlay.
A failed page keeps its row with empty text and an error, so nothing is lost silently.
"""
import gzip
import json
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

from reality_engine.scripts import hp_ocr_large as ocr

PAGES = Path(r"C:\RE\raw\proto3_pages")
NAME = sys.argv[1]
LIMIT = int(sys.argv[2]) if len(sys.argv) > 2 else 0
NUMBER = re.compile(r"\(?(\d[\d,]*(?:\.\d+)?)\)?%?")
LOW_CONF = 0.9  # tasks/ocr/OCR_ON_HP_FINDINGS_2026-11-01.md: numbers at 0.9 or above were 98.03% right


def main() -> int:
    plan = [json.loads(line) for line in (PAGES / "plan.jsonl").read_text(encoding="utf-8").splitlines()]
    if LIMIT:
        plan = plan[:LIMIT]
    images = ocr.WORK / NAME / "images"
    images.mkdir(parents=True, exist_ok=True)
    entries, jobs = [], []
    for row in plan:
        out = images / (row["file_name"][:-4] + ".png")
        entries.append({"id": row["file_name"], "image": str(out)})
        if not out.exists():
            jobs.append((row["file_name"], str(PAGES / row["file_name"]), 0, 300, str(out), "gray"))
    with ProcessPoolExecutor(max_workers=4) as pool:
        list(pool.map(ocr._render_job, jobs, chunksize=4))
    print("rendered", len(jobs), flush=True)
    rows = {row["id"]: row for row in ocr.run_entries(NAME, entries, batch=100)}
    failed = 0
    with gzip.open("ocr_pages.jsonl.gz", "wt", encoding="utf-8") as handle:
        for row in plan:
            got = rows.get(row["file_name"]) or {"error": "no row"}
            words = [word for line in got.get("line_rows") or [] for word in line.get("words") or []]
            scores = [float(word["confidence"]) for word in words if word.get("confidence") is not None]
            low = [word["text"].strip() for word in words
                   if word.get("confidence") is not None and float(word["confidence"]) < LOW_CONF
                   and NUMBER.fullmatch((word.get("text") or "").strip())]
            failed += bool(got.get("error"))
            handle.write(json.dumps({
                **row,
                "text": got.get("text") or "",
                "mean_confidence": round(sum(scores) / len(scores), 4) if scores else None,
                "low_conf_numbers": low,
                "error": got.get("error"),
            }, ensure_ascii=False) + "\n")
    print("pages", len(plan), "failed", failed, "blank", sum(not (rows.get(r["file_name"]) or {}).get("text") for r in plan), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
