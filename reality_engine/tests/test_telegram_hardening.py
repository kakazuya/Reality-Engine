"""
Extensive hardening tests for TelegramListener – edge cases, offline fallback, mock mode,
channel normalization, filename sanitization, media handling, and symbol filtering.
Runs without live Telethon credentials and without git commit.
"""

import base64
import shutil
import tempfile
import unittest
import asyncio
from datetime import datetime, timezone
from pathlib import Path
from PIL import Image, ImageDraw  # type: ignore

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.ingestion.telegram_client import TelegramListener, TELETHON_INSTALLED


class TestTelegramHardening(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="tg_hardening_"))
        cls.test_db_path = cls.temp_dir / "tg_test.db"
        cls.db = DatabaseManager(db_path=cls.test_db_path)
        cls.repo = Repository(manager=cls.db)
        # Seed a couple master companies for symbol validation
        cls.repo.upsert_master_companies([
            {"isin": "INE002A01018", "nse_symbol": "RELIANCE", "company_name": "Reliance Industries Ltd", "is_active": 1},
            {"isin": "INE467B01029", "nse_symbol": "TCS", "company_name": "TCS Ltd", "is_active": 1},
            {"isin": "INE040A01034", "nse_symbol": "HDFCBANK", "company_name": "HDFC Bank", "is_active": 1},
        ])

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def test_01_channel_normalization_edge_cases(self):
        # Empty / None
        self.assertEqual(TelegramListener._normalize_channels(None), [])
        self.assertEqual(TelegramListener._normalize_channels(""), [])
        self.assertEqual(TelegramListener._normalize_channels([]), [])
        self.assertEqual(TelegramListener._normalize_channels("   "), [])
        # Whitespace and duplicates
        l = TelegramListener(target_channels=" @alpha , @alpha , @beta ", mock_mode=True)
        self.assertEqual(len(l.target_channels), 2)
        self.assertIn("@alpha", l.target_channels)
        # Numeric strings become ints, deduped
        l2 = TelegramListener(target_channels="123, 123, 456", mock_mode=True)
        self.assertEqual(l2.target_channels, [123, 456])
        # Negative supergroup IDs
        l3 = TelegramListener(target_channels=["-100123456", -100123456, "@chan"], mock_mode=True)
        # -100123456 as int should deduplicate string form
        self.assertEqual(len([x for x in l3.target_channels if isinstance(x, int) and x == -100123456]), 1)
        # Mixed list with ints and strings
        l4 = TelegramListener(target_channels=["@stock_breakouts", 12345678, " -100987654 "], mock_mode=True)
        self.assertIn("@stock_breakouts", l4.target_channels)
        self.assertIn(12345678, l4.target_channels)
        self.assertIn(-100987654, l4.target_channels)
        # Semicolon separator
        l5 = TelegramListener(target_channels="@a; @b; @c", mock_mode=True)
        self.assertEqual(len(l5.target_channels), 3)
        # Filename sanitization
        self.assertEqual(TelegramListener._sanitize_filename_component("@my-channel/123"), "my_channel_123")
        self.assertEqual(TelegramListener._sanitize_filename_component("-100abc"), "100abc")
        self.assertTrue(len(TelegramListener._sanitize_filename_component("a" * 200)) <= 64)

    def test_02_is_available_mock_and_invalid_credentials(self):
        # Mock always available
        m = TelegramListener(mock_mode=True)
        self.assertTrue(m.is_available())
        # Unconfigured without telethon creds => False (even though telethon now installed, still false due to missing creds)
        u = TelegramListener(api_id=None, api_hash=None, mock_mode=False)
        self.assertFalse(u.is_available())
        # Invalid api_id string
        bad = TelegramListener(api_id="not-an-int", api_hash="abc", mock_mode=False)
        self.assertFalse(bad.is_available())
        self.assertIsNone(bad.api_id)
        # api_hash too short (<10) => false
        short = TelegramListener(api_id=12345, api_hash="short", mock_mode=False)
        self.assertFalse(short.is_available())
        # Valid-ish (but not real) should be true if telethon installed
        if TELETHON_INSTALLED:
            valid = TelegramListener(api_id=12345, api_hash="a" * 32, mock_mode=False)
            self.assertTrue(valid.is_available())

    def test_03_empty_and_long_text_handling(self):
        inbox = self.temp_dir / "inbox_empty"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # Empty text
        res = listener.simulate_incoming_message(text="", chat_id="ch1", message_id=10)
        self.assertEqual(res["status"], "processed")
        self.assertEqual(res["raw_message_text"], "")
        self.assertIsInstance(res["detected_symbols"], list)
        # Very long text >8000 chars
        long_text = "RELIANCE " * 2000  # 18000 chars
        res2 = listener.simulate_incoming_message(text=long_text, chat_id="ch1", message_id=11)
        self.assertEqual(res2["status"], "processed")
        # Should still detect RELIANCE (filtered correctly, not dropped)
        self.assertIn("RELIANCE", res2["detected_symbols"])
        # None text coerced to string
        res3 = asyncio.run(listener.handle_incoming_message({"id": 12, "chat_id": "ch1", "text": None}))
        self.assertEqual(res3["status"], "processed")

    def test_04_thread_topic_fallback_and_extraction(self):
        inbox = self.temp_dir / "inbox_thread"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # No thread id => General Discussion
        res = listener.simulate_incoming_message(text="hello", chat_id="c", message_id=20, thread_topic_id=0)
        self.assertEqual(res["thread_topic_name"], "General")
        self.assertEqual(res["thread_topic_id"], 0)
        # With topic id and name
        res2 = listener.simulate_incoming_message(text="hello", chat_id="c", message_id=21, thread_topic_id=5, thread_topic_name="Breakout Setups")
        self.assertEqual(res2["thread_topic_id"], 5)
        self.assertEqual(res2["thread_topic_name"], "Breakout Setups")
        # Dict with missing thread name should fallback to Topic #id
        res3 = asyncio.run(listener.handle_incoming_message({"id": 22, "chat_id": "c", "text": "hi", "thread_topic_id": 7}))
        self.assertEqual(res3["thread_topic_id"], 7)
        self.assertEqual(res3["thread_topic_name"], "Topic #7")
        # Test reply_to extraction path (object shape)
        class Reply:
            reply_to_top_id = 99
        class MsgObj:
            id = 23
            chat_id = "c"
            reply_to = Reply()
            raw_text = "TCS buy"
            date = datetime.now(timezone.utc)
        res4 = asyncio.run(listener.handle_incoming_message(MsgObj()))
        self.assertEqual(res4["thread_topic_id"], 99)

    def test_05_media_handling_image_bytes_and_missing_path(self):
        inbox = self.temp_dir / "inbox_media2"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # Create mock image
        img_path = self.temp_dir / "chart2.png"
        img = Image.new("RGB", (200, 80), color=(255, 255, 255))
        d = ImageDraw.Draw(img)
        d.text((10, 10), "HDFCBANK Target 1800 SL 1650", fill=(0, 0, 0))
        img.save(str(img_path))
        # Valid media_path copy
        res = listener.simulate_incoming_message(text="chart for HDFCBANK", chat_id="ch_media", message_id=30, media_path=img_path)
        self.assertTrue(res["has_media"])
        self.assertIsNotNone(res["media_file_path"])
        # Media path missing – should not crash, should still process text, mock placeholder created
        res2 = listener.simulate_incoming_message(text="missing file", chat_id="ch_media", message_id=31, media_path=Path(self.temp_dir / "nonexistent.png"))
        self.assertEqual(res2["status"], "processed")
        # image_bytes as raw bytes
        with open(img_path, "rb") as f:
            b = f.read()
        res3 = listener.simulate_incoming_message(text="bytes", chat_id="ch_bytes", message_id=32, image_bytes=b)
        self.assertTrue(res3["has_media"])
        self.assertTrue(Path(res3["media_file_path"]).exists())
        # image_bytes as base64 string
        b64 = base64.b64encode(b).decode()
        res4 = listener.simulate_incoming_message(text="b64", chat_id="ch_b64", message_id=33, image_bytes=b64)
        self.assertTrue(res4["has_media"])
        # has_media flag without actual file in mock_mode => placeholder
        res5 = asyncio.run(listener.handle_incoming_message({"id": 34, "chat_id": "ch_empty", "text": "no file", "has_media": True}))
        self.assertEqual(res5["status"], "processed")
        # Verify HDFCBANK detected via text at least
        self.assertIn("HDFCBANK", res["detected_symbols"])

    def test_06_symbol_filtering_noise_reduction(self):
        inbox = self.temp_dir / "inbox_filter"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # Text with many noise words – should be filtered out
        noise_text = "TARGET TGT STOP LOSS BREAKOUT HEAVY VOLUME SEEN RELIANCE TCS"
        res = listener.simulate_incoming_message(text=noise_text, chat_id="ch_filter", message_id=40)
        # RELIANCE and TCS should survive, noise should not
        self.assertIn("RELIANCE", res["detected_symbols"])
        self.assertIn("TCS", res["detected_symbols"])
        self.assertNotIn("TARGET", res["detected_symbols"])
        self.assertNotIn("BREAKOUT", res["detected_symbols"])
        # Price targets and SL extraction
        pt_text = "RELIANCE Target: 3100 SL 2880 Buy above 2950 TGT 3200"
        res2 = listener.simulate_incoming_message(text=pt_text, chat_id="ch_filter", message_id=41)
        self.assertIn(3100.0, res2["price_targets"])
        self.assertIn(2880.0, res2["stop_losses"])
        # Multiple symbols
        multi = "RELIANCE, TCS and HDFCBANK all breaking out"
        res3 = listener.simulate_incoming_message(text=multi, chat_id="ch_filter", message_id=42)
        for sym in ["RELIANCE", "TCS", "HDFCBANK"]:
            self.assertIn(sym, res3["detected_symbols"])

    def test_07_sanitize_and_database_persistence(self):
        inbox = self.temp_dir / "inbox_persist"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # Channel with special chars should be sanitized for post_id but stored original channel_id
        chat_id = "@my-weird/channel:123"
        res = listener.simulate_incoming_message(text="RELIANCE breakout", chat_id=chat_id, message_id=50)
        # post_id should be sanitized
        self.assertNotIn("/", res["id"])
        self.assertNotIn(":", res["id"])
        self.assertTrue(res["id"].endswith("_50"))
        self.assertEqual(res["channel_id"], chat_id)
        # Verify DB persisted and queryable via repo
        posts = self.repo.get_telegram_posts(channel_id=chat_id)
        self.assertGreaterEqual(len(posts), 1)
        self.assertEqual(posts[0]["channel_id"], chat_id)
        # Query by symbol
        posts_sym = self.repo.get_telegram_posts(symbol="RELIANCE")
        self.assertGreaterEqual(len(posts_sym), 1)
        # Duplicate upsert – same id should not create duplicate, just update
        res2 = listener.simulate_incoming_message(text="RELIANCE updated target 3200", chat_id=chat_id, message_id=50)
        self.assertEqual(res2["id"], res["id"])
        posts_after = self.repo.get_telegram_posts(channel_id=chat_id)
        # Count should remain same (upsert)
        self.assertEqual(len(posts_after), len(posts))

    def test_08_offline_fallback_and_mock_queue(self):
        # Offline fallback when not mock and no creds
        listener_offline = TelegramListener(api_id=None, api_hash=None, mock_mode=False, db=self.db, repository=self.repo, inbox_dir=self.temp_dir/"inbox_offline")
        result = asyncio.run(listener_offline.start_listening(duration_seconds=0.05))
        self.assertEqual(result["status"], "offline_fallback")
        self.assertEqual(result["reason"], "telethon_or_credentials_unavailable")
        # Mock mode with queue
        listener_mock = TelegramListener(mock_mode=True, db=self.db, repository=self.repo, inbox_dir=self.temp_dir/"inbox_mockq")
        listener_mock.enqueue_mock_message({"id": 60, "chat_id": "q1", "text": "TCS buy", "date": "2026-08-14T12:00:00Z"})
        listener_mock.enqueue_mock_message({"id": 61, "chat_id": "q1", "text": "RELIANCE sell", "date": "2026-08-14T12:01:00Z"})
        result2 = asyncio.run(listener_mock.start_listening(duration_seconds=0.05))
        self.assertEqual(result2["status"], "mock_listener_completed")
        self.assertEqual(result2["processed_count"], 2)
        # After processing queue should be empty
        self.assertEqual(len(listener_mock._mock_queue), 0)
        # Simulate direct queue via _mock_queue
        listener_mock2 = TelegramListener(mock_mode=True, db=self.db, repository=self.repo)
        listener_mock2._mock_queue.append({"id": 70, "chat_id": "direct", "text": "HDFCBANK"})
        result3 = asyncio.run(listener_mock2.start_listening(duration_seconds=0.05))
        self.assertEqual(result3["processed_count"], 1)

    def test_09_timestamp_and_message_id_edge_cases(self):
        inbox = self.temp_dir / "inbox_ts"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # Missing date should auto-generate
        res = asyncio.run(listener.handle_incoming_message({"chat_id": "ch_ts", "text": "hi"}))
        self.assertIsNotNone(res["post_timestamp"])
        # datetime object handling
        dt = datetime(2026, 8, 14, 10, 30, tzinfo=timezone.utc)
        res2 = listener.simulate_incoming_message(text="hi", chat_id="ch_ts", message_id=80, date=dt)
        self.assertIn("2026-08-14", res2["post_timestamp"])
        # String timestamp preserved
        res3 = listener.simulate_incoming_message(text="hi", chat_id="ch_ts", message_id=81, date="2026-08-14T15:00:00Z")
        self.assertEqual(res3["post_timestamp"], "2026-08-14T15:00:00Z")
        # Invalid message_id fallback to 1
        res4 = asyncio.run(listener.handle_incoming_message({"chat_id": "ch_ts", "text": "hi", "id": "not-an-int"}))
        self.assertEqual(res4["message_id"], 1)
        # Dict with id 0 should become 1
        res5 = asyncio.run(listener.handle_incoming_message({"chat_id": "ch_ts", "text": "hi", "id": 0}))
        self.assertEqual(res5["message_id"], 1)

    def test_10_ocr_and_inbox_integration_graceful_no_file(self):
        inbox = self.temp_dir / "inbox_ocr"
        listener = TelegramListener(inbox_dir=inbox, db=self.db, repository=self.repo, mock_mode=True)
        # Empty placeholder media file (0 bytes) should skip OCR gracefully, not crash
        empty_path = inbox / "images" / "tg_empty_999.png"
        empty_path.parent.mkdir(parents=True, exist_ok=True)
        empty_path.touch()
        res = asyncio.run(listener.handle_incoming_message({"id": 90, "chat_id": "ch_ocr", "text": "test", "has_media": True, "media_path": str(empty_path)}))
        self.assertEqual(res["status"], "processed")
        # Ensure raw text still processed even when OCR fails
        self.assertEqual(res["raw_message_text"], "test")
        # Test with corrupted image_bytes that still writes file but OCR may fallback to empty
        res2 = listener.simulate_incoming_message(text="RELIANCE", chat_id="ch_ocr", message_id=91, image_bytes=b"not-an-image-bytes-corrupted")
        self.assertEqual(res2["status"], "processed")
        self.assertIn("RELIANCE", res2["detected_symbols"])

    def test_11_channel_stats_and_cli_integration(self):
        # Verify get_channel_stats returns list
        listener = TelegramListener(db=self.db, repository=self.repo, mock_mode=True)
        stats = listener.get_channel_stats(limit=10)
        self.assertIsInstance(stats, list)
        # Simulate via CLI-like flow: ensure inbox_dir creation doesn't error when path is new
        new_inbox = self.temp_dir / "brand_new_inbox"
        listener2 = TelegramListener(inbox_dir=new_inbox, db=self.db, repository=self.repo, mock_mode=True)
        self.assertTrue(listener2.download_dir.exists())
        res = listener2.simulate_incoming_message(text="TCS", chat_id="cli_test", message_id=100)
        self.assertEqual(res["status"], "processed")


if __name__ == "__main__":
    unittest.main()
