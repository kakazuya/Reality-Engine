"""Offline tests for the deck-figure extraction pipeline (no network, no live DB)."""
import os
import tempfile
import time
import unittest

os.environ.setdefault("OPENCODE_GO_API_KEY", "test")
from reality_engine.scripts import extract_deck_figures as x


class ParseTests(unittest.TestCase):
    def test_numbers_keep_sign_and_lakh_grouping(self):
        self.assertEqual(x.parse_number("28,00,000"), 2800000.0)
        self.assertEqual(x.parse_number("(1.44)"), -1.44)
        self.assertEqual(x.parse_number("₹4.8"), 4.8)
        self.assertEqual(x.parse_number("18.2%"), 18.2)
        self.assertEqual(x.parse_number("9,7"), 9.7)        # decimal comma
        self.assertEqual(x.parse_number("-7,95%"), -7.95)
        self.assertEqual(x.parse_number("1,000"), 1000.0)   # thousands grouping unchanged
        self.assertEqual(x.parse_number("12,34,567"), 1234567.0)

    def test_currency_scale_unit(self):
        self.assertEqual(x.currency_scale_unit("Revenue", "7,571MM", "INR"), "Rs Mn")            # suffix on the number
        self.assertEqual(x.currency_scale_unit("Planned Capex (Mn)", "11,920", "Rs."), "Rs Mn")  # scale in the label
        self.assertIsNone(x.currency_scale_unit("Revenue", "1,234", "Rs", "Figures Rs. in Lacs"))  # page text not used
        self.assertIsNone(x.currency_scale_unit("Shares O/S (Mn)", "9.7", "INR"))               # a count, not money
        self.assertIsNone(x.currency_scale_unit("Infra plan", "Rs. 9.15 lakh crore", "Rs."))     # lakh crore: leave
        self.assertIsNone(x.currency_scale_unit("Revenue", "1,234 Cr", "Rs Cr"))                # unit already scaled

    def test_header_skipped_but_literal_metric_label_kept(self):
        out = ("TITLE | New Project Launches\n"
               "metric | period | number | unit\n"
               "metric | - | 869,578 | sft\n"
               "Revenue | Q1FY27 | 1,234.5 | Rs Cr\n")
        facts = x.parse_facts(out)
        self.assertEqual([f["value"] for f in facts], [869578.0, 1234.5])

    def test_period_in_number_slot_falls_back_to_real_number(self):
        facts = x.parse_facts("Revenue | - | FY27 | 512 | Rs Cr")
        self.assertEqual(facts[0]["value"], 512.0)

    def test_identifiable_share_penalises_collapsed_labels(self):
        collapsed = x.parse_facts("Revenue mix | Q1FY27 | 63% | %\nRevenue mix | Q1FY27 | 24% | %\nCash | Q1FY27 | 63% | %")
        self.assertAlmostEqual(x.identifiable_share(collapsed), 1 / 3)
        self.assertIsNone(x.identifiable_share([]))

    def test_prompt_carries_context_and_text_layer(self):
        p = x.build_prompt({"symbol": "SOBHA", "company": "Sobha Ltd", "known_at": "2026-08-12T19:00", "text": "Area 869,578 sft"})
        self.assertIn("Sobha Ltd", p); self.assertIn("2026-08-12", p); self.assertIn("869,578", p)
        self.assertNotIn("<<<", x.build_prompt({"symbol": "X", "text": "  "}))

    def test_text_reference_ignores_labels_and_dates(self):
        nums = x.text_numbers("Revenue 1QFY26 was 1,234.5 cr; Sector 63A; signed 2026.08.28; margin 18.2%")
        self.assertEqual(nums, {1234.5, 18.2})


class LimiterTests(unittest.TestCase):
    def test_backoff_and_recovery(self):
        lim = x.AdaptiveLimiter(start=100, floor=20, ceiling=120, step=5, step_every=2, pause=0)
        lim.acquire(); lim.release(throttled=True)
        self.assertEqual(lim.limit, 60)
        for _ in range(4):
            lim.acquire(); lim.release()
        self.assertEqual(lim.limit, 70)
        for _ in range(10):
            lim.acquire(); lim.release(throttled=True)
        self.assertEqual(lim.limit, 20)


