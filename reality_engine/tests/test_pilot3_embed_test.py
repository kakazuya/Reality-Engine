"""Tests for the pilot3 embedding retrieval test (``reality_engine/pilot3/embed_test.py``, T-049 G).

Run from the repo root:
    python -m pytest reality_engine/tests/test_pilot3_embed_test.py -q

No network: every test uses ``FakeClient`` (random unit vectors, fake ``usage``) and a tiny pilot3 database
built under ``.tmp/``/``tmp_path`` from the real DDL.  The tests cover batching (16 items, 4 in flight), the
budget stop, resume from the cache, the image item format and PDF rendering, RRF, the hit/MRR metrics on a
3-question fixture, the pool's as_of/date/type filters, and ``embed --dry-run`` + ``eval`` end to end.
"""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import numpy as np
import pytest

import reality_engine.pilot3.embed_test as es
from reality_engine.pilot3 import schema

TYPES = ("transcript", "deck", "results")
ROOT = Path(__file__).resolve().parents[2]
TMP = ROOT / ".tmp"


@pytest.fixture()
def workdir(request):
    """A per-test directory under ``.tmp/`` (pytest's own temp root is denied in the DSH sandbox)."""
    path = TMP / f"embed_test_{request.node.name}"
    shutil.rmtree(path, ignore_errors=True)
    path.mkdir(parents=True, exist_ok=True)
    return path



def make_pdf(path: Path, pages: int = 2) -> bool:
    """A tiny real PDF; False when no renderer is installed."""
    try:
        import pymupdf
    except ImportError:
        return False
    doc = pymupdf.open()
    for number in range(pages):
        page = doc.new_page()
        page.insert_text((72, 72), f"deck page {number + 1}")
    doc.save(str(path))
    doc.close()
    return True


