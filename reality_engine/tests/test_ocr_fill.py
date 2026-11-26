"""T-242: selection, the ocr_page row, resume, model rotation and per-route AIMD for the free OCR fill."""
import csv
import json
import shutil
import sqlite3
from pathlib import Path

import pytest

from reality_engine.scripts import ocr_fill as of
from reality_engine.v2 import page_words as pw

TMP = Path(".tmp/test_ocr_fill")
NEMOTRON = "ocr_nemotron_vl"
DEEPSEEK = "ocr_deepseek_flash_vl"


def _picked(reader, route: str = "zen") -> str:
    """The id of the model the reader would call next (model_for waits, so never None here)."""
    model = reader.model_for(route)
    assert model is not None
    return model["id"]


def _fresh(name: str) -> Path:
    path = TMP / name
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True)
    return path


def _store(root: Path, name: str, routes: list[dict], docs: list[tuple]) -> Path:
    """A universe store directory: ``<name>.db`` with a doc table plus its routes.csv."""
    store_dir = root / name
    store_dir.mkdir(parents=True)
    con = sqlite3.connect(store_dir / f"{name}.db")
    con.executescript("CREATE TABLE doc (doc_key TEXT PRIMARY KEY, symbol TEXT, doc_type TEXT, "
                      "known_at TEXT, source_key TEXT);")
    con.executemany("INSERT INTO doc VALUES (?,?,?,?,?)", docs)
    con.commit()
    con.close()
    with (store_dir / "routes.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["doc_key", "page", "doc_type", "route", "reason",
                                                "word_source", "quality"])
        writer.writeheader()
        writer.writerows(routes)
    return store_dir


def _pdf(tmp: Path, name: str = "page.pdf") -> Path:
    import pymupdf

    path = tmp / name
    doc = pymupdf.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    return path


ROUTES = [
    {"doc_key": "a.pdf", "page": 1, "doc_type": "deck", "route": "needs_ocr",
     "reason": "text layer none: fewer than 20 non-space characters; no OCR words yet", "word_source": "script_text",
     "quality": "none"},
    {"doc_key": "a.pdf", "page": 2, "doc_type": "deck", "route": "needs_ocr",
     "reason": "text layer jumbled: label-dictionary share 0.50 < 0.75", "word_source": "script_text", "quality": "none"},
    {"doc_key": "a.pdf", "page": 3, "doc_type": "deck", "route": "table_or_chart", "reason": "numbered table",
     "word_source": "script_text", "quality": "ok"},
    {"doc_key": "b.pdf", "page": 1, "doc_type": "results", "route": "needs_ocr",
     "reason": "text layer none: fewer than 20 non-space characters; no OCR words yet", "word_source": "script_text",
     "quality": "none"},
    {"doc_key": "missing.pdf", "page": 1, "doc_type": "deck", "route": "needs_ocr",
     "reason": "text layer none: fewer than 20 non-space characters; no OCR words yet", "word_source": "script_text",
     "quality": "none"},
]


def test_select_keeps_only_image_only_deck_pages():
    root = _fresh("select")
    _store(root, "c01", ROUTES, [("a.pdf", "AAA", "deck", "2026-01-01", "D:/raw/a.pdf"),
                                 ("b.pdf", "BBB", "results", "2026-01-02", "D:/raw/b.pdf")])
    pages = of.select(root)
    assert [(p["doc_key"], p["page"]) for p in pages] == [("a.pdf", 1)]
    assert pages[0]["symbol"] == "AAA"
    assert pages[0]["pdf"] == "D:/raw/a.pdf"
    assert pages[0]["store"].endswith("c01.db")


def test_select_symbol_filter_seed_and_limit():
    root = _fresh("select_filter")
    for name, symbol in (("c01", "AAA"), ("c02", "BBB")):
        _store(root, name, [dict(ROUTES[0]), {**ROUTES[0], "page": 4}],
               [("a.pdf", symbol, "deck", "2026-01-01", f"D:/raw/{name}.pdf")])
    assert [p["symbol"] for p in of.select(root, symbols=["bbb"])] == ["BBB", "BBB"]
    first = of.select(root, seed=1125, limit=3)
    assert len(first) == 3
    assert of.select(root, seed=1125, limit=3) == first
    assert of.select(root, limit=100) == sorted(of.select(root), key=lambda p: (p["store"], p["doc_key"], p["page"]))


