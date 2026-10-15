"""40-page reader quality test for deck pages (Shivam's rule: a new reader needs identifiable >= ~85%, zero misread
numbers and >= 95% of calls answered before it reads in production).

Pages: 40 vision-route deck pages read by Claude Haiku 5.5 (the best reader on the original test), one per document,
fixed by seed so every model sees the same pages. Reference: Haiku's figures + the page's PDF text layer.
Per model it reports: calls answered, figures, identifiable share (unique label+period+unit), recall of Haiku's
numbers, and UNSUPPORTED numbers (in neither Haiku's reading nor the text layer). Unsupported numbers are possible
misreads: the report lists them with the saved page image so a person (or Claude) can check them on the slide.

  python -m reality_engine.scripts.reader_quality_test --models gemini-3.1-flash-lite@g1,dots-studio/dots-3-note-preview:free
Outputs: reality_engine/data/reader_tests/<date>/ (page images, raw answers, report.md)
"""
import argparse
import json
import random
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path

import pymupdf

from reality_engine.scripts import extract_deck_figures as x

OUT = x.OUT_DB.parent / "reader_tests" / date.today().isoformat()


def pick_pages(n=40, seed=40):
    d = sqlite3.connect(f"file:{x.OUT_DB}?mode=ro", uri=True, timeout=60)
    rows = d.execute("""SELECT p.sha256, p.page_no, s.local_path, p.symbol, p.known_at, p.n_facts FROM pages p
        JOIN deck_sources s ON s.sha256 = p.sha256
        WHERE p.final_model = 'claude-haiku-5-5' AND p.route = 'vision' AND p.n_facts >= 4""").fetchall()
    by_doc = {}
    for r in rows:
        by_doc.setdefault(r[0], []).append(r)
    random.seed(seed)
    docs = random.sample(sorted(by_doc), n)
    out = []
    for sha in docs:
        r = random.choice(by_doc[sha])
        ref = d.execute("SELECT raw_output FROM outputs WHERE sha256=? AND page_no=? AND model='claude-haiku-5-5'", r[:2]).fetchone()
        if ref and Path(r[2]).exists():
            out.append({"sha256": r[0], "page_no": r[1], "path": r[2], "symbol": r[3], "known_at": r[4], "ref": ref[0]})
    return out


def numbers(facts):
    return {round(abs(f["value"]), 4) for f in facts if f.get("value") is not None}


# Deck EXHAUSTIVE prompt (2026-10-14, Shivam: test Google's multimodal models on an exhaustive deck prompt). Appended to
# the production prompt; it targets what the score measures: every printed figure, each with a label, period and unit
# specific enough to identify it.
DECK_EXHAUSTIVE = """
Be EXHAUSTIVE and specific. Work through the slide region by region: title, every table, every chart, every KPI box or
callout, and every number in body text or footnotes that is a business figure.
- Tables: one line per cell. metric = the row label plus the column label when the column names a measure or segment.
- Charts: one line per data label, bar, line point or pie slice. metric = series/legend name plus the axis category.
- Make every label specific: include the segment, product, geography or business it belongs to and the measure
  (e.g. 'Domestic Formulations Revenue', not 'Revenue'). Two figures must never share the same metric + period + unit.
- period: from the column header, axis, caption or slide title. Growth figures name their comparison (e.g. 'Q1FY27 YoY').
- unit: from the cell, the table/chart header, the axis title or a slide-level note such as '(Rs Cr)' or 'in Mn'.
- List a number again if it appears under a different label. Never output a number that is not printed on the slide."""


def variant(name):
    """'<model>+low' / '+medium' tests a reader with that reasoning effort (same key, same quotas).
    'cc:<id>' tests a CodeCraft API model (CODECRAFT_API_KEY; test only, never a production reader).
    'gx:<google model id>@g<n>' tests any Google AI Studio model on key n (GEMINI_API_KEY, _2.._30), native API;
    paced at 4/min and 20/day per key (the smallest free Flash quota) unless it is a Gemma or Flash-Lite model."""
    if name.startswith("gx:") and name not in x.MODELS:
        mid, n = name[3:].rsplit("@g", 1)
        lite = "gemma" in mid or "flash-lite" in mid
        body = ({"maxOutputTokens": 8000, "thinkingConfig": {"thinkingLevel": "minimal"}} if "gemma" in mid
                else {"maxOutputTokens": 16000})
        x.MODELS[name] = {"api": "gemini_native", "id": mid, "key_env": "GEMINI_API_KEY" + ("" if n == "1" else f"_{n}"),
                          "price": (0.0, 0.0), "capped": False, "ceiling": 4 if lite else 2,
                          "rpm": 14 if lite else 4, "rpd": 490 if lite else 20, "body": body}
        return
    if name.startswith("cc:") and name not in x.MODELS:
        x.MODELS[name] = {"api": "chat", "id": name[3:], "base": "https://codecraftapi.com/v1", "key_env": "CODECRAFT_API_KEY",
                          "price": (0.0, 0.0), "capped": False, "ceiling": 4, "body": {"max_tokens": 16000}}
        return
    if "+" in name and name not in x.MODELS:
        base, effort = name.split("+", 1)
        cfg = dict(x.MODELS[base]); cfg["body"] = {**cfg["body"], "reasoning_effort": effort}
        x.MODELS[name] = cfg


