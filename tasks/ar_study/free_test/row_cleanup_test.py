"""Row clean-up test (AR protocol gate 1): can a free model fix the label / unit / period of CPU-parsed table rows?

Input: the 39+39 hand-checked rows (challenger/hand_check_verdicts.csv), found again in challenger/out_step4/<SYM>.json
by page + value. One call per (report, page, table block); the model sees the block's rows as compact lines and returns
JSON for the target rows only. It never retypes the value: the row id ties the answer to the CPU cell.
  V1  block rows only (the cheap design)
  V2  block rows + the page's text layer (for cut or merged labels)

  python tasks/ar_study/free_test/row_cleanup_test.py run [--variants v1,v2] [--model longcat]
  python tasks/ar_study/free_test/row_cleanup_test.py table      -> row_cleanup_results.md (side by side, for judging)
"""
import argparse
import csv
import json
import re
import sys
import time
import uuid
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pymupdf
import requests

HERE = Path(__file__).resolve().parent
CH = HERE.parent / "challenger"
sys.path.insert(0, str(HERE))
import free_reader_test as frt   # noqa: E402  (reader configs, call())

OUT = HERE / "row_outputs"

PROMPT = """You clean up table rows that a parser extracted from an Indian company's annual report (fiscal year ending
{fy_end}). The parser gets the numbers right but often gets labels, units or years wrong:
- labels merged with the next heading, cut off, or missing their parent line (e.g. "Others" under "Other expenses");
- counts, shares, percentages, tonnes, m3, days or ratios tagged as rupees; absolute rupees tagged as lakh;
- a column year mapped wrongly.

Page {page}, page unit from header: {unit}, section scope: {scope}.
Table rows as `id | label | column header | year | unit | value` (all rows of the table, for context):
{rows}
{page_text}
For each TARGET id ({targets}) return one JSON object per line, nothing else:
{{"id": <id>, "label": "<clear, specific label, with the parent line or table title if the label alone is vague>",
 "unit": "<one of: rupees, thousand, lakh, crore, million, billion, percent, count, shares, tonnes, m3, kwh, gj, days, ratio, times, other>",
 "period_end": "<YYYY-MM-DD or null if no year applies>", "scope": "<standalone|consolidated|unknown>",
 "keep": <true if it is a real data row worth storing, false for junk/heading/notes>, "fix": "<what you changed, or none>"}}
Never change or restate the value. If unsure, keep the parser's field and say so in fix."""


def load_targets():
    rows = [r for r in csv.DictReader(l for l in open(CH / "hand_check_verdicts.csv", encoding="utf-8") if not l.startswith("#"))]
    cache, out = {}, []
    for i, v in enumerate(rows):
        o = cache.setdefault(v["report"], json.loads((CH / "out_step4" / f"{v['report']}.json").read_text(encoding="utf-8")))
        page = next(p for p in o["pages"] if p["page"] == int(v["page"]))
        want = re.sub(r"[^\d.]", "", v["value"])
        cand = [r for r in page["rows"] if r.get("via") == "columns" and r.get("values")
                and re.sub(r"[^\d.]", "", str(r["values"][0])) == want]
        cand.sort(key=lambda r: not r["label"].startswith(v["label"][:30]))
        if not cand:
            print("not found:", v["report"], v["page"], v["value"]); continue
        out.append({"tid": i, "verdict": v, "row": cand[0], "page": page, "pdf": o["pdf"], "fy": o["fy"]})
    return out


def block_rows(page, block):
    rs = [r for r in page["rows"] if r.get("via") == "columns" and r["block"] == block]
    return sorted(rs, key=lambda r: (r["row"], r["col"]))


def page_text(pdf, pno, cache={}):
    if pdf not in cache:
        cache[pdf] = pymupdf.open(pdf)
    return cache[pdf][pno - 1].get_text()[:6000]


