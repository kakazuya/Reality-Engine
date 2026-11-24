"""T-242: settle hy4 UNVERIFIED number rows with headless Claude Sonnet medium on Wolf's quota (Shivam 24 Nov 20:00).

    python -m reality_engine.scripts.sonnet_settle --db D:/RealityEngine/hy4_out/pilot_decks_entity.db \
        --stores-root C:/RealityEngine/tg_build/universe_fy27 --out D:/RealityEngine/t242/sonnet_settle/pilot_decks

Sonnet sees one page's text and the unverified company rows read from it, and returns per row: confirm (every
stored field right), fix (value is the company's and on the page, but period/unit/scale/basis/segment need the
given correction), reject (not on the page, wrong row/column, or not the company's own figure) or unsure.
It needs a printed snippet holding the value and its column/period header for confirm/fix.
Never writes the hy4 DB: verdicts go to <out>/verdicts.jsonl, labelled model-checked, and are served only after
an independent >= 60-row hand grade of the confirm/fix verdicts passes (maker-checker-verifier, 24 Nov).
Stops while Wolf's 5-hour use is >= LIMIT_5H or its reading is stale; one headless run at a time.
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from reality_engine.v2 import observations as obs  # noqa: E402

CFG = os.environ.get("SONNET_SETTLE_CONFIG", r"C:\Users\warri\.claude-neo")   # Eagle: C:\Users\warri\.claude
LIMIT_5H = 75
LIMIT_7D = 95
STALE_S = 1800
PAGES_PER_RUN = 6
CREATE_NO_WINDOW = 0x08000000
FIELDS = ("observation_id", "measure", "printed_label", "printed_axis", "value_text", "value", "unit", "scale",
          "period", "basis", "segment", "series_title", "status_reason")

RULES = """You check figures another model read from one page of an Indian listed company's investor presentation.
Every row below was left UNVERIFIED by scripts. For each row decide, strictly, from the page text only:
- "confirm": the value is printed on this page, it is the company's own figure (or a subsidiary/segment named in
  "segment"), and the stored measure, period, unit, scale and basis are all right.
- "fix": the value is printed and is the company's own, but one or more of period, unit, scale, basis, segment is
  wrong or empty; give the corrected fields (only those you can read off the page: a column header, a unit line
  such as "(Rs Cr)" / "in lakhs", a "Standalone"/"Consolidated" heading).
- "reject": the value is not on the page, sits on a different row/column than stored, is another entity's figure
  (market, industry, country, peer, customer, an unnamed subsidiary), or the measure is wrong.
- "unsure": the page does not let you decide (garbled text, chart values without labels).
Warnings: some decks print the value BEFORE its label; check totals and growth % arithmetic to tell the current
column from the comparative one. A period must come from a printed header, not a guess. Do not invent units.
For confirm/fix give "evidence": the shortest exact snippet from the page holding the value and its label, and
"header": the printed column/period header it sits under.
Reply with ONLY a JSON array, one object per row:
[{"id": <observation_id>, "verdict": "confirm|fix|reject|unsure", "period": "...", "unit": "...", "scale": <number>,
  "basis": "consolidated|standalone|", "segment": "...", "evidence": "...", "header": "...", "why": "<= 20 words"}]
