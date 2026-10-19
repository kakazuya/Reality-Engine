"""Annual-report work queue for readers that only answer inside the OpenCode app (OpenCode Zen free models).

The Python run (ingest_annual_reports.py: OpenCode Go LongCat + Gemma) reads reports newest-first. This queue hands
reports oldest-first to OpenCode sessions, which read the pieces with their own subagents, then imports the answers into
the same tables (ar_docs / ar_pieces / ar_facts) with the same checks. A claim in ar_claims keeps the two apart: the
Python run skips any report claimed here, and export skips any report the Python run has started.
Handbook: tasks/OPENCODE_AR_HANDBOOK.md.

  python -m reality_engine.scripts.ar_queue export --run zen01 --docs 3 --model longcat-2.5-preview-free
  python -m reality_engine.scripts.ar_queue import --run zen01
  python -m reality_engine.scripts.ar_queue test-export --run t-mimo --model mimo-v2.6-flash-free
  python -m reality_engine.scripts.ar_queue test-score --run t-mimo
  python -m reality_engine.scripts.ar_queue status
Hard reports (> 10% of numbers not found in the text; Claude Haiku helper agents re-read them, tasks/HARD_AR_HAIKU_SESSION.md):
  python -m reality_engine.scripts.ar_queue diagnose --doc-ids hard          # cause per report -> ar_queue/hard_diagnosis.csv
  python -m reality_engine.scripts.ar_queue recheck --doc-ids hard --write    # re-run value_check with the current rules
  python -m reality_engine.scripts.ar_queue export-docs --run h01 --doc-ids 63537 --misses-only
  python -m reality_engine.scripts.ar_queue missing --run h01                 # folders still without answers
  python -m reality_engine.scripts.ar_queue import-docs --run h01 [--dry]
Run folders: reality_engine/data/ar_queue/<run>/ (manifest.json, NNNN.prompt.txt from export, NNNN.out.txt from readers).
"""
import argparse
import collections
import functools
import json
import re
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

from reality_engine.scripts import ingest_annual_reports as ar
from reality_engine.scripts.go_session import session_id   # stable x-opencode-session (Shivam's rule 2026-10-20)

QUEUE = ar.DATA / "ar_queue"
STUDY_TEST = ar.ROOT / "tasks" / "ar_study" / "free_test"
MAX_LINES = 1800          # OpenCode's read tool returns 2000 lines per call; keep a piece readable in one call
CLAIM_HOURS = 72
DEPTH_MIN = 4500          # admission depth rule (2026-10-13): half the median facts of passed models on the 110 test pieces
                          # (Space Bunny 9,872, Big Pickle 9,459, Muse 1.3 5,080); Flash-Lite 3.1 hit 25/25 with only 1,189          # an unimported claim older than this is free again
CLAIMS = """CREATE TABLE IF NOT EXISTS ar_claims (doc_id INTEGER PRIMARY KEY, owner TEXT, run TEXT, model TEXT, ts TEXT,
  status TEXT)"""   # status: claimed | imported


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect():
    con = sqlite3.connect(ar.OUT_DB, timeout=120)
    con.execute("PRAGMA journal_mode=WAL"); con.executescript(ar.SCHEMA); con.execute(CLAIMS)
    return con


def claimed_elsewhere(con, doc_id):
    """Used by ingest_annual_reports.py: True when an OpenCode run holds a live claim on this report."""
    con.execute(CLAIMS)
    r = con.execute("SELECT ts, status FROM ar_claims WHERE doc_id=?", (doc_id,)).fetchone()
    if not r:
        return False
    return r[1] == "imported" or r[0] >= (datetime.now() - timedelta(hours=CLAIM_HOURS)).isoformat(timespec="seconds")


def claim_for_zen(con, doc_id, run, model, owner="opencode-zen"):
    """ingest_annual_reports.py --route zen: claim a report atomically. True when it is ours to read (new claim, or our
    own earlier claim, e.g. after a restart); False when the Python run has started it or it is otherwise taken."""
    con.execute(CLAIMS)
    con.execute("BEGIN IMMEDIATE")
    try:
        r = con.execute("SELECT owner FROM ar_claims WHERE doc_id=?", (doc_id,)).fetchone()
        if r and r[0] == owner:
            con.execute("UPDATE ar_claims SET ts=? WHERE doc_id=?", (now(), doc_id)); con.execute("COMMIT"); return True
        if r or con.execute("SELECT 1 FROM ar_docs WHERE doc_id=?", (doc_id,)).fetchone():
            con.execute("ROLLBACK"); return False
        con.execute("INSERT INTO ar_claims VALUES (?,?,?,?,?,?)", (doc_id, owner, run, model, now(), "claimed"))
        con.execute("COMMIT"); return True
    except Exception:
        con.execute("ROLLBACK"); raise


def split_long(pieces):
    """Cut pieces further at page boundaries so each prompt file stays under MAX_LINES lines."""
    out = []
    for p_from, p_to, text in pieces:
        if text.count("\n") <= MAX_LINES:
            out.append((p_from, p_to, text)); continue
        pages = re.split(r"(?==== PAGE \d+ ===)", text)
        buf = ""
        for pg in (x for x in pages if x):
            if buf and buf.count("\n") + pg.count("\n") > MAX_LINES:
                nums = [int(n) for n in re.findall(r"=== PAGE (\d+) ===", buf)]
                out.append((min(nums), max(nums), buf)); buf = ""
            buf += "\n".join(pg.split("\n")[:MAX_LINES])
        if buf.strip():
            nums = [int(n) for n in re.findall(r"=== PAGE (\d+) ===", buf)]
            out.append((min(nums), max(nums), buf))
    return out


def write_piece(run_dir, n, prompt):
    f = run_dir / f"{n:04d}.prompt.txt"
    f.write_text(prompt, encoding="utf-8")
    return f.name


