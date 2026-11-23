"""Tests for the video screen OCR pilot (``reality_engine.processing.video_screen_ocr``).

No video, ffmpeg, RapidOCR or live database: every rule is a pure function, and the
end-to-end case builds a throwaway SQLite master + Drive tree in a temp directory.
"""

import contextlib
import json
import shutil
import sqlite3
import tempfile
import unittest
import uuid
from pathlib import Path

from reality_engine.processing import video_screen_ocr as pilot


def _scratch(name: str) -> Path:
    """A writable temp dir. tempfile.mkdtemp() leaves a 0o700 ACL the DSH sandbox cannot
    write into (same reason as test_raw_root._scratch), so the dir is made here."""
    directory = Path(tempfile.gettempdir()) / f"video_ocr_{name}_{uuid.uuid4().hex}"
    directory.mkdir(parents=True)
    return directory


@contextlib.contextmanager
def _scratch_ctx(name: str):
    directory = _scratch(name)
    try:
        yield directory
    finally:
        shutil.rmtree(directory, ignore_errors=True)


class DateTests(unittest.TestCase):
    def test_iso_folder_date(self):
        self.assertEqual(pilot.parse_folder_date("2026-08-16 Astra Microwave")[0], "2026-08-16")

    def test_ordinal_day_month_name(self):
        self.assertEqual(pilot.parse_folder_date("18th feb 2026")[0], "2026-02-18")
        self.assertEqual(pilot.parse_folder_date("1st Sep 2026")[0], "2026-09-01")

    def test_plain_day_month_name(self):
        self.assertEqual(pilot.parse_folder_date("2 Jan 2026")[0], "2026-01-02")
        self.assertEqual(
            pilot.parse_folder_date("29 Dec 2025- Necter Life, Ship builders, Timex")[0],
            "2025-12-29")

    def test_month_name_first(self):
        self.assertEqual(pilot.parse_folder_date("Feb 18, 2026 call")[0], "2026-02-18")

    def test_invalid_iso_date_is_rejected_not_guessed(self):
        self.assertIsNone(pilot.parse_folder_date("2024-25-09 Veritas (India) Ltd")[0])

    def test_no_date(self):
        self.assertIsNone(pilot.parse_folder_date("Kitex Garments")[0])


class PathTests(unittest.TestCase):
    def test_channels(self):
        self.assertEqual(pilot.channel_of(
            "Current Premium Users/Member Videos/2026-05-03 Ask Me Anything/v.mp4"),
            "member_video")
        self.assertEqual(pilot.channel_of(
            "Current Premium Users/Member Videos/Daily Bytes/v.mp4"), "dailybytes")
        self.assertEqual(pilot.channel_of(
            "Current Premium Users/DailyBytes/16th feb 2026/v.mp4"), "dailybytes")
        self.assertEqual(pilot.channel_of(
            "Research/Completed/Theme Research/Railways/Industry.mp4"), "research_video")
        # the same Research tree mirrored under Current Premium Users is still research
        self.assertEqual(pilot.channel_of(
            "Current Premium Users/Research/Completed/Company Research/Kitex Garments/k.mp4"),
            "research_video")

    def test_title_is_the_folder(self):
        self.assertEqual(pilot.video_title(
            "Current Premium Users/Member Videos/2026-08-16 Astra Microwave/v.mp4"),
            "2026-08-16 Astra Microwave")

    def test_drive_relative_path_drops_the_tree_root(self):
        self.assertEqual(pilot.drive_rel_path(
            "Current Premium Users/Member Videos/2026-08-16 Astra Microwave/v.mp4"),
            "Member Videos/2026-08-16 Astra Microwave/v.mp4")
        self.assertEqual(pilot.drive_rel_path(
            "Research/Completed/Company Research/Kitex Garments/Kitex Garment.mp4"),
            "Completed/Company Research/Kitex Garments/Kitex Garment.mp4")


