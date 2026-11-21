"""T-234: free-model reader bake-off against hy4-flash-free (quality, precision, accuracy, speed, tokens).

Every candidate reads the same pages through the T-230 observation pipeline (``v2.observations``
with ``--reader`` / ``--text-only``), so the script checks -- not the model -- decide each row's status.
The stored hy4 runs (``obs_91_i.db``, ``obs_decks394.db``, ``obs_ar_91.db``) are the baseline and are only
ever read.

Subcommands::

    python -m reality_engine.scripts.reader_bakeoff pages --out-dir .tmp/t234
    python -m reality_engine.scripts.reader_bakeoff run --model nvidia/nemotron-3.5-super-vl:free \
        --pages .tmp/t234/golden_pages.json --out-dir .tmp/t234
    python -m reality_engine.scripts.reader_bakeoff score --model nvidia/nemotron-3.5-super-vl:free \
        --out-dir .tmp/t234
    python -m reality_engine.scripts.reader_bakeoff report --out-dir .tmp/t234

``run`` writes ``obs_<slug>.db`` + ``stats_<slug>.json``; ``score`` writes ``score_<slug>.json``,
``golden_values_<slug>.jsonl`` and ``disagree_<slug>.jsonl``; ``report`` writes ``bakeoff.csv`` and
``bakeoff.md``.  Nothing here grades a disagreement: Wolf hand-reads the JSONL.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import re
import sqlite3
import statistics
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from reality_engine.db.readonly import connect_ro
from reality_engine.scripts import regress
from reality_engine.v2 import observations as obs

GOLDEN = Path(__file__).resolve().parents[1] / "tests" / "golden" / "observations.jsonl"
DEFAULT_ROOTS = ("D:/RealityEngine/tg_build/measure10", "D:/RealityEngine/tg_build/decks403")
DEFAULT_HY4 = ("D:/RealityEngine/t230/obs_91_i.db",
               "C:/Users/warri/Downloads/Info_Diffusion_Model/.tmp/t232read/obs_decks394.db",
               "C:/Users/warri/Downloads/Info_Diffusion_Model/.tmp/t230ar/obs_ar_91.db")
AR_DB = "C:/Users/warri/Downloads/Info_Diffusion_Model/.tmp/t230ar/obs_ar_91.db"
IMAGE_MODELS = ("google/gemma-4-31b-it", "nvidia/nemotron-3.5-super-vl:free",
                "inclusionai/ling-3.2-flash:free", "particle-ai/particle-1:free")
TEXT_MODELS = ("baidu/ernie-5.5-flash-preview:free", "nvidia/nemotron-3-ultra-550b-a55b:free")
TEXT_PAGES = 60
TEXT_MIN_CHARS = 400                   # a "good text layer" page for the text-only set
TEXT_MIN_ROWS = 3                      # hy4 stored at least this many rows on the page
DISAGREE_SAMPLE = 40


def slug(model: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "_", model).strip("_")


# --------------------------------------------------------------------------- store / page maps
def store_map(roots: Iterable[str], out_dir: Path) -> dict[str, str]:
    """doc_key -> main store .db, scanned once and cached (the golden keys are raw PDF paths)."""
    cache = out_dir / "doc_stores.json"
    if cache.is_file():
        loaded = json.loads(cache.read_text(encoding="utf-8"))
        return {str(k): str(v) for k, v in loaded.items()}
    mapping: dict[str, str] = {}
    for root in roots:
        for db in sorted(Path(root).glob("*/*.db")):
            if db.name.endswith("_ocr.db") or db.name == "pages.db":
                continue
            try:
                con = connect_ro(db, timeout_s=30)
                try:
                    cur = con.execute("SELECT doc_key FROM doc")
                    rows = (cur.fetchall() if cur is not None else None) or []
                finally:
                    con.close()
            except Exception:
                continue
            for (doc_key,) in rows:
                if doc_key:
                    mapping.setdefault(str(doc_key), str(db))
    out_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(mapping, indent=0), encoding="utf-8")
    return mapping


def _resolve(doc_key: str, mapping: Mapping[str, str]) -> str:
    """The store holding a golden doc_key: exact, then path-suffix (some Wolf reads print a short path)."""
    if doc_key in mapping:
        return mapping[doc_key]
    key = doc_key.replace("\\", "/").lower()
    for stored, store in mapping.items():
        if stored.replace("\\", "/").lower().endswith(key):
            return store
    return ""


def golden_pages(golden: Path, mapping: Mapping[str, str]) -> tuple[list[dict[str, Any]], list[str]]:
    """The golden deck/AR pages as {symbol, doc_key, page, store}; unresolved keys are reported."""
    pairs: dict[tuple[str, int], dict[str, Any]] = {}
    unresolved: list[str] = []
    for line in golden.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        entry = json.loads(line)
        key = entry.get("key") or {}
        doc_key = str(key.get("doc_key") or "")
        page = int(key.get("page") or 0)
        if not doc_key or not page:
            continue
        store = _resolve(doc_key, mapping)
        if not store:
            if doc_key not in unresolved:
                unresolved.append(doc_key)
            continue
        pairs.setdefault((doc_key, page), {"symbol": str(key.get("symbol") or ""), "doc_key": doc_key,
                                           "page": page, "store": store})
    return list(pairs.values()), unresolved


def text_pages(ar_db: str, mapping: Mapping[str, str], out_dir: Path, seed: int = 234) -> list[dict[str, Any]]:
    """60 annual-report pages where hy4 stored >=3 rows and the text layer is good; the list is saved."""
    saved = out_dir / "text_pages.json"
    if saved.is_file():
        return list(json.loads(saved.read_text(encoding="utf-8")))
    con = connect_ro(ar_db, timeout_s=60)
    try:
        cur = con.execute("SELECT doc_key, page FROM observation GROUP BY doc_key, page HAVING COUNT(*) >= ?",
                          (TEXT_MIN_ROWS,))
        rows = (cur.fetchall() if cur is not None else None) or []
        counts = Counter((str(doc), int(page)) for doc, page in rows)
    finally:
        con.close()
    candidates: list[dict[str, Any]] = []
    for (doc_key, page), hy4_rows in sorted(counts.items()):
        store = _resolve(doc_key, mapping)
        if not store:
            continue
        text = obs.page_text_of(store, doc_key, page)
        if len(obs.norm_space(text)) < TEXT_MIN_CHARS:
            continue
        candidates.append({"symbol": "", "doc_key": doc_key, "page": page, "store": store,
                           "hy4_rows": hy4_rows, "chars": len(obs.norm_space(text))})
    picked = random.Random(seed).sample(candidates, min(TEXT_PAGES, len(candidates)))
    picked.sort(key=lambda p: (p["doc_key"], p["page"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    saved.write_text(json.dumps(picked, indent=1), encoding="utf-8")
    return picked


# --------------------------------------------------------------------------- run
class PageSet:
    """An exact (doc_key, page) selection: T-233's Selector matches documents and pages independently."""

    def __init__(self, pages: Sequence[Mapping[str, Any]]) -> None:
        self.pairs = {(str(p["doc_key"]), int(p["page"])) for p in pages}

    def store(self, store: str | Path | None) -> bool:
        return True

    def page(self, store: str | Path | None, doc_key: str | None, page: int | None) -> bool:
        return (str(doc_key or ""), int(page or 0)) in self.pairs


