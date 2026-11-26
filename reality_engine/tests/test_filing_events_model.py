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


# ---- T-242 model-first r2 (fresh8 W/J/P kinds + counter-tests) --------------------------------------------
@pytest.mark.parametrize("label,title,pages,reply_kw", [
    (
        "other_than_cash_p4",
        "Results of postal ballot",
        {1: "Sub: Results of postal ballot.", 4: "1- Approval for issuance of 1,86,07,969 equity shares of the company on preferential basis for consideration other than cash."},
        {"is_event": True, "event_type": "fund_raise", "stage": "approved_shareholders", "instrument": "preferential", "shares": 18607969},
    ),
    (
        "scheme_of_amalgamation",
        "Allotment of equity shares to the shareholders of Transferor Company (QCIL) pursuant to the Scheme of Amalgamation",
        {1: "Sub: Allotment of equity shares. Ref: Scheme of Amalgamation between Quality Care India Limited and Aster DM Healthcare Limited."},
        {"is_event": True, "event_type": "fund_raise", "stage": "allotted", "instrument": "equity", "shares": 353551410},
    ),
    (
        "mip_options_exercise",
        "Company has allotted 22,040 equity shares pursuant to TVS SCS Management Incentive Plan II (MIP II)",
        {1: "The Company has allotted 22,040 equity shares of INR 1/- each pursuant to exercise of options under TVS SCS Management Incentive Plan II, 2018."},
        {"is_event": True, "event_type": "fund_raise", "stage": "allotted", "instrument": "equity", "shares": 22040},
    ),
    (
        "subsidiary_drhp_ipo_ofs",
        "Please refer the attachment.",
        {1: "NLC India Renewables Limited (NIRL), a wholly owned subsidiary Company of NLC India Limited, has filed the Draft Red Herring Prospectus (DRHP) pertaining to the proposed Initial Public Offer (IPO) of equity shares of NIRL comprising a Fresh Issue aggregating up to Rs. 33,000 Million and an Offer for Sale (OFS) up to 10,00,00,000 equity shares."},
        {"is_event": True, "event_type": "fund_raise", "stage": "filed_offer_doc", "instrument": "ipo",
         "amounts": [{"value_text": "Rs. 33,000 Million", "number": 33000, "unit": "million", "currency": "INR", "role": "total_issue"}]},
    ),
])
def test_r2_step1_not_a_fund_raise_skipped(label: str, title: str, pages: dict[int, str], reply_kw: dict[str, Any]) -> None:
    doc = _doc(title, pages=pages, doc_key=f"fr-{label}")
    skips: list[dict[str, Any]] = []
    rows = fe.model_rows(doc, ["fund_raise"], _reply(**reply_kw), skips_out=skips)
    assert rows == []
    assert len(skips) == 1 and skips[0]["reason"]


def test_r2_step1_counter_cash_preferential_and_multi_item_board_stay() -> None:
    cash_doc = _doc(
        "Outcome of Board Meeting",
        "The Board approved issuance of 13,00,000 equity shares on a preferential issue basis for cash consideration aggregating up to Rs. 72,15,00,000.",
    )
    rows = fe.model_rows(
        cash_doc, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="approved_board", instrument="preferential",
            amounts=[{"value_text": "Rs. 72,15,00,000", "number": 721500000, "unit": "unit", "currency": "INR", "role": "total_issue"}],
            shares=1300000,
        ),
    )
    assert len(rows) == 1 and rows[0]["amount_inr_cr"] == pytest.approx(72.15)

    # Multi-item board outcome (cash warrant conversion + separate scheme swap ratio item on page 3) stays
    multi_doc = _doc(
        "Outcome of the Board Meeting held on August 12, 2024",
        pages={
            1: "2. Allotment of 3,53,761 Equity Shares pursuant to conversion of warrants. The Company has received Rs. 2,57,36,112.75/-.",
            3: "Pursuant to revision in Valuation Report, the share swap ratio has been changed from 124 to 120.",
        },
    )
    m_rows = fe.model_rows(
        multi_doc, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="equity",
            amounts=[{"value_text": "Rs. 2,57,36,112.75/-", "number": 25736112.75, "unit": "unit", "currency": "INR", "role": "total_issue"}],
            shares=353761, price_per_share=72.75,
        ),
    )
    assert len(m_rows) == 1 and m_rows[0]["amount_inr_cr"] == pytest.approx(2.5736)