def run(models, exhaustive=False):
    tag = "!ex" if exhaustive else ""
    for m in [r for mm in models for r in mm.split("|")]:
        variant(m)
    OUT.mkdir(parents=True, exist_ok=True)
    pages = pick_pages()
    store = x.Store(str(OUT / "test.db"))
    ledger = x.SpendLedger(store, margin=1.0)
    readers = [r for m in models for r in m.split("|")]
    client = x.Client(ledger, {m: x.AdaptiveLimiter(x.MODELS[m]["ceiling"], 1, x.MODELS[m]["ceiling"]) for m in readers})
    tasks = []
    for pg in pages:
        doc = pymupdf.open(pg["path"]); page = doc[pg["page_no"] - 1]
        task = x.page_task({"symbol": pg["symbol"], "company": pg["symbol"], "known_at": pg["known_at"]}, page, pg["page_no"])
        img = OUT / f"{pg['symbol']}_{pg['sha256'][:8]}_p{pg['page_no']}.png"
        if not img.exists():
            page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(str(img))
        tasks.append((pg, task, x.render_jpeg_b64(page), img))

    def one(args):
        m, (pg, task, b64, img) = args
        f = OUT / "answers" / (m.replace("/", "_").replace(":", "_").replace("|", "+")[:120] + tag) / f"{img.stem}.json"
        if f.exists() and "error" not in json.loads(f.read_text(encoding="utf-8")):
            return m, pg, img, json.loads(f.read_text(encoding="utf-8"))
        f.parent.mkdir(parents=True, exist_ok=True)
        # "a|b": one model on several keys, pages split between them (tight free quotas, e.g. 20/day)
        keys = m.split("|"); reader = keys[tasks.index((pg, task, b64, img)) % len(keys)]
        try:
            # 2026-10-14: a 20/day model hit its cap and every worker slept 11 h. Now: one process per model, quota 429s
            # bench only 2 min (BENCH_QUOTA_SEC below; per-minute limits clear), spread a 20/day model over >= 8 keys
            # so no key reaches its cap, and 20/day models get fewer retries (each retry spends a call)
            res = client.read(reader, b64, x.build_prompt(task) + (DECK_EXHAUSTIVE if exhaustive else ""),
                              tries=3 if x.MODELS[reader].get("rpd", 10**6) <= 50 else 5)
            res = {"output": res["output"], "seconds": res["seconds"]}
        except Exception as e:
            res = {"error": str(e)[:300]}
        res["truth"] = sorted(task["truth"])
        f.write_text(json.dumps(res), encoding="utf-8")
        return m, pg, img, res

    jobs = [(m, t) for m in models for t in tasks]
    with ThreadPoolExecutor(8) as ex:
        results = list(ex.map(one, jobs))

    md = [f"# Reader quality test, {date.today()} ({len(tasks)} pages, reference: Claude Haiku 5.5 + text layer; "
          f"prompt: {'EXHAUSTIVE' if exhaustive else 'production'})", "",
          "| model | answered | figures | identifiable | Haiku's numbers found | unsupported numbers | median s |", "|---|---|---|---|---|---|---|"]
    detail = []
    for m in models:
        rs = [(pg, img, r) for mm, pg, img, r in results if mm == m]
        ok = [(pg, img, r) for pg, img, r in rs if "output" in r]
        facts_all, found, refn_all, unsup, secs = [], 0, 0, [], []
        for pg, img, r in ok:
            f = x.parse_facts(r["output"]); facts_all += f
            refn = numbers(x.parse_facts(pg["ref"])); got = numbers(f); truth = {round(abs(v), 4) for v in r["truth"]}
            found += len(refn & got); refn_all += len(refn); secs.append(r["seconds"])
            for v in sorted(got - refn - truth):
                unsup.append((img.name, v, next((z["metric"] for z in f if z.get("value") is not None and round(abs(z["value"]), 4) == v), "")))
        ident = x.identifiable_share(facts_all) or 0
        secs.sort()
        md.append(f"| {m.split('|')[0]}{' x' + str(m.count('|') + 1) + ' keys' if '|' in m else ''}{tag} | {len(ok)}/{len(rs)} | {len(facts_all)} | {ident:.1%} | {found}/{refn_all} ({found / max(1, refn_all):.0%}) | "
                  f"{len(unsup)} | {secs[len(secs) // 2] if secs else '-'} |")
        detail += [f"", f"## {m}: unsupported numbers (check on the page image)"] + [f"- {i}: {v} ({lab[:80]})" for i, v, lab in unsup[:80]]
    first = models[0].split("|")[0].replace("gx:", "").split("@")[0].replace("/", "_").replace(":", "_")
    rep = OUT / f"report{'_ex' if exhaustive else ''}_{first}_{time.strftime('%H%M')}.md"
    rep.write_text("\n".join(md + detail) + "\n", encoding="utf-8")
    print("\n".join(md)); print(f"\nreport: {rep}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True, help="comma-separated; 'a|b' = one model on several keys, pages split")
    ap.add_argument("--exhaustive", action="store_true", help="append DECK_EXHAUSTIVE to the production prompt")
    a = ap.parse_args()
    import os
    from reality_engine.scripts.resource_watchdog import user_env
    os.environ.update({k: v for k, v in user_env().items() if k not in os.environ})   # keys added after this shell started
    x.BENCH_QUOTA_SEC = 120   # tests: a quota 429 is usually per-minute; production keeps 30 min
    run(a.models.split(","), a.exhaustive)