def test_pseudo_words_one_per_line_and_reader_reads_them():
    text = "Revenue 1,234\n\nPAT 56 (7%)\nEBITDA margin 12.5%"
    words = of.pseudo_words(text)
    assert [w[4] for w in words] == ["Revenue 1,234", "PAT 56 (7%)", "EBITDA margin 12.5%"]
    assert [w[1] for w in words] == sorted(w[1] for w in words)
    assert words[0][2] == float(len("Revenue 1,234"))
    assert of.figures(text) == 4

    db = TMP / "read_shapes.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(of.SCHEMA)
    con.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", text, json.dumps(words), None, len(words), 150, 1.0,
                 NEMOTRON))
    con.commit()
    con.close()
    assert [w[4] for w in pw.ocr_words([db], "a.pdf", 1)] == [w[4] for w in words]


def test_run_writes_row_under_out_dir_only(monkeypatch):
    root = _fresh("write")
    pdf = _pdf(root)
    store_dir = _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    pages = of.select(root / "u")
    out_dir = root / "out"
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")
    monkeypatch.setattr(of, "ask", lambda route, png, timeout=420, model=None: "Revenue 1,234\nPAT 56")
    stats = of.run(pages, ["kilo"], out_dir=out_dir, enabled={"kilo": True}, start_workers=1, max_workers=1)

    out = out_dir / "c01_ocr.db"
    assert out.is_file()
    assert not (store_dir / "c01_ocr.db").exists()          # nothing beside the live store
    con = sqlite3.connect(f"file:{out.as_posix()}?mode=ro", uri=True)
    row = con.execute("SELECT symbol, doc_key, page, doc_type, known_at, text, words_json, ocr_conf, n_boxes, dpi, "
                      "method FROM ocr_page").fetchone()
    con.close()
    assert row[:6] == ("AAA", "a.pdf", 1, "deck", "2026-01-01", "Revenue 1,234\nPAT 56")
    assert len(json.loads(row[6])) == 2
    assert row[7] is None and row[8] == 2 and row[9] == 150 and row[10] == NEMOTRON
    assert stats["written"] == 1 and stats["route"]["kilo"] == 1 and stats["pages_with_4_figures"] == 0
    assert stats["limits"] == {"kilo": 1}
    assert stats["models"]["nvidia/nemotron-3.5-super-vl:free"]["ok"] == 1
    assert (out_dir / "ocr_fill.jsonl").is_file()
    assert (out_dir / "samples.txt").is_file()


def test_resume_skips_and_never_overwrites_another_method(monkeypatch):
    root = _fresh("resume")
    pdf = _pdf(root)
    _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    pages = of.select(root / "u")
    out_dir = root / "out"
    calls: list[str] = []

    def fake_ask(route, png, timeout=420, model=None):
        calls.append(route)
        return f"Revenue {len(calls)}"

    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")
    monkeypatch.setattr(of, "ask", fake_ask)
    of.run(pages, ["kilo"], out_dir=out_dir, enabled={"kilo": True}, start_workers=1, max_workers=1)
    assert calls == ["kilo"]
    first = of._held(out_dir / "c01_ocr.db")[("AAA", "a.pdf", 1)]
    assert first == NEMOTRON

    stats = of.run(pages, ["kilo"], out_dir=out_dir, resume=True, enabled={"kilo": True},
                   start_workers=1, max_workers=1)
    assert calls == ["kilo"] and stats["skipped"] == 1 and stats["written"] == 0

    stats = of.run(pages, ["kilo"], out_dir=out_dir, resume=False, enabled={"kilo": True},
                   start_workers=1, max_workers=1)
    assert calls == ["kilo", "kilo"] and stats["written"] == 1
    con = sqlite3.connect(out_dir / "c01_ocr.db")
    assert con.execute("SELECT text FROM ocr_page").fetchone()[0] == "Revenue 2"
    con.execute("UPDATE ocr_page SET method='ocr_rapid'")
    con.commit()
    con.close()
    stats = of.run(pages, ["kilo"], out_dir=out_dir, enabled={"kilo": True}, start_workers=1, max_workers=1)
    assert stats["skipped"] == 1 and calls == ["kilo", "kilo"]     # another reader owns the page