def test_r2_step2_board_intimation_skipped_and_counter_egm_notice_stays() -> None:
    bm1 = _doc(
        "Board Meeting intimation",
        "Pursuant to Regulations 29 and 50 of SEBI LODR, the Board Meeting of Uno Minda Limited will be held on Monday, September 14, 2026, in which it may, inter-alia, consider and approve the raising of funds through issue of Listed Non-Convertible Debentures.",
        doc_key="bm-1",
    )
    bm2 = _doc(
        "Intimation of Forthcoming Board Meeting- 27/11/2024",
        "A meeting of the Board of Directors of the company has been scheduled to be held on Wednesday, 27th day of November, 2024 to transact: 1. To consider & approve the allotment of 100 equity shares pursuant to approval obtained from shareholders in EGM held on 12th November, 2024.",
        doc_key="bm-2",
    )
    for d in (bm1, bm2):
        skips: list[dict[str, Any]] = []
        rows = fe.model_rows(
            d, ["fund_raise"],
            _reply(event_type="fund_raise", stage="approved_board", instrument="preferential"),
            skips_out=skips,
        )
        assert rows == []
        assert len(skips) == 1 and skips[0]["stage"] == "intimation"

    # Counter: Regulation 29(1)(d) EGM notice (shareholders' meeting) stays
    egm = _doc(
        "Intimation under regulation 29(1)(d) of SEBI LODR",
        "Notice of Extra-Ordinary General Meeting ('EGM'): the EGM of the Members of the Company will be held on June 25, 2025 to consider and approve issuance of 14,770,100 equity shares for INR 3,849,088,060.",
    )
    e_rows = fe.model_rows(
        egm, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="filed_offer_doc", instrument="preferential",
            amounts=[{"value_text": "INR 3,849,088,060", "number": 3849088060, "unit": "unit", "currency": "INR", "role": "total_issue"}],
            shares=14770100,
        ),
    )
    assert len(e_rows) == 1 and e_rows[0]["amount_inr_cr"] == pytest.approx(384.9088)


