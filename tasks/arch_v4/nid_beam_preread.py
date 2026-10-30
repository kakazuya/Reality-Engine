"""Idea 2: free Beam pre-reads the 74 proxy search logs. Machine-checks every quote against the hits."""
import concurrent.futures as cf, glob, json, os, re, sys, time
import requests

sys.path.insert(0, os.getcwd())
from reality_engine.scripts.go_session import session_id

OUT = sys.argv[1]
KEY = os.environ.get("OPENCODE_GO_API_KEY_2") or os.environ["OPENCODE_GO_API_KEY"]
URL = "https://opencode.ai/zen/go/v1/chat/completions"
PROMPT = """You check whether held data can really answer a question about an Indian listed company or market.

QUESTION: {q}

SEARCH HITS from our own databases (each has an id):
{hits}

Decide using ONLY the hits. Do not use outside knowledge.
- DIRECT: a hit states the fact the question asks for, for the right company and period.
- PARTIAL: a hit answers part of it, or the right metric for the wrong period or a peer. Name the missing part.
- NONE: nothing relevant. Keyword overlap alone is NONE.

Reply with JSON only:
{{"verdict":"DIRECT|PARTIAL|NONE","hit_id":"<id or empty>","quote":"<exact words copied from that hit, max 25 words, or empty>","missing":"<what is still missing, or empty>"}}"""


def hits_of(d):
    out = []
    for s in d.get("searches", []):
        for i, h in enumerate(s.get("hits") or []):
            out.append((f"{s.get('store')}#{i}", json.dumps(h, ensure_ascii=False)[:420]))
    return out[:40]


def norm(s):
    return re.sub(r"[\s\\\"']+", " ", s).strip().lower()


def one(path):
    d = json.load(open(path, encoding="utf-8"))
    hits = hits_of(d)
    text = "\n".join(f"[{i}] {h}" for i, h in hits) or "(no hits)"
    t = time.time()
    last = None
    for attempt in range(4):
        try:
            r = requests.post(URL, timeout=240, headers={"Authorization": f"Bearer {KEY}", "x-opencode-session": session_id("nid_preread", "beam-free", KEY)},
                              json={"model": "beam-free", "max_tokens": 1500, "messages": [{"role": "user", "content": PROMPT.format(q=d["question"], hits=text)}]})
            if r.status_code != 200:
                last = f"HTTP {r.status_code}: {r.text[:100]}"
                time.sleep(5 * (attempt + 1))
                continue
            j = r.json()
            c = j["choices"][0]["message"].get("content") or ""
            m = re.search(r"\{.*\}", c, re.S)
            v = json.loads(m.group(0))
            q = v.get("quote") or ""
            hay = norm(" ".join(h for _, h in hits))
            ok = bool(q) and norm(q) in hay
            return dict(case=d["case_id"], cls=d.get("class_id"), level=d.get("evidence_level"), question=d["question"], v=v.get("verdict"), hit=v.get("hit_id"), quote=q, missing=v.get("missing"), quote_ok=ok, n_hits=len(hits), secs=round(time.time() - t, 1), usage=j.get("usage"), top=[h[:220] for _, h in hits[:3]])
        except Exception as e:
            last = repr(e)[:150]
            time.sleep(3)
    return dict(case=d["case_id"], cls=d.get("class_id"), level=d.get("evidence_level"), question=d["question"], v="ERROR", error=last, secs=round(time.time() - t, 1))


files = sorted(glob.glob("tasks/arch_v4/nid_search_logs/*.json"))
t0 = time.time()
with cf.ThreadPoolExecutor(8) as ex:
    res = list(ex.map(one, files))
json.dump(res, open(OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("done", len(res), "elapsed", round(time.time() - t0), "s")
