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
import re
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


CLOUD_CLAIM = "claude cloud claim "   # pages.error while a cloud Haiku batch holds a deferred page (deferred_pages skips it)


def export_deferred(n_pages, per_agent, out_root=None):
    """Deferred second-reading pages (pages.error = SECOND_DEFERRED), oldest decks first, for a Claude Code CLOUD session
    on Haiku (2026-10-13: Shivam's $99 cloud-session credit). Claims each page (pages.error = CLOUD_CLAIM + run) so the deck
    job skips it from its next restart; import-deferred stores Haiku's reading as the page's final reading, and
    release-deferred hands unanswered pages back. Writes the same bNNN/<k>_image.jpg + <k>_prompt.txt layout as export."""
    import pymupdf
    store = x.Store(x.OUT_DB)
    deferred = store.deferred_pages()
    paths = dict(store.query("SELECT sha256, local_path FROM deck_sources"))
    meta = {r[0]: r[1:] for r in store.query("SELECT sha256, symbol, symbol, known_at FROM deck_sources")}
    run_name = datetime.now().strftime("cloud_%Y%m%d_%H%M%S")
    run = Path(out_root or QUEUE) / run_name
    run.mkdir(parents=True)
    manifest, k = [], 0
    for sha in sorted(deferred, key=lambda s: str(meta.get(s, ("", "", ""))[2] or "")):   # oldest decks first
        path = paths.get(sha)
        if not path or not Path(path).exists():
            continue
        try:
            doc = pymupdf.open(path)
        except Exception:
            continue
        sym, comp, known = meta.get(sha, ("", "", ""))
        for pg in sorted(deferred[sha]):
            if pg > len(doc):
                continue
            page = doc[pg - 1]
            task = x.page_task({"sha256": sha, "symbol": sym, "company": comp or sym, "known_at": known, "local_path": path}, page, pg)
            task.update(sha256=sha, page_no=pg, symbol=sym, known_at=known)
            b = run / f"b{k // per_agent:03d}"; b.mkdir(exist_ok=True)
            (b / f"{k:05d}_image.jpg").write_bytes(base64.b64decode(x.render_jpeg_b64(page)))
            (b / f"{k:05d}_prompt.txt").write_text(x.build_prompt(task), encoding="utf-8")
            store.execute("UPDATE pages SET error=? WHERE sha256=? AND page_no=? AND prompt_version=?",
                          (CLOUD_CLAIM + run_name, sha, pg, x.PROMPT_VERSION))
            manifest.append({"k": k, "folder": b.name, **{a: (sorted(v) if isinstance(v, set) else v) for a, v in task.items()}})
            k += 1
            if k >= n_pages:
                break
        doc.close()
        if k >= n_pages:
            break
    (run / "manifest.json").write_text(json.dumps(manifest, default=str), encoding="utf-8")
    print(json.dumps({"run": str(run), "pages": k, "folders": len({m['folder'] for m in manifest})}))


CLOUD_TASK = """# Cloud task: re-read {pages} hard deck pages with Claude Haiku 5.5

Pages where the deck pipeline's first and second readings DISAGREE (under {min_j:.0%} of numbers in common). Folders
`b000` ... `b{last:03d}` each hold up to {per_agent} pairs `NNNNN_image.jpg` + `NNNNN_prompt.txt`.

## Context budget (hard rule: every model call must stay under 100K tokens of context; above that Haiku bills 5x)

- You (the orchestrator) NEVER open, read or list the contents of images, prompts or answer files. You only launch agents
  and read their one-line replies. Your own context must stay small: launch agents in parallel waves of up to 10 per
  message, and do not repeat instructions back.
- One helper agent per folder, model **haiku**, with exactly this prompt:
  "Follow {instructions_path} for the folder {{folder}}. Read the pairs one at a time. Write each answer file, do not
  re-open files you already handled, do not explain. Reply with one line: how many files you wrote."
- Do not give an agent more than one folder. Do not resume or message an agent after it replies.

## Steps

1. Read `{instructions_path}` once (it is short).
2. Launch the agents in waves of 10 (folders in order) until every folder has an agent.
3. When all have replied, check that every folder has a `.txt` for each image (count files with one shell command;
   do not open them). Re-launch an agent only for folders with missing answers.
4. Commit all `.txt` answer files to this branch and push. Reply with the number of answers written.
"""