def export(run, n_docs, model, owner):
    run_dir = QUEUE / run
    if (run_dir / "manifest.json").exists():
        sys.exit(f"run {run} exists; import it or pick a new run name")
    con = connect()
    docs = list(reversed(ar.inventory()))          # oldest filing first (the Python run goes newest-first)
    started = {r[0] for r in con.execute("SELECT doc_id FROM ar_docs")}
    picked, pieces = [], []
    run_dir.mkdir(parents=True)
    for d in docs:
        if len(picked) >= n_docs:
            break
        if d["doc_id"] in started or claimed_elsewhere(con, d["doc_id"]):
            continue
        con.execute("BEGIN IMMEDIATE")              # claim atomically: parallel sessions never get the same report
        if claimed_elsewhere(con, d["doc_id"]) or con.execute("SELECT 1 FROM ar_docs WHERE doc_id=?", (d["doc_id"],)).fetchone():
            con.execute("ROLLBACK"); continue
        con.execute("INSERT OR REPLACE INTO ar_claims VALUES (?,?,?,?,?,?)", (d["doc_id"], owner, run, model, now(), "claimed"))
        con.execute("COMMIT")
        try:
            n_pages, n_text, ps = ar.pieces_of(d["path"])
        except Exception as e:
            con.execute("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                         d["filed_at_source"], d["sha256"], d["path"], None, None, 0, "unreadable", str(e)[:200], now()))
            con.execute("UPDATE ar_claims SET status='imported' WHERE doc_id=?", (d["doc_id"],)); con.commit()
            continue
        ps = split_long(ps)
        d.update(n_pages=n_pages, n_text=n_text, n_pieces=len(ps))
        picked.append(d)
        for k, (p_from, p_to, text) in enumerate(ps):
            prompt = ar.PROMPT.format(company=d["company"], symbol=d["symbol"], filed=str(d["filed_at"])[:10], text=text)
            pieces.append({"file": write_piece(run_dir, len(pieces) + 1, prompt), "doc_id": d["doc_id"], "piece": k,
                           "page_from": p_from, "page_to": p_to})
    manifest = {"run": run, "model": model, "owner": owner, "created": now(), "docs": picked, "pieces": pieces}
    (run_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"run {run}: {len(picked)} reports, {len(pieces)} pieces -> {run_dir}")
    for d in picked:
        print(f"  {d['doc_id']} {d['symbol']} FY {d['fiscal_year'][:4]} filed {str(d['filed_at'])[:10]}: {d['n_pieces']} pieces")


def piece_text(prompt):
    return prompt.split("\nTEXT:\n", 1)[1]


def do_import(run):
    run_dir = QUEUE / run
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    con = connect()
    reader = f"zen:{m['model']}"
    docs = {d["doc_id"]: d for d in m["docs"]}
    got = missing = facts_n = 0
    for p in m["pieces"]:
        out_f = run_dir / p["file"].replace(".prompt.txt", ".out.txt")
        if not out_f.exists():
            missing += 1; continue
        d = docs[p["doc_id"]]
        text = piece_text((run_dir / p["file"]).read_text(encoding="utf-8"))
        out = out_f.read_text(encoding="utf-8", errors="replace")
        page_text = {int(g.group(1)): g.group(2) for g in re.finditer(r"=== PAGE (\d+) ===\n(.*?)(?=\n=== PAGE |\Z)", text, re.S)}
        facts = ar.parse_lines(out)
        rows = []
        for f in facts:
            pg = int(f["page"]) if str(f.get("page", "")).isdigit() else None
            rows.append((d["doc_id"], p["piece"], d["isin"], d["symbol"], d["fiscal_year"], d["filed_at"], pg,
                         str(f.get("category") or "")[:80], str(f.get("item") or "")[:500],
                         None if f.get("value") is None else str(f["value"])[:60], ar.to_number(f.get("value")),
                         str(f.get("unit") or "")[:40], str(f.get("period") or "")[:40], str(f.get("basis") or "")[:20],
                         str(f.get("quote") or "")[:300], reader, ar.value_check(f.get("value"), page_text.get(pg), text),
                         ar.PROMPT_VERSION))
        # an answer with no JSON line is fine only when the reader says so ("NONE"); anything else is an error
        err = None if rows or out.strip().upper().startswith("NONE") else "no JSON lines in answer"
        con.execute("DELETE FROM ar_facts WHERE doc_id=? AND piece=? AND prompt_version=?", (d["doc_id"], p["piece"], ar.PROMPT_VERSION))
        if rows:
            con.executemany("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        con.execute("INSERT OR REPLACE INTO ar_pieces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["doc_id"], p["piece"], ar.PROMPT_VERSION, p["page_from"], p["page_to"], len(text), reader, None, None, None,
                     len(rows), "error" if err else "ok", err, out, now()))
        got += 1; facts_n += len(rows)
    for d in m["docs"]:
        n_ok = con.execute("SELECT COUNT(*) FROM ar_pieces WHERE doc_id=? AND prompt_version=? AND status='ok'",
                           (d["doc_id"], ar.PROMPT_VERSION)).fetchone()[0]
        status = "done" if n_ok == d["n_pieces"] else ("partial" if n_ok else "reading")
        con.execute("INSERT OR REPLACE INTO ar_docs VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (d["doc_id"], d["isin"], d["symbol"], d["company"], d["fiscal_year"], d["fiscal_year_source"], d["filed_at"],
                     d["filed_at_source"], d["sha256"], d["path"], d["n_pages"], d["n_text"], d["n_pieces"],
                     "no_text" if not d["n_pieces"] else status, None, now()))
        if status == "done" or not d["n_pieces"]:
            con.execute("UPDATE ar_claims SET status='imported' WHERE doc_id=?", (d["doc_id"],))
        else:   # still being read: renew the claim so the Python run cannot take the report over after CLAIM_HOURS
            con.execute("UPDATE ar_claims SET ts=? WHERE doc_id=?", (now(), d["doc_id"]))
    con.commit()
    nf = con.execute(f"SELECT value_check, COUNT(*) FROM ar_facts WHERE model=? AND doc_id IN ({','.join('?' * len(docs))}) GROUP BY 1",
                     [reader, *docs]).fetchall() if docs else []
    print(f"run {run}: imported {got} pieces ({facts_n} facts), {missing} without an answer yet | value checks: {dict(nf)}")
    if missing:
        print("  re-run the readers for the missing pieces, then import again (import is repeatable)")


# ---------------------------------------------------------------- admission test (the 25 must-find facts)
TEXT_MARK = chr(10) + "TEXT:" + chr(10)
EXHAUSTIVE = """
Be EXHAUSTIVE. Go through the text line by line and table by table. For every table, output one line per figure: every
row and every column (both years, standalone and consolidated), not just totals or highlights. Every numeric fact on
these pages that is in scope above must appear in your output. Leaving out a figure is an error; a long answer is fine.
"""


INDIAN = """
Numbers in Indian reports use Indian digit grouping (lakh/crore): 1,23,45,678 is one crore twenty-three lakh, NOT
12,345,678; 22,30,000 is twenty-two lakh thirty thousand. Copy every number character by character exactly as printed,
with its commas in the same places, its decimals, minus sign or brackets. Never re-group, round, rescale or convert a
number (writing 2,23,000 for a printed 22,30,000 is a tenfold error).
"""


CORE = """
Whatever else you list, ALWAYS include these when they appear on these pages, with their exact figures: capital
commitments; contingent liabilities and claims not acknowledged as debt; cash flow totals (operating, investing,
financing; both years); auditor's opinion modifications, emphasis of matter and key audit matters; credit ratings;
related-party transactions; CSR obligation and spend; receivables and their ageing; government grants, export
incentives and subsidies.
"""