class PublishedTests(unittest.TestCase):
    def test_folder_date_wins_and_is_high_confidence(self):
        result = pilot.resolve_published([("2026-08-16 Astra Microwave", "parent folder")],
                                         {"Metadata": {"btime": "16-08-2026 03:09:20 PM"}})
        self.assertEqual(result["published_at"], "2026-08-16")
        self.assertEqual(result["pit_source"], "folder_name")
        self.assertEqual(result["pit_confidence"], "high")

    def test_drive_btime_is_medium_confidence_when_mtime_agrees(self):
        result = pilot.resolve_published(
            [("Kitex Garments", "parent folder")],
            {"Metadata": {"btime": "19-02-2025 10:39:24 AM", "mtime": "19-02-2025 09:22:54 PM"}})
        self.assertEqual(result["published_at"], "2025-02-19")
        self.assertEqual(result["pit_source"], "drive_btime")
        self.assertEqual(result["pit_confidence"], "medium")

    def test_upload_long_after_the_file_is_low_confidence(self):
        # the real Kitex Garments case: btime 2025-02-19 is the upload, mtime 2024-11-07 the file
        result = pilot.resolve_published(
            [("Kitex Garments", "parent folder")],
            {"Metadata": {"btime": "19-02-2025 10:39:24 AM", "mtime": "07-11-2024 09:22:54 PM"}})
        self.assertEqual(result["pit_source"], "drive_btime")
        self.assertEqual(result["pit_confidence"], "low")
        self.assertIn("BEFORE btime", result["date_evidence"])

    def test_folder_date_beats_a_much_later_drive_btime_but_says_so(self):
        result = pilot.resolve_published(
            [("2024-09-11 Epack Durable", "parent folder")],
            {"Metadata": {"btime": "19-02-2025 06:34:31 PM", "mtime": "10-09-2024 05:43:57 PM"}})
        self.assertEqual(result["published_at"], "2024-09-11")
        self.assertEqual(result["pit_confidence"], "high")
        self.assertIn("161 d later than the folder date", result["date_evidence"])

    def test_mtime_a_day_after_btime_is_low_confidence(self):
        result = pilot.resolve_published(
            [("Kitex Garments", "parent folder")],
            {"Metadata": {"btime": "19-02-2025 10:39:24 AM", "mtime": "25-02-2025 10:39:24 AM"}})
        self.assertEqual(result["pit_confidence"], "low")

    def test_no_date_anywhere_is_null_with_reason(self):
        result = pilot.resolve_published([("Kitex Garments", "parent folder")], None)
        self.assertIsNone(result["published_at"])
        self.assertIn("no folder date", result["date_evidence"])


class ChromeTests(unittest.TestCase):
    def test_urls_menus_and_noise_are_chrome(self):
        for line in ("https://docs.google.com/document/d/abc", "File Edit View Insert Format Tools",
                     "Type here to search", "Indicators", "ETPrime", "Home"):
            self.assertIsNotNone(pilot.chrome_reason(line), line)

    def test_real_content_survives(self):
        for line in ("Revenue from operations 1,204.6", "EBITDA margin expanded 240 bps",
                     "Balu Forge Industries Ltd"):
            self.assertIsNone(pilot.chrome_reason(line), line)

    def test_split_chrome_counts_reasons(self):
        kept, dropped = pilot.split_chrome(["www.bseindia.com", "Revenue 100", "Share"])
        self.assertEqual(kept, ["Revenue 100"])
        self.assertEqual(dropped, {"url": 1, "gdoc_chrome": 1})


