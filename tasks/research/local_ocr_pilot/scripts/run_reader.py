"""Feed each page's OCR text to the production free text reader (beam-free on OpenCode Go key 2, key 1 fallback) with the
deck fact prompt adapted to text input; parse the same `metric | period | number | unit` schema with the repo parser.

    python run_reader.py --ocr rapidocr_cpu [--workers 6] [--limit N]

Output: work/reader/<arm>.jsonl  (raw answer + parsed facts + seconds)
"""
import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
from reality_engine.scripts.extract_deck_figures import parse_facts  # noqa: E402
from reality_engine.scripts.go_session import session_id  # noqa: E402
from reality_engine.scripts.resource_watchdog import user_env  # noqa: E402

WORK = ROOT / "work"
GO_URL = "https://opencode.ai/zen/go/v1/chat/completions"
MAX_CHARS = 12000
MAX_TOKENS = 12000
CTX = ("You are reading OCR text from one page of an Indian listed company's investor presentation. The OCR text is a "
       "reconstruction of the page image: lines from the same table row are joined with ' | ', columns may be jumbled, "
       "and some digits may be misread. Use the layout and labels to decide which number belongs to which metric, period "
       "and unit.\nCompany: {company} (NSE/BSE symbol {symbol}), an Indian listed company. Document: investor presentation "
       "filed {date}. Indian fiscal year runs April-March (Q1 = Apr-Jun).\n")
PROMPT = ("List every number on this page, one per line, in this exact format:\nmetric | period | number | unit\n"
          "Copy each number EXACTLY as it appears in the OCR text, character for character, including commas, brackets, "
          "decimal points and % (e.g. 28,00,000 or (1.44) or 18.2%). Do not convert or round. Use - for an unknown period "
          "or unit. First line must be: TITLE | <slide title>. If there are no numbers, output only the TITLE line.")
RULES = ("Rules for each line:\n"
         "- metric: the specific label from the page (row/column/axis/legend/caption text, including the segment or "
         "product it belongs to). Never write the word 'metric'.\n"
         "- period: the period the number refers to, as printed in the column/axis header or caption (e.g. Q1FY27, FY26, "
         "9MFY26, Jun-26). Use - only if the page gives no period for it.\n"
         "- unit: the unit printed next to the number or in the table/chart header (e.g. Rs Cr, %, MT, homes, sft). Use - "
         "only if none is printed.\n"
         "- Skip page numbers, footnote markers, phone numbers, addresses and registration numbers.\n"
         "- Only report numbers that appear in the OCR text. If the OCR clearly garbles a digit, skip it instead of guessing.")
lock = threading.Lock()


def prompt_for(p, text):
    return (CTX.format(company=p.get("symbol") or "-", symbol=p.get("symbol") or "-",
                       date=str(p.get("known_at") or "")[:10]) + PROMPT + "\n" + RULES +
            "\n\nOCR text from the page image:\n<<<\n" + text[:MAX_CHARS] + "\n>>>")


def call_go(model, prompt, key, lane):
    r = requests.post(GO_URL, timeout=600, headers={"Authorization": f"Bearer {key}",
                                                   "x-opencode-session": session_id("deck_ocr", model, key, lane)},
                      json={"model": model, "max_tokens": MAX_TOKENS, "temperature": 0,
                            "messages": [{"role": "user", "content": prompt}]})
    if r.status_code != 200:
        raise RuntimeError(f"go HTTP {r.status_code}: {r.text[:160]}")
    j = r.json()
    return j["choices"][0]["message"].get("content") or "", (j.get("usage") or {})


def one(p, key_go, key_alt, lane):
    text = p["text"]
    prompt = prompt_for(p, text)
    errs = []
    for attempt in range(3):
        t0 = time.time()
        try:
            out, usage = call_go("beam-free", prompt, key_go, lane)
            return {**{k: p[k] for k in ("sha256", "page_no", "year", "ptype")}, "model": "beam-free@go2",
                    "seconds": round(time.time() - t0, 2), "raw": out, "facts": parse_facts(out),
                    "in_tok": usage.get("prompt_tokens"), "out_tok": usage.get("completion_tokens"), "error": None}
        except Exception as e:
            errs.append(str(e)[:160])
            time.sleep(5 if "429" not in str(e) else 30)
    if key_alt:   # second Go key, same free model: keeps the reader identical across arms
        try:
            t0 = time.time()
            out, usage = call_go("beam-free", prompt, key_alt, lane)
            return {**{k: p[k] for k in ("sha256", "page_no", "year", "ptype")}, "model": "beam-free@go1",
                    "seconds": round(time.time() - t0, 2), "raw": out, "facts": parse_facts(out),
                    "in_tok": usage.get("prompt_tokens"), "out_tok": usage.get("completion_tokens"), "error": None}
        except Exception as e:
            errs.append(str(e)[:160])
    return {**{k: p[k] for k in ("sha256", "page_no", "year", "ptype")}, "model": None, "seconds": 0.0,
            "raw": "", "facts": [], "in_tok": None, "out_tok": None, "error": " | ".join(errs)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ocr", required=True, help="stem of work/ocr/<stem>.jsonl")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    ocr = [json.loads(line) for line in (WORK / "ocr" / f"{args.ocr}.jsonl").read_text(encoding="utf-8").splitlines()
           if line.strip()]
    pages = {p["sha256"] + "/" + str(p["page_no"]): p for p in json.loads((WORK / "pages.json").read_text(encoding="utf-8"))}
    items = []
    for o in ocr:
        p = pages.get(o["sha256"] + "/" + str(o["page_no"]))
        if p:
            items.append({**p, "text": o["text"]})
    if args.limit:
        items = items[:args.limit]
    env = user_env()
    key_go, key_alt = env.get("OPENCODE_GO_API_KEY_2"), env.get("OPENCODE_GO_API_KEY")
    if not key_go:
        raise SystemExit("OPENCODE_GO_API_KEY_2 missing")
    out_path = WORK / "reader" / f"{args.ocr}.jsonl"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                r = json.loads(line)
                done.add((r["sha256"], r["page_no"]))
    todo = [p for p in items if (p["sha256"], p["page_no"]) not in done]
    print(f"{len(items)} pages, {len(todo)} to read, {args.workers} workers", flush=True)
    t0 = time.time()
    with out_path.open("a", encoding="utf-8") as fh, ThreadPoolExecutor(args.workers) as pool:
        futs = {pool.submit(one, p, key_go, key_alt, i % args.workers): p for i, p in enumerate(todo)}
        for n, fut in enumerate(as_completed(futs), 1):
            rec = fut.result()
            with lock:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                fh.flush()
            if n % 20 == 0:
                print(f"{n}/{len(todo)} {rec['seconds']}s {len(rec['facts'])} facts "
                      f"{round(time.time() - t0, 0)}s elapsed", flush=True)
    print(f"done {len(todo)} in {round(time.time() - t0, 0)}s -> {out_path}", flush=True)


if __name__ == "__main__":
    main()
