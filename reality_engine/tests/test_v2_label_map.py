"""T-133 label dictionary: normalisation, the three proposal tiers, metric kinds, and the sector map.

    python -m pytest -q reality_engine/tests/test_v2_label_map.py
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from reality_engine.pilot3.make_profile import main_store
from reality_engine.v2 import label_map, schema

STORES = (Path("D:/RealityEngine/pilot10/pilot10.db"), Path("D:/RealityEngine/p20/p20new.db"),
          Path("D:/RealityEngine/u8/u8.db"), Path("D:/RealityEngine/q12/q12.db"))


def test_normalisation_units_numbering_and_generic_children():
    assert label_map.normalise_label("1. Revenue from operations") == "revenue from operations"
    assert label_map.normalise_label("Revenue from Operations (Rs crore)") == "revenue from operations"
    assert label_map.normalise_label("EBITDA margin (%)") == "ebitda margin"
    assert label_map.normalise_label("(a) Finance costs") == "finance costs"
    assert label_map.normalise_label("i) Other income") == "other income"
    assert label_map.normalise_label("iv. Exceptional items") == "exceptional items"
    assert label_map.normalise_label("Net debt (excluding acceptances)") == "net debt excluding acceptances"
    assert label_map.normalise_label("Constant Currency Revenue") == "constant currency revenue"
    assert label_map.normalise_label("Others") == "others"
    assert label_map.normalise_label("Others", "Segment Revenue") == "segment revenue > others"
    assert label_map.normalise_cell_label("Segment Revenue > Others") == "segment revenue > others"
    assert label_map.normalise_cell_label("Expenses > Employee benefits expense") == "employee benefits expense"


def test_phrase_matching_uses_word_boundaries():
    ebit = label_map.Entry("ebit", phrases=("ebit",))
    assert label_map._match_entry(ebit, "ebit margin") > 0
    assert label_map._match_entry(ebit, "ebitda margin") == 0


def test_seed_mapping_beats_lexicon():
    family_entries, common = label_map.load_lexicons()
    seeded = label_map.propose_metric("casa ratio", "bank", {("casa ratio", "bank"): "chosen_by_seed"},
                                      family_entries, common)
    assert seeded is not None and seeded.metric == "chosen_by_seed" and seeded.reason == "seed"
    lexical = label_map.propose_metric("casa ratio", "bank", {}, family_entries, common)
    assert lexical is not None and lexical.metric == "casa_ratio"
    assert lexical.reason.startswith("lexicon:")


def test_a_label_never_maps_across_families_except_common():
    family_entries, common = label_map.load_lexicons()
    seeds = {("casa ratio", "bank"): "casa_ratio"}
    assert label_map.propose_metric("casa ratio", "fmcg", seeds, family_entries, common) is None
    shared = label_map.propose_metric("net debt", "fmcg", seeds, family_entries, common)
    assert shared is not None and shared.metric == "net_debt" and shared.family == "*"


def test_metric_kinds_for_the_period_engine():
    assert label_map.metric_kind("revenue") == "flow"
    assert label_map.metric_kind("borrowings") == "stock"
    assert label_map.metric_kind("ebitda_margin_pct") == "ratio"
    assert label_map.metric_kind("eps_basic") == "per_share"
    assert label_map.metric_kind("aum") == "stock"
    assert label_map.metric_kind("arpu") == "price"
    assert label_map.metric_kind("total_expenses") == "flow"
    assert label_map.metric_kind("other_income") == "flow"


def test_section_overrides_and_percentage_parents():
    assert label_map._section_metric("segment assets") == "segment_assets"
    assert label_map._section_metric("ii segment results") == "segment_results"
    assert label_map._pct_metric("access_charges") == "access_charges_pct"
    assert label_map._pct_metric("ebitda") == "ebitda_margin_pct"


def test_metric_def_table_and_kind_check():
    conn = sqlite3.connect(":memory:")
    schema.create(conn)
    conn.execute("INSERT INTO metric_def (metric, kind, unit_kind, description) VALUES ('revenue','flow','inr','x')")
    assert conn.execute("SELECT kind FROM metric_def WHERE metric='revenue'").fetchone()[0] == "flow"
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute("INSERT INTO metric_def (metric, kind) VALUES ('bad','maybe')")


def test_sector_map_gives_every_pilot_company_a_family():
    taxonomy = main_store()
    if not taxonomy.is_file() or not all(path.is_file() for path in STORES):
        pytest.skip("the pilot stores are not on this machine")
    rows = label_map.company_families(STORES, taxonomy)
    assert rows, "no company rows read from the four pilot stores"
    unknown = [row for row in rows if row["family"] == "unknown"]
    assert not unknown, f"{len(unknown)} company rows have no sector family: {unknown[:5]}"
