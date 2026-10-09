"""
Hand-off between the deck-figure database and Claude Code helper agents (Claude Haiku 5.5), which cannot be called
from extract_deck_figures.py the way the API readers are.

  export: claims unread deck pages, oldest decks first (the extractor works newest first, so the two meet in the
          middle and never read the same page), renders each in an isolated child process, and writes
          <queue>/<run>/bNNN/<k>_image.jpg + <k>_prompt.txt (the production prompt, text layer included), one folder
          per agent. Claimed pages are marked status='claimed' in deck_figures.db; the extractor leaves them alone for
          CLAIM_HOURS, after which unanswered pages fall back to it.
  agents: each reads its folder and writes <k>.txt next to the inputs (the answer lines only).
  import: parses every <k>.txt into outputs/facts/pages as model claude-haiku-5-5 and marks it final; pages without an
          answer are set to 'error' so the extractor picks them up on its next pass.

Quality gate passed 2026-10-09 (40-page test): 100% of figures identifiable, units filled 90.8%, no misread numbers,
both hand-checked slides fully correct.

Usage:
    python -m reality_engine.scripts.claude_page_queue export --pages 150 --per-agent 15
    python -m reality_engine.scripts.claude_page_queue import --run <run folder>
    python -m reality_engine.scripts.claude_page_queue status
"""

import argparse
import base64
import json
import time
from datetime import datetime
from pathlib import Path

from reality_engine.scripts import extract_deck_figures as x

QUEUE = x.DATA / "claude_queue"
MODEL = "claude-haiku-5-5"


def export(n_pages, per_agent):
    store = x.Store(x.OUT_DB)
    done = store.done_keys()
    bad = {r[0] for r in store.query("SELECT sha256 FROM bad_docs WHERE strikes >= ?", (x.MAX_STRIKES,))}
    complete = store.complete_docs()
    docs = [d for d in reversed(x.load_docs(["INVESTOR_PRESENTATION"], [], 0)) if d["sha256"] not in bad and d["sha256"] not in complete]
    run = QUEUE / datetime.now().strftime("run_%Y%m%d_%H%M%S")
    run.mkdir(parents=True)
    done_pages = {}
    for sha, pg in done:
        done_pages.setdefault(sha, set()).add(pg)
    manifest, k = [], 0
    renderer = x.Renderer(store)
    try:
        for d, n, pages in renderer.run(docs, lambda d: done_pages.get(d["sha256"], set())):
            store.execute("INSERT OR REPLACE INTO doc_pages VALUES (?,?)", (d["sha256"], n))
            for t in pages:
                task = {**d, **{a: b for a, b in t.items() if a != "jpeg"}}
                if task["route"].startswith("skip"):
                    store.save_page(task, {"status": "skipped"}); continue
                b = run / f"b{k // per_agent:03d}"; b.mkdir(exist_ok=True)
                (b / f"{k:05d}_image.jpg").write_bytes(base64.b64decode(t["jpeg"]))
                (b / f"{k:05d}_prompt.txt").write_text(x.build_prompt(task), encoding="utf-8")
                store.save_page(task, {"status": "claimed"})
                manifest.append({"k": k, "folder": b.name, **{a: (sorted(v) if isinstance(v, set) else v) for a, v in task.items()}})
                k += 1
                if k >= n_pages:
                    break
            if k >= n_pages:
                break
    finally:
        renderer.close()
    (run / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    folders = sorted({m["folder"] for m in manifest})
    print(json.dumps({"run": str(run), "pages": k, "folders": folders}))


def do_import(run):
    run = Path(run)
    store = x.Store(x.OUT_DB)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    ok = missing = 0
    for m in manifest:
        task = {**m, "truth": set(m["truth"])}
        out_f = run / m["folder"] / f"{m['k']:05d}.txt"
        if not out_f.exists():
            store.save_page(task, {"status": "error", "error": "claude queue: no answer"}); missing += 1; continue
        out = out_f.read_text(encoding="utf-8")
        facts = x.parse_facts(out)
        reading = {"output": out, "seconds": 0, "in_tok": 0, "out_tok": 0, "usd": 0.0, "facts": facts}
        store.save_page(task, {"readings": {MODEL: reading}, "final_model": MODEL, "status": "ok",
                               "primary_recall": x.recall(x.fact_numbers(facts), task["truth"]), "n_facts": len(facts)})
        ok += 1
    print(json.dumps({"run": str(run), "imported": ok, "missing": missing}))


def status():
    store = x.Store(x.OUT_DB)
    print(store.query("SELECT status, COUNT(*) FROM pages WHERE prompt_version=? GROUP BY 1", (x.PROMPT_VERSION,)))
    print(store.query("SELECT final_model, COUNT(*) FROM pages WHERE prompt_version=? AND status='ok' GROUP BY 1", (x.PROMPT_VERSION,)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["export", "import", "status"])
    ap.add_argument("--pages", type=int, default=150)
    ap.add_argument("--per-agent", type=int, default=15)
    ap.add_argument("--run")
    a = ap.parse_args()
    if a.what == "export":
        export(a.pages, a.per_agent)
    elif a.what == "import":
        do_import(a.run)
    else:
        status()


if __name__ == "__main__":
    main()