def test_export(run, model, piece_chars=None, exhaustive=False, indian=False, core=False):
    sys.path.insert(0, str(STUDY_TEST))
    import free_reader_test as t
    run_dir = QUEUE / run
    run_dir.mkdir(parents=True, exist_ok=False)
    pieces = []
    for rep in sorted({r for _, r, _ in t.MUST}):
        for name, text in t.parts(rep, piece_chars or ar.PIECE_CHARS):
            # attached files reach the model whole (checked 2026-10-12: 4,000 lines), so a size-test run is not re-split
            for p_from, p_to, sub in ([(0, 0, text)] if piece_chars else split_long([(0, 0, text)])):
                extra = (EXHAUSTIVE if exhaustive else "") + (CORE if core else "") + (INDIAN if indian else "")
                tmpl = ar.PROMPT.replace(TEXT_MARK, extra + TEXT_MARK) if extra else ar.PROMPT
                prompt = tmpl.format(company=rep, symbol=rep, filed="2024", text=sub)
                pieces.append({"file": write_piece(run_dir, len(pieces) + 1, prompt), "report": rep, "part": name})
    (run_dir / "manifest.json").write_text(json.dumps({"run": run, "model": model, "test": True, "piece_chars": piece_chars, "pieces": pieces}, indent=1),
                                           encoding="utf-8")
    print(f"test run {run}: {len(pieces)} pieces -> {run_dir}")


def test_score(run):
    sys.path.insert(0, str(STUDY_TEST))
    import free_reader_test as t
    run_dir = QUEUE / run
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    found, n_num, n_bad, missing, n_group, group_ex, n_added = {}, 0, 0, 0, 0, [], 0
    for p in m["pieces"]:
        out_f = run_dir / p["file"].replace(".prompt.txt", ".out.txt")
        if not out_f.exists():
            missing += 1; continue
        text = piece_text((run_dir / p["file"]).read_text(encoding="utf-8"))
        hay = t.digits(text)
        for f in ar.parse_lines(out_f.read_text(encoding="utf-8", errors="replace")):
            row = {k: "" if f.get(k) is None else str(f.get(k)) for k in ("category", "item", "value", "unit", "period", "basis", "page", "quote")}
            if re.search(r"\d", row["value"]):
                n_num += 1; n_bad += t.digits(row["value"]).strip(".") not in hay
                v = row["value"].strip().strip("()").lstrip("-−").strip()
                if "," in v and v not in text:   # grouping check: the number exactly as printed, commas included
                    printed = [x for x in re.findall(r"\d[\d,]*(?:\.\d+)?", text) if x.replace(",", "") == v.replace(",", "")]
                    if printed and all("," not in x for x in printed):
                        n_added += 1   # printed without commas, the reader added them: same value, harmless
                    else:
                        n_group += 1; group_ex.append(f"{p['report']} p{row['page']}: {row['value']} (printed {printed[:2] or 'nowhere'})")
            blob = " ".join(row.values()); nums = t.digits(row["value"] + " " + row["item"] + " " + row["quote"])
            for mid, rep, toks in t.MUST:
                if rep == p["report"] and mid not in found and all(
                        any(t.digits(alt) in nums for alt in tok.split("|")) if re.fullmatch(r"[\d.,|]+", tok) else re.search(tok, blob, re.I)
                        for tok in toks):
                    found[mid] = f"{p['part']} p{row['page']}"
    n_facts = sum(len(ar.parse_lines((run_dir / p["file"].replace(".prompt.txt", ".out.txt")).read_text(encoding="utf-8", errors="replace")))
                  for p in m["pieces"] if (run_dir / p["file"].replace(".prompt.txt", ".out.txt")).exists())
    lines = [f"# AR admission test: {m['model']} (run {run}, {now()})", "",
             f"**Facts extracted {n_facts}** (depth rule: at least {DEPTH_MIN} = half the passed models' median ~{2 * DEPTH_MIN}; "
             f"a reader that hits the must-find list but skips most facts loses data)", "",
             f"**Must-find {len(found)}/{len(t.MUST)}**; numbers not in the text {n_bad}/{n_num} ({100 * n_bad / max(1, n_num):.1f}%); "
             f"pieces without an answer {missing}/{len(m['pieces'])}; REGROUPED numbers {n_group}/{n_num} (commas placed "
             f"differently from the page, or digits not found; the tenfold-error risk); commas added to unformatted numbers {n_added}", "",
             "Pass = 25/25 must-find (LongCat and Gemma 4 31B scored 25/25), < 1% numbers not in the text, every piece answered.", ""]
    lines += [f"- {'OK  ' if mid in found else 'MISS'} {mid} {found.get(mid, '')}" for mid, _, _ in t.MUST]
    lines += ["", "Grouping-check examples (number with commas not found exactly as printed):"] + [f"- {g}" for g in group_ex[:25]]
    (run_dir / "SCORE.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


# ---------------------------------------------------------------- driver: one fresh `opencode run` per piece
# The Zen free tier refuses custom agent prompts (.opencode/agents/ar-reader.md was refused 2026-10-12) but answers the
# stock agent; the piece file is attached, the answer read from stdout, so the model needs no tools and no session
# grows (an orchestrating OpenCode session ran out of context long before 880 pieces).
ASK = ("The attached file contains instructions followed by annual-report text. Follow the instructions exactly. "
       "Do not use any tools. Reply with the JSON lines only (or the single word NONE).")
ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")
# opencode.exe is a console program: started from a windowless parent (watchdog, detached drive) it opens a visible
# terminal window per call (Shivam saw them 2026-10-13). Every opencode call passes this flag.
NO_WINDOW = 0x08000000   # subprocess.CREATE_NO_WINDOW (Windows)


def opencode_exe():
    """OpenCode CLI, installed with bun (Shivam 2026-10-13: bun only; npm's installs kept breaking). Install/update:
    `bun add -g @opencode/cli` (it is in bun's trustedDependencies, so its postinstall runs)."""
    import shutil
    bun = Path.home() / ".bun" / "install" / "global" / "node_modules"
    for p in (bun / "@opencode" / "cli" / "bin" / "opencode.exe",):
        if p.exists() and p.stat().st_size > 1_000_000:   # < 1 MB = the placeholder left when npm skipped postinstall
            return str(p)
    return shutil.which("opencode")


def read_piece(exe, model, prompt_file, timeout=900):
    import subprocess
    p = subprocess.run([exe, "run", "-m", f"opencode/{model}", "--title", f"ar-queue {prompt_file.parent.name}/{prompt_file.stem}",
                        ASK, "-f", str(prompt_file)], cwd=ar.ROOT, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout, creationflags=NO_WINDOW)
    out = "\n".join(l for l in ANSI.sub("", p.stdout).splitlines() if not l.startswith("> ")).strip()
    return out, p.returncode, ANSI.sub("", p.stderr).strip()[-400:]


KILO_URL = "https://api.kilo.ai/api/gateway/chat/completions"


TOKENHARBOR_URL = "https://tokenharbor.ai/v1/chat/completions"   # third-party reseller (2026-10-13); readings tagged th:


def read_piece_kilo(model, prompt_file, key_env="KILO_API_KEY", timeout=900, url=KILO_URL):
    """An OpenAI-compatible gateway model over its API (Kilo, Token Harbor); no OpenCode needed."""
    import requests
    from reality_engine.scripts.resource_watchdog import user_env
    key = user_env().get(key_env, "")
    import uuid
    hdr = {"Authorization": f"Bearer {key}"}
    if "opencode.ai" in url:   # OpenCode Go refuses requests without a session id (MissingSessionID)
        hdr["x-opencode-session"] = session_id("ar_queue", model, key)
    r = requests.post(url, timeout=timeout, headers=hdr,
                      json={"model": model, "max_tokens": 32000,
                            "messages": [{"role": "user", "content": prompt_file.read_text(encoding="utf-8")}]})
    if r.status_code != 200 or not r.json().get("choices"):
        return "", r.status_code, r.text[:300]
    return r.json()["choices"][0]["message"].get("content") or "", 0, ""


_gem_turn = {}


def read_piece_gemini(model, prompt_file, key_envs, timeout=900):
    """Google AI Studio model (Gemma / Gemini) over the native API; keys used in turn (limits are per project+model)."""
    import itertools
    import requests
    from reality_engine.scripts.resource_watchdog import user_env
    cyc = _gem_turn.setdefault((model, key_envs), itertools.cycle(key_envs.split(",")))
    key = user_env().get(next(cyc), "")
    body = {"contents": [{"parts": [{"text": prompt_file.read_text(encoding="utf-8")}]}],
            "generationConfig": {"maxOutputTokens": 32000, "thinkingConfig": {"thinkingLevel": "minimal"}}}
    r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", timeout=timeout,
                      headers={"x-goog-api-key": key}, json=body)
    if r.status_code == 400 and "thinking" in r.text.lower():   # model without thinking levels
        body["generationConfig"].pop("thinkingConfig")
        r = requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent", timeout=timeout,
                          headers={"x-goog-api-key": key}, json=body)
    if r.status_code != 200 or not r.json().get("candidates"):
        return "", r.status_code, r.text[:300]
    c = r.json()["candidates"][0]
    return "".join(p.get("text", "") for p in c.get("content", {}).get("parts", []) if not p.get("thought")), 0, ""


