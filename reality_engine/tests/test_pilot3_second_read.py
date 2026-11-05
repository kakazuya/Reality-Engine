"""Tests for the second reading step (T-083): a fake model client, no network.

Every company, figure and question here is invented: the graded answers are not fixtures.
"""
from __future__ import annotations

import json
import shutil
import uuid
from pathlib import Path

import pytest

from reality_engine.pilot3 import second_read

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def tmp_path():
    """A writable empty dir under the repo's ``.tmp``.

    pytest's own ``tmp_path`` is made by ``tempfile.mkdtemp``, which creates the directory mode 0700; the dsh
    filesystem sandbox denies a file opened inside such a directory, so the tests would not run in a worker.
    """
    directory = ROOT / ".tmp" / f"second_read_test_{uuid.uuid4().hex[:10]}"
    directory.mkdir(parents=True)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)

ANSWER = ("Northwind's revenue fell 8 percent to Rs 120 crore from Rs 130 crore. "
          "Margins were steady at 7.1, 7.0, 5.8 and 4.9 percent across the four quarters. "
          "The fall in credit cover came because slower factory output hit the order book.")


class Fake:
    """A stand-in for ``call_read``: returns the queued replies and records every prompt."""

    def __init__(self, *replies, in_tok=10, out_tok=5):
        self.replies = list(replies)
        self.calls: list[tuple[str, str, str, str]] = []
        self.in_tok, self.out_tok = in_tok, out_tok

    def __call__(self, system, user, key, *, job="j", **kwargs):
        self.calls.append((system, user, key, job))
        reply = self.replies.pop(0) if self.replies else {"flags": []}
        if isinstance(reply, dict) and "content" not in reply:
            content, finish = json.dumps(reply), "stop"
        elif isinstance(reply, dict):
            content, finish = reply["content"], reply.get("finish", "stop")
        else:
            content, finish = reply, "stop"
        return {"content": content, "finish": finish, "in_tok": self.in_tok, "out_tok": self.out_tok}


def make_dir(tmp_path: Path, *, qid: str = "NW-001", answer: str = ANSWER,
             numbers: list | None = None, question: str = "What were the four quarterly margins and the revenue fall?",
             duplicate: bool = False) -> Path:
    symbol = qid.rsplit("-", 1)[0]
    rows: list[dict] = [{"event": "start", "qid": qid}]
    first = {"event": "answer", "qid": qid, "answer": "Nothing was given.", "numbers": [], "status": "answered"}
    if duplicate:
        rows.append(first)
    rows.append({"event": "answer", "qid": qid, "answer": answer,
                 "numbers": numbers if numbers is not None else [], "status": "answered",
                 "tools": ["pilot3_fin"]})
    (tmp_path / f"{symbol}_answers.jsonl").write_text(
        "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    (tmp_path / f"{symbol}_questions.json").write_text(
        json.dumps([{"qid": qid, "question": question, "as_of": "2026-01-31"}]), encoding="utf-8")
    return tmp_path


def write_qids(tmp_path: Path, *qids: str) -> Path:
    path = tmp_path / "qids.txt"
    path.write_text("\n".join(qids) + "\n", encoding="utf-8")
    return path


def run_one(tmp_path: Path, fake: Fake, **kw):
    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    summary = second_read.run(tmp_path, ["NW-001"], out, client=fake, key="k1", **kw)
    rows = [json.loads(line) for line in out.read_text(encoding="utf-8").splitlines()]
    return summary, rows, out


def test_verbatim_claim_is_kept_and_paraphrase_dropped(tmp_path):
    fake = Fake({"flags": [
        {"kind": "contradicts_own_numbers", "claim": "Margins were steady at 7.1, 7.0, 5.8 and 4.9 percent",
         "why": "The series falls three times, so 'steady' is wrong."},
        {"kind": "contradicts_own_numbers", "claim": "Margins were flat across the four quarters",
         "why": "A paraphrase, not a quote."},
    ]})
    _, rows, _ = run_one(tmp_path, fake)
    assert rows[0]["status"] == "ok"
    assert [flag["claim"] for flag in rows[0]["flags"]] == [
        "Margins were steady at 7.1, 7.0, 5.8 and 4.9 percent"]
    assert rows[0]["dropped_flags"] == 1


