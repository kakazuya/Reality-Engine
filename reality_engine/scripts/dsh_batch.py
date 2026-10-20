"""Run a JSONL of worker tasks in parallel through run_deepseek_harness and print ONE compact summary table.

    python -m reality_engine.scripts.dsh_batch --tasks tasks.jsonl --model beam-free [--workers 3]
        [--account 2] [--timeout 900] [--summary summary.json] [--allow-paid] [--peak-ok]

Each JSONL line: {"id": str, "task": str, "source_file": str (optional), "out": str, "model": str (optional)}.
If an output parses as a JSON array whose items carry "quote" fields and source_file is given, every quote is
checked as a whitespace-normalised exact substring of source_file (mechanical, no LLM). Stdout gets only the table;
the full per-task detail (every missed quote) goes to summary.json. Worker output stays in each task's `out` file.
The DeepSeek rules are those of run_deepseek_harness (xhigh only, off-peak (not Mon-Fri 06:30-09:30, 11:30-15:30 IST) unless --peak-ok,
paid models need --allow-paid) and are enforced up front, before any task starts.
"""
import argparse
import json
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from reality_engine.scripts import run_deepseek_harness as h

REPO = h.REPO


def norm(s):
    return re.sub(r"\s+", " ", s).strip()


def parse_json(text):
    """The first JSON array/object in a worker answer, tolerating code fences and surrounding prose."""
    text = text.strip()
    for cand in (text, re.sub(r"^```\w*\s*|\s*```$", "", text)):
        try:
            return json.loads(cand)
        except ValueError:
            pass
    start = min((i for i in (text.find("["), text.find("{")) if i >= 0), default=-1)
    if start < 0:
        return None
    try:
        return json.JSONDecoder().raw_decode(text[start:])[0]
    except ValueError:
        return None


def collect_quotes(node, acc):
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "quote" and isinstance(v, str):
                acc.append(v)
            else:
                collect_quotes(v, acc)
    elif isinstance(node, list):
        for v in node:
            collect_quotes(v, acc)
    return acc


def check_output(out_path, source_file):
    """-> (items, quotes_total, misses). items None when the output is not a JSON array."""
    data = parse_json(Path(out_path).read_text(encoding="utf-8", errors="replace")) if Path(out_path).exists() else None
    if not isinstance(data, list):
        return None, 0, []
    quotes = collect_quotes(data, [])
    if not source_file:
        return len(data), 0, []
    src = norm(Path(source_file).read_text(encoding="utf-8", errors="replace"))
    return len(data), len(quotes), [q for q in quotes if norm(q) not in src]


def run_one(t, a):
    out = Path(t["out"])
    if not out.is_absolute():
        out = REPO / out
    model = t.get("model") or a.model
    cmd = [sys.executable, "-m", "reality_engine.scripts.run_deepseek_harness", "--model", model,
           "--task", t["task"], "--out-file", str(out), "--account", a.account, "--timeout", str(a.timeout)]
    if a.allow_paid:
        cmd.append("--allow-paid")
    if a.peak_ok:
        cmd.append("--peak-ok")
    t0 = time.time()
    p = subprocess.run(cmd, cwd=REPO, capture_output=True, text=True, encoding="utf-8", errors="replace")
    row = {"id": t["id"], "model": model, "rc": p.returncode, "secs": round(time.time() - t0), "out": str(out),
           "items": None, "quotes_total": 0, "quotes_ok": 0, "misses": [], "error": ""}
    if p.returncode:
        row["error"] = (p.stderr.strip().splitlines() or ["failed"])[-1][:200]
    sf = t.get("source_file")
    if sf:
        sf = str(Path(sf) if Path(sf).is_absolute() else REPO / sf)
    items, total, misses = check_output(out, sf)
    row.update(items=items, quotes_total=total, quotes_ok=total - len(misses), misses=misses)
    return row


def table(rows):
    head = ["id", "rc", "secs", "items", "quotes", "first miss"]
    body = []
    for r in rows:
        q = f"{r['quotes_ok']}/{r['quotes_total']}" if r["quotes_total"] else "-"
        miss = (r["misses"][0] if r["misses"] else r["error"]).replace("\n", " ")[:60]
        body.append([r["id"], r["rc"], r["secs"], "-" if r["items"] is None else r["items"], q, miss])
    cells = [head] + [[str(c) for c in b] for b in body]
    w = [max(len(c[i]) for c in cells) for i in range(len(head))]
    return "\n".join("  ".join(c.ljust(w[i]) for i, c in enumerate(row)).rstrip() for row in cells)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--tasks", required=True, help="JSONL of {id, task, source_file?, out, model?}")
    ap.add_argument("--model", required=True, help="default Go model id for tasks without their own")
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--account", choices=("1", "2"), default="2")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--summary", default=None, help="summary.json path (default: next to the tasks file)")
    ap.add_argument("--allow-paid", action="store_true")
    ap.add_argument("--peak-ok", action="store_true", help="DeepSeek at peak (Mon-Fri 06:30-09:30, 11:30-15:30 IST), only after Shivam confirms")
    a = ap.parse_args()

    tasks = [json.loads(ln) for ln in Path(a.tasks).read_text(encoding="utf-8").splitlines() if ln.strip()]
    for t in tasks:
        missing = {"id", "task", "out"} - t.keys()
        if missing:
            sys.exit(f"task {t.get('id')!r} missing {sorted(missing)}")
    for model in {(t.get("model") or a.model).partition("~")[0] for t in tasks}:
        if model not in h.FREE | h.PAID:
            sys.exit(f"unknown Go model {model!r}; known: {sorted(h.FREE | h.PAID)}")
        if model in h.PAID and not a.allow_paid:
            sys.exit(f"{model} is PAID on Go; pass --allow-paid only with Shivam's approval")
        if model.startswith("deepseek") and not h.off_peak() and not a.peak_ok:
            sys.exit(f"{datetime.now(h.IST):%H:%M} IST is in DeepSeek peak hours (Mon-Fri 06:30-09:30, 11:30-15:30 IST); "
                     "ask Shivam, then pass --peak-ok if he confirms")
    for t in tasks:   # xhigh-only rule: the wrapper rejects other efforts; fail before spending anything
        m, _, eff = (t.get("model") or a.model).partition("~")
        if m in h.FIXED_EFFORT and eff and eff != h.FIXED_EFFORT[m]:
            sys.exit(f"{m} always runs at {h.FIXED_EFFORT[m]}; drop ~{eff}")

    with ThreadPoolExecutor(max_workers=max(1, a.workers)) as ex:
        rows = list(ex.map(lambda t: run_one(t, a), tasks))

    summary = Path(a.summary) if a.summary else Path(a.tasks).with_name("summary.json")
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text(json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    print(table(rows))
    sys.exit(1 if any(r["rc"] for r in rows) else 0)


if __name__ == "__main__":
    main()