def run_model(model: str, pages: Sequence[Mapping[str, Any]], out_dir: Path, workers: int = 8,
              text_only: bool = False, resume: bool = False) -> dict[str, Any]:
    """Read exactly ``pages`` with one reader into ``obs_<slug>.db``; returns the run stats."""
    obs.set_reader(model)
    setattr(obs, "ocr_page_text", lambda *a, **k: "")   # ponytail: measure the reader alone; Dots OCR is a second model
    stores = sorted({str(p["store"]) for p in pages})
    out = out_dir / f"obs_{slug(model)}.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    if not resume:
        for suffix in ("", "-wal", "-shm"):
            Path(str(out) + suffix).unlink(missing_ok=True)
    stats = obs.run(stores, 0, workers, out, doc_types=("deck", "annual_report"), seed=234,
                    propose_limit=0, only=PageSet(pages), text_only=text_only, resume=resume)
    stats["model"] = model
    stats["text_only"] = text_only
    (out_dir / f"stats_{slug(model)}.json").write_text(json.dumps(stats, indent=1, default=str), encoding="utf-8")
    return stats


# --------------------------------------------------------------------------- scoring
def within(value: Any, other: Any, pct: float = 0.5) -> bool:
    """Both values within ``pct`` of each other (the bake-off's 'same number' rule)."""
    try:
        a, b = float(value), float(other)
    except (TypeError, ValueError):
        return False
    return abs(a - b) <= max(1e-9, abs(b) * pct / 100.0)


