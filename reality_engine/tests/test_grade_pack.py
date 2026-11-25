"""T-242 grading-pack builder: checkpoint order, seeded fill, parts and page text.

Fixtures only: tiny observation and store DBs stand under ``tmp_path``; no live
store under ``REALITY_DATA_ROOT`` is opened.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
import uuid
from pathlib import Path

import pytest

from reality_engine.scripts import grade_pack

ROOT = Path(__file__).resolve().parents[2]

OBS_FIELDS = [
    "observation_id", "symbol", "doc_key", "page", "record_type", "measure",
    "printed_label", "value_text", "value", "unit", "scale", "period", "basis",
    "segment", "speaker", "statement", "entity_scope", "status", "read_at",
    "question_context",
]

SCHEMA = """
CREATE TABLE observation (
    observation_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    doc_key TEXT NOT NULL,
    page INTEGER NOT NULL,
    record_type TEXT NOT NULL,
    measure TEXT NOT NULL DEFAULT '',
    printed_label TEXT NOT NULL DEFAULT '',
    value_text TEXT NOT NULL DEFAULT '',
    value REAL,
    unit TEXT NOT NULL DEFAULT '',
    scale REAL NOT NULL DEFAULT 1,
    period TEXT NOT NULL DEFAULT '',
    basis TEXT NOT NULL DEFAULT '',
    segment TEXT NOT NULL DEFAULT '',
    speaker TEXT NOT NULL DEFAULT '',
    statement TEXT NOT NULL DEFAULT '',
    entity_scope TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    read_at TEXT NOT NULL DEFAULT '',
    question_context TEXT NOT NULL DEFAULT ''
)
"""


@pytest.fixture()
def tmp_path():
    """A writable scratch folder: the sandbox's pytest basetemp root can be ACL-locked."""
    base = ROOT / ".tmp" / f"t242_grade_pack_{uuid.uuid4().hex}"
    base.mkdir(parents=True, exist_ok=True)
    try:
        yield base
    finally:
        shutil.rmtree(base, ignore_errors=True)


def _row(oid: int, symbol: str, doc_key: str, page: int, **overrides) -> dict:
    row = {
        "observation_id": oid, "symbol": symbol, "doc_key": doc_key, "page": page,
        "record_type": "statement", "measure": "revenue", "printed_label": "Revenue",
        "value_text": "1,000", "value": 1000.0, "unit": "inr_cr", "scale": 1.0,
        "period": "FY26", "basis": "consolidated", "segment": "", "speaker": "A. Person",
        "statement": "Revenue was 1,000 crore.", "entity_scope": "company",
        "status": "verified", "read_at": "2026-11-25T10:00:00",
        "question_context": "What did you say about revenue?",
    }
    row.update(overrides)
    return row


def _observation_db(path: Path, rows: list[dict], *, question_context: bool = True) -> Path:
    schema = SCHEMA if question_context else SCHEMA.replace(
        ",\n    question_context TEXT NOT NULL DEFAULT ''", "")
    keys = [c for c in OBS_FIELDS if question_context or c != "question_context"]
    con = sqlite3.connect(path)
    con.execute(schema)
    con.executemany(
        f"insert into observation ({', '.join(keys)}) values ({', '.join('?' * len(keys))})",
        [tuple(r.get(k) for k in keys) for r in rows])
    con.commit()
    con.close()
    return path