class SpendTests(unittest.TestCase):
    def test_cap_blocks_until_window_frees(self):
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            ledger = x.SpendLedger(store, margin=1.0, est_usd=0.0)
            m = "muse-spark-1.3-contributor"   # a capped model
            self.assertEqual(ledger.wait_seconds(m), 0.0)
            ledger.record(m, 0, 0)
            store.execute("INSERT INTO spend VALUES (?,?,?,?,?)", (time.time() - 3600, m, 0, 0, 12.0))  # 5-h cap used up
            wait = ledger.wait_seconds(m)
            self.assertGreater(wait, 3 * 3600)        # frees when the hour-old row leaves the 5-h window
            self.assertLess(wait, 4 * 3600 + 1)
            free = "longcat-2.5-preview-free"
            store.execute("INSERT INTO spend VALUES (?,?,?,?,?)", (time.time(), free, 0, 0, 999.0))
            self.assertEqual(ledger.wait_seconds(free), 0.0)   # free models never wait on a cap
            store.con.close()



def fake_render(path, skip_pages):
    """Stand-in for render_doc in a child process: 'crash' paths kill the process like a MuPDF fault."""
    if "crash" in path:
        os._exit(1)
    return 2, [{"page_no": 1, "route": "skip"}, {"page_no": 2, "route": "skip"}]


class RendererIsolationTests(unittest.TestCase):
    def test_crashing_pdf_is_skipped_and_others_still_render(self):
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            r = x.Renderer(store, procs=2, ahead=3, timeout=60, fn=fake_render)
            docs = [{"sha256": f"s{i}", "path": p} for i, p in enumerate(["a.pdf", "crash.pdf", "b.pdf", "c.pdf"])]
            try:
                got = [doc["path"] for doc, n, pages in r.run(docs, lambda doc: set())]
            finally:
                r.close()
            self.assertEqual(sorted(got), ["a.pdf", "b.pdf", "c.pdf"])
            self.assertEqual(store.query("SELECT sha256, strikes FROM bad_docs"), [("s1", x.MAX_STRIKES)])
            store.con.close()


class ChooseTests(unittest.TestCase):
    def test_overflow_goes_to_alternate_with_room(self):
        class C: pass
        c = C()
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            c.ledger = x.SpendLedger(store, margin=1.0, est_usd=0.0)
            c.limiters = {"longcat-2.5-preview-free": x.AdaptiveLimiter(1, 1, 1), "mimo-v2.6-flash": x.AdaptiveLimiter(1, 1, 1)}
            self.assertEqual(x.choose(c, "longcat-2.5-preview-free", ["mimo-v2.6-flash"]), "longcat-2.5-preview-free")
            c.limiters["longcat-2.5-preview-free"].acquire()   # primary full -> alternate
            self.assertEqual(x.choose(c, "longcat-2.5-preview-free", ["mimo-v2.6-flash"]), "mimo-v2.6-flash")
            store.execute("INSERT INTO spend VALUES (?,?,?,?,?)", (time.time(), "mimo-v2.6-flash", 0, 0, 99.0))  # alternate capped
            self.assertEqual(x.choose(c, "longcat-2.5-preview-free", ["mimo-v2.6-flash"]), "longcat-2.5-preview-free")
            store.con.close()


class BlockTests(unittest.TestCase):
    def test_402_bench_removes_model_from_choice(self):
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            ledger = x.SpendLedger(store, margin=1.0, est_usd=0.0)
            m = "mimo-v2.6-flash"
            self.assertTrue(ledger.has_room(m))
            ledger.block(m, 600)
            self.assertFalse(ledger.has_room(m))
            self.assertGreater(ledger.wait_seconds(m), 500)
            store.con.close()


class GateTests(unittest.TestCase):
    class Page:
        def __init__(self, text, img_cov):
            import pymupdf
            self.rect = pymupdf.Rect(0, 0, 100, 100); self._t = text; self._c = img_cov
        def get_text(self): return self._t
        def get_image_info(self): return [{"bbox": (0, 0, 100, 100 * self._c)}] if self._c else []

    def test_routes(self):
        rich = self.Page("Revenue 1,234 EBITDA 456 PAT 78", 0.0)
        self.assertEqual(x.page_task({}, rich, 1)["route"], "vision")
        self.assertEqual(x.page_task({}, self.Page("Disclaimer page 4", 0.0), 1)["route"], "skip")
        img = self.Page("Highlights", 0.9)
        self.assertEqual(x.page_task({}, img, 1, ocr=lambda p: 5)["route"], "vision")
        self.assertEqual(x.page_task({}, img, 1, ocr=lambda p: 1)["route"], "skip_ocr")
        self.assertEqual(x.page_task({}, img, 1, ocr=lambda p: None)["route"], "vision")   # OCR unavailable: read it


