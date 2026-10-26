"""Facts arm rebuilt by the manager: headers on every unit; concall facts mapped via corporate_documents.id
(concall_facts.cc_docs.doc_id) <-> raw_documents.doc_id by sha256; each concall item located to the v2 chunk
whose words overlap its quote most (reader quotes are paraphrased, so exact location is impossible)."""
import json, re, sqlite3, sys
from pathlib import Path
from reality_engine.db.readonly import connect_ro
from reality_engine.toolbelt._common import resolve_db
W = Path(sys.argv[1]); C = sqlite3.connect(f"file:{W/'.tmp/c2w/c2w.db'}?mode=ro", uri=True)
docs = {d: (s, p) for d, s, p in C.execute("select doc_id, symbol, published_date from docs")}
hdr = lambda d, kind: f"{docs[d][0]} · {kind} · {docs[d][1]}"
out = open(W / ".tmp/c2w/dense_input/facts_fixed.jsonl", "w", encoding="utf-8")
n = {"deck": 0, "concall": 0, "concall_located": 0}
for cid, d, body, s0, s1 in C.execute("select chunk_id, doc_id, body, norm_start, norm_end from chunks_facts where doc_type='deck'"):
    out.write(json.dumps({"chunk_id": f"f{cid}", "doc_id": d, "doc_type": "deck", "norm_start": s0, "norm_end": s1,
                          "text": hdr(d, "Investor presentation") + "\n" + body}) + "\n"); n["deck"] += 1
mp = {int(k): v for k, v in json.load(open(W / ".tmp/c2w/concall_corp_map.json")).items()}
inv = {v: k for k, v in mp.items()}
f = connect_ro(resolve_db("concall_facts.db"))
words = lambda t: set(re.findall(r"[a-z0-9]{3,}", (t or "").lower()))
v2 = {}
for d, s0, s1, b in C.execute("select doc_id, norm_start, norm_end, body from chunks_v2 where doc_type='concall'"):
    v2.setdefault(d, []).append((s0, s1, words(b)))
ids = ",".join(map(str, inv))
for cd, ln, idx, metric, val, unit, per, stmt, quote in f.execute(
        f"select doc_id, list_name, idx, metric, value, unit, period, statement, quote from cc_items where doc_id in ({ids})"):
    d = inv[cd]; q = words(quote) or words(stmt); best = (-1, -1, 0)
    for s0, s1, w in v2.get(d, []):
        ov = len(q & w) / max(1, len(q))
        if ov > best[2]: best = (s0, s1, ov)
    s0, s1 = (best[0], best[1]) if best[2] >= 0.5 else (-1, -1)
    n["concall"] += 1; n["concall_located"] += s0 >= 0
    body = " | ".join(str(x) for x in (metric, val, unit, per) if x not in (None, "")) + "\n" + (stmt or "") + ("\n" + quote if quote else "")
    out.write(json.dumps({"chunk_id": f"c{cd}-{ln}-{idx}", "doc_id": d, "doc_type": "concall", "norm_start": s0,
                          "norm_end": s1, "text": hdr(d, "Concall transcript") + "\n" + body}) + "\n")
print(n)