def _store(path: Path, pages: list[tuple[str, int, str]]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE doc_page (doc_key TEXT NOT NULL, page INTEGER NOT NULL, text TEXT NOT NULL)")
    con.executemany("INSERT INTO doc_page VALUES (?,?,?)", pages)
    con.commit()
    con.close()
    return path


def _checkpoint(path: Path, ids: list[int]) -> Path:
    lines = [json.dumps({"observation_id": oid}) for oid in ids[:-1]]
    lines.append(json.dumps({"id": ids[-1]}))  # the old checkpoint shape
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _pack_rows(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _pack_fixture(tmp_path: Path):
    checkpoint = [_row(n, f"S{n}", f"ck{n}", 2) for n in range(1, 11)]
    pool = []
    oid = 100
    pages = []
    for d in range(30):
        doc = f"p{d}"
        for page in (2, 3, 4):
            pool.append(_row(oid, f"S{oid % 10}", doc, page))
            oid += 1
        for page in (1, 2, 3, 4):
            pages.append((doc, page, f"{doc} p{page}"))
    for n in range(1, 11):
        for page in (1, 2):
            pages.append((f"ck{n}", page, f"ck{n} p{page}"))
    db = _observation_db(tmp_path / "obs.db", checkpoint + pool)
    store = tmp_path / "stores" / "c01.db"
    _store(store, pages)
    ckpt = _checkpoint(tmp_path / "ckpt.jsonl", [r["observation_id"] for r in checkpoint])
    return db, ckpt, store


def test_checkpoint_rows_come_first_then_new_symbols_then_at_most_two_per_doc():
    checkpoint = [_row(1, "AAA", "d1", 2), _row(2, "BBB", "d2", 2)]
    pool = [
        _row(10, "AAA", "d3", 2),   # a checkpoint symbol: second pass only
        _row(11, "CCC", "d4", 2),   # a new symbol: first pass
        _row(12, "DDD", "d5", 2),
        _row(13, "EEE", "d5", 3),   # second row of the doc, allowed
        _row(14, "FFF", "d5", 4),   # third row of the doc, refused
        _row(15, "GGG", "d6", 2),
    ]
    rows = grade_pack.select_rows(checkpoint, pool, size=60, seed=3)
    ids = [r["observation_id"] for r in rows]
    assert ids[:2] == [1, 2]
    assert ids.index(11) < ids.index(10), "a new symbol fills before a repeated one"
    assert ids.count(13) == 1 and ids.count(14) == 0
    assert sum(1 for r in rows if r["doc_key"] == "d5") == 2
    assert len(ids) == len(set(ids))


def test_same_seed_gives_the_same_fill():
    checkpoint = [_row(1, "AAA", "d1", 2)]
    pool = [_row(n, f"S{n}", f"d{n}", 2) for n in range(10, 40)]
    a = [r["observation_id"] for r in grade_pack.select_rows(checkpoint, pool, size=12, seed=7)]
    b = [r["observation_id"] for r in grade_pack.select_rows(checkpoint, pool, size=12, seed=7)]
    assert a == b
    assert len(a) == 12


def test_pack_has_60_rows_two_30_row_parts_and_printed_pages(tmp_path, capsys):
    db, ckpt, store = _pack_fixture(tmp_path)
    out = tmp_path / "pack.jsonl"
    code = grade_pack.main([
        "--db", str(db), "--ckpt", str(ckpt), "--stores-glob", str(store),
        "--record-type", "statement", "--seed", "5", "--out", str(out),
    ])
    assert code == 0
    assert "60 rows (10 from checkpoint), missing pages: 0" in capsys.readouterr().out

    rows = _pack_rows(out)
    assert len(rows) == 60
    assert len(_pack_rows(tmp_path / "pack_part00.jsonl")) == 30
    assert len(_pack_rows(tmp_path / "pack_part01.jsonl")) == 30
    assert [r["n"] for r in rows] == list(range(1, 61))

    assert all(r["in_checkpoint"] for r in rows[:10])
    assert [r["observation_id"] for r in rows[:10]] == list(range(1, 11))
    assert not any(r["in_checkpoint"] for r in rows[10:])
    for row in rows:
        doc = row["doc_key"]
        assert row["page_text"] == f"{doc} p{row['page']}", doc
        assert row["previous_page_text"] == f"{doc} p{row['page'] - 1}", doc
        assert "read_at" not in row
    per_doc: dict[str, int] = {}
    for row in rows:
        per_doc[row["doc_key"]] = per_doc.get(row["doc_key"], 0) + 1
    assert max(per_doc.values()) <= 2

    again = tmp_path / "pack_again.jsonl"
    grade_pack.main([
        "--db", str(db), "--ckpt", str(ckpt), "--stores-glob", str(store),
        "--record-type", "statement", "--seed", "5", "--out", str(again),
    ])
    assert [r["observation_id"] for r in _pack_rows(again)] == [r["observation_id"] for r in rows]


def test_question_context_is_written_only_when_the_column_exists(tmp_path):
    with_column = _observation_db(tmp_path / "with.db", [_row(1, "AAA", "d1", 2)])
    without = _observation_db(tmp_path / "without.db", [_row(1, "AAA", "d1", 2)],
                              question_context=False)
    ckpt = _checkpoint(tmp_path / "ckpt.jsonl", [1])

    def build(db: Path, out: Path) -> dict:
        assert grade_pack.main(["--db", str(db), "--ckpt", str(ckpt), "--record-type",
                                "statement", "--seed", "1", "--size", "1", "--split", "0",
                                "--out", str(out)]) == 0
        return _pack_rows(out)[0]

    row = build(with_column, tmp_path / "with.jsonl")
    assert row["question_context"] == "What did you say about revenue?"
    row = build(without, tmp_path / "without.jsonl")
    assert "question_context" not in row
