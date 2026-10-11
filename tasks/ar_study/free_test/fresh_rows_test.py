"""Fresh, page-checked confirmation of the row clean-up pass + guards (AR protocol gate 1, second round).

Six FY24 reports never used in the study (SUNPHARMA, LT, ICICIBANK, TITAGARH, KPIGREEN, NAVINFLUOR):
  1. parse:   challenger CPU extractor, unchanged, below-normal priority          -> fresh_out/<SYM>.json
  2. sample:  10 storable rows per report (gate.storable, confidence >= 0.7), seed 12
  3. read:    LongCat, V1 (block rows) and V2 (block rows + page text), one call per table block
  4. guard:   reality_engine.processing.ar_row_guards.apply
  5. review:  fresh_review.md, each row with the page lines around its value, for Claude to judge against the page

  python tasks/ar_study/free_test/fresh_rows_test.py parse|sample|read|review
"""
import json
import random
import re
import sys
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf

HERE = Path(__file__).resolve().parent
CH = HERE.parent / "challenger"
ROOT = HERE.parents[2]
sys.path[:0] = [str(HERE), str(CH), str(ROOT)]
import free_reader_test as frt                     # noqa: E402
import row_cleanup_test as rct                     # noqa: E402
from reality_engine.processing import ar_row_guards as guards   # noqa: E402

REPORTS = ["SUNPHARMA", "LT", "ICICIBANK", "TITAGARH", "KPIGREEN", "NAVINFLUOR"]
FRESH = HERE / "fresh_out"
import os
MODE = os.environ.get("FRESH_MODE", "storable")   # storable (round 1) | verified (round 2: rows production would clean)
SAMPLE = HERE / ("fresh_sample.json" if MODE == "storable" else "fresh_vsample.json")
READS = HERE / ("fresh_reads" if MODE == "storable" else "fresh_vreads")
REVIEW = HERE / ("fresh_review.md" if MODE == "storable" else "fresh_vreview.md")


def pdf_of(sym):
    import sqlite3
    c = sqlite3.connect(f"file:{ROOT / 'reality_engine' / 'data' / 'equity_intelligence.db'}?mode=ro", uri=True)
    return c.execute("""select local_file_path from corporate_documents where symbol=? and doc_type='ANNUAL_REPORT'
        and local_file_path is not null and coalesce(bse_dissem_ts,publication_date) between '2024-05-01' and '2024-10-31'
        order by coalesce(bse_dissem_ts,publication_date) desc limit 1""", (sym,)).fetchone()[0]


def parse():
    import extract_cpu, xbrl_tie
    xbrl_tie.low_priority()
    extract_cpu.OUT = FRESH
    for s in REPORTS:
        if (FRESH / f"{s}.json").exists():
            continue
        sector = "Financial Services" if s == "ICICIBANK" else None
        o = extract_cpu.run(s, pdf_of(s), fy=2024, sector=sector)
        print(s, o["seconds"], "s", sum(len(p["rows"]) for p in o["pages"]), "rows", flush=True)


def sample():
    from gate import storable
    random.seed(12)
    out = []
    for s in REPORTS:
        o = json.loads((FRESH / f"{s}.json").read_text(encoding="utf-8"))
        cand = [(p, r) for p in o["pages"] for r in p["rows"]
                if r.get("via") == "columns" and r.get("values") and (r.get("confidence") or 0) >= 0.7 and storable(r)]
        for p, r in random.sample(cand, min(10, len(cand))):
            out.append({"report": s, "pdf": o["pdf"], "fy": o["fy"], "page": p["page"], "block": r["block"], "row": r["row"],
                        "col": r["col"], "value": r["values"][0]})
        print(s, len(cand), "storable rows")
    SAMPLE.write_text(json.dumps(out, indent=1), encoding="utf-8")


def prev_pdf_of(sym):
    import sqlite3
    c = sqlite3.connect(f"file:{ROOT / 'reality_engine' / 'data' / 'equity_intelligence.db'}?mode=ro", uri=True)
    r = c.execute("""select local_file_path from corporate_documents where symbol=? and doc_type='ANNUAL_REPORT'
        and local_file_path is not null and coalesce(bse_dissem_ts,publication_date) between '2023-05-01' and '2023-10-31'
        order by coalesce(bse_dissem_ts,publication_date) desc limit 1""", (sym,)).fetchone()
    return r[0] if r else None


