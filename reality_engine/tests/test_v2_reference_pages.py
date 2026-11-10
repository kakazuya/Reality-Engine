import csv
import json
import sqlite3
import tempfile
import uuid
from pathlib import Path

from reality_engine.v2 import reference_pages as rp


def _tmp_base():
    base = Path(".tmp/t177/_test_tmp")
    base.mkdir(parents=True, exist_ok=True)
    d = base / uuid.uuid4().hex
    d.mkdir()
    return d


def test_parser_tolerant():
    raw = "some stray text\n{\"table\":\"T\",\"row_label\":\"A\",\"col_header\":\"B\",\"value\":\"1,234\",\"unit\":\"Rs\"}\nmore junk"
    rows = rp._parse_rows(raw)
    assert len(rows) == 1
    assert rows[0]["value"] == "1,234"
    raw2 = "prefix [ {\"table\":\"\",\"row_label\":\"X\",\"col_header\":\"Y\",\"value\":\"(1.5)\",\"unit\":\"\"} ] suffix"
    rows2 = rp._parse_rows(raw2)
    assert len(rows2) == 1
    assert rows2[0]["value"] == "(1.5)"


def test_sampler_determinism_and_quotas():
    stores = "D:/RealityEngine/p20/p20new.db,D:/RealityEngine/u8/u8.db,D:/RealityEngine/q12/q12.db"
    base = _tmp_base()
    out1 = base / "a"
    out2 = base / "b"
    rp.sample_pages([s.strip() for s in stores.split(",")], out1, seed=20261110)
    rp.sample_pages([s.strip() for s in stores.split(",")], out2, seed=20261110)
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


def _make_store(base, text):
    db = base / "store.db"
    con = sqlite3.connect(str(db))
    con.execute("CREATE TABLE doc (doc_key TEXT, source_key TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    con.execute("INSERT INTO doc VALUES (?,?)", ("dk", "dummy.pdf"))
    con.execute("INSERT INTO doc_page VALUES (?,?,?)", ("dk", 1, text))
    con.commit()
    con.close()
    return db


def test_reconcile_handmade():
    base = _tmp_base()
    text = "Revenue 100 200 300 Total 600 (1.5)"
    db = _make_store(base, text)
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