"""Offline tests for the input-cost series fetchers (WPI items, news prices, IMD rainfall).

Every parser is exercised against a fixture in
``reality_engine/tests/fixtures/extra_series/``. No test makes a network call,
opens a live database, or writes outside the workspace ``.tmp`` directory.

    python -m unittest reality_engine.tests.test_extra_series
"""

import csv
import io
import os
import unittest
import uuid
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from unittest.mock import patch

from reality_engine.scripts import extract_news_prices as news
from reality_engine.scripts import fetch_imd_rainfall as imd
from reality_engine.scripts import fetch_wpi_items as wpi
from reality_engine.scripts.series_common import anchors, html_rows, num, write_csv

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "extra_series"
#: ``tempfile.TemporaryDirectory`` is not used: the DSH sandbox grants the write
#: but denies the recursive delete, so its finaliser raises on Windows. Names
#: are unique instead of deleted, so a re-run never reads stale rows.
TMP_ROOT = Path.cwd() / ".tmp" / "extra_series_tests"


def _tmpdir(name: str) -> Path:
    d = TMP_ROOT / f"{name}_{uuid.uuid4().hex[:8]}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


class _NoNetwork:
    """A fetcher that fails loudly: proves a test never reaches the network."""

    def __init__(self, payloads=None):
        self.payloads = payloads or {}
        self.calls = []

    def __call__(self, url, timeout=90, referer=""):
        self.calls.append(url)
        if url not in self.payloads:
            raise RuntimeError(f"unexpected network call: {url}")
        return self.payloads[url]


# ---------------------------------------------------------------------------
# WPI item indices
# ---------------------------------------------------------------------------
class TestWpiIdentifiers(unittest.TestCase):
    ITEMS = {
        "Hot rolled coils": "wpi_hrc",
        "HR coils": "wpi_hrc",
        "HRC": "wpi_hrc",
        "Cold rolled coils": "wpi_cold_rolled",
        "Iron & steel": "wpi_steel_group",
        "Pig iron": "wpi_pig_iron",
        "Sponge iron": "wpi_sponge_iron",
        "Coking coal": "wpi_coking_coal",
        "Non-coking coal": "wpi_non_coking_coal",
        "Coal": "wpi_coal_group",
        "Pet coke": "wpi_pet_coke",
        "Soda ash": "wpi_soda_ash",
        "Caustic soda": "wpi_caustic_soda",
        "Ammonia": "wpi_ammonia",
        "Sulphuric acid": "wpi_sulphuric_acid",
        "Urea": "wpi_urea",
        "DAP": "wpi_dap",
        "NPK": "wpi_npk",
        "Cement, lime & plaster": "wpi_cement",
        "Aluminium": "wpi_aluminium",
        "Copper": "wpi_copper",
        "Zinc": "wpi_zinc",
        "Lead": "wpi_lead",
        "Nickel": "wpi_nickel",
        "Cotton yarn": "wpi_cotton_yarn",
        "Plastics": "wpi_plastics",
    }

    def test_every_named_input_maps_to_one_series(self):
        for label, code in self.ITEMS.items():
            self.assertEqual(wpi.match_item(label), code, label)

    def test_items_the_bank_does_not_name_are_unmatched(self):
        for label in ("Fibre glass", "Marble", "Tea", "", "   "):
            self.assertIsNone(wpi.match_item(label), label)

    def test_month_forms(self):
        self.assertEqual(wpi.month_in("Press Release, October 2026"), "2026-10")
        self.assertEqual(wpi.month_in("wpi_2026-10.pdf"), "2026-10")
        self.assertEqual(wpi.month_in("release 14.10.2026"), "2026-10")
        self.assertEqual(wpi.month_in("nothing here"), None)

    def test_release_date_is_the_printed_date_then_the_documented_14th(self):
        self.assertEqual(wpi.release_date("PRESS RELEASE DATED 14th OCTOBER, 2026", "", "2026-09"),
                         ("2026-10-14", 1.0))
        self.assertEqual(wpi.release_date("", "https://x/wpi_14.10.2026.pdf", "2026-09"),
                         ("2026-10-14", 1.0))
        self.assertEqual(wpi.release_date("no date printed", "", "2026-09"),
                         ("2026-10-14", 0.8))
        self.assertEqual(wpi.release_date("", "", "2026-12"), ("2027-01-14", 0.8))


