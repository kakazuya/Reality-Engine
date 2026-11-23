"""news_vision — infographic capture (RSS media -> download -> OCR -> FTS + row).

Zero network and zero live-DB writes: every fetch path uses an injected fake
fetcher, OCR is an injected fake engine, the database is a tempfile
``DatabaseManager`` and ``news_vision.DATA_DIR`` is redirected into the temp
directory so no image ever lands in the repo's data root.
"""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from reality_engine.db.database import DatabaseManager
from reality_engine.db.repository import Repository
from reality_engine.processing import news_vision as nv

#: raw_documents contract keys the news feed client emits (plus text/symbols).
CONTRACT_KEYS = (
    "title", "source_type", "published_date", "fiscal_period", "source_url",
    "creator_or_ministry", "sha256_hash", "local_file_path", "file_size_bytes",
)

#: Minimal real-magic payloads: content-type is absent, so the magic decides.
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 96 + b"\xff\xd9"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 96
HTML = b"<!DOCTYPE html><html><body>not an image</body></html>"

MEDIA_A = "https://cdn.livemint.com/infographics/itc-target.jpg"
MEDIA_B = "https://cdn.livemint.com/infographics/bs-logo.png"

#: Realistic infographic OCR output (> MIN_OCR_CHARS, numbers absent from RSS).
INFOGRAPHIC_TEXT = (
    "ITC UPSIDE POTENTIAL 68% CHECK TARGET PRICE TOBACCO FMCG HOTELS "
    "ASHIRVAAD PAPERBOARDS AGRI BUSINESS ITC INFOTECH CLASSIC"
)
LOGO_TEXT = "BS"


class _Fetcher:
    """Injected fetcher: scripted payload per URL, raises on any other URL."""

    def __init__(self, payloads):
        self.payloads = dict(payloads)
        self.calls = []

    def __call__(self, url, headers=None, timeout=None):
        self.calls.append((url, dict(headers or {})))
        if url not in self.payloads:
            raise RuntimeError(f"network disabled: {url}")
        return self.payloads[url]


class _Resp:
    """Response-like object (headers + content), for content-type/size gating."""

    def __init__(self, content, content_type="image/jpeg", status_code=200,
                 content_length=None):
        self.content = content
        self.status_code = status_code
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)


class _OCR:
    """Injected OCR engine mirroring FinancialOCREngine.process_image."""

    def __init__(self, text=INFOGRAPHIC_TEXT, confidence=0.97, raises=False):
        self.text = text
        self.confidence = confidence
        self.raises = raises
        self.seen = []

    def process_image(self, path):
        self.seen.append(str(path))
        if self.raises:
            raise RuntimeError("ocr engine down")
        return {"raw_text": self.text, "avg_confidence": self.confidence}


def _count(conn, table, where="1=1", params=()):
    return int(conn.execute(
        f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0])


def _record(link, title, body, media_url=None, symbols=None,
            published="2026-09-19"):
    """One news_feed_client record: contract keys + text/symbols + media_url."""
    digest = hashlib.sha256(f"{link}|{title}".encode("utf-8")).hexdigest()
    return {
        "title": title,
        "source_type": "News_livemint",
        "published_date": published,
        "fiscal_period": None,
        "source_url": link,
        "creator_or_ministry": "Mint",
        "sha256_hash": digest,
        "local_file_path": None,
        "file_size_bytes": None,
        "text": body,
        "symbols": list(symbols or []),
        "media_url": media_url,
    }


