"""Tests for the FY25+ concall PDF refetch pilot (no network, no live database)."""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from reality_engine.scripts import concall_refetch as cr


def _scratch_dir() -> Path:
    """A writable directory for one test.

    The DSH Windows sandbox denies writes inside directories Python itself
    creates, so use ``.tmp`` (the harness's own temp area) with flat names.
    """
    root = Path(".tmp")
    root.mkdir(exist_ok=True)
    return root


def _cand(newsid="n1", isin="INE1", symbol="AAA", quarter="FY25Q1", size=1000,
          sha=None, headline="Transcript of Earnings Call", cd_id=1, chunked=False,
          group=None, attachment="a.pdf"):
    return {"newsid": newsid, "scrip_cd": "500001", "attachment": attachment,
            "url": cr.pdf_url(attachment), "headline": headline, "subcat": cr.SUBCAT,
            "known_at": "2024-05-01T10:00:00", "size": size, "symbol": symbol,
            "isin": isin, "group": group or cr.group_of(symbol), "quarter": quarter,
            "cd_id": cd_id, "cd_sha": sha, "cd_title": headline,
            "chunked": chunked, "chunk_doc_id": None}


def _entry(newsid="n1", status="ok", source="bse", doc_class="transcript",
           chars=12000, pages=12, **kw):
    entry = {"newsid": newsid, "symbol": "AAA", "quarter": "FY25Q1", "group": "A-P",
             "status": status, "source": source, "doc_class": doc_class,
             "chars": chars, "pages": pages, "uppercase_ratio": 0.05,
             "image_only_share": 0.0, "same_doc": 0.95, "bytes": 1024,
             "sha256": "a" * 64, "headline": "Q1FY25 transcript", "reused": False,
             "known_at": "2024-05-01T10:00:00", "reason": "",
             "sample_text": "moderator good afternoon", "recorded_sha256": None}
    entry.update(kw)
    return entry


class DateAndCellTests(unittest.TestCase):
    def test_fiscal_quarter(self):
        self.assertEqual(cr.fiscal_quarter("2024-04-01T10:00:00"), "FY25Q1")
        self.assertEqual(cr.fiscal_quarter("2024-06-30"), "FY25Q1")
        self.assertEqual(cr.fiscal_quarter("2024-07-01"), "FY25Q2")
        self.assertEqual(cr.fiscal_quarter("2026-09-30"), "FY27Q2")
        self.assertEqual(cr.fiscal_quarter("2026-10-01"), "FY27Q3")
        self.assertIsNone(cr.fiscal_quarter(""))
        self.assertIsNone(cr.fiscal_quarter("not a date"))

    def test_group_of(self):
        self.assertEqual(cr.group_of("AMBUJA"), "A-P")
        self.assertEqual(cr.group_of("ppl"), "A-P")
        self.assertEqual(cr.group_of("QUESS"), "Q-Z")
        self.assertEqual(cr.group_of("ZOMATO"), "Q-Z")
        self.assertEqual(cr.group_of(""), "Q-Z")

    def test_pdf_url(self):
        self.assertEqual(cr.pdf_url("abc.pdf"),
                         "https://www.bseindia.com/stockinfo/AnnPdfOpen.aspx?Pname=abc.pdf")
        self.assertIsNone(cr.pdf_url(""))


class BuildCandidateTests(unittest.TestCase):
    def test_build_candidates_maps_isin_quarter_and_old_doc(self):
        ann_rows = [
            ("n1", 500001, "a.pdf", "Transcript of call", cr.SUBCAT, "2024-05-03T10:00:00", 1234, "AAA"),
            ("n2", 500002, "b.pdf", "", cr.SUBCAT, "2026-10-02T10:00:00", 2345, ""),
        ]
        identity = {"500001": {"isin": "INE1", "symbol": "AAA"},
                    "500002": {"isin": "INE2", "symbol": "ZZZ"}}
        old = {"n1": {"id": 7, "sha256": "f" * 64, "title": "old"}}
        cands = cr.build_candidates(ann_rows, identity, old, {"f" * 64: 99})
        self.assertEqual(cands[0]["isin"], "INE1")
        self.assertEqual(cands[0]["quarter"], "FY25Q1")
        self.assertEqual(cands[0]["group"], "A-P")
        self.assertEqual(cands[0]["cd_id"], 7)
        self.assertEqual(cands[0]["cd_sha"], "f" * 64)
        self.assertTrue(cands[0]["chunked"])
        self.assertEqual(cands[0]["chunk_doc_id"], 99)
        self.assertEqual(cands[1]["symbol"], "ZZZ")          # filled from the master
        self.assertEqual(cands[1]["quarter"], "FY27Q3")
        self.assertIsNone(cands[1]["cd_id"])
        self.assertFalse(cands[1]["chunked"])
        self.assertIn("AnnPdfOpen.aspx?Pname=b.pdf", cands[1]["url"])


