"""Frozen OCR test set and gate scoring for the HP OmniBook (2026-11-01).

Builds a fixed, seeded page set from PDFs that carry a real text layer, renders
each page once at 3x with pypdfium2, and stores the text layer as truth.  The
set never changes after :func:`build` writes ``pages.json``: every engine is
scored on the same page ids, and combinations are computed from the saved rows
without re-running an engine.

    python -m reality_engine.scripts.hp_ocr_gate build --out C:\\RE\\ocr_test
    python -m reality_engine.scripts.hp_ocr_gate score --engine C:\\RE\\ocr_test\\media
    python -m reality_engine.scripts.hp_ocr_gate combine --a media --b qnn

Metrics follow :mod:`reality_engine.scripts.hp_ocr_check`:

* ``accuracy``: 1 - Levenshtein(truth, ocr) / len(truth) on whitespace-normalised,
  case-folded text;
* ``numbers``: distinct tokens matching ``\\d[\\d,]*(?:\\.\\d+)?`` with commas
  stripped; ``number_recall`` = truth numbers found in OCR / truth numbers and
  ``number_precision`` = found / OCR numbers.  A page with truth numbers and an
  empty OCR scores 0 on both, so an engine cannot win precision by silence.

The table-page gate is number recall >= 0.95 and number precision >= 0.98 on
table pages.  Prose pages are reported for the overall row, not gated.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import time
from pathlib import Path

NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?")
WORD = re.compile(r"\S+")

DOC_TYPES = {
    "annual_report": "annual_report",
    "quarterly_results": "results",
    "investor_presentation": "deck",
    "concall_transcript": "transcript",
}
TABLE_QUOTA = {"annual_report": 30, "results": 45, "deck": 30, "transcript": 5}
PROSE_QUOTA = {"annual_report": 10, "results": 15, "deck": 10, "transcript": 5}
TABLE_RULE = {
    "min_chars": 100,
    "min_numbers": 15,
    "min_numbers_3digits": 8,
    "min_number_share": 0.12,
}
PROSE_RULE = {
    "min_chars": 300,
    "min_words": 60,
    "max_numbers": 8,
    "max_number_share": 0.06,
}
RENDER_SCALE = 3.0
GATE = {"number_recall": 0.95, "number_precision": 0.98}


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #

def normalize(text: str) -> str:
    return " ".join(text.split())


def numbers(text: str) -> list[str]:
    """Distinct numbers, commas stripped (the hp_ocr_bench definition)."""
    out: list[str] = []
    for match in NUMBER.findall(text):
        value = match.replace(",", "").rstrip(".")
        if value and value not in out:
            out.append(value)
    return out


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance with one vectorised row per character of ``a``."""
    import numpy as np

    if not a:
        return len(b)
    if not b:
        return len(a)
    if len(a) > len(b):
        a, b = b, a
    m = len(b)
    previous = np.arange(m + 1, dtype=np.int64)
    for i, ca in enumerate(a, start=1):
        cost = (np.frombuffer(b.encode("utf-32-le"), dtype=np.uint32)
                != ord(ca)).astype(np.int64)
        seed = np.minimum(previous[1:] + 1, previous[:-1] + cost)
        current = np.empty(m + 1, dtype=np.int64)
        current[0] = i
        current[1:] = np.minimum.accumulate(seed - np.arange(1, m + 1)) + np.arange(1, m + 1)
        previous = current
    return int(previous[m])


def char_accuracy(truth: str, ocr: str) -> float:
    truth_n = normalize(truth)
    if not truth_n:
        return 0.0
    distance = edit_distance(truth_n.casefold(), normalize(ocr).casefold())
    return max(0.0, 1.0 - distance / len(truth_n))


