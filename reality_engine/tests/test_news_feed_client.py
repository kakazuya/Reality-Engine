"""Tests for news_feed_client: RSS/Atom parse, normalize gates, symbol tagging,
raw_documents + intelligence_fts persistence.

Zero network: every fetch path uses an injected fake fetcher. Temp DB via
DatabaseManager(tempfile). The live DB is never touched.
"""
import tempfile
import unittest
from pathlib import Path

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion import news_feed_client as nfc


RSS_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Mint Markets</title>
  <item>
    <title>Sensex ends 400 points higher as banks rally</title>
    <link>https://www.livemint.com/market/stock-market-news/sensex-ends-higher</link>
    <pubDate>Sat, 19 Sep 2026 17:50:01 +0530</pubDate>
    <description>&lt;p&gt;Banking heavyweights &lt;b&gt;led&lt;/b&gt; the advance.&lt;/p&gt;</description>
  </item>
  <item>
    <title>Reliance Industries board clears capex plan</title>
    <link>https://www.livemint.com/companies/reliance-capex</link>
    <pubDate>2026-09-18T12:45:56Z</pubDate>
    <description>Reliance Industries (RELIANCE) approved a new capital expenditure plan.</description>
  </item>
  <item>
    <title>Item with an unusable timestamp</title>
    <link>https://www.livemint.com/market/undated</link>
    <pubDate>not-a-date</pubDate>
    <description>No parseable date here.</description>
  </item>
</channel></rss>
"""

RSS_DUP_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>TCS wins large deal</title>
    <link>https://www.business-standard.com/markets/tcs-deal</link>
    <pubDate>Sat, 19 Sep 2026 09:05:00 +0530</pubDate>
    <description>TCS announced a multi-year deal.</description>
  </item>
  <item>
    <title>TCS wins large deal</title>
    <link>https://www.business-standard.com/markets/tcs-deal</link>
    <pubDate>Sat, 19 Sep 2026 09:05:00 +0530</pubDate>
    <description>TCS announced a multi-year deal.</description>
  </item>
</channel></rss>
"""

RSS_PERSIST_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <item>
    <title>TCS wins large deal in Europe</title>
    <link>https://www.livemint.com/companies/tcs-deal-europe</link>
    <pubDate>Sat, 19 Sep 2026 11:20:00 +0530</pubDate>
    <description>Tata Consultancy Services signed a multi-year deal.</description>
  </item>
  <item>
    <title>Sensex ends higher on bank rally</title>
    <link>https://www.livemint.com/market/sensex-closes-higher</link>
    <pubDate>2026-09-18T12:45:56Z</pubDate>
    <description>Banking stocks led the advance on Friday.</description>
  </item>
</channel></rss>
"""

ATOM_FIXTURE = """<?xml version="1.0" encoding="utf-8"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <title>NDTV Profit</title>
  <entry>
    <title>Infosys raises FY27 guidance</title>
    <link rel="alternate" type="text/html" href="https://www.ndtvprofit.com/markets/infosys-guidance"/>
    <updated>2026-09-19T08:15:00+05:30</updated>
    <summary>Infosys raised its revenue guidance for the year.</summary>
  </entry>
