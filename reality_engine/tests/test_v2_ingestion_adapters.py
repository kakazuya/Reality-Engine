"""
Unit & Integration Tests for V2 Ingestion Adapters:
TelegramListener (Telethon) and FinanciallyFreeClient (Playwright).
Tests availability probes, mock message handling, OCR entity extraction,
HTML/JSON breadth parsing, automatic NSE fallback, and database persistence.
"""

import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw

from reality_engine.config import DATA_DIR
from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion import (
    NSEClient,
    BSEClient,
    FundamentalsClient,
    MasterSync,
    TelegramListener,
    FinanciallyFreeClient,
    telegram_listener,
    financially_free_client,
)


class TestV2IngestionAdapters(unittest.TestCase):
    """Test suite for Telegram and FinanciallyFree ingestion adapters."""

    @classmethod
    def setUpClass(cls):
        # Create an isolated temporary test directory & database
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="reality_engine_test_v2_"))
        cls.test_db_path = cls.temp_dir / "test_intelligence.db"
        cls.db = DatabaseManager(db_path=cls.test_db_path)
        cls.repo = Repository(manager=cls.db)

        # Seed minimal master companies and daily price delivery for fallback tests
        cls._seed_test_database()

    @classmethod
    def tearDownClass(cls):
        # Clean up temporary test directory
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    @classmethod
    def _seed_test_database(cls):
        """Seeds test data into the temporary database for offline fallback testing."""
        # 1. Master companies
        companies = [
            {
                "isin": "INE002A01018",
                "nse_symbol": "RELIANCE",
                "bse_code": "500325",
                "company_name": "Reliance Industries Ltd",
                "industry": "Refineries",
                "sector": "Energy",
                "market_cap_tier": "LARGE",
                "is_fno_eligible": 1,
                "is_nifty50": 1,
                "is_nifty100": 1,
                "is_nifty200": 1,
                "is_nifty500": 1,
                "is_active": 1,
            },
            {
                "isin": "INE467B01029",
                "nse_symbol": "TCS",
                "bse_code": "532540",
                "company_name": "Tata Consultancy Services Ltd",
                "industry": "Computers - Software",
                "sector": "Information Technology",
                "market_cap_tier": "LARGE",
                "is_fno_eligible": 1,
                "is_nifty50": 1,
                "is_nifty100": 1,
                "is_nifty200": 1,
                "is_nifty500": 1,
                "is_active": 1,
            },
            {
                "isin": "INE040A01034",
                "nse_symbol": "HDFCBANK",
                "bse_code": "500180",
                "company_name": "HDFC Bank Ltd",
                "industry": "Banks - Private Sector",
                "sector": "Financial Services",
                "market_cap_tier": "LARGE",
                "is_fno_eligible": 1,
                "is_nifty50": 1,
                "is_nifty100": 1,
                "is_nifty200": 1,
                "is_nifty500": 1,
                "is_active": 1,
            },
            {
                "isin": "INE155A01022",
                "nse_symbol": "TATAMOTORS",
                "bse_code": "500570",
                "company_name": "Tata Motors Ltd",
                "industry": "Automobiles",
                "sector": "Automobile",
                "market_cap_tier": "LARGE",
                "is_fno_eligible": 1,
                "is_nifty50": 1,
                "is_nifty100": 1,
                "is_nifty200": 1,
                "is_nifty500": 1,
                "is_active": 1,
            },
        ]
        cls.repo.upsert_master_companies(companies)

        # 2. Daily price delivery for 2026-08-14
        delivery_records = [
            {
                "date": "2026-08-14",
                "symbol": "RELIANCE",
                "isin": "INE002A01018",
                "series": "EQ",
                "open": 2900.0,
                "high": 2960.0,
                "low": 2890.0,
                "close": 2945.0,
                "prev_close": 2900.0,
                "change_pct": 1.55,
                "total_volume": 2500000,
                "turnover_lacs": 73625.0,
                "num_trades": 85000,
                "deliverable_volume": 1500000,
                "delivery_pct": 60.0,
                "delivery_spike_ratio": 1.8,
                "delivery_conviction_score": 108.0,
            },
            {
                "date": "2026-08-14",
                "symbol": "TCS",
                "isin": "INE467B01029",
                "series": "EQ",
                "open": 4200.0,
                "high": 4280.0,
                "low": 4190.0,
                "close": 4260.0,
                "prev_close": 4210.0,
                "change_pct": 1.19,
                "total_volume": 1200000,
                "turnover_lacs": 50800.0,
                "num_trades": 45000,
                "deliverable_volume": 800000,
                "delivery_pct": 66.7,
                "delivery_spike_ratio": 1.6,
                "delivery_conviction_score": 106.7,
            },
            {
                "date": "2026-08-14",
                "symbol": "HDFCBANK",
                "isin": "INE040A01034",
                "series": "EQ",
                "open": 1650.0,
                "high": 1660.0,
                "low": 1630.0,
                "close": 1635.0,
                "prev_close": 1655.0,
                "change_pct": -1.21,
                "total_volume": 4000000,
                "turnover_lacs": 65600.0,
                "num_trades": 92000,
                "deliverable_volume": 2200000,
                "delivery_pct": 55.0,
                "delivery_spike_ratio": 1.1,
                "delivery_conviction_score": 60.5,
            },
            {
                "date": "2026-08-14",
                "symbol": "TATAMOTORS",
                "isin": "INE155A01022",
                "series": "EQ",
                "open": 1010.0,
                "high": 1040.0,
                "low": 1005.0,
                "close": 1032.0,
                "prev_close": 1015.0,
                "change_pct": 1.67,
                "total_volume": 3100000,
                "turnover_lacs": 31700.0,
                "num_trades": 60000,
                "deliverable_volume": 1600000,
                "delivery_pct": 51.6,
                "delivery_spike_ratio": 1.5,
                "delivery_conviction_score": 77.4,
            },
        ]
        cls.repo.upsert_daily_price_delivery(delivery_records)

    # -----------------------------------------------------------------
    # 1. Module Export & Availability Tests
    # -----------------------------------------------------------------
    def test_01_module_exports(self):
        """Tests that all classes and singletons are cleanly exposed from reality_engine.ingestion."""
        self.assertIsNotNone(NSEClient)
        self.assertIsNotNone(BSEClient)
        self.assertIsNotNone(FundamentalsClient)
        self.assertIsNotNone(MasterSync)
        self.assertIsNotNone(TelegramListener)
        self.assertIsNotNone(FinanciallyFreeClient)
        self.assertIsInstance(telegram_listener, TelegramListener)
        self.assertIsInstance(financially_free_client, FinanciallyFreeClient)

    def test_02_telegram_listener_availability(self):
        """Tests TelegramListener.is_available() logic."""
        # When unconfigured without credentials, is_available() should return False
        unconfigured = TelegramListener(api_id=None, api_hash=None, mock_mode=False)
        self.assertFalse(unconfigured.is_available())

        # In mock mode, is_available() returns True
        mocked = TelegramListener(mock_mode=True)
        self.assertTrue(mocked.is_available())

    def test_03_telegram_channel_normalization(self):
        """Tests Telegram target channel parsing and normalization."""
        listener = TelegramListener(
            target_channels=["@stock_breakouts", 12345678, " -100987654 "],
            mock_mode=True
        )
        self.assertIn("@stock_breakouts", listener.target_channels)
        self.assertIn(12345678, listener.target_channels)
        self.assertIn(-100987654, listener.target_channels)

        # String parsing
        listener2 = TelegramListener(
            target_channels="@alpha_desk, @swing_trades, 998877",
            mock_mode=True
        )
        self.assertEqual(len(listener2.target_channels), 3)
        self.assertIn("@alpha_desk", listener2.target_channels)
        self.assertIn(998877, listener2.target_channels)

    # -----------------------------------------------------------------
    # 2. Telegram Message Processing & OCR Tests
    # -----------------------------------------------------------------
    def test_04_telegram_text_message_processing(self):
        """Tests handling incoming text messages with entity and topic extraction."""
        inbox_dir = self.temp_dir / "inbox"
        listener = TelegramListener(
            inbox_dir=inbox_dir,
            db=self.db,
            repository=self.repo,
            mock_mode=True
        )

        sample_text = "Strong breakout on RELIANCE above 2950. Target: 3100. Stop loss: 2880. Heavy delivery spike seen."
        result = listener.simulate_incoming_message(
            text=sample_text,
            chat_id="alpha_traders_channel",
            channel_title="Alpha Traders",
            message_id=101,
            thread_topic_id=5,
            thread_topic_name="Breakout Setups",
            date="2026-08-14T10:30:00Z"
        )

        self.assertEqual(result["status"], "processed")
        self.assertEqual(result["channel_id"], "alpha_traders_channel")
        self.assertEqual(result["thread_topic_id"], 5)
        self.assertEqual(result["thread_topic_name"], "Breakout Setups")
        self.assertIn("RELIANCE", result["detected_symbols"])
        self.assertIn(3100.0, result["price_targets"])
        self.assertIn(2880.0, result["stop_losses"])

        # Verify database record saved in telegram_posts
        posts = self.repo.get_telegram_posts(symbol="RELIANCE")
        self.assertGreaterEqual(len(posts), 1)
        latest_post = posts[0]
        self.assertEqual(latest_post["id"], "alpha_traders_channel_101")
        self.assertIn("RELIANCE", latest_post["detected_symbols_json"])
        self.assertEqual(latest_post["thread_topic_id"], 5)

    def test_05_telegram_image_message_processing(self):
        """Tests downloading media, executing OCR extraction, and indexing via InboxRunner."""
        inbox_dir = self.temp_dir / "inbox_media"
        listener = TelegramListener(
            inbox_dir=inbox_dir,
            db=self.db,
            repository=self.repo,
            mock_mode=True
        )

        # Create a mock image file
        mock_img_path = self.temp_dir / "mock_chart.png"
        img = Image.new("RGB", (300, 100), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 10), "TCS Target 4500 SL 4100", fill=(0, 0, 0))
        img.save(str(mock_img_path))

        result = listener.simulate_incoming_message(
            text="Chart setup for TCS",
            chat_id="chart_alerts",
            channel_title="Chart Alerts",
            message_id=202,
            thread_topic_id=12,
            media_path=mock_img_path,
            date="2026-08-14T11:00:00Z"
        )

        self.assertEqual(result["status"], "processed")
        self.assertTrue(result["has_media"])
        self.assertIsNotNone(result["media_file_path"])
        self.assertTrue(Path(result["media_file_path"]).exists() or "processed" in str(result["media_file_path"]))
        self.assertIn("TCS", result["detected_symbols"])

        # Verify saved in database
        posts = self.repo.get_telegram_posts(channel_id="chart_alerts")
        self.assertGreaterEqual(len(posts), 1)
        self.assertEqual(posts[0]["has_media"], 1)

    def test_06_telegram_listener_start_offline_fallback(self):
        """Tests start_listening() offline fallback when Telethon or credentials are not configured."""
        import asyncio
        listener = TelegramListener(api_id=None, api_hash=None, mock_mode=False)
        result = asyncio.run(listener.start_listening(duration_seconds=0.1))
        self.assertEqual(result["status"], "offline_fallback")
        self.assertEqual(result["reason"], "telethon_or_credentials_unavailable")

    def test_07_telegram_listener_start_mock_mode(self):
        """Tests start_listening() execution in mock mode."""
        import asyncio
        listener = TelegramListener(mock_mode=True)
        # Push mock message to queue
        listener._mock_queue.append({
            "id": 303,
            "chat_id": "mock_feed",
            "channel_title": "Mock Feed",
            "text": "TATAMOTORS buy above 1040",
            "date": "2026-08-14T12:00:00Z"
        })
        result = asyncio.run(listener.start_listening(duration_seconds=0.1))
        self.assertEqual(result["status"], "mock_listener_completed")
        self.assertEqual(result["processed_count"], 1)

    # -----------------------------------------------------------------
    # 3. FinanciallyFree Client Tests
    # -----------------------------------------------------------------
    def test_08_financially_free_availability(self):
        """Tests FinanciallyFreeClient.is_available() logic."""
        # Non-existent browser profile directory
        client = FinanciallyFreeClient(browser_profile_dir=self.temp_dir / "non_existent_profile", mock_mode=False)
        self.assertFalse(client.is_available())

        # Mock mode is always available
        mock_client = FinanciallyFreeClient(mock_mode=True)
        self.assertTrue(mock_client.is_available())

    def test_09_financially_free_html_dom_parsing(self):
        """Tests parsing rendered HTML table markup into structured sector breadth."""
        client = FinanciallyFreeClient(mock_mode=True)
        sample_html = """
        <html>
        <body>
            <table>
                <tr><th>Sector</th><th>Advances</th><th>Declines</th><th>Momentum %</th></tr>
                <tr><td>NIFTY AUTO</td><td>12</td><td>3</td><td>+1.85</td></tr>
                <tr><td>NIFTY IT</td><td>8</td><td>2</td><td>+1.20</td></tr>
                <tr><td>NIFTY BANK</td><td>4</td><td>8</td><td>-0.75</td></tr>
                <tr><td>NIFTY FMCG</td><td>9</td><td>6</td><td>+0.35</td></tr>
            </table>
        </body>
        </html>
        """
        parsed = client.parse_market_overview_html(sample_html, target_date="2026-08-14")
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(parsed["date"], "2026-08-14")
        self.assertEqual(len(parsed["sectors"]), 4)

        # Check top sector (Auto)
        top_sector = parsed["sectors"][0]
        self.assertEqual(top_sector["sector_name"], "NIFTY AUTO")
        self.assertEqual(top_sector["advances_count"], 12)
        self.assertEqual(top_sector["declines_count"], 3)
        self.assertEqual(top_sector["advance_decline_ratio"], 4.0)
        self.assertEqual(top_sector["sector_momentum_score"], 1.85)

        # Check market breadth aggregate
        mb = parsed["market_breadth"]
        self.assertEqual(mb["advances"], 33)
        self.assertEqual(mb["declines"], 19)
        self.assertGreater(mb["advance_decline_ratio"], 1.5)
        self.assertEqual(mb["market_regime"], "BULLISH")

    def test_10_financially_free_api_json_parsing(self):
        """Tests parsing intercepted JSON payloads into structured sector breadth."""
        client = FinanciallyFreeClient(mock_mode=True)
        sample_json = {
            "date": "2026-08-14",
            "sectors": [
                {
                    "sector": "Nifty Metal",
                    "advances": 10,
                    "declines": 5,
                    "ad_ratio": 2.0,
                    "momentum": 2.10,
                    "top_gainers": ["TATASTEEL", "JINDALSTEL"],
                    "top_losers": ["SAIL"]
                },
                {
                    "sector": "Nifty Pharma",
                    "advances": 7,
                    "declines": 8,
                    "ad_ratio": 0.88,
                    "momentum": -0.15,
                    "top_gainers": ["SUNPHARMA"],
                    "top_losers": ["CIPLA"]
                }
            ]
        }
        parsed = client.parse_market_overview_json(sample_json)
        self.assertEqual(parsed["status"], "success")
        self.assertEqual(len(parsed["sectors"]), 2)
        self.assertEqual(parsed["sectors"][0]["sector_name"], "Nifty Metal")
        self.assertEqual(parsed["sectors"][0]["sector_momentum_score"], 2.10)
        self.assertEqual(parsed["sectors"][0]["top_gainers"], ["TATASTEEL", "JINDALSTEL"])

    def test_11_financially_free_nse_index_breadth_fallback(self):
        """Tests automatic calculation and fallback to official NSE index breadth."""
        client = FinanciallyFreeClient(
            db=self.db,
            repository=self.repo,
            mock_mode=False
        )
        overview = client.fetch_market_overview(target_date="2026-08-14")

        self.assertEqual(overview["status"], "success")
        self.assertEqual(overview["source"], "nse_index_breadth_fallback")
        self.assertEqual(overview["date"], "2026-08-14")
        
        mb = overview["market_breadth"]
        self.assertEqual(mb["total_stocks"], 4)
        self.assertEqual(mb["advances"], 3)
        self.assertEqual(mb["declines"], 1)
        self.assertEqual(mb["advance_decline_ratio"], 3.0)
        self.assertEqual(mb["market_regime"], "BULLISH")

        # Verify sectors generated
        sectors = overview["sectors"]
        self.assertGreaterEqual(len(sectors), 3)
        sector_names = [s["sector_name"] for s in sectors]
        self.assertTrue(any("Energy" in s or "Automobile" in s or "Information Technology" in s for s in sector_names))

        # Verify data persisted to financially_free_breadth table
        breadth_records = self.repo.get_financially_free_breadth(target_date="2026-08-14")
        self.assertGreaterEqual(len(breadth_records), 3)

    def test_12_financially_free_mock_data_mode(self):
        """Tests FinanciallyFreeClient with custom mock_data."""
        mock_payload = {
            "date": "2026-08-14",
            "sectors": [
                {
                    "sector_name": "Nifty Realty",
                    "advances_count": 9,
                    "declines_count": 1,
                    "advance_decline_ratio": 9.0,
                    "sector_momentum_score": 3.45,
                    "top_gainers": [{"symbol": "DLF", "change_pct": 4.5}],
                    "top_losers": []
                }
            ]
        }
        client = FinanciallyFreeClient(mock_mode=True, mock_data=mock_payload, db=self.db, repository=self.repo)
        overview = client.fetch_market_overview()
        self.assertEqual(overview["source"], "mock_portal")
        self.assertEqual(len(overview["sectors"]), 1)
        self.assertEqual(overview["sectors"][0]["sector_name"], "Nifty Realty")


if __name__ == "__main__":
    unittest.main()
