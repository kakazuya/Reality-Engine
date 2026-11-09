"""T-157: linked transcript stubs and missing calls on a tiny fixture (no network, no real stores)."""
from __future__ import annotations

import sqlite3
import shutil
import uuid
from pathlib import Path

import pytest

pymupdf = pytest.importorskip("pymupdf")

from reality_engine.pilot3 import linked_transcripts as lt  # noqa: E402
from reality_engine.pilot3 import schema  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

ADANI_URL = ("https://www.adaniports.com/-/media/Project/Ports/Investor/Transcripts/"
             "Q2-FY25-Earnings-Call.pdf")
IHCL_ANNOTATION = ("https://ir.ihcltata.com/media/n20jfczf/"
                   "ihcl-global-earnings-call-transcript_q2fy26.pdf")
STUB_KNOWN_AT = "2024-11-04T18:45:59"


def test_urls_from_text_joins_each_split_fragment():
    adani = ("In continuation to our intimation, please find below web link of the transcript.\n\n"
             "https://www.adaniports.com/-/media/Project/Ports/Investor/Transcripts/Q2-FY25-\n"
             "Earnings-Call.pdf \n \nKindly take the above on your records.")
    assert lt.urls_from_text(adani) == [ADANI_URL]
    ihcl = ("The transcript is available at\n"
            "https://www.primeinfobase.in/z_INDHOTEL/files/IHCL_Transcript_Earnings_call__Q1_FY\n"
            "_22-23.pdf \n \nYou are requested to take the same on record.")
    assert lt.urls_from_text(ihcl) == [
        "https://www.primeinfobase.in/z_INDHOTEL/files/IHCL_Transcript_Earnings_call__Q1_FY_22-23.pdf"]


def test_urls_from_links_keeps_only_web_pdf_uris():
    links = [{"kind": 2, "uri": IHCL_ANNOTATION},
             {"kind": 2, "uri": "mailto:company.secretary@example.com"},
             {"kind": 2, "uri": "https://example.test/register?confirmationNumber=1"}]
    assert lt.urls_from_links(links) == [IHCL_ANNOTATION]