def test_resume_treats_every_ocr_fill_model_as_held(monkeypatch):
    root = _fresh("resume_models")
    pdf = _pdf(root)
    _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    pages = of.select(root / "u")
    out_dir = root / "out"
    out_dir.mkdir()
    con = sqlite3.connect(out_dir / "c01_ocr.db")
    con.executescript(of.SCHEMA)
    con.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", "deepseek line",
                 json.dumps(of.pseudo_words("deepseek line")), None, 1, 150, 41.0, DEEPSEEK))
    con.commit()
    con.close()
    calls: list[str] = []
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")
    monkeypatch.setattr(of, "ask",
                        lambda route, png, timeout=420, model=None: calls.append(route) or "Revenue 9")

    stats = of.run(pages, ["zen"], out_dir=out_dir, resume=True, enabled={"zen": True},
                   start_workers=1, max_workers=1)
    assert stats["skipped"] == 1 and stats["written"] == 0 and calls == []   # the other model already read it

    stats = of.run(pages, ["zen"], out_dir=out_dir, enabled={"zen": True}, start_workers=1, max_workers=1)
    assert stats["written"] == 1 and len(calls) == 1                         # our own family: re-read without --resume

    con = sqlite3.connect(out_dir / "c01_ocr.db")
    con.execute("UPDATE ocr_page SET method='ocr_rapid'")
    con.commit()
    con.close()
    stats = of.run(pages, ["zen"], out_dir=out_dir, enabled={"zen": True}, start_workers=1, max_workers=1)
    assert stats["skipped"] == 1 and len(calls) == 1                         # a box reader's page is never overwritten