def drive(runs, workers):
    import threading
    import time
    from concurrent.futures import ThreadPoolExecutor
    exe = opencode_exe()
    if not exe:
        sys.exit("opencode not found (npm global @opencode/cli or opencode-ai); if npm skipped its postinstall, run "
                 "`node postinstall.mjs` in that package folder")
    lock = threading.Lock()
    log_f = QUEUE / "drive.log"

    def note(msg):
        with lock, open(log_f, "a", encoding="utf-8") as f:
            f.write(f"{now()} {msg}\n")
        print(msg, flush=True)

    def one(run_dir, model, prompt_file):
        out_f = prompt_file.with_name(prompt_file.name.replace(".prompt.txt", ".out.txt"))
        for attempt in range(3):
            t = time.time()
            try:   # model "kilo:<id>[@KEY_ENV]" goes to the Kilo API, anything else through opencode run
                if model.startswith("gemini:"):   # "gemini:<model id>@KEY_A,KEY_B,..."
                    mid, _, kenvs = model[7:].partition("@")
                    out, rc, err = read_piece_gemini(mid, prompt_file, kenvs or "GEMINI_API_KEY")
                elif model.startswith("go:"):   # "go:<model id>" = OpenCode Go API (OPENCODE_GO_API_KEY)
                    out, rc, err = read_piece_kilo(model[3:], prompt_file, "OPENCODE_GO_API_KEY",
                                                   url="https://opencode.ai/zen/go/v1/chat/completions")
                elif model.startswith("th:"):   # "th:<model id>" = Token Harbor (TOKENHARBOR_API_KEY)
                    out, rc, err = read_piece_kilo(model[3:], prompt_file, "TOKENHARBOR_API_KEY", url=TOKENHARBOR_URL)
                elif model.startswith("kilo:"):
                    mid, _, kenv = model[5:].partition("@")
                    out, rc, err = read_piece_kilo(mid, prompt_file, kenv or "KILO_API_KEY")
                else:
                    out, rc, err = read_piece(exe, model, prompt_file)
            except Exception as e:
                out, rc, err = "", -1, str(e)[:300]
            ok = bool(ar.parse_lines(out)) or out.strip().upper() == "NONE"
            if ok:
                out_f.write_text(out, encoding="utf-8")
                note(f"{run_dir.name}/{prompt_file.stem} ok {len(ar.parse_lines(out))} facts {time.time() - t:.0f}s")
                return
            note(f"{run_dir.name}/{prompt_file.stem} FAIL try {attempt + 1} rc={rc} {err[-160:]!r}")
            msg = (out + " " + err).lower()   # the CLI prints the provider error on stdout or stderr
            time.sleep(120 * (attempt + 1) if "rate limit" in msg or "429" in msg else 10)
        prompt_file.with_name(prompt_file.name.replace(".prompt.txt", ".err.txt")).write_text(err, encoding="utf-8")

    def run_all(run):
        run_dir = QUEUE / run
        m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
        todo = [run_dir / p["file"] for p in m["pieces"]
                if not (run_dir / p["file"].replace(".prompt.txt", ".out.txt")).exists()]
        note(f"run {run} ({m['model']}): {len(todo)} pieces to read, {workers} at a time")
        with ThreadPoolExecutor(workers) as ex:
            list(ex.map(lambda f: one(run_dir, m["model"], f), todo))
        note(f"run {run}: finished")

    with ThreadPoolExecutor(len(runs)) as ex:
        list(ex.map(run_all, runs))