class ClassifyTests(unittest.TestCase):
    def test_real_transcript(self):
        text = ("Moderator: Good afternoon, everyone. Thank you for joining the call.\n"
                "Mr. Sharma: Thank you moderator. Revenue for the quarter was 1,200 crore.\n"
                + "Analyst: Could you comment on the margin outlook for next year?\n" * 200)
        self.assertEqual(cr.classify_document(title="Earnings Call Transcript", subcat=cr.SUBCAT,
                                              pages=12, chars=len(text), text=text),
                         "transcript")

    def test_lower_cased_transcript_is_still_a_transcript(self):
        body = ("moderator: good afternoon everyone. management: revenue grew eight percent.\n"
                "analyst: could you comment on margins?\n" * 120)
        self.assertEqual(cr.classify_document(title="Q2FY25 Earnings call", subcat=None,
                                              pages=9, chars=len(body), text=body), "transcript")

    def test_audio_link_letter(self):
        text = "Dear Sir,\nPlease find the audio recording link for the earnings call.\nThanking you."
        self.assertEqual(cr.classify_document(
            title="Audio recording of the Earnings call held on 31st January 2023",
            subcat="Analyst / Investor Meet", pages=1, chars=len(text), text=text), "audio_link")

    def test_intimation_of_call(self):
        text = ("This is to inform that the earnings conference call is scheduled on 25th October "
                "2026. The dial-in details are enclosed. Please find enclosed the details.")
        self.assertEqual(cr.classify_document(
            title="Intimation of Earnings Conference Call", subcat="Analyst / Investor Meet",
            pages=2, chars=len(text), text=text), "intimation")

    def test_cover_letter(self):
        text = "Dear Sir/Madam,\nWe wish to inform you of the above. Thanking you.\nYours faithfully,"
        self.assertEqual(cr.classify_document(
            title="Covering letter", subcat="General", pages=1, chars=len(text), text=text),
            "cover_letter")

    def test_short_unknown_is_other(self):
        text = "abcdefghij klmno pqrstu vwxyz" * 70
        self.assertEqual(cr.classify_document(title="", subcat=None, pages=5,
                                              chars=len(text), text=text), "other")

    def test_title_only_class(self):
        self.assertEqual(cr.title_only_class("Audio recording of call"), "audio_link")
        self.assertEqual(cr.title_only_class("Prior intimation of board meeting"), "intimation")
        self.assertEqual(cr.title_only_class("Earnings Call Transcript Q2 FY26"), "transcript?")
        self.assertEqual(cr.title_only_class("Enclosed"), "unknown")


class MetricTests(unittest.TestCase):
    def test_casing_ratio(self):
        self.assertAlmostEqual(cr.casing_ratio("ABab"), 0.5)
        self.assertAlmostEqual(cr.casing_ratio("abcd"), 0.0)
        self.assertIsNone(cr.casing_ratio("1234"))

    def test_image_only_share(self):
        self.assertEqual(cr.image_only_share(["", "x" * 10, "y" * 400, "z" * 500]), 0.5)
        self.assertIsNone(cr.image_only_share([]))

    def test_same_document_match(self):
        pdf = ("[Metadata: Symbol: X]\nThe Board of Directors met on Tuesday to approve the "
               "results for the quarter ended September thirty, twenty twenty five and declared "
               "an interim dividend of two rupees per equity share of face value one rupee each.")
        chunks = "[Metadata: Symbol: X | Doc: CONCALL_TRANSCRIPT]\n" + pdf.casefold()
        self.assertGreaterEqual(cr.same_document(pdf, chunks), 0.9)

    def test_same_document_mismatch(self):
        self.assertLess(cr.same_document("alpha beta gamma delta epsilon zeta eta theta iota",
                                         "completely different words entirely nothing in common at all"),
                        0.5)

    def test_is_pdf(self):
        self.assertTrue(cr.is_pdf(b"%PDF-1.7 rest"))
        self.assertFalse(cr.is_pdf(b"<html>"))
        self.assertFalse(cr.is_pdf(None))

    def test_sha_match_status(self):
        self.assertEqual(cr.sha_match_status("abc", "ABC"), "yes")
        self.assertEqual(cr.sha_match_status("abc", "def"), "no")
        self.assertIsNone(cr.sha_match_status(None, "def"))
        self.assertIsNone(cr.sha_match_status("abc", None))

    def test_headers_for(self):
        self.assertEqual(cr.headers_for("https://www.bseindia.com/x.pdf"), cr.BSE_HEADERS)
        self.assertEqual(cr.headers_for("https://www.nseindia.com/x.pdf"), cr.NSE_HEADERS)
        self.assertEqual(cr.headers_for("https://example.com/x.pdf"), cr.DEFAULT_HEADERS)