class ScreenTypeTests(unittest.TestCase):
    def test_sheet_beats_doc_when_the_grid_is_visible(self):
        screen_type, _ = pilot.classify_screen(
            ["sheets.google.com", "File Edit View", "A B C D E", "Revenue"])
        self.assertEqual(screen_type, "gsheet")

    def test_gdoc(self):
        self.assertEqual(pilot.classify_screen(["docs.google.com", "Normal text"])[0], "gdoc")

    def test_screener(self):
        self.assertEqual(pilot.classify_screen(["screener.in", "Screens"])[0], "screener")

    def test_screener_survives_ocr_mangled_logo(self):
        # measured on the 2025-11-23 AMA: screener.in's logo OCRs as "screeneril"
        self.assertEqual(
            pilot.classify_screen(["screeneril", "FEED", "SCREENS", "SHUBHAMSETHI",
                                   "Peer comparison", "Paushak"])[0], "screener")

    def test_peer_comparison_table_without_the_logo(self):
        self.assertEqual(pilot.classify_screen(["Peer comparison", "EDIT COLUMNS",
                                                "Median: 91 Co."])[0], "screener")

    def test_exchange_filing(self):
        self.assertEqual(
            pilot.classify_screen(["BSE: 532067", "Announcement under Regulation 30"])[0],
            "exchange_filing")

    def test_chart(self):
        self.assertEqual(pilot.classify_screen(["TradingView", "Indicators"])[0], "chart")

    def test_unknown_falls_back_to_other_with_a_cue(self):
        screen_type, cue = pilot.classify_screen(["Government rolls out a scheme", "Rs 44,700 crore"])
        self.assertEqual(screen_type, "other")
        self.assertIn("no cue matched", cue)


class GradeTests(unittest.TestCase):
    def test_a_grade_needs_many_lines_chars_and_score(self):
        lines = [f"Revenue line {i} with enough characters" for i in range(8)]
        self.assertEqual(pilot.grade_screen(lines, 0.9), "A")
        self.assertEqual(pilot.grade_screen(lines, 0.5), "B")

    def test_b_and_c(self):
        three_each = ["Revenue up 20 percent", "Margin holds", "Debt falls"]
        self.assertEqual(pilot.grade_screen(three_each, 0.9), "B")
        self.assertEqual(pilot.grade_screen(["Ok"], 0.9), "C")


class DedupeTests(unittest.TestCase):
    def test_first_frame_is_always_kept(self):
        self.assertEqual(pilot.keep_frame(None, b"\x00"), (True, None))

    def test_identical_thumbnail_is_dropped_below_the_threshold(self):
        thumb = bytes([100, 100, 100, 100])
        kept, diff = pilot.keep_frame(bytes([100, 100, 100, 101]), thumb)
        self.assertFalse(kept)
        self.assertLess(diff, pilot.DEDUPE_MEAN_ABS)

    def test_changed_thumbnail_is_kept(self):
        kept, diff = pilot.keep_frame(bytes([100, 100, 100, 100]), bytes([120, 120, 120, 120]))
        self.assertTrue(kept)
        self.assertAlmostEqual(diff, 20.0)


CATALOG = [
    ("INE000000001", "EPACK", "Epack Durable Ltd", "543456"),
    ("INE000000002", "ASTRAMICRO", "Astra Microwave Products Ltd", "532493"),
    ("INE000000003", "MAZDOCK", "Mazagon Dock Shipbuilders Ltd", "543237"),
    ("INE000000004", "GRSE", "Garden Reach Shipbuilders & Engineers Ltd", "542801"),
    ("INE000000005", "COCHINSHIP", "Cochin Shipyard Ltd", "540678"),
    ("INE000000006", "GARWAREBTL", "Garware Hi-Tech Films Ltd", "500655"),
    ("INE000000007", "NECLIFE", "Nectar Lifesciences Ltd", "532649"),
    ("INE000000008", "TIMEX", "Timex Group India Ltd", "500414"),
    ("INE000000009", "PAYTM", "One97 Communications Ltd", "543396"),
]


