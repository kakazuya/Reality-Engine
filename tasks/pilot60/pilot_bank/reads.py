"""DeepSeek reads the passages for each (question, stock) and reports what they state. It decides nothing else.

The verdict counts only if its quote is verbatim in the chunk it cites; the code checks that. Which stock a
question goes to, and whether it stays, is decided by the rules and by Claude. Resumable: reads.jsonl is appended.
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import re
import sqlite3
import sys
import threading
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).parent))
from reality_engine.scripts.go_session import session_id  # noqa: E402
from reality_engine.toolbelt.cost_ledger import record_usage  # noqa: E402
from tasks.arch_v4.reader_test.beam_client import _registry_env  # noqa: E402

URL = "https://opencode.ai/zen/go/v1/chat/completions"
MODEL = "deepseek-v4.1-flash"
JOB = "pilot_bank_reads"
OUT = Path(__file__).parent / "reads.jsonl"
TYPES = {"C": "concall", "D": "deck", "A": "annual_report", "N": "results_notes", "X": "announcement"}
SYSTEM = """You check whether excerpts from one Indian listed company's own documents state the answer to a question.

Reply with JSON only: {"verdict": "YES|PARTIAL|NO", "chunk_id": <id or null>, "quote": "<verbatim words>", "states": "<one line: what the quote states>"}