class SamplingTests(unittest.TestCase):
    def test_allocate_floors_at_one(self):
        self.assertEqual(cr.allocate({"a": 1, "b": 1, "c": 100}, 10), {"a": 1, "b": 1, "c": 8})
        self.assertEqual(cr.allocate({}, 10), {})
        self.assertEqual(sum(cr.allocate({"a": 300, "b": 200, "c": 50}, 200).values()), 200)

    def test_stratified_sample_covers_quarters_and_groups(self):
        rows = []
        for quarter in ("FY25Q1", "FY25Q2", "FY26Q1"):
            for group in ("A-P", "Q-Z"):
                for i in range(20):
                    rows.append(_cand(newsid=f"{quarter}-{group}-{i}", quarter=quarter,
                                      group=group, symbol="AAA" if group == "A-P" else "ZZZ"))
        picks = cr.stratified_sample(rows, 60, seed=1)
        self.assertEqual(len(picks), 60)
        self.assertEqual({p["quarter"] for p in picks},
                         {"FY25Q1", "FY25Q2", "FY26Q1"})
        self.assertEqual({p["group"] for p in picks}, {"A-P", "Q-Z"})

    def test_stratified_sample_is_deterministic(self):
        rows = [_cand(newsid=f"n{i}", quarter=f"FY25Q1{i % 4 + 1}", symbol="AAA")
                for i in range(1, 401)]
        first = [r["newsid"] for r in cr.stratified_sample(rows, 60, seed=3)]
        second = [r["newsid"] for r in cr.stratified_sample(rows, 60, seed=3)]
        self.assertEqual(first, second)

    def test_stratified_sample_handles_small_pool(self):
        rows = [_cand(newsid=f"n{i}") for i in range(1, 6)]
        self.assertEqual(len(cr.stratified_sample(rows, 200, seed=1)), 5)


class ProbeTests(unittest.TestCase):
    def test_probe_index_hashes_and_flags_bad_names(self):
        root = _scratch_dir()
        good = cr.sha256_of(b"%PDF-1.4 one")
        good_path = root / f"{good}.pdf"
        bad_path = root / "deadbeef.pdf"
        good_path.write_bytes(b"%PDF-1.4 one")
        bad_path.write_bytes(b"%PDF-1.4 two")
        try:
            index = cr.probe_index(root)
        finally:
            good_path.unlink(missing_ok=True)
            bad_path.unlink(missing_ok=True)
        self.assertGreaterEqual(index["files"], 2)
        self.assertGreaterEqual(index["bad_name"], 1)
        self.assertIn(good, index["by_sha"])

    def test_probe_analysis_classifies_a_real_pdf_and_reuses_it(self):
        import pymupdf

        root = _scratch_dir()
        doc = pymupdf.open()
        body = ("Moderator: Welcome to the earnings call. "
                "Mr. Sharma: Revenue grew eight percent this quarter. "
                "Analyst: Could you comment on margins and guidance? ") * 30
        for _ in range(6):
            page = doc.new_page()
            page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), body, fontsize=8)
        payload = doc.tobytes()
        doc.close()
        sha = cr.sha256_of(payload)
        path = root / f"{sha}.pdf"
        path.write_bytes(payload)
        try:
            index = cr.probe_index(root)
            cands = [_cand(newsid="n1", sha=sha)]
            result = cr.probe_analysis(index, cands, {})
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(result["candidates_with_probe"], 1)
        self.assertEqual(result["probe_fy_ok"], 1)
        self.assertEqual(result["probe_class_fy25"], {"transcript": 1})
        self.assertEqual(result["probe_unique_transcripts"], 1)
        self.assertEqual(result["probe_transcript_share"], 1.0)