class FakeClient:
    """Stands in for Client: canned answers per model, real limiters and spend ledger."""
    def __init__(self, store, answers, ceilings):
        self.ledger = x.SpendLedger(store, margin=1.0, est_usd=0.0)
        self.limiters = {m: x.AdaptiveLimiter(c, 1, c) for m, c in ceilings.items()}
        self.answers, self.calls = answers, []

    def read(self, model, jpeg_b64, prompt, tries=6, wait_on_cap=True):
        self.calls.append(model); out = self.answers[model]
        if isinstance(out, Exception):
            raise out
        return {"output": out, "seconds": 0.1, "in_tok": 1, "out_tok": 1, "usd": 0.0, "facts": x.parse_facts(out)}


WEAK = "TITLE | Ops\nRevenue | - | 10 | -"   # 1 of 12 text-layer numbers: needs a second reading
STRONG = "TITLE | Ops\n" + "\n".join(f"Segment {i} revenue | Q1FY27 | {i} | Rs Cr" for i in range(1, 13))
TASK = {"sha256": "s1", "page_no": 3, "doc_id": 1, "isin": "INE000000001", "symbol": "X", "doc_type": "INVESTOR_PRESENTATION",
        "known_at": "2026-08-01", "route": "vision", "text_chars": 100, "img_cov": 0.5, "text": "",
        "truth": {float(i) for i in range(1, 13)}}


class RoundRobinTests(unittest.TestCase):
    def test_primaries_take_turns_while_both_have_room(self):
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            prim = ["longcat-2.5-preview-free", "dots-studio/dots-3-note-preview:free"]
            c = FakeClient(store, {m: STRONG for m in prim}, {m: 5 for m in prim})
            for turn in range(4):
                x.process(dict(TASK), "b64", c, False, prim, ["step-5-preview-free"], turn=turn)
            self.assertEqual(c.calls, [prim[0], prim[1], prim[0], prim[1]])
            c.limiters[prim[1]].acquire(); c.limiters[prim[1]].limit = 1   # Dots full: its turn goes to LongCat
            x.process(dict(TASK), "b64", c, False, prim, ["step-5-preview-free"], turn=1)
            self.assertEqual(c.calls[-1], prim[0])
            store.con.close()

    def test_failed_alternate_primary_hands_page_to_main_primary(self):
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            prim = ["longcat-2.5-preview-free", "dots-studio/dots-3-note-preview:free"]
            c = FakeClient(store, {prim[0]: STRONG, prim[1]: RuntimeError("HTTP 400: Provider returned error")}, {m: 5 for m in prim})
            res = x.process(dict(TASK), "b64", c, False, prim, ["step-5-preview-free"], turn=1)
            self.assertEqual(c.calls, [prim[1], prim[0]]); self.assertEqual((res["status"], res["final_model"]), ("ok", prim[0]))
            store.con.close()


class DeferredSecondTests(unittest.TestCase):
    def test_weak_page_is_saved_then_queued_and_finished_by_second_reader(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db"); store = x.Store(path)
            p, s = "longcat-2.5-preview-free", "step-5-preview-free"
            c = FakeClient(store, {p: WEAK, s: STRONG}, {p: 5, s: 5})
            res = x.process(dict(TASK), "b64", c, True, [p], [s], defer=lambda: True)
            self.assertTrue(res["second_pending"]); self.assertEqual(c.calls, [p])   # worker did not wait for Step
            store.save_page(TASK, res); store.enqueue_second(TASK, "b64", res)
            store.con.close()
            store = x.Store(path)   # queue survives a restart
            self.assertEqual(store.second_queue_size(), 1)
            sha, pg, task, b64, r, tries = store.next_second(set(), 5)[0]
            self.assertEqual(store.next_second({(sha, pg)}, 5), [])   # a page being read is not handed out twice
            r = x.second_read(task, b64, c, r, [s])
            store.save_page(task, r); store.drop_second(sha, pg)
            self.assertEqual(r["final_model"], s); self.assertIsNone(r["error"])
            self.assertEqual(store.query("SELECT final_model, status FROM pages"), [(s, "ok")])
            self.assertEqual(store.query("SELECT model, SUM(is_final) FROM facts GROUP BY model ORDER BY model"), [(p, 0), (s, 12)])
            self.assertEqual(store.second_queue_size(), 0)
            store.con.close()

    def test_full_queue_falls_back_to_inline_second_read(self):
        with tempfile.TemporaryDirectory() as d:
            store = x.Store(os.path.join(d, "t.db"))
            p, s = "longcat-2.5-preview-free", "step-5-preview-free"
            c = FakeClient(store, {p: WEAK, s: STRONG}, {p: 5, s: 5})
            res = x.process(dict(TASK), "b64", c, True, [p], [s], defer=lambda: False)
            self.assertNotIn("second_pending", res); self.assertEqual(c.calls, [p, s]); self.assertEqual(res["final_model"], s)
            store.con.close()


if __name__ == "__main__":
    unittest.main()