# ---------------------------------------------------------------- hard reports: diagnose, re-check, Claude Haiku re-read
# 2026-10-16 (tasks/HARD_AR_HAIKU_SESSION.md). A "hard" report has > 10% of its numbers not found in the source text.
# diagnose sorts them by the state of the pages their misses sit on; recheck re-runs value_check (free: new font rules);
# export-docs writes the pages for Claude Haiku helper agents (Claude Code Agent tool, model haiku), as text where the text
# layer is clean and as page images where it is not; import-docs stores Haiku's answers as model claude-haiku-5-5 and
# replaces a report's earlier facts on the re-read pages only when Haiku's verify better.
HAIKU = "claude-haiku-5-5"
HAIKU_PV = "ar-v1x-haiku"     # own prompt_version: Haiku's ar_pieces rows never collide with the free readers' rows
HAIKU_PIECE_CHARS = 18000
HAIKU_PER_AGENT = 10          # text pieces (or page images) per agent folder
IMG_SIDE = 1800               # longest side of a rendered page image, pixels
HARD_SQL = """SELECT doc_id, symbol, fiscal_year, SUM(value_check='not_found') nf, COUNT(*) n FROM ar_facts
  WHERE value IS NOT NULL GROUP BY doc_id HAVING n >= ? AND 1.0 * nf / n > ? ORDER BY 1.0 * nf / n DESC"""
VOCAB_F = QUEUE / "en_vocab.txt"   # 8,000 commonest words (>= 3 letters) of 6 clean reports, built 2026-10-16
IMAGE_AGENT = """# Annual-report page reading: instructions for helper agents (Claude Haiku)

Your folder holds pairs `NNNN.prompt.txt` (the task) and either the page text inside the prompt, or a page image
`NNNN.jpg` next to it (its text layer is garbled, encoded or missing). For each prompt file in order:

1. Read the prompt file. If a `NNNN.jpg` with the same number exists, read that image: it is the page to extract from.
2. Write the answer to `NNNN.out.txt` in the same folder with the Write tool: only the JSON lines the prompt asks for
   (one object per line), or the single word NONE when the page has nothing worth storing.

Rules on top of the prompt:
- Copy every number exactly as printed in the image or text (Indian grouping such as 1,23,45,678 stays as printed;
  brackets and minus signs kept). Never compute, convert, round or add up.
- "page" is the PDF page number given in the prompt (=== PAGE n ===), not the number printed on the page.
- Every prompt file must get a `.out.txt`, even if it is only NONE.
- Do not re-open files you already handled. Do not explain.

When finished, reply with one line: how many files you wrote.
"""


def page_texts(path):
    import pymupdf
    doc = pymupdf.open(path)
    try:
        return {i + 1: doc[i].get_text() for i in range(len(doc))}
    finally:
        doc.close()


def page_kind(text):
    """no_text | hindi | encoded (font maps letters/digits elsewhere in Unicode) | garbled (OCR junk) | clean."""
    t = (text or "").translate(ar.FONT_DIGITS)
    if len(t.strip()) < 40:
        return "no_text"
    if ar.devanagari_share(t) >= 0.5:
        return "hindi"
    toks = [x for x in re.split(r"[\s\x00-\x1f]+", t) if x]
    words = re.findall(r"[A-Za-z]{2,}", t)
    if ar.shifted_digit_maps(t) or len(words) < 0.3 * len(toks):
        return "encoded"
    words = [w.lower() for w in words if len(w) >= 3]
    if words and sum(w in vocab() for w in words) < 0.6 * len(words):   # clean pages >= 0.92 (5th pct); OCR junk 0.15-0.22
        return "garbled"
    return "clean"


@functools.lru_cache(maxsize=1)
def vocab():
    return frozenset(VOCAB_F.read_text(encoding="utf-8").split())


def hard_docs(con, min_n=50, share=0.10):
    return con.execute(HARD_SQL, (min_n, share)).fetchall()


def piece_texts(con, doc_id, pages):
    """(piece, prompt_version) -> the piece text as the reader saw it (=== PAGE n === markers, skipped pages left out)."""
    skipped = {r[0] for r in con.execute("SELECT page FROM ar_skipped_pages WHERE doc_id=?", (doc_id,))}
    out = {}
    for piece, pv, a, b in con.execute("SELECT piece, prompt_version, page_from, page_to FROM ar_pieces WHERE doc_id=?", (doc_id,)):
        if a is None:
            continue
        out[(piece, pv)] = "".join(f"=== PAGE {n} ===\n{pages[n]}\n" for n in range(a, b + 1)
                                   if n in pages and len(pages[n].strip()) >= 40 and n not in skipped)
    return out


def doc_ids_arg(con, spec):
    """'hard' = every hard report; otherwise a comma list of doc ids."""
    return [r[0] for r in hard_docs(con)] if spec == "hard" else [int(x) for x in spec.split(",") if x.strip()]


def diagnose(spec, out_csv):
    """Per hard report: share of its not_found numbers on no_text / encoded / garbled / clean pages, the readers involved,
    and the cause (the page kind holding most misses; 'clean' = the text is fine, so the reader misread)."""
    import csv
    con = connect()
    rows = hard_docs(con) if spec == "hard" else [con.execute(
        "SELECT doc_id, symbol, fiscal_year, SUM(value_check='not_found'), COUNT(*) FROM ar_facts WHERE doc_id=? AND value IS NOT NULL",
        (i,)).fetchone() for i in doc_ids_arg(con, spec)]
    out = []
    for doc_id, sym, fy, nf, n in rows:
        path = con.execute("SELECT path FROM ar_docs WHERE doc_id=?", (doc_id,)).fetchone()
        try:
            pages = page_texts(path[0])
        except Exception as e:
            out.append({"doc_id": doc_id, "symbol": sym, "fy": fy, "nf": nf, "n": n, "cause": f"pdf error {e}"[:80]}); continue
        kinds = {k: page_kind(t) for k, t in pages.items()}
        miss = collections.Counter(kinds.get(pg, "no_page") for (pg,) in con.execute(
            "SELECT page FROM ar_facts WHERE doc_id=? AND value IS NOT NULL AND value_check='not_found'", (doc_id,)))
        models = collections.Counter(m.split("@")[0] for (m,) in con.execute(
            "SELECT model FROM ar_facts WHERE doc_id=? AND value_check='not_found'", (doc_id,)))
        pk = collections.Counter(kinds.values())
        out.append({"doc_id": doc_id, "symbol": sym, "fy": fy[:4], "nf": nf, "n": n, "cause": miss.most_common(1)[0][0],
                    **{f"miss_{k}": miss.get(k, 0) for k in ("clean", "encoded", "garbled", "no_text", "hindi", "no_page")},
                    **{f"pages_{k}": pk.get(k, 0) for k in ("clean", "encoded", "garbled", "no_text", "hindi")},
                    "models": " ".join(f"{m}:{c}" for m, c in models.most_common(3))})
        print(f"{doc_id} {sym} {fy[:4]} nf {nf}/{n} cause {out[-1]['cause']} {dict(miss)}", flush=True)
    keys = list(dict.fromkeys(k for r in out for k in r))
    with open(out_csv, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, keys); w.writeheader(); w.writerows(out)
    by = collections.Counter(); by_nf = collections.Counter()
    for r in out:
        by[r["cause"]] += 1; by_nf[r["cause"]] += r["nf"]
    print(f"{len(out)} reports -> {out_csv}; by cause (reports, not_found numbers): " +
          ", ".join(f"{k} {by[k]} / {by_nf[k]}" for k in by))


