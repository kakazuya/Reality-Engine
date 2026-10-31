"""Offline tests for the pilot-60 history fetcher (no network, no live DB, temp dirs only)."""

import csv
import shutil
import sqlite3
import unittest
from pathlib import Path

from reality_engine.scripts import fetch_pilot60_history as ph

TMPROOT = Path(__file__).resolve().parents[2] / ".tmp" / "tests"
PDF = b"%PDF-1.7\n" + b"x" * 32
HTML = b"<html>blocked</html>"


class FakeResponse:
    def __init__(self, status_code, content=b""):
        self.status_code = status_code
        self.content = content


class FakeSession:
    """Queued responses per URL; the last response repeats."""

    def __init__(self, responses):
        self.responses = {u: list(r) for u, r in responses.items()}
        self.calls = []

    def get(self, url, headers=None, timeout=None):
        self.calls.append(url)
        queue = self.responses.get(url) or [FakeResponse(404)]
        return queue.pop(0) if len(queue) > 1 else queue[0]


def pacer():
    return ph.Pacer(0.0, sleep=lambda s: None)


class Case(unittest.TestCase):
    def setUp(self):
        TMPROOT.mkdir(parents=True, exist_ok=True)
        self.tmp = TMPROOT / self.id().rsplit(".", 1)[-1]
        shutil.rmtree(self.tmp, ignore_errors=True)
        self.tmp.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def meta(self, **kw):
        row = {"newsid": "N1", "attachment": "a.pdf", "headline": "", "newssub": "",
               "category": "", "subcat": "", "dissem_ts": "2022-05-10T10:00:00",
               "symbol": "BOSCHLTD", "isin": "INE323A01026", "symbol_at_time": "BOSCHLTD",
               "code": "500530", "source": "bse_ann"}
        row.update(kw)
        return row


class ClassifyTests(Case):
    def test_buckets(self):
        cases = {
            "annual_report": dict(subcat="Annual Report", headline="Annual Report 2022-23"),
            "investor_presentation": dict(subcat="Investor Presentation",
                                          headline="Investor Presentation Q2 FY24"),
            "concall_transcript": dict(subcat="Earnings Call Transcript",
                                       headline="Transcript of earnings call"),
            "concall_audio_link": dict(subcat="Analyst / Investor Meet",
                                       headline="Audio recording of earnings call"),
            "quarterly_results": dict(category="Result", subcat="Financial Results",
                                      headline="Unaudited financial results"),
            "results_press_release": dict(category="Result", subcat="Press Release",
                                          headline="Press release on financial results"),
            "material_filing": dict(subcat="Award of Order", headline="Award of order"),
        }
        for bucket, fields in cases.items():
            self.assertEqual(ph.classify(self.meta(**fields))[0], bucket, bucket)

    def test_routine_skips(self):
        for subcat, headline in (
                ("Trading Window", "Closure of trading window"),
                ("Newspaper Publication", "Newspaper publication of notice"),
                ("Loss of Share Certificate", "Loss of share certificate"),
                ("Compliance Certificate", "Compliance certificate under Reg 74(5)"),
                ("General", "Certificate under Regulation 7(3) and 40(9)")):
            bucket, reason = ph.classify(self.meta(subcat=subcat, headline=headline))
            self.assertEqual(bucket, "skip", subcat)
            self.assertTrue(reason.startswith("routine:"), reason)

    def test_window_boundaries(self):
        self.assertTrue(ph.in_window("2019-01-01T00:00:00"))
        self.assertTrue(ph.in_window("2024-03-31T23:59:59"))
        self.assertFalse(ph.in_window("2018-12-31T23:59:59"))
        self.assertFalse(ph.in_window("2024-04-01T00:00:00"))

    def test_fiscal_year(self):
        self.assertEqual(ph.fiscal_year("2023-08-11T10:00:00", "annual_report",
                                        "Annual Report 2022-23"), 2023)
        self.assertEqual(ph.fiscal_year("2023-08-11T10:00:00", "annual_report", ""), 2023)
        self.assertEqual(ph.fiscal_year("2023-05-20T10:00:00", "quarterly_results"), 2023)
        self.assertEqual(ph.fiscal_year("2023-08-20T10:00:00", "quarterly_results"), 2024)
        self.assertEqual(ph.fiscal_year("2024-02-10T10:00:00", "quarterly_results"), 2024)
        self.assertEqual(ph.fiscal_year("2023-07-10T10:00:00", "material_filing"), 2024)


class UniverseTests(Case):
    def test_custom_universe_file(self):
        path = self.tmp / "universe.csv"
        path.write_text("isin,symbol\nINE000000001,AAA\nINE000000002,BBB\n", encoding="utf-8")
        rows = ph.load_universe(path)
        self.assertEqual([r["symbol"] for r in rows], ["AAA", "BBB"])


