"""Randomised question trials over the Telegram-queue stores (Shivam 16 Nov: build all, then trial 1, 2, ...).

A trial draws questions at random from ``D:/RealityEngine/tg_build/questions.db`` (4,164 investor questions, 91
companies), K per company, half from the frozen set (scored, never drives a fix) and half from the open set (drives
the fixes).  Workers answer them through ``p3ask --db <store>`` (the same lookups the reality-data MCP serves), a
separate grader grades them, and ``answer_run_report`` writes Shivam's Excel + CSV.

    python -m reality_engine.scripts.tg_trial sample --trial 1 [--per-company 2] [--batches 4] [--seed 1]
    python -m reality_engine.scripts.tg_trial merge  --trial 1        # answers + grades -> graded.jsonl

``sample`` writes ``<trials>/trial<N>/questions.jsonl`` (qid, symbol, store_db, question, theme, kind,
data_needed, frozen, as_of) and ``batch_XX.jsonl`` files, one per worker, each a balanced share of companies.
``--repeat <trial>`` also re-asks that trial's open questions (to check the fixes); frozen questions are never
repeated in a fix loop.  ``merge`` joins ``answers/*.jsonl`` and ``grades/*.jsonl`` on qid into ``graded.jsonl``
in the answer_run_report input format and prints the right-rate on frozen and open questions apart.
"""
from __future__ import annotations

import argparse
import csv
import json
import random
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path("D:/RealityEngine/tg_build")
QUESTIONS = ROOT / "questions.db"
STORES = ROOT / "measure10"
TRIALS = ROOT / "trials"
AS_OF = "2026-11-16"        # the build window's end: the questions were harvested against the latest filings


def store_map(stores: Path = STORES, universe: str = "universe91.csv") -> dict[str, str]:
    """symbol -> built store db (cNN/cNN.db), in queue order; a company whose store is not built is left out."""
    out = {}
    with (stores / universe).open(newline="", encoding="utf-8") as fh:
        for i, row in enumerate(csv.DictReader(fh), start=1):
            db = stores / f"c{i:02d}" / f"c{i:02d}.db"
            if (stores / f"c{i:02d}" / f"c{i:02d}_measure.json").is_file() and db.is_file():
                out[row["symbol"]] = db.as_posix()
    return out


def sample(trial: int, per_company: int = 2, batches: int = 4, seed: int = 1, repeat: int | None = None,
           questions: Path = QUESTIONS, stores: Path = STORES, trials: Path = TRIALS) -> dict:
    rng = random.Random(seed * 1000 + trial)
    smap = store_map(stores)
    con = sqlite3.connect(f"file:{questions.as_posix()}?mode=ro", uri=True)
    rows = con.execute("SELECT id, symbol, isin, question, theme, kind, data_needed, frozen FROM question "
                       "WHERE kind != 'found_unverified' ORDER BY id").fetchall()
    con.close()
    asked = set()
    for old in trials.glob("trial*/questions.jsonl"):
        asked |= {json.loads(line)["qid"] for line in old.open(encoding="utf-8")}
    by_sym: dict[str, dict[int, list]] = defaultdict(lambda: {0: [], 1: []})
    for qid, sym, isin, q, theme, kind, need, frozen in rows:
        if sym in smap and qid not in asked:
            by_sym[sym][int(frozen)].append((qid, sym, isin, q, theme, kind, need, int(frozen)))
    picked = []
    for sym in smap:
        for k in range(per_company):
            pool = by_sym[sym][k % 2]          # alternate: frozen 0 (open) first, then frozen 1
            if pool:
                picked.append(pool.pop(rng.randrange(len(pool))))
    if repeat is not None:
        prev = trials / f"trial{repeat}" / "questions.jsonl"
        picked += [tuple(r[k] for k in ("qid", "symbol", "isin", "question", "theme", "kind", "data_needed",
                                        "frozen"))
                   for r in map(json.loads, prev.open(encoding="utf-8")) if not r["frozen"]]
    out = trials / f"trial{trial}"
    (out / "answers").mkdir(parents=True, exist_ok=True)
    (out / "grades").mkdir(parents=True, exist_ok=True)
    recs = [dict(qid=qid, symbol=sym, isin=isin, store_db=smap[sym], question=q, theme=theme, kind=kind,
                 data_needed=need, frozen=frozen, as_of=AS_OF)
            for qid, sym, isin, q, theme, kind, need, frozen in picked]
    with (out / "questions.jsonl").open("w", encoding="utf-8") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    syms = list(dict.fromkeys(r["symbol"] for r in recs))
    for b in range(batches):                  # whole companies per batch, round-robin in queue order
        mine = set(syms[b::batches])
        with (out / f"batch_{b + 1:02d}.jsonl").open("w", encoding="utf-8") as fh:
            for r in recs:
                if r["symbol"] in mine:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    return {"trial": trial, "questions": len(recs), "companies": len(syms), "frozen": sum(r["frozen"] for r in recs),
            "batches": batches, "out": out.as_posix()}


def merge(trial: int, trials: Path = TRIALS) -> dict:
    out = trials / f"trial{trial}"
    qs = {r["qid"]: r for r in map(json.loads, (out / "questions.jsonl").open(encoding="utf-8"))}

    def load(folder: str) -> dict:
        got = {}
        for f in sorted((out / folder).glob("*.jsonl")):
            for line in f.open(encoding="utf-8"):
                line = line.strip()
                if line:
                    r = json.loads(line)
                    got[r["qid"]] = r
        return got

    answers, grades = load("answers"), load("grades")
    rows, score = [], {0: Counter(), 1: Counter()}
    for qid, q in qs.items():
        a, g = answers.get(qid, {}), grades.get(qid, {})
        grade = g.get("grade") or ("" if a else "unanswered")
        score[q["frozen"]][grade] += 1
        rows.append({"run_id": f"tg_trial{trial}", "qid": qid, "symbol": q["symbol"], "question": q["question"],
                     "reframed_question": a.get("reframed_question", ""), "as_of": q["as_of"],
                     "use": "frozen" if q["frozen"] else "open", "kind": q["theme"], "tools": a.get("tools", []),
                     "answer": a.get("answer", ""), "sources": a.get("sources", []), "grade": grade,
                     "error": g.get("error", ""), "root_cause": g.get("root_cause", ""), "fix": g.get("fix", ""),
                     "source_if_missing": g.get("source_if_missing", ""), "gap": a.get("gap", "")})
    with (out / "graded.jsonl").open("w", encoding="utf-8") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    def rate(c: Counter) -> str:
        n = sum(c.values())
        return f"{c['right']}/{n} right ({100 * c['right'] / n:.0f}%)" if n else "none"

    return {"graded": len(rows), "answered": len(answers), "frozen": rate(score[1]), "open": rate(score[0]),
            "frozen_grades": dict(score[1]), "open_grades": dict(score[0])}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("sample")
    s.add_argument("--trial", type=int, required=True)
    s.add_argument("--per-company", type=int, default=2)
    s.add_argument("--batches", type=int, default=4)
    s.add_argument("--seed", type=int, default=1)
    s.add_argument("--repeat", type=int, default=None, help="also re-ask this trial's open questions")
    m = sub.add_parser("merge")
    m.add_argument("--trial", type=int, required=True)
    a = ap.parse_args(argv)
    res = sample(a.trial, a.per_company, a.batches, a.seed, a.repeat) if a.cmd == "sample" else merge(a.trial)
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