Fields you do not change may be left out."""


def jlines(p: Path) -> list[dict]:
    if not p.is_file():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def quota_ok() -> tuple[bool, str]:
    try:
        st = json.loads(Path(CFG, "usage_status.json").read_text(encoding="utf-8"))
        age = (dt.datetime.now() - dt.datetime.fromisoformat(st["_saved_at"])).total_seconds()
        five = st["rate_limits"]["five_hour"]["used_percentage"]
        seven = st["rate_limits"]["seven_day"]["used_percentage"]
    except Exception as exc:  # noqa: BLE001
        return False, f"no reading ({exc})"
    if age > STALE_S:
        return False, f"reading {int(age)}s old"
    if five >= LIMIT_5H or seven >= LIMIT_7D:
        return False, f"5h {five}% 7d {seven}%"
    return True, f"5h {five}% 7d {seven}%"


def store_index(root: str, cache: Path) -> dict[str, str]:
    if cache.is_file():
        return json.loads(cache.read_text(encoding="utf-8"))
    idx: dict[str, str] = {}
    for db in glob.glob(f"{root}/c*/c*.db"):
        if db.endswith(("_ocr.db", "pages.db")):
            continue
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            for (k,) in con.execute("select distinct doc_key from doc_page"):
                idx.setdefault(k, db)
            con.close()
        except sqlite3.Error:
            continue
    cache.write_text(json.dumps(idx), encoding="utf-8")
    return idx


def run_claude(prompt: str, log: Path) -> tuple[str, dict]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE_CODE", "CLAUDE_PID", "CLAUDE_EFFORT"))}
    env.update(CLAUDE_CONFIG_DIR=CFG, PYTHONIOENCODING="utf-8")
    cmd = ["claude", "-p", "--model", "sonnet", "--effort", "medium", "--output-format", "json", "--max-turns", "2",
           "--disallowedTools", "Bash,Read,Write,Edit,Glob,Grep,WebFetch,WebSearch,Agent"]
    p = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", cwd=str(log.parent),
                       env=env, timeout=1800, creationflags=CREATE_NO_WINDOW, shell=False)
    log.write_text(p.stdout + "\n--- stderr ---\n" + p.stderr, encoding="utf-8")
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return "", {"error": (p.stderr or p.stdout)[-300:]}
    if isinstance(data, list):                # some CLI builds print the whole event list
        data = next((e for e in reversed(data) if isinstance(e, dict) and e.get("type") == "result"), {})
    return str(data.get("result") or ""), {"cost": data.get("total_cost_usd"), "turns": data.get("num_turns"),
                                           "error": data.get("subtype") if data.get("is_error") else None}


def parse(text: str) -> list[dict]:
    a, b = text.find("["), text.rfind("]")
    if a < 0 or b < a:
        return []
    try:
        rows = json.loads(text[a:b + 1])
    except ValueError:
        return []
    return [r for r in rows if isinstance(r, dict) and "id" in r]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--stores-root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--max-pages", type=int, default=0)
    args = ap.parse_args()
    out = Path(args.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    verdicts = out / "verdicts.jsonl"
    done = {int(r["id"]) for r in jlines(verdicts)}
    idx = store_index(args.stores_root, out / "store_index.json")
    con = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    q = ("select symbol, doc_key, page, " + ", ".join(FIELDS) + " from observation where status='unverified' "
         "and record_type='number' and entity_scope='company' and value is not null order by doc_key, page")
    pages: dict[tuple[str, int], list[dict]] = {}
    syms: dict[tuple[str, int], str] = {}
    for r in con.execute(q):
        if int(r["observation_id"]) in done:
            continue
        key = (r["doc_key"], int(r["page"]))
        pages.setdefault(key, []).append({f: r[f] for f in FIELDS})
        syms[key] = r["symbol"]
    keys = list(pages)[: args.max_pages or None]
    print(f"{len(done)} rows done, {sum(len(pages[k]) for k in keys)} rows on {len(keys)} pages to check", flush=True)
    for i in range(0, len(keys), PAGES_PER_RUN):
        part = keys[i:i + PAGES_PER_RUN]
        blocks = []
        for k in part:
            store = idx.get(k[0])
            text = obs.page_text_of(store, k[0], k[1]) if store else ""
            if not text.strip():
                continue
            blocks.append({"company_symbol": syms[k], "doc_key": k[0], "page": k[1], "page_text": text[:12000],
                           "rows": pages[k]})
        if not blocks:
            continue
        while True:
            ok, why = quota_ok()
            if ok:
                break
            print(f"  paused: {why}", flush=True)
            time.sleep(300)
        t0 = time.time()
        text, meta = run_claude(RULES + "\n\nPages and rows:\n" + json.dumps(blocks, ensure_ascii=False, indent=1),
                                out / "logs" / f"run_{i // PAGES_PER_RUN:04d}.json")
        got = parse(text)
        want = {int(r["observation_id"]) for b in blocks for r in b["rows"]}
        with verdicts.open("a", encoding="utf-8") as fh:
            for r in got:
                try:
                    rid = int(r["id"])
                except (TypeError, ValueError):
                    continue
                if rid in want:
                    r.update(id=rid, checker="claude-sonnet medium", checked_at=dt.datetime.now().isoformat("T", "seconds"))
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"  run {i // PAGES_PER_RUN}: {len(blocks)} pages, {len(want)} rows, {len(got)} verdicts, "
              f"{time.time() - t0:.0f}s, {why}, err={meta.get('error')}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
