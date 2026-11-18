"""T-223 (R-012/R-014): unit and integration tests for pilot3.link_follow (no network, no live stores)."""
from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from reality_engine.pilot3 import docs_collect, link_follow as lf, schema  # noqa: E402


def _make_pdf(pages: list[str], link_uri: str | None = None) -> bytes:
    doc = pymupdf.open()
    for idx, text in enumerate(pages):
        page = doc.new_page()
        page.insert_text((40, 60), text, fontsize=11)
        if idx == 0 and link_uri:
            page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(40, 80, 400, 120), "uri": link_uri})
    data = doc.tobytes()
    doc.close()
    return data


def _init_store(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    schema.create(conn, ("company", "doc", "doc_page", "filing"))
    conn.execute(
        "INSERT INTO company VALUES ('NAVKAR','INE278M01019','2020-01-01',NULL,'logistics','539332',"
        "'Navkar Corporation Limited')"
    )
    conn.execute(
        "INSERT INTO company VALUES ('JSWINFRA','INE880J01026','2020-01-01',NULL,'ports','543994',"
        "'JSW Infrastructure Limited')"
    )
    conn.commit()
    return conn


# --------------------------------------------------------------------------- classify_letter (evidence rows)
def test_classify_letter_covers_all_evidence_rows():
    # c08 NAVKARCORP: transcript PDF
    intent, targets = lf.classify_letter(
        "Please find the link of transcript of investor conference call.",
        ["https://navkarcorp.com/upload_data/Files/transcript-of-investor-conference-call-16-10-2025.pdf"],
    )
    assert intent == "transcript"
    assert targets == ["https://navkarcorp.com/upload_data/Files/transcript-of-investor-conference-call-16-10-2025.pdf"]

    # c08 NAVKARCORP: mp3 audio recording
    intent, targets = lf.classify_letter(
        "Audio recording of investor call.",
        ["https://navkarcorp.com/upload_data/Files/investor-call-audio-recording-27-10-2026.mp3"],
    )
    assert intent == "audio" and targets == []

    # c08 JSW / NAVKARCORP: 3-page call invitation with parent site + choruscall DiamondPass
    intent, targets = lf.classify_letter(
        "An earnings conference call is scheduled to be held on October 28, 2025. Registration details below.",
        ["https://www.jsw.in/infrastructure", "https://services.choruscall.in/DiamondPassRegistration/register?confirmationNu"],
    )
    assert intent == "invitation" and targets == []

    # c02 SEAMECLTD: bare homepage only -> no target; mp3 -> audio
    intent, targets = lf.classify_letter("Intimation of schedule of analyst meet.", ["https://www.seamec.in/"])
    assert targets == []
    intent, targets = lf.classify_letter(
        "Link of audio recording.",
        ["https://www.seamec.in/", "https://seamec.in/upload/Seamec%20Earnings%20call.mp3"],
    )
    assert intent == "audio" and targets == []

    # c05 MANINFRA: investor page with transcript uploaded
    intent, targets = lf.classify_letter(
        "The transcript of the conference call has been uploaded on our website.",
        ["https://www.maninfra.com/analyst-corner/"],
    )
    assert intent == "transcript" and targets == ["https://www.maninfra.com/analyst-corner/"]

    # c06 SUBEXLTD: fragment dropped
    intent, targets = lf.classify_letter(
        "Transcript of the investor call is available at:",
        ["https://www.subex.com/investors/announcement-filing/#investor-analyst-call"],
    )
    assert intent == "transcript"
    assert targets == ["https://www.subex.com/investors/announcement-filing/"]

    # c07 SPMLINFRA: mp3, mediafire .../file -> audio; zoom/kaptify -> invitation
    for audio_url in (
        "https://spml.co.in/SPML-Concall-12-11-2024.mp3",
        "https://www.mediafire.com/file/abc123/Concall-12-11-2024.mp3/file",
    ):
        assert lf.classify_letter("Recording of the call.", [audio_url]) == ("audio", [])
    for reg_url in ("https://zoom.us/j/12345", "https://kaptify.in/webinar/1", "https://reg.dsnl.in/call"):
        assert lf.classify_letter("Join our conference call.", [reg_url]) == ("invitation", [])

    # c08 JSW: tinyurl shortener kept as target
    intent, targets = lf.classify_letter(
        "Transcript of Q1 FY27 earnings call.",
        ["https://tinyurl.com/JSWInfraQ1FY27"],
    )
    assert intent == "transcript" and targets == ["https://tinyurl.com/JSWInfraQ1FY27"]

    # 'transcript will be' alone does not count as transcript; deck & pdf-first ordering
    intent, targets = lf.classify_letter(
        "The audio recording is available and the transcript will be uploaded shortly.",
        ["https://example.com/ir/"],
    )
    assert intent != "transcript"

    intent, targets = lf.classify_letter(
        "Investor Presentation for Q2 FY26.",
        ["https://example.com/ir/", "https://example.com/q2-deck.pdf"],
    )
    assert intent == "deck"
    assert targets == ["https://example.com/q2-deck.pdf", "https://example.com/ir/"]


# --------------------------------------------------------------------------- resolve
def test_resolve_html_page_picks_by_date_and_quarter_tag():
    good_pdf = _make_pdf([
        "Navkar Corporation Limited\nConference Call Transcript\nOctober 16, 2025",
        "Moderator: Ladies and gentlemen, good day.",
        "Management discussion.",
        "Q&A session.",
    ])
    old_pdf = _make_pdf([
        "Navkar Corporation Limited\nConference Call Transcript\nJanuary 28, 2024",
        "Moderator: Good day.",
        "Page 3",
    ])
    html_by_date = (
        "<html><body>"
        "<a href='/files/old-call-28-01-2024.pdf'>Transcript 28th January 2024</a>"
        "<a href='/files/call-16-10-2025.pdf'>Earnings Call Transcript 16-10-2025</a>"
        "</body></html>"
    ).encode()
    html_by_qtag = (
        "<html><body>"
        "<a href='/files/other.pdf'>Board Meeting Outcome</a>"
        "<a href='/files/q3-fy26-concall.pdf'>Concall Transcript Q3 FY 2026</a>"
        "</body></html>"
    ).encode()
    q3_pdf = _make_pdf([
        "Navkar Corporation Limited\nConference Call Transcript\nJanuary 28, 2026",
        "Moderator: Welcome everyone.",
        "Page 3",
    ])

    def fake_get(url: str) -> tuple[str, str, bytes]:
        if url == "https://navkarcorp.com/ir/":
            return url, "text/html", html_by_date
        if url == "https://navkarcorp.com/qtag/":
            return url, "text/html", html_by_qtag
        if url.endswith("call-16-10-2025.pdf"):
            return url, "application/pdf", good_pdf
        if url.endswith("q3-fy26-concall.pdf"):
            return url, "application/pdf", q3_pdf
        return url, "application/pdf", old_pdf

    res_date = lf.resolve(
        "https://navkarcorp.com/ir/",
        "transcript",
        "2025-10-18",
        ["NAVKAR", "Navkar Corporation Limited"],
        get=fake_get,
    )
    assert res_date["status"] == "resolved"
    assert res_date["url"].endswith("call-16-10-2025.pdf")
    assert res_date["pages"] == 4
    assert res_date["kind"] == "transcript"

    res_q = lf.resolve(
        "https://navkarcorp.com/qtag/",
        "transcript",
        "2026-01-30",
        ["NAVKAR", "Navkar Corporation Limited"],
        get=fake_get,
    )
    assert res_q["status"] == "resolved"
    assert res_q["url"].endswith("q3-fy26-concall.pdf")


def test_resolve_rejections_and_one_hop_cover_redirect():
    parent_pdf = _make_pdf([
        "JSW Steel Limited\nQ1 FY27 Conference Call Transcript\nJuly 20, 2026",
        "Moderator: Welcome to JSW Steel.",
        "Page 3",
    ])
    short_pdf = _make_pdf([
        "JSW Infrastructure Limited\nConference Call Transcript",
        "Moderator: Welcome.",
    ])
    cover_pdf = _make_pdf(
        ["Please see link to transcript."],
        link_uri="https://jswinfra.in/full-q1.pdf",
    )
    full_tx = _make_pdf([
        "JSW Infrastructure Limited\nQ1 FY27 Earnings Call\nJuly 20, 2026",
        "Moderator: Ladies and gentlemen, good day.",
        "Page 3",
        "Page 4",
        "Page 5",
    ])
    deck_pdf = _make_pdf([
        "JSW Infrastructure Limited\nInvestor Presentation Q1 FY27",
        "Key Financial Highlights",
        "Port Capacity",
        "Capital Expenditure",
        "Thank You",
    ])
    not_tx_pdf = _make_pdf([
        "JSW Infrastructure Limited\nPress Release on Port Volume",
        "Details of cargo handled.",
        "Page 3",
    ])
    stale_pdf = _make_pdf([
        "JSW Infrastructure Limited\nConference Call Transcript\nJanuary 10, 2024",
        "Moderator: Old call.",
        "Page 3",
    ])

    class NotFound(Exception):
        status_code = 404

    def fake_get(url: str) -> tuple[str, str, bytes]:
        if url.endswith("parent.pdf"):
            return url, "application/pdf", parent_pdf
        if url.endswith("short.pdf"):
            return url, "application/pdf", short_pdf
        if url.endswith("cover.pdf"):
            return url, "application/pdf", cover_pdf
        if url.endswith("full-q1.pdf"):
            return url, "application/pdf", full_tx
        if url.endswith("deck.pdf"):
            return url, "application/pdf", deck_pdf
        if url.endswith("not_tx.pdf"):
            return url, "application/pdf", not_tx_pdf
        if url.endswith("stale.pdf"):
            return url, "application/pdf", stale_pdf
        if url.endswith("404.pdf"):
            raise NotFound()
        if url.endswith("neterr.pdf"):
            raise OSError("connection reset")
        if url.endswith("nopdf.html"):
            return url, "text/html", b"<html><body>No documents here</body></html>"
        if url.endswith("nomatch.html"):
            return url, "text/html", b"<html><body><a href='/a.pdf'>Notice</a></body></html>"
        return url, "text/plain", b"not a pdf"

    names = ["JSWINFRA", "JSW Infrastructure Limited"]
    parent_res = lf.resolve("https://x/parent.pdf", "transcript", "2026-07-22", names, get=fake_get)
    assert parent_res["reason"] == "other_company"
    assert parent_res["printed_company"] == "JSW Steel Limited"
    assert lf.resolve("https://x/short.pdf", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "too_short"
    assert lf.resolve("https://x/not_tx.pdf", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "not_transcript"
    assert lf.resolve("https://x/stale.pdf", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "date_mismatch"
    assert lf.resolve("https://x/404.pdf", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "http_404"
    assert lf.resolve("https://x/neterr.pdf", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "network"
    assert lf.resolve("https://x/nopdf.html", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "no_pdf_on_page"
    assert lf.resolve("https://x/nomatch.html", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "no_matching_pdf"
    assert lf.resolve("https://x/plain.txt", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "not_pdf"

    # 1-page PDF cover followed once
    res_cover = lf.resolve("https://x/cover.pdf", "transcript", "2026-07-22", names, get=fake_get)
    assert res_cover["status"] == "resolved" and res_cover["url"].endswith("full-q1.pdf")

    # Deck checks: 5+ page non-transcript passes; transcript fails deck intent; 3-page deck fails too_short
    res_deck = lf.resolve("https://x/deck.pdf", "deck", "2026-07-22", names, get=fake_get)
    assert res_deck["status"] == "resolved" and res_deck["kind"] == "deck" and res_deck["pages"] == 5
    assert lf.resolve("https://x/full-q1.pdf", "deck", "2026-07-22", names, get=fake_get)["reason"] == "not_transcript"
    assert lf.resolve("https://x/not_tx.pdf", "deck", "2026-07-22", names, get=fake_get)["reason"] == "too_short"


# --------------------------------------------------------------------------- plan_store & apply_plan
def test_plan_store_twin_dedupe_exchange_not_fetched_and_idempotent_manifest(tmp_path: Path):
    db_path = tmp_path / "store.db"
    conn = _init_store(db_path)

    tx_pdf = _make_pdf([
        "Navkar Corporation Limited\nEarnings Call Transcript\nMay 15, 2025",
        "Moderator: Welcome.",
        "Page 3",
    ])
    deck_pdf = _make_pdf([
        "Navkar Corporation Limited\nInvestor Presentation Q4 FY25",
        "Overview",
        "Financials",
        "Outlook",
        "Thank you",
    ])
    held_pdf = _make_pdf([
        "Navkar Corporation Limited\nAlready Held Transcript\nFebruary 10, 2025",
        "Moderator: Already held.",
        "Page 3",
    ])
    held_sha = hashlib.sha256(held_pdf).hexdigest()

    conn.executemany(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("d_tx_cover", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover",
             "2025-05-16", "2025-05-16T18:00:00", 1, "sha_c1", "pages.db", "c1.pdf"),
            ("d_tx_cover_nse", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover NSE",
             "2025-05-16", "2025-05-16T17:00:00", 1, "sha_c2", "pages.db", "c2.pdf"),
            ("d_held_cover", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover Held",
             "2025-02-12", "2025-02-12T10:00:00", 1, "sha_c3", "pages.db", "c3.pdf"),
            ("d_existing_tx", "NAVKAR", "INE278M01019", "transcript", "transcript", "Held tx",
             "2025-02-10", "2025-02-10T10:00:00", 3, held_sha, "pages.db", "held_tx.pdf"),
        ],
    )
    conn.executemany(
        "INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
        [
            ("d_tx_cover", "NAVKAR", 1, "Please find transcript at https://navkar.com/q4.pdf",
             "script_text", 48, "2025-05-16T18:00:00", None),
            ("d_tx_cover_nse", "NAVKAR", 1, "Please find transcript at https://navkar.com/q4.pdf",
             "script_text", 48, "2025-05-16T17:00:00", None),
            ("d_held_cover", "NAVKAR", 1, "Please find transcript at https://navkar.com/already.pdf",
             "script_text", 50, "2025-02-12T10:00:00", None),
        ],
    )
    conn.executemany(
        "INSERT INTO filing VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # Twin link_only letters pointing to the same URL: NSE (17:00) is earlier than BSE (18:00)
            ("BSE", "b1", "NAVKAR", "INE278M01019", "2025-05-16T18:00:00", "Company Update",
             "Earnings Call Transcript", "Transcript link", "c1.pdf", "transcript",
             "d_tx_cover", "announcement", 1, json.dumps(["https://navkar.com/q4.pdf"]), None, None, "link_only"),
            ("NSE", "n1", "NAVKAR", "INE278M01019", "2025-05-16T17:00:00", "other",
             "Earnings Call Transcript", "Transcript link", "https://nse/c2.pdf", "transcript",
             "d_tx_cover_nse", "announcement", 1, json.dumps(["https://navkar.com/q4.pdf"]), None, None, "link_only"),
            # Already held by sha
            ("BSE", "b2", "NAVKAR", "INE278M01019", "2025-02-12T10:00:00", "Company Update",
             "Earnings Call Transcript", "Held link", "c3.pdf", "transcript",
             "d_held_cover", "announcement", 1, json.dumps(["https://navkar.com/already.pdf"]), None, None, "link_only"),
            # not_fetched deck on BSE (uses AttachHis URL)
            ("BSE", "b3", "NAVKAR", "INE278M01019", "2025-05-15T12:00:00", "Company Update",
             "Investor Presentation", "Q4 Deck", "navkar_deck.pdf", "deck",
             None, None, None, None, None, None, "not_fetched"),
        ],
    )
    conn.commit()
    conn.close()

    fetches: list[str] = []

    def fake_get(url: str) -> tuple[str, str, bytes]:
        fetches.append(url)
        if url == "https://navkar.com/q4.pdf":
            return url, "application/pdf", tx_pdf
        if url == "https://navkar.com/already.pdf":
            return url, "application/pdf", held_pdf
        if url == "https://www.bseindia.com/xml-data/corpfiling/AttachHis/navkar_deck.pdf":
            return url, "application/pdf", deck_pdf
        raise AssertionError(f"unexpected URL {url}")

    items = lf.plan_store(db_path, get=fake_get)
    # q4.pdf fetched ONCE and attributed to NSE n1 (17:00 < 18:00)
    assert fetches.count("https://navkar.com/q4.pdf") == 1
    assert len(items) == 3

    by_fid = {it["filing_id"]: it for it in items}
    assert by_fid["n1"]["outcome"] == "resolved" and by_fid["n1"]["source"] == "link_follow"
    assert by_fid["b2"]["outcome"] == "held" and by_fid["b2"]["sha256"] == held_sha
    assert by_fid["b3"]["outcome"] == "resolved" and by_fid["b3"]["source"] == "exchange"

    # Pre-seed manifest.csv with one existing row to verify append never rewrites existing rows
    store_dir = tmp_path / "store"
    manifest = store_dir / "raw" / "manifest.csv"
    manifest.parent.mkdir(parents=True)
    with manifest.open("w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=lf.MANIFEST_HEADER)
        w.writeheader()
        w.writerow({"isin": "INE000000000", "symbol_at_time": "KEEP", "newsid": "existing:1",
                    "sha256": "deadbeef", "status": "ok"})

    counts = lf.apply_plan(store_dir, items, raw_root=tmp_path / "raw_linked")
    assert counts == {"resolved": 2, "held": 1}

    # Re-applying is idempotent
    counts2 = lf.apply_plan(store_dir, items, raw_root=tmp_path / "raw_linked")
    assert counts2 == {"resolved": 2, "held": 1}

    with manifest.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        assert tuple(reader.fieldnames or ()) == lf.MANIFEST_HEADER
        mrows = list(reader)
    assert len(mrows) == 3  # 1 existing + 2 new, no duplicates
    assert mrows[0]["newsid"] == "existing:1"
    by_nid = {r["newsid"]: r for r in mrows}
    assert by_nid["link:NSE:n1"]["bucket"] == "concall_transcript"
    assert by_nid["link:NSE:n1"]["dissem_ts"] == "2025-05-16T17:00:00"
    assert by_nid["link:BSE:b3"]["bucket"] == "investor_presentation"
    assert by_nid["link:BSE:b3"]["source"] == "exchange"
    assert len(docs_collect._manifest_rows(manifest)) == 3

    run_csvs = list((store_dir / "link_follow").glob("*.csv"))
    assert len(run_csvs) == 2
    assert "data" not in run_csvs[0].read_text(encoding="utf-8").splitlines()[0]


# --------------------------------------------------------------------------- find_site_docs & CLI
def test_find_site_docs_and_cli(tmp_path: Path, capsys):
    store_dir = tmp_path / "c05"
    store_dir.mkdir()
    db_path = store_dir / "c05.db"
    conn = _init_store(db_path)
    # 3 held docs naming www.maninfra.com on page 1, plus excluded registrar/exchange domains
    for i in range(1, 4):
        dk = f"d_{i}"
        conn.execute(
            "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (dk, "NAVKAR", "INE278M01019", "results", "results", f"R{i}",
             "2025-05-10", "2025-05-10T10:00:00", 1, f"sh_{i}", "pages.db", f"f{i}.pdf"),
        )
        conn.execute(
            "INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
            (dk, "NAVKAR", 1,
             "Visit www.navkarcorp.com or www.bseindia.com and linkintime.co.in",
             "script_text", 60, "2025-05-10T10:00:00", None),
        )
    conn.commit()
    conn.close()

    site_tx = _make_pdf([
        "Navkar Corporation Limited\nEarnings Call Transcript\nAugust 10, 2025",
        "Moderator: Welcome.",
        "Page 3",
    ])

    def fake_get(url: str) -> tuple[str, str, bytes]:
        if url == "https://www.navkarcorp.com/":
            return url, "text/html", (
                b"<html><body><a href='/investors'>Investor Relations</a></body></html>"
            )
        if url == "https://www.navkarcorp.com/investors":
            return url, "text/html", (
                b"<html><body>"
                b"<a href='/files/q1fy26-transcript.pdf'>Earnings Call Transcript 10-08-2025</a>"
                b"<a href='/files/undated-transcript.pdf'>Earnings Call Transcript</a>"
                b"<a href='/files/old-transcript.pdf'>Earnings Call Transcript 10-01-2023</a>"
                b"</body></html>"
            )
        if url == "https://www.navkarcorp.com/files/q1fy26-transcript.pdf":
            return url, "application/pdf", site_tx
        raise AssertionError(url)

    res = lf.find_site_docs(db_path, "NAVKAR", get=fake_get, since="2024-04-01")
    assert res["verdict"] == "found"
    assert res["website"] == "https://www.navkarcorp.com/"
    assert res["pages_crawled"] == 2
    assert res["undated_skipped"] == 1
    assert len(res["items"]) == 1
    assert res["items"][0]["exchange"] == "SITE"
    assert res["items"][0]["source"] == "company_site"
    assert res["items"][0]["outcome"] == "resolved"

    # SITE dissem_ts must be fetched_at (never back-dated)
    lf.apply_plan(store_dir, res["items"], raw_root=tmp_path / "site_raw")
    with (store_dir / "raw" / "manifest.csv").open("r", encoding="utf-8", newline="") as fh:
        srow = next(csv.DictReader(fh))
    assert srow["dissem_ts"] == srow["fetched_at"] and srow["dissem_ts"] != ""

    # JSWINFRA has 0 hits -> no_website
    assert lf.find_site_docs(db_path, "JSWINFRA", get=fake_get)["verdict"] == "no_website"

    # CLI --plan-only --json
    out_json = tmp_path / "plan.json"
    rc = lf.main(["--store-dir", str(store_dir), "--plan-only", "--symbols", "NAVKAR", "--json", str(out_json)])
    assert rc == 0
    out_text = capsys.readouterr().out
    assert "| NAVKAR |" in out_text
    assert "link letters by intent" in out_text
    assert json.loads(out_json.read_text(encoding="utf-8")) == []


# --------------------------------------------------------------------------- Round 2 fixes
def test_fiscal_year_range_tag_parsing_and_seamec_site_q1_fy2026_27(tmp_path: Path):
    assert lf.parse_quarter_tag("Q1 FY 2026-27") == "Q1FY27"
    assert lf.parse_quarter_tag("Q2 FY 2024-25") == "Q2FY25"
    assert lf.parse_quarter_tag("Q4 FY24") == "Q4FY24"
    assert lf.parse_quarter_tag("Q4 FY 2026") == "Q4FY26"
    assert lf._quarter_matches_text("Transcripts of Earning Call for Q1 FY 2026-27.pdf", "Q1FY27") is True
    assert lf._quarter_matches_text("Transcripts of Earning Call for Q1 FY 2026-27.pdf", "Q1FY26") is False

    db_path = tmp_path / "seamec.db"
    conn = _init_store(db_path)
    conn.execute(
        "INSERT INTO company VALUES ('SEAMECLTD','INE497B01018','2020-01-01',NULL,'shipping','526807',"
        "'Seamec Limited')"
    )
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"s_{i}", "SEAMECLTD", "INE497B01018", "results", "results", f"R{i}",
             "2026-05-10", "2026-05-10T10:00:00", 2, f"ss_{i}", "pages.db", f"s{i}.pdf"),
        )
        conn.execute(
            "INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
            (f"s_{i}", "SEAMECLTD", 1, "Visit www.seamec.in", "script_text", 20, "2026-05-10T10:00:00", None),
        )
    conn.commit()
    conn.close()

    seamec_tx = _make_pdf([
        "Seamec Limited\nQ1 FY 2026-27 Earnings Call Transcript\nAugust 14, 2026",
        "Moderator: Ladies and gentlemen, good day.",
        "Management discussion.",
    ])

    def fake_get(url: str) -> tuple[str, str, bytes]:
        if url == "https://www.seamec.in/":
            return url, "text/html", (
                b"<html><body>"
                b"<a href='/upload/Transcripts%20of%20Earning%20Call%20for%20Q1%20FY%202026-27.pdf'>"
                b"Transcripts of Earning Call for Q1 FY 2026-27</a>"
                b"</body></html>"
            )
        if "2026-27" in url:
            return url, "application/pdf", seamec_tx
        raise AssertionError(url)

    res = lf.find_site_docs(db_path, "SEAMECLTD", get=fake_get, since="2024-04-01")
    assert res["verdict"] == "found"
    assert len(res["items"]) == 1
    assert res["items"][0]["outcome"] == "resolved"


def test_site_finder_runs_only_for_missing_kinds_and_site_all_overrides(tmp_path: Path):
    store_dir = tmp_path / "c_kinds"
    store_dir.mkdir()
    db_path = store_dir / "c_kinds.db"
    conn = _init_store(db_path)
    for i in range(1, 4):
        conn.execute(
            "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (f"r_{i}", "NAVKAR", "INE278M01019", "results", "results", f"R{i}",
             "2025-05-10", "2025-05-10T10:00:00", 2, f"rs_{i}", "pages.db", f"r{i}.pdf"),
        )
        conn.execute(
            "INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
            (f"r_{i}", "NAVKAR", 1, "www.navkarcorp.com", "script_text", 20, "2025-05-10T10:00:00", None),
        )
    # NAVKAR holds a transcript (>=3 pages) and a deck since 2024-04-01
    conn.execute(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("tx_1", "NAVKAR", "INE278M01019", "transcript", "transcript", "Held tx",
         "2025-05-15", "2025-05-15T10:00:00", 10, "txsha", "pages.db", "tx1.pdf"),
    )
    conn.execute(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        ("dk_1", "NAVKAR", "INE278M01019", "deck", "deck", "Held deck",
         "2025-05-15", "2025-05-15T10:00:00", 15, "dksha", "pages.db", "dk1.pdf"),
    )
    conn.commit()
    conn.close()

    fetches: list[str] = []

    def fake_get(url: str) -> tuple[str, str, bytes]:
        fetches.append(url)
        if url == "https://www.navkarcorp.com/":
            return url, "text/html", (
                b"<html><body>"
                b"<a href='/files/q2-transcript-10-10-2025.pdf'>Transcript 10-10-2025</a>"
                b"<a href='/files/q2-presentation-10-10-2025.pdf'>Investor Presentation 10-10-2025</a>"
                b"</body></html>"
            )
        if url.endswith("q2-transcript-10-10-2025.pdf"):
            return url, "application/pdf", _make_pdf([
                "Navkar Corporation Limited\nTranscript\nOctober 10, 2025",
                "Moderator: Welcome.",
                "Page 3",
            ])
        return url, "application/pdf", _make_pdf([
            "Navkar Corporation Limited\nInvestor Presentation\nOctober 10, 2025",
            "Slide 2", "Slide 3", "Slide 4", "Slide 5",
        ])

    # Default kinds=None -> both transcript and deck already held -> not_needed with zero fetches
    res_skip = lf.find_site_docs(db_path, "NAVKAR", get=fake_get, since="2024-04-01")
    assert res_skip["verdict"] == "not_needed"
    assert fetches == []

    # Override with kinds=('transcript', 'deck') (as --site-all does) -> crawls and resolves both
    res_all = lf.find_site_docs(db_path, "NAVKAR", get=fake_get, since="2024-04-01", kinds=("transcript", "deck"))
    assert res_all["verdict"] == "found"
    assert len(fetches) > 0
    assert sorted(it["kind"] for it in res_all["items"]) == ["deck", "transcript"]

    # When only deck is missing, only deck is fetched (transcript PDF skipped)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM doc WHERE doc_key='dk_1'")
    conn.commit()
    conn.close()
    fetches.clear()
    res_deck_only = lf.find_site_docs(db_path, "NAVKAR", get=fake_get, since="2024-04-01")
    assert res_deck_only["verdict"] == "found"
    assert [it["kind"] for it in res_deck_only["items"]] == ["deck"]
    assert not any("transcript" in u for u in fetches)


def test_same_call_dedupe_dup_in_plan_needs_ocr_and_report(tmp_path: Path):
    db_path = tmp_path / "dedupe.db"
    conn = _init_store(db_path)

    # Store already holds a transcript with printed call date May 15, 2025 (different bytes) and a deck on May 15, 2025
    conn.executemany(
        "INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            ("held_tx_call", "NAVKAR", "INE278M01019", "transcript", "transcript", "Held call",
             "2025-05-20", "2025-05-20T18:00:00", 8, "sha_held_tx", "pages.db", "held_tx.pdf"),
            ("held_dk_call", "NAVKAR", "INE278M01019", "deck", "deck", "Held deck",
             "2025-05-15", "2025-05-15T18:00:00", 12, "sha_held_dk", "pages.db", "held_dk.pdf"),
            ("cov_same_tx", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover 1",
             "2025-05-19", "2025-05-19T10:00:00", 1, "sha_c1", "pages.db", "c1.pdf"),
            ("cov_new_1", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover 2",
             "2025-08-12", "2025-08-12T10:00:00", 1, "sha_c2", "pages.db", "c2.pdf"),
            ("cov_new_2", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover 3",
             "2025-08-14", "2025-08-14T10:00:00", 1, "sha_c3", "pages.db", "c3.pdf"),
            ("cov_parent", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover 4",
             "2025-11-10", "2025-11-10T10:00:00", 1, "sha_c4", "pages.db", "c4.pdf"),
            ("cov_scan", "NAVKAR", "INE278M01019", "announcement", "announcement", "Cover 5",
             "2025-11-12", "2025-11-12T10:00:00", 1, "sha_c5", "pages.db", "c5.pdf"),
        ],
    )
    conn.executemany(
        "INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
        [
            ("held_tx_call", "NAVKAR", 1, "Navkar Corporation Limited\nConference Call May 15, 2025",
             "script_text", 60, "2025-05-20T18:00:00", None),
            ("cov_same_tx", "NAVKAR", 1, "Transcript at https://navkar.com/may.pdf",
             "script_text", 40, "2025-05-19T10:00:00", None),
            ("cov_new_1", "NAVKAR", 1, "Transcript at https://navkar.com/aug1.pdf",
             "script_text", 40, "2025-08-12T10:00:00", None),
            ("cov_new_2", "NAVKAR", 1, "Transcript at https://navkar.com/aug2.pdf",
             "script_text", 40, "2025-08-14T10:00:00", None),
            ("cov_parent", "NAVKAR", 1, "Transcript at https://navkar.com/parent.pdf",
             "script_text", 40, "2025-11-10T10:00:00", None),
            ("cov_scan", "NAVKAR", 1, "Transcript at https://navkar.com/scan.pdf",
             "script_text", 40, "2025-11-12T10:00:00", None),
        ],
    )
    conn.executemany(
        "INSERT INTO filing VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        [
            # Same-call transcript (different bytes from held_tx_call, call date May 15, 2025)
            ("BSE", "f1", "NAVKAR", "INE278M01019", "2025-05-19T10:00:00", "Company Update",
             "Earnings Call Transcript", "Tx 1", "c1.pdf", "transcript", "cov_same_tx", "announcement", 1,
             json.dumps(["https://navkar.com/may.pdf"]), None, None, "link_only"),
            # Same-call deck (anchor date May 18 within 10d of held_dk_call 2025-05-15)
            ("BSE", "f2", "NAVKAR", "INE278M01019", "2025-05-18T10:00:00", "Company Update",
             "Investor Presentation", "Deck", "dk2.pdf", "deck", None, None, None, None, None, None, "not_fetched"),
            # Two different URLs for the same August 10 call -> f3 resolved, f4 dup_in_plan
            ("BSE", "f3", "NAVKAR", "INE278M01019", "2025-08-12T10:00:00", "Company Update",
             "Earnings Call Transcript", "Aug 1", "c2.pdf", "transcript", "cov_new_1", "announcement", 1,
             json.dumps(["https://navkar.com/aug1.pdf"]), None, None, "link_only"),
            ("NSE", "f4", "NAVKAR", "INE278M01019", "2025-08-14T10:00:00", "other",
             "Earnings Call Transcript", "Aug 2", "c3.pdf", "transcript", "cov_new_2", "announcement", 1,
             json.dumps(["https://navkar.com/aug2.pdf"]), None, None, "link_only"),
            # Parent company PDF -> other_company + printed_company
            ("BSE", "f5", "NAVKAR", "INE278M01019", "2025-11-10T10:00:00", "Company Update",
             "Earnings Call Transcript", "Parent", "c4.pdf", "transcript", "cov_parent", "announcement", 1,
             json.dumps(["https://navkar.com/parent.pdf"]), None, None, "link_only"),
            # Empty / scanned PDF (<50 chars on pages 1-2) -> needs_ocr
            ("BSE", "f6", "NAVKAR", "INE278M01019", "2025-11-12T10:00:00", "Company Update",
             "Earnings Call Transcript", "Scan", "c5.pdf", "transcript", "cov_scan", "announcement", 1,
             json.dumps(["https://navkar.com/scan.pdf"]), None, None, "link_only"),
        ],
    )
    conn.commit()
    conn.close()

    may_tx = _make_pdf([
        "Navkar Corporation Limited\nTranscript May 15, 2025\nSite copy",
        "Moderator: Good day.",
        "Page 3",
    ])
    may_dk = _make_pdf([
        "Navkar Corporation Limited\nInvestor Presentation",
        "Slide 2", "Slide 3", "Slide 4", "Slide 5",
    ])
    aug_tx_1 = _make_pdf([
        "Navkar Corporation Limited\nTranscript August 10, 2025\nCopy A",
        "Moderator: Welcome.",
        "Page 3",
    ])
    aug_tx_2 = _make_pdf([
        "Navkar Corporation Limited\nTranscript August 11, 2025\nCopy B",
        "Moderator: Welcome all.",
        "Page 3",
    ])
    parent_tx = _make_pdf([
        "JSW Infrastructure Limited\nQ2 FY26 Earnings Conference Call\nNovember 8, 2025",
        "Moderator: Welcome.",
        "Page 3",
    ])
    scan_tx = _make_pdf(["", "", ""])

    blobs = {
        "https://navkar.com/may.pdf": may_tx,
        "https://www.bseindia.com/xml-data/corpfiling/AttachHis/dk2.pdf": may_dk,
        "https://navkar.com/aug1.pdf": aug_tx_1,
        "https://navkar.com/aug2.pdf": aug_tx_2,
        "https://navkar.com/parent.pdf": parent_tx,
        "https://navkar.com/scan.pdf": scan_tx,
    }
    items = lf.plan_store(db_path, get=lambda u: (u, "application/pdf", blobs[u]))
    by_fid = {it["filing_id"]: it for it in items}

    assert by_fid["f1"]["outcome"] == "held_same_call"
    assert by_fid["f1"]["held_doc_key"] == "held_tx_call"
    assert by_fid["f2"]["outcome"] == "held_same_call"
    assert by_fid["f2"]["held_doc_key"] == "held_dk_call"
    assert by_fid["f3"]["outcome"] == "resolved"
    assert by_fid["f4"]["outcome"] == "dup_in_plan"
    assert by_fid["f5"]["outcome"] == "failed"
    assert by_fid["f5"]["reason"] == "other_company"
    assert by_fid["f5"]["printed_company"] == "JSW Infrastructure Limited"
    assert by_fid["f6"]["outcome"] == "failed"
    assert by_fid["f6"]["reason"] == "needs_ocr"

    report = lf.format_report(items)
    assert "held_same_call" in report
    assert "dup_in_plan" in report
    assert "other_company" in report
    assert "link letters by intent" in report
    assert "JSW Infrastructure Limited" in report


# --------------------------------------------------------------------------- Round 3 fixes
def test_krystal_listing_page_context_and_quarter_and_date_window():
    assert lf.parse_quarter_tag("Q4 & FY 2025") == "Q4FY25"
    assert lf.parse_quarter_tag("Q4 and FY2023-24") == "Q4FY24"

    page_url = "https://krystal-group.com/earnings-call-recording-transcripts/"
    html = (
        "<html><body>"
        "<a href='/wp-content/uploads/2026/05/KISLQ4_FY26_Earnings_Call_Transcript.pdf'>12.05.2026</a>"
        "<a href='/wp-content/uploads/2025/07/Finalletter-2.pdf'>Q4 &amp; FY 2025</a>"
        "<a href='/wp-content/uploads/2025/06/Krystal-Integrated-Services_Q4-FY24-Transcript_final-1.pdf'>"
        "Q4 &amp; FY2023-24</a>"
        "</body></html>"
    ).encode()

    pdf_fy25 = _make_pdf([
        "Krystal Integrated Services Limited\nQ4 FY25 Conference Call Transcript\nMay 12, 2025",
        "Moderator: Welcome.",
        "Page 3",
    ])
    pdf_fy26 = _make_pdf([
        "Krystal Integrated Services Limited\nQ4 FY26 Conference Call Transcript\nMay 12, 2026",
        "Moderator: Welcome.",
        "Page 3",
    ])
    tried: list[str] = []

    def fake_get(url: str) -> tuple[str, str, bytes]:
        if url == page_url:
            return url, "text/html", html
        tried.append(url)
        if url.endswith("Finalletter-2.pdf"):
            return url, "application/pdf", pdf_fy25
        if url.endswith("KISLQ4_FY26_Earnings_Call_Transcript.pdf"):
            return url, "application/pdf", pdf_fy26
        raise AssertionError(f"unexpected URL tried: {url}")

    names = ["KRYSTAL", "Krystal Integrated Services Limited"]
    res_2025 = lf.resolve(page_url, "transcript", "2025-05-15", names, get=fake_get)
    assert res_2025["status"] == "resolved"
    assert tried[0].endswith("Finalletter-2.pdf")
    assert res_2025["url"].endswith("Finalletter-2.pdf")

    tried.clear()
    res_2026 = lf.resolve(page_url, "transcript", "2026-05-20", names, get=fake_get)
    assert res_2026["status"] == "resolved"
    assert tried[0].endswith("KISLQ4_FY26_Earnings_Call_Transcript.pdf")
    assert res_2026["url"].endswith("KISLQ4_FY26_Earnings_Call_Transcript.pdf")

    # Date window: -45 days before anchor up to +10 days after anchor
    assert lf._score_pdf_link("https://x/a.pdf", "01.04.2025", "transcript", "2025-05-15", page_url) == 6
    assert lf._score_pdf_link("https://x/a.pdf", "25.05.2025", "transcript", "2025-05-15", page_url) == 6
    assert lf._score_pdf_link("https://x/a.pdf", "20.03.2025", "transcript", "2025-05-15", page_url) == 3  # 56d before
    assert lf._score_pdf_link("https://x/a.pdf", "30.05.2025", "transcript", "2025-05-15", page_url) == 3  # 15d after


def test_default_get_403_retries_with_browser_headers(monkeypatch):
    import requests

    seen_headers: list[dict[str, str]] = []

    class FakeResp:
        def __init__(self, status_code: int, url: str, body: bytes = b"", ctype: str = "text/html") -> None:
            self.status_code = status_code
            self.url = url
            self.headers = {"Content-Type": ctype, "Content-Length": str(len(body))}
            self._body = body

        def iter_content(self, chunk_size: int = 65536):
            if self._body:
                yield self._body

        def close(self) -> None:
            pass

    class FakeSession:
        def get(self, url, headers=None, timeout=None, allow_redirects=True, stream=True):
            seen_headers.append(dict(headers or {}))
            ua = (headers or {}).get("User-Agent", "")
            if "Chrome/130.0" in ua:
                return FakeResp(200, "https://www.esafbank.com/disclosures/", b"<html>ok</html>")
            return FakeResp(403, url, b"Forbidden")

        def close(self) -> None:
            pass

    monkeypatch.setattr(requests, "Session", FakeSession)
    final_url, ctype, body = lf.default_get(
        "https://www.esafbank.com/investor-relation/?id=disclosure-to-stock-exchanges",
        sleep=lambda _s: None,
    )
    assert len(seen_headers) == 2
    assert seen_headers[0]["User-Agent"] == lf.DEFAULT_HEADERS["User-Agent"]
    assert "Chrome/130.0" in seen_headers[1]["User-Agent"]
    assert seen_headers[1]["Accept"] == "text/html,application/pdf,*/*"
    assert seen_headers[1]["Accept-Language"] == "en-IN,en;q=0.9"
    assert final_url == "https://www.esafbank.com/disclosures/"
    assert ctype == "text/html"
    assert body == b"<html>ok</html>"