class CompanyMatchTests(unittest.TestCase):
    def setUp(self):
        self.matcher = pilot.CompanyMatcher(CATALOG)

    def test_exact_name_after_date_prefix(self):
        matches = self.matcher.match("2024-09-11 Epack Durable")
        self.assertEqual([m["isin"] for m in matches], ["INE000000001"])
        self.assertEqual(matches[0]["method"], "exact_name")
        self.assertEqual(matches[0]["score"], 1.0)

    def test_multi_company_title_returns_several(self):
        matches = self.matcher.match(
            "2025-06-29 ShipBuilding Sector_ Mazgaon, GRSE, Cochin Shipyard")
        isins = {m["isin"] for m in matches}
        self.assertEqual(isins, {"INE000000003", "INE000000004", "INE000000005"})
        methods = {m["isin"]: m["method"] for m in matches}
        self.assertEqual(methods["INE000000004"], "symbol")
        self.assertEqual(methods["INE000000003"], "token_prefix")  # Mazgaon -> Mazagon

    def test_ama_and_market_view_yield_nothing(self):
        self.assertEqual(self.matcher.match("2026-05-03 Ask Me Anything"), [])
        self.assertEqual(self.matcher.match("2024-12-18 Market View"), [])

    def test_typo_still_matches_by_token_prefix(self):
        matches = self.matcher.match("29 Dec 2025- Necter Life, Ship builders, Timex")
        isins = {m["isin"] for m in matches}
        self.assertIn("INE000000007", isins)
        self.assertIn("INE000000008", isins)
        self.assertLess(min(m["score"] for m in matches), 1.0)

    def test_hyphenated_name_fuzzy_match(self):
        matches = self.matcher.match("2025-02-16 Garware Hitech Films & AMA")
        self.assertEqual([m["isin"] for m in matches], ["INE000000006"])

    def test_generic_head_never_takes_a_fuzzy_match(self):
        self.assertEqual(self.matcher.match("Power Sector"), [])
        self.assertEqual(self.matcher.match("Chartink Dashboard Detailed"), [])


class GlossaryTests(unittest.TestCase):
    def test_line_starters_dropped_and_acronyms_kept(self):
        lines = ["Industry", "SBFAS scheme for shipbuilding", "Industry",
                 "SbDS covers shipbuilding", "SBFAS again"]
        terms = {term for term, _, is_company in pilot.glossary(lines)}
        self.assertIn("SBFAS", terms)
        self.assertNotIn("Industry", terms)

    def test_company_name_always_present(self):
        terms = pilot.glossary([], ["Epack Durable Ltd"])
        self.assertEqual(terms[0][0], "Epack Durable Ltd")
        self.assertEqual(terms[0][2], 1)

    def test_ui_label_on_most_screens_is_dropped(self):
        # 'DMA' is a screener.in column header repeated on nearly every screen of the AMA
        lines = ["Cash Flow DMA alpha", "Profit DMA beta", "Sales DMA gamma",
                 "Loss DMA delta", "Debt DMA epsilon", "Assets DMA zeta",
                 "Peer table Paushak 577.95", "Medians Paushak 577.95"]
        terms = {term for term, _, _ in pilot.glossary(lines, total_screens=20)}
        self.assertNotIn("DMA", terms)
        self.assertIn("Paushak", terms)


class LinkDocTests(unittest.TestCase):
    DOCS = [{"path": "Current Premium Users/Member Videos/2026-03-07 Fake Durable/"
                     "Fake Durable Ltd.docx",
             "folder": "2026-03-07 Fake Durable", "stem": "Fake Durable Ltd"},
            {"path": "Current Premium Users/Research/Completed/Company Research/Astra Microwave/"
                     "Astra Microwave.xlsx",
             "folder": "Astra Microwave", "stem": "Astra Microwave"}]

    def test_same_folder_doc_is_linked(self):
        path, reason = pilot.link_doc(
            "gdoc", "Fake Durable Ltd\nRevenue 120\nEBITDA 22", "2026-03-07 Fake Durable",
            ["fake durable"], self.DOCS)
        self.assertTrue(path.endswith("Fake Durable Ltd.docx"))
        self.assertIn("same_folder", reason)

    def test_company_folder_doc_is_linked_by_title_coverage(self):
        path, reason = pilot.link_doc(
            "gsheet", "Astra Microwave Products Ltd\nRevenue", "2026-08-16 Astra Microwave",
            ["astra microwave products"], self.DOCS)
        self.assertTrue(path.endswith("Astra Microwave.xlsx"))

    def test_chart_screen_is_null_with_a_reason(self):
        path, reason = pilot.link_doc("chart", "Indicators", "x", [], self.DOCS)
        self.assertIsNone(path)
        self.assertEqual(reason, "screen_type_not_doc")