def export_hard(n_pages, per_agent, out_root=None, min_j=0.5, select="disagree"):
    """Deck pages whose two best readings disagree (Jaccard of their number sets < min_j), most-disagreeing first, for a
    Claude Code CLOUD session on Haiku (2026-10-14, Shivam: spend the cloud credit on second-reading disagreements).
    Claims each page (pages.error = CLOUD_CLAIM + run; the page's previous error is kept in the manifest and restored if
    unanswered). Writes CLOUD_TASK.md with the context-budget rules (agents of <= per_agent slides stay under 100K)."""
    import collections
    import pymupdf
    store = x.Store(x.OUT_DB)
    vals = collections.defaultdict(lambda: collections.defaultdict(set))
    for s, p, m, v in store.query(
            """SELECT f.sha256, f.page_no, f.model, ROUND(ABS(f.value), 4) FROM facts f JOIN
               (SELECT sha256, page_no FROM outputs WHERE prompt_version=? GROUP BY 1, 2 HAVING COUNT(DISTINCT model) >= 2) m
               ON f.sha256 = m.sha256 AND f.page_no = m.page_no WHERE f.value IS NOT NULL AND f.prompt_version=?""",
            (x.PROMPT_VERSION, x.PROMPT_VERSION)):
        vals[(s, p)][m].add(v)
    claimed = {(r[0], r[1]) for r in store.query("SELECT sha256, page_no FROM pages WHERE error LIKE ?", (CLOUD_CLAIM + "%",))}
    done_by_claude = {(r[0], r[1]) for r in store.query("SELECT sha256, page_no FROM pages WHERE final_model=?", (MODEL,))}
    hard = []
    if select == "nofig":   # 2026-10-15: pages the free readers left with NO figures although the text layer has numbers
        vals = {}
        for sha, pg, tn in store.query("""SELECT sha256, page_no, text_numbers FROM pages WHERE prompt_version=? AND status='ok'
                AND n_facts=0 AND COALESCE(final_model,'') != ? AND text_numbers >= 5""", (x.PROMPT_VERSION, MODEL)):
            if (sha, pg) not in claimed:
                hard.append((-tn, (sha, pg)))   # most numbers first
    for key, ms in vals.items():
        if key in claimed or key in done_by_claude or MODEL in ms:
            continue
        sets = sorted(ms.values(), key=len, reverse=True)
        if len(sets) < 2:
            continue
        j = len(sets[0] & sets[1]) / max(1, len(sets[0] | sets[1]))
        if j < min_j:
            hard.append((j, key))
    hard.sort()
    paths = dict(store.query("SELECT sha256, local_path FROM deck_sources"))
    meta = {r[0]: r[1:] for r in store.query("SELECT sha256, symbol, symbol, known_at FROM deck_sources")}
    run_name = datetime.now().strftime("cloud_hard_%Y%m%d_%H%M%S")
    run = Path(out_root or QUEUE) / run_name
    run.mkdir(parents=True)
    manifest, k = [], 0
    for j, (sha, pg) in hard:
        path = paths.get(sha)
        if not path or not Path(path).exists():
            continue
        try:   # open per page and close at once: keeping every PDF open failed silently after ~800 (2026-10-15)
            doc = pymupdf.open(path)
        except Exception:
            continue
        if pg > len(doc):
            doc.close(); continue
        sym, comp, known = meta.get(sha, ("", "", ""))
        page = doc[pg - 1]
        task = x.page_task({"sha256": sha, "symbol": sym, "company": comp or sym, "known_at": known, "local_path": path}, page, pg)
        task.update(sha256=sha, page_no=pg, symbol=sym, known_at=known)
        prev = store.query("SELECT error FROM pages WHERE sha256=? AND page_no=? AND prompt_version=?", (sha, pg, x.PROMPT_VERSION))
        b = run / f"b{k // per_agent:03d}"; b.mkdir(exist_ok=True)
        (b / f"{k:05d}_image.jpg").write_bytes(base64.b64decode(x.render_jpeg_b64(page)))
        (b / f"{k:05d}_prompt.txt").write_text(x.build_prompt(task), encoding="utf-8")
        store.execute("UPDATE pages SET error=? WHERE sha256=? AND page_no=? AND prompt_version=?",
                      (CLOUD_CLAIM + run_name, sha, pg, x.PROMPT_VERSION))
        manifest.append({"k": k, "folder": b.name, "jaccard": round(j, 3), "prev_error": prev[0][0] if prev else None,
                         **{a: (sorted(v) if isinstance(v, set) else v) for a, v in task.items()}})
        doc.close()
        k += 1
        if k >= n_pages:
            break
    (run / "manifest.json").write_text(json.dumps(manifest, default=str), encoding="utf-8")
    (run / "AGENT_INSTRUCTIONS.md").write_text((QUEUE / "AGENT_INSTRUCTIONS.md").read_text(encoding="utf-8"), encoding="utf-8")
    folders = len({m["folder"] for m in manifest})
    # paths relative to the repo root the cloud session starts in (out_root is <worktree>/cloud_batches)
    rel = f"{Path(out_root).name}/{run_name}" if out_root else run_name
    task = CLOUD_TASK.format(pages=k, min_j=min_j, last=max(0, folders - 1), per_agent=per_agent,
                             instructions_path=f"{rel}/AGENT_INSTRUCTIONS.md")
    task = task.replace("Folders\n`b000`", f"Folders\n`{rel}/b000`").replace("for the folder {folder}", f"for the folder {rel}/<bNNN>")
    (run / "CLOUD_TASK.md").write_text(task, encoding="utf-8")
    if out_root:   # also at the repo root, where the session is told to look
        (Path(out_root).parent / "CLOUD_TASK.md").write_text(task, encoding="utf-8")
    print(json.dumps({"run": str(run), "pages": k, "folders": folders, "hard_pages_left": len(hard) - k}))