def test_r2_step3_amounts_unit_legs_price_shares_boilerplate_and_computed() -> None:
    # 3(a) parenthetical "(Indian Rupees Three Billion ...)" must not multiply full rupees by 100; >1,00,000 cr refused
    vssl = _doc(
        "Notice of EGM",
        "Issue of 14,770,100 equity shares for an aggregate amount of INR 3,849,088,060 (Indian Rupees Three Billion Eight Hundred Forty Nine Million Eighty Eight Thousand and Sixty only).",
    )
    r_vssl = fe.model_rows(
        vssl, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="filed_offer_doc", instrument="preferential",
            amounts=[{"value_text": "INR 3,849,088,060 (Indian Rupees Three Billion Eight Hundred Forty Nine Million Eighty Eight Thousand and Sixty only)",
                      "number": 3849088060, "unit": "unit", "currency": "INR", "role": "total_issue"}],
        ),
    )[0]
    assert r_vssl["amount_inr_cr"] == pytest.approx(384.9088)

    huge = _doc("Huge", "Raising Rs. 2,50,000 Crore.")
    r_huge = fe.model_rows(
        huge, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="approved_board", instrument="other",
            amounts=[{"value_text": "Rs. 2,50,000 Crore", "number": 250000, "unit": "crore", "currency": "INR", "role": "total_issue"}],
        ),
    )[0]
    assert r_huge["status"] == "quarantined" and r_huge["amount_inr_cr"] is None

    # 3(b) same-meeting legs across multiple events AND multiple total_issue inside one event; no double-count on combined total
    sejal_3legs = _doc(
        "Outcome of Board Meeting",
        "1. Equity shares aggregating up to Rs. 21,17,61,500. 2. Warrants aggregating up to Rs. 10,84,88,500/-. 3. QIP not exceeding Rs. 100 Crores.",
    )
    r_legs = fe.model_rows(
        sejal_3legs, ["fund_raise"],
        json.dumps({"events": [
            {"is_event": True, "event_type": "fund_raise", "stage": "approved_board", "instrument": "preferential", "shares": 347150,
             "amounts": [{"value_text": "Rs. 21,17,61,500", "number": 211761500, "unit": "unit", "currency": "INR", "role": "total_issue"}]},
            {"is_event": True, "event_type": "fund_raise", "stage": "approved_board", "instrument": "warrants", "shares": 177750,
             "amounts": [{"value_text": "Rs. 10,84,88,500/-", "number": 108488500, "unit": "unit", "currency": "INR", "role": "total_issue"}]},
            {"is_event": True, "event_type": "fund_raise", "stage": "approved_board", "instrument": "qip",
             "amounts": [{"value_text": "Rs. 100 Crores", "number": 100, "unit": "crore", "currency": "INR", "role": "total_issue"}]},
        ]}),
    )
    assert len(r_legs) == 1
    assert r_legs[0]["amount_inr_cr"] == pytest.approx(132.025, rel=1e-4)
    assert r_legs[0]["instrument"] == "mixed"
    assert "sum of printed legs" in r_legs[0]["detail"]

    bhag_2totals = _doc(
        "Preferential Issue",
        "Annexure A: Issue of 12,06,895 equity shares aggregating Rs.41,99,99,460/-. Annexure B: Issue of 2,94,539 equity shares aggregating Rs.10,24,99,572/-.",
    )
    r_bhag = fe.model_rows(
        bhag_2totals, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="approved_board", instrument="preferential",
            amounts=[
                {"value_text": "Rs.41,99,99,460/-", "number": 419999460, "unit": "unit", "currency": "INR", "role": "total_issue"},
                {"value_text": "Rs.10,24,99,572/-", "number": 102499572, "unit": "unit", "currency": "INR", "role": "total_issue"},
            ],
            shares=1501434,
        ),
    )
    assert len(r_bhag) == 1 and r_bhag[0]["amount_inr_cr"] == pytest.approx(52.2499, rel=1e-4)

    # Counter 3(b): two events sharing the SAME combined total_issue must not double count
    combined = _doc("Allotment", "Allotment of 81,77,068 shares and 1,11,70,000 warrants aggregating ₹905,44,27,824/-.")
    r_comb = fe.model_rows(
        combined, ["fund_raise"],
        json.dumps({"events": [
            {"is_event": True, "event_type": "fund_raise", "stage": "allotted", "instrument": "preferential", "shares": 8177068,
             "amounts": [{"value_text": "₹905,44,27,824/-", "number": 9054427824, "unit": "unit", "currency": "INR", "role": "total_issue"}]},
            {"is_event": True, "event_type": "fund_raise", "stage": "allotted", "instrument": "warrants", "shares": 11170000,
             "amounts": [{"value_text": "₹905,44,27,824/-", "number": 9054427824, "unit": "unit", "currency": "INR", "role": "total_issue"}]},
        ]}),
    )
    assert len(r_comb) == 1 and r_comb[0]["amount_inr_cr"] == pytest.approx(905.4428, rel=1e-4)

    # 3(c) + 3(f): face + premium -> issue price = 207, computed amount = 650000 * 207 / 1e7 = 13.455 cr
    modinatur = _doc(
        "Trading Approval",
        "Trading of 6,50,000 Equity Shares of Rs. 10.00/- each issued at a premium of Rs. 197.00/- per share.",
    )
    r_modi = fe.model_rows(
        modinatur, ["fund_raise"],
        _reply(event_type="fund_raise", stage="in_principle", instrument="preferential", shares=650000, price_per_share=197.0),
    )[0]
    assert r_modi["price_per_share"] == pytest.approx(207.0)
    assert r_modi["amount_inr_cr"] == pytest.approx(13.455)
    assert r_modi["method"] == "computed" and r_modi["value_text"] is None
    assert "650,000 x Rs 207 / 1e7" in r_modi["detail"]

    # Counter 3(c) + 3(d): "including premium" keeps issue price, Indian comma 10x slip on shares fixed, printed total keeps method='model'
    hfcl = _doc(
        "Allotment of Warrants",
        "Upon receipt of ₹138.75 crore, the Committee allotted 7,50,00,000 (Seven Crore Fifty Lakh) Warrants at ₹74/- per warrant.",
    )
    r_hfcl = fe.model_rows(
        hfcl, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="warrants",
            amounts=[{"value_text": "₹138.75 crore", "number": 138.75, "unit": "crore", "currency": "INR", "role": "total_issue"}],
            shares=750000000, price_per_share=74.0,
        ),
    )[0]
    assert r_hfcl["shares"] == pytest.approx(75000000.0)
    assert r_hfcl["amount_inr_cr"] == pytest.approx(138.75) and r_hfcl["method"] == "model"

    # 3(e): "About <Company>:" boilerplate amount rejected
    pdsl = _doc(
        "Press Release",
        pages={
            1: "Press Release titled Qualified Institutions Placement of the Company.",
            2: "PDS Successfully Raises crore (~$51mn) Through A QIP.\nAbout PDS Limited: (www.pdsltd.com)\nPDS engages dedicated talent and 370cr in FY24.",
        },
    )
    r_pdsl = fe.model_rows(
        pdsl, ["fund_raise"],
        _reply(
            event_type="fund_raise", stage="allotted", instrument="qip",
            amounts=[{"value_text": "370cr", "number": 370, "unit": "crore", "currency": "INR", "role": "total_issue"}],
        ),
    )[0]
    assert r_pdsl["amount_inr_cr"] is None and r_pdsl["value_text"] is None


