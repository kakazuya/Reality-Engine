"""Annual-report free-reader quality test (FREE_MODEL_QUALITY_PLAN.md, step 2): TEST ONLY, nothing goes to the DB.

The free API readers (LongCat on OpenCode Go, Dots on Kilo) cannot open files or grep like the Haiku agents did, so
each gets one whole section (GESHIP v2 split) or 50-page chunk (COCHINSHIP, CONCOR) in the prompt and returns every
storable fact as CSV rows. Scoring against the must-find list (checked facts from the Haiku gold runs):
  recall     must-find facts present with the right number (or, for prose facts, the key terms)
  precision  every number in a `value` field must appear in that section's text (digits compared, grouping ignored)
  pages      cited pages must fall inside the section

  python tasks/ar_study/free_test/free_reader_test.py run   [--models longcat,dots] [--reports GESHIP,CONCOR,COCHINSHIP]
  python tasks/ar_study/free_test/free_reader_test.py score
Step is left out on purpose: it is the deck run's second reader and is already throttled.
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

HERE = Path(__file__).resolve().parent
STUDY = HERE.parent
ROOT = STUDY.parents[1]
sys.path.insert(0, str(ROOT))
from reality_engine.scripts import extract_deck_figures as x   # noqa: E402  (reader configs)
from reality_engine.scripts.resource_watchdog import user_env   # noqa: E402

OUT = HERE / "outputs"
READERS = {"longcat": "longcat-2.5-preview-free", "dots": "dots-studio/dots-3-note-preview:free@kilo2",
           "nemotron-ultra": "nemotron-ultra@kilo", "nemotron-super": "nemotron-super@kilo2",
           "nim-ultra": "nemotron-ultra@nim", "nim-super": "nemotron-super@nim", "glyph": "glyph@kilo"}
NIM = "https://integrate.api.nvidia.com/v1"
NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}   # 2026-10-11: with thinking, Super spent 80% of output on it
KILO = "https://api.kilo.ai/api/gateway"
# text-only readers (not in the deck extractor). Nemotron Super uses its whole output budget on reasoning unless
# effort is low (2026-10-11 probe: default effort -> no CSV; low -> 98 rows).
EXTRA = {"glyph@kilo": {"id": "stealth/glyph-cluster", "base": KILO, "key_env": "KILO_API_KEY",
                        "body": {"reasoning": {"effort": "low"}}},   # free stealth reasoning model (text only, 256k context)
         "nemotron-ultra@kilo": {"id": "nvidia/nemotron-3-ultra-550b-a55b:free", "base": KILO, "key_env": "KILO_API_KEY", "body": {}},
         "nemotron-super@kilo2": {"id": "nvidia/nemotron-3-super-120b-a12b:free", "base": KILO, "key_env": "KILO_API_KEY_2",
                                  "body": {"reasoning": {"effort": "low"}}},
         "nemotron-ultra@nim": {"id": "nvidia/nemotron-3-ultra-550b-a55b", "base": NIM, "key_env": "NVIDIA_API_KEY", "body": NO_THINK},
         "nemotron-super@nim": {"id": "nvidia/nemotron-3-super-120b-a12b", "base": NIM, "key_env": "NVIDIA_API_KEY", "body": NO_THINK}}
COMPANY = {"GESHIP": "The Great Eastern Shipping Co. Ltd.", "CONCOR": "Container Corporation of India Ltd.",
           "COCHINSHIP": "Cochin Shipyard Ltd."}

PROMPT = """You are reading part of {company}'s FY24 (April 2023 - March 2024) annual report, an Indian listed company.
Pages are marked "=== PAGE n ===" (n = PDF page number).

Task: extract EVERY fact in this text that an investor database should store and that is NOT just a standard line item
of the main balance sheet or P&L. Include:
- auditor's report: modified opinion, qualification, emphasis of matter, key audit matters (with amounts),
  audit-trail / edit-log remarks; CARO remarks; C&AG comments; secretarial-audit (MR-3) qualifications
- contingent liabilities and claims by type, disputed tax/duty demands, capital commitments, capital advances
- cash flow statement totals (operating, investing, financing) for both years
- order book / contract liabilities / unbilled revenue, receivables and their ageing buckets
- related-party shares (BRSR Section A) and related-party transactions by party, loans/investments in related parties
- subsidiaries / JVs (AOC-1) figures, credit ratings (agency, instrument, rating, change), borrowings maturity
- CSR obligation / spent / unspent / transfers, remuneration ratios, employee counts
- fleet / capacity / asset lists, delayed or disputed contracts, grants or claims reversed or disallowed,
  regulatory or policy changes, any sign of stress
