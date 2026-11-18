"""T-223 (R-014): filing register tests on a tiny in-memory store and tiny BSE/NSE fixtures."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from reality_engine.pilot3 import filings, part_stamp, schema


def _make_store() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute(schema.TABLES["company"])
    conn.execute(schema.TABLES["doc"])
    conn.execute(schema.TABLES["doc_page"])
    conn.executemany(
        "INSERT INTO company VALUES (?,?,?,?,?,?,?)",
        [
            ("TST", "INE000A01010", "2020-01-01", None, "test", "599999", "Test Co Ltd"),
            ("OTH", "INE000B01010", "2020-01-01", None, "test", "588888", "Other Co Ltd"),
        ],
    )
    conn.executemany(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # 1. Held by attachment filename (source_key basename == BSE ATTACHMENTNAME)
            ("d_att", "TST", "INE000A01010", "results", "results", "Unrelated local title",
             "2025-05-10", "2025-05-10T18:00:00", 12, "sha1", "pages.db", r"D:\raw\TST\att_res.pdf"),
            # 2. Held by title prefix + known_at within 1 day (source_key basename differs from ATTACHMENTNAME)
            ("d_title", "TST", "INE000A01010", "deck", "deck",
             "Investor Presentation on Q4 FY25 financial performance",
             "2025-05-11", "2025-05-11T10:00:00", 24, "sha2", "pages.db", r"D:\raw\TST\newsid_only.pdf"),
            # 3. Link-only 1-page cover letter (held as 'announcement', exchange hints 'transcript')
            ("d_link", "TST", "INE000A01010", "announcement", "announcement", "Transcript cover letter",
             "2025-05-15", "2025-05-15T17:00:00", 1, "sha3", "pages.db", r"D:\raw\TST\cover_link.pdf"),
            # 4. Held doc that matches no filing on either exchange
            ("d_orphan", "TST", "INE000A01010", "announcement", "announcement", "Completely unindexed local doc",
             "2025-06-01", "2025-06-01T12:00:00", 2, "sha4", "pages.db", r"D:\raw\TST\local_only.pdf"),
            # 5. Another company's doc (must not be touched when symbols=["TST"])
            ("d_oth", "OTH", "INE000B01010", "results", "results", "Other Co Q1 results",
             "2025-05-12", "2025-05-12T15:00:00", 8, "sha5", "pages.db", r"D:\raw\OTH\oth_res.pdf"),
        ],
    )
    conn.executemany(
        "INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
        [
            ("d_link", "TST", 1,
             "The transcript of the earnings conference call is hosted at https://example.com/q4-call.pdf",
             "script_text", 92, "2025-05-15T17:00:00", None),
            ("d_orphan", "TST", 1,
             "Notice of registered office change https://example.com/office",
             "script_text", 60, "2025-06-01T12:00:00", None),
        ],
    )
    conn.commit()
    return conn


def _make_bse_db(path: Path) -> Path:
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE ann(NEWSID TEXT PRIMARY KEY, SCRIP_CD, ATTACHMENTNAME, NEWSSUB, HEADLINE, "
        "CATEGORYNAME, SUBCATNAME, NEWS_DT, DissemDT, symbol TEXT)"
    )
    con.executemany(
        "INSERT INTO ann VALUES (?,?,?,?,?,?,?,?,?,?)",
        [
            # Matches d_att by ATTACHMENTNAME
            ("bse-1", 599999, "att_res.pdf", "Financial Results", "Q4 FY25 Financial Results",
             "Result", "Financial Results", "2025-05-10T18:00:00", "2025-05-10T18:00:00", "TST"),
            # Matches d_title by title prefix + within 1 day (ATTACHMENTNAME differs)
            ("bse-2", 599999, "other_uuid.pdf", "Announcement under Reg 30 - Investor Presentation",
             "Investor Presentation on Q4 FY25 financial performance and outlook for FY26",
             "Company Update", "Investor Presentation", "2025-05-10T18:00:00", "2025-05-10T20:00:00", "TST"),
            # Matches d_link by ATTACHMENTNAME; exchange labels it transcript, doc.doc_type must stay 'announcement'
            ("bse-3", 599999, "cover_link.pdf", "Earnings Call Transcript", "Transcript cover letter",
             "Company Update", "Earnings Call Transcript", "2025-05-15T17:00:00", "2025-05-15T17:00:00", "TST"),
            # Not fetched (attachment present, no matching doc)
            ("bse-4", 599999, "missing_ar.pdf", "Reg. 34 (1) Annual Report", "Annual Report FY25",
             "Others", "Reg. 34 (1) Annual Report", "2026-02-15T14:00:00", "2026-02-15T14:00:00", "TST"),
            # No attachment
            ("bse-5", 599999, "", "Shareholding", "Shareholding pattern inline link",
             "Company Update", "Shareholding", "2025-05-20T11:00:00", "2025-05-20T11:00:00", "TST"),
            # Other company
            ("bse-oth", 588888, "oth_res.pdf", "Financial Results", "Other Co Q1 results",
             "Result", "Financial Results", "2025-05-12T15:00:00", "2025-05-12T15:00:00", "OTH"),
        ],
    )
    con.commit()
    con.close()
    return path


def _make_nse_root(root: Path) -> Path:
    row_common = {
        "symbol": "TST",
        "isin": "INE000A01010",
        "subject": "Credit Rating",
        "desc": "Credit Rating",
        "kind": "other",
        "known_at": "2025-05-18T16:00:00",
        "attachment_url": "https://nsearchives.nseindia.com/corporate/TST_rating.pdf",
        "seq_id": "9001",
        "raw": {
            "attchmntFile": "https://nsearchives.nseindia.com/corporate/TST_rating.pdf",
            "attchmntText": "Test Co Limited has informed the Exchange about Credit Rating reaffirmation.",
            "exchdisstime": "18-May-2025 16:00:00",
        },
    }
    row_held_by_nse_att = {
        "symbol": "TST",
        "isin": "INE000A01010",
        "subject": "Financial Result Updates",
        "desc": "Financial Result Updates",
        "kind": "other",
        "known_at": "2025-05-10T18:05:00",
        "attachment_url": "https://nsearchives.nseindia.com/corporate/att_res.pdf",
        "seq_id": "9002",
        "raw": {
            "attchmntFile": "https://nsearchives.nseindia.com/corporate/att_res.pdf",
            "attchmntText": "Test Co submitted financial results.",
            "exchdisstime": "10-May-2025 18:05:00",
        },
    }
    for folder, items in (
        ("tg_queue_2026-11-16", [row_common, row_held_by_nse_att]),
        ("run_2026-10-28", [row_common]),  # duplicate seq_id=9001 across two folders
    ):
        d = root / folder
        d.mkdir(parents=True, exist_ok=True)
        (d / "TST.jsonl").write_text("\n".join(json.dumps(x) for x in items) + "\n", encoding="utf-8")
    return root


def test_filings_register_matching_statuses_and_dedupe(tmp_path: Path):
    conn = _make_store()
    bse_db = _make_bse_db(tmp_path / "bse_announcements.db")
    nse_root = _make_nse_root(tmp_path / "nse_announcements")

    # Pre-seed an OTH filing row to verify per-symbol delete+rewrite leaves other companies alone.
    schema.ensure(conn, ("filing",))
    conn.execute(
        "INSERT INTO filing VALUES ('BSE','keep-oth','OTH','INE000B01010','2025-05-12T15:00:00',"
        "'Result','Financial Results','Keep me','oth_res.pdf','results','d_oth','results',8,NULL,'held')"
    )
    conn.commit()

    doc_types_before = dict(conn.execute("SELECT doc_key, doc_type FROM doc"))
    summary = filings.run(conn, symbols=["TST"], bse_db=bse_db, nse_root=nse_root)
    doc_types_after = dict(conn.execute("SELECT doc_key, doc_type FROM doc"))
    assert doc_types_after == doc_types_before  # kind_hint is never written into doc

    tst = summary["TST"]
    # BSE: 5 rows; NSE: 2 rows after seq_id=9001 deduped across two folders
    assert tst["by_exchange"] == {"BSE": 5, "NSE": 2}
    assert tst["held_docs_total"] == 4
    assert tst["held_docs_unmatched"] == 1  # d_orphan matched no filing

    rows = {
        (ex, fid): {
            "kind_hint": kh, "held_doc_key": dk, "held_doc_type": dt, "held_pages": pgs,
            "link_urls": json.loads(lu) if lu else None, "status": st, "headline": hl,
        }
        for ex, fid, kh, dk, dt, pgs, lu, st, hl in conn.execute(
            "SELECT exchange, filing_id, kind_hint, held_doc_key, held_doc_type, held_pages, "
            "link_urls, status, headline FROM filing WHERE symbol='TST'"
        )
    }
    assert rows[("BSE", "bse-1")]["status"] == "held"
    assert rows[("BSE", "bse-1")]["held_doc_key"] == "d_att"
    assert rows[("BSE", "bse-2")]["status"] == "held"
    assert rows[("BSE", "bse-2")]["held_doc_key"] == "d_title"
    assert rows[("BSE", "bse-3")]["status"] == "link_only"
    assert rows[("BSE", "bse-3")]["kind_hint"] == "transcript"
    assert rows[("BSE", "bse-3")]["held_doc_type"] == "announcement"
    assert rows[("BSE", "bse-3")]["link_urls"] == ["https://example.com/q4-call.pdf"]
    assert rows[("BSE", "bse-4")]["status"] == "not_fetched"
    assert rows[("BSE", "bse-4")]["kind_hint"] == "annual_report"
    assert rows[("BSE", "bse-5")]["status"] == "no_attachment"
    assert rows[("BSE", "bse-5")]["kind_hint"] == "shareholding"
    assert rows[("NSE", "9001")]["status"] == "not_fetched"
    assert rows[("NSE", "9001")]["kind_hint"] == "rating"
    assert rows[("NSE", "9002")]["status"] == "held"
    assert rows[("NSE", "9002")]["held_doc_key"] == "d_att"

    # Other company's row was preserved
    assert conn.execute("SELECT COUNT(*) FROM filing WHERE symbol='OTH'").fetchone()[0] == 1

    # View filing_coverage: Indian FY quarters (May 2025 -> Q1FY26, Feb 2026 -> Q4FY26)
    cov = {
        (fq, kh): (filed, held, link_only, not_fetched)
        for fq, kh, filed, held, link_only, not_fetched in conn.execute(
            "SELECT fiscal_quarter, kind_hint, filed, held, link_only, not_fetched "
            "FROM filing_coverage WHERE symbol='TST'"
        )
    }
    assert cov[("Q1FY26", "results")] == (2, 2, 0, 0)
    assert cov[("Q1FY26", "deck")] == (1, 1, 0, 0)
    assert cov[("Q1FY26", "transcript")] == (1, 0, 1, 0)
    assert cov[("Q1FY26", "rating")] == (1, 0, 0, 1)
    assert cov[("Q1FY26", "shareholding")] == (1, 0, 0, 0)
    assert cov[("Q4FY26", "annual_report")] == (1, 0, 0, 1)
    conn.close()


def test_part_stamp_places_filings_after_docs_collect():
    assert part_stamp.ORDER[part_stamp.ORDER.index("docs_collect") + 1] == "filings"
    assert "filings" in part_stamp.RECIPE
    assert part_stamp.PART_TABLES["filings"] == ("filing",)
    assert part_stamp.part_files("filings")
