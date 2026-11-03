"""Tests for the night loop's deterministic checks (T-055).

Everything is built here: a small sqlite fixture database with the pilot3 tables the checks read, six-question
fixture sets per sector, and a temporary git repository for the A5 literal and protected-file scans.  pytest's
``tmp_path`` is denied in the dsh sandbox, so the work dir is ``.tmp/night_eval/test/<test>``.  No model call.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Any

from reality_engine.night_eval import answerable, audit, decide, guards, qset, run_loop

ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp" / "night_eval" / "test"

VOCAB: dict[str, dict[str, list[str]]] = {
    "metals": {"order_book": ["order book"], "revenue": ["revenue"], "ebitda_margin": ["EBITDA margin"],
               "net_margin_pct": ["net margin"], "pat": ["profit after tax"]},
    "lender": {"nim": ["NIM"], "aum": ["AUM"], "credit_cost": ["credit cost"], "gnpa": ["GNPA"], "pat": ["PAT"]},
    "epc": {"order_book": ["order book"], "order_intake": ["order intake"], "revenue": ["revenue"],
            "ebitda_margin": ["EBITDA margin"], "pat": ["PAT"]},
}

DDL = """
CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, isin TEXT, doc_type TEXT, doc_family TEXT, title TEXT,
    filing_date TEXT, known_at TEXT, pages INTEGER, sha256 TEXT, source TEXT, source_key TEXT);
CREATE TABLE doc_page (doc_key TEXT, symbol TEXT, page INTEGER, text TEXT, method TEXT, chars INTEGER,
    known_at TEXT, ocr_conf REAL, PRIMARY KEY (doc_key, page));
CREATE VIRTUAL TABLE doc_page_fts USING fts5(text, content='doc_page', content_rowid='rowid',
    tokenize='unicode61 remove_diacritics 2');
CREATE TABLE kpi_series (symbol TEXT, metric TEXT, fiscal_period TEXT, basis TEXT, value REAL, unit TEXT,
    known_at TEXT, doc_key TEXT, page INTEGER, quote TEXT);
CREATE TABLE fin_quarter_xbrl (symbol TEXT, fiscal_period TEXT, basis TEXT, line_item TEXT, value REAL,
    known_at TEXT);
CREATE TABLE ratio_panel (symbol TEXT, fiscal_period TEXT, basis TEXT, metric TEXT, value REAL, known_at TEXT);
CREATE TABLE guidance (symbol TEXT, metric TEXT, target_period TEXT, low REAL, high REAL, known_at TEXT,
    doc_key TEXT, page INTEGER, quote TEXT);