def test_claim_matches_after_whitespace_normalising(tmp_path):
    fake = Fake({"flags": [{"kind": "unsourced_cause",
                            "claim": "the fall in credit cover came because slower factory output hit the order book",
                            "why": "No output figure and no quote is given."}]})
    answer = ANSWER.replace("The fall in credit cover came because slower factory output hit the order book.",
                            "The fall in credit cover came because\n slower   factory output hit the order book.")
    make_dir(tmp_path, answer=answer)
    out = tmp_path / "flags.jsonl"
    second_read.run(tmp_path, ["NW-001"], out, client=fake, key="k1")
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert len(row["flags"]) == 1 and row["dropped_flags"] == 0


def test_unknown_kind_or_empty_why_is_dropped(tmp_path):
    fake = Fake({"flags": [
        {"kind": "made_up_kind", "claim": "revenue fell 8 percent", "why": "x"},
        {"kind": "unsourced_cause", "claim": "revenue fell 8 percent", "why": ""},
        "not a flag",
    ]})
    _, rows, _ = run_one(tmp_path, fake)
    assert rows[0]["status"] == "ok" and rows[0]["flags"] == []
    assert rows[0]["dropped_flags"] == 3


def test_empty_claim_misfit_must_name_the_question(tmp_path):
    fake = Fake({"flags": [
        {"kind": "question_misfit", "claim": "",
         "why": "The question asked for four quarters of margins and the answer gives one revenue fall."},
        {"kind": "question_misfit", "claim": "", "why": "The answer is incomplete."},
    ]})
    _, rows, _ = run_one(tmp_path, fake)
    assert len(rows[0]["flags"]) == 1
    assert rows[0]["flags"][0]["claim"] == ""
    assert rows[0]["dropped_flags"] == 1


def test_resume_skips_a_finished_qid_and_pass(tmp_path):
    first = Fake({"flags": []})
    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    second_read.run(tmp_path, ["NW-001"], out, client=first, key="k1")
    assert len(first.calls) == 1

    again = Fake({"flags": []})
    summary = second_read.run(tmp_path, ["NW-001"], out, client=again, key="k1")
    assert again.calls == []
    assert summary["skipped"] == 1 and summary["checked"] == 0
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1

    other_pass = Fake({"flags": []})
    second_read.run(tmp_path, ["NW-001"], out, client=other_pass, key="k1", pass_no=2)
    assert len(other_pass.calls) == 1
    assert len(out.read_text(encoding="utf-8").splitlines()) == 2


def test_truncated_reply_is_retried_once_then_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(second_read.time, "sleep", lambda seconds: None)
    truncated = {"content": '{"flags": [{"kind": "unsourced_cause", "claim": "revenue fell',
                 "finish": "length"}
    fake = Fake(truncated, truncated)
    _, rows, _ = run_one(tmp_path, fake)
    row = rows[0]
    assert len(fake.calls) == 2
    assert row["status"] == "truncated" and row["flags"] == []
    assert row["attempts"] == 2 and row["finish"] == "length"
    assert row["in_tok"] == 20          # both attempts are counted
    assert "truncated" in row["error"]


def test_unparseable_reply_retried_then_failed(tmp_path):
    fake = Fake("not json at all", "still not json")
    _, rows, _ = run_one(tmp_path, fake)
    assert len(fake.calls) == 2
    assert rows[0]["status"] == "unparseable" and rows[0]["flags"] == []


def test_unparseable_then_good_reply_is_ok(tmp_path):
    good = {"flags": [{"kind": "contradicts_own_numbers", "claim": "revenue fell 8 percent",
                       "why": "The table prints 120 after 130, which is a fall, but the same answer says growth."}]}
    fake = Fake("not json", good)
    _, rows, _ = run_one(tmp_path, fake)
    assert len(fake.calls) == 2
    assert rows[0]["status"] == "ok" and len(rows[0]["flags"]) == 1