class _VisionCase(unittest.TestCase):
    """Temp DB + temp DATA_DIR; master_companies carries TCS -> INE467B01029."""

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.data = Path(self._td.name) / "data"
        self.data.mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(nv, "DATA_DIR", self.data)
        patcher.start()
        self.addCleanup(patcher.stop)

        self.mgr = DatabaseManager(db_path=Path(self._td.name) / "news.db")
        self.repo = Repository(manager=self.mgr)
        with self.mgr.session() as conn:
            conn.execute(
                "INSERT INTO master_companies (isin, nse_symbol, company_name,"
                " is_active) VALUES (?, ?, ?, 1)",
                ("INE467B01029", "TCS", "Tata Consultancy Services Ltd"))

    def _persist(self, record):
        """Insert the record's raw_documents row (as the feed client does)."""
        self.repo.upsert_raw_document({k: record.get(k) for k in CONTRACT_KEYS})
        return self.repo.get_raw_document_by_hash(record["sha256_hash"])["doc_id"]

    def _chunks(self, source_type="News_livemint"):
        with self.mgr.session() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM intelligence_fts WHERE source_type = ?",
                (source_type,)).fetchall()]

    def _artifacts(self):
        with self.mgr.session() as conn:
            return [dict(row) for row in conn.execute(
                "SELECT * FROM news_visual_artifacts ORDER BY artifact_id").fetchall()]

    def _image_path(self, media_url, day="2026-09-19", suffix=".jpg"):
        key = hashlib.sha256(media_url.encode("utf-8")).hexdigest()[:16]
        return self.data / nv.IMAGE_DIR_NAME / day / f"{key}{suffix}"


# ---------------------------------------------------------------------------
# ensure_schema
# ---------------------------------------------------------------------------

class TestEnsureSchema(_VisionCase):
    def test_idempotent_and_column_shape(self):
        self.assertTrue(nv.ensure_schema(self.repo))
        self.assertTrue(nv.ensure_schema(self.repo))  # second call: no error
        with self.mgr.session() as conn:
            columns = {row[1] for row in conn.execute(
                "PRAGMA table_info(news_visual_artifacts)").fetchall()}
        self.assertEqual(columns, {
            "artifact_id", "doc_id", "symbol", "source_type", "source_url",
            "media_url", "local_path", "ocr_text", "ocr_confidence", "ocr_chars",
            "created_at"})
        # Adopting an existing live DB must not rewrite unrelated tables.
        with self.mgr.session() as conn:
            self.assertEqual(_count(conn, "raw_documents"), 0)
            self.assertEqual(_count(conn, "intelligence_fts"), 0)

    def test_fail_closed_on_bad_target(self):
        self.assertFalse(nv.ensure_schema(object()))


# ---------------------------------------------------------------------------
# download_image
# ---------------------------------------------------------------------------

