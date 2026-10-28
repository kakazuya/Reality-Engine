"""Offline tests for the NSE corporate-announcements fetcher.

No network, no live DB: the session is a fake object and the ISIN map is given.
"""

import json
import shutil
import unittest
import uuid
from pathlib import Path

from reality_engine.scripts.nse_announcements import (
    AnnouncementFetcher,
    DEFAULT_DOWNLOAD_BUCKETS,
    attachment_url,
    bucket,
    is_transcript_like,
    known_at_of,
    matches_subject,
    needs_download,
    normalize,
    record_bucket,
    record_kind,
    parse_known_at,
    row_size_bytes,
)

ROW = {
    "symbol": "RELIANCE",
    "sm_isin": "INE002A01018",
    "sm_name": "Reliance Industries Limited",
    "desc": "Analysts/Institutional Investor Meet/Con. Call Updates",
    "attchmntText": "Audio / Video Recording and Transcript of Presentation made to analysts",
    "an_dt": "30-Apr-2024 21:04:19",
    "exchdisstime": "30-Apr-2024 21:04:23",
    "sort_date": "2024-04-30 21:04:19",
    "attchmntFile": "https://archives.nseindia.com/corporate/RELIANCE_30042024210423.pdf",
    "seq_id": "1234567",
    "fileSize": "-",
    "attFileSize": None,
}


def tmpdir(case) -> Path:
    """A scratch dir the sandbox can actually write (mkdtemp dirs are denied)."""
    d = Path(".tmp") / f"nse_ann_test_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    case.addCleanup(shutil.rmtree, d, True)
    return d


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b""):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self):
        if self._payload is None:
            raise ValueError("no json")
        return self._payload