def import_deferred(run):
    """Haiku's answers from a cloud batch: final reading of each answered page; unanswered pages go back to deferred."""
    run = Path(run)
    store = x.Store(x.OUT_DB)
    manifest = json.loads((run / "manifest.json").read_text(encoding="utf-8"))
    ok = back = 0
    for m in manifest:
        task = {**m, "truth": set(m.get("truth", []))}
        row = store.query("SELECT doc_id, isin, symbol, doc_type, known_at FROM pages WHERE sha256=? AND page_no=? AND prompt_version=?",
                          (m["sha256"], m["page_no"], x.PROMPT_VERSION))
        if row:   # the page's stored identity (export did not record doc_id/isin/doc_type)
            task.update(dict(zip(("doc_id", "isin", "symbol", "doc_type", "known_at"), row[0])))
        out_f = run / m["folder"] / f"{m['k']:05d}.txt"
        if not out_f.exists():   # unanswered: back to its previous state (export-hard records it; deferred pages had none)
            store.execute("UPDATE pages SET error=? WHERE sha256=? AND page_no=? AND prompt_version=? AND error LIKE ?",
                          (m.get("prev_error", x.SECOND_DEFERRED), m["sha256"], m["page_no"], x.PROMPT_VERSION, CLOUD_CLAIM + "%"))
            back += 1; continue
        out = out_f.read_text(encoding="utf-8")
        facts = x.parse_facts(out)
        reading = {"output": out, "seconds": 0, "in_tok": 0, "out_tok": 0, "usd": 0.0, "facts": facts}
        store.save_page(task, {"readings": {MODEL: reading}, "final_model": MODEL, "status": "ok",
                               "primary_recall": x.recall(x.fact_numbers(facts), task["truth"]), "n_facts": len(facts)})
        store.execute("UPDATE pages SET error=NULL WHERE sha256=? AND page_no=? AND prompt_version=?", (m["sha256"], m["page_no"], x.PROMPT_VERSION))
        ok += 1
    print(json.dumps({"run": str(run), "imported": ok, "returned_to_deferred": back, "chart_trends": refresh_chart_trends(store)}))


def refresh_chart_trends(store):
    """`CHART | measure | span | trend` lines from Haiku readings (charts without printed values; AGENT_INSTRUCTIONS from
    2026-10-15) into table chart_trends: trend evidence without invented figures (Shivam: keep these charts)."""
    store.execute("""CREATE TABLE IF NOT EXISTS chart_trends (sha256 TEXT, page_no INT, symbol TEXT, isin TEXT, known_at TEXT,
        measure TEXT, span TEXT, trend TEXT, model TEXT, PRIMARY KEY (sha256, page_no, measure))""")
    rows = []
    for sha, pg, out, sym, isin, known in store.query(
            """SELECT o.sha256, o.page_no, o.raw_output, p.symbol, p.isin, p.known_at FROM outputs o JOIN pages p
               ON p.sha256 = o.sha256 AND p.page_no = o.page_no WHERE o.model = ? AND o.raw_output LIKE '%CHART |%'""", (MODEL,)):
        for line in out.splitlines():
            m = re.match(r"\s*CHART\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|\s*(.*)$", line)
            if m:
                rows.append((sha, pg, sym, isin, known, m.group(1), m.group(2), m.group(3), MODEL))
    for r in rows:
        store.execute("INSERT OR REPLACE INTO chart_trends VALUES (?,?,?,?,?,?,?,?,?)", r)
    return len(rows)


def status():
    store = x.Store(x.OUT_DB)
    print(store.query("SELECT status, COUNT(*) FROM pages WHERE prompt_version=? GROUP BY 1", (x.PROMPT_VERSION,)))
    print(store.query("SELECT final_model, COUNT(*) FROM pages WHERE prompt_version=? AND status='ok' GROUP BY 1", (x.PROMPT_VERSION,)))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["export", "import", "status", "export-deferred", "import-deferred", "export-hard"])
    ap.add_argument("--select", choices=["disagree", "nofig"], default="disagree", help="export-hard: disagreeing readings, or pages with no figures but text-layer numbers")
    ap.add_argument("--min-j", type=float, default=0.5, help="export-hard: pages whose two readings share fewer numbers than this")
    ap.add_argument("--out-root", help="export-deferred: folder for the run (e.g. a repo folder pushed for a cloud session)")
    ap.add_argument("--pages", type=int, default=150)
    ap.add_argument("--per-agent", type=int, default=15)
    ap.add_argument("--run")
    a = ap.parse_args()
    if a.what == "export":
        export(a.pages, a.per_agent)
    elif a.what == "import":
        do_import(a.run)
    elif a.what == "export-deferred":
        export_deferred(a.pages, a.per_agent, a.out_root)
    elif a.what == "export-hard":   # import with import-deferred
        export_hard(a.pages, a.per_agent, a.out_root, a.min_j, a.select)
    elif a.what == "import-deferred":
        import_deferred(a.run)
    else:
        status()


if __name__ == "__main__":
    main()
