"""Tests for reality_engine.v2.silver_score (T-225)."""
from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

from reality_engine.v2 import silver_score as ss

_DDL = """
CREATE TABLE page_cell (
    doc_key TEXT, page INTEGER, symbol TEXT, known_at TEXT, reader TEXT,
    table_title TEXT, row_label TEXT, col_header TEXT, value_text TEXT, unit_text TEXT,
    status TEXT, conflict TEXT, x0 REAL, y0 REAL, x1 REAL, y1 REAL
)
"""


def _make_db(path: Path, rows: list[tuple[str, int, str, str, str, str, str]]) -> Path:
    """Create a tiny reader DB; each row is (doc_key, page, row_label, col_header, value_text, status, conflict)."""
    conn = sqlite3.connect(path)
    conn.execute(_DDL)
    for dk, pg, rl, ch, vt, st, cf in rows:
        conn.execute(
            "INSERT INTO page_cell VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (dk, pg, "TST", "2025-11-01", path.stem, "", rl, ch, vt, "Rs. Cr", st, cf, 0, 0, 0, 0),
        )
    conn.commit()
    conn.close()
    return path


def test_a_two_tags_same_value_label_header_silver(tmp_path: Path) -> None:
    p1 = _make_db(tmp_path / "read_dots.db", [
        ("doc1", 2, "Total Income", "Q1 FY25", "1,234.50", "verified", ""),
    ])
    p2 = _make_db(tmp_path / "read_hy4.db", [
        ("doc1", 2, "Total Income", "Q1FY25", "1234.50", "unverified", "row_elsewhere"),
    ])
    cells = ss.load([p1, p2])
    assert {c["tag"] for c in cells} == {"dots", "hy4"}
    sil = ss.silver(cells)
    assert len(sil) == 1
    assert sil[0]["tags"] == ["dots", "hy4"]
    assert sil[0]["value_key"] == "1234.50"


def test_b_same_tag_twice_is_not_silver(tmp_path: Path) -> None:
    p1 = _make_db(tmp_path / "read_dots.db", [
        ("doc1", 1, "Other Income", "Q2 FY25", "500.00", "verified", ""),
        ("doc1", 1, "Other Income", "Q2 FY25", "500.00", "unverified", "row_elsewhere"),
        ("doc1", 1, "Other Income (net)", "Q2 FY25", "500.00", "verified", ""),
    ])
    cells = ss.load([p1])
    # Exact duplicate within the same tag is deduped (keeping verified), and remaining cells share one tag.
    assert len(cells) == 2
    assert ss.silver(cells) == []


def test_c_different_header_period_not_silver(tmp_path: Path) -> None:
    p1 = _make_db(tmp_path / "read_dots.db", [
        ("doc1", 1, "Profit before tax", "Quarter Ended 30.06.2025", "900", "verified", ""),
    ])
    p2 = _make_db(tmp_path / "read_hy4.db", [
        ("doc1", 1, "Profit before tax", "Quarter Ended 30.09.2025", "900", "verified", ""),
    ])
    cells = ss.load([p1, p2])
    assert ss.silver(cells) == []
    assert ss.conflict(cells) == []


def test_d_third_tag_different_value_silver_wrong_and_wrong_verified(tmp_path: Path) -> None:
    _make_db(tmp_path / "read_dots.db", [
        ("doc1", 3, "Net Profit", "Q1 FY26", "250.00", "verified", ""),
        ("doc1", 3, "Tax Expense", "Q1 FY26", "40.00", "verified", ""),
    ])
    _make_db(tmp_path / "read_hy4.db", [
        ("doc1", 3, "Net Profit", "Q1 FY26", "250.00", "verified", ""),
        ("doc1", 3, "Tax Expense", "Q1 FY26", "40.00", "verified", ""),
    ])
    _make_db(tmp_path / "read_haiku.db", [
        ("doc1", 3, "Net Profit", "Q1 FY26", "999.00", "verified", ""),
        ("doc1", 3, "Tax Expense", "Q1 FY26", "41.00", "unverified", "column_elsewhere"),
    ])
    res = ss.score(tmp_path)
    haiku = res["by_tag"]["haiku"]
    assert haiku["silver_wrong"] == 2
    assert haiku["wrong_verified"] == 1
    assert res["by_tag"]["dots"]["wrong_verified"] == 0
    assert res["by_tag"]["hy4"]["wrong_verified"] == 0
    assert res["by_page"][("doc1", 3)]["wrong_verified"] == 1


def test_e_label_match_revenue_from_operations(tmp_path: Path) -> None:
    assert ss.label_match("Revenue from operations", "Revenue from Operations (net)")
    assert not ss.label_match("Total", "Total Income")

    p1 = _make_db(tmp_path / "read_dots.db", [
        ("doc1", 1, "Revenue from operations", "Year Ended 31.03.2025", "(1,200.5)", "verified", ""),
    ])
    p2 = _make_db(tmp_path / "read_hy4.db", [
        ("doc1", 1, "Revenue from Operations (net)", "Year Ended 31.03.2025", "-1200.5", "verified", ""),
    ])
    sil = ss.silver(ss.load([p1, p2]))
    assert len(sil) == 1
    assert sil[0]["value_key"] == "-1200.5"


def test_f_recall_proxy_conflicts_disputed_and_cli(tmp_path: Path) -> None:
    _make_db(tmp_path / "read_dots.db", [
        ("doc1", 1, "Revenue from operations", "Q1 FY25", "100", "verified", ""),
        ("doc1", 1, "Other Income", "Q1 FY25", "20", "unverified", "lone_unlocated"),
        ("doc1", 2, "EBITDA Margin", "Q1 FY25", "15", "unverified", "row_elsewhere"),
        ("doc1", 2, "Finance Cost", "Q1 FY25", "8", "verified", ""),
    ])
    _make_db(tmp_path / "read_hy4.db", [
        ("doc1", 1, "Revenue from operations", "Q1 FY25", "100", "verified", ""),
        ("doc1", 1, "Other Income", "Q1 FY25", "20", "verified", ""),
        ("doc1", 2, "EBITDA Margin", "Q1 FY25", "15", "unverified", "column_elsewhere"),
        ("doc1", 2, "Finance Cost", "Q1 FY25", "9", "verified", ""),
    ])
    res = ss.score(tmp_path)
    dots = res["by_tag"]["dots"]
    hy4 = res["by_tag"]["hy4"]
    assert dots["silver"] == 3 and dots["verified"] == 1
    assert dots["recall_proxy"] == 1 / 3
    assert dots["conflicts"] == {"lone_unlocated": 1, "row_elsewhere": 1}
    assert dots["disputed"] == 1
    assert hy4["silver"] == 3 and hy4["verified"] == 2
    assert hy4["recall_proxy"] == 2 / 3
    assert hy4["conflicts"] == {"column_elsewhere": 1}
    assert hy4["disputed"] == 1

    assert res["by_page"][("doc1", 1)]["lost"] == 1
    assert res["by_page"][("doc1", 2)]["lost"] == 2

    out_csv = tmp_path / "out.csv"
    out_json = tmp_path / "out.json"
    rc = ss.main(["--dirs", str(tmp_path), "--out", str(out_csv), "--json", str(out_json)])
    assert rc == 0
    with out_csv.open(encoding="utf-8") as fh:
        csv_rows = list(csv.DictReader(fh))
    assert len(csv_rows) == 8
    assert {r["kind"] for r in csv_rows} == {"silver", "disputed"}
    payload = json.loads(out_json.read_text(encoding="utf-8"))
    assert payload["stores"][0]["by_page"][0]["page"] == 2