def build(group, variant):
    t0 = group[0]; page = t0["page"]
    rs = block_rows(page, t0["row"]["block"])[:80]
    ids = {id(r): n for n, r in enumerate(rs)}
    lines = [f"{n} | {r['label'][:90]} | {(r.get('column') or '')[:60]} | {r.get('period')} | {r.get('unit')} | {r['values'][0]}"
             for n, r in enumerate(rs)]
    targets = []
    for t in group:
        n = next((ids[id(r)] for r in rs if r is t["row"]), None)
        if n is None:   # target row beyond the 80-row cap: append it
            n = len(lines); lines.append(f"{n} | {t['row']['label'][:90]} | {(t['row'].get('column') or '')[:60]} | "
                                         f"{t['row'].get('period')} | {t['row'].get('unit')} | {t['row']['values'][0]}")
        t["rid"] = n; targets.append(str(n))
    pt = f"\nPage text (layer may be jumbled):\n<<<\n{page_text(t0['pdf'], page['page'])}\n>>>\n" if variant == "v2" else ""
    return PROMPT.format(fy_end=f"{t0['fy']}-03-31", page=page["page"], unit=page.get("unit"), scope=page.get("scope"),
                         rows="\n".join(lines), page_text=pt, targets=", ".join(targets))


def run(variants, model):
    env = frt.user_env()
    targets = load_targets()
    groups = defaultdict(list)
    for t in targets:
        groups[(t["verdict"]["report"], t["page"]["page"], t["row"]["block"])].append(t)
    jobs = [(v, k, g) for v in variants for k, g in groups.items()]
    print(f"{len(targets)} target rows in {len(groups)} table blocks; {len(jobs)} calls")

    def one(job):
        v, k, g = job
        f = OUT / model / v / f"{k[0]}_{k[1]}_{k[2]}.json"
        prompt = build(g, v)
        if f.exists():
            return None
        f.parent.mkdir(parents=True, exist_ok=True)
        res = frt.call(frt.READERS[model], prompt, env)
        res["targets"] = {t["tid"]: t["rid"] for t in g}
        f.write_text(json.dumps(res, indent=1), encoding="utf-8")
        return f"{v} {k}: " + (res.get("error") or f"{res['seconds']}s in {res['in_tok']} out {res['out_tok']}")

    with ThreadPoolExecutor(6) as ex:
        for msg in ex.map(one, jobs):
            if msg:
                print(msg, flush=True)


def parse(text):
    out = {}
    for line in text.splitlines():
        line = line.strip().strip(",")
        if line.startswith("{"):
            try:
                o = json.loads(line); out[int(o["id"])] = o
            except (ValueError, KeyError, json.JSONDecodeError):
                pass
    return out


def table(model):
    targets = {t["tid"]: t for t in load_targets()}
    md = ["# Row clean-up test: side by side", "",
          "| set | report p. | parser: label / unit / period | verdict, suggested fix | V1 label / unit / period / keep | V2 label / unit / period / keep |",
          "|---|---|---|---|---|---|"]
    got = {"v1": {}, "v2": {}}
    for v in got:
        for f in (OUT / model / v).glob("*.json"):
            res = json.loads(f.read_text(encoding="utf-8"))
            ans = parse(res.get("text", ""))
            for tid, rid in res.get("targets", {}).items():
                got[v][int(tid)] = ans.get(rid)
    for tid, t in sorted(targets.items()):
        r, vd = t["row"], t["verdict"]
        cell = lambda a: "-" if not a else f"{a.get('label')} / {a.get('unit')} / {a.get('period_end')} / {'keep' if a.get('keep') else 'DROP'}"
        md.append(f"| {vd['set']} | {vd['report']} {vd['page']} | {r['label'][:60]} / {r.get('unit')} / {r.get('period')} | "
                  f"{vd['verdict']}: {vd['suggested_fix'][:70]} | {cell(got['v1'].get(tid))} | {cell(got['v2'].get(tid))} |")
    (HERE / "row_cleanup_results.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "table"])
    ap.add_argument("--variants", default="v1,v2")
    ap.add_argument("--model", default="longcat")
    a = ap.parse_args()
    run(a.variants.split(","), a.model) if a.cmd == "run" else table(a.model)