</feed>
"""

SYMBOL_MAP = {
    "RELIANCE": "INE002A01018",
    "TCS": "INE467B01029",
    "INFY": "INE009A01021",
}

#: Image-layer fixture: media:content (largest wins), media:thumbnail,
#: image enclosure, inline <img>, and an item with no image at all. The MRSS
#: namespace is deliberately declared so the parser has to match on local name.
MEDIA_FIXTURE = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:media="http://search.yahoo.com/mrss/">
<channel>
  <item>
    <title>Nifty sector map: who led the rally</title>
    <link>https://www.business-standard.com/markets/nifty-sector-map</link>
    <pubDate>Sat, 19 Sep 2026 10:00:00 +0530</pubDate>
    <description>Charts from the markets desk.</description>
    <media:content url="https://img.business-standard.com/thumb?w=200" width="200" height="200" type="image/png"/>
    <media:content url="https://img.business-standard.com/charts/nifty.png?width=1200" width="1200" height="800" type="image/png"/>
    <media:thumbnail url="https://img.business-standard.com/fallback.jpg" width="640" height="360"/>
  </item>
  <item>
    <title>Thumbnail-only item</title>
    <link>https://www.business-standard.com/markets/thumb-only</link>
    <pubDate>Sat, 19 Sep 2026 10:05:00 +0530</pubDate>
    <description>No media:content here.</description>
    <media:thumbnail url="https://img.business-standard.com/only-thumb.jpg"/>
  </item>
  <item>
    <title>Enclosure-only item</title>
    <link>https://economictimes.indiatimes.com/markets/enclosure-only</link>
    <pubDate>Sat, 19 Sep 2026 10:10:00 +0530</pubDate>
    <description>Chart arrives as an enclosure.</description>
    <enclosure url="https://img.et.example/charts/dalal-street.png" type="image/png" length="71000"/>
  </item>
  <item>
    <title>Inline image item</title>
    <link>https://www.livemint.com/market/inline-image</link>
    <pubDate>Sat, 19 Sep 2026 10:15:00 +0530</pubDate>
    <description>&lt;img src="https://img.livemint.com/inline/chart?id=7" /&gt;Sensex heatmap.</description>
  </item>
  <item>
    <title>Text-only item</title>
    <link>https://www.livemint.com/market/text-only</link>
    <pubDate>Sat, 19 Sep 2026 10:20:00 +0530</pubDate>
    <description>No artwork in this one.</description>
  </item>
  <item>
    <title>Extensionless CDN path</title>
    <link>https://www.thehindubusinessline.com/markets/extensionless</link>
    <pubDate>Sat, 19 Sep 2026 10:25:00 +0530</pubDate>
    <description>Tracking query must go.</description>
    <media:content url="https://img.thehindubusinessline.com/chart?x=1&amp;y=2" width="600" height="400"/>
  </item>
</channel></rss>
"""

CONTRACT_KEYS = {
    "title", "source_type", "published_date", "fiscal_period", "source_url",
    "creator_or_ministry", "sha256_hash", "local_file_path", "file_size_bytes",
}


def _mk_repo(td):
    mgr = DatabaseManager(db_path=Path(td) / "news.db")
    return Repository(manager=mgr), mgr


def _feed_fetcher(mapping):
    """mapping: url -> body or None. Unknown urls -> None (miss)."""
    def _fetch(url, headers=None, timeout=15):
        return mapping.get(url)
    return _fetch


def _count(conn, table, where="", params=()):
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where:
        sql += f" WHERE {where}"
    return int(conn.execute(sql, params).fetchone()["n"])