class SegmentsAndLinesTests(unittest.TestCase):
    def _screens(self, *specs):
        out = []
        for no, (t_start, t_end, screen_type) in enumerate(specs, 1):
            out.append({"screen_no": no, "t_start": t_start, "t_end": t_end,
                        "screen_type": screen_type})
        return out

    def test_same_type_run_is_one_segment(self):
        screens = self._screens((0, 5, "gdoc"), (5, 10, "gdoc"), (10, 15, "chart"))
        self.assertEqual([label for _, label in pilot.assign_segments(screens)],
                         ["gdoc #1", "gdoc #1", "chart #2"])

    def test_long_gap_starts_a_new_segment(self):
        screens = self._screens((0, 5, "other"), (5 + pilot.SEGMENT_GAP_S + 5, 120, "other"))
        segments = pilot.assign_segments(screens)
        self.assertEqual(segments[0][0], 1)
        self.assertEqual(segments[1][0], 2)

    def test_interleaved_type_going_back_reopens_a_segment(self):
        screens = self._screens((0, 5, "gdoc"), (5, 10, "chart"), (10, 15, "gdoc"))
        self.assertEqual([no for no, _ in pilot.assign_segments(screens)], [1, 2, 3])

    def test_annotate_lines_marks_the_chrome_it_drops(self):
        annotated = pilot.annotate_lines(["https://x.com", "Revenue 100"])
        self.assertEqual(annotated[0][1], "url")
        self.assertIsNone(annotated[1][1])