class DedupeTests(unittest.TestCase):
    def test_identical_bytes_are_duplicates(self):
        a = _entry("n1", sha256="b" * 64, chars=9000, isin="I1", quarter="FY25Q1")
        b = _entry("n2", sha256="b" * 64, chars=9000, isin="I1", quarter="FY25Q1")
        marks = cr.dedupe([a, b])
        self.assertEqual(marks["n2"], {"dup_of": "n1", "dup_kind": "sha256"})

    def test_same_call_keeps_the_fullest(self):
        small = _entry("n1", sha256="1" * 64, chars=8000, isin="I1", quarter="FY25Q1")
        big = _entry("n2", sha256="2" * 64, chars=20000, isin="I1", quarter="FY25Q1")
        marks = cr.dedupe([small, big])
        self.assertEqual(marks["n1"], {"dup_of": "n2", "dup_kind": "same_call"})
        self.assertNotIn("n2", marks)

    def test_other_classes_and_quarters_are_not_deduplicated(self):
        a = _entry("n1", sha256="1" * 64, isin="I1", quarter="FY25Q1")
        b = _entry("n2", sha256="2" * 64, doc_class="cover_letter", isin="I1", quarter="FY25Q1")
        c = _entry("n3", sha256="3" * 64, isin="I1", quarter="FY25Q2")
        self.assertEqual(cr.dedupe([a, b, c]), {})


class AnalysisTests(unittest.TestCase):
    def test_duplicate_proxy_uses_size_and_validates_with_sha(self):
        cands = [
            _cand("n1", isin="I1", size=1000, sha="a" * 64),
            _cand("n2", isin="I1", size=1000, sha="a" * 64),
            _cand("n3", isin="I1", size=2000, sha="b" * 64),
            _cand("n4", isin="I2", size=1000, sha="c" * 64),
        ]
        dup = cr.duplicate_analysis(cands)
        self.assertEqual(dup["size_dup_rows"], 1)
        self.assertEqual(dup["size_groups"], 1)
        self.assertEqual(dup["size_precision_checked"], 1)
        self.assertEqual(dup["size_precision_same"], 1)
        self.assertEqual(dup["sha_dup_rows"], 1)
        self.assertEqual(dup["wide_size_groups"], 1)   # I1/1000 same quarter
        self.assertEqual(dup["call_dup_rows"], 2)      # n1,n2,n3 share I1/FY25Q1

    def test_coverage_both_directions(self):
        cands = [_cand("n1", cd_id=1), _cand("n2", cd_id=None)]
        old_rows = [
            {"id": 1, "newsid": "n1", "sha256": "a", "title": "t", "isin": "INE1",
             "known_dt": "2024-05-01"},
            {"id": 2, "newsid": "n9", "sha256": "b", "title": "x", "isin": "INE2",
             "known_dt": "2025-02-01"},
            {"id": 3, "newsid": None, "sha256": "c", "title": "nse", "isin": "INE1",
             "known_dt": "2024-05-01"},
            {"id": 4, "newsid": "n8", "sha256": "d", "title": "old", "isin": "INE3",
             "known_dt": "2023-01-01"},
        ]
        meta = {"n9": {"subcat": "Analyst / Investor Meet"}}
        cov = cr.coverage_analysis(cands, old_rows, lambda ids: meta)
        self.assertEqual(cov["old_fy_rows"], 3)
        self.assertEqual(cov["covered_by_ann"], 1)
        self.assertEqual(cov["missing_from_old"], 1)
        self.assertEqual(cov["old_not_covered"], 1)
        self.assertEqual(cov["nse_only"], 1)
        self.assertEqual(cov["old_not_covered_subcats"], {"Analyst / Investor Meet": 1})
        self.assertEqual(cov["cross_source_dupes"], 1)   # the NSE row is the same call

    def test_project_counts_only_unique_transcripts(self):
        analysis = {"total": 1000,
                    "probe": {"candidates_with_probe": 100, "probe_unique_transcripts": 50}}
        pilot = {"transcript_share": 0.8, "duplicate_share": 0.1, "ok": 190, "sampled": 200}
        got = cr.project(analysis, pilot, interval=2.4)
        self.assertEqual(got["fetch_needed"], 900)
        self.assertEqual(got["est_transcripts"], 800)
        self.assertEqual(got["est_unique_transcripts"], 720)
        self.assertEqual(got["rate_per_min"], 25.0)
        self.assertAlmostEqual(got["fetch_minutes"], (900 / 0.95) * 2.4 / 60, places=4)