class TestFetchFeed(unittest.TestCase):
    def test_rss_items_parsed(self):
        items = nfc.fetch_feed("https://f/rss", fetcher=_feed_fetcher(
            {"https://f/rss": RSS_FIXTURE}))
        self.assertEqual(len(items), 3)
        first = items[0]
        self.assertEqual(
            set(first),
            {"title", "link", "published_raw", "summary", "media_url"})
        self.assertEqual(first["media_url"], "")  # no artwork in this fixture
        self.assertEqual(first["title"], "Sensex ends 400 points higher as banks rally")
        self.assertEqual(first["published_raw"], "Sat, 19 Sep 2026 17:50:01 +0530")
        self.assertIn("<b>", first["summary"])  # raw HTML kept at parse layer

    def test_atom_entries_parsed(self):
        items = nfc.fetch_feed("https://f/atom", fetcher=_feed_fetcher(
            {"https://f/atom": ATOM_FIXTURE}))
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Infosys raises FY27 guidance")
        self.assertEqual(items[0]["link"],
                         "https://www.ndtvprofit.com/markets/infosys-guidance")
        self.assertEqual(items[0]["published_raw"], "2026-09-19T08:15:00+05:30")
        self.assertEqual(items[0]["summary"],
                         "Infosys raised its revenue guidance for the year.")

    def test_fail_closed(self):
        garbage = _feed_fetcher({"https://f/bad": "<html>not a feed"})
        self.assertEqual(nfc.fetch_feed("https://f/bad", fetcher=garbage), [])
        self.assertEqual(nfc.fetch_feed("https://f/garbage", fetcher=_feed_fetcher(
            {"https://f/garbage": "\x00\x01not xml at all <<<"})), [])
        self.assertEqual(nfc.fetch_feed("https://f/miss", fetcher=_feed_fetcher({})), [])
        self.assertEqual(nfc.fetch_feed("", fetcher=_feed_fetcher({})), [])
        self.assertEqual(nfc.fetch_feed(None, fetcher=_feed_fetcher({})), [])

    def test_fetcher_raising_is_fail_closed(self):
        def boom(url, headers=None, timeout=15):
            raise RuntimeError("network down")
        self.assertEqual(nfc.fetch_feed("https://f/boom", fetcher=boom), [])

    def test_unknown_outlet_key(self):
        self.assertEqual(nfc.fetch_outlet("nope", fetcher=_feed_fetcher({})), [])

    def test_atom_entry_without_image_has_empty_media_url(self):
        items = nfc.fetch_feed("https://f/atom", fetcher=_feed_fetcher(
            {"https://f/atom": ATOM_FIXTURE}))
        self.assertEqual(items[0]["media_url"], "")


class TestMediaUrl(unittest.TestCase):
    def _items(self):
        return nfc.fetch_feed("https://f/media", fetcher=_feed_fetcher(
            {"https://f/media": MEDIA_FIXTURE}))

    def test_largest_media_content_wins(self):
        # Two media:content nodes -> the 1200x800 chart beats the 200x200 thumb,
        # even though the thumbnail comes later in document order.
        item = self._items()[0]
        self.assertEqual(
            item["media_url"],
            "https://img.business-standard.com/charts/nifty.png?width=1200")

    def test_media_content_beats_media_thumbnail(self):
        item = self._items()[1]
        self.assertEqual(item["media_url"],
                         "https://img.business-standard.com/only-thumb.jpg")

    def test_image_enclosure_captured(self):
        item = self._items()[2]
        self.assertEqual(item["media_url"],
                         "https://img.et.example/charts/dalal-street.png")

    def test_inline_img_in_description_captured(self):
        item = self._items()[3]
        self.assertEqual(item["media_url"],
                         "https://img.livemint.com/inline/chart")

    def test_item_without_image_yields_empty_string(self):
        item = self._items()[4]
        self.assertEqual(item["media_url"], "")
        self.assertEqual(item["summary"], "No artwork in this one.")

    def test_tracking_query_stripped_only_without_extension(self):
        self.assertEqual(self._items()[5]["media_url"],
                         "https://img.thehindubusinessline.com/chart")

    def test_media_url_is_a_plain_string_on_every_item(self):
        for item in self._items():
            self.assertIsInstance(item["media_url"], str)

    def test_non_image_enclosure_is_ignored(self):
        fixture = MEDIA_FIXTURE.replace('type="image/png" length="71000"',
                                        'type="audio/mpeg" length="71000"')
        items = nfc.fetch_feed("https://f/media", fetcher=_feed_fetcher(
            {"https://f/media": fixture}))
        self.assertEqual(items[2]["media_url"], "")


