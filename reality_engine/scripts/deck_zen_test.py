"""40-page deck reader test for OpenCode Zen free models (they answer only inside OpenCode, so each page is one
`opencode run` with the slide image and its prompt attached). Same pages, prompt and scoring as reader_quality_test.py
(pass: identifiable >= ~85%, zero misread numbers, >= 95% answered).

  python -m reality_engine.scripts.deck_zen_test --models step-5-preview-free,longcat-2.5-preview-free --workers 1
Outputs: reality_engine/data/reader_tests/<date>-zen/ (answers/<model>/*.json, report.md)
"""
import argparse
import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pymupdf

from reality_engine.scripts import extract_deck_figures as x
from reality_engine.scripts import reader_quality_test as q
from reality_engine.scripts.ar_queue import ANSI, opencode_exe

OUT = x.OUT_DB.parent / "reader_tests" / f"{date.today().isoformat()}-zen"
ASK = ("Read the attached slide image and follow the instructions in the attached text file exactly. "
       "Do not use any tools. Reply with the requested output only.")


def call(exe, model, prompt_file, img, timeout=600):
    t = time.time()
    p = subprocess.run([exe, "run", "-m", f"opencode/{model}", "--title", f"deck-test {model} {img.stem}", ASK,
                        "-f", str(prompt_file), "-f", str(img)], cwd=OUT, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout)
    out = "\n".join(l for l in ANSI.sub("", p.stdout).splitlines() if not l.startswith("> ")).strip()
    return {"output": out, "seconds": round(time.time() - t, 1), "rc": p.returncode, "stderr": ANSI.sub("", p.stderr)[-400:]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--models", required=True)
    ap.add_argument("--workers", type=int, default=1, help="pages in flight per model")
    a = ap.parse_args()
    models = a.models.split(",")
    exe = opencode_exe()
    OUT.mkdir(parents=True, exist_ok=True)
    pages = []
    for pg in q.pick_pages():
        doc = pymupdf.open(pg["path"]); page = doc[pg["page_no"] - 1]
        task = x.page_task({"symbol": pg["symbol"], "company": pg["symbol"], "known_at": pg["known_at"]}, page, pg["page_no"])
        stem = f"{pg['symbol']}_{pg['sha256'][:8]}_p{pg['page_no']}"
        img = OUT / f"{stem}.png"
        if not img.exists():
            page.get_pixmap(matrix=pymupdf.Matrix(1.6, 1.6)).save(str(img))
        pf = OUT / f"{stem}.prompt.txt"
        pf.write_text(x.build_prompt(task), encoding="utf-8")
        pages.append((pg, task, img, pf))

    def one(job):
        m, (pg, task, img, pf) = job
        f = OUT / "answers" / m / f"{img.stem}.json"
        if f.exists():
            r = json.loads(f.read_text(encoding="utf-8"))
            if x.parse_facts(r.get("output", "")):
                return m, pg, task, r
        f.parent.mkdir(parents=True, exist_ok=True)
        r = {}
        for _ in range(2):
            try:
                r = call(exe, m, pf, img)
            except Exception as e:
                r = {"error": str(e)[:300]}
            if x.parse_facts(r.get("output", "")):
                break
            time.sleep(10)
        f.write_text(json.dumps(r), encoding="utf-8")
        print(f"{m} {img.stem}: {r.get('seconds')}s facts={len(x.parse_facts(r.get('output', '')))}", flush=True)
        return m, pg, task, r

    jobs = [(m, p) for p in pages for m in models]   # interleaved: every model gets pages from the start
    with ThreadPoolExecutor(a.workers * len(models)) as ex:
        res = list(ex.map(one, jobs))

    md = [f"# Deck reader test via OpenCode Zen, {date.today()} ({len(pages)} pages, reference: Claude Haiku 5.5 + text layer)", "",
          "| model | answered | figures | identifiable | Haiku's numbers found | unsupported numbers | median s |",
          "|---|---|---|---|---|---|---|"]
    detail = []
    for m in models:
        facts_all, found, refn_all, unsup, secs, ok = [], 0, 0, [], [], 0
        for mm, pg, task, r in res:
            if mm != m:
                continue
            f = x.parse_facts(r.get("output", ""))
            if not f:
                continue
            ok += 1; facts_all += f; secs.append(r.get("seconds", 0))
            refn = q.numbers(x.parse_facts(pg["ref"])); got = q.numbers(f); truth = {round(abs(v), 4) for v in task["truth"]}
            found += len(refn & got); refn_all += len(refn)
            unsup += [(pg["symbol"], pg["page_no"], v) for v in sorted(got - refn - truth)]
        secs.sort()
        md.append(f"| {m} | {ok}/{len(pages)} | {len(facts_all)} | {x.identifiable_share(facts_all) or 0:.1%} | "
                  f"{found}/{refn_all} ({found / max(1, refn_all):.0%}) | {len(unsup)} | {secs[len(secs) // 2] if secs else '-'} |")
        detail += ["", f"## {m}: unsupported numbers (check on the page image)"] + [f"- {s} p{p}: {v}" for s, p, v in unsup[:80]]
    (OUT / "report.md").write_text("\n".join(md + detail) + "\n", encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