class TestDownloadImage(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)

    def test_writes_bytes_and_returns_count(self):
        dest = self.tmp / "img" / "chart.jpg"
        written = nv.download_image(MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: JPEG}))
        self.assertEqual(written, len(JPEG))
        self.assertEqual(dest.read_bytes(), JPEG)

    def test_suffix_appended_from_content_type_and_url(self):
        # No suffix on dest -> response content-type decides the extension.
        stem = self.tmp / "a"
        written = nv.download_image(
            "https://cdn.example.com/x", stem,
            fetcher=_Fetcher({"https://cdn.example.com/x": (PNG, "image/png")}))
        self.assertEqual(written, len(PNG))
        self.assertTrue((self.tmp / "a.png").exists())
        # Unknown type + image URL suffix -> URL decides.
        stem_b = self.tmp / "b"
        nv.download_image("https://cdn.example.com/y.webp", stem_b,
                          fetcher=_Fetcher({"https://cdn.example.com/y.webp": JPEG}))
        self.assertTrue((self.tmp / "b.jpg").exists())

    def test_oversized_payload_rejected(self):
        big = b"\xff\xd8\xff" + b"0" * (nv.MAX_IMAGE_BYTES + 1)
        dest = self.tmp / "big.jpg"
        self.assertEqual(nv.download_image(MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: big})), 0)
        self.assertFalse(dest.exists())

    def test_declared_oversized_content_length_rejected(self):
        dest = self.tmp / "declared.jpg"
        resp = _Resp(JPEG, "image/jpeg", content_length=nv.MAX_IMAGE_BYTES + 1)
        # A response-like fetcher result exercises the header gate without the
        # 8 MB payload ever being buffered.
        written = nv.download_image(MEDIA_A, dest,
                                    fetcher=lambda url, **kw: resp)
        self.assertEqual(written, 0)
        self.assertFalse(dest.exists())

    def test_non_image_rejected(self):
        dest = self.tmp / "html.jpg"
        self.assertEqual(nv.download_image(
            MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: (HTML, "text/html")})), 0)
        self.assertFalse(dest.exists())
        self.assertEqual(nv.download_image(
            MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: ('{"a": 1}', "application/json")})), 0)
        # HTML bytes with no declared type: magic sniff refuses too.
        self.assertEqual(nv.download_image(MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: HTML})), 0)
        self.assertEqual(nv.download_image(
            MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: _Resp(HTML, "text/html")})), 0)
        self.assertFalse(dest.exists())

    def test_opaque_content_type_accepted_with_image_magic(self):
        dest = self.tmp / "octet"
        written = nv.download_image(
            MEDIA_A, dest,
            fetcher=_Fetcher({MEDIA_A: (JPEG, "application/octet-stream")}))
        self.assertEqual(written, len(JPEG))
        self.assertTrue((self.tmp / "octet.jpg").exists())

    def test_empty_and_error_payloads_fail_closed(self):
        dest = self.tmp / "empty.jpg"
        self.assertEqual(nv.download_image(MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: b""})), 0)
        self.assertEqual(nv.download_image(
            MEDIA_A, dest, fetcher=_Fetcher({MEDIA_A: _Resp(JPEG, "image/jpeg",
                                                            status_code=403)})), 0)
        # Unscripted URL (the injected fetcher raises) and a body-less stream.
        self.assertEqual(nv.download_image(MEDIA_A, dest, fetcher=_Fetcher({})), 0)
        self.assertEqual(nv.download_image(
            MEDIA_A, dest, fetcher=lambda url, **kw: _Resp(b"", "image/jpeg")), 0)
        self.assertFalse(dest.exists())

    def test_extensionless_publisher_url_defaults_to_jpg(self):
        # ET chart URLs carry no image suffix: .../msid-123,imgsize-456.cms
        et_url = "https://img.etimg.com/photo/msid-1234567,imgsize-98765.cms"
        stem = self.tmp / "et"
        written = nv.download_image(et_url, stem, fetcher=_Fetcher({et_url: JPEG}))
        self.assertEqual(written, len(JPEG))
        self.assertTrue((self.tmp / "et.jpg").exists())
        self.assertFalse((self.tmp / "et.cms").exists())

    def test_write_failure_returns_zero_without_partial_file(self):
        blocker = self.tmp / "blocker"
        blocker.write_text("not a directory")
        self.assertEqual(nv.download_image(
            MEDIA_A, blocker / "x", fetcher=_Fetcher({MEDIA_A: JPEG})), 0)
        self.assertTrue(blocker.is_file())


# ---------------------------------------------------------------------------
# ocr_image
# ---------------------------------------------------------------------------

class TestOcrImage(unittest.TestCase):
    def test_result_normalized(self):
        out = nv.ocr_image("x.jpg", ocr=_OCR(text="  ITC\n\nHOTELS  ", confidence=0.8))
        self.assertEqual(out, {"text": "ITC HOTELS", "confidence": 0.8})
        out = nv.ocr_image("x.jpg", ocr=_OCR(text="A", confidence=None))
        self.assertEqual(out, {"text": "A", "confidence": 0.0})
        out = nv.ocr_image("x.jpg", ocr=_OCR(text="A", confidence=7.5))
        self.assertEqual(out["confidence"], 1.0)

    def test_engine_never_constructed_at_import(self):
        self.assertIsNone(nv._ocr_engine)

    def test_failure_fail_closed(self):
        with mock.patch.object(nv, "_get_ocr_engine",
                               side_effect=AssertionError("no real engine")):
            self.assertEqual(nv.ocr_image("x.jpg", ocr=_OCR(raises=True)),
                             {"text": "", "confidence": 0.0})
            self.assertEqual(nv.ocr_image("x.jpg", ocr=object()),
                             {"text": "", "confidence": 0.0})
            self.assertEqual(nv.ocr_image("x.jpg", ocr=_OCR(text=None)),
                             {"text": "", "confidence": 0.0})