def test_run_rotates_models_and_logs_route_and_model(monkeypatch, capsys):
    root = _fresh("rotate")
    pdf = _pdf(root)
    _store(root / "u", "c01", [{**ROUTES[0], "page": 1}, {**ROUTES[0], "page": 2}],
           [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    out_dir = root / "out"
    asked: list[tuple[str, str]] = []
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")

    def fake_ask(route, png, timeout=420, model=None):
        assert model is not None
        asked.append((route, model["id"]))
        return "Revenue 1,234"

    monkeypatch.setattr(of, "ask", fake_ask)
    stats = of.run(of.select(root / "u"), ["zen"], out_dir=out_dir, enabled={"zen": True},
                   start_workers=1, max_workers=1)
    assert [mid for _route, mid in asked] == ["nemotron-3.5-super-vl-free", "deepseek-v4.1-flash-free"]
    con = sqlite3.connect(f"file:{(out_dir / 'c01_ocr.db').as_posix()}?mode=ro", uri=True)
    methods = sorted(row[0] for row in con.execute("SELECT method FROM ocr_page"))
    con.close()
    assert methods == [DEEPSEEK, NEMOTRON]
    assert stats["models"]["nemotron-3.5-super-vl-free"]["ok"] == 1
    assert stats["models"]["deepseek-v4.1-flash-free"]["ok"] == 1
    out = capsys.readouterr().out
    assert "ok   zen:nemotron-3.5 AAA" in out
    assert "ok   zen:deepseek-v4.1 AAA" in out


def test_aimd_grows_after_20_ok_and_cuts_on_throttle(capsys):
    reader = of.Reader(["kilo"], 6, 24)
    model = of.FREE_ROUTES["kilo"]["models"][0]
    for _ in range(of.AIMD_WINDOW - 1):
        reader.success("kilo", model, 4.0)
    assert reader.routes["kilo"]["limit"] == 6
    reader.success("kilo", model, 4.0)
    assert reader.routes["kilo"]["limit"] == 7
    assert "limit kilo 6->7 (20 ok)" in capsys.readouterr().out
    reader.throttle("kilo", model)
    assert reader.routes["kilo"]["limit"] == 4                # floor(7 * 0.7)
    assert "limit kilo 7->4 (429)" in capsys.readouterr().out
    for _ in range(50):
        reader.throttle("kilo", model)
    assert reader.routes["kilo"]["limit"] == 1                # never below one


def test_unmeasured_models_first_in_quality_order_then_fastest():
    reader = of.Reader(["zen"], 6, 24)
    nemotron, deepseek = of.FREE_ROUTES["zen"]["models"]
    assert _picked(reader) == nemotron["id"]                   # unmeasured: quality order
    reader.success("zen", nemotron, 58.0)
    assert _picked(reader) == deepseek["id"]                   # the other unmeasured model next
    reader.success("zen", deepseek, 40.0)
    assert _picked(reader) == deepseek["id"]                   # 40 s beats 58 s


def test_every_8th_call_explores_least_recently_used():
    reader = of.Reader(["zen"], 6, 24)
    nemotron, deepseek = of.FREE_ROUTES["zen"]["models"]
    reader.success("zen", nemotron, 100.0)
    reader.success("zen", deepseek, 10.0)
    picks = [_picked(reader) for _ in range(of.EXPLORE_EVERY)]
    assert picks[:-1] == [deepseek["id"]] * (of.EXPLORE_EVERY - 1)
    assert picks[-1] == nemotron["id"]                        # the 8th call probes the slower, unused model


def test_throttle_cools_only_that_model():
    reader = of.Reader(["zen"], 6, 24)
    nemotron, deepseek = of.FREE_ROUTES["zen"]["models"]
    reader.success("zen", nemotron, 10.0)
    reader.success("zen", deepseek, 20.0)
    reader.throttle("zen", nemotron)
    picks = [_picked(reader) for _ in range(of.EXPLORE_EVERY)]
    assert picks == [deepseek["id"]] * of.EXPLORE_EVERY       # nemotron cools, its sibling keeps reading


def test_method_priority_prefers_box_readers():
    assert pw.OCR_METHOD_PRIORITY["ocr_rapid"] < pw.OCR_METHOD_PRIORITY["ocr_nemotron_vl"]
    assert pw.OCR_METHOD_PRIORITY["ocr_textrec"] < pw.OCR_METHOD_PRIORITY["ocr_nemotron_vl"]
    assert pw.OCR_METHOD_PRIORITY["ocr_nemotron_vl"] < pw.OCR_METHOD_PRIORITY["ocr_deepseek_flash_vl"]
    db = TMP / "priority.db"
    db.unlink(missing_ok=True)
    con = sqlite3.connect(db)
    con.executescript(of.SCHEMA)
    con.execute("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", "nemotron line", json.dumps(of.pseudo_words("nemotron line")),
                 None, 1, 150, 1.0, NEMOTRON))
    con.commit()
    assert [w[4] for w in pw.ocr_words([db], "a.pdf", 1)] == ["nemotron line"]
    assert pw._ocr_method([db], "a.pdf", 1) == NEMOTRON
    con.execute("INSERT OR REPLACE INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                ("AAA", "a.pdf", 1, "deck", "2026-01-01", "rapid box", json.dumps([[0, 0, 9, 9, "rapid box", 0.9]]),
                 0.9, 1, 300, 1.0, "ocr_rapid"))
    con.commit()
    con.close()
    assert [w[4] for w in pw.ocr_words([db], "a.pdf", 1)] == ["rapid box"]
    assert pw._ocr_method([db], "a.pdf", 1) == "ocr_rapid"


def test_shared_acl_tempdir_is_writable():
    import tempfile

    original = tempfile.mkdtemp
    with of._shared_acl_tempdirs():
        folder = Path(tempfile.mkdtemp(prefix="ocr_fill_test_"))
        (folder / "a.txt").write_text("x", encoding="utf-8")
    assert (folder / "a.txt").read_text(encoding="utf-8") == "x"
    assert tempfile.mkdtemp is original
    shutil.rmtree(folder, ignore_errors=True)


def test_cli_exposes_adaptive_worker_flags(capsys):
    with pytest.raises(SystemExit) as stop:
        of.main(["--help"])
    assert stop.value.code == 0
    out = capsys.readouterr().out
    assert "--start-workers" in out and "--max-workers" in out