class TestWpiRelease(unittest.TestCase):
    def test_text_release_yields_item_level_rows(self):
        parsed = wpi.parse_release(_fixture("wpi_press_release_2026_09.txt"),
                                   "https://eaindustry.nic.in/wpi_2026-09.pdf")
        self.assertEqual(parsed["status"], "ok", parsed.get("reason"))
        rows = {r["series_code"]: r for r in parsed["rows"]}
        self.assertIn("wpi_hrc", rows)
        self.assertIn("wpi_steel_group", rows)
        self.assertAlmostEqual(rows["wpi_hrc"]["value"], 138.6)
        self.assertAlmostEqual(rows["wpi_hrc"]["weight"], 3.1187)
        self.assertEqual(rows["wpi_hrc"]["date"], "2026-09-30")   # period end
        self.assertEqual(rows["wpi_hrc"]["known_at"], "2026-10-14")  # release date
        self.assertEqual(rows["wpi_hrc"]["pit_conf"], 1.0)
        self.assertEqual(rows["wpi_hrc"]["unit"], wpi.UNIT)
        self.assertAlmostEqual(rows["wpi_coal_group"]["value"], 143.8)
        self.assertAlmostEqual(rows["wpi_cement"]["value"], 131.7)
        self.assertAlmostEqual(rows["wpi_aluminium"]["value"], 127.0)
        # One row per code, even though the family matches a group and its items.
        codes = [r["series_code"] for r in parsed["rows"]]
        self.assertEqual(len(codes), len(set(codes)))
        self.assertEqual(parsed["info"]["reference_month"], "2026-09")
        self.assertGreaterEqual(parsed["info"]["unmatched"], 2)   # Fibre glass, Marble
        self.assertEqual(set(parsed["rows"][0]), set(wpi.CSV_COLUMNS))

    def test_html_release_uses_the_index_column_that_names_the_month(self):
        parsed = wpi.parse_release(_fixture("wpi_press_release_2026_09.html"),
                                   "https://eaindustry.nic.in/pr_sep26.html")
        self.assertEqual(parsed["status"], "ok", parsed.get("reason"))
        rows = {r["series_code"]: r for r in parsed["rows"]}
        self.assertAlmostEqual(rows["wpi_hrc"]["value"], 138.6)     # Sep column, not Aug
        self.assertAlmostEqual(rows["wpi_steel_group"]["value"], 141.3)
        self.assertEqual(rows["wpi_hrc"]["date"], "2026-09-30")
        self.assertEqual(len(rows), 11)

    def test_layout_drift_refuses_instead_of_guessing_a_column(self):
        parsed = wpi.parse_release(b"<html><body>Site under maintenance</body></html>", "u")
        self.assertEqual(parsed["status"], "failed")
        headerless = b"Hot rolled coils  138.6  136.2\nUrea  98.7  99.2\n"
        self.assertEqual(wpi.parse_release(headerless, "u")["status"], "refused")

    def test_without_a_reference_month_there_is_no_row_and_no_today_date(self):
        body = ("Item   Weight   Index\nHot rolled coils   3.1187   138.6\n"
                "Urea   1.5678   98.7\n")
        parsed = wpi.parse_release(body, "https://x/release.pdf")
        self.assertEqual(parsed["status"], "refused")
        self.assertEqual(parsed["rows"], [])

    def test_two_vintages_of_one_month_stay_two_rows(self):
        rows = [
            {"series_code": "wpi_hrc", "date": "2026-03-31", "value": 138.6,
             "unit": wpi.UNIT, "weight": 3.1, "known_at": "2026-04-14",
             "pit_conf": 1.0, "source": wpi.SOURCE, "source_url": "u"},
            {"series_code": "wpi_hrc", "date": "2026-03-31", "value": 138.9,
             "unit": wpi.UNIT, "weight": 3.1, "known_at": "2026-05-14",
             "pit_conf": 1.0, "source": wpi.SOURCE, "source_url": "u2"},
        ]
        out = _tmpdir("wpi_vintages")
        self.assertEqual(write_csv(out / "wpi.csv", wpi.CSV_COLUMNS, rows), 2)
        with (out / "wpi.csv").open(newline="") as f:
            got = list(csv.DictReader(f))
        self.assertEqual([r["known_at"] for r in got], ["2026-04-14", "2026-05-14"])