class TestNormalize(unittest.TestCase):
    def _records(self, fixture=RSS_FIXTURE, outlet="livemint", symbol_map=None):
        items = nfc.fetch_feed("https://f/rss", fetcher=_feed_fetcher(
            {"https://f/rss": fixture}))
        return nfc.normalize(items, outlet, symbol_map=symbol_map)

    def test_counts_and_date_skip(self):
        records, stats = self._records()
        self.assertEqual(stats["items"], 3)
        self.assertEqual(stats["records"], 2)
        self.assertEqual(stats["skipped_no_date"], 1)
        self.assertEqual(stats["skipped_empty"], 0)
        self.assertEqual(stats["duplicates"], 0)
        self.assertEqual([r["published_date"] for r in records],
                         ["2026-09-19", "2026-09-18"])

    def test_record_contract_and_text(self):
        records, _ = self._records()
        rec = records[0]
        self.assertEqual(set(rec) - {"text", "symbols", "media_url"},
                         CONTRACT_KEYS)
        self.assertEqual(rec["source_type"], "News_livemint")
        self.assertEqual(rec["creator_or_ministry"], "Mint")
        self.assertIsNone(rec["fiscal_period"])
        self.assertIsNone(rec["local_file_path"])
        self.assertIsNone(rec["file_size_bytes"])
        self.assertEqual(rec["source_url"],
                         "https://www.livemint.com/market/stock-market-news/sensex-ends-higher")
        self.assertNotIn("<b>", rec["text"])  # HTML stripped from summary
        self.assertTrue(rec["text"].startswith(rec["title"] + " :: "))
        self.assertIn("Banking heavyweights led the advance.", rec["text"])

    def test_media_url_propagated_per_record(self):
        records, stats = self._records(MEDIA_FIXTURE, outlet="bs")
        self.assertEqual(stats["records"], 6)
        self.assertEqual(
            [r["media_url"] for r in records],
            ["https://img.business-standard.com/charts/nifty.png?width=1200",
             "https://img.business-standard.com/only-thumb.jpg",
             "https://img.et.example/charts/dalal-street.png",
             "https://img.livemint.com/inline/chart",
             "",
             "https://img.thehindubusinessline.com/chart"])
        # media_url is an extra, never a raw_documents column.
        self.assertNotIn("media_url", CONTRACT_KEYS)

    def test_media_url_defaults_empty_when_item_lacks_key(self):
        records, _ = nfc.normalize(
            [{"title": "T", "link": "https://x/1",
              "published_raw": "2026-09-19", "summary": "s"}], "et")
        self.assertEqual(records[0]["media_url"], "")

    def test_summary_capped(self):
        long_summary = "word " * 1000
        fixture = RSS_FIXTURE.replace(
            "Banking heavyweights &lt;b&gt;led&lt;/b&gt; the advance.",
            long_summary)
        records, _ = self._records(fixture)
        body = records[0]["text"].split(" :: ", 1)[1]
        self.assertLessEqual(len(body), nfc.SUMMARY_MAX_CHARS)

    def test_duplicate_hash_dropped_and_counted(self):
        records, stats = self._records(RSS_DUP_FIXTURE, outlet="bs")
        self.assertEqual(stats["items"], 2)
        self.assertEqual(stats["records"], 1)
        self.assertEqual(stats["duplicates"], 1)
        self.assertEqual(records[0]["source_type"], "News_bs")
        self.assertEqual(records[0]["creator_or_ministry"], "Business Standard")

    def test_sha_matches_link_title(self):
        import hashlib
        records, _ = self._records()
        rec = records[0]
        expected = hashlib.sha256(
            f"{rec['source_url']}|{rec['title']}".encode("utf-8")).hexdigest()
        self.assertEqual(rec["sha256_hash"], expected)

    def test_symbols_tagged_when_map_given(self):
        records, _ = self._records(symbol_map=SYMBOL_MAP)
        self.assertEqual(records[0]["symbols"], [])
        self.assertEqual(records[1]["symbols"], ["RELIANCE"])
        self.assertIn("(RELIANCE)", records[1]["text"])

    def test_empty_input_fail_closed(self):
        records, stats = nfc.normalize([], "et")
        self.assertEqual(records, [])
        self.assertEqual(stats["records"], 0)
        records, stats = nfc.normalize(None, "et")
        self.assertEqual(records, [])
        self.assertEqual(stats["items"], 0)


