"""Tests for the FY25+ concall PDF refetch pilot (no network, no live database)."""
from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
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


def _workdir(name: str) -> Path:
    """A private scratch directory for one run (it writes PDFs and a journal)."""
    path = _scratch_dir() / f"cr_{name}"
    path.mkdir(parents=True, exist_ok=True)
    return path


class _StubCon:
    """Read-only stand-in for the two databases: no query, no live file."""

    def execute(self, *args, **kwargs):
        return []

    def close(self):
        pass


@contextlib.contextmanager
def _offline_db():
    """``run_pilot`` with no database behind it (no REALITY_DATA_ROOT file)."""
    with mock.patch.dict(os.environ, {"REALITY_DATA_ROOT": str(_scratch_dir())}):
        with mock.patch.object(cr, "connect_ro", lambda *a, **kw: _StubCon()):
            yield


def _fake_fetch(responses, calls=None, on_call=None):
    """A ``fetch_url`` stand-in: newsid-less URLs looked up in ``responses``."""
    calls = calls if calls is not None else []

    def fetch(url, *, pacer=None, session=None, backoff=30.0, cooldown=None):
        calls.append(url)
        if on_call is not None:
            on_call(url)
        got = responses(url)
        record = {"status": got[0], "http_status": got[1], "content_type": "application/pdf",
                  "reason": got[2], "attempts": 1, "content": got[3]}
        return record

    return fetch


def _ok_bytes(url: str) -> bytes:
    """Distinct fake PDF bytes per URL, so the shas never collide."""
    return b"%PDF-1.4 " + url.encode()


def _stub_inspect(entry, path, cand, con_eq, log=print):
    entry.update(status="ok", doc_class="transcript", chars=12000, pages=9,
                 uppercase_ratio=0.05, image_only_share=0.0)


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

    def test_floor_allows_the_probed_rate(self):
        # 2026-10-28 probes: no block at ~400/min on NSE, ~200/min on BSE.
        self.assertLessEqual(cr.MIN_INTERVAL, 0.25)
        self.assertGreaterEqual(60 / cr.MIN_INTERVAL, 400 - 1e-9)
        self.assertGreaterEqual(cr.Pacer(0.1).interval, 0.1)


