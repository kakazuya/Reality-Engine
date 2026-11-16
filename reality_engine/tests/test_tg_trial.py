"""tg_trial: balanced random sample (open + frozen per company), batches by whole company, merge scores apart."""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts import tg_trial


@pytest.fixture
def tmp():
    d = Path(__file__).resolve().parents[2] / ".tmp" / f"tg_trial_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True)
    try:
        yield d
    finally:
        shutil.rmtree(d, ignore_errors=True)


def _setup(tmp: Path) -> tuple[Path, Path]:
    stores = tmp / "stores"
    stores.mkdir()
    (stores / "universe91.csv").write_text("isin,symbol\nI1,AAA\nI2,BBB\nI3,CCC\n", encoding="utf-8")
    for i in (1, 2):                                   # CCC (c03) is not built yet
        d = stores / f"c{i:02d}"
        d.mkdir()
        (d / f"c{i:02d}.db").write_bytes(b"")
        (d / f"c{i:02d}_measure.json").write_text("{}", encoding="utf-8")
    q = tmp / "questions.db"
    con = sqlite3.connect(q)
    con.execute("CREATE TABLE question (id INTEGER PRIMARY KEY, isin TEXT, symbol TEXT, question TEXT, theme TEXT, "
                "kind TEXT, data_needed TEXT, frozen INTEGER)")
    n = 0
    for sym in ("AAA", "BBB", "CCC"):
        for frozen in (0, 0, 0, 1, 1, 1):
            n += 1
            con.execute("INSERT INTO question VALUES (?,?,?,?,?,?,?,?)",
                        (n, "I", sym, f"q{n}", "accounting", "found", "", frozen))
    con.commit()
    con.close()
    return stores, q


def test_sample_takes_one_open_and_one_frozen_per_built_company_and_never_repeats(tmp):
    stores, q = _setup(tmp)
    res = tg_trial.sample(1, 2, 2, 1, None, q, stores, tmp / "trials")
    recs = [json.loads(x) for x in (tmp / "trials" / "trial1" / "questions.jsonl").open()]
    assert res["questions"] == 4 and res["companies"] == 2 and res["frozen"] == 2
    assert sorted((r["symbol"], r["frozen"]) for r in recs) == [("AAA", 0), ("AAA", 1), ("BBB", 0), ("BBB", 1)]
    b1 = [json.loads(x)["symbol"] for x in (tmp / "trials" / "trial1" / "batch_01.jsonl").open()]
    assert set(b1) == {"AAA"}                          # whole companies per batch
    tg_trial.sample(2, 2, 1, 1, None, q, stores, tmp / "trials")
    again = [json.loads(x)["qid"] for x in (tmp / "trials" / "trial2" / "questions.jsonl").open()]
    assert not set(again) & {r["qid"] for r in recs}   # a later trial draws new questions
    tg_trial.sample(3, 2, 1, 1, 1, q, stores, tmp / "trials")
    rep = [json.loads(x) for x in (tmp / "trials" / "trial3" / "questions.jsonl").open()]
    assert {r["qid"] for r in recs if not r["frozen"]} <= {r["qid"] for r in rep}   # --repeat re-asks open only


def test_merge_scores_frozen_and_open_apart(tmp):
    stores, q = _setup(tmp)
    tg_trial.sample(1, 2, 1, 1, None, q, stores, tmp / "trials")
    out = tmp / "trials" / "trial1"
    recs = [json.loads(x) for x in (out / "questions.jsonl").open()]
    with (out / "answers" / "a.jsonl").open("w") as fh:
        for r in recs:
            fh.write(json.dumps({"qid": r["qid"], "answer": "x"}) + "\n")
    with (out / "grades" / "g.jsonl").open("w") as fh:
        for r in recs:
            fh.write(json.dumps({"qid": r["qid"], "grade": "right" if r["frozen"] else "wrong"}) + "\n")
    res = tg_trial.merge(1, tmp / "trials")
    assert res["frozen"].startswith("2/2") and res["open"].startswith("0/2")


def test_check_flags_give_ups_after_one_tool_kind(tmp):
    def w(name, rows):
        p = tmp / name
        p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return p
    batch = w("b.jsonl", [{"qid": q} for q in (1, 2, 3, 4)])
    answers = w("a.jsonl", [{"qid": 1, "status": "answered"}, {"qid": 2, "status": "not_found"},
                            {"qid": 3, "status": "partly"}])
    calls = w("c.jsonl", [{"qid": 1, "tool": "fact"}, {"qid": "2", "tool": "search"}, {"qid": 2, "tool": "search"},
                          {"qid": 3, "tool": "search"}, {"qid": 3, "tool": "statements"}])
    bad = dict(tg_trial.check(answers, calls, batch))
    assert set(bad) == {2, 4}                       # 1 answered, 3 tried two tool kinds
    assert "1 tool kinds" in bad[2] and bad[4] == "no answer"