def recheck(spec, write):
    """Re-run value_check on reports' facts with the current rules (page and piece text rebuilt from the PDF). Free."""
    con = connect()
    tot_b, tot_a = collections.Counter(), collections.Counter()
    for doc_id in doc_ids_arg(con, spec):
        path = con.execute("SELECT path FROM ar_docs WHERE doc_id=?", (doc_id,)).fetchone()
        if not path:
            continue
        try:
            pages = page_texts(path[0])
        except Exception as e:
            print(f"{doc_id}: {e}"); continue
        pieces = piece_texts(con, doc_id, pages)
        changes, b, a = [], collections.Counter(), collections.Counter()
        for rowid, piece, pv, pg, raw, old in con.execute("""SELECT rowid, piece, prompt_version, page, value_raw, value_check
                FROM ar_facts WHERE doc_id=? AND value_raw IS NOT NULL AND model != ?""", (doc_id, HAIKU)).fetchall():
            new = ar.value_check(raw, pages.get(pg), pieces.get((piece, pv), ""))
            b[old] += 1; a[new] += 1
            if new != old and not (old == "piece" and new == "not_found"):   # never downgrade on a rebuilt piece text
                changes.append((new, rowid))
        tot_b.update(b); tot_a.update(a)
        if write and changes:
            con.executemany("UPDATE ar_facts SET value_check=? WHERE rowid=?", changes); con.commit()
        print(f"{doc_id}: not_found {b['not_found']} -> {a['not_found']} ({len(changes)} rows {'updated' if write else 'would change'})", flush=True)
    print(f"total not_found {tot_b['not_found']} -> {tot_a['not_found']}; page {tot_b['page']} -> {tot_a['page']}")


def render_jpeg(page):
    import pymupdf
    zoom = IMG_SIDE / max(page.rect.width, page.rect.height)
    return page.get_pixmap(matrix=pymupdf.Matrix(zoom, zoom), alpha=False).tobytes("jpeg", jpg_quality=85)


_OCR = []


def ocr_text(jpeg):
    """RapidOCR (DirectML) text of a rendered page: the independent text a Haiku image read is checked against."""
    if not _OCR:
        try:
            from rapidocr import RapidOCR
            _OCR.append(RapidOCR(params={"EngineConfig.onnxruntime.use_dml": True, "Global.log_level": "ERROR",
                                         "Global.max_side_len": IMG_SIDE}))
        except Exception:
            _OCR.append(None)
    if _OCR[0] is None:
        return ""
    try:
        r = _OCR[0](jpeg)
        return "\n".join(r.txts or ()) if r is not None else ""
    except Exception:
        return ""


def export_docs(run, spec, pages_spec=None, mode="auto", per_agent=HAIKU_PER_AGENT, misses_only=False, image_only=False):
    """Write a report's pages for Haiku agents: run/bNNN/NNNN.prompt.txt (+ NNNN.jpg for image pages), manifest.json.
    mode auto: clean pages as text pieces (<= HAIKU_PIECE_CHARS), encoded/garbled/no_text pages as images; text: all as
    text; image: all as images. Hindi pages and year-over-year repeats stay skipped. pages_spec 'a-b' limits the pages.
    misses_only: only pages that hold at least one not_found number (and pages of failed pieces never read).
    image_only: only the pages that go as images (the clean pages keep their earlier reading)."""
    run_dir = QUEUE / run
    if (run_dir / "manifest.json").exists():
        sys.exit(f"run {run} exists; import it or pick a new run name")
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "AGENT_INSTRUCTIONS.md").write_text(IMAGE_AGENT, encoding="utf-8")
    tmpl, _ = ar.prompt_for("exhaustive")
    con = connect()
    units, docs = [], []
    import pymupdf
    for doc_id in doc_ids_arg(con, spec):
        r = con.execute("""SELECT doc_id, isin, symbol, company, fiscal_year, fiscal_year_source, filed_at, filed_at_source,
                           sha256, path FROM ar_docs WHERE doc_id=?""", (doc_id,)).fetchone()
        if not r:
            print(f"{doc_id}: not in ar_docs, skipped"); continue
        d = dict(zip(("doc_id", "isin", "symbol", "company", "fiscal_year", "fiscal_year_source", "filed_at",
                      "filed_at_source", "sha256", "path"), r))
        pages = page_texts(d["path"])
        skipped = {x[0] for x in con.execute("SELECT page FROM ar_skipped_pages WHERE doc_id=?", (doc_id,))}
        want = set(pages)
        if pages_spec:
            a, _, b = pages_spec.partition("-"); want = set(range(int(a), int(b or a) + 1))
        if misses_only:
            miss = {x[0] for x in con.execute("SELECT DISTINCT page FROM ar_facts WHERE doc_id=? AND value_check='not_found'", (doc_id,))}
            unread = set()
            for a, b in con.execute("""SELECT page_from, page_to FROM ar_pieces e WHERE doc_id=? AND status='error' AND NOT EXISTS
                    (SELECT 1 FROM ar_pieces o WHERE o.doc_id=e.doc_id AND o.status='ok' AND o.page_from<=e.page_to AND o.page_to>=e.page_from)""",
                                    (doc_id,)):
                unread |= set(range(a, b + 1))
            want &= miss | unread
        kinds = {n: page_kind(t) for n, t in pages.items()}
        todo = [n for n in sorted(pages) if n in want and n not in skipped and kinds[n] != "hindi"]
        as_image = [n for n in todo if mode == "image" or (mode == "auto" and kinds[n] in ("encoded", "garbled", "no_text"))]
        as_text = [] if image_only else [n for n in todo if n not in as_image and len(pages[n].strip()) >= 40]
        d.update(n_pages=len(pages), pages_text=as_text, pages_image=as_image)
        docs.append(d)
        k = 0
        buf, first, last = "", None, None
        def flush():
            nonlocal buf, first, k
            if buf:
                units.append({"doc_id": doc_id, "piece": k, "kind": "text", "page_from": first, "page_to": last, "text": buf})
                k += 1
            buf, first = "", None
        for n in as_text:
            block = f"=== PAGE {n} ===\n{pages[n]}\n"
            if buf and (len(buf) + len(block) > HAIKU_PIECE_CHARS or n != last + 1):
                flush()
            if first is None:
                first = n
            buf += block[:HAIKU_PIECE_CHARS]; last = n
        flush()
        pdf = pymupdf.open(d["path"])
        for n in as_image:
            jpeg = render_jpeg(pdf[n - 1])
            units.append({"doc_id": doc_id, "piece": k, "kind": "image", "page_from": n, "page_to": n, "jpeg": jpeg,
                          "ocr": ocr_text(jpeg)})
            k += 1
        pdf.close()
        print(f"{doc_id} {d['symbol']} FY {d['fiscal_year'][:4]}: {len(as_text)} text pages, {len(as_image)} image pages", flush=True)
    man = []
    for i, u in enumerate(units):
        d = next(x for x in docs if x["doc_id"] == u["doc_id"])
        b = run_dir / f"b{i // per_agent:03d}"; b.mkdir(exist_ok=True)
        stem = f"{i:04d}"
        if u["kind"] == "text":
            text = u["text"]
        else:
            text = (f"=== PAGE {u['page_from']} ===\n(The text layer of this page is unusable. Read the page image "
                    f"{stem}.jpg in this folder instead.)\n")
            (b / f"{stem}.jpg").write_bytes(u["jpeg"])
            (b / f"{stem}.ocr.txt").write_text(u["ocr"], encoding="utf-8")   # for the import check only; agents ignore it
        (b / f"{stem}.prompt.txt").write_text(tmpl.format(company=d["company"], symbol=d["symbol"],
                                                          filed=str(d["filed_at"])[:10], text=text), encoding="utf-8")
        man.append({"file": f"{b.name}/{stem}", "doc_id": u["doc_id"], "piece": u["piece"], "kind": u["kind"],
                    "page_from": u["page_from"], "page_to": u["page_to"]})
    (run_dir / "manifest.json").write_text(json.dumps({"run": run, "model": HAIKU, "prompt_version": HAIKU_PV, "created": now(),
                                                       "docs": docs, "units": man}, indent=1), encoding="utf-8")
    folders = sorted({m["file"].split("/")[0] for m in man})
    print(f"run {run}: {len(docs)} reports, {len(man)} units ({sum(m['kind'] == 'image' for m in man)} images) in "
          f"{len(folders)} folders -> {run_dir}")


