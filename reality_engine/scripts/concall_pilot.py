"""Concall semantic-extraction pilot (2026-10-18): the same prompt (data/concall_pilot/prompt.md) on 25 transcripts,
read by every free API model we have; Claude Opus/Sonnet are run separately by Claude Code subagents on the Claude plan
and write into the same out/<model>/ layout. Outputs: data/concall_pilot/out/<model>/<doc_id>.json (+ .meta.json with
seconds and token usage). Re-runnable: an existing output is kept.

    python -m reality_engine.scripts.concall_pilot run --models gemma-4-26b-a4b-it,gemini-3.8-flash,longcat-2.5-preview-free
    python -m reality_engine.scripts.concall_pilot score
"""
import argparse
import concurrent.futures as cf
import json
import re
import time
import uuid
from pathlib import Path

import requests

from reality_engine.scripts import ingest_annual_reports as ar

PILOT = Path(__file__).resolve().parents[1] / "data" / "concall_pilot"
GOOGLE = {"gemma-4-26b-a4b-it", "gemma-4-31b-it", "gemini-3.5-flash-lite", "gemini-3.8-flash", "gemini-3.1-pro-preview",
          "gemini-2.5-pro"}
GO = {"longcat-2.5-preview-free", "beam-free"}


# reader name -> (model id, prompt file): round 2 (2026-10-18) adds rules learned from round 1's judged errors
ALIASES = {"longcat-v2": ("longcat-2.5-preview-free", "prompt_v2.md"),
           # round 3 (2026-10-18): paid Go models, prompt v2, all on Go key 2 (key 1's monthly allowance is used up)
           "mimo-v2.6-flash": ("mimo-v2.6-flash", "prompt_v2.md"),
           "deepseek-v4.1-flash": ("deepseek-v4.1-flash", "prompt_v2.md"),
           "muse-spark-1.3-contributor": ("muse-spark-1.3-contributor", "prompt_v2.md"),
           # round 4 (2026-10-18 evening): same model id after DeepSeek's 1017 release; tokens/quality vs round 3 tell
           # whether Go now serves V4.1-Flash-1017
           "deepseek-v4.1-flash-r4": ("deepseek-v4.1-flash", "prompt_v2.md")}
GO_KEY2_ONLY = {"mimo-v2.6-flash", "deepseek-v4.1-flash", "muse-spark-1.3-contributor", "deepseek-v4.1-flash-r4"}
RESPONSES_API = {"muse-spark-1.3-contributor"}   # Muse answers only on /responses (chat/completions gives 400)


def prompt_for(item, prompt_file="prompt.md"):
    text = (PILOT / "text" / f"{item['doc_id']}_{item['symbol']}.txt").read_text(encoding="utf-8")
    p = (PILOT / prompt_file).read_text(encoding="utf-8")
    return (p.replace("{company}", item["symbol"]).replace("{symbol}", item["symbol"])
             .replace("{date}", item["date"]).replace("{text}", text))


def call_google(model, prompt, key):
    body = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"maxOutputTokens": 32000}}
    if not model.startswith("gemma"):
        body["generationConfig"]["responseMimeType"] = "application/json"
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                      headers={"x-goog-api-key": key}, json=body, timeout=900)
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    j = r.json(); u = j.get("usageMetadata", {})
    text = "".join(p.get("text", "") for c in j.get("candidates", []) for p in c.get("content", {}).get("parts", [])
                   if not p.get("thought"))
    return text, u.get("promptTokenCount"), (u.get("candidatesTokenCount") or 0) + (u.get("thoughtsTokenCount") or 0)


def call_go(model, prompt, key):
    if model in RESPONSES_API:
        r = requests.post("https://opencode.ai/zen/go/v1/responses", timeout=900,
                          headers={"Authorization": f"Bearer {key}", "x-opencode-session": str(uuid.uuid4())},
                          json={"model": model, "input": prompt, "max_output_tokens": 32000})
        if r.status_code != 200:
            raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
        j = r.json(); u = j.get("usage") or {}
        if j.get("status") != "completed":
            raise RuntimeError(f"response {j.get('status')}: {str(j.get('incomplete_details') or j.get('error'))[:150]}")
        text = "".join(c.get("text", "") for o in j.get("output", []) if o.get("type") == "message"
                       for c in o.get("content", []) if c.get("type") == "output_text")
        return text, u.get("input_tokens"), u.get("output_tokens")
    r = requests.post("https://opencode.ai/zen/go/v1/chat/completions", timeout=900,
                      headers={"Authorization": f"Bearer {key}", "x-opencode-session": str(uuid.uuid4())},
                      json={"model": model, "max_tokens": 32000, "messages": [{"role": "user", "content": prompt}]})
    if r.status_code != 200:
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
    j = r.json(); u = j.get("usage", {})
    return j["choices"][0]["message"].get("content") or "", u.get("prompt_tokens"), u.get("completion_tokens")