def _annotated_cover(path: Path, uri: str, text_url: str) -> None:
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_textbox(pymupdf.Rect(40, 40, 550, 200),
                        f"Sub: Transcript of Earnings Call\n{text_url}", fontsize=11)
    page.insert_link({"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(40, 220, 400, 260), "uri": uri})
    doc.save(str(path))
    doc.close()


def _pdf_bytes(pages: list[str]) -> bytes:
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(40, 40, 550, 800), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def _store(path: Path, cover: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    schema.create(conn, ("company", "doc", "doc_page"))
    conn.execute(schema.FTS)
    conn.execute("INSERT INTO company VALUES ('TST','INE000A01001',NULL,NULL,'test','999001','Test Ltd')")
    docs = [
        # a one-page cover letter whose annotation names the real transcript
        ("stub/cover.pdf", "transcript", "Transcript intimation", "2024-11-04", STUB_KNOWN_AT, 1, "stubsha"),
        # a real transcript already held for the May call
        ("held/may.pdf", "transcript", "Transcript of the Earnings Call", "2024-05-20",
         "2024-05-20T18:00:00", 12, "maysha"),
        # another for the Sep/Oct cluster, filed 43 days after the call intimation
        ("held/oct.pdf", "transcript", "Transcript of the Earnings Call", "2024-11-15",
         "2024-11-15T18:00:00", 14, "octsha"),
        ("res/may.pdf", "results", "Q4 results", "2024-05-02", "2024-05-02T18:00:00", 5, "r1"),
        ("res/sep.pdf", "results", "Intimation of Q2 earnings call", "2024-09-30",
         "2024-09-30T12:00:00", 1, "r2"),
        ("res/oct.pdf", "results", "Q2 results", "2024-10-28", "2024-10-28T18:00:00", 5, "r3"),
        ("res/jan.pdf", "results", "Q3 results", "2025-01-15", "2025-01-15T18:00:00", 5, "r4"),
        # a call whose transcript the store does not hold: the one missing call
        ("res/apr.pdf", "results", "Q4 results", "2025-04-15", "2025-04-15T18:00:00", 5, "r5"),
        ("held/apr.pdf", "transcript", "Transcript of the Earnings Call", "2025-04-20",
         "2025-04-20T18:00:00", 11, "aprsha"),
    ]
    conn.executemany(
        "INSERT INTO doc (doc_key, symbol, isin, doc_type, doc_family, title, filing_date, known_at, pages, "
        "sha256, source, source_key) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        [(key, "TST", "INE000A01001", kind, kind, title, filing, known, pages, sha, "test", None)
         for key, kind, title, filing, known, pages, sha in docs])
    conn.execute("UPDATE doc SET source_key=? WHERE doc_key='stub/cover.pdf'", (str(cover),))
    conn.executemany(
        "INSERT INTO doc_page (doc_key, symbol, page, text, method, chars, known_at) VALUES (?,?,?,?,?,?,?)",
        [("stub/cover.pdf", "TST", 1, f"Sub: transcript\n{ADANI_URL}", "script_text", 10, STUB_KNOWN_AT)] +
        [(f"held/may.pdf", "TST", page, "ordinary page", "script_text", 12, None) for page in (1,)])
    conn.commit()
    return conn


@pytest.fixture()
def world():
    """Scratch under the repo's ``.tmp`` (a plain mkdir; pytest's tmp_path is ACL-denied in this sandbox)."""
    base = ROOT / ".tmp" / f"t157_{uuid.uuid4().hex[:10]}"
    base.mkdir(parents=True)
    cover = base / "cover.pdf"
    _annotated_cover(cover, IHCL_ANNOTATION, "https://example.test/wrong-text-link.pdf")
    conn = _store(base / "pilot.db", cover)
    yield conn, base
    conn.close()
    shutil.rmtree(base, ignore_errors=True)


def test_stub_urls_prefer_the_annotation(world):
    conn, _ = world
    urls = lt.stub_urls(conn, "stub/cover.pdf", conn.execute(
        "SELECT source_key FROM doc WHERE doc_key='stub/cover.pdf'").fetchone()[0])
    assert urls[0] == IHCL_ANNOTATION and urls[1] == ADANI_URL   # the page text comes second
    assert urls[0] == IHCL_ANNOTATION           # text URL never wins over the annotation


def test_missing_call_rule_uses_the_cluster_and_21_days(world):
    conn, _ = world
    missing = lt.missing_calls(conn)
    assert [item["filing_date"] for item in missing] == ["2025-01-15"]
    assert missing[0]["until"] == "2025-02-05"


def test_build_plan_resolves_stub_and_missing_call(world, monkeypatch):
    conn, base = world
    transcript = _pdf_bytes(["Call transcript page one. anchorage."] * 4)
    found = _pdf_bytes(["BSE transcript page one. quayside."] * 5)

    def fetch(url):
        return found if "bse" in url else transcript

    monkeypatch.setattr(lt, "bse_transcript", lambda *a, **k: {
        "url": "https://www.bseindia.com/bse-transcript.pdf", "title": "Transcript Of Earnings Call",
        "known_at": "2025-01-20T10:00:00", "newsid": "n1"})
    plan = lt.build_plan(conn, fetch=fetch)
    stubs = [item for item in plan["stubs"] if item["stub"] == "stub/cover.pdf"]
    assert stubs and stubs[0]["status"] == "planned" and stubs[0]["pages"] == 4
    assert stubs[0]["known_at"] == STUB_KNOWN_AT                 # the stub's time, never earlier
    assert "linked from stub/cover.pdf" in stubs[0]["title"]
    calls = [item for item in plan["calls"] if item["status"] == "planned"]
    assert len(calls) == 1 and calls[0]["anchor"] == "2025-01-15"
    assert calls[0]["known_at"] == "2025-01-20T10:00:00"          # BSE dissemination time
    assert calls[0]["title"] == "Transcript Of Earnings Call"

    counts = lt.apply_plan(conn, plan, base / "raw")
    assert counts == {"added": 2, "pages": 9, "skipped": 0}
    linked = conn.execute("SELECT filing_date, known_at, pages FROM doc WHERE doc_key LIKE 'linked%' "
                          "AND symbol='TST' ORDER BY filing_date").fetchall()
    assert linked[0] == ("2024-11-04", STUB_KNOWN_AT, 4)          # known_at is the stub's, not the run's
    assert conn.execute("SELECT COUNT(*) FROM doc_page WHERE doc_key LIKE 'linked%'").fetchone()[0] == 9
    for word in ("anchorage", "quayside"):
        assert conn.execute("SELECT COUNT(*) FROM doc_page_fts WHERE doc_page_fts MATCH ?",
                            (word,)).fetchone()[0] >= 1

    again = lt.build_plan(conn, fetch=fetch)
    assert lt.apply_plan(conn, again, base / "raw") == {"added": 0, "pages": 0, "skipped": 0}
    assert conn.execute("SELECT COUNT(*) FROM doc WHERE symbol='TST' AND doc_type='transcript' "
                        "AND pages>=3").fetchone()[0] == 5       # 3 held + 2 added, no duplicate