class _FakeResponse:
    def __init__(self, status, content=b"", headers=None):
        self.status_code = status
        self.content = content
        self.headers = headers or {}


class _FakeSession:
    def __init__(self, responses):
        self.responses = list(responses)
        self.closed = False

    def get(self, *a, **kw):
        return self.responses.pop(0)

    def close(self):
        self.closed = True


class FetchUrlTests(unittest.TestCase):
    def setUp(self):
        self.slept: list[float] = []
        self.pacer = cr.Pacer(interval=2.0, clock=lambda: 0.0, sleep=self.slept.append)

    def test_ok_pdf(self):
        got = cr.fetch_url("https://www.bseindia.com/x.pdf",
                           pacer=self.pacer,
                           session=_FakeSession([_FakeResponse(200, b"%PDF-1.4 body")]))
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["bytes"], 13)
        self.assertEqual(got["http_status"], 200)

    def test_not_a_pdf(self):
        got = cr.fetch_url("https://www.bseindia.com/x.pdf", pacer=self.pacer,
                           session=_FakeSession([_FakeResponse(200, b"<html>login")]))
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["reason"], "not a PDF")

    def test_404_does_not_retry(self):
        session = _FakeSession([_FakeResponse(404)])
        got = cr.fetch_url("https://www.bseindia.com/x.pdf", pacer=self.pacer, session=session)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["attempts"], 1)
        self.assertEqual(session.responses, [])

    def test_429_backs_off_then_succeeds(self):
        session = _FakeSession([_FakeResponse(429), _FakeResponse(200, b"%PDF-1.7 ok")])
        got = cr.fetch_url("https://www.bseindia.com/x.pdf", pacer=self.pacer, session=session,
                           backoff=1.0, sleep=self.slept.append)
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["attempts"], 2)
        self.assertIn(1.0, self.slept)

    def test_gives_up_after_attempts(self):
        session = _FakeSession([_FakeResponse(503)] * 3)
        got = cr.fetch_url("https://www.bseindia.com/x.pdf", pacer=self.pacer, session=session,
                           attempts=3, backoff=0.0, sleep=self.slept.append)
        self.assertEqual(got["status"], "failed")
        self.assertEqual(got["http_status"], 503)
        self.assertEqual(got["attempts"], 3)


class PacerTests(unittest.TestCase):
    def test_spaces_requests(self):
        slept: list[float] = []
        clock_values = iter([0.0, 0.5, 2.1])
        pacer = cr.Pacer(interval=2.0, clock=lambda: next(clock_values), sleep=slept.append)
        pacer.wait()
        pacer.wait()
        self.assertEqual(len(slept), 1)
        self.assertAlmostEqual(slept[0], 1.5)
        self.assertEqual(pacer.requests, 2)

    def test_floor_is_25_per_minute(self):
        pacer = cr.Pacer(interval=0.1)
        self.assertGreaterEqual(pacer.interval, 0.1)   # caller enforces MIN_INTERVAL
        self.assertGreaterEqual(cr.MIN_INTERVAL, 2.4)