class DownloadTests(Case):
    def test_pdf_ok(self):
        row = self.meta()
        session = FakeSession({ph.PDF_URLS[0].format(name="a.pdf"): [FakeResponse(200, PDF)]})
        status, body, http, attempts, error = ph.download(row, session, pacer())
        self.assertEqual((status, http, attempts, error), ("ok", 200, 1, None))
        self.assertEqual(body, PDF)

    def test_html_is_not_fetched(self):
        row = self.meta()
        session = FakeSession({ph.PDF_URLS[0].format(name="a.pdf"): [FakeResponse(200, HTML)]})
        status, body, http, attempts, error = ph.download(row, session, pacer())
        self.assertEqual(status, "error")
        self.assertIn("not a PDF", error)
        self.assertEqual(attempts, 1)

    def test_attachhis_404_falls_back_to_attachlive(self):
        row = self.meta()
        session = FakeSession({
            ph.PDF_URLS[0].format(name="a.pdf"): [FakeResponse(404)],
            ph.PDF_URLS[1].format(name="a.pdf"): [FakeResponse(200, PDF)],
        })
        status, _body, http, attempts, _error = ph.download(row, session, pacer())
        self.assertEqual((status, http, attempts), ("ok", 200, 2))
        self.assertTrue(row["url"].startswith(ph.PDF_URLS[1].split("{")[0]))

    def test_no_attachment_is_no_file(self):
        status, _b, _h, attempts, error = ph.download(
            self.meta(attachment=None), FakeSession({}), pacer())
        self.assertEqual(status, "no_file")
        self.assertIn("no attachment", error)
        self.assertEqual(attempts, 0)


class ManifestTests(Case):
    def test_round_trip_and_resume_state(self):
        m = ph.Manifest(self.tmp / "manifest.db")
        row = self.meta()
        rec = ph._record(row, "ok", http_status=200, attempts=1,
                         local_path=self.tmp / "a.pdf", bytes=10, sha="x")
        (self.tmp / "a.pdf").write_bytes(PDF)
        m.put(rec)
        self.assertEqual(m.done()["N1"][0], "ok")
        self.assertEqual(m.rows()[0]["bucket"], None)
        n = m.write_csv(self.tmp / "manifest.csv")
        self.assertEqual(n, 1)
        with (self.tmp / "manifest.csv").open(encoding="utf-8") as f:
            got = list(csv.DictReader(f))
        self.assertEqual(list(got[0].keys()), ph.CSV_FIELDS)
        self.assertEqual(got[0]["newsid"], "N1")

    def test_skip_rows_keep_reason(self):
        m = ph.Manifest(self.tmp / "manifest.db")
        row = self.meta(bucket="skip", skip_reason="routine: trading window closure")
        m.put(ph._record(row, "skipped", skip=row["skip_reason"]))
        got = m.rows()[0]
        self.assertEqual(got["status"], "skipped")
        self.assertTrue(got["skip_reason"].startswith("routine:"))

    def test_target_path_layout(self):
        p = ph.target_path("BOSCHLTD", "annual_report", "abc")
        self.assertEqual(p.parts[-3:], ("BOSCHLTD", "annual_report", "abc.pdf"))
        nse = ph.target_path("PANACHE", "material_filing", "nse:5027463")
        self.assertNotIn(":", nse.name)  # a colon would create an NTFS data stream
        self.assertEqual(nse.name, "nse_5027463.pdf")


class PacerTests(Case):
    def test_pacer_spaces_requests(self):
        now = {"t": 100.0}
        sleeps = []
        p = ph.Pacer(0.3, sleep=lambda s: sleeps.append(s), clock=lambda: now["t"])
        p.wait()
        p.wait()
        p.wait()
        self.assertEqual([round(s, 3) for s in sleeps], [0.3, 0.6])
        now["t"] += 10.0
        p.wait()  # clock moved past the reservation: no forced extra wait
        self.assertEqual(len(sleeps), 2)


class NseTests(Case):
    def test_plan_and_download_keep_a_direct_url(self):
        row = self.meta(newsid="nse:123", source="nse", attachment=None, code="",
                        url="https://nsearchives.nseindia.com/corporate/X.pdf", url_direct=True)
        rows = ph.plan({"nse:123": row}, {})
        self.assertEqual(rows[0]["url"], "https://nsearchives.nseindia.com/corporate/X.pdf")
        session = FakeSession({rows[0]["url"]: [FakeResponse(200, PDF)]})
        status, _body, http, attempts, _error = ph.download(rows[0], session, pacer())
        self.assertEqual((status, http, attempts), ("ok", 200, 1))
        self.assertEqual(session.calls, [rows[0]["url"]])


class VerifyTests(Case):
    def test_content_check_flags_a_mismatch(self):
        import fitz

        good = self.tmp / "good.pdf"
        doc = fitz.open()
        doc.new_page().insert_text(
            (40, 60), "BOSCH LIMITED\nUnaudited financial results for the quarter ended March 31, 2023")
        doc.save(good)
        doc.close()
        m = ph.Manifest(self.tmp / "manifest.db")
        m.put(ph._record(self.meta(newsid="A", bucket="quarterly_results",
                                   headline="Unaudited financial results for the quarter",
                                   symbol_at_time="BOSCHLTD"),
                         "ok", local_path=good, bytes=good.stat().st_size))
        other = self.tmp / "other.pdf"
        doc = fitz.open()
        doc.new_page().insert_text(
            (40, 60), "COMPLETELY UNRELATED TEXT ABOUT COTTON AND SUGAR AND STEEL AND CEMENT")
        doc.save(other)
        doc.close()
        m.put(ph._record(self.meta(newsid="B", bucket="material_filing",
                                   headline="Board meeting outcome", symbol_at_time="BOSCHLTD"),
                         "ok", local_path=other, bytes=other.stat().st_size))
        resolved = {"BOSCHLTD": {"name": "BOSCH LIMITED"}}
        out = self.tmp / "check.md"
        got = ph.verify_files(m, resolved, sample=2, out_path=out)
        self.assertEqual(got["checked"], 2)
        self.assertEqual(got["verdicts"].get("ok"), 1)
        self.assertEqual(got["verdicts"].get("MISMATCH: neither company nor headline"), 1)
        self.assertTrue(out.exists())


if __name__ == "__main__":
    unittest.main()