def test_free_only_guard_and_paid_cost_stop(monkeypatch):
    assert of.parse_routes("kilo,zen") == ["kilo", "zen"]
    with pytest.raises(SystemExit):
        of.parse_routes("kilo,step-5-preview@stepfun")
    assert all(m["id"] in of.FREE_IDS for cfg in of.FREE_ROUTES.values() for m in cfg["models"])
    for paid_id in ("mimo-v2.6-flash-free", "hy4-flash-free", "opencode/hy4-flash-free"):
        with pytest.raises(SystemExit):
            of.model_entry("zen", paid_id)
    with pytest.raises(SystemExit):
        of.model_entry("zen", "some-unlisted-vision-model")
    assert of.parse_events('{"type":"step_finish","part":{"cost":0.0}}')[1] == 0.0
    assert of.parse_events('{"type":"text","part":{"text":"hello"}}\n'
                           '{"type":"step_finish","part":{"cost":0.25}}') == ("hello", 0.25, "")

    root = _fresh("paid")
    pdf = _pdf(root)
    _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")

    def paid(route, png, timeout=420, model=None):
        raise of.PaidModel("zen reported a cost of 0.25 on a free model")

    monkeypatch.setattr(of, "ask", paid)
    stats = of.run(of.select(root / "u"), ["zen"], out_dir=root / "out", enabled={"zen": True},
                   start_workers=1, max_workers=1)
    assert stats["paid"] and stats["errors"] == 1 and stats["written"] == 0


def test_classify_slide_parses_json_and_malformed_replies(monkeypatch):
    seen: list[tuple[str, str, str]] = []

    def fake_ask(route, png, timeout=420, model=None, prompt=of.PROMPT):
        seen.append((route, model["id"], prompt))
        ocr_part = prompt.split("OCR text:\n", 1)[-1]
        if "table" in ocr_part:
            return '{"kind": "data_table"}'
        if "chart" in ocr_part:
            return '```json\n{"kind": "data_chart"}\n```'
        if "kpi" in ocr_part:
            return 'Here: {"kind": "kpi_highlights"}'
        if "cover" in ocr_part:
            return '{"kind": "cover_divider", "data": true}'
        if "unknown" in ocr_part:
            return '{"kind": "not_a_real_kind"}'
        return "not json at all {broken"

    monkeypatch.setattr(of, "ask", fake_ask)

    res_table = of.classify_slide(b"png", "Revenue table 100", route="kilo")
    assert res_table["kind"] == "data_table" and res_table["data"] is True
    assert res_table["model"] == "nvidia/nemotron-3.5-super-vl:free"
    assert isinstance(res_table["seconds"], float)
    assert "Revenue table 100" in seen[0][2] and "JSON" in seen[0][2]

    assert of.classify_slide(b"png", "Revenue chart", route="kilo")["data"] is True
    assert of.classify_slide(b"png", "Headline kpi", route="kilo")["kind"] == "kpi_highlights"
    cover = of.classify_slide(b"png", "Welcome cover", route="kilo")
    assert cover["kind"] == "cover_divider" and cover["data"] is False
    unk = of.classify_slide(b"png", "unknown", route="kilo")
    assert unk["kind"] == "other" and unk["data"] is False
    bad = of.classify_slide(b"png", "garbage", route="kilo")
    assert bad["kind"] == "other" and bad["data"] is False

    # ask_http enforces temperature 0 in the request body
    import requests
    from reality_engine.scripts import resource_watchdog
    sent: list[dict] = []

    class _Resp:
        status_code = 200
        def json(self):
            return {"choices": [{"message": {"content": '{"kind": "data_table"}'}}]}

    monkeypatch.setattr(resource_watchdog, "user_env", lambda: {"KILO_API_KEY": "k"})
    monkeypatch.setattr(requests, "post", lambda url, json, headers, timeout: sent.append(json) or _Resp())
    of.ask_http("kilo", b"png", prompt="classify")
    assert sent[0]["temperature"] == 0 and sent[0]["messages"][0]["content"][1]["text"] == "classify"


def test_classify_slide_paid_model_refused_and_throttled(monkeypatch):
    for paid_id in ("hy4-flash-free", "mimo-v2.6-flash-free", "unlisted-model"):
        with pytest.raises(SystemExit):
            of.classify_slide(b"png", "Revenue 10", route="zen", model=paid_id)
    with pytest.raises(SystemExit):
        of.classify_slide(b"png", "Revenue 10", route="stepfun")

    reader = of.Reader(["kilo"], 6, 24)
    monkeypatch.setattr(of, "ask", lambda *a, **kw: (_ for _ in ()).throw(of.Throttled("429")))
    with pytest.raises(of.Throttled):
        of.classify_slide(b"png", "Revenue 10", route="kilo", reader=reader)
    assert reader.routes["kilo"]["throttled"] == 1 and reader.routes["kilo"]["limit"] == 4