def test_r2_step4_duplicates_same_text_and_revised_outcome() -> None:
    amends: list[dict[str, Any]] = []
    same_body = "Proceedings of 25th Annual General Meeting held on September 27, 2024: Issue of Convertible Equity Warrants. " * 3
    r1 = {
        "symbol": "STEELXIND", "kind": "fund_raise", "doc_key": "d-agm-1", "filing_date": "2024-09-27",
        "known_at": "2024-09-27T19:16:26", "raise_stage": "approved_shareholders", "shares": None,
        "amount_inr_cr": None, "amount_usd_mn": None, "title": "Proceedings of 25th AGM", "_text_full": same_body,
    }
    r2 = {
        "symbol": "STEELXIND", "kind": "fund_raise", "doc_key": "d-agm-2", "filing_date": "2024-09-27",
        "known_at": "2024-09-27T20:06:50", "raise_stage": "approved_shareholders", "shares": None,
        "amount_inr_cr": None, "amount_usd_mn": None, "title": "Proceeding of 25th AGM", "_text_full": same_body,
    }
    kept_same = fe._fold_same_raise([r1, r2], amends)
    assert len(kept_same) == 1 and len(amends) == 1

    # Same-day "Revised outcome" supersedes original
    amends2: list[dict[str, Any]] = []
    orig = {
        "symbol": "SEJALLTD", "kind": "fund_raise", "doc_key": "d-orig", "filing_date": "2025-09-15",
        "known_at": "2025-09-15T11:59:43", "raise_stage": "approved_board", "shares": 400000.0,
        "amount_inr_cr": None, "amount_usd_mn": None, "title": "Outcome of Board Meeting", "_text_full": "orig",
    }
    rev = {
        "symbol": "SEJALLTD", "kind": "fund_raise", "doc_key": "d-rev", "filing_date": "2025-09-15",
        "known_at": "2025-09-15T21:20:19", "raise_stage": "approved_board", "shares": 1300000.0,
        "amount_inr_cr": 94.35, "amount_usd_mn": None, "title": "Revised outcome", "_text_full": "revised",
    }
    kept_rev = fe._fold_same_raise([orig, rev], amends2)
    assert len(kept_rev) == 1 and kept_rev[0]["doc_key"] == "d-rev"
    assert amends2[0]["doc_key"] == "d-orig" and amends2[0]["amends"] == "d-rev"

    # Counter: different-day approval -> allotment stays 2 rows
    amends3: list[dict[str, Any]] = []
    appr = {
        "symbol": "ACME", "kind": "fund_raise", "doc_key": "d-appr", "filing_date": "2025-09-15",
        "known_at": "2025-09-15T11:00:00", "raise_stage": "approved_board", "shares": 1000000.0,
        "amount_inr_cr": 100.0, "amount_usd_mn": None, "title": "Outcome of Board Meeting", "_text_full": "board",
    }
    allot = {
        "symbol": "ACME", "kind": "fund_raise", "doc_key": "d-allot", "filing_date": "2025-10-15",
        "known_at": "2025-10-15T15:00:00", "raise_stage": "allotted", "shares": 1000000.0,
        "amount_inr_cr": 100.0, "amount_usd_mn": None, "title": "Allotment of shares", "_text_full": "allotted",
    }
    assert len(fe._fold_same_raise([appr, allot], amends3)) == 2


