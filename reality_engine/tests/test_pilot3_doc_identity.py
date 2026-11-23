"""T-093: the identity checks on real first-page text and the build's set-aside filter.  Pure functions plus one
synthetic raw-store index: no live store, no network, no PDF."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from reality_engine.pilot3 import doc_identity, schema
from reality_engine.pilot3.doc_identity import Expected, FileIndex, check, resolve_file

KEC_PAGE = ("KEC INTERNATIONAL LTD. RPG House 463, Dr. Annie Besant Road Worli, Mumbai 400030, India +91 22 66670200 "
            "kecindia@kecrpg.com www.kecrpg.com Registered Office: RPG House, 463, Dr. Annie Besant Road Worli, Mumbai "
            "400030, CIN: L45200MH2005PLC152061, India. An RPG Company. Integrated Report 2025-26.")
LETTER = ("June 10, 2026 BSE Limited Corporate Relationship Department 1st Floor, New Trading Ring, Rotunda Bldg., P. J. "
          "Towers, Dalal Street, Fort, Mumbai 400 001. Scrip Code: 500400 National Stock Exchange of India Limited "
          "Exchange Plaza, Bandra Kurla Complex. Sub: Annual Report for the Financial Year 2025-26 and notice of AGM.")
TRANSCRIPT = ("GTPL Hathway Limited Q3 FY '26 Earnings Conference Call January 13, 2026 MANAGEMENT: MR. ANIRUDHSINH "
              "JADEJA - PROMOTER AND MANAGING DIRECTOR MODERATOR: MR. PRANAV KSHATRIYA - EMKAY GLOBAL FINANCIAL "
              "SERVICES LIMITED Transcript of the post results conference call.")
NEWSPAPER = ("August 19, 2026 To, The Manager, Listing Department BSE Limited. Subject: Submission of newspaper "
             "publication titled 20th Annual General Meeting of United Foodbrands Limited. Pursuant to Regulation 47 "
             "of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015, we hereby enclose the "
             "e-clippings of the advertisement published in the newspapers.")
NOTICE = ("August 25, 2026 To, BSE Limited. Subject: Notice of 37th Annual General Meeting (AGM) of Chemcon Speciality "
          "Chemicals Limited. Pursuant to SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015, "
          "please find enclosed the Notice of 37th Annual General Meeting of the Company scheduled to be held on "
          "Thursday, September 17, 2026. NOTICE is hereby given that the Thirty-seventh Annual General Meeting of the "
          "members of Chemcon Speciality Chemicals Limited will be held on Thursday, September 17, 2026 to transact "
          "the following business: ORDINARY BUSINESS: 1. To receive, consider and adopt the Audited Standalone "
          "Financial Statements of the Company for the financial year ended 31st March, 2026.")
OLD_REPORT = ("May 26, 2022 Dear Sir/Madam, Sub: Notice of the 41st Annual General Meeting and Integrated Annual Report "
              "2021-22. Please find enclosed the Notice convening the 41st AGM and the Integrated Annual Report for "
              "the fiscal 2022 which will be circulated to the shareholders. The 41st AGM will be held on Saturday, "
              "June 25, 2022. Integrated Annual Report 2021-22.")


def _expected(name="KEC International Ltd", doc_type="ANNUAL_REPORT", **kwargs):
    return Expected(symbol="S", doc_type=doc_type, names=(name,), **kwargs)


def test_name_in_the_first_pages_is_the_company():
    result = check({1: KEC_PAGE}, _expected("KEC International Ltd"))
    assert (result.verdict, result.company) == ("ok", "ok")


def test_scrip_code_in_a_covering_letter_is_the_company():
    result = check({1: LETTER}, _expected("A Name Not On The Letter", bse_codes=("500400",)))
    assert result.company == "ok" and "500400" in result.company_reason


def test_a_late_name_on_the_auditors_pages_is_not_another_company():
    result = check({1: LETTER}, _expected("KEC International Ltd"),
                   evidence_text="To the Members of KEC International Limited. Independent Auditor's Report")
    assert (result.verdict, result.company) == ("ok", "ok")


def test_own_isin_prefix_later_in_the_file_is_a_former_name():
    result = check({1: "A covering letter that names no company at all. " * 8}, _expected("Old Name Ltd", isin_prefixes=("INE389H",)),
                   whole_pages={1: "A covering letter that names no company at all. " * 8,
                                40: "The Company was formerly known as something else. ISIN: INE389H01022"})
    assert result.company == "ok" and "INE389H" in result.company_reason


def test_a_swapped_pair_is_set_aside():
    result = check({1: KEC_PAGE}, _expected("Tata Power Company Limited", bse_codes=("500400",), isin_prefixes=("INE245A",)))
    assert (result.verdict, result.company) == ("set_aside", "mismatch")


def test_thin_text_is_unknown_never_a_guess():
    result = check({1: "scanned", 2: ""}, _expected("KEC International Ltd"))
    assert (result.verdict, result.company) == ("unknown", "thin")


def test_a_newspaper_notice_labelled_annual_report_is_set_aside():
    result = check({1: NEWSPAPER}, _expected(pages=3, bse_subcat="Newspaper Publication"))
    assert (result.verdict, result.type) == ("set_aside", "mismatch")
    assert "newspaper" in result.type_reason


def test_a_meeting_notice_labelled_annual_report_is_set_aside():
    result = check({1: NOTICE}, _expected(pages=15, bse_subcat="AGM"))
    assert (result.verdict, result.type) == ("set_aside", "mismatch")
    assert "notice" in result.type_reason


def test_a_short_letter_labelled_annual_report_is_set_aside():
    result = check({1: LETTER}, _expected(pages=1))
    assert (result.verdict, result.type) == ("set_aside", "mismatch")


def test_a_small_annual_report_with_a_balance_sheet_heading_is_ok():
    first = {1: "KEC International Limited. Notice of the 34th Annual General Meeting and Annual Report for the "
                "financial year 2025-26. " * 4}
    whole = {**first, 20: "Balance Sheet as at March 31, 2026\n(All amounts in rupees)"}
    result = check(first, _expected("KEC International Ltd", pages=22, bse_subcat="AGM"), whole_pages=whole)
    assert (result.verdict, result.type) == ("ok", "ok")


def test_a_one_page_covering_letter_labelled_transcript_is_set_aside():
    letter = ("Please find enclosed herewith the transcript of the earnings conference call held on August 6, 2026. "
              "The transcript is available at https://www.example.com/transcripts/q1fy27.pdf . "
              "KEC International Limited. Scrip Code: 532714." * 4)
    result = check({1: letter}, _expected("KEC International Ltd", doc_type="CONCALL_TRANSCRIPT", pages=1))
    assert (result.verdict, result.type) == ("set_aside", "mismatch")
    assert result.type_reason.startswith("cover_letter")
    assert result.linked_url == "https://www.example.com/transcripts/q1fy27.pdf"


def test_a_28_page_agm_notice_labelled_annual_report_is_set_aside():
    notice = ("GMR Airports Limited. Notice is hereby given that the 30th Annual General Meeting of the members will "
              "be held on Monday, September 21, 2026 to adopt the Annual Report for 2025-26 and the audited financial "
              "statements. " * 6)
    result = check({1: notice}, _expected("GMR Airports Limited", pages=28, bse_subcat="AGM"))
    assert (result.verdict, result.type) == ("set_aside", "mismatch")


def test_a_transcript_labelled_presentation_is_set_aside():
    result = check({1: TRANSCRIPT}, _expected("GTPL Hathway Limited", doc_type="INVESTOR_PRESENTATION", pages=18,
                                              bse_subcat="Analyst / Investor Meet"))
    assert (result.verdict, result.type) == ("set_aside", "mismatch")


def test_a_transcript_under_the_wrong_bse_category_is_ok():
    result = check({1: TRANSCRIPT}, _expected("GTPL Hathway Limited", doc_type="CONCALL_TRANSCRIPT", pages=13,
                                              bse_subcat="Investor Presentation"))
    assert (result.verdict, result.type) == ("ok", "ok")


def test_a_report_from_another_year_is_set_aside():
    result = check({1: OLD_REPORT}, _expected("Infosys Limited", pages=364,
                                              doc_date="2026-08-28", created_at="2026-08-28 18:56:08"))
    assert result.verdict == "set_aside"
    assert (result.fiscal_year, result.date) == ("mismatch", "crawl_date")
    assert result.filing_date == "2022-05-26"


def test_a_filing_record_dates_the_document_and_beats_the_crawl_date():
    result = check({1: LETTER}, _expected("KEC International Ltd", pages=229, doc_date="2026-08-28",
                                          created_at="2026-08-28 18:56:08", bse_dissem_ts="2026-07-29T20:30:27.23"))
    assert result.date == "filing" and result.filing_date == "2026-07-29"


def test_a_pit_field_backs_doc_date_instead_of_calling_it_a_crawl_date():
    result = check({1: LETTER}, _expected("KEC International Ltd", pages=229, doc_date="2026-07-29",
                                          created_at="2026-08-28 18:56:08", pit_source="bse_ar_api"))
    assert result.date == "filing" and result.filing_date == "2026-07-29"


def test_resolve_file_finds_a_sha_named_file():
    import shutil
    from pathlib import Path
    root = Path(".tmp") / "idtest_sha"          # pytest's tmp_path and mkdtemp dirs are denied by this sandbox
    shutil.rmtree(root, ignore_errors=True)
    try:
        sha = "a" * 64
        pdf = root / "annual_report" / sha[:2] / f"{sha}.pdf"
        pdf.parent.mkdir(parents=True)
        pdf.write_bytes(b"%PDF-1.4")
        index = FileIndex(raw_root=root, disk=doc_identity.sha_index(root))
        path, where, _ = resolve_file({"id": 1, "local_file_path": None, "sha256_hash": sha}, index)
        assert (where, path) == ("disk", pdf)
    finally:
        shutil.rmtree(root, ignore_errors=True)


def test_a_row_only_in_the_archive_is_on_drive_and_one_with_nothing_is_not_held():
    sha = "b" * 64
    rel = "pdfs/S/ANNUAL_REPORT/20260101_deadbeef_x.pdf"
    index = FileIndex(raw_root=Path("."), archive={"remote": "gdrive:X", "folders": {
        "pdfs/S/ANNUAL_REPORT": {"files": {rel: {"sha256": sha}}}}})
    index.reindex_drive()
    row = {"id": 2, "local_file_path": r"C:\repo\reality_engine\data\pdfs\S\ANNUAL_REPORT\20260101_deadbeef_x.pdf",
           "sha256_hash": sha}
    assert resolve_file(row, index)[1] == "drive"
    assert resolve_file({"id": 3, "local_file_path": None, "sha256_hash": "c" * 64}, index)[1] == "missing"
    assert resolve_file({"id": 4, "local_file_path": None, "sha256_hash": None}, index)[1] == "no_hash"


def test_the_build_skips_set_aside_documents():
    from reality_engine.pilot3.registry import _identity_set_aside
    conn = sqlite3.connect(":memory:")
    schema.ensure(conn, ("doc_identity",))
    conn.executemany("INSERT INTO doc_identity (doc_key, verdict) VALUES (?,?)",
                     [("a" * 64, "set_aside"), ("corp:2", "set_aside"), ("d" * 64, "ok")])
    assert _identity_set_aside(conn) == {"a" * 64, "corp:2"}


def test_table_exists():
    conn = sqlite3.connect(":memory:")
    conn.execute(schema.TABLES["doc_identity"])
    columns = {row[1] for row in conn.execute("PRAGMA table_info(doc_identity)")}
    assert {"doc_key", "verdict", "company", "fiscal_year", "type", "date", "filing_date", "file_where",
            "linked_url", "duplicate_of"} <= columns