def order_free_accuracy(truth: str, ocr: str) -> float:
    truth_tokens = sorted(t.casefold() for t in WORD.findall(normalize(truth)))
    ocr_tokens = sorted(t.casefold() for t in WORD.findall(normalize(ocr)))
    if not truth_tokens:
        return 0.0
    truth_text = " ".join(truth_tokens)
    return max(0.0, 1.0 - edit_distance(truth_text, " ".join(ocr_tokens)) / len(truth_text))


def number_score(truth: str, ocr: str) -> dict:
    truth_numbers, ocr_numbers = numbers(truth), numbers(ocr)
    found = [n for n in truth_numbers if n in ocr_numbers]
    return {
        "number_truth": len(truth_numbers),
        "number_ocr": len(ocr_numbers),
        "number_found": len(found),
        "number_recall": round(len(found) / len(truth_numbers), 4) if truth_numbers else None,
        "number_precision": round(len(found) / len(ocr_numbers), 4) if ocr_numbers else 0.0,
        "numbers_missing": [n for n in truth_numbers if n not in ocr_numbers][:20],
        "numbers_extra": [n for n in ocr_numbers if n not in truth_numbers][:20],
    }


def score_page(truth: str, ocr: str) -> dict:
    return {
        "accuracy": round(char_accuracy(truth, ocr), 4),
        "order_free": round(order_free_accuracy(truth, ocr), 4),
        **number_score(truth, ocr),
        "truth_chars": len(normalize(truth)),
        "ocr_chars": len(normalize(ocr)),
    }


def mean(values) -> float | None:
    values = [v for v in values if v is not None]
    return round(sum(values) / len(values), 4) if values else None


def summarize(rows: list[dict]) -> dict:
    """Means overall, by kind (table/prose) and by document type."""
    out: dict = {"pages": len(rows)}
    groups = {"all": rows}
    for kind in ("table", "prose"):
        groups[kind] = [r for r in rows if r.get("kind") == kind]
    for doc_type in ("annual_report", "results", "deck", "transcript"):
        groups[f"table:{doc_type}"] = [r for r in rows
                                       if r.get("kind") == "table" and r.get("doc_type") == doc_type]
    for name, group in groups.items():
        if not group:
            continue
        out[name] = {
            "pages": len(group),
            "accuracy": mean(r.get("accuracy") for r in group),
            "order_free": mean(r.get("order_free") for r in group),
            "number_recall": mean(r.get("number_recall") for r in group),
            "number_precision": mean(r.get("number_precision") for r in group),
            "pages_per_min": None,
        }
    return out


def gate_verdict(summary: dict) -> dict:
    table = summary.get("table") or {}
    recall, precision = table.get("number_recall"), table.get("number_precision")
    passed = (recall is not None and precision is not None
              and recall >= GATE["number_recall"] and precision >= GATE["number_precision"])
    return {"number_recall": recall, "number_precision": precision,
            "gate": GATE, "passed": bool(passed)}


# --------------------------------------------------------------------------- #
# Frozen set build
# --------------------------------------------------------------------------- #

def page_stats(text: str) -> dict:
    normal = normalize(text)
    numeric_tokens = NUMBER.findall(normal)
    words = WORD.findall(normal)
    with_digits = [t for t in numeric_tokens if sum(c.isdigit() for c in t) >= 3]
    return {
        "chars": len(normal),
        "words": len(words),
        "numbers": len(numeric_tokens),
        "numbers_3digits": len(with_digits),
        "number_share": round(len(numeric_tokens) / len(words), 4) if words else 0.0,
    }


def is_table_page(stats: dict) -> bool:
    return (stats["chars"] >= TABLE_RULE["min_chars"]
            and stats["numbers"] >= TABLE_RULE["min_numbers"]
            and stats["numbers_3digits"] >= TABLE_RULE["min_numbers_3digits"]
            and stats["number_share"] >= TABLE_RULE["min_number_share"])


def is_prose_page(stats: dict) -> bool:
    return (stats["chars"] >= PROSE_RULE["min_chars"]
            and stats["words"] >= PROSE_RULE["min_words"]
            and stats["numbers"] <= PROSE_RULE["max_numbers"]
            and stats["number_share"] <= PROSE_RULE["max_number_share"]
            and stats["numbers_3digits"] <= 2)