def vsample():
    """Rows verified like row_verify.py: a cell in the row equals an XBRL annual figure on that page, or a FY23 figure
    printed as current year in last year's report (>= 3 significant digits, the AR study's rule after INFY p290)."""
    import extract_cpu, xbrl_tie
    from gate import prior_index, norm, storable
    xbrl_tie.low_priority()
    random.seed(12)
    out = []
    for s in REPORTS:
        prev_json = FRESH / "prev" / f"{s}.json"
        if not prev_json.exists() and prev_pdf_of(s):
            extract_cpu.OUT = FRESH / "prev"; (FRESH / "prev").mkdir(exist_ok=True)
            extract_cpu.run(s, prev_pdf_of(s), fy=2023, sector="Financial Services" if s == "ICICIBANK" else None)
        tie = xbrl_tie.tie(s, FRESH / f"{s}.json")
        xh = {(h["page"], norm(h["raw"])) for h in tie["hits"]}
        prev = prior_index(prev_json, "2023") if prev_json.exists() else set()
        o = json.loads((FRESH / f"{s}.json").read_text(encoding="utf-8"))
        rows = defaultdict(list)
        for p in o["pages"]:
            for r in p["rows"]:
                if r.get("via") == "columns" and r.get("value") is not None:
                    rows[(p["page"], r["block"], r["row"])].append(r)
        sig = lambda r: len(norm(r["values"][0]).replace(".", "").lstrip("0-")) >= 3
        ver = []
        for (pg, b, i), rs in rows.items():
            by_x = any((pg, norm(r["values"][0])) in xh and sig(r) for r in rs)
            by_p = any((r.get("period") or "").startswith("2023") and sig(r) and (r.get("unit"), norm(r["values"][0])) in prev
                       for r in rs)
            if by_x or by_p:
                ver += [(pg, r) for r in rs if storable(r)]
        print(s, "prev AR" if prev else "NO prev AR", "| xbrl hits", len(tie["hits"]), "| verified storable cells", len(ver), flush=True)
        for pg, r in random.sample(ver, min(10, len(ver))):
            out.append({"report": s, "pdf": o["pdf"], "fy": o["fy"], "page": pg, "block": r["block"], "row": r["row"],
                        "col": r["col"], "value": r["values"][0]})
    SAMPLE.write_text(json.dumps(out, indent=1), encoding="utf-8")


def load():
    smp = json.loads(SAMPLE.read_text(encoding="utf-8"))
    cache, out = {}, []
    for i, t in enumerate(smp):
        o = cache.setdefault(t["report"], json.loads((FRESH / f"{t['report']}.json").read_text(encoding="utf-8")))
        page = next(p for p in o["pages"] if p["page"] == t["page"])
        row = next(r for r in page["rows"] if r.get("via") == "columns" and r["block"] == t["block"] and r["row"] == t["row"]
                   and r["col"] == t["col"])
        out.append({"tid": i, "row": row, "page": page, "pdf": t["pdf"], "fy": t["fy"], "report": t["report"],
                    "verdict": {"report": t["report"]}})
    return out


def read(model="longcat"):
    env = frt.user_env()
    targets = load()
    groups = defaultdict(list)
    for t in targets:
        groups[(t["report"], t["page"]["page"], t["row"]["block"])].append(t)
    jobs = [(v, k, g) for v in ("v1", "v2") for k, g in groups.items()]

    def one(job):
        v, k, g = job
        f = READS / v / f"{k[0]}_{k[1]}_{k[2]}.json"
        prompt = rct.build(g, v)
        if f.exists():
            return None
        f.parent.mkdir(parents=True, exist_ok=True)
        res = frt.call(frt.READERS[model], prompt, env)
        res["targets"] = {t["tid"]: t["rid"] for t in g}
        f.write_text(json.dumps(res, indent=1), encoding="utf-8")
        return f"{v} {k}: " + (res.get("error") or f"{res['seconds']}s")

    print(f"{len(targets)} rows, {len(groups)} blocks")
    with ThreadPoolExecutor(6) as ex:
        for m in ex.map(one, jobs):
            if m:
                print(m, flush=True)


def context(pdf, pno, value, cache={}):
    """Page lines around the value (for judging against the page)."""
    if pdf not in cache:
        cache[pdf] = pymupdf.open(pdf)
    lines = cache[pdf][pno - 1].get_text().splitlines()
    head = " / ".join(l.strip() for l in lines[:15] if l.strip())
    v = re.sub(r"[()\s]", "", value)
    hits = [i for i, l in enumerate(lines) if v and v in re.sub(r"[()\s]", "", l)]
    if not hits:
        return head, "(value not found in text layer)"
    i = hits[0]
    return head, " | ".join(l.strip() for l in lines[max(0, i - 6):i + 3] if l.strip())


def review():
    targets = load()
    got = {"v1": {}, "v2": {}}
    for v in got:
        for f in (READS / v).glob("*.json"):
            res = json.loads(f.read_text(encoding="utf-8"))
            ans = rct.parse(res.get("text", ""))
            for tid, rid in res.get("targets", {}).items():
                got[v][int(tid)] = ans.get(rid)
    md = ["# Fresh rows: parser vs LongCat+guards, with page context", ""]
    for t in targets:
        r, p = t["row"], t["page"]
        head, ctx = context(t["pdf"], p["page"], r["values"][0])
        md += [f"## {t['tid']}. {t['report']} p{p['page']} value {r['values'][0]}",
               f"- page head: {head[:200]}", f"- around value: {ctx[:600]}",
               f"- parser: label `{r['label'][:120]}` | column `{(r.get('column') or '')[:80]}` | unit {r.get('unit')} | period {r.get('period')} | page unit {p.get('unit')}"]
        for v in ("v1", "v2"):
            a = got[v].get(t["tid"])
            if not a:
                md.append(f"- {v}: no answer"); continue
            out, flags = guards.apply(r, a, page_header=head, verified=(MODE == "verified"))
            md.append(f"- {v}+guards: label `{out['label_clean'][:120]}` | unit {out['unit']} | period {out['period']} | "
                      f"keep {out['keep']}" + (f" | rejected: {'; '.join(flags)}" if flags else ""))
        md.append("")
    REVIEW.write_text("\n".join(md), encoding="utf-8")
    print(f"wrote {REVIEW.name} ({len(targets)} rows)")


if __name__ == "__main__":
    {"parse": parse, "sample": sample, "vsample": vsample, "read": read, "review": review}[sys.argv[1]]()