class ReportTests(unittest.TestCase):
    def _analysis(self):
        return {
            "total": 100, "by_quarter": {"FY25Q1": 60, "FY25Q2": 40},
            "by_cell": {("FY25Q1", "A-P"): 30, ("FY25Q1", "Q-Z"): 30,
                        ("FY25Q2", "A-P"): 20, ("FY25Q2", "Q-Z"): 20},
            "sizes": {"n": 100, "min": 1000, "median": 2000, "p90": 3000, "max": 4000},
            "coverage": {"old_rows_total": 200, "old_fy_rows": 150, "covered_by_ann": 99,
                         "missing_from_old": 1, "old_not_covered": 51, "nse_only": 40,
                         "old_not_covered_subcats": {}, "missing_from_old_examples": ["n2"],
                         "old_not_covered_examples": ["1 | n9"],
                         "cross_source_dupes": 3, "cross_source_examples": []},
            "duplicates": {"sha_groups": 1, "sha_dup_rows": 1, "sha_dup_share": 0.01,
                           "size_groups": 2, "size_dup_rows": 2, "size_dup_share": 0.02,
                           "size_precision_checked": 2, "size_precision_same": 2,
                           "size_precision": 1.0, "wide_size_groups": 2,
                           "wide_size_dup_rows": 2, "headline_size_groups": 3,
                           "headline_size_rows": 3, "headline_dups": 5,
                           "headline_distinct": 80, "call_groups": 1,
                           "call_dup_rows": 1, "call_dup_share": 0.01},
            "headlines": {"classes": {"transcript?": 90, "unknown": 10},
                          "distinct_headlines": 80,
                          "top_headlines": [["Transcript", 20]], "empty_headlines": 0},
            "probe": {"files": 10, "bad_name": 0, "candidates_with_probe": 5,
                      "distinct_probe_sha_matched": 5, "probe_class_fy25": {"transcript": 4},
                      "probe_ok": 5, "probe_fy_ok": 5, "probe_transcripts": 4,
                      "probe_unique_transcripts": 3, "probe_transcript_share": 0.8,
                      "probe_dup_share": 0.25, "probe_class_all": {}},
        }

    def test_summary_and_markdown(self):
        entries = [_entry("n1"), _entry("n2", status="failed", source="bse", doc_class=None,
                                        reason="http 404"),
                   _entry("n3", doc_class="cover_letter", chars=900, pages=1)]
        pilot = cr.summarize(entries, elapsed=120.0, pacer_requests=7, interval=2.5)
        analysis = self._analysis()
        projection = cr.project(analysis, pilot, 2.5)
        text = cr.format_report(analysis, pilot, projection)
        self.assertEqual(pilot["ok"], 2)
        self.assertEqual(pilot["failed"], 1)
        self.assertEqual(pilot["classes"]["transcript"], 1)
        self.assertEqual(pilot["by_source"]["bse"]["failed"], 1)
        self.assertIn("http 404", pilot["by_source"]["bse"])
        for section in ("## 1. Candidate set", "## 5. Duplicates",
                        "## 6. Pilot (200 docs)", "## 7. Projection", "## 8. Samples"):
            self.assertIn(section, text)
        self.assertIn("FY25Q1", text)

    def test_manifest_roundtrip(self):
        root = _scratch_dir()
        path = cr.write_manifest(root, [_entry("n1"), _entry("n2")],
                                 name="_test_manifest.jsonl")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["newsid"], "n1")


class RunTests(unittest.TestCase):
    def test_dry_run_summary_counts_skips_separately(self):
        entries = [_entry(f"n{i}", status="skipped", source=None, doc_class=None)
                   for i in range(1, 6)]
        pilot = cr.summarize(entries, elapsed=1.0, pacer_requests=0, interval=2.5,
                             dry_run=True)
        self.assertEqual(pilot["ok"], 0)
        self.assertEqual(pilot["failed"], 0)
        self.assertEqual(pilot["skipped"], 5)
        self.assertEqual(pilot["transcripts"], 0)


class WidenFilterTests(unittest.TestCase):
    def test_transcript_headlines_are_kept(self):
        for headline in (
                "Earnings Call Transcript",
                "Earning Call Transcript",
                "Transcript of Earnings Call held on 15th October 2026",
                "Transcript is attached",
                "Submission of transcripts of Earning Conference Call",
                "Q2 and H1 FY25 Earning concall transcript",
                "Transcript of the Post Results Conference Call",
                "Investor Meet Transcript",
                "Transcript of Analysts/Investors Call",
                "Disclosure under Regulation 30 and Regulation 46(2)(oa) of SEBI LODR",
                "Audio / video recording and transcript of the presentation to analysts",
                "Transcript of Post Earnings Concall / Meet",
                "Investor Call"):
            self.assertTrue(cr.is_widened_transcript(headline), headline)

    def test_schedule_and_link_notices_are_dropped(self):
        for headline in (
                "Schedule of Analyst/Investor Meet",
                "Intimation of Schedule of Investor Meeting",
                "Intimation of Earnings Conference Call",
                "Audio Recording of Conference Call held on 22nd October 2026",
                "Link of Recording",
                "Investor Presentation -Nov 2024",
                "Press Release",
                "Clarification on Price Movement",
                "Announcement attached",
                ""):
            self.assertFalse(cr.is_widened_transcript(headline), headline)

    def test_attachment_name_can_signal_a_transcript(self):
        # BSE attachment names are UUIDs today; a real filename still counts.
        self.assertTrue(cr.is_widened_transcript(
            "Announcement attached", "Q2FY26_concall_transcript.pdf"))
        self.assertFalse(cr.is_widened_transcript("Announcement attached", "abc.pdf"))

    def test_widen_rows_keeps_only_signal_rows(self):
        rows = [
            ("n1", 1, "a.pdf", "Transcript of Earnings Call", "General",
             "2024-05-01", 10, "AAA"),
            ("n2", 1, "b.pdf", "Investor Presentation", "Investor Presentation",
             "2024-05-01", 10, "AAA"),
            ("n3", 1, "c.pdf", "Audio recording of the call", "General",
             "2024-05-01", 10, "AAA"),
        ]
        kept = cr.widen_rows(rows)
        self.assertEqual([row[0] for row in kept], ["n1"])