def _rows(db: str | Path) -> list[dict[str, Any]]:
    con = connect_ro(db, timeout_s=60)
    try:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM observation")
        return [dict(row) for row in ((cur.fetchall() if cur is not None else None) or [])]
    finally:
        con.close()


def match_rows(model_rows: Sequence[Mapping[str, Any]],
               hy4_rows: Sequence[Mapping[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """Greedy 1:1 match on (measure, period, value within 0.5%); returns the count and the disagreements."""
    remaining = list(hy4_rows)
    matched = 0
    disagree: list[dict[str, Any]] = []
    for row in model_rows:
        hit = None
        for number, other in enumerate(remaining):
            if (row.get("measure") == other.get("measure") and row.get("period") == other.get("period")
                    and within(row.get("value"), other.get("value"))):
                hit = number
                break
        if hit is not None:
            matched += 1
            del remaining[hit]
            continue
        same_key = next((other for other in remaining
                         if row.get("measure") == other.get("measure") and row.get("period") == other.get("period")),
                        None)
        disagree.append({"kind": "mismatch" if same_key else "model_only", "row": row, "hy4": same_key})
    return matched, disagree


def _text_match(rows: Sequence[Mapping[str, Any]], stores: Mapping[str, str]) -> tuple[int, int]:
    """Rows whose value_text occurs in the page text layer: (matched, rows)."""
    cache: dict[tuple[str, int], str] = {}
    matched = 0
    for row in rows:
        doc_key, page = str(row.get("doc_key") or ""), int(row.get("page") or 0)
        key = (doc_key, page)
        if key not in cache:
            store = stores.get(doc_key, "")
            cache[key] = obs.norm_space(obs.page_text_of(store, doc_key, page)) if store else ""
        if cache[key] and obs.text_has(cache[key], obs.norm_space(str(row.get("value_text") or ""))):
            matched += 1
    return matched, len(rows)


def _entry_page(entry: Mapping[str, Any]) -> tuple[str, int] | None:
    """The (doc_key, page) a golden line grades."""
    for part in ("key", "identity"):
        key = entry.get(part) or {}
        if key.get("doc_key") and key.get("page"):
            return str(key["doc_key"]), int(key["page"])
    return None


def score_model(model: str, pages: Sequence[Mapping[str, Any]], out_dir: Path,
                hy4_dbs: Sequence[str], golden: bool) -> dict[str, Any]:
    """One model's score: golden verdicts, hy4 agreement, status mix, text-layer precision, disagreements."""
    db = out_dir / f"obs_{slug(model)}.db"
    stats_path = out_dir / f"stats_{slug(model)}.json"
    stats = json.loads(stats_path.read_text(encoding="utf-8")) if stats_path.is_file() else {}
    report: dict[str, Any] = {"model": model, "db": str(db), "text_only": bool(stats.get("text_only")),
                              "pages": 0, "rows": 0}
    if not db.is_file():
        report["error"] = "no output DB (the run did not finish)"
        return report
    model_rows = _rows(db)
    report["rows"] = len(model_rows)
    present = {(str(row.get("doc_key") or ""), int(row.get("page") or 0)) for row in model_rows}
    pages = [p for p in pages if (str(p["doc_key"]), int(p["page"])) in present]
    report["pages"] = len(pages)
    if not pages:
        report["error"] = "the output DB holds none of the requested pages"
        return report
    # status mix
    status = Counter(str(row.get("status") or "") for row in model_rows)
    report["status"] = dict(status)
    report["verified_per_page"] = round(status.get("verified", 0) / max(1, len(pages)), 2)
    # precision proxy: the value is printed in the page text layer
    stores = {str(p["doc_key"]): str(p["store"]) for p in pages}
    text_ok, text_total = _text_match(model_rows, stores)
    report["text_match"] = [text_ok, text_total]
    # golden
    if golden:
        entries = [e for e in regress._load_golden("observations")
                   if _entry_page(e) is None or _entry_page(e) in present]
        pipeline = regress.PIPELINES["observations"]
        con = connect_ro(db, timeout_s=60)
        try:
            grade = [regress.grade_entry(con, pipeline, entry) for entry in entries]
            counts = Counter(str(v["verdict"]) for v in grade)
            values_path = out_dir / f"golden_values_{slug(model)}.jsonl"
            with values_path.open("w", encoding="utf-8") as fh:
                for entry in entries:
                    if entry.get("kind") == "page":
                        continue
                    found, how = regress.find_rows(con, pipeline, entry)
                    row = regress._pick(found, entry.get("expect") or {}, entry.get("wrong") or {}) if found else {}
                    fh.write(json.dumps({"source": entry.get("source", ""), "grade": entry.get("grade", ""),
                                         "key": entry.get("key"), "expect": entry.get("expect"),
                                         "model": {k: row.get(k) for k in ("measure", "period", "value_text", "status")}
                                         if row else None, "matched": how}, default=str) + "\n")
        finally:
            con.close()
        report["golden"] = {"counts": dict(counts), "lines": len(entries),
                            "right_total": sum(1 for e in entries if e.get("grade") == "RIGHT"),
                            "wrong_total": sum(1 for e in entries if e.get("grade") in ("WRONG", "MINOR"))}
    # hy4 agreement on the same pages
    pairs = {(str(p["doc_key"]), int(p["page"])) for p in pages}
    hy4_rows: list[dict[str, Any]] = []
    for path in hy4_dbs:
        if not Path(path).is_file():
            continue
        hy4_rows.extend(row for row in _rows(path)
                        if (str(row.get("doc_key") or ""), int(row.get("page") or 0)) in pairs)
    matched, disagree = match_rows(model_rows, hy4_rows)
    report["hy4"] = {"matched": matched, "model_rows": len(model_rows), "hy4_rows": len(hy4_rows),
                     "model_only": len(model_rows) - matched, "hy4_only": len(hy4_rows) - matched}
    disagree.sort(key=lambda item: (str(item["row"].get("doc_key")), int(item["row"].get("page") or 0),
                                    str(item["row"].get("measure")), str(item["row"].get("value_text"))))
    sample = random.Random(234).sample(disagree, min(DISAGREE_SAMPLE, len(disagree)))
    with (out_dir / f"disagree_{slug(model)}.jsonl").open("w", encoding="utf-8") as fh:
        for item in sample:
            row, other = item["row"], item["hy4"]
            fh.write(json.dumps({
                "model": model, "kind": item["kind"], "symbol": row.get("symbol"),
                "doc_key": row.get("doc_key"), "page": row.get("page"), "page_path": row.get("doc_key"),
                "measure": row.get("measure"), "period": row.get("period"), "value_text": row.get("value_text"),
                "status": row.get("status"), "hy4_value_text": (other or {}).get("value_text"),
                "hy4_measure": (other or {}).get("measure"), "hy4_period": (other or {}).get("period"),
            }, default=str) + "\n")
    report["disagree_sample"] = len(sample)
    # speed / tokens from the run stats
    latencies = [float(x) for x in stats.get("latencies") or []]
    report["speed"] = {
        "pages_read": int(stats.get("read") or 0), "errors": int(stats.get("errors") or 0),
        "http_429": int(stats.get("http_429") or 0), "seconds": float(stats.get("seconds") or 0.0),
        "pages_per_min": round((int(stats.get("read") or 0) + int(stats.get("errors") or 0))
                               / max(1e-9, float(stats.get("seconds") or 0.0)) * 60, 1),
        "median_s": round(statistics.median(latencies), 2) if latencies else None,
        "p90_s": round(sorted(latencies)[int(round(0.9 * (len(latencies) - 1)))], 2) if latencies else None,
        "calls": len(latencies),
        "in_tok": int(stats.get("in_tok") or 0), "out_tok": int(stats.get("out_tok") or 0),
    }
    calls = max(1, len(latencies))
    report["speed"]["in_tok_per_page"] = round(report["speed"]["in_tok"] / calls, 1)
    report["speed"]["out_tok_per_page"] = round(report["speed"]["out_tok"] / calls, 1)
    (out_dir / f"score_{slug(model)}.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    return report


# --------------------------------------------------------------------------- report
def _pct(part: int, whole: int) -> str:
    return f"{part}/{whole} ({100 * part / whole:.0f}%)" if whole else "0/0"


def report(out_dir: Path) -> list[dict[str, Any]]:
    scores = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(out_dir.glob("score_*.json"))]
    scores.sort(key=lambda s: (s.get("text_only", False), s["model"]))
    columns = ["model", "kind", "pages", "rows", "golden_right", "golden_accuracy", "wrong_fixed",
               "wrong_reproduced", "hy4_matched", "model_only", "hy4_only", "verified", "unverified",
               "quarantined", "verified_per_page", "text_match", "pages_per_min", "median_s", "p90_s",
               "errors", "http_429", "in_tok", "out_tok", "in_tok_page", "out_tok_page"]
    with (out_dir / "bakeoff.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns)
        writer.writeheader()
        for score in scores:
            if score.get("error"):
                writer.writerow({"model": score["model"], "kind": "text" if score.get("text_only") else "image",
                                 "pages": 0, "rows": 0})
                continue
            golden = score.get("golden") or {}
            counts = golden.get("counts") or {}
            hy4 = score.get("hy4") or {}
            status = score.get("status") or {}
            speed = score.get("speed") or {}
            text_match = score.get("text_match") or [0, 0]
            right_total = int(golden.get("right_total") or 0)
            writer.writerow({
                "model": score["model"], "kind": "text" if score.get("text_only") else "image",
                "pages": score.get("pages", 0), "rows": score.get("rows", 0),
                "golden_right": _pct(counts.get("still_right", 0), right_total),
                "golden_accuracy": _pct(counts.get("still_right", 0) + counts.get("fixed", 0),
                                        int(golden.get("lines") or 0)),
                "wrong_fixed": _pct(counts.get("fixed", 0), int(golden.get("wrong_total") or 0)),
                "wrong_reproduced": _pct(counts.get("still_wrong", 0), int(golden.get("wrong_total") or 0)),
                "hy4_matched": _pct(hy4.get("matched", 0), score.get("rows", 0)),
                "model_only": hy4.get("model_only", 0), "hy4_only": hy4.get("hy4_only", 0),
                "verified": status.get("verified", 0), "unverified": status.get("unverified", 0),
                "quarantined": status.get("quarantined", 0),
                "verified_per_page": score.get("verified_per_page", 0),
                "text_match": _pct(text_match[0], text_match[1]),
                "pages_per_min": speed.get("pages_per_min", 0), "median_s": speed.get("median_s"),
                "p90_s": speed.get("p90_s"), "errors": speed.get("errors", 0),
                "http_429": speed.get("http_429", 0), "in_tok": speed.get("in_tok", 0),
                "out_tok": speed.get("out_tok", 0), "in_tok_page": speed.get("in_tok_per_page", 0),
                "out_tok_page": speed.get("out_tok_per_page", 0),
            })
    lines = ["# T-234 free-model reader bake-off (22 Nov 2026)",
             "Image set: the 228 golden pages (Nemotron VL's partial run at 16 workers reads 120); text set: 60 "
             "annual-report pages (hy4 >=3 rows, good text layer) - not read, all Kilo text models were quota-blocked. "
             "Hy4 rows are read, never re-run.",
             "",
             "| model | kind | pages/rows | golden RIGHT | accuracy | WRONG fixed / reproduced | "
             "vs hy4 matched / model-only / hy4-only | status ver/unv/quar | ver/page | text match | "
             "pages/min | median/p90 s | 429 | tok in/out per page |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for score in scores:
        if score.get("error"):
            lines.append(f"| {score['model']} | {'text' if score.get('text_only') else 'image'} | "
                         f"unavailable: {score['error'][:120]} | - | - | - | - | - | - | - | - | - | - | - |")
            continue
        golden = score.get("golden") or {}
        counts = golden.get("counts") or {}
        hy4 = score.get("hy4") or {}
        status = score.get("status") or {}
        speed = score.get("speed") or {}
        text_match = score.get("text_match") or [0, 0]
        right_total = int(golden.get("right_total") or 0)
        wrong_total = int(golden.get("wrong_total") or 0)
        graded = golden.get("lines") or 0
        if golden:
            golden_right = _pct(counts.get("still_right", 0), right_total)
            accuracy = _pct(counts.get("still_right", 0) + counts.get("fixed", 0), int(graded))
            wrong = f"{_pct(counts.get('fixed', 0), wrong_total)} / {_pct(counts.get('still_wrong', 0), wrong_total)}"
        else:
            golden_right = accuracy = wrong = "not run"
        lines.append(
            f"| {score['model']} | {'text' if score.get('text_only') else 'image'} "
            f"| {score.get('pages', 0)}/{score.get('rows', 0)} "
            f"| {golden_right} | {accuracy} | {wrong} "
            f"| {_pct(hy4.get('matched', 0), score.get('rows', 0))} / {hy4.get('model_only', 0)} "
            f"/ {hy4.get('hy4_only', 0)} "
            f"| {status.get('verified', 0)}/{status.get('unverified', 0)}/{status.get('quarantined', 0)} "
            f"| {score.get('verified_per_page', 0)} | {_pct(text_match[0], text_match[1])} "
            f"| {speed.get('pages_per_min', 0)} | {speed.get('median_s')}/{speed.get('p90_s')} "
            f"| {speed.get('http_429', 0)} | {speed.get('in_tok_per_page', 0)}/{speed.get('out_tok_per_page', 0)} |")
    lines += ["",
              "Run notes: Gemma 4 31B completes 1 page of the 12-page set (its compat route cannot switch thinking off: "
              "240-300 s/page, 1 of 2 probe pages hit the 300 s client timeout); its speed row is that 2-page probe. "
              "Nemotron VL read 120 of 228 golden pages before the Kilo free quota answered 429 on every model "
              "(195 429s, 108 calls failed after 6 retries); its speed row covers that 120-page partial run.",
              "Golden RIGHT = the hand-graded correct rows still matching every graded field; accuracy adds the WRONG/MINOR "
              "rows the model now gets right. Text-layer match = the model's value_text is printed on the page. "
              "Speed/tokens come from the run's own `usage`; empty/non-JSON replies count as errors.",
              "Disagreement samples: `disagree_<model>.jsonl` (40 seeded rows, model-only + mismatched vs hy4) are for "
              "Wolf's hand-read, not graded here."]
    (out_dir / "bakeoff.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return scores


# --------------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T-234 free-model reader bake-off")
    sub = parser.add_subparsers(dest="command", required=True)
    pages_cmd = sub.add_parser("pages", help="write golden_pages.json and text_pages.json")
    pages_cmd.add_argument("--out-dir", default=".tmp/t234")
    pages_cmd.add_argument("--roots", default=",".join(DEFAULT_ROOTS))
    pages_cmd.add_argument("--golden", default=str(GOLDEN))
    pages_cmd.add_argument("--ar-db", default=AR_DB)
    run_cmd = sub.add_parser("run", help="read one page set with one reader")
    run_cmd.add_argument("--model", required=True)
    run_cmd.add_argument("--pages", required=True)
    run_cmd.add_argument("--out-dir", default=".tmp/t234")
    run_cmd.add_argument("--workers", type=int, default=8)
    run_cmd.add_argument("--text-only", action="store_true")
    run_cmd.add_argument("--resume", action="store_true", help="keep the output DB and skip pages already written")
    score_cmd = sub.add_parser("score", help="score one finished run")
    score_cmd.add_argument("--model", required=True)
    score_cmd.add_argument("--pages", required=True)
    score_cmd.add_argument("--out-dir", default=".tmp/t234")
    score_cmd.add_argument("--hy4", default=",".join(DEFAULT_HY4))
    score_cmd.add_argument("--golden", action="store_true", help="the run used the golden pages")
    report_cmd = sub.add_parser("report", help="write bakeoff.csv and bakeoff.md")
    report_cmd.add_argument("--out-dir", default=".tmp/t234")
    args = parser.parse_args(argv)
    out_dir = Path(args.out_dir)
    if args.command == "pages":
        mapping = store_map([r for r in str(args.roots).split(",") if r], out_dir)
        golden, unresolved = golden_pages(Path(args.golden), mapping)
        (out_dir / "golden_pages.json").write_text(json.dumps(golden, indent=1), encoding="utf-8")
        text = text_pages(args.ar_db, mapping, out_dir)
        print(json.dumps({"golden_pages": len(golden), "unresolved_docs": unresolved,
                          "text_pages": len(text)}))
        return 0
    if args.command == "run":
        pages = json.loads(Path(args.pages).read_text(encoding="utf-8"))
        stats = run_model(args.model, pages, out_dir, args.workers, args.text_only, args.resume)
        print(json.dumps({k: stats.get(k) for k in ("pages", "read", "errors", "http_429", "observations",
                                                    "seconds", "in_tok", "out_tok")}))
        return 0
    if args.command == "score":
        pages = json.loads(Path(args.pages).read_text(encoding="utf-8"))
        score = score_model(args.model, pages, out_dir, [p for p in str(args.hy4).split(",") if p], args.golden)
        print(json.dumps({k: score.get(k) for k in ("model", "rows", "status", "golden", "hy4", "text_match",
                                                     "speed")}, default=str))
        return 0
    report(out_dir)
    print((out_dir / "bakeoff.md").read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
