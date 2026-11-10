import csv
import json
import sqlite3
import uuid
from pathlib import Path

from reality_engine.v2 import reference_pages as rp


def _base():
    base = Path(".tmp/t177/_test_tmp")
    base.mkdir(parents=True, exist_ok=True)
    d = base / uuid.uuid4().hex
    d.mkdir()
    return d


def _make_store(path, docs):
    db = path / "store.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE doc (doc_key TEXT, symbol TEXT, doc_type TEXT, sha256 TEXT, pages INTEGER)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    for d in docs:
        con.execute("INSERT INTO doc VALUES (?,?,?,?,?)", (d["key"], d["symbol"], d["type"], d["sha"], d["pages"]))
        for pg in range(1, d["pages"] + 1):
            text = d["text"]
            con.execute("INSERT INTO doc_page VALUES (?,?,?)", (d["key"], pg, text))
    con.commit()
    con.close()
    return db


def _sample_docs():
    docs = []
    nums = " ".join(str(i) for i in range(1, 40))
    for i in range(4):
        docs.append({"key": f"u{i}", "symbol": f"S{i}", "type": "investor_presentation", "sha": "sha", "pages": 1, "text": ""})
    for i in range(26):
        docs.append({"key": f"d{i}", "symbol": f"S{i % 13 + 10}", "type": "investor_presentation", "sha": "sha", "pages": 1, "text": nums})
    for i in range(20):
        docs.append({"key": f"r{i}", "symbol": f"R{i % 10}", "type": "quarterly_results", "sha": "sha", "pages": 1, "text": nums})
    for i in range(10):
        docs.append({"key": f"a{i}", "symbol": f"A{i % 5}", "type": "annual_report", "sha": "sha", "pages": 1, "text": nums})
    return docs


def test_parser_tolerant():
    raw = "some stray text\n{\"table\":\"T\",\"row_label\":\"A\",\"col_header\":\"B\",\"value\":\"1,234\",\"unit\":\"Rs\"}\nmore junk"
    rows = rp._parse_rows(raw)
    assert len(rows) == 1
    assert rows[0]["value"] == "1,234"
    raw2 = "prefix [ {\"table\":\"\",\"row_label\":\"X\",\"col_header\":\"Y\",\"value\":\"(1.5)\",\"unit\":\"\"} ] suffix"
    rows2 = rp._parse_rows(raw2)
    assert len(rows2) == 1
    assert rows2[0]["value"] == "(1.5)"
    raw3 = "```json\n[{\"table\":\"T\",\"row_label\":\"Z\",\"col_header\":\"C\",\"value\":\"9\",\"unit\":\"\"}]\n```"
    rows3 = rp._parse_rows(raw3)
    assert len(rows3) == 1


def test_sampler_determinism_and_quotas():
    from unittest.mock import patch
    with patch("reality_engine.v2.reference_pages._deck_sha_set", lambda: set()):
        base = _base()
        db = _make_store(base, _sample_docs())
        out1 = base / "a"
        out2 = base / "b"
        rp.sample_pages([str(db)], out1, seed=20261110)
        rp.sample_pages([str(db)], out2, seed=20261110)
        assert (out1 / "pages.csv").read_text() == (out2 / "pages.csv").read_text()
        rows = list(csv.DictReader((out1 / "pages.csv").open()))
        assert len(rows) == 60
        from collections import Counter
        types = Counter(r["doc type"] for r in rows)
        assert types["deck"] == 30
        assert types["results"] == 20
        assert types["annual_report"] == 10
        splits = Counter(r["split"] for r in rows)
        assert splits["dev"] == 30 and splits["frozen"] == 30


def test_reconcile_handmade():
    base = _base()
    text = "Revenue 100 200 300 Total 600 (1.5)"
    db = base / "store.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE doc (doc_key TEXT, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    con.execute("INSERT INTO doc VALUES (?,?)", ("dk", "dummy.pdf"))
    con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("dk", 1, text))
    con.commit()
    con.close()
    pages_csv = base / "pages.csv"
    with pages_csv.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["page_id", "store", "symbol", "doc key", "sha256", "doc type", "page", "stratum", "in_first_build", "split"])
        w.writerow(["p1", str(db), "SYM", "dk", "sha", "deck", "1", "ruled_table", "False", "dev"])
    run_a = base / "runA"
    run_b = base / "runB"
    run_a.mkdir()
    run_b.mkdir()
    rows_a = [
        {"table": "T", "row_label": "Revenue", "col_header": "Q1", "value": "100", "unit": "Rs"},
        {"table": "T", "row_label": "Revenue", "col_header": "Q2", "value": "200", "unit": "Rs"},
        {"table": "T", "row_label": "Total", "col_header": "Q1", "value": "100", "unit": "Rs"},
    ]
    rows_b = [
        {"table": "T", "row_label": "Revenue", "col_header": "Q1", "value": "100", "unit": "Rs"},
        {"table": "T", "row_label": "Revenue", "col_header": "Q2", "value": "200", "unit": "Rs"},
        {"table": "T", "row_label": "Total", "col_header": "Q1", "value": "(100)", "unit": "Rs"},
        {"table": "T", "row_label": "Revenue", "col_header": "Q3", "value": "999", "unit": "Rs"},
    ]
    (run_a / "p1.rows.json").write_text(json.dumps(rows_a))
    (run_b / "p1.rows.json").write_text(json.dumps(rows_b))
    rp.reconcile_pages(pages_csv, [run_a, run_b], base / "out")
    rc = list(csv.DictReader((base / "out" / "reference_cells.csv").open()))
    total_row = [r for r in rc if r["row_label"] == "Total"][0]
    assert total_row["agreed"] == "False"
    q3 = [r for r in rc if r["col_header"] == "Q3"]
    assert len(q3) == 1
    rev = [r for r in rc if r["row_label"] == "Revenue" and r["col_header"] == "Q1"][0]
    assert rev["verbatim"] == "True"
    assert rev["agreed"] == "True"
