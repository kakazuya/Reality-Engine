"""Checks for the v4 decomposer and its typed Ask contract (§C.1–§C.2, §H.3).

No DB, no model, no network: the registry JSON and the master bank are read as files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from reality_engine.query.v4.decompose import (
    REGISTRY_PATH,
    Registry,
    decompose,
    decompose_case,
    load_registry,
    split_clauses,
)
from reality_engine.query.v4.parts import OPERATORS, STATUSES, Ask, Part, Result

ROOT = Path(__file__).resolve().parents[2]
BANK = ROOT / "tasks" / "master_bank" / "MASTER_BANK.jsonl"


@pytest.fixture(scope="module")
def registry() -> Registry:
    return load_registry(REGISTRY_PATH)


def _case(mid: str) -> dict:
    for line in BANK.read_text(encoding="utf-8").splitlines():
        case = json.loads(line)
        if case["mid"] == mid:
            return case
    raise KeyError(mid)


def _part(atom: str, dims: dict) -> Part:
    return Part(atom=atom, dims=dims)


# --------------------------------------------------------------------------- #
# the typed contract WP4 imports
# --------------------------------------------------------------------------- #
def test_operator_set_matches_the_registry(registry):
    assert tuple(o["op_id"] for o in registry.data["operators"]) == OPERATORS


def test_part_needs_exactly_one_measure():
    with pytest.raises(ValueError):
        Part(atom="price.close", formula="f.cagr")
    with pytest.raises(ValueError):
        Part()


def test_part_rejects_unknown_operator_and_shape():
    with pytest.raises(ValueError):
        Part(atom="price.close", operator="vibe_check")
    with pytest.raises(ValueError):
        Part(atom="price.close", shape="poem")


def test_ask_rejects_a_window_index_out_of_range():
    with pytest.raises(ValueError):
        Ask(parts=[_part("price.close", {})], status="mapped").__class__(
            parts=[Part(atom="price.close", window=3)], status="mapped")


def test_result_answer_types_are_closed():
    assert Result(part_index=0, answer_type="measured").answer_type == "measured"
    with pytest.raises(ValueError):
        Result(part_index=0, answer_type="probably")


def test_ask_round_trips_through_dict():
    ask = decompose("What was AEROFLEX's close on 16 October 2026?", "2026-10-19")
    again = Ask.from_dict(json.loads(json.dumps(ask.to_dict())))
    assert again.measures == ask.measures
    assert again.status == ask.status
    assert again.windows[0].to_dict() == ask.windows[0].to_dict()


# --------------------------------------------------------------------------- #
# §H.3: multi-part asks keep every part
# --------------------------------------------------------------------------- #
def test_promoter_and_public_are_two_parts(registry):
    ask = decompose(
        "M & B Engineering (NSE: MBEL) mein public shareholding Sep 2026 tak kitni hai? "
        "Promoter aur public dono ka percentage filing se batao.", "2026-10-19", registry)
    parts = [p for p in ask.parts if p.concept == "hold.pct"]
    assert set(p.dim_values("holder_class")[0] for p in parts) == {"promoter", "public"}


def test_nse_bse_and_sum_are_three_parts(registry):
    ask = decompose("Ather delivery volume on 13 April 2026, NSE + BSE combined, "
                    "give NSE, BSE and the sum per day.", "2026-10-19", registry)
    parts = [p for p in ask.parts if p.concept == "price.delivery_qty"]
    assert set(p.dim_values("exchange")[0] for p in parts) == {"NSE", "BSE", "sum"}


def test_raw_and_adjusted_are_two_parts(registry):
    ask = decompose("Polycab: give the raw and adjusted close for 2026.", "2026-10-19", registry)
    parts = [p for p in ask.parts if p.concept == "price.close"]
    assert set(p.dim_values("basis")[0] for p in parts) == {"raw", "adjusted"}


def test_a_restated_class_does_not_double_a_part(registry):
    ask = decompose("Promoter holding and promoter stake for GESHIP, latest.", "2026-10-19",
                    registry)
    keys = [(p.concept, tuple(sorted(p.dims.items()))) for p in ask.parts]
    assert len(keys) == len(set(keys))


def test_every_part_carries_a_scalar_dim_reading(registry):
    ask = decompose("For all listed companies in Banks, rank the banks by net NPA % for Q1FY27.",
                    "2026-10-19", registry)
    for part in ask.parts:
        for dim_id, value in part.dims.items():
            assert not isinstance(value, (list, tuple, dict)), (dim_id, value)


# --------------------------------------------------------------------------- #
# §H.3: unmapped is emitted, never guessed
# --------------------------------------------------------------------------- #
def test_inexpressible_ask_is_unmapped_and_has_no_guessed_part(registry):
    ask = decompose_case(_case("MB1021"), registry)   # "what would prove the path is broken"
    assert ask.status == "unmapped"
    assert ask.residues or not ask.parts
    assert ask.status in STATUSES


def test_residue_is_named(registry):
    ask = decompose("What is the company's order escalation clause?",
                    "2026-10-19", registry)
    assert ask.status == "unmapped"
    assert ask.residues


def test_a_mapped_ask_has_no_residue(registry):
    ask = decompose("What was AEROFLEX's close on 16 October 2026?", "2026-10-19", registry)
    assert ask.status in ("mapped", "not_in_data")
    assert ask.residues == []


def test_a_gap_atom_is_a_typed_not_in_data_not_a_guess(registry):
    ask = decompose("IRFC declared a Re 1.15 interim dividend with an ex-date of 23 Oct 2026.",
                    "2026-10-19", registry)
    assert ask.status == "not_in_data"
    assert ask.nid_reasons


# --------------------------------------------------------------------------- #
# §C.2: bank fields are not inputs
# --------------------------------------------------------------------------- #
def test_decompose_case_ignores_bank_fields(registry):
    case = _case("MB0305")
    bare = {"mid": case["mid"], "question": case["question"], "as_of": case["as_of"]}
    noisy = dict(bare, period="16 Oct 2026", template="DBQ1", family=[1], answer_kind="text+quote",
                 chain=["resolve", "FACTS"])
    assert decompose_case(bare, registry).to_dict() == decompose_case(noisy, registry).to_dict()


def test_window_comes_from_the_question_text(registry):
    ask = decompose("What was the close on 16 October 2026?", "2026-10-19", registry)
    assert ask.windows[0].to_dict()["from"] == "2026-10-16"
    assert ask.windows[0].basis == "named date"


def test_no_date_declares_the_run_date_as_the_window(registry):
    ask = decompose("TITAGARH promoter %", "2026-10-31", registry)
    assert ask.windows[0].basis == "as_of"


def test_a_named_year_cagr_opens_its_window(registry):
    """"3-year CAGR to 19 Oct 2026" reads three years of closes, not one day's."""
    ask = decompose("What was Power Grid's 3-year price CAGR to 19 October 2026, "
                    "using split- and dividend-adjusted closes?", "2026-10-19", registry)
    assert "f.cagr" in ask.measures
    window = ask.windows[0].to_dict()
    assert (window["from"], window["to"]) == ("2023-10-19", "2026-10-19")


def test_clause_split_keeps_a_company_name_whole():
    assert split_clauses("CG Power and Industrial Solutions close") == [
        "CG Power and Industrial Solutions close"]


def test_clause_split_keeps_a_capitalised_measure_after_and():
    assert "CFO/PAT improve with it" in [c.strip() for c in split_clauses(
        "Did DSO and CFO/PAT improve with it", frozenset({"dso", "cfo", "pat"}))]