class TestTagSymbols(unittest.TestCase):
    def test_token_match(self):
        text = "TCS and INFY report; RELIANCE Industries capex up"
        self.assertEqual(nfc.tag_symbols(text, SYMBOL_MAP), ["INFY", "RELIANCE", "TCS"])

    def test_lowercase_symbol_not_tagged(self):
        self.assertEqual(nfc.tag_symbols("tcs wins a deal", SYMBOL_MAP), [])

    def test_prose_name_resolves_to_ticker(self):
        # Prose hits return the TICKER sharing the ISIN, never the name string:
        # downstream consumers (intelligence_fts.symbol, attention ranks) need
        # tradeable symbols, not company names.
        name_map = {"RELIANCE": "INE002A01018", "Reliance Industries": "INE002A01018"}
        self.assertEqual(
            nfc.tag_symbols("Reliance Industries board clears capex", name_map),
            ["RELIANCE"])

    def test_unresolvable_name_key_dropped(self):
        # A name with no ticker sharing its ISIN cannot be resolved to a symbol.
        self.assertEqual(
            nfc.tag_symbols("Reliance Industries board clears capex",
                            {"Reliance Industries": "INE002A01018"}),
            [])

    def test_name_match_is_word_bounded(self):
        name_map = {"ICICI Bank": "INE090A01021", "ICICIBANK": "INE090A01021"}
        self.assertEqual(nfc.tag_symbols("ICICI Bank Q2 profit up", name_map),
                         ["ICICIBANK"])
        self.assertEqual(nfc.tag_symbols("ICICIBANKPAT growth strong", name_map), [])

    def test_max_eight_sorted(self):
        big = {f"SYM{i:02d}": f"ISIN{i:02d}" for i in range(12)}
        text = " ".join(big)
        out = nfc.tag_symbols(text, big)
        self.assertEqual(len(out), nfc.MAX_SYMBOLS)
        self.assertEqual(out, sorted(out))

    def test_fail_closed(self):
        self.assertEqual(nfc.tag_symbols("RELIANCE up", None), [])
        self.assertEqual(nfc.tag_symbols("RELIANCE up", {}), [])
        self.assertEqual(nfc.tag_symbols("", SYMBOL_MAP), [])


class TestLoadSymbolMap(unittest.TestCase):
    def test_maps_symbol_to_isin(self):
        class StubRepo:
            def get_all_companies(self, active_only=True):
                assert active_only is True
                return [
                    {"nse_symbol": "RELIANCE", "isin": "INE002A01018",
                     "company_name": "Reliance Industries Ltd"},
                    {"nse_symbol": None, "isin": "INE000", "company_name": "X"},
                ]
        self.assertEqual(nfc.load_symbol_map(StubRepo()),
                         {"RELIANCE": "INE002A01018"})

    def test_include_names(self):
        # Company names are stored with corporate suffixes stripped so prose
        # ("HDFC Bank shares gain") can match them.
        class StubRepo:
            def get_all_companies(self, active_only=True):
                return [{"nse_symbol": "RELIANCE", "isin": "INE002A01018",
                         "company_name": "Reliance Industries Ltd"}]
        mapping = nfc.load_symbol_map(StubRepo(), include_names=True)
        self.assertEqual(mapping["RELIANCE"], "INE002A01018")
        self.assertEqual(mapping["Reliance Industries"], "INE002A01018")
        self.assertNotIn("Reliance Industries Ltd", mapping)

    def test_include_names_skips_short_names(self):
        class StubRepo:
            def get_all_companies(self, active_only=True):
                return [{"nse_symbol": "ABC", "isin": "INE000A01010",
                         "company_name": "ABC Ltd"}]
        mapping = nfc.load_symbol_map(StubRepo(), include_names=True)
        self.assertEqual(mapping, {"ABC": "INE000A01010"})

    def test_fail_closed(self):
        class BadRepo:
            def get_all_companies(self, active_only=True):
                raise RuntimeError("db down")
        self.assertEqual(nfc.load_symbol_map(BadRepo()), {})
        self.assertEqual(nfc.load_symbol_map(repo=object()), {})