YES: the excerpts state the fact the question mainly asks for, for this company, as a real company-specific disclosure.
PARTIAL: they state a real company-specific fact for one part of the question, and other parts need more.
NO: they do not. Boilerplate is NO: accounting-policy wording, risk-factor templates, definitions, sensitivity notes, cover letters,
and a word match with a different meaning (for example "going concern" in a history line, "discount rate" for a question on price discounts).
A judgement question ("is it real", "is it sustainable") is PARTIAL if the excerpts give company-specific facts that bear on it.
The quote must be 8 to 40 consecutive words copied exactly from one excerpt. Leave quote empty for NO. Use no outside knowledge."""
LOCK = threading.Lock()
LOCAL = threading.local()


def key() -> str:
    env = _registry_env()
    for name in ("OPENCODE_GO_API_KEY_2", "OPENCODE_GO_API_KEY"):
        if (env.get(name) or "").strip():
            return env[name].strip()
    raise SystemExit("no Go key in environment or registry")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


def window(body: str, words: list, width: int = 1500) -> str:
    text = re.sub(r"\s+", " ", body or "").strip()
    if len(text) <= width:
        return text
    low = text.lower()
    pos = [low.find(w) for w in words if low.find(w) >= 0]
    start = max(0, (min(pos) if pos else 0) - width // 3)
    return text[start:start + width]


def excerpts(isin: str, match: str, types: str, as_of: str) -> list:
    con = getattr(LOCAL, "con", None)
    if con is None:
        con = sqlite3.connect(f"file:{ROOT}/reality_engine/data/pilot/pilot60/chunks_v3_pilot.db?mode=ro", uri=True, timeout=30)
        LOCAL.con = con
    dts = [TYPES[t] for t in types]
    q = (f"SELECT c.chunk_id,c.doc_type,substr(c.event_date,1,10),c.page_from,c.body FROM chunk_fts JOIN chunk c ON c.chunk_id=chunk_fts.rowid "
         f"WHERE chunk_fts MATCH ? AND c.isin=? AND c.doc_type IN ({','.join('?' * len(dts))}) AND substr(c.known_at,1,10)<=? AND c.char_len>=200 "
         f"ORDER BY bm25(chunk_fts,0,1) LIMIT 6")
    return con.execute(q, ["{body}: (" + match + ")", isin] + dts + [as_of]).fetchall()


def ask(api_key: str, company: str, question: str, chunks: list, words: list) -> dict:
    text = "\n\n".join(f"[chunk_id {c[0]} | {c[1]} | {c[2]} | page {c[3]}]\n{window(c[4], words)}" for c in chunks)
    body = {"model": MODEL, "max_tokens": 6000, "reasoning_effort": "max", "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": SYSTEM},
                         {"role": "user", "content": f"Company: {company}\nQuestion: {question}\n\nExcerpts:\n{text}"}]}
    last = None
    for attempt in range(5):
        try:
            r = requests.post(URL, json=body, timeout=400, headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json",
                                                                    "x-opencode-session": session_id(JOB, MODEL, api_key)})
            if r.status_code == 429:
                time.sleep(20 * (attempt + 1))
                continue
            r.raise_for_status()
            data = r.json()
            record_usage(MODEL, data.get("usage") or {}, JOB)
            raw = data["choices"][0]["message"]["content"]
            return json.loads(re.search(r"\{.*\}", raw, re.S)[0])
        except Exception as e:  # noqa: BLE001 - a failed read stays unread and is retried on the next pass
            last = type(e).__name__
            time.sleep(5 * (attempt + 1))
    return {"verdict": "ERROR", "states": last}


def work(job: dict, api_key: str, fh) -> str:
    chunks = excerpts(job["isin"], job["ev"], job["t"], job["as_of"])
    rec = {k: job[k] for k in ("parent_mid", "symbol", "isin", "question", "ev")}
    if not chunks:
        rec.update(verdict="NO", reason="no_chunks")
    else:
        words = [w.lower() for w in re.findall(r"[A-Za-z][A-Za-z-]{3,}", job["ev"]) if w not in ("AND",)]
        ans = ask(api_key, job["company"], job["question"], chunks, words)
        v = str(ans.get("verdict", "ERROR")).upper()
        if v == "ERROR":
            return "ERROR"
        rec.update(verdict=v, states=str(ans.get("states", ""))[:240], quote=str(ans.get("quote", ""))[:400], chunk_id=ans.get("chunk_id"))
        if v in ("YES", "PARTIAL"):
            hit = next((c for c in chunks if norm(rec["quote"]) and norm(rec["quote"]) in norm(c[4])), None)
            if hit is None:
                rec.update(verdict="NO", reason="quote_not_verbatim", model_verdict=v)
            else:
                rec.update(chunk_id=hit[0], doc_type=hit[1], date=hit[2], page=hit[3])
    with LOCK:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
    return rec["verdict"]


def jobs() -> list:
    sys.path.insert(0, str(Path(__file__).parent))
    import engine as E
    done = set()
    if OUT.exists():
        for line in open(OUT, encoding="utf-8"):
            o = json.loads(line)
            done.add((o["parent_mid"], o["symbol"], o["ev"]))
    import build
    import rules_a, rules_b, rules_c, rules_d, rules_e, rules_f  # noqa: F401,E401
    names = {s: n for s, n in E.NAMES.items()}
    out = []
    for line in open(ROOT / "tasks/pilot60/PILOT_BANK_2026-10-31.jsonl", encoding="utf-8"):
        r = json.loads(line)
        rule = build.RULES[r["parent_mid"]]
        if not rule.get("ev") or r["kind"] == "market":
            continue
        for e in r["entities"]:
            if (r["parent_mid"], e["symbol"], rule["ev"]) in done:
                continue
            q = r["question"] if r["kind"] == "stock" else f"{r['question']} (Answer for {names[e['symbol']]} only.)"
            out.append({"parent_mid": r["parent_mid"], "symbol": e["symbol"], "isin": e["isin"], "company": names[e["symbol"]], "question": q,
                        "ev": rule["ev"], "t": rule["t"], "as_of": r["as_of"]})
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--only", default="", help="comma list of parent ids; read just these")
    a = ap.parse_args()
    todo = jobs()
    if a.only:
        todo = [j for j in todo if j["parent_mid"] in a.only.split(",")]
    if a.limit:
        todo = todo[:a.limit]
    print(f"to read: {len(todo)}", flush=True)
    api_key = key()
    counts: dict = {}
    t0 = time.time()
    with open(OUT, "a", encoding="utf-8", newline="\n") as fh, cf.ThreadPoolExecutor(a.workers) as ex:
        for i, f in enumerate(cf.as_completed([ex.submit(work, j, api_key, fh) for j in todo]), 1):
            v = f.result()
            counts[v] = counts.get(v, 0) + 1
            if i % 50 == 0 or i == len(todo):
                print(f"{i}/{len(todo)} {counts} {time.time() - t0:.0f}s", flush=True)
    print("DONE", counts, flush=True)


if __name__ == "__main__":
    main()
