"""Can we query the DeepSeek concall facts? (2026-10-18 pilot of 118 transcripts, Shivam: test before the full run.)

Questions: data/cc_query_test/questions.json (50 analyst questions on 25 pilot transcripts, written by a helper from the
transcripts alone, with the management answer quoted verbatim). For each question, search only that company's material
known at the call's filing time (filed_at <= as_of) and check the top 5:
  A  facts, keyword (SQLite FTS5 BM25 over list/metric/value/period/statement/quote)
  B  facts, EmbeddingGemma vectors
  C  raw transcript chunks (~2,400 chars, the production chunk size), EmbeddingGemma  <- what the search layer does
A fact answers when its quote/statement shares >= 40% of the answer quote's words, or (number questions) carries the
answer number; a chunk answers when it contains the answer quote. 'captured' = any fact of the doc answers (top-k
independent): did DeepSeek extract it at all?
Also: PIT leak test (as_of one second before filing -> no fact of that call), PEAD join (posts vs calls by ISIN/time).

    python -m reality_engine.scripts.concall_query_test
"""
import datetime as dt
import json
import re
import sqlite3
from pathlib import Path

import numpy as np

from reality_engine.scripts.embed_model_test import Model

ROOT = Path(__file__).resolve().parents[2]
T = ROOT / "reality_engine/data/cc_query_test"
FACTS = ROOT / "reality_engine/data/concall_facts.db"
MAIN = ROOT / "reality_engine/data/equity_intelligence.db"
W = re.compile(r"[a-z0-9]+(?:\.[0-9]+)?")


def words(s):
    return set(W.findall((s or "").lower()))


def norm(s):
    return " ".join(W.findall((s or "").lower()))


def digits(s):
    return {x.replace(",", "") for x in re.findall(r"\d[\d,]*\.?\d*", s or "")}


def fact_text(r):
    return " | ".join(str(x) for x in (r["list_name"], r["metric"], r["value"], r["unit"], r["period"], r["statement"], r["quote"]) if x)


def answers(fact, q):
    aw = words(q["answer_quote"])
    fw = words((fact["quote"] or "") + " " + (fact["statement"] or ""))
    if aw and len(aw & fw) / len(aw) >= 0.4:
        return True
    if q["answer_number"]:
        need = digits(q["answer_number"])
        have = digits(" ".join(str(fact[k] or "") for k in ("value", "quote", "statement")))
        return bool(need) and need <= have
    return False


def chunks_of(text, size=2400):
    out, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(cur) + len(para) > size and cur:
            out.append(cur); cur = ""
        cur += para + "\n\n"
    if cur.strip():
        out.append(cur)
    return out


def main():
    qs = json.load(open(T / "questions.json", encoding="utf-8"))
    docs = {d["doc_id"]: d for d in json.load(open(T / "docs.json", encoding="utf-8"))}
    db = sqlite3.connect(f"file:{FACTS}?mode=ro", uri=True); db.row_factory = sqlite3.Row
    m = Model("embeddinggemma")
    res = {"A_fts": [], "B_vec": [], "C_chunks": [], "captured": []}
    per_q = []
    for q in qs:
        d = docs[q["doc_id"]]; as_of = d["filed_at"]
        facts = db.execute("SELECT * FROM cc_items WHERE isin=? AND filed_at<=?", (d["isin"], as_of)).fetchall()
        ok = [answers(f, q) for f in facts]
        res["captured"].append(any(ok))
        # A: FTS5 BM25 in memory over this company's PIT facts
        mem = sqlite3.connect(":memory:")
        mem.execute("CREATE VIRTUAL TABLE f USING fts5(t)")
        mem.executemany("INSERT INTO f(rowid, t) VALUES (?,?)", [(i, fact_text(f)) for i, f in enumerate(facts)])
        terms = " OR ".join(sorted(words(q["question"]) - {d["symbol"].lower()} - {"the", "what", "is", "for", "of", "in", "and", "to", "a", "on", "does", "did", "how"}))
        top = [r[0] for r in mem.execute("SELECT rowid FROM f WHERE f MATCH ? ORDER BY bm25(f) LIMIT 5", (terms,))] if terms else []
        res["A_fts"].append(any(ok[i] for i in top))
        # B: embeddings over facts
        if facts:
            E = m.embed([fact_text(f) for f in facts]); qv = m.embed([q["question"]], query=True)[0]
            topb = list(np.argsort(-(E @ qv))[:5])
            res["B_vec"].append(any(ok[i] for i in topb))
        else:
            res["B_vec"].append(False)
        # C: raw chunks of the same transcript
        text = (T / d["file"]).read_text(encoding="utf-8")
        ch = chunks_of(text)
        Ec = m.embed(ch); qv = m.embed([q["question"]], query=True)[0]
        topc = list(np.argsort(-(Ec @ qv))[:5])
        na = norm(q["answer_quote"])
        res["C_chunks"].append(any(na in norm(ch[i]) for i in topc))
        per_q.append({"q": q["question"], "kind": q["kind"], **{k: v[-1] for k, v in res.items()}})
    n = len(qs)
    print(f"questions: {n}")
    for k, v in res.items():
        num = [x for x, q in zip(v, qs) if q["kind"] == "number"]; qual = [x for x, q in zip(v, qs) if q["kind"] != "number"]
        print(f"  {k:9} {sum(v)}/{n} = {sum(v)/n:.0%}   number {sum(num)}/{len(num)}   qualitative {sum(qual)}/{len(qual)}")
    json.dump(per_q, open(T / "results.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    missed = [p["q"] for p in per_q if not p["captured"]]
    print("not captured by DeepSeek at all:", len(missed)); [print("   -", x) for x in missed[:12]]

    # PIT leak test: one second before each call's filing, none of its facts may be visible
    leaks = 0
    for d in docs.values():
        t = dt.datetime.fromisoformat(d["filed_at"]) - dt.timedelta(seconds=1)
        leaks += db.execute("SELECT COUNT(*) FROM cc_items WHERE doc_id=? AND filed_at<=?", (d["doc_id"], t.isoformat())).fetchone()[0]
    print(f"PIT leak test: facts visible before their call was public = {leaks}")

    # PEAD join: posts (UTC) vs calls (BSE time, IST) for the same ISIN
    main = sqlite3.connect(f"file:{MAIN}?mode=ro", uri=True)
    posts = main.execute("SELECT isin, post_ts_utc FROM tg_pead_signals WHERE is_test_post=0 AND isin IS NOT NULL").fetchall()
    calls = db.execute("SELECT isin, filed_at FROM cc_docs WHERE status='ok'").fetchall()
    by = {}
    for i, f in calls:
        by.setdefault(i, []).append(dt.datetime.fromisoformat(f[:19]) - dt.timedelta(hours=5, minutes=30))  # IST -> UTC
    joined = before = after = 0
    for i, p in posts:
        if i not in by:
            continue
        pt = dt.datetime.fromisoformat(p[:19]); joined += 1
        before += any(c <= pt for c in by[i]); after += any(c > pt for c in by[i])
    print(f"PEAD join: posts with a pilot call for the same ISIN {joined}; with a call already public at post time "
          f"{before}; with a call after the post {after}")


if __name__ == "__main__":
    main()