def test_rate_limited_is_a_named_failure_not_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(second_read.time, "sleep", lambda seconds: None)

    def limited(system, user, key, **kwargs):
        raise second_read.RateLimited("HTTP 429")

    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    second_read.run(tmp_path, ["NW-001"], out, client=limited, key="k1")
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["status"] == "rate_limited" and row["flags"] == []


def test_last_answer_row_for_a_qid_wins(tmp_path):
    fake = Fake({"flags": [{"kind": "contradicts_own_numbers", "claim": "revenue fell 8 percent",
                            "why": "Checked against the answer that was kept."}]})
    _, rows, _ = run_one(tmp_path, fake, )
    assert len(fake.calls) == 1
    assert "Nothing was given." not in fake.calls[0][1]
    assert len(rows[0]["flags"]) == 1


def test_number_table_reaches_the_prompt(tmp_path):
    numbers = [{"value": 120, "unit": "crore", "period": "Q1FY27", "source": "results p3",
                "quote": "Revenue 120.0 against 130.0"}]
    fake = Fake({"flags": []})
    make_dir(tmp_path, numbers=numbers)
    out = tmp_path / "flags.jsonl"
    second_read.run(tmp_path, ["NW-001"], out, client=fake, key="k1")
    prompt = fake.calls[0][1]
    assert "120 crore Q1FY27" in prompt and "results p3" in prompt
    assert "What were the four quarterly margins" in prompt


def test_duplicate_qid_in_list_reads_once(tmp_path):
    fake = Fake({"flags": []})
    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    second_read.run(tmp_path, ["NW-001", "NW-001"], out, client=fake, key="k1")
    assert len(fake.calls) == 1
    assert len(out.read_text(encoding="utf-8").splitlines()) == 1


def test_missing_answer_is_a_named_row(tmp_path):
    fake = Fake({"flags": []})
    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    summary = second_read.run(tmp_path, ["NW-999"], out, client=fake, key="k1")
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["status"] == "not_found" and fake.calls == []
    assert summary["status"] == {"not_found": 1}


def test_limit_applies_to_remaining_work(tmp_path):
    make_dir(tmp_path, qid="NW-001")
    make_dir(tmp_path, qid="OR-002")
    fake = Fake({"flags": []})
    out = tmp_path / "flags.jsonl"
    summary = second_read.run(tmp_path, ["NW-001", "OR-002"], out, client=fake, key="k1", limit=1)
    assert len(fake.calls) == 1 and summary["checked"] == 1


def test_cli_writes_rows_and_resumes(tmp_path, monkeypatch):
    monkeypatch.setattr(second_read, "resolve_key", lambda: "k1")
    fake = Fake({"flags": []})
    monkeypatch.setattr(second_read, "call_read", fake)
    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    qids = write_qids(tmp_path, "NW-001")

    assert second_read.main(["--answers-dir", str(tmp_path), "--qids", str(qids),
                             "--out", str(out), "--parallel", "2"]) == 0
    row = json.loads(out.read_text(encoding="utf-8").strip())
    assert row["qid"] == "NW-001" and row["pass_no"] == 1 and row["status"] == "ok"

    assert second_read.main(["--answers-dir", str(tmp_path), "--qids", str(qids),
                             "--out", str(out), "--parallel", "2"]) == 0
    assert len(fake.calls) == 1


def test_cli_without_key_exits_before_any_call(tmp_path, monkeypatch):
    monkeypatch.setattr(second_read, "resolve_key", lambda: "")
    make_dir(tmp_path)
    out = tmp_path / "flags.jsonl"
    qids = write_qids(tmp_path, "NW-001")
    assert second_read.main(["--answers-dir", str(tmp_path), "--qids", str(qids),
                             "--out", str(out)]) == 2
    assert not out.exists()


def test_billing_error_stops_the_run(tmp_path):
    def billing(system, user, key, **kwargs):
        raise second_read.BillingError("HTTP 402: no credits")

    make_dir(tmp_path)
    with pytest.raises(second_read.BillingError):
        second_read.run(tmp_path, ["NW-001"], tmp_path / "flags.jsonl", client=billing, key="k1")
