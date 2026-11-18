"""T-223 (R-014): filing register tests on a tiny in-memory store and tiny BSE/NSE fixtures."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

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
            # 5. Pre-window held doc (must stay 'held')
            ("d_pre", "TST", "INE000A01010", "results", "results", "Pre-window Q3 results",
             "2024-02-10", "2024-02-10T15:00:00", 10, "sha5", "pages.db", r"D:\raw\TST\pre_res.pdf"),
            # 6. Solo BSE held doc on 2025-05-25 (to verify same-exchange filing never pairs as held_twin)
            ("d_solo", "TST", "INE000A01010", "results", "results", "Solo BSE Q4 note",
             "2025-05-25", "2025-05-25T15:00:00", 4, "sha6", "pages.db", r"D:\raw\TST\solo_bse.pdf"),
            # 7. Another company's doc (must not be touched when symbols=["TST"])
            ("d_oth", "OTH", "INE000B01010", "results", "results", "Other Co Q1 results",
             "2025-05-12", "2025-05-12T15:00:00", 8, "sha7", "pages.db", r"D:\raw\OTH\oth_res.pdf"),
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
        "CATEGORYNAME, SUBCATNAME, NEWS_DT, DissemDT, Fld_Attachsize, symbol TEXT)"
    )
    con.executemany(
        "INSERT INTO ann VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            # Matches d_att by ATTACHMENTNAME
            ("bse-1", 599999, "att_res.pdf", "Financial Results", "Q4 FY25 Financial Results",
             "Result", "Financial Results", "2025-05-10T18:00:00", "2025-05-10T18:00:00", 464415, "TST"),
            # Matches d_title by title prefix + within 1 day (ATTACHMENTNAME differs)
            ("bse-2", 599999, "other_uuid.pdf", "Announcement under Reg 30 - Investor Presentation",
             "Investor Presentation on Q4 FY25 financial performance and outlook for FY26",
             "Company Update", "Investor Presentation", "2025-05-10T18:00:00", "2025-05-10T20:00:00", 100000, "TST"),
            # Matches d_link by ATTACHMENTNAME; exchange labels it transcript, doc.doc_type must stay 'announcement'
            ("bse-3", 599999, "cover_link.pdf", "Earnings Call Transcript", "Transcript cover letter",
             "Company Update", "Earnings Call Transcript", "2025-05-15T17:00:00", "2025-05-15T17:00:00", 50000, "TST"),
            # Not fetched (in-window, attachment present, no matching doc, no twin)
            ("bse-4", 599999, "missing_ar.pdf", "Reg. 34 (1) Annual Report", "Annual Report FY25",
             "Others", "Reg. 34 (1) Annual Report", "2026-02-15T14:00:00", "2026-02-15T14:00:00", 900000, "TST"),
            # No attachment (in-window)
            ("bse-5", 599999, "", "Shareholding", "Shareholding pattern inline link",
             "Company Update", "Shareholding", "2025-05-20T11:00:00", "2025-05-20T11:00:00", None, "TST"),
            # Pre-window held (must stay 'held')
            ("bse-pre-held", 599999, "pre_res.pdf", "Financial Results", "Pre-window Q3 results",
             "Result", "Financial Results", "2024-02-10T15:00:00", "2024-02-10T15:00:00", 200000, "TST"),
            # Pre-window boundary 2024-03-31 not held -> 'out_of_window'
            ("bse-pre-miss", 599999, "pre_miss.pdf", "Credit Rating", "Old rating",
             "Company Update", "Credit Rating", "2024-03-31T23:50:00", "2024-03-31T23:50:00", 10000, "TST"),
            # Window start boundary 2024-04-01 not held -> 'not_fetched'
            ("bse-win-start", 599999, "win_start.pdf", "Credit Rating", "Day 1 rating",
             "Company Update", "Credit Rating", "2024-04-01T00:05:00", "2024-04-01T00:05:00", 10000, "TST"),
            # Solo BSE held on 2025-05-25 + same-exchange not-fetched on 2025-05-25 with identical size: must stay not_fetched
            ("bse-solo", 599999, "solo_bse.pdf", "Financial Results", "Solo BSE Q4 note",
             "Result", "Financial Results", "2025-05-25T15:00:00", "2025-05-25T15:00:00", 222222, "TST"),
            ("bse-same-ex", 599999, "bse_extra.pdf", "Financial Results", "Second BSE filing",
             "Result", "Financial Results", "2025-05-25T19:00:00", "2025-05-25T19:00:00", 222222, "TST"),
            # Other company
            ("bse-oth", 588888, "oth_res.pdf", "Financial Results", "Other Co Q1 results",
             "Result", "Financial Results", "2025-05-12T15:00:00", "2025-05-12T15:00:00", 123456, "OTH"),
        ],
    )
    con.commit()
    con.close()
    return path


def _make_nse_root(root: Path) -> Path:
    def _nse_row(seq_id: str, desc: str, known_at: str, att_name: str, text: str, file_size: str | None) -> dict:
        return {
            "symbol": "TST",
            "isin": "INE000A01010",
            "subject": desc,
            "desc": desc,
            "kind": "other",
            "known_at": known_at,
            "attachment_url": f"https://nsearchives.nseindia.com/corporate/{att_name}",
            "seq_id": seq_id,
            "file_size": file_size,
            "raw": {
                "attchmntFile": f"https://nsearchives.nseindia.com/corporate/{att_name}",
                "attchmntText": text,
                "attFileSize": file_size,
                "exchdisstime": known_at,
            },
        }

    # Duplicate across two folders (not_fetched, no held doc on 2025-05-18)
    row_dedupe = _nse_row("9001", "Credit Rating", "2025-05-18T16:00:00", "TST_rating.pdf", "Credit Rating.", "120.00 KB")
    # Held directly by attachment filename matching d_att
    row_held_att = _nse_row("9002", "Financial Result Updates", "2025-05-10T18:05:00", "att_res.pdf", "Results.", "453.53 KB")
    # Twin by size: BSE bse-1 (464415 B == 453.53 KB) on 2025-05-10, different filename & title
    row_twin_size = _nse_row("9003", "Outcome of Board Meeting", "2025-05-11T09:00:00", "nse_res_copy.pdf",
                             "Financial results board outcome.", "453.53 KB")
    # Twin refused when sizes differ (>2%): BSE bse-2 is 100000 B (~97.66 KB), NSE is 250.00 KB
    row_diff_size = _nse_row("9004", "Investor Presentation", "2025-05-10T21:00:00", "nse_deck_diff.pdf",
                             "Presentation.", "250.00 KB")

    for folder, items in (
        ("tg_queue_2026-11-16", [row_dedupe, row_held_att, row_twin_size, row_diff_size]),
        ("run_2026-10-28", [row_dedupe]),
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
        "'Result','Financial Results','Keep me','oth_res.pdf','results','d_oth','results',8,NULL,NULL,'held')"
    )
    conn.commit()

    doc_types_before = dict(conn.execute("SELECT doc_key, doc_type FROM doc"))
    summary = filings.run(conn, symbols=["TST"], bse_db=bse_db, nse_root=nse_root)
    doc_types_after = dict(conn.execute("SELECT doc_key, doc_type FROM doc"))
    assert doc_types_after == doc_types_before  # kind_hint is never written into doc

    tst = summary["TST"]
    # BSE: 10 rows; NSE: 4 rows after seq_id=9001 deduped across two folders
    assert tst["by_exchange"] == {"BSE": 10, "NSE": 4}
    assert tst["held_docs_total"] == 6
    assert tst["held_docs_unmatched"] == 1  # d_orphan matched no filing

    rows = {
        (ex, fid): {
            "kind_hint": kh, "held_doc_key": dk, "held_doc_type": dt, "held_pages": pgs,
            "link_urls": json.loads(lu) if lu else None, "twin_filing_id": tw, "status": st,
        }
        for ex, fid, kh, dk, dt, pgs, lu, tw, st in conn.execute(
            "SELECT exchange, filing_id, kind_hint, held_doc_key, held_doc_type, held_pages, "
            "link_urls, twin_filing_id, status FROM filing WHERE symbol='TST'"
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
    assert rows[("BSE", "bse-5")]["status"] == "no_attachment"

    # Window boundary: 2024-03-31 held stays 'held', not held becomes 'out_of_window'; 2024-04-01 stays 'not_fetched'
    assert rows[("BSE", "bse-pre-held")]["status"] == "held"
    assert rows[("BSE", "bse-pre-miss")]["status"] == "out_of_window"
    assert rows[("BSE", "bse-win-start")]["status"] == "not_fetched"

    # Cross-exchange twins: same-exchange stays not_fetched; size match -> held_twin; >2% size diff -> not_fetched
    assert rows[("BSE", "bse-same-ex")]["status"] == "not_fetched"
    assert rows[("NSE", "9002")]["status"] == "held"
    assert rows[("NSE", "9003")]["status"] == "held_twin"
    assert rows[("NSE", "9003")]["twin_filing_id"] == "bse-1"
    assert rows[("NSE", "9004")]["status"] == "not_fetched"
    assert rows[("NSE", "9001")]["status"] == "not_fetched"

    # Other company's row was preserved
    assert conn.execute("SELECT COUNT(*) FROM filing WHERE symbol='OTH'").fetchone()[0] == 1

    # View filing_coverage: excludes out_of_window, counts twin pair once in filed, includes twin & no_attachment
    cov = {
        (fq, kh): (filed, held, link_only, twin, not_fetched, no_attachment)
        for fq, kh, filed, held, link_only, twin, not_fetched, no_attachment in conn.execute(
            "SELECT fiscal_quarter, kind_hint, filed, held, link_only, twin, not_fetched, no_attachment "
            "FROM filing_coverage WHERE symbol='TST'"
        )
    }
    assert ("Q4FY24", "credit") not in cov and ("Q4FY24", "rating") not in cov  # out_of_window excluded
    assert cov[("Q4FY24", "results")] == (1, 1, 0, 0, 0, 0)  # pre-window held stays in coverage
    # Q1FY26 results: bse-1 (held), bse-solo (held), bse-same-ex (not_fetched), nse-9002 (held), nse-9003 (held_twin -> twin=1, filed+=0)
    assert cov[("Q1FY26", "results")] == (4, 3, 0, 1, 1, 0)
    assert cov[("Q1FY26", "deck")] == (2, 1, 0, 0, 1, 0)
    assert cov[("Q1FY26", "transcript")] == (1, 0, 1, 0, 0, 0)
    assert cov[("Q1FY26", "shareholding")] == (1, 0, 0, 0, 0, 1)
    assert cov[("Q1FY25", "rating")] == (1, 0, 0, 0, 1, 0)  # 2024-04-01 boundary
    assert cov[("Q4FY26", "annual_report")] == (1, 0, 0, 0, 1, 0)
    conn.close()


def test_missing_size_twin_requires_single_same_kind_hint_candidate(tmp_path: Path):
    conn = sqlite3.connect(":memory:")
    conn.execute(schema.TABLES["company"])
    conn.execute(schema.TABLES["doc"])
    conn.execute(schema.TABLES["doc_page"])
    conn.execute("INSERT INTO company VALUES ('TST','INE000A01010','2020-01-01',NULL,'test','599999','Test Co')")
    conn.executemany(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # Two held results docs on 2025-07-10
            ("d_r1", "TST", "INE000A01010", "results", "results", "Standalone results",
             "2025-07-10", "2025-07-10T15:00:00", 5, "s1", "pages.db", r"D:\raw\r1.pdf"),
            ("d_r2", "TST", "INE000A01010", "results", "results", "Consolidated results",
             "2025-07-10", "2025-07-10T16:00:00", 5, "s2", "pages.db", r"D:\raw\r2.pdf"),
            # One held deck doc on 2025-07-10 (different kind_hint, same day)
            ("d_dk", "TST", "INE000A01010", "deck", "deck", "Q1 presentation",
             "2025-07-10", "2025-07-10T17:00:00", 12, "s3", "pages.db", r"D:\raw\dk.pdf"),
        ],
    )
    conn.commit()

    bse_db = tmp_path / "bse.db"
    bcon = sqlite3.connect(bse_db)
    bcon.execute(
        "CREATE TABLE ann(NEWSID TEXT PRIMARY KEY, SCRIP_CD, ATTACHMENTNAME, NEWSSUB, HEADLINE, "
        "CATEGORYNAME, SUBCATNAME, NEWS_DT, DissemDT, Fld_Attachsize, symbol TEXT)"
    )
    bcon.executemany(
        "INSERT INTO ann VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("bse-r1", 599999, "r1.pdf", "Financial Results", "Standalone results", "Result", "Financial Results",
             "2025-07-10T15:00:00", "2025-07-10T15:00:00", None, "TST"),
            ("bse-r2", 599999, "r2.pdf", "Financial Results", "Consolidated results", "Result", "Financial Results",
             "2025-07-10T16:00:00", "2025-07-10T16:00:00", None, "TST"),
            ("bse-dk", 599999, "dk.pdf", "Investor Presentation", "Q1 presentation", "Company Update",
             "Investor Presentation", "2025-07-10T17:00:00", "2025-07-10T17:00:00", None, "TST"),
        ],
    )
    bcon.commit()
    bcon.close()

    nse_root = tmp_path / "nse"
    (nse_root / "tg_queue_2026-11-16").mkdir(parents=True)
    nse_items = [
        {
            "symbol": "TST", "isin": "INE000A01010", "subject": "Financial Result Updates",
            "desc": "Financial Result Updates", "kind": "other", "known_at": "2025-07-10T15:30:00",
            "attachment_url": "https://nsearchives.nseindia.com/corporate/nse_r.pdf", "seq_id": "nse-r",
            "file_size": "-", "raw": {"attchmntFile": "nse_r.pdf", "attchmntText": "Results.", "attFileSize": "-"},
        },
        {
            "symbol": "TST", "isin": "INE000A01010", "subject": "Investor Presentation",
            "desc": "Investor Presentation", "kind": "other", "known_at": "2025-07-10T17:10:00",
            "attachment_url": "https://nsearchives.nseindia.com/corporate/nse_dk.pdf", "seq_id": "nse-dk",
            "file_size": "-", "raw": {"attchmntFile": "nse_dk.pdf", "attchmntText": "Deck.", "attFileSize": "-"},
        },
    ]
    (nse_root / "tg_queue_2026-11-16" / "TST.jsonl").write_text(
        "\n".join(json.dumps(x) for x in nse_items) + "\n", encoding="utf-8"
    )

    filings.run(conn, symbols=["TST"], bse_db=bse_db, nse_root=nse_root)
    got = dict(conn.execute("SELECT filing_id, status || ':' || COALESCE(twin_filing_id, '') FROM filing WHERE exchange='NSE'"))
    assert got["nse-r"] == "not_fetched:"     # refused: two held results candidates on 2025-07-10 with no sizes
    assert got["nse-dk"] == "held_twin:bse-dk"  # matched: exactly one held deck candidate on 2025-07-10
    conn.close()


def test_part_stamp_places_filings_after_docs_collect():
    assert part_stamp.ORDER[part_stamp.ORDER.index("docs_collect") + 1] == "filings"
    assert "filings" in part_stamp.RECIPE
    assert part_stamp.PART_TABLES["filings"] == ("filing",)
    assert part_stamp.part_files("filings")