def candidate_pdfs(base: Path) -> dict[str, list[Path]]:
    out: dict[str, list[Path]] = {name: [] for name in set(DOC_TYPES.values())}
    for pdf in base.rglob("*.pdf"):
        mapped = DOC_TYPES.get(pdf.parent.name)
        if mapped:
            out[mapped].append(pdf)
    for name in out:
        out[name].sort()
    return out


def pick_pages(pdf: Path, want: str, rng: random.Random, seen: set[int],
               max_pages: int = 0) -> tuple[int, str, dict, int] | None:
    """Find one unseen page in ``pdf`` that matches the table/prose rule."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        count = len(doc)
        if count <= 0:
            return None
        indices = [i for i in range(count) if i not in seen]
        rng.shuffle(indices)
        if max_pages:
            indices = indices[:max_pages]
        checker = is_table_page if want == "table" else is_prose_page
        for index in indices:
            text = doc[index].get_textpage().get_text_range()
            stats = page_stats(text)
            if checker(stats):
                return index, text, stats, count
    finally:
        doc.close()
    return None


def render_page(pdf: Path, page: int, scale: float, out: Path) -> tuple[int, int]:
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        image = doc[page].render(scale=scale).to_pil().convert("RGB")
        image.save(out)
        return image.width, image.height
    finally:
        doc.close()


def build(out_dir: Path, base: Path, seed: int, scale: float) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    images = out_dir / "images"
    truth_dir = out_dir / "truth"
    images.mkdir(exist_ok=True)
    truth_dir.mkdir(exist_ok=True)
    rng = random.Random(seed)
    pdfs = candidate_pdfs(base)
    pages: list[dict] = []
    counters = {"table": 0, "prose": 0}
    for doc_type in ("annual_report", "results", "deck", "transcript"):
        for want, quota in (("table", TABLE_QUOTA[doc_type]),
                            ("prose", PROSE_QUOTA[doc_type])):
            picked = 0
            candidates = list(pdfs[doc_type])
            rng.shuffle(candidates)
            for pdf in candidates:
                if picked >= quota:
                    break
                # Annual reports and decks are long: inspect a bounded sample of
                # unseen pages so the build stays quick.  Transcripts are short
                # and often have few numeric pages, so every page is considered.
                max_pages = 0 if doc_type in ("transcript", "results") else 40
                found = pick_pages(pdf, want, rng, set(), max_pages=max_pages)
                if found is None:
                    continue
                page, text, stats, page_count = found
                counters[want] += 1
                page_id = f"{'T' if want == 'table' else 'P'}{counters[want]:04d}"
                image_path = images / f"{page_id}.png"
                render_page(pdf, page, scale, image_path)
                truth_path = truth_dir / f"{page_id}.txt"
                truth_path.write_text(text, encoding="utf-8")
                pages.append({
                    "id": page_id,
                    "kind": want,
                    "doc_type": doc_type,
                    "company": pdf.relative_to(base).parts[0],
                    "pdf": pdf.relative_to(base).as_posix(),
                    "page": page,
                    "page_count": page_count,
                    "image": str(image_path),
                    "truth_file": str(truth_path),
                    **stats,
                })
                picked += 1
                if picked % 5 == 0:
                    print(f"{doc_type}/{want}: {picked}/{quota}", flush=True)
            if picked < quota:
                print(f"WARNING: {doc_type}/{want} filled {picked}/{quota}", flush=True)

    manifest = {
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": seed,
        "base": str(base),
        "render_scale": scale,
        "table_rule": TABLE_RULE,
        "prose_rule": PROSE_RULE,
        "table_quota": TABLE_QUOTA,
        "prose_quota": PROSE_QUOTA,
        "gate": GATE,
        "pages": pages,
    }
    path = out_dir / "pages.json"
    path.write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"wrote {path} ({len(pages)} pages: "
          f"{sum(1 for p in pages if p['kind'] == 'table')} table, "
          f"{sum(1 for p in pages if p['kind'] == 'prose')} prose)")
    return manifest


def load_pages(path: Path) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    for page in manifest["pages"]:
        truth_file = page.get("truth_file")
        if truth_file and "truth" not in page:
            page["truth"] = Path(truth_file).read_text(encoding="utf-8")
    return manifest


# --------------------------------------------------------------------------- #
# Scoring saved engine rows
# --------------------------------------------------------------------------- #

def read_rows(engine_dir: Path) -> dict[str, dict]:
    """All rows of one engine keyed by page id; later duplicate ids win."""
    rows: dict[str, dict] = {}
    for path in sorted(engine_dir.glob("rows*.jsonl")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("id"):
                rows[row["id"]] = row
    return rows


def score_engine(engine_dir: Path, manifest: dict) -> dict:
    rows = read_rows(engine_dir)
    scored = []
    for page in manifest["pages"]:
        row = rows.get(page["id"])
        if row is None:
            continue
        item = {"id": page["id"], "kind": page["kind"], "doc_type": page["doc_type"],
                "pdf": page["pdf"], "page": page["page"],
                "seconds": row.get("seconds"), "engine": row.get("engine")}
        item.update(score_page(page["truth"], row.get("text", "")))
        scored.append(item)
    summary = summarize(scored)
    summary["verdict"] = gate_verdict(summary)
    seconds = sum(r["seconds"] for r in scored if r.get("seconds"))
    summary["seconds_scored"] = round(seconds, 2)
    summary["pages_per_min"] = round(len(scored) / seconds * 60, 2) if seconds else None
    if summary.get("table"):
        summary["table"]["pages_per_min"] = summary["pages_per_min"]
    summary["coverage"] = {"scored": len(scored), "set": len(manifest["pages"])}
    result = {"engine_dir": str(engine_dir), "summary": summary, "rows": scored}
    (engine_dir / "metrics.json").write_text(json.dumps(result, indent=1), encoding="utf-8")
    return result


# --------------------------------------------------------------------------- #
# Combinations
# --------------------------------------------------------------------------- #

def combine_pair(rows_a: dict[str, dict], rows_b: dict[str, dict],
                 manifest: dict) -> list[dict]:
    """Agreement/union rows for one engine pair on the pages both ran."""
    out = []
    for page in manifest["pages"]:
        a, b = rows_a.get(page["id"]), rows_b.get(page["id"])
        if a is None or b is None:
            continue
        truth = set(numbers(page["truth"]))
        na, nb = set(numbers(a.get("text", ""))), set(numbers(b.get("text", "")))
        for mode, chosen in (("agree", na & nb), ("union", na | nb),
                             ("a_only", na), ("b_only", nb)):
            found = truth & chosen
            out.append({
                "id": page["id"], "kind": page["kind"], "doc_type": page["doc_type"],
                "mode": mode,
                "number_recall": round(len(found) / len(truth), 4) if truth else None,
                "number_precision": round(len(found) / len(chosen), 4) if chosen else 0.0,
                "disagree": na != nb,
                "disagree_share": round(len(na ^ nb) / len(na | nb), 4) if (na | nb) else 0.0,
                "columns_fail": any(columns_add_up(row.get("text", "")) is False
                                    for row in (a, b) if row is not None),
            })
    return out


def combo_summary(rows: list[dict]) -> dict:
    out: dict = {}
    for mode in ("agree", "union", "a_only", "b_only"):
        group = [r for r in rows if r["mode"] == mode]
        table = [r for r in group if r["kind"] == "table"]
        out[mode] = {
            "table": {
                "pages": len(table),
                "number_recall": mean(r["number_recall"] for r in table),
                "number_precision": mean(r["number_precision"] for r in table),
            },
            "all": {
                "pages": len(group),
                "number_recall": mean(r["number_recall"] for r in group),
                "number_precision": mean(r["number_precision"] for r in group),
            },
        }
    table = [r for r in rows if r["kind"] == "table" and r["mode"] == "agree"]
    out["flagged"] = {
        "disagree_pages": sum(1 for r in table if r["disagree"]),
        "columns_fail_pages": sum(1 for r in table if r.get("columns_fail")),
        "flagged_pages": sum(1 for r in table if r["disagree"] or r.get("columns_fail")),
        "table_pages": len(table),
        "disagree_share": round(sum(1 for r in table if r["disagree"]) / len(table), 4)
        if table else None,
        "columns_fail_share": round(sum(1 for r in table if r.get("columns_fail"))
                                    / len(table), 4) if table else None,
        "flagged_share": round(sum(1 for r in table
                                  if r["disagree"] or r.get("columns_fail")) / len(table), 4)
        if table else None,
    }
    return out


def columns_add_up(text: str) -> bool | None:
    """Heuristic: does a line labelled total equal the sum of the lines above?

    Only called for table pages.  Returns None when the page shows no total line
    with at least three numeric rows, so a page is never penalised for having no
    arithmetic to check.  Numbers are compared with a 1% tolerance.
    """
    lines = [line for line in text.splitlines() if NUMBER.search(line)]
    checks = 0
    for index, line in enumerate(lines):
        if not re.search(r"\btotal\b", line, re.I):
            continue
        total_numbers = [float(n.replace(",", "")) for n in NUMBER.findall(line)]
        if len(total_numbers) < 2:
            continue
        above = lines[max(0, index - 8):index]
        if len(above) < 3:
            continue
        checks += 1
        for column in range(1, min(4, len(total_numbers))):
            wanted = total_numbers[-column]
            values = []
            for row in above:
                row_numbers = [float(n.replace(",", "")) for n in NUMBER.findall(row)]
                if len(row_numbers) >= column:
                    values.append(row_numbers[-column])
            if len(values) >= 3 and abs(sum(values) - wanted) <= max(1.0, abs(wanted) * 0.01):
                return True
    return False if checks else None


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build")
    b.add_argument("--out", default=r"C:\RE\ocr_test")
    b.add_argument("--base", default=r"C:\RE\raw\pilot60_history")
    b.add_argument("--seed", type=int, default=20261101)
    b.add_argument("--scale", type=float, default=RENDER_SCALE)
    b.add_argument("--force", action="store_true",
                   help="rebuild over an existing frozen pages.json")
    s = sub.add_parser("score")
    s.add_argument("--engine", required=True, help="engine directory with rows*.jsonl")
    s.add_argument("--pages", default=r"C:\RE\ocr_test\pages.json")
    c = sub.add_parser("combine")
    c.add_argument("--a", required=True)
    c.add_argument("--b", required=True)
    c.add_argument("--pages", default=r"C:\RE\ocr_test\pages.json")
    c.add_argument("--out", default=None)
    args = ap.parse_args()

    if args.command == "build":
        manifest_path = Path(args.out) / "pages.json"
        if manifest_path.exists() and not args.force:
            raise SystemExit(f"{manifest_path} is frozen; pass --force to rebuild")
        build(Path(args.out), Path(args.base), args.seed, args.scale)
        return 0
    manifest = load_pages(Path(args.pages))
    if args.command == "score":
        result = score_engine(Path(args.engine), manifest)
        print(json.dumps(result["summary"], indent=2))
        return 0
    rows_a = read_rows(Path(args.a))
    rows_b = read_rows(Path(args.b))
    rows = combine_pair(rows_a, rows_b, manifest)
    summary = combo_summary(rows)
    out = Path(args.out) if args.out else Path(args.a) / f"combo_with_{Path(args.b).name}.json"
    out.write_text(json.dumps({"a": args.a, "b": args.b, "summary": summary}, indent=1),
                   encoding="utf-8")
    print(json.dumps(summary, indent=2))
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