class TestPersist(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.repo, self.mgr = _mk_repo(self._td.name)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name, is_active)"
                " VALUES (?, ?, ?, 1)",
                ("INE467B01029", "TCS", "Tata Consultancy Services Ltd"))
        items = nfc.fetch_feed("https://f/rss", fetcher=_feed_fetcher(
            {"https://f/rss": RSS_PERSIST_FIXTURE}))
        self.records, _ = nfc.normalize(items, "livemint", symbol_map=SYMBOL_MAP)

    def test_persist_writes_raw_and_fts(self):
        out = nfc.persist(self.records, repo=self.repo)
        self.assertEqual(out["raw_written"], 2)
        self.assertEqual(out["fts_written"], 2)
        with self.mgr.session() as conn:
            self.assertEqual(_count(conn, "raw_documents",
                                    "source_type = ?", ("News_livemint",)), 2)
            self.assertEqual(_count(conn, "intelligence_fts",
                                    "source_type = ?", ("News_livemint",)), 2)
        row = self.repo.get_raw_document_by_hash(self.records[0]["sha256_hash"])
        self.assertEqual(row["published_date"], "2026-09-19")
        self.assertIsNone(row["local_file_path"])
        self.assertEqual(row["creator_or_ministry"], "Mint")

    def test_chunk_id_format_and_symbol(self):
        nfc.persist(self.records, repo=self.repo)
        tcs = next(r for r in self.records if r["symbols"] == ["TCS"])
        row = self.repo.get_raw_document_by_hash(tcs["sha256_hash"])
        with self.mgr.session() as conn:
            chunks = [dict(r) for r in conn.execute(
                "SELECT * FROM intelligence_fts WHERE source_type = ?",
                ("News_livemint",)).fetchall()]
        by_id = {c["chunk_id"]: c for c in chunks}
        self.assertIn(f"News_livemint:{row['doc_id']}:0", by_id)
        chunk = by_id[f"News_livemint:{row['doc_id']}:0"]
        self.assertEqual(chunk["symbol"], "TCS")
        self.assertEqual(chunk["isin"], "INE467B01029")
        self.assertEqual(chunk["document_date"], tcs["published_date"])
        self.assertEqual(chunk["document_text"], tcs["text"])
        # untagged row: empty symbol + isin, still one chunk
        other = next(r for r in self.records if not r["symbols"])
        other_row = self.repo.get_raw_document_by_hash(other["sha256_hash"])
        self.assertIn(f"News_livemint:{other_row['doc_id']}:0", by_id)
        self.assertEqual(by_id[f"News_livemint:{other_row['doc_id']}:0"]["symbol"], "")
        self.assertEqual(by_id[f"News_livemint:{other_row['doc_id']}:0"]["isin"], "")

    def test_double_persist_writes_once(self):
        first = nfc.persist(self.records, repo=self.repo)
        second = nfc.persist(self.records, repo=self.repo)
        self.assertEqual(first["raw_written"], 2)
        self.assertEqual(second["raw_written"], 0)
        self.assertEqual(second["raw_updated"], 2)
        with self.mgr.session() as conn:
            self.assertEqual(_count(conn, "raw_documents",
                                    "source_type = ?", ("News_livemint",)), 2)
            self.assertEqual(_count(conn, "intelligence_fts",
                                    "source_type = ?", ("News_livemint",)), 2)

    def test_records_without_text_skipped(self):
        blank = dict(self.records[0])
        blank["text"] = ""
        out = nfc.persist([blank], repo=self.repo)
        self.assertEqual(out, {"raw_written": 0, "raw_updated": 0, "fts_written": 0})
        with self.mgr.session() as conn:
            self.assertEqual(_count(conn, "raw_documents"), 0)

    def test_persist_empty(self):
        self.assertEqual(nfc.persist([], repo=self.repo),
                         {"raw_written": 0, "raw_updated": 0, "fts_written": 0})

    def test_media_url_never_reaches_upsert_contract(self):
        # raw_documents has no media_url column: the contract handed to the
        # repository must stay exactly the 9 documented keys.
        seen = []

        class SpyRepo:
            def __init__(self):
                self.rows = {}

            def get_all_companies(self, active_only=True):
                return []

            def get_raw_document_by_hash(self, sha):
                return self.rows.get(sha)

            def upsert_raw_document(self, contract):
                seen.append(dict(contract))
                self.rows[contract["sha256_hash"]] = {"doc_id": len(seen)}
                return len(seen)

            def insert_fts_chunks(self, chunks):
                return len(chunks)

        records, _ = nfc.normalize(
            nfc.fetch_feed("https://f/media", fetcher=_feed_fetcher(
                {"https://f/media": MEDIA_FIXTURE})), "bs")
        self.assertTrue(any(r["media_url"] for r in records))
        out = nfc.persist(records, repo=SpyRepo())
        self.assertEqual(out["raw_written"], len(records))
        for contract in seen:
            self.assertEqual(set(contract), CONTRACT_KEYS)
            self.assertNotIn("media_url", contract)