class HandCheckTests(unittest.TestCase):
    """The hand check must fail rows whose label no independent source supports."""

    def setUp(self):
        self.company_rows = [("INE000000001", "FKDUR", "Fake Durable Ltd", "543456"),
                             ("INE000000008", "TIMEX", "Timex Group India Ltd", "500414")]

    def _video(self, rel_path, matches, published_at="2026-03-07",
               pit_source="folder_name", channel="member_video"):
        return {"video_id": "v1", "rel_path": rel_path, "title": Path(rel_path).parent.name,
                "matches_json": json.dumps(matches), "company_isin":
                ";".join(m["isin"] for m in matches) or None,
                "published_at": published_at, "pit_source": pit_source,
                "pit_confidence": "high", "channel": channel, "drive_btime": None,
                "duration_s": 300.0, "date_evidence": ""}

    def test_legal_suffix_words_are_not_required_in_the_title(self):
        video = self._video("Member Videos/2026-03-07 Timex/v.mp4",
                            [{"isin": "INE000000008", "symbol": "TIMEX",
                              "name": "Timex Group India Ltd", "method": "symbol",
                              "score": 0.95, "segment": "timex"}])
        ok, note = pilot._check_company(video)
        self.assertTrue(ok, note)

    def test_typo_head_word_still_passes(self):
        video = self._video("Member Videos/2025-12-29 Necter Life/v.mp4",
                            [{"isin": "INE000000007", "symbol": "NECLIFE",
                              "name": "Nectar Lifesciences Ltd", "method": "token_prefix",
                              "score": 0.88, "segment": "necter life"}])
        ok, note = pilot._check_company(video)
        self.assertTrue(ok, note)
        self.assertIn("typo", note)

    def test_unrelated_company_fails(self):
        video = self._video("Member Videos/2026-03-07 Steel Cast/v.mp4",
                            [{"isin": "INE000000001", "symbol": "FKDUR",
                              "name": "Fake Durable Ltd", "method": "fuzzy_name",
                              "score": 0.9, "segment": "steel cast"}])
        self.assertFalse(pilot._check_company(video)[0])

    def test_isin_must_resolve_to_the_same_name(self):
        video = self._video("Member Videos/2026-03-07 Fake Durable/v.mp4",
                            [{"isin": "INE000000001", "symbol": "FKDUR",
                              "name": "Someone Else Ltd", "method": "exact_name"}])
        ok, note = pilot._check_isin(video, self.company_rows)
        self.assertFalse(ok)
        self.assertIn("belongs to", note)

    def test_date_mismatch_is_caught(self):
        video = self._video("Member Videos/2026-03-07 Fake Durable/v.mp4", [],
                            published_at="2026-03-09")
        self.assertFalse(pilot._check_date(video)[0])

    def test_missing_frame_file_is_caught(self):
        ok, note = pilot._check_frame({"frame_path": "frames/x/f_00000.jpg", "frame_no": 0},
                                      Path(tempfile.gettempdir()) / "no_such_dir")
        self.assertFalse(ok)
        self.assertIn("missing", note)

    def test_full_hand_check_tally(self):
        tmp = _scratch("tally")
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        (tmp / "frames" / "v1").mkdir(parents=True)
        (tmp / "frames" / "v1" / "f_00000.jpg").write_bytes(b"x" * 2000)
        video = self._video("Member Videos/2026-03-07 Fake Durable/v.mp4",
                            [{"isin": "INE000000001", "symbol": "FKDUR",
                              "name": "Fake Durable Ltd", "method": "exact_name",
                              "score": 1.0, "segment": "fake durable"}])
        screens = [{"video_id": "v1", "screen_no": 1, "t_start": 0.0, "t_end": 5.0,
                    "frame_no": 0, "frame_path": "frames/v1/f_00000.jpg",
                    "speaker": None, "segment_label": "gdoc #1", "screen_type": "gdoc",
                    "nulls_json": json.dumps({"speaker": pilot.SPEAKER_NULL_REASON})}]
        rows, tally = pilot.hand_check([video], screens, self.company_rows, tmp)
        self.assertEqual(len(rows), 1)
        self.assertTrue(all(ok for ok, _ in rows[0]["checks"].values()),
                        {k: v for k, v in rows[0]["checks"].items() if not v[0]})
        self.assertEqual(tally["frame"], [1, 1])