class WidenOverlapTests(unittest.TestCase):
    def test_dedupe_by_isin_quarter_and_attachment(self):
        widened = [
            _cand("w1", isin="I1", quarter="FY25Q1", attachment="a.pdf"),
            _cand("w2", isin="I2", quarter="FY25Q2", attachment="b.pdf"),
            _cand("w3", isin="I3", quarter="FY25Q3", attachment="c.pdf"),
        ]
        earnings = [
            _cand("e1", isin="I1", quarter="FY25Q1", attachment="x.pdf"),
            _cand("e2", isin="I9", quarter="FY26Q1", attachment="b.pdf"),
        ]
        got = cr.overlap_analysis(widened, earnings)
        self.assertEqual(got["by_call"], 1)
        self.assertEqual(got["by_attachment"], 1)
        self.assertEqual(got["either"], 2)
        self.assertEqual(got["fresh"], 1)
        self.assertEqual(got["covered_newsids"], {"w1", "w2"})
        self.assertEqual(got["earnings_without_isin"], 0)

    def test_internal_duplicates_are_counted(self):
        widened = [
            _cand("w1", isin="I1", quarter="FY25Q1", attachment="a.pdf"),
            _cand("w2", isin="I1", quarter="FY25Q1", attachment="b.pdf"),
        ]
        got = cr.overlap_analysis(widened, [])
        self.assertEqual(got["internal_call_dupes"], 1)
        self.assertEqual(got["fresh"], 2)


class WidenRecallTests(unittest.TestCase):
    def _meta(self):
        return {
            "n1": {"subcat": "General", "headline": "Transcript of Earnings Call"},
            "n2": {"subcat": "Analyst / Investor Meet", "headline": "Transcript is attached"},
            "m1": {"subcat": "General", "headline": "Schedule of Analyst Meet"},
            "m2": {"subcat": "General", "headline": "Audio recording of the call"},
            "m3": {"subcat": "AGM", "headline": "Transcript of the 38th AGM"},
        }

    def _old_rows(self):
        return [
            {"id": 1, "newsid": "n1", "title": "t", "isin": "I1",
             "known_dt": "2024-05-01"},
            {"id": 2, "newsid": "n2", "title": "t", "isin": "I2",
             "known_dt": "2024-06-01"},
            {"id": 3, "newsid": "m1", "title": "x", "isin": "I3",
             "known_dt": "2025-02-01"},
            {"id": 4, "newsid": "m2", "title": "y", "isin": "I4",
             "known_dt": "2025-02-01"},
            {"id": 5, "newsid": "m3", "title": "z", "isin": "I5",
             "known_dt": "2025-02-01"},
            {"id": 6, "newsid": "e1", "title": "ec", "isin": "I6",
             "known_dt": "2025-02-01"},
            {"id": 7, "newsid": "old", "title": "pre-window", "isin": "I7",
             "known_dt": "2023-01-01"},
        ]

    def test_recall_buckets_and_ordering(self):
        widened = [_cand("n1"), _cand("n2")]
        meta = self._meta()
        got = cr.recall_analysis(widened, self._old_rows(), {"e1"},
                                 lambda ids: {k: meta[k] for k in ids if k in meta})
        self.assertEqual(got["others"], 5)          # n1, n2, m1, m2, m3
        self.assertEqual(got["in_scope"], 4)        # m3 is an AGM row
        self.assertEqual(got["caught"], 2)
        self.assertEqual(got["missed"], 3)
        self.assertAlmostEqual(got["recall"], 2 / 5)
        self.assertAlmostEqual(got["recall_in_scope"], 2 / 4)
        self.assertEqual(got["miss_buckets"], {
            "schedule / intimation only": 1, "audio/video or recording link": 1,
            "other subcategory": 1})
        # in-scope misses are listed first
        self.assertEqual([line.split(" | ")[0] for line in got["miss_lines"]],
                         ["m1", "m2", "m3"])

    def test_rows_missing_from_the_feed_are_their_own_bucket(self):
        widened = []
        rows = [{"id": 1, "newsid": "gone", "title": "not in ann", "isin": "I1",
                 "known_dt": "2025-02-01"}]
        got = cr.recall_analysis(widened, rows, set(), lambda ids: {})
        self.assertEqual(got["miss_buckets"], {"not in the BSE announcement feed": 1})