Skip boilerplate (accounting policies, statutory wording, AGM procedure) unless it states a specific fact.

Output ONLY a CSV with this header, then the rows:
category,item,value,unit,period,basis,page,quote
- value: the number exactly as printed (keep its digits and minus sign); for a prose fact write - and put the fact in item
- unit: as stated on that page (Rs crore, Rs lakh, %, MT, number, ...). Check the page/table header for lakh vs crore.
- period: FY24 / FY23 / as on date; basis: standalone / consolidated / -
- page: the PDF page number from the "=== PAGE n ===" marker; quote: at most 15 words from the page
- Put double quotes around any field that contains a comma.
After the CSV write a line "# NOTES" and 3-8 bullets: signs of stress, related-party leakage, auditor unease or
policy change, each with a page. Do not invent anything; if a section has nothing worth storing, output the header only.

TEXT:
{text}
"""

# must-find facts: (id, report, all-of tokens). A number token matches the digits of a value/item/quote field
# (grouping commas ignored); a word token matches case-insensitively anywhere in a row.
MUST = [
    ("CSL-ocf-standalone", "COCHINSHIP", ["17282.73"]),
    ("CSL-ocf-fy23", "COCHINSHIP", ["204600.40"]),
    ("CSL-ocf-consolidated", "COCHINSHIP", ["17159.36"]),
    ("CSL-contract-liab", "COCHINSHIP", ["487527.27"]),
    ("CSL-1200-pax-vessels", "COCHINSHIP", ["1200", "passenger"]),
    ("CSL-sbfa-reversal", "COCHINSHIP", ["SBFA|shipbuilding financial assistance"]),
    ("CSL-sap-edit-log", "COCHINSHIP", ["edit log|audit trail"]),
    ("CON-kam-tughlakabad", "CONCOR", ["677.68"]),
    ("CON-kam-phillaur", "CONCOR", ["15.96"]),
    ("CON-kam-moradabad", "CONCOR", ["5.58"]),
    ("CON-land-lease-rou", "CONCOR", ["right[- ]of[- ]use|lease liabilit"]),
    ("CON-seis-861", "CONCOR", ["861.05"]),
    ("CON-receivables", "CONCOR", ["329.45"]),
    ("CON-brsr-rpt-purchases", "CONCOR", ["73.65"]),
    ("GES-audit-trail", "GESHIP", ["audit trail|edit log"]),
    ("GES-capcom-standalone", "GESHIP", ["518.88"]),
    ("GES-capcom-consolidated", "GESHIP", ["559.18"]),
    ("GES-care-aaa", "GESHIP", ["AAA"]),
    ("GES-tc-receivables", "GESHIP", ["1142.46"]),
    ("GES-brsr-loans-rp", "GESHIP", ["4.69"]),
    ("GES-brsr-invest-rp", "GESHIP", ["51.01"]),
    ("GES-csr-obligation", "GESHIP", ["24.73"]),
    ("GES-csr-spent", "GESHIP", ["18.77|187777325"]),   # gold list says 18.78; the report prints 18.77 / 18,77,77,325
    ("GES-csr-unspent", "GESHIP", ["6.17"]),
    ("GES-eu-ets", "GESHIP", ["EUA|ETS|emission"]),
]


# Readers whose request size is capped (Gemma: 16k tokens/min per project, so a request must stay well under that):
# sections are cut at page markers into pieces of at most this many characters (~9k tokens), named "<part>#<k>".
SPLIT = {"gemma": 36000}
GEMMA_KEYS = ["gemma-4-31b@g1", "gemma-4-31b@g2"]


def parts(report, max_chars=None):
    files = sorted((STUDY / "text").glob(f"{report}_FY24_AR_*.txt"))
    out = [(f.stem.replace(f"{report}_FY24_AR_", ""), f.read_text(encoding="utf-8", errors="replace")) for f in files]
    if not max_chars:
        return out
    pieces = []
    for name, text in out:
        pages = re.split(r"(?=^=== PAGE \d+ ===)", text, flags=re.M)
        buf, k = "", 1
        for pg in pages:
            if buf and len(buf) + len(pg) > max_chars:
                pieces.append((f"{name}#{k}", buf)); buf, k = "", k + 1
            buf += pg
        if buf.strip():
            pieces.append((f"{name}#{k}", buf))
    return pieces


class TokenPacer:
    """Keeps each key under its tokens-per-minute limit (estimated from prompt length)."""
    def __init__(self, tpm=15000):
        import threading
        self.tpm, self.lock, self.log = tpm, threading.Lock(), {}

    def wait(self, key, tokens):
        while True:
            with self.lock:
                now = time.time(); log = [(t, n) for t, n in self.log.get(key, []) if now - t < 60]
                if sum(n for _, n in log) + tokens <= self.tpm or not log:
                    log.append((now, tokens)); self.log[key] = log; return
                wait = 60 - (now - log[0][0]) + 0.5
            time.sleep(wait)


PACER = TokenPacer()


def call(model, prompt, env, tries=4):
    cfg = EXTRA.get(model) or x.MODELS[model]
    if cfg.get("api") == "gemini_native":
        key = env[cfg["key_env"]]; last = None
        for a in range(6):
            PACER.wait(cfg["key_env"], int(len(prompt) / 3.2) + 1500)
            t = time.time()
            try:
                r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{cfg['id']}:generateContent",
                                  headers={"x-goog-api-key": key}, timeout=900,
                                  json={"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {**cfg["body"], "maxOutputTokens": 32000}})
                if r.status_code == 200 and r.json().get("candidates"):
                    j = r.json(); u = j.get("usageMetadata", {}); c = j["candidates"][0]
                    text = "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []) if not p.get("thought"))
                    return {"text": text, "seconds": round(time.time() - t, 1), "in_tok": u.get("promptTokenCount"),
                            "out_tok": u.get("candidatesTokenCount"), "finish": "length" if c.get("finishReason") == "MAX_TOKENS" else "stop",
                            "key": cfg["key_env"]}
                last = f"HTTP {r.status_code}: {r.text[:300]}"
            except requests.RequestException as e:
                last = str(e)[:300]
            time.sleep(65 if "429" in str(last) else 20 * (a + 1))
        return {"error": last}
    hdr = {"Authorization": f"Bearer {env[cfg.get('key_env', 'OPENCODE_GO_API_KEY')]}", "Content-Type": "application/json",
           "x-opencode-session": str(uuid.uuid4()), "User-Agent": "reality-engine-ar-test/1.0"}
    body = {"model": cfg.get("id", model), **cfg["body"], "messages": [{"role": "user", "content": prompt}]}
    body["max_tokens"] = 32000
    last = None
    for a in range(tries):
        t = time.time()
        try:
            r = requests.post(f"{cfg.get('base', x.BASE)}/chat/completions", headers=hdr, json=body, timeout=900)
            if r.status_code == 200 and r.json().get("choices"):
                j = r.json(); u = j.get("usage", {})
                return {"text": j["choices"][0]["message"].get("content") or "", "seconds": round(time.time() - t, 1),
                        "in_tok": u.get("prompt_tokens"), "out_tok": u.get("completion_tokens"),
                        "finish": j["choices"][0].get("finish_reason")}
            last = f"HTTP {r.status_code}: {r.text[:300]}"
        except requests.RequestException as e:
            last = str(e)[:300]
        time.sleep(30 * (a + 1))
    return {"error": last}


def run(models, reports):
    env = user_env()
    jobs = [(m, rep, name, text) for m in models for rep in reports for name, text in parts(rep, SPLIT.get(m))]

    def one(job):
        m, rep, name, text = job
        f = OUT / m / f"{rep}_{name}.json"
        if f.exists() and "error" not in json.loads(f.read_text(encoding="utf-8")):
            return f"skip {f.name}"
        f.parent.mkdir(parents=True, exist_ok=True)
        reader = GEMMA_KEYS[jobs.index(job) % len(GEMMA_KEYS)] if m == "gemma" else READERS[m]
        res = call(reader, PROMPT.format(company=COMPANY[rep], text=text), env)
        f.write_text(json.dumps(res, indent=1), encoding="utf-8")
        return f"{m} {rep} {name}: " + (res.get("error") or f"{res['seconds']}s in {res['in_tok']} out {res['out_tok']} {res['finish']}")

    with ThreadPoolExecutor(6) as ex:
        for msg in ex.map(one, jobs):
            print(msg, flush=True)


def digits(s):
    return re.sub(r"[^\d.]", "", s.replace(",", ""))


def rows_of(text):
    body = text.split("# NOTES")[0]
    body = re.sub(r"^```\w*|```$", "", body.strip(), flags=re.M).strip()
    i = body.find("category,")
    if i < 0:
        return [], "no CSV header"
    rows, bad = [], 0
    for r in csv.reader(io.StringIO(body[i:])):
        if not r or r[0] == "category":
            continue
        if len(r) > 8 and all(re.fullmatch(r"-?\d+(\.\d+)?", v.strip()) for v in r[2:2 + len(r) - 7]):
            # unquoted Indian grouping ("33,58,258") split the value over several fields: join them back
            r = r[:2] + [",".join(r[2:2 + len(r) - 7])] + r[2 + len(r) - 7:]
        if len(r) != 8:
            bad += 1
            r = (r + [""] * 8)[:8]
        rows.append(dict(zip(["category", "item", "value", "unit", "period", "basis", "page", "quote"], r)))
    return rows, (f"{bad} malformed rows" if bad else "")


def page_range(text):
    p = [int(n) for n in re.findall(r"=== PAGE (\d+) ===", text)]
    return (min(p), max(p)) if p else (0, 0)


def score():
    lines = ["# Free-reader AR test: scores", ""]
    for mdir in sorted(d for d in OUT.iterdir() if d.is_dir()):
        m = mdir.name
        lines += [f"## {m}", "", "| report | part | rows | numbers checked | not in text | pages outside | notes |", "|---|---|---|---|---|---|---|"]
        found = {}
        tot_num = tot_bad = tot_rows = 0
        for rep in COMPANY:
            for name, text in parts(rep, SPLIT.get(m)):
                f = mdir / f"{rep}_{name}.json"
                if not f.exists():
                    continue
                res = json.loads(f.read_text(encoding="utf-8"))
                if "error" in res:
                    lines.append(f"| {rep} | {name} | - | - | - | - | ERROR {res['error'][:80]} |"); continue
                rows, note = rows_of(res["text"])
                hay = digits(text)
                lo, hi = page_range(text)
                nums = [r for r in rows if re.search(r"\d", r["value"]) and r["value"].strip() != "-"]
                bad = [r for r in nums if digits(r["value"]).strip(".") and digits(r["value"]).strip(".") not in hay]
                outside = [r for r in rows if r["page"].strip().isdigit() and not lo <= int(r["page"]) <= hi]
                tot_num += len(nums); tot_bad += len(bad); tot_rows += len(rows)
                if res.get("finish") == "length":
                    note = (note + "; output cut at max_tokens").strip("; ")
                lines.append(f"| {rep} | {name} | {len(rows)} | {len(nums)} | {len(bad)} | {len(outside)} | {note} |")
                for mid, mrep, toks in MUST:
                    if mrep != rep:
                        continue
                    for r in rows:
                        blob = " ".join(r.values())
                        nums = digits(r["value"] + " " + r["item"] + " " + r["quote"])
                        ok = all(any(digits(alt) in nums for alt in t.split("|")) if re.fullmatch(r"[\d.,|]+", t)
                                 else re.search(t, blob, re.I) for t in toks)
                        if ok:
                            found.setdefault(mid, f"{name} p{r['page']}"); break
        hit = [mid for mid, rep, _ in MUST if mid in found]
        lines += ["", f"**Must-find recall: {len(hit)}/{len(MUST)}**; numbers not found in the text: {tot_bad}/{tot_num} "
                  f"({100 * tot_bad / max(1, tot_num):.1f}%); rows {tot_rows}", ""]
        lines += [f"- {'OK ' if mid in found else 'MISS'} {mid} {found.get(mid, '')}" for mid, _, _ in MUST]
        lines.append("")
    (HERE / "SCORES.md").write_text("\n".join(lines), encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--models", default="longcat,dots")
    ap.add_argument("--reports", default="GESHIP,CONCOR,COCHINSHIP")
    a = ap.parse_args()
    if a.cmd == "run":
        run(a.models.split(","), a.reports.split(","))
    else:
        score()
