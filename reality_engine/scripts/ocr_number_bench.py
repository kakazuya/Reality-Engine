"""Number recall/precision bench for OCR engines on financial-table pages.

Truth is the PDF text layer; numbers are the distinct tokens matching
``\\d[\\d,]*(?:\\.\\d+)?`` with the commas stripped (the measure the Windows OCR
run was scored with).  A page is a *table* page when its text layer carries at
least 15 numeric tokens, at least 8 of them with 3+ digits, and numbers are at
least 12% of its words.

Modes are separate so each is one process and the OCR engine (RapidOCR, only
installed in some interpreters) is imported only where it is used::

    python -m reality_engine.scripts.ocr_number_bench sample --out .tmp/ocr_bench
    python -m reality_engine.scripts.ocr_number_bench ocr  --out .tmp/ocr_bench --config asis3
    python -m reality_engine.scripts.ocr_number_bench score --out .tmp/ocr_bench --config asis3
    python -m reality_engine.scripts.ocr_number_bench census --out .tmp/ocr_bench

``sample`` renders with pypdfium2 (3x by default) and stores the truth text.
``ocr`` needs ``rapidocr`` + ``pypdfium2`` and writes one row per page with the
wall seconds.  ``score`` is pure stdlib.  ``census`` is read-only: it opens every
``is_scanned_guess=1`` PDF in the pilot-60 manifest and counts pages whose text
layer is under 100 characters, per document type.

Read-only on the data root.  Nothing here writes a database.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sqlite3
import statistics
import sys
import time
from pathlib import Path

DEFAULT_MANIFEST = (r"C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine"
                    r"\data\pilot\pilot60_history_manifest.db")
SEED = 20261031
SCALE = 3
MIN_FREE_MB = 1500

# Brief quotas: annual reports 30, results 45, decks 30, transcripts 5.
DOC_TYPES = {
    "annual_report": {"table": 30, "docs": 14, "page_cap": 420},
    "quarterly_results": {"table": 45, "docs": 45, "page_cap": 60},
    "investor_presentation": {"table": 30, "docs": 24, "page_cap": 90},
    "concall_transcript": {"table": 5, "docs": 70, "page_cap": 40},
}
# 40 prose pages, split like the table quotas so no doc type is absent.
PROSE_QUOTA = {"annual_report": 11, "quarterly_results": 16,
               "investor_presentation": 9, "concall_transcript": 4}
PROSE_MIN_WORDS = 60
LOW_TEXT_CHARS = 100

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"\S+")
WORDLIKE = re.compile(r"[A-Za-z]{2,}")


# --------------------------------------------------------------------------- #
# Measure
# --------------------------------------------------------------------------- #

def numbers(text: str) -> list[str]:
    """Distinct numbers, commas removed so 1,433 and 1433 compare equal."""
    out: list[str] = []
    for match in NUMBER.findall(text):
        value = match.replace(",", "").rstrip(".")
        if value and value not in out:
            out.append(value)
    return out


def digit_count(token: str) -> int:
    return sum(ch.isdigit() for ch in token.replace(",", ""))


def page_stats(text: str) -> dict:
    tokens = WORD.findall(text)
    found = NUMBER.findall(text)
    distinct = numbers(text)
    return {
        "words": len(tokens),
        "numeric_tokens": len(found),
        "long_numeric": sum(1 for t in found if digit_count(t) >= 3),
        "distinct_numeric": len(distinct),
        "numeric_share": round(len(found) / len(tokens), 4) if tokens else 0.0,
    }


def is_table_page(stats: dict) -> bool:
    return (stats["numeric_tokens"] >= 15 and stats["long_numeric"] >= 8
            and stats["numeric_share"] >= 0.12)


def score_page(truth: str, ocr: str) -> dict:
    """Recall/precision over distinct numbers; micro counts kept for pooling."""
    truth_numbers = numbers(truth)
    ocr_numbers = numbers(ocr)
    hit = [n for n in truth_numbers if n in set(ocr_numbers)]
    true_ocr = [n for n in ocr_numbers if n in set(truth_numbers)]
    return {
        "truth_numbers": len(truth_numbers),
        "ocr_numbers": len(ocr_numbers),
        "recall_hits": len(hit),
        "precision_hits": len(true_ocr),
        "recall": round(len(hit) / len(truth_numbers), 4) if truth_numbers else None,
        "precision": round(len(true_ocr) / len(ocr_numbers), 4) if ocr_numbers else None,
        "missing": [n for n in truth_numbers if n not in set(ocr_numbers)][:12],
        "spurious": [n for n in ocr_numbers if n not in set(truth_numbers)][:12],
    }


def summarize(rows: list[dict]) -> dict:
    """Micro (pooled counts) and macro (mean of page scores) recall/precision."""
    truth = sum(r["truth_numbers"] for r in rows)
    ocr = sum(r["ocr_numbers"] for r in rows)
    hits = sum(r["recall_hits"] for r in rows)
    true_ocr = sum(r["precision_hits"] for r in rows)
    recalls = [r["recall"] for r in rows if r.get("recall") is not None]
    precisions = [r["precision"] for r in rows if r.get("precision") is not None]
    return {
        "pages": len(rows),
        "truth_numbers": truth,
        "ocr_numbers": ocr,
        "micro_recall": round(hits / truth, 4) if truth else None,
        "micro_precision": round(true_ocr / ocr, 4) if ocr else None,
        "macro_recall": round(statistics.fmean(recalls), 4) if recalls else None,
        "macro_precision": round(statistics.fmean(precisions), 4) if precisions else None,
    }


def free_mb() -> int:
    import ctypes

    class MemoryStatus(ctypes.Structure):
        _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]

    status = MemoryStatus()
    status.dwLength = ctypes.sizeof(MemoryStatus)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return int(status.ullAvailPhys // (1024 * 1024))


def check_ram(floor: int = MIN_FREE_MB) -> None:
    available = free_mb()
    if available < floor:
        raise SystemExit(f"stop: free RAM {available} MB is under the {floor} MB floor")


# --------------------------------------------------------------------------- #
# Data access
# --------------------------------------------------------------------------- #

def manifest_docs(manifest: Path) -> list[dict]:
    con = sqlite3.connect("file:" + str(manifest).replace("\\", "/") + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT bucket, symbol_at_time, local_path FROM docs "
            "WHERE local_path IS NOT NULL AND is_pdf = 1 ORDER BY local_path").fetchall()
    finally:
        con.close()
    out = []
    for bucket, symbol, path in rows:
        if bucket not in DOC_TYPES:
            continue
        if not Path(path).exists():
            continue
        out.append({"doc_type": bucket, "symbol": symbol, "path": path})
    return out


def pdfium():
    try:
        import pypdfium2
    except ImportError:  # the reader's interpreter may need the system site-packages
        sys.path.insert(0, r"C:\Users\warri\AppData\Local\Programs\Python"
                              r"\Python314\Lib\site-packages")
        import pypdfium2
    return pypdfium2


def render_page(page, scale: int):
    return page.render(scale=scale).to_pil()


def page_text(page) -> str:
    return page.get_textpage().get_text_range() or ""


# --------------------------------------------------------------------------- #
# Modes
# --------------------------------------------------------------------------- #

def mode_sample(args) -> int:
    check_ram()
    out = Path(args.out)
    (out / "pages").mkdir(parents=True, exist_ok=True)
    docs = manifest_docs(Path(args.manifest))
    by_type: dict[str, list[dict]] = {}
    for doc in docs:
        by_type.setdefault(doc["doc_type"], []).append(doc)
    rng = random.Random(args.seed)
    pdf = pdfium()
    picked: list[dict] = []
    for doc_type, spec in DOC_TYPES.items():
        pool = by_type.get(doc_type, [])
        rng.shuffle(pool)
        tables, prose = [], []
        for doc in pool[: spec["docs"]]:
            try:
                document = pdf.PdfDocument(doc["path"])
            except Exception as exc:  # unreadable PDF: skip, never abort the sample
                print(f"skip {doc['path']}: {exc}", flush=True)
                continue
            try:
                for index in range(min(len(document), spec["page_cap"])):
                    text = page_text(document[index])
                    if len(text.strip()) < 120:
                        continue
                    stats = page_stats(text)
                    entry = dict(doc, page=index, truth=text, **stats)
                    if is_table_page(stats):
                        tables.append(entry)
                    elif stats["words"] >= PROSE_MIN_WORDS:
                        prose.append(entry)
            finally:
                document.close()
        take = min(spec["table"], len(tables))
        if take < spec["table"]:
            print(f"note: {doc_type} yielded {take}/{spec['table']} table pages", flush=True)
        picked.extend(rng.sample(tables, take))
        wanted = PROSE_QUOTA[doc_type]
        picked.extend(rng.sample(prose, min(wanted, len(prose))))
    rows = []
    for index, entry in enumerate(picked):
        row = dict(entry)
        row["id"] = f"{index:03d}_{entry['doc_type'][:6]}_{entry['page']}"
        row["kind"] = "table" if is_table_page(page_stats(entry["truth"])) else "prose"
        rows.append(row)
    # render the kept pages and store truth beside them
    kept, started = [], time.time()
    for row in rows:
        try:
            document = pdf.PdfDocument(row["path"])
            page = document[row["page"]]
            image = render_page(page, args.scale)
            png = out / "pages" / f"{row['id']}_s{args.scale}.png"
            image.save(png)
            row["png"] = str(png)
            row["truth_chars"] = len(row["truth"])
            kept.append(row)
            document.close()
        except Exception as exc:
            print(f"render skip {row['id']}: {exc}", flush=True)
    with (out / "sample.jsonl").open("w", encoding="utf-8") as handle:
        for row in kept:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    elapsed = time.time() - started
    tables = sum(1 for r in kept if r["kind"] == "table")
    print(json.dumps({"pages": len(kept), "table": tables, "prose": len(kept) - tables,
                      "render_seconds": round(elapsed, 1),
                      "by_type": {t: sum(1 for r in kept if r["doc_type"] == t)
                                  for t in DOC_TYPES},
                      "free_mb": free_mb()}, indent=2))
    return 0


class MediaOcrEngine:
    """Windows.Media.Ocr, the engine that ships with Windows (PyWinRT projection).

    The projection wheels are not installable from pip on this box (its temp dirs
    are ACL-restricted), so ``.tmp/pylib`` is added to ``sys.path`` when present.
    """

    name = "windows_media_ocr"

    def __init__(self):
        sys.path.insert(0, str(Path(".tmp/pylib")))
        from winrt.windows.media.ocr import OcrEngine
        engine = OcrEngine.try_create_from_user_profile_languages()
        if engine is None:
            raise SystemExit("no Windows OCR language pack for this user profile")
        self.engine = engine

    def __call__(self, source) -> str:
        import asyncio

        import numpy as np
        from PIL import Image

        if isinstance(source, (str, Path)):
            with Image.open(source) as image:
                array = np.asarray(image.convert("RGB"))
        else:
            array = np.asarray(source)
        return asyncio.run(self._run(array))

    async def _run(self, array) -> str:
        import numpy as np
        from winrt.windows.graphics.imaging import (
            BitmapAlphaMode, BitmapPixelFormat, SoftwareBitmap)
        from winrt.windows.security.cryptography import CryptographicBuffer

        if array.ndim == 2:
            array = np.stack([array] * 3, axis=-1)
        if array.shape[2] == 4:
            bgra = array[:, :, [2, 1, 0, 3]]
        else:
            alpha = np.full(array.shape[:2] + (1,), 255, np.uint8)
            bgra = np.concatenate([array[:, :, 2::-1], alpha], axis=2)
        bitmap = SoftwareBitmap(BitmapPixelFormat.BGRA8, bgra.shape[1], bgra.shape[0],
                                BitmapAlphaMode.PREMULTIPLIED)
        bitmap.copy_from_buffer(CryptographicBuffer.create_from_byte_array(
            np.ascontiguousarray(bgra).tobytes()))
        result = await self.engine.recognize_async(bitmap)
        return "\n".join(line.text for line in result.lines)


def mode_ocr(args) -> int:
    check_ram(args.min_free_mb)
    out = Path(args.out)
    rows = [json.loads(line) for line in
            (out / "sample.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    target = out / f"ocr_{args.config}.jsonl"
    done = set()
    if target.exists():  # a stopped run resumes where it stopped
        done = {json.loads(line)["id"] for line in
                target.read_text(encoding="utf-8").splitlines() if line.strip()}
    rows = [row for row in rows if row["id"] not in done]
    if args.every > 1:
        rows = rows[:: args.every]
    if args.limit:
        rows = rows[: args.limit]
    reuse = {}
    if args.from_config:
        for line in (out / f"ocr_{args.from_config}.jsonl").read_text(
                encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                reuse[row["id"]] = row["text"]
    params = {"Global.max_side_len": args.max_side} if args.max_side else None
    if args.engine == "windows":
        engine = MediaOcrEngine()
    else:
        from rapidocr import RapidOCR
        engine = RapidOCR(params=params)
    started, count, handle = time.time(), 0, target.open("a", encoding="utf-8")
    retried = 0
    try:
        for row in rows:
            png = Path(row["png"])
            if args.scale != args.sample_scale:
                png = png.with_name(png.name.replace(f"_s{args.sample_scale}", f"_s{args.scale}"))
                if not png.exists():
                    document = pdfium().PdfDocument(row["path"])
                    render_page(document[row["page"]], args.scale).save(png)
                    document.close()
            previous = reuse.get(row["id"])
            if previous is not None and not needs_rotation(previous, args):
                item = {"id": row["id"], "kind": row["kind"], "doc_type": row["doc_type"],
                        "symbol": row["symbol"], "page": row["page"], "png": str(png),
                        "seconds": 0.0, "chars": len(previous), "rotated": False,
                        "reused": True, "text": previous}
            else:
                t0 = time.time()
                text, rotated = ocr_page(engine, png, args)
                item = {"id": row["id"], "kind": row["kind"], "doc_type": row["doc_type"],
                        "symbol": row["symbol"], "page": row["page"], "png": str(png),
                        "seconds": round(time.time() - t0, 3), "chars": len(text),
                        "rotated": rotated, "reused": False, "text": text}
                retried += 1
                print(f"{row['id']:22s} {item['seconds']:6.2f}s {item['chars']:5d}ch "
                      f"{text[:60]!r}", flush=True)
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
            handle.flush()
            count += 1
            if count % 10 == 0:
                check_ram(args.min_free_mb)
    finally:
        handle.close()
    seconds = time.time() - started
    print(json.dumps({"config": args.config, "pages": len(rows), "pages_ocred": retried,
                      "done_total": len(done) + count,
                      "seconds": round(seconds, 1),
                      "pages_per_min": round(retried / seconds * 60, 2) if seconds else None,
                      "free_mb": free_mb()}, indent=2))
    return 0


def needs_rotation(text: str, args) -> bool:
    """The retry trigger: under 40 characters or under 3 word-like tokens."""
    return args.rotate and (len(text) < 40 or len(WORDLIKE.findall(text)) < 3)


def raw_text(engine, source) -> str:
    """One page of text; RapidOCR returns an output object, MediaOcr a string."""
    result = engine(source)
    return result if isinstance(result, str) else "\n".join(result.txts or [])


def ocr_page(engine, png: Path, args) -> tuple[str, bool]:
    from PIL import Image

    text = raw_text(engine, str(png))
    if not needs_rotation(text, args):
        return text, False
    import numpy as np

    with Image.open(png) as image:
        for angle in (90, 270):
            candidate = raw_text(engine, np.asarray(image.rotate(angle, expand=True)))
            if len(candidate) > len(text):
                text = candidate
    return text, True


def mode_score(args) -> int:
    out = Path(args.out)
    sample = {json.loads(line)["id"]: json.loads(line) for line in
              (out / "sample.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()}
    configs = args.config or [p.stem.replace("ocr_", "") for p in out.glob("ocr_*.jsonl")]
    summary, failures = {}, []
    for config in configs:
        path = out / f"ocr_{config}.jsonl"
        if not path.exists():
            continue
        rows = []
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            ocr = json.loads(line)
            truth = sample[ocr["id"]]["truth"]
            row = {"id": ocr["id"], "kind": ocr["kind"], "doc_type": ocr["doc_type"],
                   "symbol": ocr["symbol"], "seconds": ocr["seconds"],
                   "chars": ocr["chars"], "rotated": ocr["rotated"],
                   **score_page(truth, ocr["text"])}
            rows.append(row)
            if row["recall"] is not None and row["recall"] < 0.8:
                failures.append(row)
        summary[config] = {
            "all": summarize(rows),
            "table": summarize([r for r in rows if r["kind"] == "table"]),
            "prose": summarize([r for r in rows if r["kind"] == "prose"]),
            "by_type": {t: summarize([r for r in rows if r["doc_type"] == t])
                        for t in DOC_TYPES if any(r["doc_type"] == t for r in rows)},
            "seconds": round(sum(r["seconds"] for r in rows), 1),
            "pages_per_min": round(len(rows) / sum(r["seconds"] for r in rows) * 60, 2)
            if rows and sum(r["seconds"] for r in rows) else None,
            "rotated": sum(1 for r in rows if r["rotated"]),
        }
        scores = out / f"scores_{config}.jsonl"
        with scores.open("w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
    failures.sort(key=lambda r: r["recall"] or 0)
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    (out / "failures.json").write_text(json.dumps(failures[: int(args.failures)],
                                                  indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=2))
    return 0


def mode_census(args) -> int:
    """Read-only: pages with under 100 characters of text in every scanned-guess PDF."""
    check_ram()
    con = sqlite3.connect("file:" + str(args.manifest).replace("\\", "/") + "?mode=ro", uri=True)
    try:
        rows = con.execute(
            "SELECT bucket, symbol_at_time, local_path FROM docs "
            "WHERE is_scanned_guess = 1 AND local_path IS NOT NULL ORDER BY local_path").fetchall()
    finally:
        con.close()
    pdf = pdfium()
    by_type: dict[str, dict] = {}
    started = time.time()
    for bucket, _symbol, path in rows:
        if not Path(path).exists():
            continue
        stats = by_type.setdefault(bucket or "?", {"docs": 0, "pages": 0, "low_text": 0,
                                                   "failed": 0})
        stats["docs"] += 1
        try:
            document = pdf.PdfDocument(path)
        except Exception:
            stats["failed"] += 1
            continue
        try:
            stats["pages"] += len(document)
            for index in range(len(document)):
                if len(page_text(document[index]).strip()) < LOW_TEXT_CHARS:
                    stats["low_text"] += 1
        except Exception:
            stats["failed"] += 1
        finally:
            document.close()
        if sum(s["docs"] for s in by_type.values()) % 100 == 0:
            check_ram()
    total = {"docs": sum(s["docs"] for s in by_type.values()),
             "pages": sum(s["pages"] for s in by_type.values()),
             "low_text": sum(s["low_text"] for s in by_type.values()),
             "failed": sum(s["failed"] for s in by_type.values())}
    report = {"by_type": by_type, "total": total,
              "seconds": round(time.time() - started, 1), "free_mb": free_mb()}
    Path(args.out).mkdir(parents=True, exist_ok=True)
    (Path(args.out) / "census.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m reality_engine.scripts.ocr_number_bench")
    sub = ap.add_subparsers(dest="mode", required=True)

    sample = sub.add_parser("sample", help="pick pages with a fixed seed, render, store truth")
    sample.add_argument("--out", required=True)
    sample.add_argument("--manifest", default=DEFAULT_MANIFEST)
    sample.add_argument("--scale", type=int, default=SCALE)
    sample.add_argument("--seed", type=int, default=SEED)
    sample.set_defaults(func=mode_sample)

    ocr = sub.add_parser("ocr", help="run RapidOCR on the rendered pages")
    ocr.add_argument("--out", required=True)
    ocr.add_argument("--config", default="asis3")
    ocr.add_argument("--scale", type=int, default=SCALE)
    ocr.add_argument("--sample-scale", type=int, default=SCALE)
    ocr.add_argument("--max-side", type=int, default=0,
                     help="rise above RapidOCR's 2000-px preprocess cap (0 = as shipped)")
    ocr.add_argument("--rotate", action="store_true",
                     help="retry 90/270 degrees under 40 chars or under 3 word-like tokens")
    ocr.add_argument("--from-config", default="",
                     help="reuse another run's text where the retry trigger does not fire")
    ocr.add_argument("--every", type=int, default=1, help="take every Nth page of the sample")
    ocr.add_argument("--limit", type=int, default=0)
    ocr.add_argument("--engine", choices=("rapidocr", "windows"), default="rapidocr")
    ocr.add_argument("--min-free-mb", type=int, default=MIN_FREE_MB,
                     help="stop when system free RAM falls under this (default 1500)")
    ocr.set_defaults(func=mode_ocr)

    score = sub.add_parser("score", help="recall/precision against the text layer")
    score.add_argument("--out", required=True)
    score.add_argument("--config", nargs="*", default=None)
    score.add_argument("--failures", type=int, default=30)
    score.set_defaults(func=mode_score)

    census = sub.add_parser("census", help="read-only low-text page census of scanned PDFs")
    census.add_argument("--out", required=True)
    census.add_argument("--manifest", default=DEFAULT_MANIFEST)
    census.set_defaults(func=mode_census)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