"""


# --- fixtures -------------------------------------------------------------------------------------------
def _unlink_readonly(func, path, _exc: object) -> None:
    """Windows: git writes read-only object files, so clear the bit and retry the same call."""
    import os
    import stat

    os.chmod(path, stat.S_IWRITE | stat.S_IREAD)
    func(path)


def workdir(name: str) -> Path:
    path = TMP / name
    if path.exists():
        shutil.rmtree(path, onexc=_unlink_readonly)
    path.mkdir(parents=True)
    return path


def row_need(table: str = "kpi_series", metric: str | None = "order_book", period: str = "Q2FY26",
             basis: str | None = "consolidated") -> dict[str, Any]:
    return {"kind": "row", "table": table, "metric": metric, "period": period, "basis": basis}


def text_need(doc_type: str = "transcript", terms: list[str] | tuple[str, ...] = ("order", "book"),
              period: str | None = None) -> dict[str, Any]:
    return {"kind": "text", "doc_type": doc_type, "terms": list(terms), "period": period}


def question(qid: str, *, order: int = 1, lens: str = "results", sector: str = "metals", symbol: str = "KEC",
             needs: list[dict[str, Any]] | None = None, text: str | None = None,
             variations: list[str] | None = None, **extra: Any) -> dict[str, Any]:
    made = {"qid": qid, "symbol": symbol, "sector": sector,
            "text": text or f"{qid}: what did revenue do last quarter",
            "variations": variations if variations is not None else [
                f"{qid} variation alpha sales trajectory", f"{qid} variation beta margin comparison",
                f"{qid} variation gamma dated last quarter"],
            "order": order, "lens": lens, "sector_fit": [], "from_mids": "new", "new_reason": "fixture",
            "as_of": "2026-11-01", "answer_kind": "number", "needs": needs if needs is not None else [row_need()]}
    made.update(extra)
    return made


def six_questions(sector: str) -> list[dict[str, Any]]:
    """The six-question fixture set for one sector: three first order, two second, one third."""
    metrics = list(VOCAB[sector])
    rows = [(1, "results", row_need("kpi_series", metrics[0], "Q2FY26")),
            (1, "orders", text_need("transcript", ["order", "book"])),
            (1, "segments", row_need("fin_quarter_xbrl", "revenue_from_operations", "Q2FY26")),
            (2, "margins", row_need("ratio_panel", "net_margin_pct", "Q2FY26")),
            (2, "guidance", row_need("guidance", "ebitda_margin", "FY26", None)),
            (3, "ownership", text_need("deck", ["revenue"]))]
    return [question(f"{sector}-{index}", sector=sector, order=order, lens=lens, needs=[need],
                     sector_fit=[metrics[0]])
            for index, (order, lens, need) in enumerate(rows)]


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
    return path


def write_vocab(work: Path, vocab: dict[str, dict[str, list[str]]] | None = None) -> Path:
    path = work / "sector_vocab.json"
    path.write_text(json.dumps(vocab or VOCAB), encoding="utf-8")
    return path


def build_db(path: Path, *, bad_row: bool = False) -> Path:
    """A small database with the pilot3 tables the checks read: one good deck, one transcript, one early doc."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.executescript(DDL)
    docs = [("KEC_deck_2026-07-20", "deck", "2026-07-20", "a" * 64),
            ("KEC_transcript_2026-07-25", "transcript", "2026-07-25", "a" * 64),   # same sha256: a duplicate
            ("KEC_early_2025", "deck", "2025-05-01", "c" * 64)]
    con.executemany("INSERT INTO doc (doc_key, symbol, doc_type, title, filing_date, known_at, pages, sha256) "
                    "VALUES (?, 'KEC', ?, ?, ?, ?, 3, ?)",
                    [(key, dtype, key, filed, filed, sha) for key, dtype, filed, sha in docs])
    pages = [("KEC_deck_2026-07-20", 1, "Q2FY26 order book stood at 1,234 crore as of June 2026"),
             ("KEC_deck_2026-07-20", 2, "Q2FY26 revenue was 200 crore"),
             ("KEC_deck_2026-07-20", 3, "FY26 ebitda margin guided at 0.12 to 0.14"),
             ("KEC_transcript_2026-07-25", 1, "The order book grew well during the quarter on new wins"),
             ("KEC_early_2025", 1, "profit after tax was 50 crore in the quarter"),
             ("KEC_early_2025", 2, "unrelated page text")]
    con.executemany("INSERT INTO doc_page (doc_key, symbol, page, text, known_at) VALUES (?, 'KEC', ?, ?, '2026-11-01')",
                    pages)
    con.execute("INSERT INTO doc_page_fts (doc_page_fts) VALUES ('rebuild')")
    kpi = [("KEC", "order_book", "Q2FY26", "consolidated", 1234.0, "2026-07-20", "KEC_deck_2026-07-20", 1,
            "Q2FY26 order book stood at 1,234 crore as of June 2026"),
           ("KEC", "revenue", "Q2FY26", "consolidated", 200.0, "2026-07-20", "KEC_deck_2026-07-20", 2,
            "Q2FY26 revenue was 200 crore"),
           ("KEC", "pat", "Q2FY26", "consolidated", 50.0, "2025-04-01", "KEC_early_2025", 1,
            "profit after tax was 50 crore in the quarter")]
    if bad_row:
        kpi.append(("KEC", "order_intake", "Q2FY26", "consolidated", 777.0, "2026-07-20", "KEC_early_2025", 2,
                    "nothing here at all"))
    con.executemany("INSERT INTO kpi_series (symbol, metric, fiscal_period, basis, value, known_at, doc_key, page, "
                    "quote) VALUES (?,?,?,?,?,?,?,?,?)", kpi)
    con.execute("INSERT INTO fin_quarter_xbrl (symbol, fiscal_period, basis, line_item, value, known_at) "
                "VALUES ('KEC', 'Q2FY26', 'consolidated', 'revenue_from_operations', 100.0, '2026-07-20')")
    con.execute("INSERT INTO ratio_panel (symbol, fiscal_period, basis, metric, value, known_at) "
                "VALUES ('KEC', 'Q2FY26', 'consolidated', 'net_margin_pct', 150.0, '2026-07-20')")
    con.execute("INSERT INTO guidance (symbol, metric, target_period, low, high, known_at, doc_key, page, quote) "
                "VALUES ('KEC', 'ebitda_margin', 'FY26', 0.12, 0.14, '2026-07-20', 'KEC_deck_2026-07-20', 3, "
                "'FY26 ebitda margin guided at 0.12 to 0.14')")
    con.commit()
    con.close()
    return path


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=str(repo), capture_output=True, text=True, check=True).stdout