class EndToEndTests(unittest.TestCase):
    def test_build_db_audit_and_null_reasons(self):
        with _scratch_ctx("e2e") as tmp:
            tmp = Path(tmp)
            companies = tmp / "companies.db"
            con = sqlite3.connect(companies)
            con.execute("CREATE TABLE master_companies(isin TEXT, nse_symbol TEXT, "
                        "company_name TEXT, bse_code TEXT)")
            con.execute("INSERT INTO master_companies VALUES (?,?,?,?)",
                        ("INE000000001", "FKDUR", "Fake Durable Ltd", "543456"))
            con.commit()
            con.close()

            root = tmp / "extracted"
            folder = root / "Current Premium Users" / "Member Videos" / "2026-03-07 Fake Durable"
            folder.mkdir(parents=True)
            (folder / "Fake Durable Ltd.docx").write_bytes(b"pk")
            (folder / "video1.mp4").write_bytes(b"not really a video")

            drive_dir = tmp / "drive"
            drive_dir.mkdir()
            (drive_dir / "_drive_meta_current_premium.json").write_text(json.dumps([{
                "Path": "Member Videos/2026-03-07 Fake Durable/video1.mp4", "IsDir": False,
                "Metadata": {"btime": "07-03-2026 10:00:00 AM"}}]), encoding="utf-8")

            ocr_dir = tmp / "work" / "ocr"
            ocr_dir.mkdir(parents=True)
            frames_dir = tmp / "work" / "frames" / "abc123"
            frames_dir.mkdir(parents=True)
            for frame_no in (0, 6):
                (frames_dir / f"f_{frame_no:05d}.jpg").write_bytes(b"\xff" * 2000)
            payload = {
                "video": {"video_id": "abc123", "rel_path":
                          "Current Premium Users/Member Videos/2026-03-07 Fake Durable/video1.mp4",
                          "source_path": "x", "duration_s": 60.0, "frames_extracted": 12,
                          "frames_kept": 2, "ocr_seconds": 8.0,
                          "frames_dir": "frames/abc123"},
                "screens": [
                    {"t": 0.0, "frame_no": 0, "thumb_diff": None, "scores": [0.95] * 10,
                     "lines": ["docs.google.com", "Fake Durable Ltd",
                               "Revenue from operations 1,204.6", "EBITDA margin expanded 240 bps",
                               "Order book at an all time high", "Capex plan for FY27",
                               "Debt reduction target", "Volume growth 18 percent",
                               "Guidance unchanged", "Q and A follows"]},
                    {"t": 30.0, "frame_no": 6, "thumb_diff": 12.0, "scores": [0.42],
                     "lines": ["TradingView"]},
                ],
            }
            (ocr_dir / "abc123.json").write_text(json.dumps(payload), encoding="utf-8")

            db_path = tmp / "pilot.db"
            videos, screens, docs, company_rows, line_index = pilot.build_db(
                db_path, ocr_dir, drive_dir, companies, root, workdir=tmp / "work")
            audit = pilot.write_audit(tmp / "AUDIT.md", videos, screens, docs, db_path,
                                      tmp / "work", company_rows, line_rows=line_index)

            self.assertEqual(len(videos), 1)
            self.assertEqual(videos[0]["company_isin"], "INE000000001")
            self.assertEqual(videos[0]["published_at"], "2026-03-07")
            self.assertEqual(videos[0]["channel"], "member_video")

            stored = sqlite3.connect(db_path)
            screen_rows = stored.execute(
                "SELECT screen_type, linked_doc_path, quality_grade, text_clean, nulls_json, "
                "frame_no, frame_path, frame_exists, segment_label, speaker FROM screen "
                "ORDER BY screen_no").fetchall()
            line_rows = stored.execute(
                "SELECT frame_no, COUNT(*) FROM ocr_line GROUP BY frame_no ORDER BY frame_no"
            ).fetchall()
            stored.close()
            self.assertEqual(screen_rows[0][0], "gdoc")
            self.assertTrue(screen_rows[0][1].endswith("Fake Durable Ltd.docx"))
            self.assertEqual(screen_rows[0][2], "A")
            self.assertNotIn("docs.google.com", screen_rows[0][3])
            self.assertEqual(screen_rows[1][0], "chart")
            self.assertIsNone(screen_rows[1][1])
            for row in screen_rows:
                nulls = json.loads(row[4])
                if row[1] is None:
                    self.assertIn("linked_doc_path", nulls)
                self.assertIn("speaker", nulls)
                self.assertIsNone(row[9])
            # frame provenance: every line points at its screen's frame, and the jpg is there
            self.assertEqual([row[5] for row in screen_rows], [0, 6])
            self.assertTrue(all(row[7] == 1 for row in screen_rows))
            self.assertEqual(screen_rows[0][5], 0)
            self.assertTrue(screen_rows[0][6].endswith("f_00000.jpg"))
            self.assertEqual(screen_rows[0][8], "gdoc #1")
            self.assertEqual([row[0] for row in line_rows], [0, 6])
            self.assertEqual(sum(row[1] for row in line_rows), len(line_index))
            text = audit.read_text(encoding="utf-8")
            for section in ("Label fill rates", "15 random screens",
                            "Per-video check: company + date", "Hand check: 2 screens",
                            "line.frame_on_disk", "Timing and throughput",
                            "frames/s OCR'd"):
                self.assertIn(section, text)
            self.assertNotIn("no reason recorded", text)
            self.assertIn("| company | 2 | 2 | 100% |", text)
            self.assertIn("| frame | 2 | 2 | 100% |", text)


if __name__ == "__main__":
    unittest.main()