def parse_json(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    i, j = t.find("{"), t.rfind("}")
    return json.loads(t[i:j + 1])


def run_one(model, item, key):
    out = PILOT / "out" / model / f"{item['doc_id']}.json"
    if out.exists():
        return model, item["symbol"], "have"
    out.parent.mkdir(parents=True, exist_ok=True)
    mid, pfile = ALIASES.get(model, (model, "prompt.md"))
    fn = call_google if mid in GOOGLE else call_go
    last = ""
    for attempt in range(4):
        t0 = time.time()
        try:
            text, it, ot = fn(mid, prompt_for(item, pfile), key)
            data = parse_json(text)
            out.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
            out.with_suffix(".meta.json").write_text(json.dumps(
                {"seconds": round(time.time() - t0, 1), "in_tok": it, "out_tok": ot}), encoding="utf-8")
            return model, item["symbol"], "ok"
        except Exception as e:
            last = str(e)[:160]
            (PILOT / "out" / model / f"{item['doc_id']}.err.txt").write_text(last, encoding="utf-8")
            time.sleep(65 if "429" in last else 15)
    return model, item["symbol"], f"failed: {last}"


def run(models, workers):
    env = ar.user_env()
    gkeys = [env[k] for k in ar.gemini_keys(env)]
    sample = json.loads((PILOT / "sample.json").read_text())
    jobs = []
    for m in models:
        for n, item in enumerate(sample):
            if ALIASES.get(m, (m,))[0] in GOOGLE:
                key = gkeys[n % len(gkeys)]
            elif m in GO_KEY2_ONLY:
                key = env["OPENCODE_GO_API_KEY_2"]
            else:
                key = env["OPENCODE_GO_API_KEY" if n % 2 == 0 else "OPENCODE_GO_API_KEY_2"]
            jobs.append((m, item, key))
    with cf.ThreadPoolExecutor(workers) as ex:
        for m, sym, st in ex.map(lambda j: run_one(*j), jobs):
            print(m, sym, st, flush=True)


LISTS = ["guidance", "capex", "order_book", "capacity_and_projects", "demand_commentary", "margin_and_cost_commentary",
         "pricing_and_competition", "balance_sheet_and_cash", "risks_and_headwinds", "one_offs_and_surprises",
         "analyst_pushback", "key_numbers"]
VALUE_KEYS = ("value", "amount")


def _norm(s):
    return re.sub(r"[^a-z0-9%.]+", " ", str(s).lower()).strip()


def _digits(v):
    """numbers in a value string, as digit strings without grouping commas ('1,234.5 crore' -> ['1234.5'])."""
    return [x.replace(",", "") for x in re.findall(r"\d[\d,]*\.?\d*", str(v)) if any(c.isdigit() for c in x)]


def score():
    sample = json.loads((PILOT / "sample.json").read_text())
    texts = {s["doc_id"]: (PILOT / "text" / f"{s['doc_id']}_{s['symbol']}.txt").read_text(encoding="utf-8") for s in sample}
    ntext = {d: _norm(t) for d, t in texts.items()}
    tdig = {d: set(x.replace(",", "") for x in re.findall(r"\d[\d,]*\.?\d*", t)) for d, t in texts.items()}
    models = sorted(p.name for p in (PILOT / "out").iterdir() if p.is_dir())
    res, union = {}, {}
    for m in models:
        r = {"docs": 0, "items": 0, "quotes": 0, "quotes_ok": 0, "nums": 0, "nums_ok": 0, "guid": 0, "in": 0, "out": 0,
             "sec": 0.0, "found": {}}
        for s in sample:
            d = s["doc_id"]; p = PILOT / "out" / m / f"{d}.json"
            if not p.exists():
                continue
            try:
                j = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            r["docs"] += 1
            meta = p.with_suffix(".meta.json")
            if meta.exists():
                mt = json.loads(meta.read_text()); r["in"] += mt.get("in_tok") or 0; r["out"] += mt.get("out_tok") or 0
                r["sec"] += mt.get("seconds") or 0
            found = set()
            for k in LISTS:
                for it in (j.get(k) or []):
                    if not isinstance(it, dict):
                        continue
                    r["items"] += 1; r["guid"] += k == "guidance"
                    q = it.get("quote")
                    if q:
                        r["quotes"] += 1
                        nq = _norm(q)
                        r["quotes_ok"] += bool(nq) and (nq in ntext[d] or _norm(q[:60]) in ntext[d])
                    for vk in VALUE_KEYS:
                        for x in _digits(it.get(vk, "")):
                            r["nums"] += 1
                            ok = x in tdig[d]
                            r["nums_ok"] += ok
                            if ok and k in ("guidance", "key_numbers", "capex", "order_book"):
                                found.add(x)
            r["found"][d] = found
            union.setdefault(d, set()).update(found)
        res[m] = r
    print(f"{'model':28} docs items/doc guid/doc quotes_verbatim nums_in_text recall_vs_union  in_tok/doc out_tok/doc sec/doc")
    for m, r in sorted(res.items(), key=lambda x: -sum(len(v) for v in x[1]["found"].values())):
        docs = max(1, r["docs"])
        rec = sum(len(r["found"].get(d, set())) for d in union) / max(1, sum(len(union[d]) for d in union))
        print(f"{m:28} {r['docs']:4} {r['items'] / docs:9.1f} {r['guid'] / docs:8.1f} "
              f"{100 * r['quotes_ok'] / max(1, r['quotes']):14.1f}% {100 * r['nums_ok'] / max(1, r['nums']):11.1f}% "
              f"{100 * rec:14.1f}% {r['in'] / docs:11.0f} {r['out'] / docs:11.0f} {r['sec'] / docs:7.0f}")


VERIFY_PROMPT = """You are checking another reader's extraction from an earnings-call transcript. For EACH item below,
decide from the transcript alone whether it is supported. Rules: a quote must exist word for word and mean what the item
says (watch negations such as "not"); numbers, periods and units must match; basis standalone/consolidated must be said;
guidance direction raised/maintained/lowered needs an earlier figure referenced in the call; nothing may be inferred.
Return ONE JSON object only: {"checks": [{"id": "<id>", "verdict": "supported|wrong|unsupported", "reason": "<short>"}]}

ITEMS:
{items}

TRANSCRIPT:
{text}
"""


def machine_check(doc_text, data):
    """Free checks: quote word-for-word (whitespace-insensitive), every number of a value in the text, basis word said.
    Returns (data with failing items removed and basis fixed, counts)."""
    nt = _norm(doc_text); low = doc_text.lower()
    tdig = set(x.replace(",", "") for x in re.findall(r"\d[\d,]*\.?\d*", doc_text))
    c = {"items": 0, "bad_quote": 0, "bad_number": 0, "basis_fixed": 0}
    for k in LISTS:
        keep = []
        for it in (data.get(k) or []):
            if not isinstance(it, dict):
                continue
            c["items"] += 1
            q = it.get("quote")
            if q and _norm(q) not in nt:
                c["bad_quote"] += 1; continue
            if any(x not in tdig for vk in VALUE_KEYS for x in _digits(it.get(vk, ""))):
                c["bad_number"] += 1; continue
            if it.get("basis") in ("standalone", "consolidated") and it["basis"] not in low:
                it["basis"] = "unknown"; c["basis_fixed"] += 1
            keep.append(it)
        data[k] = keep
    return data, c


def verify(reader, workers):
    """round 2: machine checks, then a LongCat verifier call per transcript; unsupported/wrong items are dropped.
    Writes out/<reader>-checked/<doc_id>.json and prints what was removed."""
    env = ar.user_env()
    sample = json.loads((PILOT / "sample.json").read_text())
    dst = PILOT / "out" / f"{reader}-checked"; dst.mkdir(parents=True, exist_ok=True)

    def one(n_item):
        n, item = n_item
        src = PILOT / "out" / reader / f"{item['doc_id']}.json"
        if not src.exists() or (dst / src.name).exists():
            return None
        text = (PILOT / "text" / f"{item['doc_id']}_{item['symbol']}.txt").read_text(encoding="utf-8")
        data, c = machine_check(text, json.loads(src.read_text(encoding="utf-8")))
        ids = {}
        lines = []
        for k in LISTS:
            for i, it in enumerate(data.get(k) or []):
                iid = f"{k}:{i}"; ids[iid] = (k, it); lines.append(json.dumps({"id": iid, **it}, ensure_ascii=False))
        key = env["OPENCODE_GO_API_KEY" if n % 2 == 0 else "OPENCODE_GO_API_KEY_2"]
        p = VERIFY_PROMPT.replace("{items}", "\n".join(lines)).replace("{text}", text)
        for attempt in range(4):
            try:
                out, it_, ot_ = call_go("longcat-2.5-preview-free", p, key)
                checks = parse_json(out).get("checks", [])
                break
            except Exception as e:
                time.sleep(30); checks = None
        if checks is None:
            return item["symbol"], c, "verifier failed"
        bad = {ch["id"] for ch in checks if ch.get("verdict") in ("wrong", "unsupported")}
        for k in LISTS:
            data[k] = [it for i, it in enumerate(data.get(k) or []) if f"{k}:{i}" not in bad]
        c["verifier_dropped"] = len(bad)
        (dst / src.name).write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        return item["symbol"], c, "ok"

    with cf.ThreadPoolExecutor(workers) as ex:
        for r in ex.map(one, enumerate(sample)):
            if r:
                print(*r, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score", "verify"])
    ap.add_argument("--models", default="")
    ap.add_argument("--workers", type=int, default=25)
    a = ap.parse_args()
    if a.cmd == "score":
        return score()
    if a.cmd == "verify":
        return verify(a.models, a.workers)
    run(a.models.split(","), a.workers)


if __name__ == "__main__":
    main()
