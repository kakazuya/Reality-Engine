"""T-205 round 13: blind grading of N sets -- shuffled labels, a private key, strict parsing, a decoder."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from reality_engine.answer import blind_grade  # noqa: E402

QUESTIONS = [{"qid": f"BS-{i:03d}", "question": f"q{i}", "as_of": "2026-11-11"} for i in range(1, 4)]


def _set(folder: Path, answers: dict[str, str]) -> Path:
    folder.mkdir(parents=True)
    lines = [json.dumps({"qid": qid, "answer": answer}) for qid, answer in answers.items()]
    (folder / "answers.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return folder


def test_make_shuffles_labels_and_keeps_the_key_private(tmp_path):
    out = tmp_path / "report" / "blind"
    pack = _set(tmp_path / "pack", {q["qid"]: f"pack {i}" for i, q in enumerate(QUESTIONS)})
    seeded = _set(tmp_path / "seeded", {q["qid"]: f"seeded {i}" for i, q in enumerate(QUESTIONS)})
    questions = tmp_path / "questions_in.json"
    questions.write_text(json.dumps(QUESTIONS), encoding="utf-8")
    summary = blind_grade.make({"pack": pack, "seeded": seeded}, out, questions=questions, batch=2)
    assert summary["sets"] == ["pack", "seeded"] and summary["questions"] == 3 and summary["batches"] == 2
    key = Path(summary["key"])
    assert key.parent.name == "key_private" and key.is_file()
    assert "key_private" in blind_grade.RULES and "must stay closed" in blind_grade.RULES
    rows = [json.loads(line) for line in (out / "grade_in_0.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2 and set(rows[0]["answers"]) == {"A", "B"}
    assert len((out / "grade_in_1.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    with key.open(newline="", encoding="utf-8") as fh:
        mapping = list(csv.DictReader(fh))
    assert len(mapping) == 6
    # the key is the only place that says which label is which set: the batches carry no set name
    by_qid_label = {(r["qid"], r["label"]): r["set"] for r in mapping}
    for row in rows:
        for label, body in row["answers"].items():
            name = by_qid_label[(row["qid"], label)]
            expected = "pack" if name == "pack" else "seeded"
            assert body["answer"].startswith(expected)
            assert "set" not in row               # a batch never names the set behind a label


def test_parse_grades_is_strict(tmp_path):
    wanted = {("BS-001", "A"), ("BS-001", "B")}
    text = "\n".join([
        'The truth is clear.',
        '{"qid": "BS-001", "label": "A", "grade": "right", "root_cause": "", "truth": "x", "note": "ok"}',
        '{"qid": "BS-001", "label": "B", "grade": "brilliant", "note": "unknown grade"}',
        '{"qid": "BS-009", "label": "A", "grade": "wrong"}',
        '{"qid": "BS-001", "label": "A", "grade": "wrong"}',   # duplicate: first wins
    ])
    rows = blind_grade.parse_grades(text, wanted)
    assert len(rows) == 1 and rows[0]["grade"] == "right"


def test_grade_batch_re_asks_once_when_the_reply_does_not_parse(tmp_path):
    batch = tmp_path / "grade_in_1.jsonl"
    batch.write_text(json.dumps({"qid": "BS-001", "question": "q", "as_of": "2026-11-11",
                                 "answers": {"A": {"answer": "one"}, "B": {"answer": "two"}}}) + "\n",
                     encoding="utf-8")
    replies = ["no json at all",
               '{"qid": "BS-001", "label": "A", "grade": "right", "truth": "t", "note": "n"}\n'
               '{"qid": "BS-001", "label": "B", "grade": "partly", "truth": "t", "note": "n"}']
    calls = []

    def run(prompt, model, **kwargs):
        calls.append(prompt)
        return {"ok": True, "text": replies[len(calls) - 1]}

    report = blind_grade.grade_batch(batch, run=run)
    assert len(calls) == 2 and report["attempts"] == 2
    assert {(r["qid"], r["label"], r["grade"]) for r in report["grades"]} == {
        ("BS-001", "A", "right"), ("BS-001", "B", "partly")}
    assert not report["missing"]
    # the re-ask carries the parse complaint, not just the same prompt again
    assert "DID NOT PARSE" in calls[1]


def test_decode_totals_and_pairwise_agreement(tmp_path):
    out = tmp_path / "blind"
    out.mkdir()
    key = out.parent / "key_private" / "key_blind.csv"
    key.parent.mkdir()
    mapping = {"BS-001": {"A": "pack", "B": "seeded"}, "BS-002": {"A": "seeded", "B": "pack"}}
    with key.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["qid", "label", "set"])
        for qid, labels in mapping.items():
            for label, name in labels.items():
                w.writerow([qid, label, name])
    rows = [  # pack: right + wrong; seeded: not_held + partly (not_held counts as right)
        {"qid": "BS-001", "label": "A", "grade": "right"},
        {"qid": "BS-001", "label": "B", "grade": "not_held"},
        {"qid": "BS-002", "label": "A", "grade": "partly"},
        {"qid": "BS-002", "label": "B", "grade": "wrong"},
    ]
    (out / "grades.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    result = blind_grade.decode(out)
    assert result["totals"]["pack"] == {"right": 1, "partly": 0, "wrong": 1, "not_held": 0, "graded": 2,
                                        "right_equivalent": 1, "right_pct": 50.0}
    assert result["totals"]["seeded"]["right_equivalent"] == 1
    assert result["pairwise"]["pack|seeded"] == {"questions": 2, "agree_grade": 0, "agree_right": 1,
                                                 "agree_right_pct": 50.0}
    assert (out / "per_question.csv").is_file()
    assert [r["qid"] for r in result["per_question"]] == ["BS-001", "BS-002"]