def test_r2_step5_order_win_capex_bg_repeat_band_and_inr_eqv(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # 5(a) Capex/greenfield press release mentioning order as background -> skipped
    capex_pr = _doc(
        "Press release titled \"Uno Minda to setup greenfield plant for four wheeler EV Powertrain products\"",
        "Uno Minda today announced that its Board has approved a new greenfield plant. Uno Minda has already secured e-axle order from a key anchor customer. Project cost is Rs 423 Crore.",
        doc_key="ow-capex",
    )
    skips_a: list[dict[str, Any]] = []
    assert fe.model_rows(capex_pr, ["order_win"], _reply(event_type="order_win", stage="received"), skips_out=skips_a) == []
    assert len(skips_a) == 1

    # 5(b) Repeat/update "further to our disclosure dated ..." with no new value -> skipped + linked in build()
    earlier = _doc(
        "Letter of award received from Oil and Natural Gas Corporation Limited",
        "Deep Industries Limited received LOA worth Rs. 1,402 Cr from ONGC.",
        doc_key="ow-orig", symbol="DEEPINDS", filing_date="2024-09-07", known_at="2024-09-07T15:38:49",
    )
    repeat = _doc(
        "Update with respect to Letter of Award received from Oil and Natural Gas Corporation Limited",
        "This is further to our disclosure dated September 07, 2024, regarding receipt of Letter of Award from ONGC. The details has already been disclosed in the intimation dated September 07, 2024.",
        doc_key="ow-rep", symbol="DEEPINDS", filing_date="2025-04-03", known_at="2025-04-03T12:00:00",
    )
    monkeypatch.setattr(fe, "load_docs", lambda store: [dict(earlier), dict(repeat)])

    class FakeClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None: pass
        def retry_after(self) -> float: return 0.0
        def chat(self, prompt: str) -> tuple[int, str, tuple[int, int]]:
            if "1,402 Cr" in prompt:
                return 200, _reply(
                    event_type="order_win", stage="loa", customer="ONGC",
                    amounts=[{"value_text": "Rs. 1,402 Cr", "number": 1402, "unit": "crore", "currency": "INR", "role": "order_size"}],
                ), (5, 5)
            return 200, _reply(event_type="order_win", stage="loa", customer="ONGC"), (5, 5)

    monkeypatch.setattr(fe, "Client", FakeClient)
    out_db = tmp_path / "ev.db"
    fe.build(stores=["cXX"], use_model=True, workers=1, out=out_db, cache=tmp_path / "c.json")
    con = sqlite3.connect(out_db)
    ev_dks = [r[0] for r in con.execute("SELECT doc_key FROM event").fetchall()]
    am_rows = con.execute("SELECT doc_key, amends FROM amend").fetchall()
    con.close()
    assert ev_dks == ["ow-orig"]
    assert ("ow-rep", "ow-orig") in am_rows

    # 5(c) Multi-order + band floor ("INR 300Cr+") -> 2 rows, amount_inr_cr=None, detail notes band floor
    bajel = _doc(
        "Press Release",
        "Bajel Projects Secures an Ultra-Mega Order worth INR 400 Cr+ and a Mega Order worth INR 300Cr+ from POWERGRID.",
    )
    b_rows = fe.model_rows(
        bajel, ["order_win"],
        json.dumps({"events": [
            {"is_event": True, "event_type": "order_win", "stage": "received", "customer": "POWERGRID",
             "amounts": [{"value_text": "INR 400 Cr+", "number": 400, "unit": "crore", "currency": "INR", "role": "order_size"}]},
            {"is_event": True, "event_type": "order_win", "stage": "received", "customer": "POWERGRID",
             "amounts": [{"value_text": "INR 300Cr+", "number": 300, "unit": "crore", "currency": "INR", "role": "order_size"}]},
        ]}),
    )
    assert len(b_rows) == 2
    assert all(r["amount_inr_cr"] is None and "band floor" in r["detail"] for r in b_rows)

    # 5(d) INR equivalent beside foreign currency ("AED 27.6 Million equivalent to INR 71 Crores")
    sejal_fx = _doc(
        "Receipt of Order",
        "Sejal Glass LLC has secured orders aggregating to approximately AED 27.6 Million equivalent to INR 71 Crores.",
    )
    r_fx = fe.model_rows(
        sejal_fx, ["order_win"],
        _reply(
            event_type="order_win", stage="received",
            amounts=[
                {"value_text": "AED 27.6 Million", "number": 27.6, "unit": "million", "currency": "AED", "role": "order_size"},
                {"value_text": "INR 71 Crores", "number": 71, "unit": "crore", "currency": "INR", "role": "other"},
            ],
        ),
    )[0]
    assert r_fx["amount_inr_cr"] == pytest.approx(71.0)
    assert r_fx["value_text"] == "AED 27.6 Million"


def test_r2_edge_regressions_kept_and_skipped() -> None:
    """Regressions from first model_v2 pass: gloss words, non-IPO OFS, warrant conversion, past-EGM intimation, made-on date."""
    # VASCONEQ #56: keep 'Crore' inside parenthetical gloss when leading number is small (660.79 < 100k)
    vascon = _doc(
        "Receipt of Order",
        "Vascon Engineers Limited has received Letter of Award amounting to Rs. 660.79/- (Rupees Six Hundred & Sixty Crore and Seventy Nine Lakhs Only).",
    )
    v_rows = fe.model_rows(
        vascon,
        ["order_win"],
        json.dumps({"events": [{
            "is_event": True, "event_type": "order_win", "stage": "received", "customer": "Client",
            "amounts": [{"value_text": "Rs. 660.79/- (Rupees Six Hundred & Sixty Crore and Seventy Nine Lakhs Only)",
                         "number": 660.79, "unit": "crore", "currency": "INR", "role": "order_size"}],
        }]}),
    )
    assert len(v_rows) == 1
    assert v_rows[0]["amount_inr_cr"] == pytest.approx(660.79)

    # NLCINDIA #10: NCD board outcome with Offer for Sale text in body stays kept
    nlc = _doc(
        "Outcome of Board Meeting - Raising of Funds through Non-Convertible Debentures",
        "Sub: Outcome of Board Meeting.\nApproved raising of funds by issue of NCDs up to Rs. 1500 Crore.\n" + ("x " * 160) + "Item 6: Offer for Sale (OFS) update.",
    )
    n_rows = fe.model_rows(
        nlc,
        ["fund_raise"],
        _reply(
            event_type="fund_raise", instrument="ncd", stage="approved_board",
            amounts=[{"value_text": "Rs. 1500 Crore", "number": 1500, "unit": "crore", "currency": "INR", "role": "total_issue"}],
        ),
    )
    assert len(n_rows) == 1
    assert n_rows[0]["amount_inr_cr"] == pytest.approx(1500.0)

    # KAMATHOTEL #39: exercise of option of conversion of warrants past char 1200 on p1 + Item 5 share swap on p2 stays kept
    kamat = _doc(
        "We are attaching herewith, an Outcome of the Board Meeting held on August 12, 2024",
        pages={
            1: ("Sub.: Outcome of the Board Meeting. 1. Unaudited Financial Results approved. " + ("x " * 650)
                + "2. Allotment of 3,53,761 Equity Shares pursuant to conversion of warrants allotted on preferential basis. "
                + "The Company has received Rs. 2,57,36,112.75/- warrant exercise price."),
            2: ("5. Updates on Proposed Scheme of Arrangement: share swap ratio has been changed from 124 to 120. "
                "Excluding potential exercise of option of conversion of outstanding warrants."),
        },
    )
    k_rows = fe.model_rows(
        kamat,
        ["fund_raise"],
        _reply(
            event_type="fund_raise", instrument="warrant", stage="allotted",
            shares=353761, price_per_share=72.75,
            amounts=[{"value_text": "Rs. 2,57,36,112.75/-", "number": 25736112.75, "unit": "unit", "currency": "INR", "role": "total_issue"}],
        ),
    )
    assert len(k_rows) == 1
    assert k_rows[0]["amount_inr_cr"] == pytest.approx(2.5736)

    # BETA #49: Forthcoming Board Meeting citing past EGM is skipped as intimation
    beta_int = _doc(
        "Board Meeting Intimation - Forthcoming Board Meeting",
        "Sub: Intimation of Forthcoming Board Meeting to consider preferential issue pursuant to approval at Extra Ordinary General Meeting held on 12th November, 2024.",
    )
    b_skips: list[dict[str, Any]] = []
    b_rows = fe.model_rows(
        beta_int,
        ["fund_raise"],
        _reply(
            event_type="fund_raise", instrument="preferential", stage="approved_board",
            amounts=[{"value_text": "Rs. 100 Crore", "number": 100, "unit": "crore", "currency": "INR", "role": "total_issue"}],
        ),
        skips_out=b_skips,
    )
    assert b_rows == []
    assert len(b_skips) == 1 and b_skips[0]["stage"] == "intimation"

    # RUSTOMJEE #39: repeat update referring to disclosure 'made on July 1, 2025' is skipped with _ref_date=2025-07-01
    rustom_clar = _doc(
        "Clarification on announcement made on July 1, 2025",
        "Further to our disclosure dated made on July 1, 2025 regarding the order, we clarify the typographical error. Earlier communication dated 30/06/2025 noted.",
    )
    r_skips: list[dict[str, Any]] = []
    r_rows = fe.model_rows(
        rustom_clar,
        ["order_win"],
        _reply(event_type="order_win", stage="received", customer="Client", amounts=[]),
        skips_out=r_skips,
    )
    assert r_rows == []
    assert len(r_skips) == 1 and r_skips[0].get("_ref_date") == "2025-07-01"

    # _fold_same_raise prefers printed value_text (method='model') over method='computed' twin
    amends: list[dict[str, Any]] = []
    comp_early = {
        "symbol": "KRN", "kind": "fund_raise", "doc_key": "d-comp", "filing_date": "2025-08-01",
        "known_at": "2025-08-01T10:00:00", "raise_stage": "allotted", "shares": 1000000.0,
        "amount_inr_cr": 100.0, "amount_usd_mn": None, "method": "computed", "value_text": None,
        "title": "Allotment", "_text_full": "allotment board",
    }
    printed_late = {
        "symbol": "KRN", "kind": "fund_raise", "doc_key": "d-print", "filing_date": "2025-08-01",
        "known_at": "2025-08-01T12:00:00", "raise_stage": "allotted", "shares": 1000000.0,
        "amount_inr_cr": 100.0, "amount_usd_mn": None, "method": "model", "value_text": "Rs. 100 Crore",
        "title": "Press Release - Allotment", "_text_full": "press release",
    }
    kept = fe._fold_same_raise([comp_early, printed_late], amends)
    assert len(kept) == 1 and kept[0]["doc_key"] == "d-print"
    assert amends[0]["doc_key"] == "d-comp" and amends[0]["amends"] == "d-print"





def test_main_names_store_root_and_refuses_missing_store(tmp_path, monkeypatch, capsys):
    """T-242 (26 Nov): a --stores name missing under the resolved root stops the run (rc 2), root printed first."""
    from reality_engine.research import driver_claims, filing_events
    monkeypatch.setattr(driver_claims, "STORE_ROOT", tmp_path)
    monkeypatch.delenv("T228_STORE_ROOT", raising=False)
    assert filing_events.main(["--stores", "c999", "--no-model", "--out", str(tmp_path / "x.db")]) == 2
    assert "T228_STORE_ROOT set" in capsys.readouterr().err
    monkeypatch.setenv("T228_STORE_ROOT", str(tmp_path))
    rc = filing_events.main(["--stores", "c999", "--no-model", "--out", str(tmp_path / "x.db"),
                             "--report-file", str(tmp_path / "r.md")])
    out = capsys.readouterr()
    assert rc == 2
    assert out.out.splitlines()[0].startswith(f"store root: {tmp_path}")
    assert "c999" in out.err