class FakeSession:
    """Serves a scripted list of responses and records every URL."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        return self.script.pop(0) if self.script else FakeResponse(200, {"data": []})


class FakeClient:
    """Stands in for NSEClient: session + warm-up flag, nothing else."""

    def __init__(self, script):
        self.session = FakeSession(script)
        self._warmed_up = True

    def _warmup_session(self):
        self._warmed_up = True


class TimestampTests(unittest.TestCase):
    def test_nse_formats(self):
        self.assertEqual(parse_known_at("30-Apr-2024 21:04:23"), "2024-04-30T21:04:23")
        self.assertEqual(parse_known_at("2024-04-30 21:04:19"), "2024-04-30T21:04:19")
        self.assertEqual(parse_known_at("2024-04-30T21:04:19"), "2024-04-30T21:04:19")
        self.assertEqual(parse_known_at("30-04-2024 21:04"), "2024-04-30T21:04:00")
        self.assertEqual(parse_known_at("30-Apr-2024"), "2024-04-30T00:00:00")

    def test_garbage_is_none(self):
        for bad in (None, "", "  ", "-", "not a date"):
            self.assertIsNone(parse_known_at(bad), bad)

    def test_exchdisstime_wins_over_an_dt_and_sort_date(self):
        # The three clocks differ by seconds: exchdisstime is the later,
        # exchange-side dissemination stamp, so it is the known_at.
        self.assertEqual(known_at_of(ROW), "2024-04-30T21:04:23")

    def test_fallbacks(self):
        self.assertEqual(known_at_of({"an_dt": "30-Apr-2024 21:04:19"}), "2024-04-30T21:04:19")
        self.assertEqual(known_at_of({"sort_date": "2024-04-30"}), "2024-04-30T00:00:00")
        self.assertIsNone(known_at_of({"desc": "no clock here"}))


class NormalizeTests(unittest.TestCase):
    def test_row_with_isin_and_full_fields(self):
        rec = normalize(ROW, "RELIANCE", {})
        self.assertEqual(rec["symbol"], "RELIANCE")
        self.assertEqual(rec["isin"], "INE002A01018")
        self.assertEqual(rec["isin_source"], "row")
        self.assertEqual(rec["subject"], ROW["desc"])   # subject is empty on this feed
        self.assertEqual(rec["desc"], ROW["desc"])
        self.assertEqual(rec["known_at"], "2024-04-30T21:04:23")
        self.assertEqual(rec["attachment_url"], ROW["attchmntFile"])
        self.assertEqual(rec["seq_id"], "1234567")
        self.assertIs(rec["raw"], ROW)

    def test_isin_resolved_from_master_when_row_has_none(self):
        row = dict(ROW, sm_isin="")
        rec = normalize(row, "RELIANCE", {"RELIANCE": "INE002A01018"})
        self.assertEqual(rec["isin"], "INE002A01018")
        self.assertEqual(rec["isin_source"], "master_companies")

    def test_malformed_isin_is_not_trusted(self):
        row = dict(ROW, sm_isin="NA", symbol="TCS")
        rec = normalize(row, "TCS", {"TCS": "INE467B01029"})
        self.assertEqual(rec["isin"], "INE467B01029")
        self.assertEqual(rec["isin_source"], "master_companies")

    def test_unresolvable_isin_is_kept_as_none(self):
        rec = normalize(dict(ROW, sm_isin=""), "UNKNOWN", {})
        self.assertIsNone(rec["isin"])
        self.assertIsNone(rec["isin_source"])

    def test_relative_attachment_url_is_expanded(self):
        self.assertEqual(attachment_url({"attchmntFile": "/corporate/x.pdf"}),
                         "https://www.nseindia.com/corporate/x.pdf")
        self.assertIsNone(attachment_url({"attchmntFile": ""}))

    def test_transcript_detection(self):
        self.assertTrue(is_transcript_like(normalize(ROW, "RELIANCE", {})))
        deck = normalize(dict(ROW, desc="Investor Presentation",
                              attchmntText="Investor Presentation"), "X", {})
        self.assertFalse(is_transcript_like(deck))  # a deck is another job
        losing = normalize(dict(ROW, desc="Loss of Share Certificates",
                                attchmntText="Reg 39(3) share certificates"), "X", {})
        self.assertFalse(is_transcript_like(losing))

    def test_record_kind_separates_transcripts_from_meet_paperwork(self):
        self.assertEqual(record_kind(ROW), "transcript")   # 'Con. Call Updates' + 'Transcript of'
        self.assertEqual(record_kind({"desc": "Investor Presentation",
                                      "attchmntFile": "X_21082026_ConcallTranscript.pdf"}), "transcript")
        self.assertEqual(record_kind({"desc": "Analysts/Institutional Investor Meet/Con. Call Updates",
                                      "attchmntText": "intimation of investor meet",
                                      "attchmntFile": "X_IntimationofInvestorsMeet.pdf"}), "meet")
        self.assertEqual(record_kind({"desc": "Loss of Share Certificates"}), "other")

    def test_subject_filter(self):
        self.assertTrue(matches_subject("Analysts/Institutional Investor Meet/Con. Call Updates",
                                        ["analyst"]))
        self.assertFalse(matches_subject("Dividend", ["analyst"]))
        self.assertTrue(matches_subject("Dividend", []))  # no filter keeps everything


class BucketTests(unittest.TestCase):
    """Shivam 2026-10-28: download only transcript/meet and material rows."""

    @staticmethod
    def rec(desc, text=""):
        return {"desc": desc, "raw": {"attchmntText": text}}

    def test_transcript_bucket(self):
        self.assertEqual(bucket(normalize(ROW, "RELIANCE", {})), "transcript")
        self.assertEqual(bucket(self.rec(
            "Updates", "Transcript of the Earnings Call")), "transcript")
        self.assertEqual(bucket(self.rec(
            "Updates", "Audio Recording Q4FY24 Earnings Call")), "transcript")

    def test_material_bucket(self):
        for desc, text in (
            ("Bagging/Receiving of orders/contracts", ""),
            ("Updates", "Intimation of changes in senior management"),
            ("Outcome of Board Meeting",
             "financial results for the period ended Jun 30, 2026"),
            ("Outcome of Board Meeting", "Board meeting held on February 11, 2025"),
            ("Investor Presentation", ""),
            ("Credit Rating", ""),
            ("Public Announcement-Open Offer", "Substantial Acquisition of Shares"),
            ("General Updates", "Receipt of Order from Indian Railways"),
        ):
            self.assertEqual(bucket(self.rec(desc, text)), "material", (desc, text))

    def test_procedural_bucket(self):
        for desc, text in (
            ("Copy of Newspaper Publication",
             "newspaper publication of unaudited financial results"),
            ("Outcome of Board Meeting", "trading window closure pursuant to SEBI PIT"),
            ("Outcome of Board Meeting", "Notice of Annual General Meeting"),
            ("Shareholders meeting", "Srutinizers report of Annual General Meeting"),
            ("ESOP/ESOS/ESPS", "Grant of 2000 Options"),
            ("Allotment of Securities",
             "allotment of 43333 securities pursuant to ESOP/ESPS"),
            ("Loss of Share Certificates", ""),
            ("Trading Window", ""),
            ("Record Date", ""),
            ("Book Closure", ""),
            ("Clarification - Financial Results", "Exchange has sought clarification"),
        ):
            self.assertEqual(bucket(self.rec(desc, text)), "procedural", (desc, text))

    def test_unclear_bucket(self):
        self.assertEqual(bucket(self.rec(
            "Updates", "Disclosure under Regulation 30 of SEBI (LODR) Regulations, 2015")),
            "unclear")
        self.assertEqual(bucket(self.rec("General Updates")), "unclear")
        self.assertEqual(bucket(self.rec("Updates", "")), "unclear")

    def test_bucket_is_stored_and_old_rows_are_rejudged(self):
        rec = normalize(ROW, "RELIANCE", {})
        self.assertEqual(rec["bucket"], "transcript")
        self.assertEqual(record_bucket(rec), "transcript")
        old = {"desc": "Trading Window", "raw": {"attchmntText": "Trading Window closure"}}
        self.assertEqual(record_bucket(old), "procedural")     # written before the field
        self.assertEqual(record_bucket({"bucket": "material"}), "material")

    def test_default_download_buckets(self):
        self.assertEqual(DEFAULT_DOWNLOAD_BUCKETS, ("transcript", "material"))


class DownloadBucketTests(unittest.TestCase):
    def _row(self, **kw):
        return dict(ROW, **kw)

    def test_run_downloads_only_transcript_and_material(self):
        out = tmpdir(self)
        transcript_row = self._row()
        procedural_row = self._row(
            desc="Trading Window", seq_id="7654321",
            attchmntText="Trading Window closure pursuant to SEBI PIT Regulations",
            attchmntFile="https://archives.nseindia.com/corporate/TW.pdf")
        script = [FakeResponse(200, {"data": [transcript_row, procedural_row]}),
                  FakeResponse(200, content=b"%PDF-1.4 transcript")]
        f = AnnouncementFetcher(out, interval=3, client=FakeClient(script),
                                isin_map={}, sleep=lambda seconds: None)
        stats = f.run(["RELIANCE"], "2024-04-01", "2024-04-30", download=True)
        self.assertEqual(stats["downloaded"], 1)
        self.assertEqual(stats["bucket_transcript"], 1)
        self.assertEqual(stats["bucket_procedural"], 1)
        pdfs = [p for p in (out / "attachments").rglob("*") if p.is_file()]
        self.assertEqual(len(pdfs), 1)
        self.assertIn("RELIANCE_30042024210423.pdf", pdfs[0].name)
        rows = [json.loads(line) for line in
                (out / "RELIANCE.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual({r["bucket"] for r in rows}, {"transcript", "procedural"})

    def test_download_buckets_can_be_overridden(self):
        out = tmpdir(self)
        procedural_row = self._row(
            desc="Trading Window", seq_id="7654321",
            attchmntText="Trading Window closure pursuant to SEBI PIT Regulations",
            attchmntFile="https://archives.nseindia.com/corporate/TW.pdf")
        script = [FakeResponse(200, {"data": [procedural_row]}),
                  FakeResponse(200, content=b"%PDF-1.4 window")]
        f = AnnouncementFetcher(out, interval=3, client=FakeClient(script),
                                isin_map={}, sleep=lambda seconds: None)
        stats = f.run(["RELIANCE"], "2024-04-01", "2024-04-30", download=True,
                      download_buckets=["procedural"])
        self.assertEqual(stats["downloaded"], 1)


class ResumeTests(unittest.TestCase):
    def test_size_parsing(self):
        self.assertEqual(row_size_bytes({"fileSize": "1.5 MB"}), int(1.5 * 1024 ** 2))
        self.assertEqual(row_size_bytes({"fileSize": "500 KB"}), 500 * 1024)
        self.assertIsNone(row_size_bytes({"fileSize": "-"}))

    def test_needs_download(self):
        if True:
            p = tmpdir(self) / "a.pdf"
            self.assertTrue(needs_download(p, 100))          # nothing on disk
            p.write_bytes(b"x" * 100)
            self.assertFalse(needs_download(p, 100))         # same size: resume skip
            self.assertFalse(needs_download(p, None))        # no size hint: keep it
            self.assertTrue(needs_download(p, 5000))         # clearly truncated: refetch
            p.write_bytes(b"")
            self.assertTrue(needs_download(p, None))         # zero-byte file: refetch

    def test_write_symbol_dedups_on_resume(self):
        out = tmpdir(self)
        f = AnnouncementFetcher(out, interval=3, client=FakeClient([]), isin_map={})
        self.assertEqual(f.write_symbol("RELIANCE", [ROW]), 1)
        self.assertEqual(f.write_symbol("RELIANCE", [ROW]), 0)   # second run, same seq_id
        lines = (out / "RELIANCE.jsonl").read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 1)
        self.assertEqual(json.loads(lines[0])["known_at"], "2024-04-30T21:04:23")

    def test_manifest_marks_window_done(self):
        out = tmpdir(self)
        script = [FakeResponse(200, {"data": [ROW]}), FakeResponse(200, {"data": []})]
        f = AnnouncementFetcher(out, interval=3, client=FakeClient(script), isin_map={})
        first = f.run(["RELIANCE"], "2024-04-01", "2024-04-30")
        self.assertEqual(first["new"], 1)
        # a second run skips the finished window without a request
        again = AnnouncementFetcher(out, interval=3, client=FakeClient([]), isin_map={})
        second = again.run(["RELIANCE"], "2024-04-01", "2024-04-30")
        self.assertEqual(second["skipped"], 1)
        self.assertEqual(again.requests_made, 0)


class RecordingFetcher(AnnouncementFetcher):
    """Fetcher whose session rebuild is observable and offline."""

    def __init__(self, *a, **kw):
        self.rebuilds = 0
        self.sleeps = []
        super().__init__(*a, sleep=self.sleeps.append, **kw)

    def _rebuild(self, client):
        self.rebuilds += 1
        client.session = FakeSession(client.session.script)


class BackoffTests(unittest.TestCase):
    def test_403_backs_off_then_succeeds(self):
        out = tmpdir(self)
        client = FakeClient([FakeResponse(403), FakeResponse(403), FakeResponse(200, {"data": [ROW]})])
        f = RecordingFetcher(out, interval=3, client=client, isin_map={})
        resp = f.get("https://www.nseindia.com/api/x")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(f.blocks, {403: 2})
        self.assertEqual(f.sleeps, [3.0, 6.0])      # exponential: base * 2**attempt
        self.assertEqual(f.rebuilds, 2)             # cookie jar rebuilt after each block

    def test_429_and_503_are_retried_and_hopeless_runs_stop(self):
        out = tmpdir(self)
        client = FakeClient([FakeResponse(429), FakeResponse(503), FakeResponse(503),
                             FakeResponse(503), FakeResponse(503)])
        f = RecordingFetcher(out, interval=3, client=client, isin_map={})
        self.assertIsNone(f.get("https://www.nseindia.com/api/x"))
        self.assertEqual(f.blocks, {429: 1, 503: 4})
        self.assertEqual(f.sleeps, [3.0, 6.0, 12.0, 24.0, 48.0])

    def test_other_status_is_not_retried(self):
        out = tmpdir(self)
        f = RecordingFetcher(out, interval=3, client=FakeClient([FakeResponse(404)]), isin_map={})
        self.assertEqual(f.get("https://www.nseindia.com/api/x").status_code, 404)
        self.assertEqual(f.sleeps, [])

    def test_interval_floor_is_three_seconds(self):
        f = AnnouncementFetcher(tmpdir(self), interval=0.2,
                                client=FakeClient([]), isin_map={})
        self.assertEqual(f.interval, 3.0)


if __name__ == "__main__":
    unittest.main()