# ---------------------------------------------------------------------------
# capture_images
# ---------------------------------------------------------------------------

class TestCaptureImages(_VisionCase):
    def test_counts_and_chunk_id(self):
        with_media = _record("https://livenews/itc", "ITC target", "ITC news body",
                             media_url=MEDIA_A, symbols=["TCS"])
        without_media = _record("https://livenews/nifty", "Nifty ends flat",
                                "Nifty news body")
        doc_id = self._persist(with_media)
        self._persist(without_media)
        ocr = _OCR()
        stats = nv.capture_images(
            [with_media, without_media], repo=self.repo,
            fetcher=_Fetcher({MEDIA_A: JPEG}), ocr=ocr)

        self.assertEqual(stats["attempted"], 2)
        self.assertEqual(stats["downloaded"], 1)
        self.assertEqual(stats["ocr_ok"], 1)
        self.assertEqual(stats["chunks_written"], 1)
        self.assertEqual(stats["artifacts_written"], 1)
        self.assertEqual(stats["skipped_no_media"], 1)
        self.assertEqual(stats["skipped_existing"], 0)
        self.assertEqual(stats["skipped_low_signal"], 0)
        self.assertEqual(stats["files_deleted"], 0)
        self.assertEqual(stats["errors"], [])
        # The injected OCR was handed the downloaded file.
        self.assertEqual(ocr.seen, [str(self._image_path(MEDIA_A))])

        chunks = self._chunks()
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["chunk_id"], f"News_livemint:{doc_id}:img")
        self.assertEqual(chunks[0]["symbol"], "TCS")
        self.assertEqual(chunks[0]["isin"], "INE467B01029")
        self.assertEqual(chunks[0]["document_date"], "2026-09-19")
        self.assertEqual(chunks[0]["document_text"],
                         nv.CHUNK_PREFIX + INFOGRAPHIC_TEXT)
        # Article chunk shape is left untouched/absent.
        self.assertNotIn(f"News_livemint:{doc_id}:0",
                         {c["chunk_id"] for c in chunks})

    def test_artifact_row_and_file(self):
        rec = _record("https://livenews/itc", "ITC target", "ITC news body",
                      media_url=MEDIA_A, symbols=["TCS"])
        doc_id = self._persist(rec)
        nv.capture_images([rec], repo=self.repo,
                          fetcher=_Fetcher({MEDIA_A: JPEG}), ocr=_OCR())

        rows = self._artifacts()
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["doc_id"], doc_id)
        self.assertEqual(row["symbol"], "TCS")
        self.assertEqual(row["source_type"], "News_livemint")
        self.assertEqual(row["source_url"], rec["source_url"])
        self.assertEqual(row["media_url"], MEDIA_A)
        self.assertEqual(row["local_path"], str(self._image_path(MEDIA_A)))
        self.assertEqual(row["ocr_text"], INFOGRAPHIC_TEXT)
        self.assertEqual(row["ocr_chars"], len(INFOGRAPHIC_TEXT))
        self.assertAlmostEqual(row["ocr_confidence"], 0.97, places=6)
        self.assertTrue(Path(row["local_path"]).exists())

    def test_second_run_is_idempotent(self):
        rec = _record("https://livenews/itc", "ITC target", "ITC news body",
                      media_url=MEDIA_A, symbols=["TCS"])
        self._persist(rec)
        fetcher = _Fetcher({MEDIA_A: JPEG})
        first = nv.capture_images([rec], repo=self.repo, fetcher=fetcher, ocr=_OCR())
        second = nv.capture_images([rec], repo=self.repo, fetcher=fetcher, ocr=_OCR())

        self.assertEqual(first["chunks_written"], 1)
        self.assertEqual(second["skipped_existing"], 1)
        self.assertEqual(second["chunks_written"], 0)
        self.assertEqual(second["artifacts_written"], 0)
        # Skipped before the download: no second fetch.
        self.assertEqual(len(fetcher.calls), 1)
        self.assertEqual(len(self._chunks()), 1)
        self.assertEqual(len(self._artifacts()), 1)

    def test_ocr_empty_writes_nothing_and_removes_file(self):
        rec = _record("https://livenews/itc", "ITC target", "ITC news body",
                      media_url=MEDIA_A, symbols=["TCS"])
        self._persist(rec)
        stats = nv.capture_images([rec], repo=self.repo,
                                  fetcher=_Fetcher({MEDIA_A: JPEG}),
                                  ocr=_OCR(text="", confidence=0.0))
        self.assertEqual(stats["downloaded"], 1)
        self.assertEqual(stats["ocr_ok"], 0)
        self.assertEqual(stats["chunks_written"], 0)
        self.assertEqual(stats["artifacts_written"], 0)
        self.assertEqual(stats["skipped_low_signal"], 1)
        self.assertEqual(stats["files_deleted"], 1)
        self.assertEqual(self._chunks(), [])
        self.assertEqual(self._artifacts(), [])
        self.assertFalse(self._image_path(MEDIA_A).exists())

    def test_logo_low_signal_skipped(self):
        # A 2-char OCR ("BS") at full confidence is a wordmark, not data.
        rec = _record("https://livenews/bs", "BS logo item", "BS news body",
                      media_url=MEDIA_B, symbols=[])
        self._persist(rec)
        stats = nv.capture_images([rec], repo=self.repo,
                                  fetcher=_Fetcher({MEDIA_B: (PNG, "image/png")}),
                                  ocr=_OCR(text=LOGO_TEXT, confidence=1.0))
        self.assertEqual(stats["ocr_ok"], 1)
        self.assertEqual(stats["skipped_low_signal"], 1)
        self.assertEqual(stats["chunks_written"], 0)
        self.assertEqual(stats["artifacts_written"], 0)
        self.assertEqual(stats["files_deleted"], 1)
        self.assertEqual(self._artifacts(), [])
        self.assertFalse(self._image_path(MEDIA_B, suffix=".png").exists())

    def test_duplicate_media_ocrs_once_per_batch(self):
        # Business Standard repeats one generic asset across most items: the
        # OCR call must happen once, the repeats are counted, not re-downloaded.
        recs = [_record(f"https://livenews/bs{i}", f"BS {i}", "body",
                        media_url=MEDIA_B, symbols=[]) for i in range(3)]
        distinct = _record("https://livenews/mint", "Mint chart", "body",
                           media_url=MEDIA_A, symbols=[])
        recs.append(distinct)
        for rec in recs:
            self._persist(rec)
        fetcher = _Fetcher({MEDIA_B: (PNG, "image/png"), MEDIA_A: JPEG})
        ocr = _OCR()
        stats = nv.capture_images(recs, repo=self.repo, fetcher=fetcher, ocr=ocr)

        self.assertEqual(stats["attempted"], 4)
        self.assertEqual(stats["downloaded"], 2)
        self.assertEqual(stats["skipped_duplicate_media"], 2)
        self.assertEqual(stats["chunks_written"], 2)
        self.assertEqual(stats["artifacts_written"], 2)
        self.assertEqual(len(ocr.seen), 2)
        self.assertEqual(len(fetcher.calls), 2)
        self.assertEqual(len(self._artifacts()), 2)

    def test_min_ocr_chars_boundary(self):
        at_limit = _record("https://livenews/exact", "Exact", "body",
                           media_url=MEDIA_A, symbols=[])
        one_under = _record("https://livenews/under", "Under", "body",
                            media_url=MEDIA_B, symbols=[])
        self._persist(at_limit)
        self._persist(one_under)
        stats = nv.capture_images([at_limit, one_under], repo=self.repo,
                                  fetcher=_Fetcher({MEDIA_A: JPEG, MEDIA_B: PNG}),
                                  ocr=_OCR(text="X" * nv.MIN_OCR_CHARS))
        self.assertEqual(stats["chunks_written"], 2)
        self.assertEqual(len(self._chunks()), 2)

        exact = _record("https://livenews/short", "Short", "body",
                        media_url=MEDIA_B, symbols=[])
        self._persist(exact)
        one_under_short = _record("https://livenews/short2", "Short2", "body",
                                  media_url="https://cdn.livemint.com/short.png",
                                  symbols=[])
        self._persist(one_under_short)
        short_media = "https://cdn.livemint.com/short.png"
        stats = nv.capture_images(
            [exact, one_under_short], repo=self.repo,
            fetcher=_Fetcher({MEDIA_B: PNG, short_media: PNG}),
            ocr=_OCR(text="Y" * (nv.MIN_OCR_CHARS - 1)))
        self.assertEqual(stats["skipped_low_signal"], 2)
        self.assertEqual(stats["chunks_written"], 0)
        self.assertEqual(stats["artifacts_written"], 0)
        self.assertEqual(len(self._chunks()), 2)  # only the >= 20-char captures
        self.assertTrue(all(len(c["document_text"]) >= nv.MIN_OCR_CHARS
                            for c in self._chunks()))

    def test_chunk_text_capped(self):
        rec = _record("https://livenews/itc", "ITC target", "ITC news body",
                      media_url=MEDIA_A, symbols=[])
        self._persist(rec)
        nv.capture_images([rec], repo=self.repo, fetcher=_Fetcher({MEDIA_A: JPEG}),
                          ocr=_OCR(text="Z" * (nv.MAX_OCR_TEXT * 2)))
        text = self._chunks()[0]["document_text"]
        self.assertEqual(len(text), nv.MAX_OCR_TEXT)
        self.assertTrue(text.startswith(nv.CHUNK_PREFIX))

    def test_keep_files_false_deletes_only_after_write(self):
        rec = _record("https://livenews/itc", "ITC target", "ITC news body",
                      media_url=MEDIA_A, symbols=["TCS"])
        self._persist(rec)
        stats = nv.capture_images([rec], repo=self.repo,
                                  fetcher=_Fetcher({MEDIA_A: JPEG}), ocr=_OCR(),
                                  keep_files=False)
        self.assertEqual(stats["chunks_written"], 1)
        self.assertEqual(stats["artifacts_written"], 1)
        self.assertEqual(stats["files_deleted"], 1)
        self.assertFalse(self._image_path(MEDIA_A).exists())
        # Rows survive the file purge (the text is the durable artifact).
        self.assertEqual(len(self._chunks()), 1)
        self.assertEqual(len(self._artifacts()), 1)
        self.assertEqual(self._artifacts()[0]["local_path"],
                         str(self._image_path(MEDIA_A)))

    def test_download_failure_keeps_file_and_writes_nothing(self):
        rec = _record("https://livenews/itc", "ITC target", "ITC news body",
                      media_url=MEDIA_A, symbols=["TCS"])
        self._persist(rec)
        stats = nv.capture_images([rec], repo=self.repo,
                                  fetcher=_Fetcher({MEDIA_A: (HTML, "text/html")}),
                                  ocr=_OCR())
        self.assertEqual(stats["downloaded"], 0)
        self.assertEqual(stats["chunks_written"], 0)
        self.assertEqual(stats["artifacts_written"], 0)
        self.assertEqual(stats["files_deleted"], 0)
        self.assertEqual(len(stats["errors"]), 1)
        self.assertIn(MEDIA_A, stats["errors"][0])
        self.assertFalse(self._image_path(MEDIA_A).exists())

    def test_unpersisted_record_reported_not_written(self):
        rec = _record("https://livenews/ghost", "Ghost", "body",
                      media_url=MEDIA_A, symbols=[])
        stats = nv.capture_images([rec], repo=self.repo,
                                  fetcher=_Fetcher({MEDIA_A: JPEG}), ocr=_OCR())
        self.assertEqual(stats["downloaded"], 0)
        self.assertEqual(stats["artifacts_written"], 0)
        self.assertEqual(len(stats["errors"]), 1)
        self.assertIn("no raw_document", stats["errors"][0])

    def test_limit_respected(self):
        recs = [_record(f"https://livenews/{i}", f"T{i}", "body",
                        media_url=f"https://cdn.livemint.com/{i}.jpg", symbols=[])
                for i in range(3)]
        for rec in recs:
            self._persist(rec)
        fetcher = _Fetcher({r["media_url"]: JPEG for r in recs})
        stats = nv.capture_images(recs, repo=self.repo, limit=1, fetcher=fetcher,
                                  ocr=_OCR())
        self.assertEqual(stats["attempted"], 1)
        self.assertEqual(stats["downloaded"], 1)
        self.assertEqual(len(fetcher.calls), 1)

    def test_no_media_never_touches_network(self):
        rec = _record("https://livenews/plain", "Plain", "body")
        self._persist(rec)
        with mock.patch.object(nv, "_get_session",
                               side_effect=AssertionError("network touched")):
            stats = nv.capture_images([rec], repo=self.repo, ocr=_OCR())
        self.assertEqual(stats["skipped_no_media"], 1)
        self.assertEqual(stats["attempted"], 1)

    def test_never_raises_on_bad_input(self):
        self.assertEqual(nv.capture_images(None, repo=self.repo)["attempted"], 0)
        stats = nv.capture_images(123, repo=self.repo)
        self.assertEqual(stats["attempted"], 0)
        self.assertTrue(stats["errors"])
        stats = nv.capture_images([{"text": "x", "media_url": "m"}, "junk"],
                                  repo=self.repo, fetcher=_Fetcher({}), ocr=_OCR())
        self.assertEqual(stats["attempted"], 2)
        self.assertTrue(any("not a mapping" in e for e in stats["errors"]))
        stats = nv.capture_images(
            [_record("https://livenews/itc", "T", "b", media_url=MEDIA_A)],
            repo=object(), db=object())
        self.assertEqual(stats["downloaded"], 0)
        self.assertTrue(any("db unavailable" in e for e in stats["errors"]))

    def test_missing_ocr_engine_writes_nothing(self):
        rec = _record("https://livenews/itc", "T", "b", media_url=MEDIA_A,
                      symbols=[])
        self._persist(rec)
        with mock.patch.object(nv, "_get_ocr_engine",
                               side_effect=AssertionError("engine built")):
            stats = nv.capture_images([rec], repo=self.repo,
                                      fetcher=_Fetcher({MEDIA_A: JPEG}))
            # No engine -> empty OCR -> treated as low signal, never a chunk.
            self.assertEqual(nv.ocr_image("x.jpg"), {"text": "", "confidence": 0.0})
        self.assertEqual(stats["downloaded"], 1)
        self.assertEqual(stats["ocr_ok"], 0)
        self.assertEqual(stats["skipped_low_signal"], 1)
        self.assertEqual(stats["chunks_written"], 0)
        self.assertEqual(stats["artifacts_written"], 0)
        self.assertEqual(self._artifacts(), [])


if __name__ == "__main__":
    unittest.main()