class TestFetchFeeds(unittest.TestCase):
    def test_isolated_failures(self):
        mapping = {
            nfc.FEEDS["livemint"]: RSS_FIXTURE,
            nfc.FEEDS["livemint_co"]: RSS_FIXTURE,
            nfc.FEEDS["et"]: None,   # dead feed must not suppress the others
        }
        records, stats = nfc.fetch_feeds(
            ["livemint", "livemint_co", "et"], fetcher=_feed_fetcher(mapping))
        self.assertEqual(stats["feeds_ok"], 2)
        self.assertEqual(stats["feeds_failed"], 1)
        self.assertEqual(stats["records"], 4)
        self.assertEqual(stats["skipped_no_date"], 2)
        self.assertEqual(stats["feeds_requested"], 3)
        self.assertEqual({r["source_type"] for r in records},
                         {"News_livemint", "News_livemint_co"})
        self.assertEqual(stats["per_feed"]["et"], {"items": 0, "records": 0})

    def test_limit_applied_per_feed(self):
        records, stats = nfc.fetch_feeds(
            ["livemint"], limit=1,
            fetcher=_feed_fetcher({nfc.FEEDS["livemint"]: RSS_FIXTURE}))
        self.assertEqual(stats["items"], 1)
        self.assertEqual(stats["records"], 1)

    def test_unknown_key_counted_as_failure(self):
        records, stats = nfc.fetch_feeds(["nope"], fetcher=_feed_fetcher({}))
        self.assertEqual(records, [])
        self.assertEqual(stats["feeds_failed"], 1)

    def test_registry_is_official_outlets_only(self):
        self.assertEqual(set(nfc.FEEDS), {
            "livemint", "livemint_co", "bs", "businessline", "et", "ndtvprofit"})
        self.assertEqual(nfc.SOURCE_PREFIX, "News_")
        self.assertEqual(set(nfc.OUTLET_NAMES), set(nfc.FEEDS))
        for key, url in nfc.FEEDS.items():
            self.assertTrue(url.startswith("https://"), key)
        self.assertEqual(nfc.SOURCE_TYPES["et"], "News_et")


if __name__ == "__main__":
    unittest.main()