class PacerParallelTests(unittest.TestCase):
    """One pacer, many workers: the *total* rate stays at 60/interval per minute."""

    def test_shared_pacer_caps_the_total_rate(self):
        interval = 0.01
        pacer = cr.Pacer(interval=interval)
        stamps: list[float] = []
        lock = threading.Lock()

        def worker():
            for _ in range(5):
                pacer.wait()
                with lock:
                    stamps.append(time.monotonic())

        threads = [threading.Thread(target=worker) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        stamps.sort()
        self.assertEqual(pacer.requests, 20)
        # 20 slots, each `interval` after the previous one: >= 19 intervals.
        self.assertGreaterEqual(stamps[-1] - stamps[0], 19 * interval * 0.95)

    def test_block_pauses_every_thread(self):
        cooldown = cr.Cooldown()
        started = time.monotonic()
        resumed: list[float] = []
        lock = threading.Lock()

        def waiter():
            cooldown.wait()
            with lock:
                resumed.append(time.monotonic() - started)

        cooldown.pause(0.25)
        threads = [threading.Thread(target=waiter) for _ in range(3)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(len(resumed), 3)
        self.assertEqual(cooldown.hits, 1)
        self.assertTrue(all(at >= 0.2 for at in resumed), resumed)

    def test_pause_never_shortens_and_wait_reports_the_sleep(self):
        now = {"t": 0.0}

        def sleep(seconds):
            now["t"] += seconds

        cooldown = cr.Cooldown(clock=lambda: now["t"], sleep=sleep)
        cooldown.pause(5.0)
        self.assertEqual(cooldown.until, 5.0)
        cooldown.pause(1.0)                     # a later, shorter block
        self.assertEqual(cooldown.until, 5.0)   # keeps the longer one
        cooldown.pause(10.0)                    # extends from now
        self.assertEqual(cooldown.until, 10.0)
        self.assertEqual(cooldown.wait(), 10.0)
        self.assertEqual(cooldown.hits, 3)

    def test_429_pauses_the_shared_cooldown(self):
        pacer = cr.Pacer(interval=0.0)
        cooldown = cr.Cooldown()
        slept: list[float] = []
        url = "https://www.bseindia.com/x.pdf"
        session = _FakeSession([_FakeResponse(429), _FakeResponse(200, b"%PDF-1.7 ok")])
        started = time.monotonic()
        got = cr.fetch_url(url, pacer=pacer, session=session, cooldown=cooldown,
                           backoff=0.05, sleep=slept.append)
        self.assertEqual(got["status"], "ok")
        self.assertEqual(got["attempts"], 2)
        self.assertEqual(cooldown.hits, 1)
        self.assertEqual(slept, [])             # the cooldown owns the wait
        self.assertGreaterEqual(time.monotonic() - started, 0.045)


class ParallelRunTests(unittest.TestCase):
    def test_workers_run_concurrently_behind_the_pacer(self):
        calls: list[str] = []
        lock = threading.Lock()
        state = {"active": 0, "peak": 0}

        def on_call(url):
            with lock:
                state["active"] += 1
                state["peak"] = max(state["peak"], state["active"])
            time.sleep(0.05)
            with lock:
                state["active"] -= 1

        fetch = _fake_fetch(lambda url: ("ok", 200, "", _ok_bytes(url)),
                            calls=calls, on_call=on_call)
        root = _workdir("parallel")
        cands = [_cand(f"n{i}", isin=f"I{i}") for i in range(1, 7)]
        try:
            with _offline_db(), mock.patch.object(cr, "inspect_pdf", _stub_inspect):
                report = cr.run_pilot(candidates=cands, n=10, root=root,
                                      probe=root / "probe", fetch=fetch,
                                      workers=3, log=lambda *a: None)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(len(calls), 6)
        self.assertEqual(report["sampled"], 6)
        self.assertEqual(report["workers"], 3)
        self.assertEqual(report["ok"], 6)
        self.assertGreaterEqual(state["peak"], 2)


class JournalTests(unittest.TestCase):
    def test_roundtrip_flushes_each_line_and_ignores_junk(self):
        path = _scratch_dir() / "_journal_roundtrip.jsonl"
        path.unlink(missing_ok=True)
        try:
            with cr.JournalWriter(path) as writer:
                writer.append({"newsid": "n1", "status": "ok"})
                self.assertIn('"n1"', path.read_text(encoding="utf-8"))  # flushed, open
                writer.append({"newsid": "n2", "status": "failed", "permanent": True})
            with path.open("a", encoding="utf-8") as handle:
                handle.write('{"newsid": "truncated"')                  # killed mid-write
            journal = cr.load_journal(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(sorted(journal), ["n1", "n2"])
        self.assertEqual(writer.lines, 2)

    def test_last_line_for_a_newsid_wins(self):
        path = _scratch_dir() / "_journal_last.jsonl"
        try:
            path.write_text("\n".join([
                json.dumps({"newsid": "n1", "status": "failed", "reason": "network: Timeout"}),
                json.dumps({"newsid": "n1", "status": "ok"}),
            ]) + "\n", encoding="utf-8")
            journal = cr.load_journal(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(journal["n1"]["status"], "ok")

    def test_missing_journal_is_empty(self):
        self.assertEqual(cr.load_journal(_scratch_dir() / "_journal_none.jsonl"), {})

    def test_journal_done_skips_ok_and_permanent_only(self):
        self.assertTrue(cr.journal_done({"status": "ok"}))
        self.assertTrue(cr.journal_done({"status": "failed", "permanent": True}))
        self.assertFalse(cr.journal_done({"status": "failed",
                                          "reason": "network: Timeout"}))
        self.assertFalse(cr.journal_done({"status": "skipped"}))

    def test_permanent_failures(self):
        self.assertTrue(cr.is_permanent_failure({"status": "failed", "reason": "http 404",
                                                 "http_status": 404}))
        self.assertTrue(cr.is_permanent_failure({"status": "failed",
                                                 "reason": "not a PDF"}))
        self.assertTrue(cr.is_permanent_failure({"status": "invalid",
                                                 "reason": "pymupdf: FileDataError"}))
        self.assertFalse(cr.is_permanent_failure({"status": "failed", "reason": "http 429",
                                                  "http_status": 429}))
        self.assertFalse(cr.is_permanent_failure({"status": "failed", "reason": "http 503",
                                                  "http_status": 503}))
        self.assertFalse(cr.is_permanent_failure({"status": "failed", "reason": "no bytes",
                                                  "http_status": None}))


class JournalResumeTests(unittest.TestCase):
    """A restart skips ok/permanent rows, retries transient ones, keeps the manifest."""

    def _journal(self, root: Path, lines) -> Path:
        path = cr.journal_path(root, "full")
        path.write_text("".join(json.dumps(line) + "\n" for line in lines),
                        encoding="utf-8")
        return path

    def test_resume_skips_done_and_retries_transient(self):
        root = _workdir("resume")
        try:
            journal = self._journal(root, [
                {"newsid": "n1", "status": "ok", "chars": 4000,
                 "doc_class": "transcript", "sha256": "a" * 64},
                {"newsid": "n2", "status": "failed", "reason": "network: Timeout"},
                {"newsid": "n3", "status": "failed", "permanent": True,
                 "reason": "http 404", "http_status": 404},
            ])
            calls: list[str] = []
            fetch = _fake_fetch(lambda url: ("ok", 200, "", _ok_bytes(url)), calls=calls)
            cands = [_cand(f"n{i}", isin=f"I{i}") for i in range(1, 5)]
            with _offline_db(), mock.patch.object(cr, "inspect_pdf", _stub_inspect):
                report = cr.run_pilot(candidates=cands, n=10, root=root,
                                      probe=root / "probe", fetch=fetch,
                                      log=lambda *a: None)
            entries = {entry["newsid"]: entry for entry in report["entries"]}
            self.assertEqual(report["skipped_journal"], 2)      # n1 ok, n3 permanent
            self.assertEqual(report["sampled"], 4)
            self.assertEqual(len(calls), 2)                     # n2 retried, n4 new
            self.assertEqual(set(entries), {"n1", "n2", "n3", "n4"})
            self.assertEqual(entries["n1"]["chars"], 4000)      # journal row kept
            self.assertEqual(entries["n3"]["status"], "failed")
            self.assertEqual(entries["n2"]["status"], "ok")
            journal_now = cr.load_journal(journal)
            self.assertEqual(journal_now["n2"]["status"], "ok")
            self.assertEqual(journal_now["n4"]["status"], "ok")
            manifest = [json.loads(line) for line in
                        (root / "_manifest.jsonl").read_text(encoding="utf-8").splitlines()]
            self.assertEqual([row["newsid"] for row in manifest], ["n1", "n2", "n3", "n4"])
        finally:
            shutil.rmtree(root, ignore_errors=True)

    def test_dry_run_reports_the_journal_skips_and_writes_nothing(self):
        root = _workdir("dryresume")
        try:
            journal = self._journal(root, [
                {"newsid": "n1", "status": "ok", "chars": 4000, "doc_class": "transcript"},
                {"newsid": "n3", "status": "failed", "permanent": True},
            ])
            before = journal.read_text(encoding="utf-8")
            calls: list[str] = []
            fetch = _fake_fetch(lambda url: ("ok", 200, "", _ok_bytes(url)), calls=calls)
            cands = [_cand(f"n{i}", isin=f"I{i}") for i in range(1, 5)]
            with _offline_db(), mock.patch.object(cr, "inspect_pdf", _stub_inspect):
                report = cr.run_pilot(candidates=cands, n=10, root=root,
                                      probe=root / "probe", fetch=fetch, dry_run=True,
                                      log=lambda *a: None)
            self.assertEqual(report["skipped_journal"], 2)
            self.assertEqual(report["skipped"], 2)          # the two not journalled
            self.assertEqual(calls, [])                     # no network
            self.assertEqual(journal.read_text(encoding="utf-8"), before)
            self.assertFalse((root / "_manifest.jsonl").exists())
        finally:
            shutil.rmtree(root, ignore_errors=True)


class SeedLogTests(unittest.TestCase):
    def test_parse_log_rows(self):
        text = ("Traceback (most recent call last):\n"
                "[  1/9390] AAA          FY25Q4 ok      bse   transcript     29381c \n"
                "[3245/9390] TITAN        FY25Q4 ok      bse   transcript     56806c \n"
                "[   7/9390] ?            None    failed  bse   -                  0c http 404\n")
        rows = cr.parse_log_rows(text)
        self.assertEqual([row["index"] for row in rows], [1, 3245, 7])
        self.assertEqual(rows[0]["symbol"], "AAA")
        self.assertEqual(rows[0]["quarter"], "FY25Q4")
        self.assertEqual(rows[0]["doc_class"], "transcript")
        self.assertEqual(rows[0]["source"], "bse")
        self.assertEqual(rows[0]["chars"], 29381)
        self.assertEqual(rows[2]["symbol"], "")
        self.assertIsNone(rows[2]["doc_class"])
        self.assertEqual(rows[2]["reason"], "http 404")

    def _row(self, index, symbol, quarter="FY25Q1", status="ok", source="bse",
             doc_class="transcript", chars=5000, total=3, reason=""):
        return {"index": index, "total": total, "symbol": symbol, "quarter": quarter,
                "status": status, "source": None if source == "-" else source,
                "doc_class": None if doc_class == "-" else doc_class,
                "chars": chars, "reason": reason}

    def test_seed_keeps_only_ok_rows_with_a_pdf_on_disk(self):
        root = _workdir("seed")
        try:
            picks = [_cand("n1", sha="a" * 64), _cand("n2", sha="b" * 64, symbol="ZZZ"),
                     _cand("n3", sha=None, symbol="QQQ")]
            target = cr.pdf_path("a" * 64, root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"%PDF-1.4 seeded")
            rows = [self._row(1, "AAA"), self._row(2, "ZZZ"),
                    self._row(3, "QQQ"), self._row(4, "QQQ", status="failed",
                                                   doc_class="-", reason="http 404")]
            entries, counts = cr.seed_entries(rows, picks, root)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual([entry["newsid"] for entry in entries], ["n1"])
        self.assertEqual(counts["ok_rows"], 3)
        self.assertEqual(counts["seeded"], 1)
        self.assertEqual(counts["unmapped"], 2)      # no pdf on disk / no recorded sha
        self.assertEqual(entries[0]["sha256"], "a" * 64)
        self.assertEqual(entries[0]["bytes"], 15)
        self.assertEqual(entries[0]["chars"], 5000)
        self.assertTrue(entries[0]["seeded_from_log"])
        self.assertTrue(cr.journal_done(entries[0]))

    def test_seed_realigns_when_a_new_announcement_shifted_the_index(self):
        root = _workdir("seedshift")
        try:
            picks = [_cand("n1", sha="a" * 64, symbol="AAA"),
                     _cand("n2", sha="b" * 64, symbol="ZZZ")]
            target = cr.pdf_path("b" * 64, root)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(b"%PDF-1.4 shifted")
            # The live run's row 1 was ZZZ; today's pick at index 1 is AAA.
            entries, counts = cr.seed_entries([self._row(1, "ZZZ")], picks, root)
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual([entry["newsid"] for entry in entries], ["n2"])
        self.assertEqual(counts["realigned"], 1)

    def test_seed_journal_from_log_writes_the_journal(self):
        root = _workdir("seedjournal")
        try:
            cands = [_cand("n1", sha="a" * 64, symbol="AAA"),
                     _cand("n2", sha="b" * 64, symbol="ZZZ")]
            for sha in ("a" * 64, "b" * 64):
                target = cr.pdf_path(sha, root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(b"%PDF-1.4 " + sha[:1].encode())
            picks = cr.stratified_sample(cands, 2, seed=1)
            log_path = root / "run.log"
            log_path.write_text(
                "".join(f"[{i:>3}/{len(picks)}] {cand['symbol']:<12} {cand['quarter']} "
                        f"ok      bse   transcript     5000c \n"
                        for i, cand in enumerate(picks, 1)), encoding="utf-8")
            with _offline_db():
                got = cr.seed_journal_from_log(log_path, candidates=cands, seed=1,
                                               root=root, log=lambda *a: None)
            journal = cr.load_journal(cr.journal_path(root, "full"))
        finally:
            shutil.rmtree(root, ignore_errors=True)
        self.assertEqual(got["seeded"], 2)
        self.assertEqual(got["unmapped"], 0)
        self.assertEqual(sorted(journal), ["n1", "n2"])
        self.assertEqual(journal["n2"]["status"], "ok")
        self.assertEqual(journal["n2"]["doc_class"], "transcript")


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


class WidenTranscriptWordTests(unittest.TestCase):
    """Shivam 2026-10-28: of the fresh widened rows, only a transcript word is fetched."""

    def test_word_in_headline_or_attachment(self):
        self.assertTrue(cr.has_transcript_word("Transcript of the Earnings Call"))
        self.assertTrue(cr.has_transcript_word("Announcement attached",
                                               "Q2FY26_concall_Transcript.pdf"))
        self.assertFalse(cr.has_transcript_word("Conference Call with Analysts", "abc.pdf"))
        self.assertFalse(cr.has_transcript_word("Audio recording of the call"))
        self.assertFalse(cr.has_transcript_word(None, None))

    def test_filter_keeps_only_the_worded_rows(self):
        rows = [
            _cand("n1", headline="Earnings Call Transcript"),
            _cand("n2", headline="Intimation of Earnings Conference Call", attachment="b.pdf"),
            _cand("n3", headline="Announcement attached", attachment="Transcript_Q1FY26.pdf"),
            _cand("n4", headline="Investor Presentation", attachment="d.pdf"),
        ]
        kept = cr.transcript_word_rows(rows)
        self.assertEqual([c["newsid"] for c in kept], ["n1", "n3"])

    def test_widen_filter_is_wider_than_the_transcript_word(self):
        # The widen filter keeps a call synonym too; --transcript-word does not.
        row = ("n1", 1, "a.pdf", "Conference Call with Analysts", "General",
               "2024-05-01", 10, "AAA")
        self.assertEqual(len(cr.widen_rows([row])), 1)
        cand = _cand("n1", headline=row[3])
        self.assertEqual(cr.transcript_word_rows([cand]), [])


class RescueTests(unittest.TestCase):
    """--rescue-file: fetch exactly the newsids in the dedupe-rescue JSON."""

    def _write(self, payload) -> Path:
        path = _scratch_dir() / f"rescue_test_{id(payload)}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_rescue_rows_become_pilot_candidates(self):
        path = self._write([{
            "newsid": "7e4954f2", "scrip_cd": "543398",
            "attachment": "f475.pdf",
            "url": cr.pdf_url("f475.pdf"),
            "headline": "Pursuant to Regulation 30 ... transcript of the Analyst call",
            "subcat": "General", "known_at": "2024-04-04T15:07:25.35",
            "size": "542359", "symbol": "latentview", "isin": "INE0I7C01011",
            "group": "A-P", "quarter": "FY25Q1", "cd_id": "52268",
            "cd_sha": "ABCDEF", "cd_title": "CONCALL_TRANSCRIPT",
            "chunked": "True", "chunk_doc_id": "17052",
        }])
        try:
            rows = cr.load_rescue(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["symbol"], "LATENTVIEW")
        self.assertEqual(row["cd_id"], 52268)          # strings -> ints
        self.assertEqual(row["chunk_doc_id"], 17052)
        self.assertTrue(row["chunked"])                # "True" string -> bool
        self.assertEqual(row["cd_sha"], "abcdef")      # case-folded
        self.assertEqual(row["url"], cr.pdf_url("f475.pdf"))
        self.assertEqual(row["quarter"], "FY25Q1")

    def test_missing_fields_are_derived_and_junk_rows_dropped(self):
        path = self._write([
            {"newsid": "n1", "attachment": "a.pdf", "symbol": "quess",
             "known_at": "2024-07-05", "url": None},          # url from attachment
            {"newsid": "n1", "url": "https://x/y.pdf"},       # duplicate newsid
            {"newsid": "", "url": "https://x/z.pdf"},         # no newsid
            {"attachment": "q.pdf"},                          # no newsid, no url
            "not a dict",
        ])
        try:
            rows = cr.load_rescue(path)
        finally:
            path.unlink(missing_ok=True)
        self.assertEqual([r["newsid"] for r in rows], ["n1"])
        self.assertEqual(rows[0]["group"], "Q-Z")          # derived from QUESS
        self.assertEqual(rows[0]["quarter"], "FY25Q2")     # derived from Jul 2024
        self.assertFalse(rows[0]["chunked"])

    def test_rescue_file_must_be_a_json_array(self):
        path = self._write({"rows": [{"newsid": "n1"}]})
        try:
            with self.assertRaises(ValueError):
                cr.load_rescue(path)
        finally:
            path.unlink(missing_ok=True)

    def test_rescue_flag_writes_its_own_manifest(self):
        # The CLI wires --rescue-file to its own manifest name.
        import inspect
        source = inspect.getsource(cr.main)
        self.assertIn("--rescue-file", source)
        self.assertIn("_manifest_rescue.jsonl", source)


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