def build_fixture_db(path: Path) -> Path:
    """Three corpus documents plus one too old for the corpus; KEC deck pages point at a real PDF."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    pdf = path.parent / "deck.pdf"
    has_pdf = make_pdf(pdf, 2)
    con = sqlite3.connect(path)
    con.execute(schema.TABLES["doc"])
    con.execute(schema.TABLES["doc_page"])
    con.execute(schema.FTS)
    docs = [
        ("kec/call.pdf", "KEC", "transcript", "Q4 FY26 earnings call", "2026-05-18", "2026-05-18T16:00:00", 3,
         None),
        ("kec/deck.pdf", "KEC", "deck", "Q1 FY27 investor presentation", "2026-07-30", "2026-07-30T17:00:00", 2,
         str(pdf) if has_pdf else None),
        ("baj/results.pdf", "BAJFINANCE", "results", "Q1 FY27 results", "2026-07-25", "2026-07-25T18:00:00", 2,
         None),
        ("kec/old.pdf", "KEC", "transcript", "Q1 FY25 call", "2024-07-01", "2024-07-01T16:00:00", 1, None),
    ]
    con.executemany("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    [(key, symbol, None, doc_type, doc_type, title, filed, known, pages, None, "fixture", pdf_path)
                     for key, symbol, doc_type, title, filed, known, pages, pdf_path in docs])
    pages = [
        ("kec/call.pdf", "KEC", 1, "The company reported revenue growth of 12% for the year.", "2026-05-18T16:00:00"),
        ("kec/call.pdf", "KEC", 2, "The order intake for the year stood at 25,280 crore.", "2026-05-18T16:00:00"),
        ("kec/call.pdf", "KEC", 3, "Margin guidance for the year is 8-8.5%.", "2026-05-18T16:00:00"),
        ("kec/deck.pdf", "KEC", 1, "Order intake grew 20% in the quarter.", "2026-07-30T17:00:00"),
        ("kec/deck.pdf", "KEC", 2, "The order book is 36,267 crore at the end of the quarter.",
         "2026-07-30T17:00:00"),
        ("baj/results.pdf", "BAJFINANCE", 1, "AUM growth of 24% for the year.", "2026-07-25T18:00:00"),
        ("baj/results.pdf", "BAJFINANCE", 2, "Net interest margin was 10.5%.", "2026-07-25T18:00:00"),
        ("kec/old.pdf", "KEC", 1, "Order intake was low.", "2024-07-01T16:00:00"),
    ]
    con.executemany("INSERT INTO doc_page VALUES (?,?,?,?,?,?,?,?)",
                    [(key, symbol, page, text, "script_text", len(text), known, None)
                     for key, symbol, page, text, known in pages])
    con.execute("INSERT INTO doc_page_fts(rowid, text) SELECT rowid, text FROM doc_page")
    con.commit()
    con.close()
    return path


def dummy_pages(count: int, text: str = "order intake for the year " * 60) -> list[es.Page]:
    return [es.Page(doc_key=f"kec/dummy_{number // 4}.pdf", symbol="KEC", page=number % 4 + 1, text=text,
                    known_at="2026-05-18T16:00:00", doc_type="transcript", title="dummy", filing_date="2026-05-18",
                    pdf=None) for number in range(count)]


@pytest.fixture()
def fixture(workdir):
    return build_fixture_db(workdir / "pilot3.db")


def test_plan_lists_counts_and_cost(fixture, capsys):
    es.main(["plan", "--db", str(fixture)])
    out = capsys.readouterr().out
    assert "3 documents, 7 pages" in out          # the 2024-07 document is outside the corpus
    assert "transcript" in out and "deck" in out and "results" in out
    assert "nvidia/Nemotron-3.5-Embed-1B-BF16" in out and "nvidia/Nemotron-3.5-Embed-8B-BF16" in out
    assert "text USD" in out and "image USD" in out


def test_text_item_header_and_truncation():
    page = es.Page("kec/call.pdf", "KEC", 7, "x" * 40_000, "2026-05-18T16:00:00", "transcript", "Q4 call",
                   "2026-05-18", None)
    item = es.text_item(page)
    assert item.startswith("KEC | transcript | Q4 call | filed 2026-05-18 | page 7\n")
    assert item.endswith("x" * 30_000)
    assert len(item) < 30_100


def test_image_item_is_the_content_part_shape():
    page = es.Page("kec/deck.pdf", "KEC", 2, "text", "2026-07-30", "deck", "Q1 deck", "2026-07-30", None)
    parts = es.image_item(page, b"\xff\xd8jpegbytes")
    assert parts[0]["type"] == "text" and parts[0]["text"].startswith("KEC | deck |")
    assert parts[1]["type"] == "image_url"
    assert parts[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    import base64

    assert base64.b64decode(parts[1]["image_url"]["url"].split(",", 1)[1]) == b"\xff\xd8jpegbytes"


def test_render_jpeg_if_a_renderer_is_installed(workdir):
    if not make_pdf(workdir / "deck.pdf", 2):
        pytest.skip("neither PyMuPDF nor pypdfium2 is installed")
    assert es.renderer_name() in {"pymupdf", "pypdfium2"}
    data = es.render_jpeg(workdir / "deck.pdf", 2)
    assert data[:2] == b"\xff\xd8"                # JPEG SOI
    assert len(data) > 1_000


def test_batching_16_items_4_in_flight(workdir):
    pages = dummy_pages(80)
    client = es.FakeClient()
    cache = es.VectorCache(workdir, "1b", "text")
    spend = es.embed_pages(pages, "text", client, "1b", cache, 1.0, 0.0)
    assert len(cache.keys) == 80 and len(cache.matrix) == 80
    assert spend > 0
    assert all(size <= es.BATCH for _task, size in client.calls)
    assert sum(size for _task, size in client.calls) == 80
    assert 2 <= client.peak <= es.PARALLEL
    assert cache.matrix.shape[1] == es.FakeClient.dim


def test_budget_stop_before_a_batch(workdir, capsys):
    pages = dummy_pages(80)
    client = es.FakeClient()
    cache = es.VectorCache(workdir, "1b", "text")
    one_batch = sum(len(es.text_item(page)) // 4 for page in pages[:es.BATCH])
    budget = es.cost_usd("1b", "text", one_batch) * 1.5
    spend = es.embed_pages(pages, "text", client, "1b", cache, budget, 0.0)
    assert 0 < len(cache.keys) < 80
    assert spend <= budget + 1e-12
    assert "STOP before the next" in capsys.readouterr().out


def test_zero_budget_embeds_nothing(workdir):
    client = es.FakeClient()
    cache = es.VectorCache(workdir, "1b", "text")
    spend = es.embed_pages(dummy_pages(20), "text", client, "1b", cache, 0.0, 0.0)
    assert spend == 0.0 and cache.keys == [] and client.calls == []


def test_resume_from_cache_makes_no_request(workdir):
    pages = dummy_pages(20)
    cache = es.VectorCache(workdir, "1b", "text")
    es.embed_pages(pages, "text", es.FakeClient(), "1b", cache, 1.0, 0.0)
    keys = list(cache.keys)
    again = es.FakeClient()
    spend = es.embed_pages(pages, "text", again, "1b", es.VectorCache(workdir, "1b", "text"), 1.0, 0.0)
    assert again.calls == [] and spend == 0.0
    assert list(es.VectorCache(workdir, "1b", "text").keys) == keys


def test_images_probe_skips_a_page_without_a_pdf(workdir):
    if not make_pdf(workdir / "deck.pdf", 2):
        pytest.skip("neither PyMuPDF nor pypdfium2 is installed")
    pages = [es.Page("kec/deck.pdf", "KEC", 1, "text", "2026-07-30", "deck", "Q1 deck", "2026-07-30",
                     str(workdir / "deck.pdf")),
             es.Page("kec/deck.pdf", "KEC", 2, "text", "2026-07-30", "deck", "Q1 deck", "2026-07-30", None)]
    client = es.FakeClient()
    cache = es.VectorCache(workdir, "1b", "image")
    es.embed_pages(pages, "image", client, "1b", cache, 1.0, 0.0)
    assert len(cache.keys) == 1                   # the second page has no PDF on purpose
    assert ("kec/deck.pdf", 1) in cache.keys
    assert cache.matrix.shape == (1, es.FakeClient.dim)


def test_rrf_and_metrics():
    a, b, c = (es.Page("d", "KEC", 1, "", None, "transcript", "", None, None).key,
               es.Page("d", "KEC", 2, "", None, "transcript", "", None, None).key,
               es.Page("d", "KEC", 3, "", None, "transcript", "", None, None).key)
    fused = es.rrf([[a, b, c], [b, c, a]], k=60)
    assert fused[0] == b                          # in both lists at rank 1 and 2
    assert sorted(fused) == sorted([a, b, c])
    # three-question fixture: one hit at rank 1, one at rank 3, one never returned
    golds = [{a}, {c}, {(es.Page("d", "KEC", 9, "", None, "transcript", "", None, None).key)}]
    rankings = [[a, b, c], [b, a, c], [b, a]]
    rows = [es.metrics(ranking, gold) for ranking, gold in zip(rankings, golds)]
    assert rows[0]["rank"] == 1 and rows[0]["hit@1"] == 1.0 and rows[0]["mrr"] == 1.0
    assert rows[1]["rank"] == 3 and rows[1]["hit@1"] == 0.0 and rows[1]["hit@5"] == 1.0
    assert rows[1]["mrr"] == pytest.approx(1 / 3)
    assert rows[2]["rank"] is None and rows[2]["hit@50"] == 0.0 and rows[2]["mrr"] == 0.0
    assert sum(row["hit@1"] for row in rows) / 3 == pytest.approx(1 / 3)


def test_pool_filters_as_of_window_and_type(fixture):
    pages = es.load_corpus(fixture)
    either = es.pool_for(pages, {"as_of": "2026-06-01"})
    assert {page.doc_key for page in either} == {"kec/call.pdf"}
    decks = es.pool_for(pages, {"as_of": "2026-08-01", "doc_type": "deck"})
    assert {page.doc_key for page in decks} == {"kec/deck.pdf"}
    window = es.pool_for(pages, {"as_of": "2026-08-01", "date_from": "2026-07-26", "date_to": "2026-08-01"})
    assert {page.doc_key for page in window} == {"kec/deck.pdf"}


def test_bm25_returns_the_gold_page_first(fixture):
    from reality_engine.db.readonly import connect_ro

    con = connect_ro(fixture, timeout_s=10)
    try:
        pages = es.load_corpus(fixture)
        pool = [page.key for page in es.pool_for(pages, {"as_of": "2026-06-01"})]
        ranking = es.bm25_ranking(con, {"question": "order intake for the year", "symbol": "KEC",
                                        "as_of": "2026-06-01"}, pool)
    finally:
        con.close()
    assert ranking[0] == ("kec/call.pdf", 2)


def test_eval_end_to_end_on_three_questions(workdir, fixture, capsys):
    gold = [
        {"qid": "Q1", "symbol": "KEC", "question": "order intake for the year", "as_of": "2026-06-01",
         "gold": [["kec/call.pdf", 2]]},
        {"qid": "Q2", "symbol": "KEC", "question": "order book", "as_of": "2026-08-01", "doc_type": "deck",
         "gold": [["kec/deck.pdf", 2]]},
        {"qid": "Q3", "symbol": "BAJFINANCE", "question": "AUM growth", "as_of": "2026-08-01",
         "gold": [["baj/results.pdf", 1]]},
    ]
    gold_path = workdir / "gold.json"
    gold_path.write_text(json.dumps(gold), encoding="utf-8")
    out = workdir / "embed"
    es.main(["embed", "--model", "1b", "--dry-run", "--db", str(fixture), "--out", str(out)])
    assert (out / "1b_text.npy").is_file() and (out / "1b_text.index.json").is_file()
    report = es.evaluate(fixture, gold, out, {"1b": es.FakeClient()})
    assert set(report["methods"]) == {"bm25", "1b_dense", "1b_hybrid"}
    assert all(len(rows) == 3 for rows in report["methods"].values())
    assert report["by_question"]["Q1"]["ranks"]["bm25"] == 1
    assert report["by_question"]["Q2"]["ranks"]["bm25"] == 1
    for rows in report["methods"].values():
        for row in rows:
            for key, value in row.items():
                if key != "rank":
                    assert 0.0 <= value <= 1.0
    assert (out / "EVAL.xlsx").is_file()
    # and the same path through the CLI, as the acceptance command runs it
    es.main(["eval", "--gold", str(gold_path), "--model", "1b", "--dry-run", "--db", str(fixture),
             "--out", str(out)])
    printed = capsys.readouterr().out
    assert "bm25" in printed and "1b_hybrid" in printed and "hit@50" in printed


def test_paid_client_needs_the_key(monkeypatch):
    monkeypatch.delenv("DEEPINFRA_API_KEY", raising=False)
    with pytest.raises(SystemExit):
        es.DeepInfraClient(es.MODELS["1b"]["id"])


def test_cache_survives_a_truncated_index(workdir):
    cache = es.VectorCache(workdir, "8b", "text")
    cache.add([("d", 1), ("d", 2)], [[1.0, 0.0], [0.0, 1.0]])
    cache.save()
    index = json.loads((workdir / "8b_text.index.json").read_text(encoding="utf-8"))
    (workdir / "8b_text.index.json").write_text(json.dumps(index[:1]), encoding="utf-8")
    reloaded = es.VectorCache(workdir, "8b", "text")
    assert len(reloaded.keys) == 1 and reloaded.matrix.shape == (1, 2)
    assert np.linalg.norm(reloaded.matrix[0]) == pytest.approx(1.0)