def repo_with_branches(work: Path) -> Path:
    """A repository with ``main`` (base), ``dirty`` (a company literal and a changed assertion), ``clean``."""
    repo = work / "repo"
    (repo / "reality_engine" / "pilot3").mkdir(parents=True)
    (repo / "reality_engine" / "tests").mkdir(parents=True)
    (repo / "reality_engine" / "pilot3" / "kpi.py").write_text("x = 1\n", encoding="utf-8")
    (repo / "reality_engine" / "pilot3" / "build.py").write_text("y = 2\n", encoding="utf-8")
    (repo / "reality_engine" / "tests" / "test_kpi.py").write_text("assert a == 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "night_eval@example.com")
    _git(repo, "config", "user.name", "night_eval")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "checkout", "-q", "-b", "dirty")
    (repo / "reality_engine" / "pilot3" / "kpi.py").write_text('x = 1\nLITERAL = "KEC"\n', encoding="utf-8")
    (repo / "reality_engine" / "tests" / "test_kpi.py").write_text("assert a == 2\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "dirty")
    _git(repo, "checkout", "-q", "main")
    _git(repo, "checkout", "-q", "-b", "clean")
    (repo / "reality_engine" / "pilot3" / "kpi.py").write_text("x = 1\ny = 3\n", encoding="utf-8")
    _git(repo, "commit", "-qam", "clean")
    _git(repo, "checkout", "-q", "main")
    return repo


# --- qset: schema, Q1, Q2, Q3, split --------------------------------------------------------------------
def test_qset_schema_validation():
    work = workdir("qset_schema")
    questions = work / "questions"
    bad = question("q-bad-order", order=4)
    bad.pop("sector")
    write_jsonl(questions / "KEC.jsonl", [bad, question("q-good")])
    report = qset.check(questions, write_vocab(work))
    joined = " ".join("; ".join(e["errors"]) for e in report["schema_errors"])
    assert "order" in joined and "sector" in joined
    assert not report["ok"] and report["schema_errors"]


def test_q1_off_sector_metric_fails():
    work = workdir("q1")
    questions = work / "questions"
    write_jsonl(questions / "KEC.jsonl", [
        question("q-off", sector="metals", sector_fit=["nim"], needs=[row_need("kpi_series", "nim", "Q2FY26")]),
        question("q-on", sector="metals", sector_fit=["order_book"]),
    ])
    report = qset.check(questions, write_vocab(work))
    found = [(v["qid"], v["metric"], v["kind"]) for v in report["q1"]["violations"]]
    assert ("q-off", "nim", "sector_fit") in found
    assert ("q-off", "nim", "need") in found
    assert not report["q1"]["ok"] and not report["ok"]


def test_q2_order_rule_thirty_percent_passes_five_percent_fails():
    assert qset.order_rule([1] * 4 + [2] * 3 + [3] * 3) == []
    fails = qset.order_rule([1] * 10 + [2] * 9 + [3] * 1)
    assert len(fails) == 1 and "order 3" in fails[0]


def test_q2_company_report_counts_lens_and_doc_types():
    work = workdir("q2")
    questions = work / "questions"
    write_jsonl(questions / "KEC.jsonl", six_questions("metals"))
    report = qset.check(questions, write_vocab(work))
    company = report["q2"]["companies"]["KEC"]
    assert company["questions"] == 6 and company["orders"]["3"] == 1 and company["order_rates"]["1"] == 0.5
    assert set(company["doc_types"]) == {"transcript", "deck"}
    assert any("lens results" in fail for fail in company["fails"])   # a fixture set is far under 10 per lens


def test_q3_order_one_needs_three_variations():
    report = qset.q3_variations([question("q-var", order=1, variations=["only one", "only two"])])
    assert report["short_variations"] == ["q-var"] and not report["ok"]


def test_q3_near_duplicate_is_flagged():
    text = "what was revenue and ebitda margin in the september quarter"
    variations = ["same form one", "same form two", "same form three"]
    report = qset.q3_variations([question("q-dup-a", text=text, variations=variations),
                                 question("q-dup-b", text=text, variations=variations)])
    assert report["duplicates"] and report["duplicates"][0]["jaccard"] == 1.0
    assert not report["ok"]


def test_split_is_the_fixed_hash_and_keeps_hidden_out_of_dev():
    work = workdir("split")
    questions = work / "questions"
    rows = six_questions("metals") + six_questions("lender") + six_questions("epc")
    write_jsonl(questions / "KEC.jsonl", rows)
    dev_path, hidden_path = work / "dev.jsonl", work / "hidden.jsonl"
    report = qset.split(questions, dev_path, hidden_path)
    dev = [json.loads(line)["qid"] for line in dev_path.read_text(encoding="utf-8").splitlines()]
    hidden = [json.loads(line)["qid"] for line in hidden_path.read_text(encoding="utf-8").splitlines()]
    expected_dev = [q["qid"] for q in rows
                    if int(hashlib.sha256(q["qid"].encode()).hexdigest()[:8], 16) % 10 < 7]
    assert report["total"] == 18 and sorted(dev) == sorted(expected_dev)
    assert sorted(dev + hidden) == sorted(q["qid"] for q in rows)
    assert report["dev"] == len(dev) and report["hidden"] == len(hidden)


# --- answerable: A1 ------------------------------------------------------------------------------------
def test_planted_row_turns_an_unmet_need_into_a_met_one():
    work = workdir("a1_row")
    db_path = build_db(work / "pilot3.db")
    ask = question("q-a1", needs=[row_need("kpi_series", "ebitda_margin", "Q2FY26")])
    db = answerable.Db(db_path)
    before = answerable.score([ask], db)
    db.close()
    assert before["a1"]["total"]["none"] == 1 and before["unmet"] == [{"key": "kpi_series.ebitda_margin", "count": 1}]
    raw = sqlite3.connect(db_path)
    raw.execute("INSERT INTO kpi_series (symbol, metric, fiscal_period, basis, value, known_at, doc_key, page, quote)"
                " VALUES ('KEC', 'ebitda_margin', 'Q2FY26', 'consolidated', 13.5, '2026-07-20', "
                "'KEC_deck_2026-07-20', 3, 'ebitda margin was 13.5 percent')")
    raw.commit()
    raw.close()
    db = answerable.Db(db_path)
    after = answerable.score([ask], db)
    db.close()
    assert after["a1"]["total"]["all"] == 1 and after["unmet"] == []


def test_text_need_uses_the_pilot3_search_and_hidden_prints_counts_only(capsys):
    work = workdir("a1_text")
    db_path = build_db(work / "pilot3.db")
    qset_path = write_jsonl(work / "set.jsonl", [
        question("q-text-met", needs=[text_need("transcript", ["order", "book"])]),
        question("q-text-unmet", needs=[text_need("transcript", ["order", "book", "hospital"])]),
    ])
    out = work / "out.json"
    assert answerable.main(["--db", str(db_path), "--qset", str(qset_path), "--out", str(out)]) == 0
    report = json.loads(out.read_text(encoding="utf-8"))
    assert {row["qid"]: row["status"] for row in report["questions"]} == {"q-text-met": "all",
                                                                         "q-text-unmet": "none"}
    assert report["a1"]["total"]["rate"] == 0.5
    capsys.readouterr()
    assert answerable.main(["--db", str(db_path), "--qset", str(qset_path), "--hidden", "--out", str(out)]) == 0
    printed = capsys.readouterr().out
    assert "q-text-met" not in printed and "q-text-unmet" not in printed
    hidden_report = json.loads(out.read_text(encoding="utf-8"))
    assert "questions" not in hidden_report and "unmet" not in hidden_report
    assert hidden_report["hidden"] is True and hidden_report["a1"]["total"]["questions"] == 2


def test_pilot3_search_import_survives_a_foreign_core_module():
    """Another test suite's module named ``core`` must not shadow the server's (it did before this guard)."""
    import types

    work = workdir("core_shadow")
    assert work.is_dir()
    fake = types.ModuleType("core")
    original = sys.modules.get("core")
    answerable._PILOT3_MODULE = None
    sys.modules["core"] = fake
    try:
        module = answerable._pilot3_search()
        assert module.__name__ == "lookups_pilot3"
        assert hasattr(module.core, "connect_ro")
        assert sys.modules["core"] is fake
    finally:
        answerable._PILOT3_MODULE = None
        if original is None:
            sys.modules.pop("core", None)
        else:
            sys.modules["core"] = original


# --- guards: A3, A4, A5 --------------------------------------------------------------------------------
def test_a3_provenance_passes_a_clean_db_and_fails_a_bad_row():
    work = workdir("a3")
    clean = guards.a3_provenance(build_db(work / "clean.db"))
    assert clean["checked"] == 4 and clean["rate"] == 1.0 and clean["ok"]
    bad = guards.a3_provenance(build_db(work / "bad.db", bad_row=True))
    assert bad["rate"] < 0.98 and not bad["ok"] and bad["examples"]
    assert bad["examples"][0]["value_in_quote"] is False or bad["examples"][0]["quote_on_page"] is False


def test_a3_added_rows_only_with_a_base_db():
    work = workdir("a3_base")
    base = build_db(work / "base.db")
    branch = build_db(work / "branch.db", bad_row=True)
    report = guards.a3_provenance(branch, base_db=base)
    assert report["scope"] == "added_rows" and report["checked"] == 1 and not report["ok"]


def test_a4_counts_the_junk_rows():
    counts = guards.a4_counts(build_db(workdir("a4") / "pilot3.db"))["counts"]
    assert counts["duplicate_sha256"] == 1
    assert counts["margins_over_100"] == 1
    assert counts["xbrl_disagreements"] == 1
    assert counts["period_after_doc"] == 1
    assert counts["known_before_filing"] == 1


def test_a5_scans_added_lines_for_company_literals():
    diff = ("diff --git a/reality_engine/pilot3/kpi.py b/reality_engine/pilot3/kpi.py\n"
            "--- a/reality_engine/pilot3/kpi.py\n"
            "+++ b/reality_engine/pilot3/kpi.py\n"
            "@@ -10,0 +11,2 @@\n"
            '+LITERAL = "KEC"\n'
            "+x = 1\n")
    hits = guards.literal_violations(guards.parse_added(diff))
    assert [(h["kind"], h["line"]) for h in hits] == [("company", 11)]
    assert guards.literal_violations({"reality_engine/pilot3/kpi.py": [(3, "x = 1")]}) == []
    assert guards.parts_for(["reality_engine/pilot3/kpi.py"]) == ["kpi"]
    assert guards.parts_for(["reality_engine/pilot3/build.py"]) == list(guards.ALL_PARTS)


def test_socket_guard_blocks_a_connect():
    work = workdir("socket")
    guard = guards.socket_guard(work / "guard")
    opener = work / "opener.py"
    opener.write_text("import socket\nsocket.create_connection(('127.0.0.1', 9), timeout=1)\n", encoding="utf-8")
    done = guards.run_blocked([sys.executable, str(opener)], work, guard, timeout=120)
    assert done.returncode != 0
    assert "A5" in (done.stdout + done.stderr)


def test_a5_fails_a_dirty_branch_and_passes_a_clean_one():
    work = workdir("a5")
    repo = repo_with_branches(work)
    db_path = build_db(work / "pilot3.db")
    opener = work / "opener.py"
    opener.write_text("import socket\nsocket.create_connection(('127.0.0.1', 9), timeout=1)\n", encoding="utf-8")
    guard = guards.socket_guard(work / "guard")

    def socket_build(part: str, _copy: Path) -> dict[str, Any]:
        done = guards.run_blocked([sys.executable, str(opener)], repo, guard, timeout=120)
        return {"part": part, "returncode": done.returncode, "tail": done.stderr[-300:]}

    dirty = guards.a5_build(db_path, "main", "dirty", work / "dirty_work", repo=repo, parts=["kpi"],
                            build_runner=socket_build)
    assert not dirty["ok"] and dirty["builds"][0]["returncode"] != 0
    assert any(hit["kind"] == "company" for hit in dirty["literals"])
    assert any(hit["kind"] == "test_assertion" for hit in dirty["protected"])

    clean = guards.a5_build(db_path, "main", "clean", work / "clean_work", repo=repo, parts=["kpi"],
                            build_runner=lambda part, _copy: {"part": part, "returncode": 0, "tail": ""})
    assert clean["ok"] and clean["literals"] == [] and clean["protected"] == []


def test_protected_paths_and_changed_test_lines_fail():
    found = guards.protected_violations(
        ["reality_engine/tests/test_kpi.py", "reality_engine/pilot3/kpi.py"],
        {"reality_engine/tests/test_kpi.py": ["assert a == 1"]},
        {"reality_engine/tests/test_kpi.py"})
    assert [hit["kind"] for hit in found] == ["test_assertion"]
    assert guards.protected_violations(["tasks/night_loop/GOAL.md"], {}, set())[0]["kind"] == "protected_path"
    assert guards.protected_violations(["reality_engine/night_eval/qset.py"], {}, set())
    assert guards.protected_violations(["reality_engine/tests/test_new.py"], {}, set()) == []


# --- decide and the rest ---------------------------------------------------------------------------------
def _a1(rate: float) -> dict[str, Any]:
    all_ = int(rate * 10)
    block = {"questions": 10, "all": all_, "some": 0, "none": 10 - all_, "rate": rate}
    return {"companies": {"KEC": dict(block)}, "total": dict(block)}


def _answerable(dev: float, hidden: float) -> list[dict[str, Any]]:
    return [{"hidden": False, "a1": _a1(dev)}, {"hidden": True, "a1": _a1(hidden)}]


def _guards(ok: bool = True, rate: float = 1.0, counts: dict[str, int] | None = None) -> dict[str, Any]:
    return {"a3": {"rate": rate, "checked": 4, "ok": rate >= 0.98},
            "a4": {"counts": counts if counts is not None else {"junk": 1}},
            "a5": {"ok": ok, "literals": [], "protected": [], "builds": []},
            "a6": {"ok": True}, "a7": {"build_seconds": 100.0, "pages_read": 50}}


def test_decide_rejects_when_hidden_falls():
    report = decide.decide(_answerable(0.5, 0.5), _answerable(0.6, 0.4), _guards(), _guards())
    assert report["verdict"] == "REJECT"
    assert any("hidden down" in reason for reason in report["reasons"])


def test_decide_accepts_a_clean_loop():
    report = decide.decide(_answerable(0.5, 0.5), _answerable(0.6, 0.5), _guards(), _guards())
    assert report["verdict"] == "ACCEPT", report["reasons"]


def test_decide_rejects_guards_and_risen_counts():
    report = decide.decide(_answerable(0.5, 0.5), _answerable(0.6, 0.5), _guards(ok=False), _guards())
    assert report["verdict"] == "REJECT" and any(reason.startswith("A5") for reason in report["reasons"])
    report = decide.decide(_answerable(0.5, 0.5), _answerable(0.6, 0.5), _guards(counts={"junk": 2}),
                           _guards(counts={"junk": 1}))
    assert report["verdict"] == "REJECT" and any("A4 junk" in reason for reason in report["reasons"])


def test_audit_finds_a_planted_hidden_read():
    work = workdir("audit")
    transcript = work / "loop_01.jsonl"
    lines = [json.dumps({"type": "system", "subtype": "init"}),
             json.dumps({"type": "assistant", "message": {"content": [
                 {"type": "tool_use", "name": "Read",
                  "input": {"file_path": ".tmp\\night_eval\\hidden.jsonl"}}]}}),
             json.dumps({"type": "assistant", "message": {"content": [
                 {"type": "tool_use", "name": "Read", "input": {"file_path": "tasks\\STATE.md"}}]}})]
    transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    hits = audit.scan(transcript)
    assert len(hits) == 1 and hits[0]["tool"] == "Read" and hits[0]["line"] == 2
    assert audit.main([str(transcript)]) == 1


def test_run_loop_dry_run_never_starts_a_session(capsys):
    work = workdir("loop")
    prompt = work / "prompt.txt"
    prompt.write_text("do the work item", encoding="utf-8")
    assert run_loop.main(["--n", "1", "--prompt", str(prompt), "--dry-run"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["dry_run"] is True and data["run_seconds"] == 7200
    assert "claude-opus-5-5" in data["cmd"] and "150" in data["cmd"]
    for tool in guards_tools_expectation():
        assert tool in data["disallowed"]


def guards_tools_expectation() -> tuple[str, ...]:
    return ("Agent", "mcp__dsh-worker__merge_worker", "mcp__dsh-worker__push", "Bash(git push*)",
            "Bash(git merge*)")