def test_cli_classify_idempotent_upsert_and_data_slide_pages(monkeypatch):
    root = _fresh("classify")
    pdf = _pdf(root)
    _store(root / "u", "c01", [ROUTES[0]], [("a.pdf", "AAA", "deck", "2026-01-01", str(pdf))])
    out_dir = root / "out"
    out_dir.mkdir()
    ocr_db = out_dir / "c01_ocr.db"
    con = sqlite3.connect(ocr_db)
    con.executescript(of.SCHEMA)
    rows_in = [
        ("AAA", "a.pdf", 1, "deck", "2026-01-01", "Revenue 100", json.dumps(of.pseudo_words("Revenue 100")),
         None, 1, 150, 1.0, NEMOTRON),
        ("AAA", "a.pdf", 2, "deck", "2026-01-01", "Investor Presentation",
         json.dumps(of.pseudo_words("Investor Presentation")), None, 1, 150, 1.0, NEMOTRON),
        ("AAA", "a.pdf", 3, "deck", "2026-01-01", "Shop Now 50% off",
         json.dumps(of.pseudo_words("Shop Now 50% off")), None, 1, 150, 1.0, DEEPSEEK),
    ]
    con.executemany("INSERT INTO ocr_page VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows_in)
    con.commit()
    con.close()

    assert of.data_slide_pages(out_dir / "missing_ocr.db") == set()
    assert of.data_slide_pages(ocr_db) == set()                   # table missing -> empty (quarantined)

    from reality_engine.scripts import resource_watchdog
    monkeypatch.setattr(resource_watchdog, "user_env", lambda: {"KILO_API_KEY": "k"})
    monkeypatch.setattr(of, "render_page", lambda pdf_path, page: b"png")
    replies = {"Revenue": '{"kind": "data_table"}', "Investor": '{"kind": "cover_divider"}',
               "Shop": '{"kind": "advert_product_photo"}'}
    calls: list[str] = []

    def fake_ask(route, png, timeout=420, model=None, prompt=of.PROMPT):
        calls.append(route)
        for needle, reply in replies.items():
            if needle in prompt:
                return reply
        return '{"kind": "other"}'

    monkeypatch.setattr(of, "ask", fake_ask)
    rc = of.main(["--classify", "--out-dir", str(out_dir), "--universe", str(root / "u"),
                  "--routes", "kilo", "--start-workers", "1", "--max-workers", "1"])
    assert rc == 0 and len(calls) == 3

    con = sqlite3.connect(f"file:{ocr_db.as_posix()}?mode=ro", uri=True)
    assert con.execute("SELECT * FROM ocr_page ORDER BY page").fetchall() == rows_in
    kinds = con.execute("SELECT symbol, doc_key, page, kind, data, model FROM ocr_slide_kind ORDER BY page").fetchall()
    con.close()
    assert kinds == [
        ("AAA", "a.pdf", 1, "data_table", 1, "nvidia/nemotron-3.5-super-vl:free"),
        ("AAA", "a.pdf", 2, "cover_divider", 0, "nvidia/nemotron-3.5-super-vl:free"),
        ("AAA", "a.pdf", 3, "advert_product_photo", 0, "nvidia/nemotron-3.5-super-vl:free"),
    ]
    assert of.data_slide_pages(ocr_db) == {("a.pdf", 1)}

    # --resume skips already-classified pages
    rc = of.main(["--classify", "--resume", "--out-dir", str(out_dir), "--universe", str(root / "u"),
                  "--routes", "kilo", "--start-workers", "1", "--max-workers", "1"])
    assert rc == 0 and len(calls) == 3

    # Re-running without --resume upserts idempotently (no duplicate rows)
    replies["Investor"] = '{"kind": "kpi_highlights"}'
    rc = of.main(["--classify", "--out-dir", str(out_dir), "--universe", str(root / "u"),
                  "--routes", "kilo", "--start-workers", "1", "--max-workers", "1"])
    assert rc == 0 and len(calls) == 6
    con = sqlite3.connect(f"file:{ocr_db.as_posix()}?mode=ro", uri=True)
    assert con.execute("SELECT COUNT(*) FROM ocr_slide_kind").fetchone()[0] == 3
    con.close()
    assert of.data_slide_pages(ocr_db) == {("a.pdf", 1), ("a.pdf", 2)}
