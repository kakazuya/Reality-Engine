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
    assert lf.resolve("https://x/parent.pdf", "transcript", "2026-07-22", names, get=fake_get)["reason"] == "wrong_company"
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
        "Navkar Corporation Limited\nAlready Held Transcript\nMay 10, 2025",
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
             "2025-05-12", "2025-05-12T10:00:00", 1, "sha_c3", "pages.db", "c3.pdf"),
            ("d_existing_tx", "NAVKAR", "INE278M01019", "transcript", "transcript", "Held tx",
             "2025-05-10", "2025-05-10T10:00:00", 3, held_sha, "pages.db", "held_tx.pdf"),
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
             "script_text", 50, "2025-05-12T10:00:00", None),
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
            ("BSE", "b2", "NAVKAR", "INE278M01019", "2025-05-12T10:00:00", "Company Update",
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
    assert "| NAVKAR |" in capsys.readouterr().out
    assert json.loads(out_json.read_text(encoding="utf-8")) == []