def missing_folders(run):
    """Folders of a Haiku run that still lack answers (to launch the next wave on)."""
    run_dir = QUEUE / run
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    todo = collections.Counter(u["file"].split("/")[0] for u in m["units"] if not (run_dir / f"{u['file']}.out.txt").exists())
    print(" ".join(sorted(todo)) or "none")


def import_docs(run, dry=False, redo=False, skip=()):
    """Store Haiku's answers. Per report, over the pages Haiku re-read: old facts (any other reader) vs Haiku's facts.
    Haiku's replace the old ones only when they verify better: a lower not_found share AND at least 80% as many verified
    numbers (a short answer must not win by saying less). Replaced rows move to ar_facts_replaced (never deleted
    outright). A report is decided only when every unit of it is answered, and only once: a report with Haiku pieces
    already stored is skipped unless redo (2026-10-16: a second import counted Haiku's own facts as missing and re-tagged
    them rejected). Raw answers are kept in ar_pieces either way.
    Check: text pieces against their own text (page / piece); image pages against the text layer (font rules decode it
    where possible) and then against RapidOCR's text of the same image ('ocr'); else not_found."""
    run_dir = QUEUE / run
    m = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    con = connect()
    con.execute("CREATE TABLE IF NOT EXISTS ar_facts_replaced AS SELECT *, '' AS replaced_by, '' AS replaced_ts FROM ar_facts WHERE 0")
    docs = {d["doc_id"]: d for d in m["docs"]}
    report = []
    for doc_id, d in docs.items():
        if doc_id in skip:   # 2026-10-16: e.g. a PDF that is another company's report (stored under the wrong symbol)
            report.append(f"{doc_id} {d['symbol']}: skipped (--skip-docs)"); continue
        us = [u for u in m["units"] if u["doc_id"] == doc_id]
        if not us:
            continue
        if not all((run_dir / f"{u['file']}.out.txt").exists() for u in us):
            report.append(f"{doc_id} {d['symbol']}: {sum(not (run_dir / (u['file'] + '.out.txt')).exists() for u in us)}"
                          f"/{len(us)} units unanswered, not decided"); continue
        if not redo and con.execute("SELECT 1 FROM ar_pieces WHERE doc_id=? AND prompt_version=? LIMIT 1", (doc_id, HAIKU_PV)).fetchone():
            report.append(f"{doc_id} {d['symbol']}: already imported (use --redo to decide again)"); continue
        pages = page_texts(d["path"])
        rows, pieces = [], []
        for u in us:
            prompt = (run_dir / f"{u['file']}.prompt.txt").read_text(encoding="utf-8")
            out = (run_dir / f"{u['file']}.out.txt").read_text(encoding="utf-8", errors="replace")
            text = piece_text(prompt)
            ocr_f = run_dir / f"{u['file']}.ocr.txt"
            ocr = ocr_f.read_text(encoding="utf-8") if ocr_f.exists() else ""
            facts = ar.parse_lines(out)
            for f in facts:
                pg = int(f["page"]) if str(f.get("page", "")).isdigit() else None
                if u["kind"] == "image":
                    pg = pg if pg == u["page_from"] else u["page_from"]   # one page per image unit
                    chk = ar.value_check(f.get("value"), pages.get(pg), "")
                    if chk == "not_found" and ar.value_check(f.get("value"), ocr, "") == "page":
                        chk = "ocr"
                else:
                    page_text = {int(g.group(1)): g.group(2) for g in re.finditer(r"=== PAGE (\d+) ===\n(.*?)(?=\n=== PAGE |\Z)", text, re.S)}
                    chk = ar.value_check(f.get("value"), page_text.get(pg), text)
                rows.append((doc_id, u["piece"], d["isin"], d["symbol"], d["fiscal_year"], d["filed_at"], pg,
                             str(f.get("category") or "")[:80], str(f.get("item") or "")[:500],
                             None if f.get("value") is None else str(f["value"])[:60], ar.to_number(f.get("value")),
                             str(f.get("unit") or "")[:40], str(f.get("period") or "")[:40], str(f.get("basis") or "")[:20],
                             str(f.get("quote") or "")[:300], HAIKU, chk, HAIKU_PV))
            err = None if facts or out.strip().upper().startswith("NONE") else "no JSON lines in answer"
            pieces.append((doc_id, u["piece"], HAIKU_PV, u["page_from"], u["page_to"], len(text), HAIKU, None, None, None,
                           len(facts), "error" if err else "ok", err, out, now()))
        covered = sorted({n for u in us for n in range(u["page_from"], u["page_to"] + 1)})
        q = f"FROM ar_facts WHERE doc_id=? AND model NOT LIKE ? AND page IN ({','.join('?' * len(covered))})"
        old = con.execute(f"SELECT value_check, COUNT(*) {q} AND value IS NOT NULL GROUP BY 1", (doc_id, HAIKU + "%", *covered)).fetchall()
        old = collections.Counter(dict(old))
        new = collections.Counter(r[16] for r in rows if r[10] is not None)
        o_n, n_n = sum(old.values()), sum(new.values())
        o_v, n_v = old["page"] + old["piece"], new["page"] + new["piece"] + new["ocr"]
        o_s, n_s = old["not_found"] / max(1, o_n), new["not_found"] / max(1, n_n)
        # 2026-10-16: with no old numbers on these pages (scans no reader got text from) nothing is replaced, so Haiku's
        # facts are pure gain; they were kept as rejected because 'n_s < 0%' can never hold. Each row keeps its value_check.
        better = n_n > 0 and (n_s < 0.5 if o_n == 0 else n_s < o_s and n_v >= 0.8 * o_v)
        line = (f"{doc_id} {d['symbol']} FY {d['fiscal_year'][:4]} pages {len(covered)}: old {o_n} numbers, not_found "
                f"{100 * o_s:.0f}%, verified {o_v} | haiku {n_n} numbers, not_found {100 * n_s:.0f}%, verified {n_v} "
                f"({dict(new)}) -> {'REPLACE' if better else 'keep old'}")
        report.append(line)
        if dry:
            continue
        con.execute("DELETE FROM ar_facts WHERE doc_id=? AND model LIKE ? AND prompt_version=?", (doc_id, HAIKU + "%", HAIKU_PV))
        con.execute("DELETE FROM ar_pieces WHERE doc_id=? AND prompt_version=?", (doc_id, HAIKU_PV))
        con.executemany("INSERT INTO ar_pieces VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", pieces)
        if better:
            con.execute(f"INSERT INTO ar_facts_replaced SELECT *, ?, ? {q}", (f"{run}:{HAIKU}", now(), doc_id, HAIKU + "%", *covered))
            con.execute(f"DELETE {q}", (doc_id, HAIKU + "%", *covered))
            con.executemany("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        else:   # kept for the record, flagged so they never mix with the facts in use
            con.executemany("INSERT INTO ar_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            [r[:15] + (HAIKU + ":rejected",) + r[16:] for r in rows])
        con.commit()
    (run_dir / ("IMPORT_DRY.md" if dry else "IMPORT.md")).write_text("\n".join(report) + "\n", encoding="utf-8")
    print("\n".join(report))


def status():
    con = connect()
    print("claims:", con.execute("SELECT owner, status, COUNT(*) FROM ar_claims GROUP BY 1, 2").fetchall())
    print("docs by reader family:", con.execute("""SELECT CASE WHEN model LIKE 'zen:%' THEN 'opencode-zen' ELSE 'python-run' END,
        COUNT(DISTINCT doc_id), COUNT(*), SUM(status='ok') FROM ar_pieces GROUP BY 1""").fetchall(), "(reports, pieces, ok)")
    for d in sorted(QUEUE.glob("*/manifest.json")) if QUEUE.exists() else []:
        m = json.loads(d.read_text(encoding="utf-8"))
        n_out = len(list(d.parent.glob("*.out.txt")))
        print(f"  run {m['run']}: {len(m['pieces'])} pieces, {n_out} answered, model {m['model']}{' (test)' if m.get('test') else ''}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")   # Windows console/pipe is cp1252: ₹ in SCORE lines crashed print
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["export", "import", "test-export", "test-score", "status", "drive", "diagnose", "recheck",
                                    "export-docs", "import-docs", "missing"])
    ap.add_argument("--doc-ids", default="hard", help="hard reports: 'hard' or a comma list of doc ids")
    ap.add_argument("--pages", default=None, help="export-docs: page range a-b")
    ap.add_argument("--mode", default="auto", choices=["auto", "text", "image"], help="export-docs: how pages are given")
    ap.add_argument("--per-agent", type=int, default=HAIKU_PER_AGENT, help="export-docs: units per agent folder")
    ap.add_argument("--misses-only", action="store_true", help="export-docs: only pages holding not_found numbers or never read")
    ap.add_argument("--image-only", action="store_true", help="export-docs: only pages whose text layer is unusable")
    ap.add_argument("--write", action="store_true", help="recheck: store the new value_check results")
    ap.add_argument("--dry", action="store_true", help="import-docs: report the decision only")
    ap.add_argument("--redo", action="store_true", help="import-docs: decide reports already imported again")
    ap.add_argument("--skip-docs", default="", help="import-docs: comma list of doc ids to leave out")
    ap.add_argument("--out", default=str(QUEUE / "hard_diagnosis.csv"), help="diagnose: CSV path")
    ap.add_argument("--run", help="run name; for drive a comma list (runs read in parallel)")
    ap.add_argument("--workers", type=int, default=2, help="drive: opencode processes per run")
    ap.add_argument("--docs", type=int, default=3)
    ap.add_argument("--model", default="longcat-2.5-preview-free")
    ap.add_argument("--owner", default="opencode-zen")
    ap.add_argument("--core", action="store_true", help="test-export: add the always-include CORE list to the prompt")
    ap.add_argument("--indian", action="store_true", help="test-export: add the Indian-number-grouping note to the prompt")
    ap.add_argument("--exhaustive", action="store_true", help="test-export: add the EXHAUSTIVE instruction to the prompt")
    ap.add_argument("--piece-chars", type=int, default=None, help="test-export: piece size (default: production size, re-split)")
    a = ap.parse_args()
    if a.cmd not in ("status", "diagnose", "recheck") and not a.run:
        sys.exit("--run is required")
    {"export": lambda: export(a.run, a.docs, a.model, a.owner), "import": lambda: do_import(a.run),
     "test-export": lambda: test_export(a.run, a.model, a.piece_chars, a.exhaustive, a.indian, a.core), "test-score": lambda: test_score(a.run), "status": status,
     "drive": lambda: drive(a.run.split(","), a.workers), "diagnose": lambda: diagnose(a.doc_ids, a.out),
     "recheck": lambda: recheck(a.doc_ids, a.write), "missing": lambda: missing_folders(a.run),
     "export-docs": lambda: export_docs(a.run, a.doc_ids, a.pages, a.mode, a.per_agent, a.misses_only, a.image_only),
     "import-docs": lambda: import_docs(a.run, a.dry, a.redo, {int(x) for x in a.skip_docs.split(",") if x.strip()})}[a.cmd]()