class TestWpiDiscovery(unittest.TestCase):
    PAGE = (
        '<a href="/Press_Release_2026-10.pdf">WPI Press Release October 2026</a>'
        '<a href="https://eaindustry.nic.in/Excel.xls">Index numbers</a>'
        '<a href="/wpi_14.09.2026.pdf">Press Release</a>'
        '<a href="/contact.html">Contact us</a>'
        '<a href="/press-releases.asp">Archive of press releases</a>'
    )

    def test_release_links_carry_a_readable_month(self):
        got = wpi.discover_release_links(
            [("https://eaindustry.nic.in/", self.PAGE)])
        self.assertEqual(got, {
            "2026-09": "https://eaindustry.nic.in/wpi_14.09.2026.pdf",
            "2026-10": "https://eaindustry.nic.in/Press_Release_2026-10.pdf",
        })

    def test_archive_page_is_followed(self):
        links = wpi.archive_links(self.PAGE, "https://eaindustry.nic.in/")
        self.assertEqual(links, ["https://eaindustry.nic.in/press-releases.asp"])

    def test_plan_and_dry_run_touch_nothing(self):
        plan = wpi.plan(date(2019, 1, 1), date(2026, 10, 31))
        self.assertEqual(plan["months"], 94)
        self.assertEqual(plan["requests_p50"], 94 + wpi.MAX_ARCHIVE_PAGES + 1)
        out = TMP_ROOT / "wpi_dry_absent"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = wpi.main(["--dry-run", "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("requests_p50", buf.getvalue())
        self.assertIn("dry-run: no request made", buf.getvalue())
        self.assertFalse(out.exists())


# ---------------------------------------------------------------------------
# Weekly news price points
# ---------------------------------------------------------------------------
class TestNewsFeeds(unittest.TestCase):
    def test_rss_items_and_publication_time(self):
        parsed = news.parse_rss(_fixture("news_rss_markets.xml"))
        self.assertEqual(parsed["status"], "ok")
        self.assertEqual(len(parsed["items"]), 3)
        first = parsed["items"][0]
        self.assertEqual(first["title"], "Domestic HRC prices hold at Rs 52,000 a tonne")
        # 14:30 UTC is 20:00 IST; known_at is stored in IST.
        self.assertEqual(news.ist_iso(first["published"]), "2026-10-28T20:00:00+05:30")
        self.assertEqual(news.ist_iso(None), "")          # never "now"

    def test_a_broken_feed_is_reported_not_raised(self):
        parsed = news.parse_rss(b"<!DOCTYPE html><html>blocked</html>")
        self.assertEqual(parsed["status"], "failed")
        self.assertEqual(parsed["items"], [])

    def test_rss_stage_keeps_only_items_that_name_a_series(self):
        fake = _NoNetwork({url: _fixture("news_rss_markets.xml") for _o, url in news.FEEDS})
        stats = {"requests": 0, "feeds": [], "sitemaps": [], "articles_failed": [],
                 "articles_no_known_at": [], "articles_parsed": 0}
        candidates = news.rss_articles(news.FEEDS, stats, article_budget=100, fetcher=fake)
        self.assertEqual(stats["requests"], len(news.FEEDS))
        self.assertEqual(len(candidates), 2 * len(news.FEEDS))   # HRC + BDI item per feed
        self.assertTrue(all("sensex" not in c["url"] for c in candidates))

    def test_robots_sitemaps_and_weekly_pick(self):
        robots = "User-agent: *\nDisallow: /search\nSitemap: https://x/sitemap-index.xml\n"
        self.assertEqual(news.robots_sitemaps(robots), ["https://x/sitemap-index.xml"])
        index = (b'<?xml version="1.0"?><sitemapindex>'
                 b'<sitemap><loc>https://x/sitemap/2026-10-02.xml</loc>'
                 b'<lastmod>2026-10-02</lastmod></sitemap>'
                 b'<sitemap><loc>https://x/sitemap/2026-10-09.xml</loc>'
                 b'<lastmod>2026-10-09</lastmod></sitemap></sitemapindex>')
        parsed = news.parse_sitemap(index)
        self.assertEqual(parsed["kind"], "sitemapindex")
        days = [date(2026, 10, 6), date(2026, 10, 9)]        # Tue, Fri
        self.assertEqual(news.pick_weekly(parsed["entries"], days),
                         ["https://x/sitemap/2026-10-02.xml",
                          "https://x/sitemap/2026-10-09.xml"])
        self.assertEqual(news.weekly_days(date(2026, 10, 5), date(2026, 10, 19)),
                         [date(2026, 10, 9), date(2026, 10, 16)])


class TestNewsExtraction(unittest.TestCase):
    def test_article_meta_and_body(self):
        page = news.article_text(_fixture("news_article_hrc.html").decode())
        self.assertEqual(page["published"], "2026-10-28T20:00:00+05:30")
        self.assertEqual(page["title"], "Domestic HRC prices hold at Rs 52,000 a tonne")
        self.assertIn("hot rolled coil", page["body"])

    def test_hrc_and_bdi_points_with_quotes_of_at_most_15_words(self):
        page = news.article_text(_fixture("news_article_hrc.html").decode())
        text = " ".join((page["title"], page["description"], page["body"]))
        rows, residue = news.extract_points(text, "https://x/a.html", "economictimes",
                                            page["published"], "2026-10-28")
        self.assertEqual(residue, [])
        by_code = {}
        for row in rows:
            self.assertEqual(set(row), set(news.CSV_COLUMNS))
            self.assertLessEqual(len(row["quote"].split()), 15, row["quote"])
            by_code.setdefault(row["series_code"], []).append(row)
        self.assertEqual([r["value"] for r in by_code["hrc_india"]], [52000.0, 50500.0])
        self.assertEqual(by_code["hrc_india"][0]["price_date"], "2026-10-28")
        self.assertEqual(by_code["hrc_india"][0]["price_date_basis"], "stated")
        self.assertEqual(by_code["hrc_india"][0]["known_at"], "2026-10-28T20:00:00+05:30")
        self.assertEqual(by_code["baltic_dry_index"][0]["value"], 1850.0)
        self.assertEqual(by_code["baltic_dry_index"][0]["unit"], "index_points")
        # The quote carries the number, and nothing else of the article survives.
        self.assertIn("52,000", by_code["hrc_india"][0]["quote"])

    def test_baltic_percentage_is_never_the_level(self):
        rows, _residue = news.extract_points(
            "The Baltic Dry Index rose 1.2% to 1,850 points on Wednesday.",
            "u", "livemint", "2026-10-28T18:30:00+05:30", "2026-10-28")
        self.assertEqual([r["value"] for r in rows], [1850.0])
        self.assertEqual(rows[0]["price_date_basis"], "pubdate")

    def test_a_change_without_a_level_is_residue_not_a_row(self):
        rows, residue = news.extract_points(
            "HRC prices rose by Rs 500/t this week on restocking demand.",
            "u", "business-standard", "2026-10-28T18:30:00+05:30", "2026-10-28")
        self.assertEqual(rows, [])
        self.assertEqual(len(residue), 1)

    def test_zero_rows_when_the_sentence_names_no_series(self):
        rows, residue = news.extract_points("Sensex closed 210 points higher on Wednesday.",
                                            "u", "moneycontrol", "2026-10-28T18:30:00+05:30",
                                            "2026-10-28")
        self.assertEqual((rows, residue), ([], []))

    def test_price_date_forms(self):
        self.assertEqual(news.price_date_in("on 28 October 2026 prices", "2026-10-30"),
                         ("2026-10-28", "stated"))
        self.assertEqual(news.price_date_in("on October 28, 2026 prices", "2026-10-30"),
                         ("2026-10-28", "stated"))
        self.assertEqual(news.price_date_in("on Wednesday", "2026-10-30"),
                         ("2026-10-30", "pubdate"))

    def test_dedupe_keeps_the_earliest_known_at_and_both_disagreeing_levels(self):
        base = {"unit": "inr_per_tonne", "source_url": "u", "outlet": "et",
                "price_date_basis": "stated", "pit_conf": 1.0, "extractor": "regex"}
        rows = [
            {**base, "series_code": "hrc_india", "price_date": "2026-10-28",
             "value": 52000.0, "known_at": "2026-10-28T20:00:00+05:30", "quote": "a"},
            {**base, "series_code": "hrc_india", "price_date": "2026-10-28",
             "value": 52000.0, "known_at": "2026-10-28T18:00:00+05:30", "quote": "b"},
            {**base, "series_code": "hrc_india", "price_date": "2026-10-28",
             "value": 51800.0, "known_at": "2026-10-28T21:00:00+05:30", "quote": "c"},
        ]
        got = news.dedupe(rows)
        self.assertEqual(len(got), 2)
        self.assertEqual([r["value"] for r in got], [51800.0, 52000.0])
        self.assertEqual(got[1]["quote"], "b")               # earliest first-known

    def test_harvest_refuses_a_page_without_a_publication_time(self):
        bare = b"<html><head><title>HRC prices</title></head><body>" \
               b"<p>HRC prices were quoted at Rs 52,000 per tonne on Wednesday.</p></body></html>"
        fake = _NoNetwork({"https://x/bare.html": bare})
        stats = {"requests": 0, "feeds": [], "sitemaps": [], "articles_failed": [],
                 "articles_no_known_at": [], "articles_parsed": 0}
        rows, stats = news.harvest(
            [{"outlet": "economictimes", "url": "https://x/bare.html", "published": "",
              "title": "", "text": ""}], stats, 10, fetcher=fake)
        self.assertEqual(rows, [])
        self.assertEqual(stats["articles_no_known_at"], ["https://x/bare.html"])

    def test_harvest_reads_the_article_and_keeps_only_the_quote(self):
        fake = _NoNetwork({"https://x/a.html": _fixture("news_article_bdi.html")})
        stats = {"requests": 0, "feeds": [], "sitemaps": [], "articles_failed": [],
                 "articles_no_known_at": [], "articles_parsed": 0}
        rows, _stats = news.harvest(
            [{"outlet": "economictimes", "url": "https://x/a.html", "published": "",
              "title": "", "text": ""}], stats, 10, fetcher=fake)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["series_code"], "baltic_dry_index")
        self.assertLessEqual(len(rows[0]["quote"].split()), 15)
        self.assertNotIn("shipbrokers", rows[0]["quote"])

    def test_sitemap_walk_keeps_only_article_urls_that_name_a_series(self):
        robots = b"Sitemap: https://bs.example/sitemap-index.xml\n"
        index = (b'<?xml version="1.0"?><sitemapindex>'
                 b'<sitemap><loc>https://bs.example/sitemap/2026-10-09.xml</loc>'
                 b'<lastmod>2026-10-09</lastmod></sitemap></sitemapindex>')
        child = (b'<?xml version="1.0"?><urlset>'
                 b'<url><loc>https://bs.example/markets/hrc-price-rises.html</loc>'
                 b'<lastmod>2026-10-09</lastmod></url>'
                 b'<url><loc>https://bs.example/markets/sensex-close.html</loc>'
                 b'<lastmod>2026-10-09</lastmod></url></urlset>')
        fake = _NoNetwork({"https://bs.example/robots.txt": robots,
                           "https://bs.example/sitemap-index.xml": index,
                           "https://bs.example/sitemap/2026-10-09.xml": child})
        stats = {"requests": 0, "feeds": [], "sitemaps": [], "articles_failed": [],
                 "articles_no_known_at": [], "articles_parsed": 0}
        found = news.sitemap_articles({"bs": "https://bs.example"},
                                      date(2026, 10, 5), date(2026, 10, 11),
                                      stats, fetcher=fake)
        self.assertEqual([c["url"] for c in found],
                         ["https://bs.example/markets/hrc-price-rises.html"])
        self.assertEqual(found[0]["published"], "2026-10-09")
        self.assertEqual(stats["requests"], 3)               # robots + index + one child

    def test_plan_and_dry_run_touch_nothing(self):
        plan = news.plan(date(2026, 1, 1), date(2026, 12, 31))
        self.assertEqual(plan["weeks_sampled"], 52)
        self.assertEqual(plan["rss_feeds"], len(news.FEEDS))
        self.assertGreater(plan["requests_p50"], plan["rss_feeds"])
        out = TMP_ROOT / "news_dry_absent"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = news.main(["--dry-run", "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("requests_p50", buf.getvalue())
        self.assertIn("dry-run: no request made", buf.getvalue())
        self.assertFalse(out.exists())

    def test_deepseek_residue_is_skipped_without_a_key(self):
        with patch.dict(os.environ, {"OPENCODE_GO_API_KEY": ""}, clear=False):
            buf = io.StringIO()
            with redirect_stdout(buf), patch.object(news, "rss_articles", return_value=[]), \
                    patch.object(news, "write_csv", return_value=0):
                news.main(["--deepseek", "--rss-only", "--out", str(TMP_ROOT / "skip_absent")])
        self.assertIn("skipped (OPENCODE_GO_API_KEY not set)", buf.getvalue())


# ---------------------------------------------------------------------------
# IMD weekly rainfall
# ---------------------------------------------------------------------------
class TestImdDates(unittest.TestCase):
    def test_week_end_forms(self):
        self.assertEqual(imd.week_end_in("Week ending 30.09.2026"), "2026-09-30")
        self.assertEqual(imd.week_end_in("week ending 30 September, 2026"), "2026-09-30")
        self.assertIsNone(imd.week_end_in("no date here"))

    def test_known_at_is_the_printed_issue_date_then_the_thursday(self):
        self.assertEqual(imd.bulletin_date("Dated 01 October 2026", "2026-09-30"),
                         ("2026-10-01", 1.0))
        self.assertEqual(imd.bulletin_date("", "2026-09-30"), ("2026-10-01", 0.85))
        self.assertEqual(imd.bulletin_date("", ""), ("", 0.0))

    def test_monsoon_weeks_are_wednesdays_inside_june_to_september(self):
        weeks = imd.monsoon_weeks(date(2019, 6, 1), date(2019, 9, 30))
        self.assertEqual(len(weeks), 17)
        self.assertTrue(all(w.weekday() == 2 for w in weeks))
        self.assertTrue(all(w.month in imd.MONSOON_MONTHS for w in weeks))
        self.assertEqual(weeks[0], date(2019, 6, 5))
        self.assertEqual(weeks[-1], date(2019, 9, 25))


class TestImdBulletin(unittest.TestCase):
    def test_html_bulletin_yields_one_row_per_state(self):
        parsed = imd.parse_bulletin(_fixture("imd_weekly_rainfall_2026_39.html"),
                                    "https://mausam.imd.gov.in/w39.html")
        self.assertEqual(parsed["status"], "ok", parsed.get("reason"))
        states = {r["state"]: r for r in parsed["rows"]}
        self.assertEqual(len(states), 10)
        self.assertAlmostEqual(states["Kerala"]["departure_pct"], -34.9)
        self.assertAlmostEqual(states["Punjab"]["departure_pct"], -77.5)
        self.assertAlmostEqual(states["Karnataka"]["departure_pct"], 33.4)
        self.assertAlmostEqual(states["All India"]["departure_pct"], -5.9)
        self.assertEqual(states["Kerala"]["week_end"], "2026-09-30")
        self.assertEqual(states["Kerala"]["known_at"], "2026-10-01")
        self.assertEqual(states["Kerala"]["pit_conf"], 1.0)
        self.assertEqual(set(states["Kerala"]), set(imd.CSV_COLUMNS))

    def test_pdf_text_bulletin_uses_the_last_number_of_the_line(self):
        parsed = imd.parse_bulletin(_fixture("imd_weekly_rainfall_2026_38.txt"),
                                    "https://mausam.imd.gov.in/w38.pdf")
        self.assertEqual(parsed["status"], "ok", parsed.get("reason"))
        states = {r["state"]: r for r in parsed["rows"]}
        self.assertEqual(len(states), 9)
        self.assertAlmostEqual(states["Punjab"]["departure_pct"], -77.5)
        self.assertEqual(states["Punjab"]["week_end"], "2026-09-23")
        self.assertEqual(states["Punjab"]["known_at"], "2026-09-24")
        self.assertEqual(parsed["info"]["format"], "text")

    def test_layout_drift_and_thin_tables_are_refused(self):
        self.assertEqual(
            imd.parse_bulletin(b"<html><body>maintenance</body></html>", "u")["status"],
            "failed")
        thin = ("<table><tr><th>State/UT</th><th>Departure (%)</th></tr>"
                "<tr><td>Kerala</td><td>-34.9</td></tr>"
                "<tr><td>Punjab</td><td>-77.5</td></tr></table>")
        parsed = imd.parse_bulletin(thin, "u", fallback_week_end="2026-09-30")
        self.assertEqual(parsed["status"], "refused")
        self.assertEqual(parsed["rows"], [])

    def test_without_a_week_end_there_is_no_row(self):
        body = ("<table><tr><th>State/UT</th><th>Departure (%)</th></tr>"
                + "".join(f"<tr><td>State {i}</td><td>{i}</td></tr>" for i in range(6))
                + "</table>")
        parsed = imd.parse_bulletin(body, "u")
        self.assertEqual(parsed["status"], "refused")


class TestImdDiscovery(unittest.TestCase):
    PAGE = (
        '<a href="/rainfall/weekly_rainfall_30.09.2026.pdf">Weekly rainfall bulletin</a>'
        '<a href="https://mausam.imd.gov.in/rainfall/w39_2026.html">Rainfall week 39</a>'
        '<a href="/rainfall/archive.html">Rainfall archive</a>'
        '<a href="/press/notice.html">Office notice</a>'
    )

    def test_bulletin_links_carry_the_week_end(self):
        got = imd.discover_bulletins([("https://mausam.imd.gov.in/", self.PAGE)])
        self.assertEqual(got, {
            "2026-09-30": "https://mausam.imd.gov.in/rainfall/weekly_rainfall_30.09.2026.pdf",
        })

    def test_archive_pages_are_followed(self):
        links = imd.archive_pages(self.PAGE, "https://mausam.imd.gov.in/")
        self.assertEqual(links, ["https://mausam.imd.gov.in/rainfall/archive.html"])

    def test_plan_counts_one_request_per_monsoon_week(self):
        plan = imd.plan(date(2019, 6, 1), date(2019, 9, 30))
        self.assertEqual(plan["monsoon_weeks"], 17)
        self.assertEqual(plan["requests_p50"], 17 + len(imd.LANDING_URLS) + imd.MAX_ARCHIVE_PAGES)
        out = TMP_ROOT / "imd_dry_absent"
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc = imd.main(["--dry-run", "--out", str(out)])
        self.assertEqual(rc, 0)
        self.assertIn("monsoon_weeks", buf.getvalue())
        self.assertIn("dry-run: no request made", buf.getvalue())
        self.assertFalse(out.exists())


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
class TestSeriesCommon(unittest.TestCase):
    def test_num_accepts_the_pdf_minus_and_thousands(self):
        self.assertEqual(num("\u221245.5"), -45.5)     # U+2212 minus from a PDF
        self.assertEqual(num("-45.5%"), -45.5)
        self.assertEqual(num("1,234.5"), 1234.5)
        self.assertIsNone(num("n.a."))
        self.assertIsNone(num(""))

    def test_anchors_resolve_relative_hrefs(self):
        got = anchors('<a href="/a.pdf">A</a><a href="#top">x</a><a href="https://h/b">B</a>',
                      "https://h/")
        self.assertEqual(got, [("https://h/a.pdf", "A"), ("https://h/b", "B")])

    def test_html_rows_keep_headers(self):
        rows = html_rows("<table><tr><th>Item</th><th>Weight</th></tr>"
                         "<tr><td>Urea</td><td>1.5</td></tr></table>")
        self.assertEqual(rows, [["Item", "Weight"], ["Urea", "1.5"]])


if __name__ == "__main__":
    unittest.main()
