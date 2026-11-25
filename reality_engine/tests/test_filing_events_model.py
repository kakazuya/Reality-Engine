"""T-242: model-first reading + script verification tests for ``order_win`` and ``fund_raise``."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from reality_engine.research import filing_events as fe


def _doc(title: str, text: str = "", *, pages: dict[int, str] | None = None, symbol: str = "ACME",
         company_name: str = "Acme Industries Limited", doc_key: str = "doc-1",
         filing_date: str = "2026-01-10", known_at: str = "2026-01-10T10:00:00") -> dict[str, Any]:
    if pages is None:
        pages = {1: text}
    full = "\n".join(pages[p] for p in sorted(pages))
    head = "\n".join(pages[p] for p in sorted(pages)[:2])
    return {
        "store": "cXX", "symbol": symbol, "company_name": company_name, "isin": "INE000A01001",
        "doc_key": doc_key, "title": title, "filing_date": filing_date, "known_at": known_at,
        "pages": pages, "text": full, "head": head,
    }


def _reply(**ev: Any) -> str:
    base = {
        "is_event": True,
        "event_type": "order_win",
        "not_event_reason": None,
        "stage": "received",
        "instrument": None,
        "amounts": [],
        "tenure_years": None,
        "awardee": None,
        "awardee_is_subsidiary": False,
        "awardee_is_joint": False,
        "customer": None,
        "execution_period": None,
        "execution_months": None,
        "shares": None,
        "price_per_share": None,
    }
    base.update(ev)
    return json.dumps({"events": [base]})


@pytest.fixture(autouse=True)
def _gate_both_kinds(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    if "live_gate" not in request.node.name:
        monkeypatch.setattr(fe, "VERIFIED_KINDS", frozenset({"order_win", "fund_raise"}))


# ---- W shapes: order_win (from audit_orderwin_fresh7) -----------------------------------------------------
@pytest.mark.parametrize("label,title,text,reply_kw", [
    (
        "ministry_director_appointment",
        "Please refer the enclosed file.",
        "The Company has received the Order dated December 03, 2024 from the Ministry of Mines, Government of India "
        "appointing Shri X as Government Nominee Director on the Board of Hindustan Zinc Limited.",
        {"is_event": False, "event_type": "not_event", "not_event_reason": "government director appointment order"},
    ),
    (
        "sebi_or_rd_order",
        "Intimation for receipt of SEBI Order dated September 18, 2025",
        "Adani Enterprises Limited has received an Order passed by Securities and Exchange Board of India (SEBI) "
        "disposing of adjudication proceedings. Similarly Regional Director order on shifting of Registered Office.",
        {"is_event": False, "event_type": "not_event", "not_event_reason": "regulatory order, not customer order"},
    ),
    (
        "block_termination_or_pli_ineligibility",
        "Disclosure under Regulation 30(4) - Termination of Banai-Bhalumuda Coal Block Development Agreement",
        "JSW Steel Limited informs regarding termination of Banai-Bhalumuda Coal Block agreement and PLI scheme "
        "ineligibility / Redler MoU called off.",
        {"is_event": False, "event_type": "not_event", "not_event_reason": "termination/ineligibility, not order win"},
    ),
    (
        "l1_only",
        "Announcement under Regulation 30_receipt of order.",
        "Force Motors Limited has been declared as the L1 vendor for supply of 2978 vehicles to Indian Defence Forces; "
        "formal Letter of Award is awaited.",
        {"is_event": True, "event_type": "order_win", "stage": "l1_only", "customer": "Indian Defence Forces"},
    ),
    (
        "cancelled_order",
        "Update on Work Order",
        "We wish to inform that the Work Order dated 01.04.2025 has been cancelled by the client.",
        {"is_event": True, "event_type": "order_win", "stage": "cancelled"},
    ),
])
def test_w_shapes_order_win_skipped_and_logged(label: str, title: str, text: str, reply_kw: dict[str, Any]) -> None:
    doc = _doc(title, text, doc_key=f"ow-{label}")
    skips: list[dict[str, Any]] = []
    rows = fe.model_rows(doc, ["order_win"], _reply(**reply_kw), skips_out=skips)
    assert rows == []
    assert len(skips) == 1 and skips[0]["doc_key"] == f"ow-{label}" and skips[0]["reason"]


def test_w_shape_annual_value_times_printed_tenure_kept_unverified() -> None:
    # fresh7 #11 ASHOKA: Rs.1265.37 Million annually for 35 years (24m construction + 35y O&M)
    doc = _doc(
        "Intimation for Receipt of Letter of Intent (LOI) from REC Power Development and Consultancy Limited",
        "Ashoka Buildcon Limited received LoI. Expected Completion Period: 24 months. Operation & Maintenance "
        "Period 35 years. 7 Broad consideration or size of the order(s) / contract(s): "
        "Rs.1265.37 Million, annually, for 35 years. (Annual Transmission Charges)",
        symbol="ASHOKA", company_name="Ashoka Buildcon Limited",
    )
    rows = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="loa",
            amounts=[{"value_text": "Rs.1265.37 Million", "number": 1265.37, "unit": "million",
                      "currency": "INR", "role": "annual_value"}],
            tenure_years=35,
            awardee="Ashoka Buildcon Limited",
            customer="REC Power Development and Consultancy Limited",
            execution_period="35 years", execution_months=24,
        ),
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["value_annual"] == pytest.approx(126.537)
    assert r["value_total"] == pytest.approx(126.537 * 35)
    assert r["amount_inr_cr"] == pytest.approx(126.537 * 35)
    assert r["status"] == "unverified"
    assert "annual value x printed tenure" in r["detail"]


def test_w_shape_usd_stays_in_usd_and_rejects_currency_confusion() -> None:
    # fresh7 #51 NEWGEN: US Dollars 2,593,125 (must stay USD mn, never rupees)
    doc = _doc(
        "Disclosure of material order USD 2,593,125 is attached.",
        "Newgen Software Inc. (NSI), a material Subsidiary of Newgen Software Technologies Limited, has entered "
        "into a Master Service Agreement with a leading healthcare company in the U.S. The aggregate value of the "
        "aforesaid Agreement is US Dollars 2,593,125.",
        symbol="NEWGEN", company_name="Newgen Software Technologies Limited",
    )
    rows = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "US Dollars 2,593,125", "number": 2593125, "unit": "unit",
                      "currency": "USD", "role": "order_size"}],
            awardee="Newgen Software Inc.", awardee_is_subsidiary=True,
        ),
    )
    assert len(rows) == 1
    r = rows[0]
    assert r["amount_inr_cr"] is None
    assert r["amount_usd_mn"] == pytest.approx(2.5931)
    assert r["entity_scope"] == "subsidiary" and "Newgen Software Inc." in r["detail"]
    assert r["status"] == "verified"

    # If the model mislabels USD text as currency="INR", the script rejects it (never stores USD as rupees!)
    bad = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "US Dollars 2,593,125", "number": 2593125, "unit": "unit",
                      "currency": "INR", "role": "order_size"}],
            awardee="Newgen Software Inc.", awardee_is_subsidiary=True,
        ),
    )
    assert bad[0]["status"] == "quarantined" and bad[0]["amount_inr_cr"] is None


def test_w_shape_coal_india_customer_does_not_make_own_subsidiary_and_uk_eur_kept() -> None:
    # fresh7 #23 SOLARINDS: customer is SECL (Subsidiary Company) of Coal India Limited -> awardee is company!
    solar = _doc(
        "Receipt of order of INR 483 Crores from South Eastern Coalfields Limited (SECL).",
        "Our Company, Solar Industries India Limited has received order worth INR 483 Crores for Supply of Bulk "
        "Explosives to SECL (Subsidiary Company) of Coal India Limited, to be delivered over a period of 2 years.",
        symbol="SOLARINDS", company_name="Solar Industries India Limited",
    )
    r_solar = fe.model_rows(
        solar, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "INR 483 Crores", "number": 483, "unit": "crore",
                      "currency": "INR", "role": "order_size"}],
            awardee="Solar Industries India Limited", awardee_is_subsidiary=False,
            customer="South Eastern Coalfields Limited", execution_months=24,
        ),
    )[0]
    assert r_solar["entity_scope"] == "company"
    assert r_solar["amount_inr_cr"] == pytest.approx(483.0)
    assert r_solar["customer"] == "South Eastern Coalfields Limited"

    # fresh7 #2 NEWGEN UK subsidiary EUR 4,222,683 -> subsidiary scope kept, EUR value_text preserved
    newgen_uk = _doc(
        "Disclosure of Material Order is attached.",
        "Newgen Software Technologies (UK) Limited, a wholly owned subsidiary of the Newgen Software Technologies "
        "Limited, has executed a Master Service Agreement. The aggregate value of the aforesaid Agreement is "
        "€ 4,222,683. Name of the entity awarding the order(s)/contract (s) : Tata Consultancy Services N.V, Belgium",
        symbol="NEWGEN", company_name="Newgen Software Technologies Limited",
    )
    r_uk = fe.model_rows(
        newgen_uk, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "€ 4,222,683", "number": 4222683, "unit": "unit",
                      "currency": "EUR", "role": "order_size"}],
            awardee="Newgen Software Technologies (UK) Limited", awardee_is_subsidiary=True,
            customer="Tata Consultancy Services N.V, Belgium",
        ),
    )[0]
    assert r_uk["entity_scope"] == "subsidiary"
    assert "Newgen Software Technologies (UK) Limited" in r_uk["detail"]
    assert r_uk["value_text"] == "€ 4,222,683"
    assert r_uk["amount_inr_cr"] is None and r_uk["amount_usd_mn"] is None


# ---- W shapes: fund_raise (from events_grade_fundraise_fresh7) --------------------------------------------
@pytest.mark.parametrize("label,title,text,reply_kw", [
    (
        "divestment",
        "Sale of entire share capital in 5 SPVs to Maple",
        "Ashoka Concessions Limited has sold its entire share capital held in 5 SPVs for Rs. 1814.42 Crores.",
        {"is_event": False, "event_type": "not_event", "not_event_reason": "divestment, not fund raise"},
    ),
    (
        "asset_purchase",
        "Update on transfer of Bonaire USA LLC and IPRs from CTPL",
        "An aggregate consideration of AUD 7.6 million (~₹52 crore) was remitted to CTPL for BUSA/IPR transfer.",
        {"is_event": False, "event_type": "not_event", "not_event_reason": "asset purchase, not fund raise"},
    ),
    (
        "withdrawn_rights",
        "Board meeting outcome- withdrawal of the proposed Right Issue of Equity Shares",
        "The Board decided to withdraw the proposed Right Issue of Equity Shares of Rs. 22,000 crore.",
        {"is_event": True, "event_type": "fund_raise", "stage": "withdrawn", "instrument": "rights"},
    ),
    (
        "bonus_issue",
        "intimation on issue of Bonus shares",
        "Bonus issue 1:1 of 2,16,92,52,744 equity shares by capitalizing Rs. 2,169.25 Crores from Reserves.",
        {"is_event": True, "event_type": "fund_raise", "stage": "approved_board", "instrument": "bonus"},
    ),
    (
        "nclt_scheme",
        "Update on approval of Scheme of Arrangement along with the Resolution Plan, pursuant to NCLT Order",
        "Update on NCLT/NCLAT resolution scheme of Rs. 43.6722 crore; no allotment in this filing.",
        {"is_event": False, "event_type": "not_event", "not_event_reason": "NCLT scheme update, no issuance"},
    ),
])
def test_w_shapes_fund_raise_skipped_and_logged(label: str, title: str, text: str, reply_kw: dict[str, Any]) -> None:
    doc = _doc(title, text, doc_key=f"fr-{label}")
    skips: list[dict[str, Any]] = []
    rows = fe.model_rows(doc, ["fund_raise"], _reply(**reply_kw), skips_out=skips)
    assert rows == []
    assert len(skips) == 1 and skips[0]["doc_key"] == f"fr-{label}"


def test_w_shapes_board_limit_offered_size_double_count_and_threshold() -> None:
    # fresh7 #16 CGCL: allotted 160 cr out of offered 300 cr (offered_size must NOT be stored/added)
    cgcl = _doc(
        "Allotment of Non-convertible Debentures",
        "Pursuant to the Key Information Document for base/offered issue up to Rs. 300 Crore, the Management "
        "Committee approved the allotment of 16,000 NCDs aggregating to Rs. 160,00,00,000.",
        symbol="CGCL",
    )
    r_cgcl = fe.model_rows(
        cgcl, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="ncd",
            amounts=[
                {"value_text": "Rs. 300 Crore", "number": 300, "unit": "crore", "currency": "INR", "role": "offered_size"},
                {"value_text": "Rs. 160,00,00,000", "number": 1600000000, "unit": "unit", "currency": "INR", "role": "total_issue"},
            ],
        ),
    )[0]
    assert r_cgcl["amount_inr_cr"] == pytest.approx(160.0)

    # fresh7 #51 JSWENERGY: board limit Rs 3,000 cr + Committee allotted Rs 1,200 cr -> 1200 only, never 4200
    jsw = _doc(
        "Clarification on news item",
        "The Board earlier approved raising up to Rs. 3,000 crores; the Finance Committee approved the allotment "
        "of 1,20,000 NCDs aggregating to Rs. 1,200 crore.",
        symbol="JSWENERGY",
    )
    r_jsw = fe.model_rows(
        jsw, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="ncd",
            amounts=[
                {"value_text": "Rs. 3,000 crores", "number": 3000, "unit": "crore", "currency": "INR", "role": "board_limit"},
                {"value_text": "Rs. 1,200 crore", "number": 1200, "unit": "crore", "currency": "INR", "role": "total_issue"},
            ],
        ),
    )[0]
    assert r_jsw["amount_inr_cr"] == pytest.approx(1200.0)

    # fresh7 #18 JSWSTEEL: two tranches 1750 + 500 aggregating to INR 2,250 Crore -> printed total 2250 wins!
    jswsteel = _doc(
        "Allotment of NCDs aggregating to INR 2,250 Crore",
        "Finance Committee allotted (i) Tranche I aggregating to INR 1750,00,00,000 and (ii) Tranche II "
        "aggregating to INR 500,00,00,000, aggregating to INR 2,250 Crore.",
        symbol="JSWSTEEL",
    )
    r_steel = fe.model_rows(
        jswsteel, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="ncd",
            amounts=[
                {"value_text": "INR 1750,00,00,000", "number": 17500000000, "unit": "unit", "currency": "INR", "role": "tranche"},
                {"value_text": "INR 500,00,00,000", "number": 5000000000, "unit": "unit", "currency": "INR", "role": "tranche"},
                {"value_text": "INR 2,250 Crore", "number": 2250, "unit": "crore", "currency": "INR", "role": "total_issue"},
            ],
        ),
    )[0]
    assert r_steel["amount_inr_cr"] == pytest.approx(2250.0) and r_steel["status"] == "verified"

    # fresh7 #45 DIACABS: threshold on page 4 (NOT issue size)
    diacabs = _doc(
        "Notice of Postal Ballot",
        "",
        pages={
            1: "Notice of Postal Ballot to approve raising funds via QIP.",
            4: "allotment to a single QIB shall not exceed 50% if issue size is less than or equal to ₹250 Crore.",
        },
        symbol="DIACABS",
    )
    r_dia = fe.model_rows(
        diacabs, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="filed_offer_doc", instrument="qip",
            amounts=[{"value_text": "₹250 Crore", "number": 250, "unit": "crore", "currency": "INR", "role": "threshold"}],
        ),
    )[0]
    assert r_dia["amount_inr_cr"] is None and r_dia["status"] == "unverified"


def test_w_shape_equity_plus_warrant_legs_sum_when_total_not_printed() -> None:
    doc = _doc(
        "Allotment of equity shares and warrants",
        "Finance Committee allotted 95,23,809 equity shares on receipt of Rs. 499,99,99,725 and 4,76,19,047 "
        "warrants for Rs. 2,500 Crore.",
        symbol="JSWENERGY",
    )
    row = fe.model_rows(
        doc, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="preferential",
            amounts=[
                {"value_text": "Rs. 499,99,99,725", "number": 4999999725, "unit": "unit", "currency": "INR", "role": "equity_leg"},
                {"value_text": "Rs. 2,500 Crore", "number": 2500, "unit": "crore", "currency": "INR", "role": "warrant_leg"},
            ],
        ),
    )[0]
    assert row["amount_inr_cr"] == pytest.approx(3000.0, rel=1e-3)
    assert row["status"] == "unverified"
    assert "sum of printed tranche/leg" in row["detail"]


# ---- Step 5 counter-tests ---------------------------------------------------------------------------------
def test_counter_1_real_order_with_rupee_size_on_page_4() -> None:
    doc = _doc(
        "Intimation of Order received from PGVCL",
        "",
        pages={
            1: "Rajesh Power Services Limited informs receipt of order from PGVCL.",
            2: "See Annexure I.",
            3: "Details continued.",
            4: "7. Broad consideration or size of the order(s)/contract(s); Rs. 40.58 Crores (Incl. Taxes)",
        },
        symbol="RAJESH", company_name="Rajesh Power Services Limited",
    )
    prompt = fe.model_prompt(doc, ["order_win"])
    assert "Rs. 40.58 Crores" in prompt  # verifies pages 1-4 are sent to the model
    row = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "Rs. 40.58 Crores (Incl. Taxes)", "number": 40.58, "unit": "crore",
                      "currency": "INR", "role": "order_size"}],
            awardee="Rajesh Power Services Limited", customer="PGVCL", execution_months=12,
        ),
    )[0]
    assert row["amount_inr_cr"] == pytest.approx(40.58)
    assert row["page"] == 4
    assert row["status"] == "verified"


def test_counter_2_usd_order() -> None:
    doc = _doc(
        "Disclosure Under Regulation 30 - Intimation of receipt of Order",
        "The Company has received an order with the value of USD 9.28 million from a major US OEM.",
        symbol="TDPOWERSYS", company_name="TD Power Systems Limited",
    )
    row = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "USD 9.28 million", "number": 9.28, "unit": "million",
                      "currency": "USD", "role": "order_size"}],
            awardee="TD Power Systems Limited",
        ),
    )[0]
    assert row["amount_usd_mn"] == pytest.approx(9.28) and row["amount_inr_cr"] is None
    assert row["status"] == "verified"


def test_counter_3_subsidiary_order() -> None:
    doc = _doc(
        "Receipt of Order",
        "KRN HVAC Products Private Limited, a wholly owned subsidiary of KRN Heat Exchanger Limited, has "
        "received an order worth INR 55 Crore from ABC Industrial Ltd.",
        symbol="KRN", company_name="KRN Heat Exchanger Limited",
    )
    row = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "INR 55 Crore", "number": 55, "unit": "crore",
                      "currency": "INR", "role": "order_size"}],
            awardee="KRN HVAC Products Private Limited", awardee_is_subsidiary=True,
            customer="ABC Industrial Ltd",
        ),
    )[0]
    assert row["entity_scope"] == "subsidiary"
    assert "subsidiary: KRN HVAC Products Private Limited" in row["detail"]
    assert row["amount_inr_cr"] == pytest.approx(55.0)
    assert row["status"] == "verified"


def test_counter_4_qip_allotment_with_printed_total() -> None:
    doc = _doc(
        "Allotment of Equity Shares to Eligible QIBs",
        "The QIP Committee approved the issue and allotment of 77,41,935 Equity Shares at Rs. 775 per share, "
        "aggregating to ₹599,99,99,625.",
        symbol="TDPOWERSYS", company_name="TD Power Systems Limited",
    )
    row = fe.model_rows(
        doc, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="qip",
            amounts=[{"value_text": "₹599,99,99,625", "number": 5999999625, "unit": "unit",
                      "currency": "INR", "role": "total_issue"}],
            shares=7741935, price_per_share=775,
        ),
    )[0]
    assert row["amount_inr_cr"] == pytest.approx(600.0, abs=1e-4)
    assert row["instrument"] == "qip" and row["raise_stage"] == "allotted"
    assert row["status"] == "verified"


def test_counter_5_two_tranche_ncd_allotment() -> None:
    doc = _doc(
        "Allotment of Non-Convertible Debentures",
        "The Committee allotted 42,000 NCDs aggregating up to INR 420 Crore (STRPP1) and 98,000 NCDs "
        "aggregating up to INR 980 Crore (STRPP2).",
        symbol="HINDZINC", company_name="Hindustan Zinc Limited",
    )
    row = fe.model_rows(
        doc, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="ncd",
            amounts=[
                {"value_text": "INR 420 Crore", "number": 420, "unit": "crore", "currency": "INR", "role": "tranche"},
                {"value_text": "INR 980 Crore", "number": 980, "unit": "crore", "currency": "INR", "role": "tranche"},
            ],
        ),
    )[0]
    assert row["amount_inr_cr"] == pytest.approx(1400.0)
    assert row["status"] == "unverified" and "sum of printed tranche/leg" in row["detail"]


# ---- Script checks, prompt fp, caching, 429, stop rules ---------------------------------------------------
def test_unprinted_amount_is_quarantined_with_no_stored_amount() -> None:
    doc = _doc("Receipt of Order", "The Company received an order from Acme Corp.")
    row = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "Rs. 999 Crore", "number": 999, "unit": "crore",
                      "currency": "INR", "role": "order_size"}],
        ),
    )[0]
    assert row["status"] == "quarantined"
    assert row["amount_inr_cr"] is None and row["amount_usd_mn"] is None and row["value_text"] is None


def test_script_parse_mismatch_makes_row_unverified_with_both_values() -> None:
    doc = _doc("Receipt of Order", "The Company received an order worth Rs. 100 Crore from Acme Ltd.")
    row = fe.model_rows(
        doc, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[{"value_text": "Rs. 100 Crore", "number": 100, "unit": "crore",
                      "currency": "INR", "role": "order_size"}],
        ),
        script_check={"order_win": [{"amount_inr_cr": 200.0, "amount_usd_mn": None}]},
    )[0]
    assert row["status"] == "unverified"
    assert "amount mismatch:" in row["detail"] and "100" in row["detail"] and "200" in row["detail"]


def test_build_model_first_caches_by_doc_key_and_prompt_fp_and_logs_skips(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docs = [
        _doc(
            "Company has received an order from Acme Ltd",
            "The Company has received an order worth Rs. 50 Crore from Acme Ltd.",
            doc_key="d-win", filing_date="2026-01-10", known_at="2026-01-10T10:00:00",
        ),
        _doc(
            "Company received Order from GoI for appointment of Director",
            "The Company has received an order from Ministry of Mines appointing a Director.",
            doc_key="d-skip", filing_date="2026-01-11", known_at="2026-01-11T10:00:00",
        ),
    ]
    monkeypatch.setattr(fe, "load_docs", lambda store: [dict(d) for d in docs])

    calls: list[str] = []

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self._ra = 0.0

        def retry_after(self) -> float:
            return self._ra

        def chat(self, prompt: str) -> tuple[int, str, tuple[int, int]]:
            calls.append(prompt)
            if "d-skip" in prompt or "appointing a Director" in prompt:
                return 200, _reply(is_event=False, event_type="not_event", not_event_reason="director appointment"), (10, 10)
            return 200, _reply(
                event_type="order_win", stage="received",
                amounts=[{"value_text": "Rs. 50 Crore", "number": 50, "unit": "crore",
                          "currency": "INR", "role": "order_size"}],
                awardee="Acme Industries Limited", customer="Acme Ltd",
            ), (10, 10)

    monkeypatch.setattr(fe, "Client", FakeClient)
    out = tmp_path / "events.db"
    cache = tmp_path / "cache.json"
    meta = fe.build(stores=["cXX"], use_model=True, workers=1, out=out, cache=cache)
    assert meta["prompt_fp"] == fe.prompt_fingerprint()
    assert meta["model_requests"] == 2 and meta["skipped"] == 1
    assert meta["stopped"] is None  # 30% MODEL_STOP_SHARE does NOT stop model-first order_win/fund_raise

    con = sqlite3.connect(out)
    ev_rows = con.execute("SELECT doc_key, kind, amount_inr_cr, method FROM event").fetchall()
    skip_rows = con.execute("SELECT doc_key, reason FROM skip_log").fetchall()
    con.close()
    assert ev_rows == [("d-win", "order_win", 50.0, "model")]
    assert skip_rows == [("d-skip", "director appointment")]

    # Second run uses cache: 0 new HTTP requests
    meta2 = fe.build(stores=["cXX"], use_model=True, workers=1, out=out, cache=cache)
    assert meta2["model_requests"] == 0 and meta2["model_cached"] == 2
    assert len(calls) == 2


def test_run_model_honours_429_retry_after_and_stops_above_5pct_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr(fe.time, "sleep", lambda s: sleeps.append(s))

    class Flaky429Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.n = 0

        def retry_after(self) -> float:
            return 3.0

        def chat(self, prompt: str) -> tuple[int, str, tuple[int, int]]:
            self.n += 1
            if self.n == 1:
                return 429, "rate limited", (0, 0)
            return 200, _reply(is_event=False, event_type="not_event", not_event_reason="ok"), (5, 5)

    monkeypatch.setattr(fe, "Client", Flaky429Client)
    d = _doc("New Order", "Order worth Rs. 10 Crore.")
    d["_missing"] = ["order_win"]
    _, stats = fe.run_model([d], workers=1, cache_path=tmp_path / "c1.json")
    assert 3.0 in sleeps and stats["errors"] == 0

    # >5% error stop rule
    class ErrorClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        def retry_after(self) -> float:
            return 0.0

        def chat(self, prompt: str) -> tuple[int, str, tuple[int, int]]:
            return 500, "boom", (0, 0)

    monkeypatch.setattr(fe, "Client", ErrorClient)
    many = [{**_doc("New Order", "Order worth Rs. 10 Crore.", doc_key=f"k-{i}"), "_missing": ["order_win"]}
            for i in range(30)]
    _, err_stats = fe.run_model(many, workers=1, cache_path=tmp_path / "c2.json")
    assert err_stats["stopped"] is not None and "error rate" in err_stats["stopped"]
    assert err_stats["requests"] < 30


def test_indian_comma_10x_llm_slip_and_ocr_shapes() -> None:
    # Indian comma 10x slip by model: uses printed digits (450 cr), not model's 4500 cr
    d_ncd = _doc("Allotment of NCDs", "The Committee allotted NCDs aggregating to ₹ 450,00,00,000.")
    r_ncd = fe.model_rows(
        d_ncd, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="ncd",
            amounts=[{"value_text": "₹ 450,00,00,000", "number": 45000000000, "unit": "unit",
                      "currency": "INR", "role": "total_issue"}],
        ),
    )[0]
    assert r_ncd["amount_inr_cr"] == pytest.approx(450.0) and r_ncd["status"] == "verified"

    # OCR ¥ in place of ₹ alongside Crore, and Rs. 121lakhs (no space) + spaced decimal "43. 50"
    d_ocr = _doc(
        "Order received",
        "Won ¥ 3.67 Crore including GST, Rs. 121lakhs, and Rs. 43. 50 Crores Only/-.",
        company_name="Acme Industries Limited",
    )
    rows = fe.model_rows(
        d_ocr, ["order_win"],
        json.dumps({"events": [
            {"is_event": True, "event_type": "order_win", "stage": "received", "awardee": "Acme Industries Limited",
             "amounts": [{"value_text": "₹ 3.67 Crore including GST", "number": 3.67, "unit": "crore", "currency": "INR", "role": "order_size"}]},
            {"is_event": True, "event_type": "order_win", "stage": "received", "awardee": "Acme Industries Limited",
             "amounts": [{"value_text": "Rs. 121lakhs", "number": 121, "unit": "lakh", "currency": "INR", "role": "order_size"}]},
            {"is_event": True, "event_type": "order_win", "stage": "received", "awardee": "Acme Industries Limited",
             "amounts": [{"value_text": "Rs. 43. 50 Crores Only/-", "number": 43.5, "unit": "crore", "currency": "INR", "role": "order_size"}]},
        ]}),
    )
    assert [r["amount_inr_cr"] for r in rows] == pytest.approx([3.67, 1.21, 43.5])
    assert rows[0]["value_text"] == "¥ 3.67 Crore including GST"

    # Table cell in Amount (In ₹ crore) and non-monetary MWp quantity (not quarantined)
    d_tbl = _doc("Orders", "Sr Segment Amount (In ₹ crore) 1 Solar 441.30; 173.35 MWp module supply.")
    r_tbl = fe.model_rows(
        d_tbl, ["order_win"],
        json.dumps({"events": [
            {"is_event": True, "event_type": "order_win", "stage": "received",
             "amounts": [{"value_text": "441.30", "number": 441.3, "unit": "crore", "currency": "INR", "role": "order_size"}]},
            {"is_event": True, "event_type": "order_win", "stage": "received",
             "amounts": [{"value_text": "173.35 MWp", "number": 173.35, "unit": "unit", "currency": None, "role": "order_size"}]},
            {"is_event": True, "event_type": "order_win", "stage": "received",
             "amounts": [{"value_text": "2429 units", "number": 2429, "unit": "unit", "currency": None, "role": "order_size"}]},
        ]}),
    )
    assert r_tbl[0]["amount_inr_cr"] == pytest.approx(441.30) and r_tbl[0]["status"] == "verified"
    assert r_tbl[1]["amount_inr_cr"] is None and r_tbl[1]["status"] != "quarantined"
    assert r_tbl[2]["amount_inr_cr"] is None and r_tbl[2]["status"] != "quarantined"


def test_fold_same_raise_keeps_quantified_allotted_twin() -> None:
    amends: list[dict[str, Any]] = []
    r1 = {
        "symbol": "ACME", "kind": "fund_raise", "doc_key": "d1", "filing_date": "2026-07-30",
        "known_at": "2026-07-30T10:00:00", "raise_stage": "allotted", "shares": 1000000,
        "amount_inr_cr": None, "amount_usd_mn": None, "title": "Outcome of Committee",
    }
    r2 = {
        "symbol": "ACME", "kind": "fund_raise", "doc_key": "d2", "filing_date": "2026-07-30",
        "known_at": "2026-07-30T11:00:00", "raise_stage": "allotted", "shares": 1000000,
        "amount_inr_cr": 350.0, "amount_usd_mn": None, "title": "Allotment of QIP",
    }
    kept = fe._fold_same_raise([r1, r2], amends)
    assert len(kept) == 1 and kept[0]["doc_key"] == "d2" and kept[0]["amount_inr_cr"] == 350.0

