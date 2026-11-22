"""T-234 bake-off scorer and exact page selection (synthetic, no network)."""
import json
import shutil
from pathlib import Path

from reality_engine.scripts import reader_bakeoff as rb


def test_within_is_half_a_percent():
    assert rb.within(100, 100.49)
    assert not rb.within(100, 100.6)
    assert rb.within(0, 0)
    assert not rb.within(None, 1)
    assert not rb.within("Rs 47.9 Mn", 47.9)


def test_page_set_is_exact_not_a_document_page_cross_product():
    only = rb.PageSet([{"doc_key": "a.pdf", "page": 3}, {"doc_key": "b.pdf", "page": 9}])
    assert only.page("store", "a.pdf", 3)
    assert not only.page("store", "a.pdf", 9)      # a Selector would take this cross product
    assert only.store("anything")


def test_match_rows_counts_agreement_and_disagreement():
    model = [{"measure": "loans", "period": "Q2FY26", "value": 100.0},
             {"measure": "loans", "period": "Q2FY26", "value": 300.0}]
    hy4 = [{"measure": "loans", "period": "Q2FY26", "value": 100.4},
           {"measure": "loans", "period": "Q2FY26", "value": 200.0},
           {"measure": "aum", "period": "Q2FY26", "value": 50.0}]
    matched, disagree = rb.match_rows(model, hy4)
    assert matched == 1
    assert [item["kind"] for item in disagree] == ["mismatch"]   # 300 is not 200: a disagreement, not an agreement


def test_match_rows_never_crosses_pages():
    model = [{"doc_key": "a.pdf", "page": 1, "measure": "loans", "period": "FY25", "value": 100.0},
             {"doc_key": "a.pdf", "page": 2, "measure": "loans", "period": "FY25", "value": 300.0}]
    hy4 = [{"doc_key": "b.pdf", "page": 1, "measure": "loans", "period": "FY25", "value": 100.0},
           {"doc_key": "a.pdf", "page": 1, "measure": "loans", "period": "FY25", "value": 999.0}]
    matched, disagree = rb.match_rows(model, hy4)
    assert matched == 0                                           # same value on another document is no agreement
    assert [item["kind"] for item in disagree] == ["mismatch", "model_only"]
    assert disagree[0]["hy4"]["doc_key"] == "a.pdf"               # paired only with its own page's row


def test_report_writes_csv_and_md_from_score_files():
    tmp_path = Path(".tmp/t234/test_report")
    shutil.rmtree(tmp_path, ignore_errors=True)
    tmp_path.mkdir(parents=True)
    score = {"model": "nvidia/nemotron-3.5-super-vl:free", "pages": 228, "rows": 1000, "text_only": False,
             "status": {"verified": 500, "unverified": 400, "quarantined": 100}, "verified_per_page": 2.19,
             "text_match": [900, 1000],
             "golden": {"counts": {"still_right": 120, "fixed": 10, "still_wrong": 20}, "lines": 241,
                        "right_total": 158, "wrong_total": 83},
             "hy4": {"matched": 700, "model_only": 300, "hy4_only": 50},
             "speed": {"pages_per_min": 4.0, "median_s": 9.5, "p90_s": 20.0, "errors": 2, "http_429": 1,
                       "in_tok": 228000, "out_tok": 57000, "in_tok_per_page": 1000.0, "out_tok_per_page": 250.0}}
    (tmp_path / "score_nvidia_nemotron_3_5_super_vl_free.json").write_text(json.dumps(score), encoding="utf-8")
    rb.report(tmp_path)
    md = (tmp_path / "bakeoff.md").read_text(encoding="utf-8")
    assert "120/158 (76%)" in md
    assert "500/400/100" in md
    rows = (tmp_path / "bakeoff.csv").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 2 and rows[0].startswith("model,kind,pages,rows")
    assert "120/158 (76%)" in rows[1]
