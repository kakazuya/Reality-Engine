"""T-131: the v2 schema contract loads, is idempotent, and its core keys behave as documented."""
import sqlite3

import pytest

from reality_engine.v2 import schema

EXPECTED = {"entity", "entity_alias", "period", "doc", "doc_page", "table_cell", "statement", "label_map", "fact",
            "fact_evidence", "derivation", "guidance", "event", "event_entity", "note_item", "disclosure",
            "outside_doc", "question_template"}


def _conn():
    conn = sqlite3.connect(":memory:")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def test_contract_creates_every_table_and_reruns():
    conn = _conn()
    assert EXPECTED <= set(schema.create(conn))
    assert EXPECTED <= set(schema.create(conn))  # second run is a no-op


def test_one_fact_many_evidence_and_a_derived_row():
    conn = _conn()
    schema.create(conn)
    conn.execute("INSERT INTO entity VALUES (1,'INE001A01036','SBI Life','company',NULL,NULL,NULL,NULL,NULL,NULL)")
    conn.executemany("INSERT INTO period VALUES (?,?,?,?,?)", [
        ("2025-04-01/2026-03-31", "2025-04-01", "2026-03-31", "FY", "FY26"),
        ("2025-04-01/2025-12-31", "2025-04-01", "2025-12-31", "9M", "9MFY26"),
        ("2026-01-01/2026-03-31", "2026-01-01", "2026-03-31", "Q", "Q4FY26")])
    ins = ("INSERT INTO fact (fact_id, entity_id, metric, period_id, basis, kind, value, unit, known_at) "
           "VALUES (?,?,?,?,?,?,?,?,?)")
    conn.execute(ins, (1, 1, "ape", "2025-04-01/2026-03-31", "na", "reported", 2.1e11, "inr", "2026-04-25T16:00:00"))
    conn.execute(ins, (2, 1, "ape", "2025-04-01/2025-12-31", "na", "reported", 1.5e11, "inr", "2026-01-25T16:00:00"))
    conn.execute(ins, (3, 1, "ape", "2026-01-01/2026-03-31", "na", "derived", 0.6e11, "inr", "2026-04-25T16:00:00"))
    conn.execute("INSERT INTO derivation VALUES (3,'Q_FROM_FY_LESS_9M','[1,2]')")
    conn.executemany("INSERT INTO fact_evidence (fact_id, evidence_kind, evidence_ref) VALUES (?,?,?)",
                     [(1, "table_cell", "11"), (1, "page", "deck#4")])
    assert conn.execute("SELECT count(*) FROM fact_evidence WHERE fact_id=1").fetchone()[0] == 2
    with pytest.raises(sqlite3.IntegrityError):  # a derived row must name a real fact
        conn.execute("INSERT INTO derivation VALUES (99,'TTM_SUM4','[1]')")


def test_checks_refuse_bad_values():
    conn = _conn()
    schema.create(conn)
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO period VALUES ('x', NULL, '2026-01-01', 'WEEK', 'x')")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO label_map (label_norm, sector_family, metric, status) VALUES ('a','*','m','maybe')")