class WidenPrecisionTests(unittest.TestCase):
    def test_precision_counts_real_transcripts(self):
        import pymupdf

        root = _scratch_dir()
        doc = pymupdf.open()
        body = ("Moderator: Welcome to the earnings call. "
                "Mr. Sharma: Revenue grew eight percent this quarter. "
                "Analyst: Could you comment on margins and guidance? ") * 30
        for _ in range(6):
            page = doc.new_page()
            page.insert_textbox(pymupdf.Rect(40, 40, 560, 800), body, fontsize=8)
        payload = doc.tobytes()
        doc.close()
        path = root / "one.pdf"
        path.write_bytes(payload)
        cands = [_cand("w1", headline="Transcript of Earnings Call")]
        try:
            with mock.patch.object(
                    cr, "staged_path",
                    lambda cand, dirs: path if cand["newsid"] == "w1" else None):
                got = cr.precision_sample(cands, [root], n=1)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(got["available"], 1)
        self.assertEqual(got["sampled"], 1)
        self.assertEqual(got["ok"], 1)
        self.assertEqual(got["transcripts"], 1)
        self.assertEqual(got["precision"], 1.0)
        self.assertFalse(got["headline_only"])

    def test_fewer_pdfs_than_requested_falls_back_to_headlines(self):
        with mock.patch.object(cr, "staged_path", lambda cand, dirs: None):
            got = cr.precision_sample([_cand("w1")], [Path(".")], n=40)
        self.assertTrue(got["headline_only"])
        self.assertEqual(got["available"], 0)
        self.assertIsNone(got["precision"])
        self.assertEqual(got["classes"], {"transcript?": 1})


class WidenReportTests(unittest.TestCase):
    def _widen(self):
        return {
            "window_start": "2024-04-01",
            "subcats": list(cr.WIDEN_SUBCATS),
            "raw_rows": 204685, "total": 100, "attachment_only": 0,
            "by_subcat": {"Analyst / Investor Meet": 70, "General": 30},
            "by_quarter": {"FY25Q1": 60, "FY25Q2": 40},
            "by_cell": {("Analyst / Investor Meet", "FY25Q1"): 40,
                        ("General", "FY25Q2"): 40},
            "overlap": {"widened": 100, "earnings": 9390, "by_call": 25,
                        "by_attachment": 0, "either": 25, "fresh": 75,
                        "internal_call_dupes": 2, "earnings_without_isin": 0,
                        "covered_newsids": set(), "examples": ["w1 | AAA | FY25Q1 | t"]},
            "recall": {"others": 1771, "in_scope": 1686, "caught": 1589,
                       "missed": 182, "recall": 0.897, "recall_in_scope": 0.942,
                       "miss_buckets": {"no transcript signal in the headline": 63},
                       "miss_lines": ["m1 | General | Attached"]},
            "precision": {"available": 101, "sampled": 40, "ok": 40,
                          "headline_only": False, "classes": {"transcript": 34},
                          "transcripts": 34, "precision": 0.85,
                          "precision_ok": 0.85, "records": []},
            "dirs": ["probe", "store"],
        }

    def test_report_has_every_acceptance_section(self):
        widen = self._widen()
        projection = cr.project_widen(widen, interval=2.5)
        text = cr.format_widen_report(widen, projection)
        for section in ("## 1. Widened candidates by subcategory",
                        "## 2. Overlap with the 9,390",
                        "## 3. Recall against the pilot's 1,771",
                        "## 4. Classifier precision",
                        "## 5. Fetch time"):
            self.assertIn(section, text)
        self.assertIn("**75**", text)               # fresh rows
        self.assertIn("--widen --fetch", text)
        self.assertIn("85.0%", text)

    def test_projection_uses_the_pacing_floor(self):
        got = cr.project_widen(self._widen(), interval=2.5)
        self.assertEqual(got["fresh"], 75)
        self.assertEqual(got["rate_per_min"], 24.0)
        self.assertAlmostEqual(got["fetch_minutes"], 75 * 2.5 / 60.0)
        self.assertEqual(got["est_transcripts"], round(75 * 0.85))


if __name__ == "__main__":
    unittest.main()
