"""T-231: filing-level events -- classification and printed-value parsing on real and synthetic filings.

Every ``REAL`` fixture is a verbatim excerpt from the announcement its ``doc_key`` names in the measured stores
(``D:/RealityEngine/tg_build/measure10``), one per class and three per class, as the brief requires.  Synthetic
cases cover the shapes the brief calls out: a board-meeting intimation is not a raise, a court order is not an
order win, a forward capacity plan is not commissioned capacity, an addendum links instead of becoming an event,
and a model amount must be printed with its unit.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from reality_engine.research import filing_events as fe

OUT_DIR = Path(".tmp/t231")


@pytest.fixture(autouse=True)
def _order_win_checks_as_gated(request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch) -> None:
    """These tests check the order_win row checks, so they run with order_win as a gated kind.  The LIVE gate is
    empty since 25 Nov 2026 (order_win failed its fresh-store grade 39/5/14/2); `test_live_gate` checks that."""
    if "live_gate" not in request.node.name:
        monkeypatch.setattr(fe, "VERIFIED_KINDS", frozenset({"order_win"}))


def test_live_gate_is_empty_until_a_kind_passes_a_fresh_store_grade() -> None:
    assert fe.VERIFIED_KINDS == frozenset()
    order = _doc("New orders worth Rs. 816 Crores",
                 "The Company has secured new orders of Rs. 816 crores across its various businesses.")
    row = _row(fe.event_rows(order)[0], "order_win")
    assert row["status"] == "unverified" and "kind_not_gated: order_win" in row["detail"]


def _doc(title: str, text: str, *, symbol: str = "ACME", doc_key: str = "doc-1",
         filing_date: str = "2026-01-05", known_at: str = "2026-01-05T10:00:00") -> dict[str, Any]:
    return {"store": "cXX", "symbol": symbol, "isin": "INE000A01001", "doc_key": doc_key, "title": title,
            "filing_date": filing_date, "known_at": known_at, "pages": {1: text}, "text": text, "head": text}


def _row(rows: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    found = [row for row in rows if row["kind"] == kind]
    assert len(found) == 1, f"expected one {kind} row, got {[row['kind'] for row in rows]}"
    return found[0]


# ---- real announcement excerpts (verbatim, doc_key quoted) -----------------------------------------------
REAL: dict[str, list[dict[str, Any]]] = {
    "order_win": [
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/MICEL/material_filing/d03ae644-1b18-4378-bf4f-3c22694335bf.pdf",
         "title": "MIC Electronics Limited hereby informs you that the company has received a letter of acceptance "
                  "from the Malda Division of the Eastern Railway Zone.",
         "text": "MIC Electronics Limited ('the Company') hereby informs you that the Company has received Letter of "
                 "Acceptance from the Malda Division of the Eastern Railway Zone for replacement of CIB, TIB of PF "
                 "No: 1, 4&5 and passenger amenities at Bhagalpur Station of the Malda Division. The aggregate value "
                 "of the said Work-Order is Rs. 1,47,24,831.24 (Rupees One Crore Forty-Seven Lakh Twenty-Four "
                 "Thousand Eight Hundred and Thirty-One Rupees and Twenty-Four Paise Only). Additional details of "
                 "Work-Order are enclosed as Annexure.",
         "expect": {"amount_inr_cr": 1.4725, "status": "verified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/MICEL/material_filing/3f7108c7-6b20-4123-a701-a09bdeb717c3.pdf",
         "title": "MIC Electronics Limited hereby informs you that the company has received a letter of acceptance "
                  "from the Firozpur division and also received a letter of completion/installation.",
         "text": "MIC Electronics Limited ('the Company') hereby informs you that the Company has received a Letter of "
                 "Acceptance from the Firozpur Division of the Northern Railway Zone for the provision of coach "
                 "guidance display boards at major and important stations in the Firozpur (FZR) Division. The "
                 "aggregate value of the said work order is Rs. 3,04,95,149.54/- (three crores, four lakhs, "
                 "ninety-five thousand, one hundred and forty-nine rupees, and fifty-four paise only).",
         "expect": {"amount_inr_cr": 3.0495, "status": "verified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/ROTO/material_filing/9c33f96d-49ce-4416-9671-d56750e5c167.pdf",
         "title": "We hereby intimate receipt of major purchase order.",
         "text": "Name of the entity awarding the order(s) / contract(s); GPS Renewables Pvt Ltd. 4. Nature of "
                 "order(s) / contract(s); Designing, Engineering, Supply of Pumps 6. Time period by which the "
                 "order(s)/contract(s) is to be executed; Supply to be completed within current financial year in "
                 "phased manner 7. Broad consideration or size of the order(s)/contract(s); Twelve orders for supply "
                 "of Pumps totalling to ₹ 14.40 Crores plus applicable goods and service tax",
         "expect": {"amount_inr_cr": 14.4, "customer": "GPS Renewables Pvt Ltd", "status": "verified"}},
    ],
    "capex_approval": [
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/SESHAPAPER/material_filing/c20191bf-2ec5-41a8-b9f3-c16799b0ae06.pdf",
         "title": "Updates under Regulation 30 of SEBI (LODR) Regulations, 2015",
         "text": "In this background, the Board of Directors, in their meeting held today, has approved speedy revival, "
                 "refurbishment and expeditious recommencement of the operations of Unit-Ill, at the earliest and "
                 "has accordingly approved a Capital expenditure of Rs.100.0 crores as Phase- I, towards this purpose.",
         "expect": {"amount_inr_cr": 100.0, "status": "unverified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/SPMLINFRA/material_filing/73807300-d232-4447-9dbe-39f233944370.pdf",
         "title": "Outcome of Board Meeting",
         "text": "The Board has approved an increase in capital expenditure from ₹176.44 crore to ₹238.43 crore to "
                 "support the expansion of BESS capacity from 2.5 GWh to 5 GWh. This includes the development of "
                 "allied facilities such as container manufacturing capacity of 600 units per annum.",
         "expect": {"amount_inr_cr": 238.43, "status": "unverified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/RAJRILTD/material_filing/a3a0af34-ccba-4445-b67e-36e24fa9b833.pdf",
         "title": "Raj Rayon Industries Limited announces Rs 650 Crore Phase -II Expansion",
         "text": "Press Release - Raj Rayon Industries Limited -Announces Rs. 650 Crore Phase II Expansion. Board "
                 "approves up to Rs. 650 crore Phase II expansion at the Company's existing Silvassa facility, adding "
                 "300 TPD polyester yarn and 50 TPD recycled polyester yarn capacity; Full Capacity Commissioning in "
                 "CY2028.",
         "expect": {"amount_inr_cr": 650.0, "status": "unverified"}},
    ],
    "capacity_commissioned": [
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/WEBELSOLAR/material_filing/2a4c5c86-2b95-46c1-8db8-48eb2b0ba730.pdf",
         "title": "PRESS RELEASE DATED 03.11.2025",
         "text": "Business Highlights: Commenced production of additional 600 MW Mono PERC solar cell line (Phase II) "
                 "at Falta, West Bengal, taking overall cell capacity to 1,200 MW. Planned total capacity addition of "
                 "4 GW Topcon solar cell line: Phase III of 2 GW by June 2027 and Phase IV of 2 GW by June 2028.",
         "expect": {"capacity_value": 600.0, "capacity_unit": "mw", "status": "unverified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/GREENPOWER/material_filing/d431890a-a559-49a4-ae51-e1ad0b16313b.pdf",
         "title": "Intimation under Regulation 30 of the SEBI [Listing Obligations and Disclosure Requirements] Regulations, 2015.",
         "text": "The Company has successfully commissioned a 7 MW AC / 9.8 MW DC solar power project at Krishnapuram "
                 "and Veeraganallur Villages, Thiruvallur District, Tamil Nadu. Further, the Company has entered into "
                 "an EPC Contract to develop a 17.6 MW AC (24.64 MW DC) solar power project, and the same is under "
                 "progress.",
         "expect": {"capacity_value": 7.0, "capacity_unit": "mw", "status": "unverified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/ADVAIT/material_filing/7d639f28-988a-4ad6-8385-d830ada502a0.pdf",
         "title": "Inauguration of new manufacturing facility of Advait Greenergy Private Limited, material subsidiary.",
         "text": "Advait Greenergy Private Limited, material subsidiary of Advait Energy Transitions Limited, has "
                 "officially inaugurated its Phase I - 30 MW Alkaline Electrolyser Assembly Facility on March 13, "
                 "2026. Advait Greenergy Private Limited has commissioned its Phase I - 30 MW Alkaline Electrolyser "
                 "Assembly Facility, a strategic step towards a 300 MW integrated manufacturing capacity.",
         "expect": {"capacity_value": 30.0, "capacity_unit": "mw", "status": "unverified"}},
    ],
    "fund_raise": [
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/SALSTEEL/material_filing/ca587c2e-dc4b-4eba-85b3-89ee1022ea40.pdf",
         "title": "Approval of Board of Directors of the Company for fund raising by way of preferential issue of "
                  "convertible equity warrants on a private placement basis",
         "text": "at a price of ₹ 25/- per Warrant including Premium of ₹ 15/- each, being the issue price determined "
                 "in accordance with the provisions of the Companies Act, 2013, aggregating up to ₹ 12.00 Crores to "
                 "the Promoter Allottee, on a preferential and private placement basis.",
         "expect": {"amount_inr_cr": 12.0, "instrument": "warrant", "status": "unverified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/99a1a419-5563-4437-89d4-7445ccd76e4d.pdf",
         "title": "Approval of fund raise by way of Equity Shares for an aggregate amount of up to Rs. 500 crores "
                  "by way of rights issue",
         "text": "The Board of Directors of the Company, at their meeting held today, i.e., November 22, 2024 has "
                 "inter alia considered and approved the following: Approval of fund raise by way of Equity Shares "
                 "for an aggregate amount of up to Rs. 500 crores by way of rights issue.",
         "expect": {"amount_inr_cr": 500.0, "instrument": "rights", "status": "unverified"}},
        {"doc_key": "D:/RealityEngine/raw/pilot60_history/SUDARSHAN/material_filing/2ea66984-6120-4dd2-9641-5c55f9893ef4.pdf",
         "title": "Raising of funds by way of creating, issuing and allotting up to 4,30,00,000 Fully Convertible "
                  "Warrants Convertible into equivalent number of fully paid-up equity shares",
         "text": "RAISING OF FUNDS UP TO RS.188.34 CRORES THROUGH PREFERENTIAL BASIS: through raising of funds by way "
                 "of creating, issuing and allotting up to 4,30,00,000 (Four Crores Thirty Lakhs Only) Fully "
                 "Convertible Warrants Convertible into equivalent number of fully paid-up equity shares, on "
                 "preferential basis, for aggregating amount of up to Rs.188.34 Crores.",
         "expect": {"amount_inr_cr": 188.34, "instrument": "warrant", "status": "unverified"}},
    ],
}


@pytest.mark.parametrize("kind", list(REAL))
def test_three_real_announcements_per_class(kind: str) -> None:
    for fixture in REAL[kind]:
        doc = _doc(fixture["title"], fixture["text"], doc_key=fixture["doc_key"])
        rows, missing = fe.event_rows(doc)
        row = _row(rows, kind)
        assert kind not in missing, missing
        for field, expected in fixture["expect"].items():
            assert row[field] == expected, (kind, fixture["doc_key"], field, row[field])
        assert row["method"] == "script" and row["known_at"] == doc["known_at"]
        assert row["value_text"] and row["value_text"] in doc["text"]
        assert row["page"] == 1


def test_printed_aggregate_beats_a_shares_times_price_computation() -> None:
    text = ("The Board of Directors has approved and allotted 4,38,000 equity shares of face value of Rs.1/- each "
            "consequent to the Conversion of 4,38,000 Convertible Warrants, at a price of Rs. 47.625 per warrant, "
            "aggregating to Rs. 2,08,59,750/-.")
    row = _row(fe.event_rows(_doc("Outcome of Board Meeting", text))[0], "fund_raise")
    assert row["amount_inr_cr"] == pytest.approx(2.086) and row["status"] == "unverified"
    assert row["instrument"] == "warrant"


def test_shares_times_price_without_a_printed_aggregate_is_unverified() -> None:
    text = "The Board has allotted 1,00,000 equity shares at an issue price of Rs. 10 per equity share."
    row = _row(fe.event_rows(_doc("Allotment of equity shares", text))[0], "fund_raise")
    assert row["amount_inr_cr"] == pytest.approx(0.1) and row["status"] == "unverified"


def test_monthly_order_value_is_multiplied_by_the_execution_months() -> None:
    text = ("3 Whether order(s) / contract(s) have been awarded by domestic/ international entity; Domestic Entity "
            "6 Time period by which the order(s)/contract(s) is to be executed; 1 year "
            "7 Broad consideration or size of the order(s)/contract(s); Approximately monthly value of Rs.10,32,566")
    row = _row(fe.event_rows(_doc("Intimation under Regulation 30", text))[0], "order_win")
    assert row["amount_inr_cr"] == pytest.approx(1.2398, rel=1e-3)
    assert row["execution_months"] == 12 and row["status"] == "unverified"


# ---- negatives the brief calls out ----------------------------------------------------------------------
@pytest.mark.parametrize("title,text,absent", [
    ("Board Meeting Intimation under Regulation 29",
     "The meeting of the Board of Directors is scheduled to consider and approve raising of funds up to Rs. 500 crore.",
     "fund_raise"),
    ("Credit rating revision",
     "CRISIL Ratings has revised its ratings. The framework for fund raising by issuance of debt securities by "
     "Large Corporates is not applicable to the Company.",
     "fund_raise"),
    ("Order passed by the Hon'ble High Court of Delhi",
     "The Hon'ble High Court passed the order in terms of settlement in favour of the Company.",
     "order_win"),
    ("Statement of Deviation or Variation of Rights Issue Proceeds",
     "We enclose the statement of utilisation of rights issue proceeds of Rs. 230 crores raised on 23 September 2023.",
     "fund_raise"),
    ("Capacity addition of 600 MW Cell Line",
     "The new line is expected to be installed and commissioned in the first quarter of 2025-26. Commercial "
     "production is estimated to commence in July 2026.",
     "capacity_commissioned"),
])
def test_false_shapes_are_not_events(title: str, text: str, absent: str) -> None:
    assert absent not in fe.classify(title, text)
    assert not [row for row in fe.event_rows(_doc(title, text))[0] if row["kind"] == absent]


# ---- one per filing, one per class, addendum, parent scope ------------------------------------------------
def test_two_orders_in_one_filing_make_two_rows() -> None:
    block = ("Name of entity awarding the order(s)/contract(s) {name} "
             "Time period by which the order(s)/contract(s) is to be executed 12 months "
             "Broad consideration or size of the order(s)/contract(s) Rs. {value} Crores")
    text = "Order No.1 " + block.format(name="Alpha Ltd", value="100") + " Order No.2 " + block.format(
        name="Beta Ltd", value="200")
    rows, _missing = fe.event_rows(_doc("The Company has secured two orders aggregating to Rs. 300 Crores", text))
    orders = sorted((row for row in rows if row["kind"] == "order_win"), key=lambda row: row["seq"])
    assert [(row["seq"], row["amount_inr_cr"]) for row in orders] == [(1, 100.0), (2, 200.0)]
    assert "Alpha Ltd" in (orders[0]["customer"] or "") and "Beta Ltd" in (orders[1]["customer"] or "")


def test_addendum_links_to_the_filing_it_names_instead_of_becoming_an_event() -> None:
    original = _doc("The Company has secured an order worth Rs. 100 Crores", "order worth Rs. 100 Crores",
                    doc_key="orig", filing_date="2024-01-10", known_at="2024-01-10T10:00:00")
    addendum = _doc("Addendum dated 10.01.2024 to the intimation of order", "the order value is unchanged",
                    doc_key="add", filing_date="2024-02-01", known_at="2024-02-01T10:00:00")
    amends, skipped = fe.amend_rows([original, addendum], classified={"orig", "add"})
    assert skipped == {"add"} and len(amends) == 1 and amends[0]["amends"] == "orig"
    # an addendum whose filing is not an event and whose target is not one is never linked
    other = _doc("Addendum to charter party dated 10.01.2024", "charter hire extension",
                 doc_key="other", filing_date="2024-02-01")
    amends, skipped = fe.amend_rows([original, other], classified={"orig"})
    assert amends == [] and skipped == set()


def test_parent_release_is_kept_but_marked_parent_and_unverified() -> None:
    text = "The Company has received an order of Rs. 100 Crores from Acme."
    doc = _doc("Media Release issued by the Ultimate Holding Company", text)
    row = _row(fe.event_rows(doc)[0], "order_win")
    assert row["entity_scope"] == "parent" and row["status"] == "unverified"


# ---- model fallback: strict JSON, printed value and unit --------------------------------------------------
def _model_reply(**event: Any) -> str:
    import json
    payload = {"events": [{"kind": "order_win", "amount_inr_cr": None, "amount_usd_mn": None, "value_text": None,
                           "customer": None, "execution_months": None, "purpose": None, "completion": None,
                           "capacity_value": None, "capacity_unit": None, "plant": None, "price_per_share": None,
                           "shares": None, "instrument": None, **event}]}
    return json.dumps(payload)


def test_model_value_must_be_printed_with_its_unit() -> None:
    doc = _doc("As attached", "The Company has received an order of Rs. 200 crore from Acme Limited.")
    (good,) = fe.model_rows(doc, ["order_win"],
                            _model_reply(amount_inr_cr=200, value_text="Rs. 200 crore"))
    assert good["status"] == "verified" and good["method"] == "model" and good["page"] == 1
    (no_unit,) = fe.model_rows(doc, ["order_win"], _model_reply(amount_inr_cr=63, value_text="Rs. 63.00"))
    assert no_unit["status"] == "unverified" and "unit" in no_unit["detail"]
    (missing,) = fe.model_rows(_doc("As attached", "Nothing printed here."), ["order_win"],
                               _model_reply(amount_inr_cr=200, value_text="Rs. 200 crore"))
    assert missing["status"] == "quarantined"


# ---- Stage B fixtures: the texts Wolf's read A cited (verbatim excerpts, doc_key quoted) ------------------
STAGE_B: dict[str, dict[str, Any]] = {
    "cncrd_274": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/CNCRD/material_filing/x274.pdf",
        "title": "Receives Contract of 3100 HP Green Hydrogen Hybrid Locomotive",
        "text": "Name of the entity awarding the order: NTPC Limited. Broad consideration or size of the order: "
                "Approx. Rs. 47 Crores. Nature of Contract: Supply of all plant and equipment for Green Hydrogen "
                "Fuel Cell Locomotive (Retrofitted). The details as required to disclosed is attached.; "
                "Broad consideration or size of the order(s)/contract(s); Approx. Rs. 47 Crores; Time period ... "
                "Within 18 months",
    },
    "krystal_66": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x66.pdf",
        "title": "Intimation Under Regulation 30 of SEBI (Listing Obligations And Disclosure Requirements) "
                 "Regulations, 2015",
        "text": "Krystal Integrated Services Limited has received a work order from Directorate of Medical Education "
                "and Research, Maharashtra on October 11, 2024 for providing Facility Management Services. "
                "1 Name of the entity awarding the order(s)/contract(s); Directorate of Medical Education and "
                "Research, Maharashtra 6 Time period by which the order(s)/contract(s) is to be executed; "
                "3 years 7 Broad consideration or size of the order(s)/contract(s); Approximately Yearly value of "
                "Rs. 55 Crore",
    },
    "krystal_68": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x68.pdf",
        "title": "Announcement under Regulation 30 (LODR)-Press Release",
        "text": "Subject - Press Release to announce receipt of work order from Directorate of Medical Education and "
                "Research, Maharashtra for providing Facility Management Services. Krystal Integrated Services "
                "Limited Secures ₹55 Crore Contract for Facility Management Services in Maharashtra.",
    },
    "premex_163": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/PREMEXPLN/material_filing/x163.pdf",
        "title": "Amendment of Purchase Order received from an International entity on June 19, 2025, i.e., "
                 "increase in total value from USD 762,860.08 (i.e. Rs. 6.62 crores) to USD 21,33,750 "
                 "(i.e. Rs. 18.29 crores).",
        "text": "In continuation to our intimation dated June 19, 2025 to the Stock Exchanges, we would like to "
                "inform about the amendment of purchase order received from an International entity, for the "
                "manufacture and supply of Defence Products ie., an increase in the total value from USD "
                "762,860.08 (i.e. Rs. 6.62 crares) to USD 21,33,750 (ie., Rs. 18.29 crores), to be delivered "
                "within a period of 6 months.",
    },
    "micel_227": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/MICEL/material_filing/x227.pdf",
        "title": "Receipt of LOA variation from Indian Railways.",
        "text": "The Company has received a Letter of Variations as detailed below: 1. LOA variation received from "
                "South East Central Railway ... for an amount of Rs. 82,56,066/- 2. LOA variation received from "
                "Northern Railway ... for an amount of Rs. 33,08,094/- The aggregate value of the said work orders "
                "are Rs. 1,15,64,160/-.",
    },
    "krystal_132": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x132.pdf",
        "title": "Intimation Under Regulation 30 of SEBI (Listing Obligations And Disclosure Requirements) "
                 "Regulations, 2015",
        "text": "The Company has received a contract from SVC Co-Operative Bank Limited for providing Security "
                "services. 6 Time period by which the order(s)/contract(s) is to be executed; From May 01, 2025 to "
                "March 31, 2027 7 Broad consideration or size of the order(s)/contract(s); Contract value of "
                "Rs. 4,48,15,487.52/- per annum, excluding taxes and duties.",
    },
    "krystal_394": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x394.pdf",
        "title": "Intimation under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) "
                 "Regulations, 2015.",
        "text": "Krystal Integrated Services Limited, in consortium with M/s. LC Infra Projects Private Limited, has "
                "received two work orders from Government of Maharashtra. The aggregate contract value of the two "
                "work orders is Rs. 7,40,06,30,000 Crore, including GST. The Company's share in the Consortium is "
                "40%, aggregating to approximately Rs. 2,96,02,52,000 Crore. The contracts are for a period of "
                "2 (Two) years.",
    },
    "spml_299": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SPMLINFRA/material_filing/x299.pdf",
        "title": "SPML Infra wins Rs. 344.64 Crore Order for water Infrastructure Project under Amrut Scheme in "
                 "Chennai",
        "text": "The Company has secured a significant new project worth Rs. 344.64 crore from the Chennai "
                "Metropolitan Water Supply and Sewerage Board. The order is awarded to the consortium comprising "
                "SPML Infra Limited, JWIL Infra Limited, and Vishnusurya Projects & Infra Private Limited in JV. "
                "The consortium of M/s JWIL Infra Limited (Equity Share of 64%) and M/s SPML Infra Limited (Equity "
                "share of 26%) and M/s Vishnusurya Projects and Infra Limited (Equity share of 10%).",
    },
    "rane_349": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/RANEHOLDIN/material_filing/x349.pdf",
        "title": "Order received by Rane Steering Systems Private Limited, wholly owned material subsidiary",
        "text": "Form A Disclosure by Rane Holdings Limited regarding receipt of communication from regulatory, "
                "statutory, enforcement or judicial authority. Authority: Hon'ble High Court of Madras. RSSL has "
                "obtained a stay order from Hon'ble High Court of Madras setting aside the order passed by "
                "Assessment Unit of Income Tax Department.",
    },
    "suryoday_10": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SURYODAY/material_filing/x10.pdf",
        "title": "Allotment of Equity Shares of the Bank pursuant to exercise of stock option under Suryoday ESOP "
                 "Scheme 2019",
        "text": "14,227 Equity Shares of face value of Rs. 10/- each have been allotted today pursuant to the "
                "exercise of Options by the employee(s) of the Bank under ESOP Scheme 2019, 7,125 Equity Shares at "
                "the Exercise Price of Rs. 114.25/- per Equity Share.",
    },
    "kopran_413": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KOPRAN/material_filing/x413.pdf",
        "title": "Allotment of ESOP Shares",
        "text": "The Corporate Affairs Committee has approved the allotment of 40500 Equity Shares of face value of "
                "Re. 10/- each to the eligible employees upon exercise of the Options under the Kopran Employee "
                "Stock Option Plan 2023 at the exercise price of Rs 179/- per share.",
    },
    "salsteel_240": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SALSTEEL/material_filing/x240.pdf",
        "title": "Vivro Financial Services Private Limited (Manager to the Offer) has submitted a Pre-Offer "
                 "advertisement",
        "text": "OPEN OFFER FOR THE ACQUISITION OF UP TO 3,76,39,342 FULLY PAID-UP EQUITY SHARES OF SAL STEEL "
                "LIMITED AT A PRICE OF Rs. 25/- PER EQUITY SHARE FROM THE PUBLIC SHAREHOLDERS OF THE TARGET COMPANY "
                "BY SREE METALIKS LIMITED (THE ACQUIRER) PURSUANT TO SEBI (SAST) REGULATIONS, 2011.",
    },
    "shreepushk_231": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SHREEPUSHK/material_filing/x231.pdf",
        "title": "Raising of Funds by Issue of Fully Convertible Warrants to the Promoter of the Company on "
                 "Preferential Basis",
        "text": "The Board of Directors at its Meeting held today considered, discussed and approved the following: "
                "B. Expansion of Madhya Bharat Phosphate Private Limited, a Material Wholly Owned Subsidiary: "
                "Capital Expenditure of Rs. 350 crores in Madhya Bharat Phosphate Private Limited. "
                "D. Raising of Funds by Issue of Fully Convertible Warrants: Issuance of upto 7,36,196 (Seven "
                "Lakhs Thirty Six Thousand One Hundred and Ninety Six Only) Fully Convertible Warrants, at a "
                "price of Rs. 407.50/- each on a Preferential Basis to the Promoter.",
    },
    "spml_347": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SPMLINFRA/material_filing/x347.pdf",
        "title": "Outcome of Board Meeting",
        "text": "1. Issuance of up to 3,09,141 Equity Shares of face value of Rs. 2/- each at an issue price of "
                "Rs. 186/- per equity share aggregating up to Rs. 5.75 crores on preferential basis. 2. Issuance "
                "of up to 95,39,449 Warrants at an issue price of Rs. 186/- per warrants aggregating up to "
                "Rs. 177.43 crores. 3. Issuance of up to 3,84,858 Equity Shares at an issue price of Rs. 186/- "
                "per equity share aggregating up to Rs. 7.16 crores. 5. The Board has approved an increase in "
                "capital expenditure from ₹176.44 crore to ₹238.43 crore.",
    },
    "asianene_63": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ASIANENE/material_filing/x63.pdf",
        "title": "Asian Energy Services Limited secures Rs. 82 crores contract from Oil India for 2D Seismic Data "
                 "in Rajasthan Basin.",
        "text": "Asian Energy Services Limited (AESL) has been awarded an order from Oil India for 2D Seismic Data "
                "Acquisition of 4,300 LKM in Rajasthan Basin. The total contract value is ~Rs 82 crores inclusive "
                "of all taxes and duties and the order will be executed over a span of 18 months. The total order "
                "book as on date stands at approx Rs 1,000 crs.",
    },
    "blkashyap_910": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/BLKASHYAP/material_filing/x910.pdf",
        "title": "B. L. Kashyap and Sons Limited has secured a new order of Rs. 910 Crores excluding GST.",
        "text": "B.L. Kashyap and Sons Limited has secured an order of the Company the details as under given below: "
                "a Name of entity awarding the order(s)/ contract(s) BPTP Limited f Time period by which the "
                "order(s)/ contract(s) is to be executed 36 months approx. g Broad consideration or size of the "
                "order(s)/contract(s) ₹ 910 Crores (excluding GST)",
    },
    "jyoti_6796": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x6796.pdf",
        "title": "Intimation on New Project Order",
        "text": "The Company has entered into a Contract Agreement with National Transmission Network Service "
                "Provider (Private) Limited, in a joint venture with Fentons, for execution of the project as per "
                "details given below: (a) Project Name Mullikulam Wind Power Transmission Project (b) EPC Contractor "
                "Jyoti Structures Limited India and Fentons Joint Venture (c) Location Sri Lanka (d) Scope of Work "
                "Lot B: Construction of 28km long, 220kV double circuit transmission line (e) Value Rs. 67.96 "
                "Crores (f) Completion Period 18 months",
    },
}


STAGE_B_SYMBOL = {
    "cncrd_274": "CNCRD", "krystal_66": "KRYSTAL", "krystal_68": "KRYSTAL", "premex_163": "PREMEXPLN",
    "micel_227": "MICEL", "krystal_132": "KRYSTAL", "krystal_394": "KRYSTAL", "spml_299": "SPMLINFRA",
    "rane_349": "RANEHOLDIN", "suryoday_10": "SURYODAY", "kopran_413": "KOPRAN", "salsteel_240": "SALSTEEL",
    "shreepushk_231": "SHREEPUSHK", "spml_347": "SPMLINFRA", "asianene_63": "ASIANENE",
    "blkashyap_910": "BLKASHYAP", "jyoti_6796": "JYOTISTRUC",
}


@pytest.mark.parametrize("case,expected", [
    ("cncrd_274", {"amount_inr_cr": 47.0, "status": "verified", "flag": "B1 doubled cover+annexure figure"}),
    ("premex_163", {"amount_inr_cr": 11.67, "status": "unverified", "value_total": 18.29,
                    "flag": "B3 amendment increment"}),
    ("micel_227", {"amount_inr_cr": 1.1564, "status": "unverified", "flag": "B3 variation aggregate"}),
    ("krystal_132", {"value_annual": 4.4815, "status": "unverified", "flag": "B4 per-annum x printed tenure"}),
    ("krystal_394", {"amount_inr_cr": 296.0252, "value_total": 740.063, "share_pct": 40.0,
                     "status": "verified", "flag": "B5 consortium share printed"}),
    ("spml_299", {"amount_inr_cr": 89.6064, "value_total": 344.64, "share_pct": 26.0,
                  "status": "unverified", "flag": "B5 consortium share %"}),
    ("shreepushk_231", {"flag": "B7 bundled capex + raise"}),
    ("asianene_63", {"order_kind": "new_order", "status": "verified", "flag": "B8 new order vs order book"}),
    ("blkashyap_910", {"amount_inr_cr": 910.0, "status": "verified", "flag": "B9 recall: GST is not a veto"}),
    ("jyoti_6796", {"amount_inr_cr": 67.96, "status": "verified", "flag": "B9 recall: loose (e) Value letter"}),
])
def test_stage_b_fixes(case: str, expected: dict[str, Any]) -> None:
    fixture = STAGE_B[case]
    doc = _doc(fixture["title"], fixture["text"], doc_key=fixture["doc_key"], symbol=STAGE_B_SYMBOL[case])
    rows, _missing = fe.event_rows(doc)
    if case == "shreepushk_231":
        capex = _row(rows, "capex_approval")
        raise_row = _row(rows, "fund_raise")
        assert capex["amount_inr_cr"] == 350.0 and capex["status"] == "unverified"
        assert raise_row["amount_inr_cr"] == 30.0 and raise_row["status"] == "unverified"
        return
    flag = expected.pop("flag")
    kind = "order_amendment" if "B3" in flag else "order_win"
    if case == "spml_299":
        kind = "order_win"
    row = _row(rows, kind)
    for field, value in expected.items():
        assert row[field] == value, (case, flag, field, row[field], value)


def test_stage_b_amendment_links_to_the_original_order() -> None:
    original = _doc("Premier Explosives Limited has received a purchase order for Rs. 6.62 crores",
                    "The Company has received a purchase order from an International entity for Rs. 6.62 crores.",
                    symbol="PREMEXPLN", doc_key="premex-155", filing_date="2025-06-19",
                    known_at="2025-06-19T10:00:00")
    amendment = _doc(STAGE_B["premex_163"]["title"], STAGE_B["premex_163"]["text"],
                     symbol="PREMEXPLN", doc_key=STAGE_B["premex_163"]["doc_key"], filing_date="2025-07-10",
                     known_at="2025-07-10T10:00:00")
    first = _row(fe.event_rows(original)[0], "order_win")
    second = _row(fe.event_rows(amendment)[0], "order_amendment")
    fe._link_amendments([first, second])
    assert second["amends"] == "premex-155"


def test_stage_b_same_order_filed_twice_is_one_event_and_the_later_amends() -> None:
    doc66 = _doc(STAGE_B["krystal_66"]["title"], STAGE_B["krystal_66"]["text"], symbol="KRYSTAL",
                 doc_key=STAGE_B["krystal_66"]["doc_key"], filing_date="2024-10-12",
                 known_at="2024-10-12T10:00:00")
    doc68 = _doc(STAGE_B["krystal_68"]["title"], STAGE_B["krystal_68"]["text"], symbol="KRYSTAL",
                 doc_key=STAGE_B["krystal_68"]["doc_key"], filing_date="2024-10-14",
                 known_at="2024-10-14T10:00:00")
    rows = fe.event_rows(doc66)[0] + fe.event_rows(doc68)[0]
    amends: list[dict[str, Any]] = []
    kept = fe._fold_same_order(rows, amends)
    assert len(kept) == 1 and kept[0]["doc_key"] == STAGE_B["krystal_66"]["doc_key"]
    assert kept[0]["value_annual"] == 55.0
    assert len(amends) == 1
    assert amends[0]["doc_key"] == STAGE_B["krystal_68"]["doc_key"]
    assert amends[0]["amends"] == STAGE_B["krystal_66"]["doc_key"]
    assert amends[0]["symbol"] == "KRYSTAL" and "earlier known_at kept" in amends[0]["why"]


@pytest.mark.parametrize("case", ["rane_349", "suryoday_10", "kopran_413", "salsteel_240"])
def test_stage_b_wrong_classes_are_not_events(case: str) -> None:
    fixture = STAGE_B[case]
    rows, _missing = fe.event_rows(_doc(fixture["title"], fixture["text"], doc_key=fixture["doc_key"]))
    assert rows == [], [row["kind"] for row in rows]


# ---- Stage C fixtures: the texts Wolf's read B cited -----------------------------------------------------
STAGE_C: dict[str, dict[str, Any]] = {
    "jyoti_136": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x136.pdf",
        "title": "Approval of fund raise by way of Equity Shares for an aggregate amount of up to Rs. 500 crores by way of rights issue",
        "text": "The Board of Directors of the Company, at their meeting held today, has inter alia considered and approved "
                "fund raise by way of equity shares for an amount upto Rs. 500 crores by way of a rights issue.",
    },
    "jyoti_137": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x137.pdf",
        "title": "Revised Outcome of Board meeting held on 22.11.2024",
        "text": "The Board of Directors of the Company, at their meeting held on November 22, 2024 has inter alia considered "
                "and approved fund raise by way of equity shares for an amount upto Rs. 500 crores by way of a rights issue.",
    },
    "jyoti_167": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x167.pdf",
        "title": "Outcome of the Rights Issue Committee Meeting held on February 04, 2025",
        "text": "The Rights Issue Committee of the Company, at its meeting held today, has approved the following key terms "
                "related to the Rights Issue: Type of Issuance Rights Issue, upto Rs. 500 crore. Ratio 9 (Nine) Equity Share "
                "for every 26 (Twenty-Six) Equity Share held. Post Right Issue: 1,21,30,81,396.",
    },
    "jyoti_192": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x192.pdf",
        "title": "Outcome of Rights Issue Committee for Finalizing Basis of Allotment",
        "text": "This is in continuation to the intimation of meeting of the Board of Directors held on November 22, 2024, "
                "where the raising of funds through the issue of equity shares was approved by way of a rights issue for an "
                "amount aggregating up to Rs. 49,908.79 lakhs. Basis of allotment finalised.",
    },
    "jyoti_22": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x22.pdf",
        "title": "Outcome of Rights Issue Committee Meeting pursuant to the basis of allotment approved by the designated stock exchange",
        "text": "This is in continuation to the Board meeting held on March 20, 2024 approving an aggregate amount not exceeding "
                "Rs. 175 crore by way of Rights Issue. Post Right Issue: 84,73,48,420 Equity Shares x at a price of Rs. 15/- per "
                "Equity Share.",
    },
    "green_239": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/GREENPOWER/material_filing/x239.pdf",
        "title": "Intimation under Regulation 30 of SEBI (LODR) Regulations, 2015",
        "text": "One of our subsidiaries M/s. Delta Renewable Energy Private Limited has signed and executed an EPC Contract "
                "today for development of 7.00 MW AC Solar Power Project in Tiruttani Taluk with Remon Solutions Private "
                "Limited (EPC Contractor). The estimated development cost is Rs. 40 crores.",
    },
    "advait_410": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ADVAIT/material_filing/x410.pdf",
        "title": "Results",
        "text": "The Company has informed the Board that its material subsidiary, Advait Greenergy Private Limited, is "
                "exploring the options for fund raising of approximately Rs 90 Crores from various investors, for its future "
                "capex purpose.",
    },
    "simplex_171": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SIMPLEXINF/material_filing/x171.pdf",
        "title": "Notice of Board Meeting",
        "text": "A meeting of the Board of Directors of the Company is scheduled to be held on 14th February 2025, inter-alia, "
                "to consider and approve raising of funds by way of QIP and increase in borrowing limits up to Rs. 12500 Crore.",
    },
    "jyoti_4": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/JYOTISTRUC/material_filing/x4.pdf",
        "title": "Intimation on Completion of Project order",
        "text": "Jyoti Structures Limited is pleased to update on having successfully executed all three transmission lines "
                "awarded by Mundra Port and Special Economic Zone Limited. The initial value of the contract was Rs 39.04 Cr.",
    },
    "bluspring_495": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/BLUSPRING/material_filing/x495.pdf",
        "title": "Intimation of Bagging/Receiving of Order/contracts",
        "text": "STEAG Energy Services (India) Private Limited has been awarded an order from Bharat Aluminium Company "
                "Limited (BALCO) for the 1740 MW Power Plant Operations and Maintenance Contract. Estimated aggregate "
                "contract value is Rs. 2,049.8 Crores for 60 months.",
    },
    "bluspring_509": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/BLUSPRING/material_filing/x509.pdf",
        "title": "Press Release titled A Bluspring subsidiary, STEAG India order book stands at Rs 5,100 Cr with new deals",
        "text": "This Press Release summarises the recent disclosures: 1. STEAG has won the STEAG-BALCO contract worth "
                "Rs. 2,050 Crores from Bharat Aluminium Company Limited, intimated June 5, 2026. 2. STEAG-Vedanta "
                "Aluminium contract worth Rs. 1,219 Crores June 26, 2026.",
    },
    "krystal_226": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x226.pdf",
        "title": "Intimation under Regulation 30 of SEBI (Listing Obligation and Disclosure Requirements) Regulations, 2015",
        "text": "The Company has received contract from Airports Authority of India, Patna for providing Facility Management "
                "Services at the new terminal building. Approximate contract value of Rs. 20,26,49,506/- including taxes, "
                "3 years.",
    },
    "krystal_255": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x255.pdf",
        "title": "Announcement under Regulation 30 (LODR)- Press Release",
        "text": "Krystal Integrated Services Wins Rs. 20.26 Crore Facility Management Contract for New Terminal at Patna "
                "Airport. Contract from the Airports Authority of India (AAI) for the new terminal building, valued at "
                "approximately Rs. 20.26 crore, three-year contract.",
    },
    "krystal_551": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x551.pdf",
        "title": "Intimation under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulation, 2015",
        "text": "The Company has received a work order from Shree Shyam Mandir Committee, Khatu Shyamji (Sikar, Rajasthan) "
                "for Sanitation and Waste Management Services, approximate contract value Rs. 6.60 Crore excluding taxes.",
    },
    "krystal_556": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x556.pdf",
        "title": "Intimation under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulation, 2015",
        "text": "The Company has received a Letter of Commencement from Maha Mumbai Metro (M3) Operation Corporation Limited "
                "for Housekeeping and cleaning at Monorail Stations, contract value Rs. 6,58,35,987 including GST.",
    },
    "abinfra_397": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ABINFRA/material_filing/x397.pdf",
        "title": "Allotment of Award",
        "text": "M/s. A B Infrabuild Limited has received letter of acceptance for a new project — Construction of Road Over "
                "Bridge in lieu of LC No- 334 at Km 633/5-7 under Khurda Road Division. Broad commercial consideration or "
                "size of the order(s)/contract(s) Rs. 48,58,36,248.44. 24 Months.",
    },
    "abinfra_439": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ABINFRA/material_filing/x439.pdf",
        "title": "Allotment of Order",
        "text": "M/s. A B Infrabuild Limited has received letter of acceptance for a new project — Construction of Road Over "
                "Bridge in lieu of LC No- 360 at Km 665/19-21 under Khurda Road Division. Broad commercial consideration or "
                "size of the order(s)/contract(s) Rs. 48,67,75,280.22. 24 Months.",
    },
    "green_511": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/GREENPOWER/material_filing/x511.pdf",
        "title": "Intimation under Regulation 30 of the SEBI [Listing Obligations and Disclosure Requirements] Regulations, 2015.",
        "text": "The Company has been allotted 2,19,59,094 Equity shares at face value of Rs. 10 each by Delta Renewable Energy "
                "Private Limited in the fifth tranche of its Preferential issue. The Company has successfully commissioned a "
                "7 MW AC solar power project at Krishnapuram and Veeraganallur Villages. The Company has entered into an EPC "
                "Contract to develop a 17.6 MW AC solar power project and the same is under progress.",
    },
    "micel_259": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/MICEL/material_filing/x259.pdf",
        "title": "Please find the attached Letter of Acceptance received from the Palakkad division.",
        "text": "The Company has received a Letter of Acceptance from the Palakkad Division S and T, Railway Divisional Office, "
                "Signal and Telecommunication Branch, Palakkad. The aggregate value of the said work order is "
                "Rs. 1,28,34,157.90. 6 Months from the date of issue of Letter of Acceptance.",
    },
    "micel_463": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/MICEL/material_filing/x463.pdf",
        "title": "Please find enclosed the receipt of the LOAs (letters of acceptance) intimation.",
        "text": "The Company has received a Letter of Acceptance from the Signal and Telecommunication (S&T) department of the "
                "Nagpur Division, Central Railway (CR) Zone of Indian Railways, for Supply, Installation, Testing & "
                "Commissioning Telecom assets/Passenger amenities IPIS at Wardha station, for an amount of Rs. 1,12,14,148.93. "
                "Further, the Company has received a LOA variation order from Salem Division, Southern Railway (SR) Zone of "
                "Indian Railways, for Provision of Passenger Information System, for an amount of Rs. 1,09,45,604.",
    },
    "krystal_396": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/KRYSTAL/material_filing/x396.pdf",
        "title": "Intimation of Postal Ballot Notice",
        "text": "The Company seeks approval of Members for: 1. Increase in Authorised Share Capital from Rs. 15,00,00,000 "
                "divided into 1,50,00,000 Equity Shares to Rs.19,00,00,000 divided into 1,90,00,000 Equity Shares. 2. "
                "Approval to raise capital by way of a Qualified Institutions Placement up to Rs. 300 Crores.",
    },
    "yashhv_504": {
        "doc_key": "D:/RealityEngine/raw/pilot60_history/YASHHV/material_filing/x504.pdf",
        "title": "Please Find Attached herewith Press Release.",
        "text": "The Board has approved the issuance of up to 12,62,131 equity shares and 8,32,177 convertible warrants, each "
                "warrant convertible into one equity share, at an issue price of Rs. 721 per security, aggregating up to "
                "approximately Rs. 151 crore.",
    },
}


def _stage_c_rows(case: str, symbol: str) -> list[dict[str, Any]]:
    fixture = STAGE_C[case]
    return fe.event_rows(_doc(fixture["title"], fixture["text"], symbol=symbol,
                              doc_key=fixture["doc_key"]))[0]


def test_stage_c_raise_stages_share_one_raise_id() -> None:
    rows: list[dict[str, Any]] = []
    for case in ("jyoti_136", "jyoti_137", "jyoti_167", "jyoti_192"):
        rows.extend(_stage_c_rows(case, "JYOTISTRUC"))
    fe._assign_raise_ids(rows)
    raises = [row for row in rows if row["kind"] == "fund_raise"]
    assert len({row["raise_id"] for row in raises}) == 1
    assert {row["raise_stage"] for row in raises} == {"approval", "allotment"}
    assert sum(int(row["raise_primary"] or 0) for row in raises) == 1
    primary = next(row for row in raises if row["raise_primary"])
    assert primary["raise_stage"] == "allotment"


def test_stage_c_separate_raise_keeps_its_own_value_and_id() -> None:
    rows = _stage_c_rows("jyoti_22", "JYOTISTRUC")
    fe._assign_raise_ids(rows)
    row = _row(rows, "fund_raise")
    assert row["amount_inr_cr"] == pytest.approx(175.0) and row["shares"] is None
    assert row["raise_stage"] == "allotment" and row["raise_primary"] == 1


@pytest.mark.parametrize("early,late,should_fold", [
    ("bluspring_495", "bluspring_509", True),
    ("krystal_226", "krystal_255", True),
    ("krystal_551", "krystal_556", False),
    ("abinfra_397", "abinfra_439", False),
])
def test_stage_c_press_release_recap_within_120_days(early: str, late: str, should_fold: bool) -> None:
    first = _doc(STAGE_C[early]["title"], STAGE_C[early]["text"], symbol=early.split("_")[0].upper(),
                 doc_key=STAGE_C[early]["doc_key"], filing_date="2025-01-01", known_at="2025-01-01T10:00:00")
    second = _doc(STAGE_C[late]["title"], STAGE_C[late]["text"], symbol=late.split("_")[0].upper(),
                  doc_key=STAGE_C[late]["doc_key"], filing_date="2025-02-01", known_at="2025-02-01T10:00:00")
    rows = fe.event_rows(first)[0] + fe.event_rows(second)[0]
    amends: list[dict[str, Any]] = []
    kept = fe._fold_same_order(rows, amends)
    assert (len(kept) == 1 and len(amends) == 1) is should_fold
    if should_fold:
        assert kept[0]["doc_key"] == STAGE_C[early]["doc_key"]
        assert amends[0]["amends"] == STAGE_C[early]["doc_key"]


@pytest.mark.parametrize("case,symbol,absent", [
    ("jyoti_4", "JYOTISTRUC", "order_win"),
    ("green_239", "GREENPOWER", "order_win"),
    ("advait_410", "ADVAIT", "capex_approval"),
    ("simplex_171", "SIMPLEXINF", "fund_raise"),
])
def test_stage_c_vetoes(case: str, symbol: str, absent: str) -> None:
    rows = _stage_c_rows(case, symbol)
    assert not [row for row in rows if row["kind"] == absent], [row["kind"] for row in rows]


def test_stage_c_ballot_is_not_an_allotment() -> None:
    rows = _stage_c_rows("krystal_396", "KRYSTAL")
    assert [row["kind"] for row in rows] == ["fund_raise"]
    # T-242 round 5: a postal-ballot notice asks for the approval, so the raise is proposed, never an allotment
    assert rows[0]["raise_stage"] == "proposed"


def test_stage_c_restated_background_is_dropped_but_first_disclosure_is_kept() -> None:
    earlier = _doc("7 MW Solar Power Project commissioned under the MSKVY 2.0",
                   "The Company has successfully commissioned a 7 MW solar power project at Krishnapuram.",
                   symbol="GREENPOWER", doc_key="earlier-7mw", filing_date="2025-12-08",
                   known_at="2025-12-08T10:00:00")
    later_fixture = STAGE_C["green_511"]
    later = _doc(later_fixture["title"], later_fixture["text"], symbol="GREENPOWER",
                 doc_key=later_fixture["doc_key"], filing_date="2026-07-06", known_at="2026-07-06T10:00:00")
    earlier_rows = fe.event_rows(earlier)[0]
    later_rows = fe.event_rows(later)[0]
    capacity = [row for row in later_rows if row["kind"] == "capacity_commissioned"]
    assert capacity, "the later filing still narrates a capacity event"
    kept = fe._drop_restated_capacity(earlier_rows + capacity)
    assert [row["doc_key"] for row in kept if row["kind"] == "capacity_commissioned"] == ["earlier-7mw"]
    first = fe._drop_restated_capacity(capacity)
    assert first and first[0]["doc_key"] == later_fixture["doc_key"]


def test_stage_c_field_hygiene() -> None:
    customer = _row(_stage_c_rows("micel_259", "MICEL"), "order_win")
    assert customer["customer"] is None
    assert customer["value_text"] and "1,28,34,157.90" in customer["value_text"]

    shares_ratio = _row(_stage_c_rows("jyoti_167", "JYOTISTRUC"), "fund_raise")
    assert shares_ratio["shares"] is None
    authorised = _row(_stage_c_rows("krystal_396", "KRYSTAL"), "fund_raise")
    assert authorised["shares"] is None
    mixed = _row(_stage_c_rows("yashhv_504", "YASHHV"), "fund_raise")
    assert mixed["shares"] == 2_094_308 and mixed["instrument"] == "equity+warrant"

    micro = _stage_c_rows("micel_463", "MICEL")
    order = _row(micro, "order_win")
    variation = _row(micro, "order_amendment")
    assert order["amount_inr_cr"] == pytest.approx(1.1214) and "Nagpur" in (order["customer"] or "")
    assert variation["amount_inr_cr"] == pytest.approx(1.0946) and "Salem" in (variation["quote"] or "")


# ---- the DB writer: one row per filing, feed duplicates dropped -------------------------------------------
def test_build_writes_one_row_per_filing_and_keeps_doc_known_at(monkeypatch: pytest.MonkeyPatch) -> None:
    order = "The Company has secured an order worth Rs. 100 Crores."
    docs = [
        _doc("The Company has secured an order worth Rs. 100 Crores", order, doc_key="a",
             filing_date="2026-01-05", known_at="2026-01-05T10:00:00"),
        _doc("The Company has secured an order worth Rs. 100 Crores", order, doc_key="b",
             filing_date="2026-01-05", known_at="2026-01-05T18:00:00"),
        _doc("Board Meeting Intimation", "The Board will meet to consider fund raising.", doc_key="c"),
    ]
    monkeypatch.setattr(fe, "load_docs", lambda store: docs)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "_pytest_events.db"
    meta = fe.build(stores=["cXX"], use_model=False, out=out, cache=None)
    assert meta["classified_filings"] == 2 and meta["quarantined"] == 0
    con = sqlite3.connect(out)
    try:
        rows = con.execute("SELECT symbol, kind, amount_inr_cr, known_at, status, method FROM event").fetchall()
        assert rows == [("ACME", "order_win", 100.0, "2026-01-05T10:00:00", "verified", "script")]
        amend = con.execute("SELECT doc_key, amends FROM amend").fetchall()
        assert amend == [("b", "a")]        # the same order filed twice: the later doc amends the earlier
    finally:
        con.close()
        out.unlink(missing_ok=True)


def test_t242_load_docs_reads_press_releases_too(monkeypatch):
    """T-242: a press release that announces an order is read like an announcement; other doc types are not."""
    import sqlite3

    work = Path(".tmp/t242_load_docs")
    work.mkdir(parents=True, exist_ok=True)
    db = work / "c01" / "c01.db"
    db.parent.mkdir(exist_ok=True)
    con = sqlite3.connect(db)
    con.execute("DROP TABLE IF EXISTS doc")
    con.execute("DROP TABLE IF EXISTS doc_page")
    con.execute("CREATE TABLE doc (doc_key TEXT, symbol TEXT, isin TEXT, title TEXT, filing_date TEXT, "
                "known_at TEXT, pages INTEGER, doc_type TEXT)")
    con.execute("CREATE TABLE doc_page (doc_key TEXT, page INTEGER, text TEXT)")
    for key, kind in (("a", "announcement"), ("p", "press_release"), ("t", "transcript")):
        con.execute("INSERT INTO doc VALUES (?,?,?,?,?,?,?,?)", (key, "X", "INE0", key, "2026-08-01",
                                                                 "2026-08-01", 1, kind))
        con.execute("INSERT INTO doc_page VALUES (?,?,?)", (key, 1, f"page of {kind}"))
    con.commit()
    con.close()
    monkeypatch.setattr(fe, "store_path", lambda store: db)
    import reality_engine.research.driver_claims as dc
    monkeypatch.setattr(dc, "ocr_page_texts", lambda store, kinds: {})
    assert sorted(d["doc_key"] for d in fe.load_docs("c01")) == ["a", "p"]


# ---- T-242 fixes 1-6: real sentences from the 60 graded filings -------------------------------------------
T242_CASES: dict[str, dict[str, Any]] = {
    "E21": {
        "symbol": "RAILTEL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/RAILTEL/material_filing/52699e33-430b-498c-8308-32e4d286436c.pdf",
        "title": "New Order Received",
        "text": ("RailTel Corporation of India Ltd. has received the work order from Ircon International Limited "
                 "for Works amounting to Rs. 1,62,58,96,785 (Including Tax). Annexure-A a) Name of the entity "
                 "awarding the order(s)/contract(s); Ircon International Limited b) Significant terms and conditions "
                 "order(s)/contract (s) awarded in brief; Integrated Tunnel Communication g) Broad consideration or "
                 "size of order(s)/contract(s) (in INR); 1,62,58,96,785"),
    },
    "E27": {
        "symbol": "RAILTEL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/RAILTEL/material_filing/ff36168d-6ac5-44f2-b4df-cd4fe3e4877f.pdf",
        "title": "New order received",
        "text": ("RailTel Corporation of India Ltd. has received the work order from Madhya Pradesh State Electronics "
                 "Development Corporation Ltd for Work Order amounting to Rs. 37,18,16,668 (Including Tax). "
                 "Annexure-A a) Name of the entity awarding the order(s)/contract(s); Madhya Pradesh State Electronics "
                 "Development Corporation Ltd b) Significant terms and conditions order(s)/contract (s) awarded in "
                 "brief; Work Order as System Integrator g) Broad consideration or size of order(s)/contract(s) (in INR); "
                 "37,18,16,668"),
    },
    "E30": {
        "symbol": "RAILTEL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/RAILTEL/material_filing/268f3a27-70bc-40db-b5ac-74a634d99120.pdf",
        "title": "New order received",
        "text": ("RailTel Corporation of India Ltd. has received the Letter of Acceptance (LoA) from Assam Health "
                 "Infrastructure Development & Management Society (Ahidms). Annexure-A a) Name of the entity awarding "
                 "the order(s)/contract(s); Assam Health Infrastructure Development & Management Society (Ahidms) "
                 "b) Significant terms and conditions order(s)/contract (s) awarded in brief; HMIS "
                 "g) Broad consideration or size of order(s)/contract(s) (in INR); The Estimated Size of Order as per "
                 "LoA is Rs. 56,71,47,619/-"),
    },
    "E60": {
        "symbol": "EIMCOELECO",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/EIMCOELECO/material_filing/0ba649f9-18ea-4acc-8793-b05a46805b21.pdf",
        "title": "As per attached letter",
        "text": ("Subject: Bagging / Receiving of orders/ contracts. In compliance with Regulation 30, we are pleased to "
                 "inform that the Company has received an order of INR 33.11 Crores (excluding GST). "
                 "a) Name of the entity awarding the The Singareni Collieries Company order(s) / contact(s) Limited "
                 "b) Significant terms and conditions of order(s)/ contract(s) awarded in brief Supply of Coal Mining "
                 "Equipment g) Broad consideration or size of the order(s)/ contract(s); INR 33.11 Crores (Excluding GST)"),
    },
    "E44": {
        "symbol": "INDOSMC",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/INDOSMC/material_filing/a844c202-935d-47cc-ab23-f3ed373c1fac.pdf",
        "title": "Intimation of Receipt of Purchase orders",
        "text": ("Sub: Intimation Of receipts of Two Purchase Orders aggregate orders worth Rs. 3525.50 Lacs "
                 "bifurcated into (1) Supply worth Rs.2423.50 Lacs vide PO No. Asiatic/0006, 22 Apr, 2026 ; & "
                 "(2) Supply worth Rs.1102.00 Lacs vide PO No. RVFI/0722/KPC/72 dated 22 Apr, 2026. "
                 "Further, this Purchase order received from our Valued Customer signifies our strong execution "
                 "capabilities. 1. Name of the entity awarding the order (s)/Contract(s); A renowned Gujarat based "
                 "Composite manufacturing Company. 2. Significant terms: Rs. 2423.50 Lacs. 7. Broad Consideration "
                 "The order size worth Rs. 2423.50 Lacs. "
                 "1. Name of the entity awarding the order (s)/Contract(s); One of the reputed wholesale trader unit "
                 "based at Ahmedabad. 2. Significant terms: Rs. 1102 Lacs. 7. Broad Consideration The order size "
                 "worth Rs. 1102 Lacs"),
    },
    "E41": {
        "symbol": "SEPC",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SEPC/material_filing/c763e387-0de5-47ab-a5a3-d76d1a858f75.pdf",
        "title": "We hereby inform the exchange that the Company has received a Letter of Acceptance from Steel Authority of India Limited (SAIL).",
        "text": ("Subject: Letter of Acceptance for 4.08Mtpa CS Expansion of SAIL-ISP Burnpur for a total value of "
                 "order is ₹673.32 Crores. 1. Coke Oven BOP for Rs.296,77,12,664/- vide LOA dated 11/06/2026; and "
                 "2. Sinter Plant BOP for Rs.376,55,75,841/- vide LOA dated 11/06/2026. "
                 "Annexure-1: 1. Name of the entity awarding the order(s)/contract(s); Steel Authority of India Limited "
                 "- IISCO Steel Plant (ISP), Burnpur 2. Significant terms Coke Oven BOP 7. Broad consideration Total "
                 "value of Rs.296,77,12,664/-. "
                 "Annexure-1: 1. Name of the entity awarding the order(s)/contract(s); Steel Authority of India Limited "
                 "- IISCO Steel Plant (ISP), Burnpur 2. Significant terms Sinter Plant BOP 7. Broad consideration Total "
                 "value of Rs.376,55,75,841 /-"),
    },
    "E43": {
        "symbol": "SEPC",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SEPC/material_filing/41269cc3-fc0a-41dc-8e77-503b41cae26a.pdf",
        "title": "Update on earlier intimation made under Regulation 30 of SEBI (LODR) Regulations, 2015.",
        "text": ("Subject: Intimation under Regulation 30 – Cancellation of Work Order by MOIL Limited. "
                 "We wish to inform you that the Work Order earlier disclosed to the Stock Exchanges on December 29, "
                 "2025, received from MOIL Limited (Government Undertaking) for designing, construction, furnishing and "
                 "equipping, having a total order value of ₹230 Crores including taxes, has been cancelled by MOIL."),
    },
    "E38": {
        "symbol": "EIMCOELECO",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/EIMCOELECO/material_filing/a2ef184b-8088-4b95-96df-2632d478b85a.pdf",
        "title": "Update on Awarded/Bagged Orders/Contracts",
        "text": ("We would like to inform you that the Company had received orders worth of INR 53.61 Crores "
                 "(excluding GST) from JMS Mining Private Limited for Manufacturing and Supply of Coal Mining Equipment. "
                 "In this connection, this to inform you that JMS Mining Private Limited has decided to reduce the "
                 "awarded orders by INR 23.18 Crore (excluding GST) by reducing the deliveries pertaining to FY2025-26."),
    },
    "E58": {
        "symbol": "EIMCOELECO",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/EIMCOELECO/material_filing/50f7e494-d726-4921-8cba-b1baeb2b4384.pdf",
        "title": "As per attached letter",
        "text": ("Subject: Update on Awarded / bagged orders/ contracts. This is further to our intimation letter dated "
                 "31st July, 2024, this to inform you that JMS Mining Private Limited has further decided to reduce "
                 "the awarded orders by INR 9.39 Crore (excluding GST) by reducing the deliveries pertaining to FY2025-26."),
    },
    "E53": {
        "symbol": "SAGILITY",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SAGILITY/material_filing/a4a025d4-ccfe-466a-8ffc-e330dd2e9f41.pdf",
        "title": "Receipt of order from Department of Commercial Taxes, Karnataka, under section 73(9) of Karnataka Goods and Services Tax Act 2017 and Central Goods and Services Tax Act, 2017",
        "text": ("We wish to inform you that the Company is in receipt of the order in Form GST DRC-07 dated June 3, "
                 "2026 from Department of Commercial Taxes, Karnataka under Section 73(9) of Karnataka Goods and "
                 "Services Tax Act, 2017 and Central Goods and Services Tax Act, 2017 with a total demand of "
                 "Rs. 90,44,596 (including interest and penalty)."),
    },
    "E09": {
        "symbol": "ABREL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ABREL/material_filing/cc05460d-7edc-481a-8019-660883aaf1bc.pdf",
        "title": "Disclosure regarding amendment in clauses of Debenture Trust Deed dated 1st March, 2024",
        "text": ("This is to inform you that the Company has received the in-principle approval from the BSE Limited "
                 "for amendment in the clauses of Debenture Trust Deed in respect of 25,000 8.05% Unsecured, Listed, "
                 "Rated, Senior, Redeemable, Non-Convertible Debentures aggregating to Rs. 250 crores issued under "
                 "Private Placement basis."),
    },
    "E13": {
        "symbol": "ABREL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ABREL/material_filing/a7ebdaca-542f-4955-b5f5-520f3b7a04c8.pdf",
        "title": "Disclosure regarding modification in one of the Financial Covenants of Debenture Trust Deeds",
        "text": ("Sub: Disclosure regarding modification in one of the financial covenants of Debenture Trust Deeds "
                 "in respect of 8.55% Unsecured, Listed, Redeemable, Non-Convertible Debentures of Rs. 400 crores and "
                 "Rs. 100 crores aggregating to Rs. 500 Crores issued by Aditya Birla Real Estate Limited."),
    },
    "E14": {
        "symbol": "SAGILITY",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SAGILITY/material_filing/2c961fb8-db80-465a-b466-f5c23cee6d7c.pdf",
        "title": "Partial Redemption of Unsecured, Unlisted Redeemable Non-Convertible Debentures",
        "text": ("We hereby inform that 1,495 unsecured, unlisted, redeemable Non-Convertible Debentures (NCDs) of face "
                 "value ₹10,00,000 each, aggregating to ₹1,49,50,00,000 have been redeemed and paid to Sagility B.V. "
                 "Further, the applicable interest of ₹2,88,09,576 has also been paid."),
    },
    "E15": {
        "symbol": "ABREL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ABREL/material_filing/b058ea26-5110-485f-9efa-88fd751a43d8.pdf",
        "title": "Intimation of exercise of Call Option, Record Date and Notice of exercise of Call Option for early redemption",
        "text": ("This is to inform you that the Company has decided to exercise Call Option for early redemption in "
                 "respect of 25,000 8.05% Unsecured, Listed, Rated, Senior, Redeemable, Non-Convertible Debentures of "
                 "face value of Rs. 1,00,000/- each aggregating to Rs. 250 crores issued under Private Placement basis."),
    },
    "E18": {
        "symbol": "SAGILITY",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SAGILITY/material_filing/1e1d2b29-53cb-48c4-a6ba-c395083c3dd3.pdf",
        "title": "Partial Redemption of Unsecured, Unlisted Redeemable Non-Convertible Debentures",
        "text": ("We hereby inform that 1,105 unsecured, unlisted, redeemable Non-Convertible Debentures (NCDs) of face "
                 "value ₹10,00,000 each, aggregating to ₹110,50,00,000 have been redeemed and paid to Sagility B.V. "
                 "Further, the applicable interest of ₹2,12,94,034 has also been paid."),
    },
    "E04": {
        "symbol": "GULFOILLUB",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/GULFOILLUB/results_press_release/99a28d2b-dd27-485e-b6e8-8745de566da1.pdf",
        "title": "We enclose herewith a copy of the Press Release in respect of the Unaudited Financial Results of the Company for the quarter ended June 30, 2025.",
        "text": ("Press Release Q1 FY26 Key Financial highlights for Q1 · Revenues at Rs. 996.36 Crores, up 12.57% YoY "
                 "· EBITDA at Rs. 126.58 Crores, up 8.89% YoY · PAT at Rs. 96.66 Crores, up 9.81% YoY "
                 "Board approves Rs. 55 Crores Capex plan to enhance Manufacturing Capacity by 70% to 240 million litres."),
    },
    "E45": {
        "symbol": "ZENTEC",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/ZENTEC/material_filing/3db948a1-271e-4b5a-963f-9331beb15843.pdf",
        "title": "Press Release",
        "text": ("Please find attached press release on the Un-audited Financial Results of the Company for the quarter "
                 "and nine months ended December 31, 2025. Q3 & 9MFY26 PRESS & MEDIA RELEASE: Zen Technologies "
                 "announced its financial results for Q3 & 9MFY26. During Q3 FY26, we secured new orders aggregating "
                 "₹586 crore. Subsequent to 31 December 2025, we received additional orders aggregating ₹345 crore."),
    },
    "E01": {
        "symbol": "BEPL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/BEPL/material_filing/a90f9d5b-139a-4725-8eef-87efb68c5d67.pdf",
        "title": "Board at its meeting held today declared 1st Interim Dividend 2025-26",
        "text": ("Sub: Outcome of Board Meeting - 13th August, 2025. 1. Approved the Un-audited Financial Results "
                 "(Standalone and Consolidated) for the quarter year ended 30th June, 2025. "
                 "5. Considered and approved the project for enhancement of production capacity of ABS from 75000 TPA "
                 "to 100000 TPA at Company's existing plants at Abu Road (Rajasthan) and Satnoor (Madhya Pradesh) at "
                 "an estimated cost of Rs.200 crores, to be completed by September, 2026."),
    },
    "E22": {
        "symbol": "RAILTEL",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/RAILTEL/material_filing/1e0ba17d-f871-456c-91bd-69cb97ed20ad.pdf",
        "title": "New order received",
        "text": ("RailTel Corporation of India Ltd. has received the work order from Northern Railway for Service "
                 "amounting to Rs. 10,00,00,000 (Including Tax). Annexure-A a) Name of the entity awarding the "
                 "order(s)/contract(s); Northern Railway b) Significant terms and conditions order(s)/contract (s) "
                 "awarded in brief; Cloud Service for Railway Board g) Broad consideration or size of order(s)/contract(s) "
                 "(in INR); 10,00,00,000"),
    },
    "E33": {
        "symbol": "SEPC",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SEPC/material_filing/c9f91f14-1fb9-43f4-8214-8c8fc9437d35.pdf",
        "title": "We hereby inform the exchange of the five work orders from M/s. Bajaj Energy Private Limited for a total value of Rs. 180000000/-",
        "text": ("This is to inform you that we have been awarded Five (05) Orders from M/s. Bajaj Energy Private "
                 "Limited for Operation & Maintenance Services for total order value of Rs.180000000/- (Rupees One "
                 "Hundred and Eighty Millions only). Annexure-1 a Name of the entity awarding the order(s)/contract(s); "
                 "M/s. Bajaj Energy Private Limited. g Broad consideration or size of the order / contract Total Value "
                 "in Rs.180000000/-"),
    },
    "E42": {
        "symbol": "SEPC",
        "doc_key": "D:/RealityEngine/raw/pilot60_history/SEPC/material_filing/67aa4c0d-fa7f-4493-b7f5-1f06b664ed40.pdf",
        "title": "Intimation under Reg.30 SEBI (LODR) Regulations, 2015 - Receipt of LOA from SAIL - ISP Burnpur for Total Value of Rs.854.57 Crores (Net of ITC)",
        "text": ("We wish to inform you that the Company has received a Letter of Acceptance (LoA) from Steel Authority "
                 "of India Limited (SAIL) – IISCO Steel Plant (ISP), Burnpur. Annexure-1 1. Name of the entity awarding "
                 "the order(s)/contract(s); Steel Authority of India Limited - IISCO Steel Plant (ISP), Burnpur "
                 "7. Broad consideration or size of the order / contract Total value of Rs.854,56,71,234/- (Net of "
                 "Input Tax Credit)"),
    },
}


def test_t242_fix1_customer_cleanup_and_annexure_preference() -> None:
    for cid, expected in (
        ("E21", "Ircon International Limited"),
        ("E27", "Madhya Pradesh State Electronics Development Corporation Ltd"),
        ("E30", "Assam Health Infrastructure Development & Management Society (Ahidms)"),
        ("E60", "Singareni Collieries Company Limited"),
    ):
        fx = T242_CASES[cid]
        row = _row(fe.event_rows(_doc(fx["title"], fx["text"], symbol=fx["symbol"], doc_key=fx["doc_key"]))[0],
                   "order_win")
        assert row["customer"] == expected, (cid, row["customer"])


def test_t242_fix2_cancellations_reductions_and_gst_demands() -> None:
    for cid, expected_amt in (("E43", -230.0), ("E38", -23.18), ("E58", -9.39)):
        fx = T242_CASES[cid]
        rows, _missing = fe.event_rows(_doc(fx["title"], fx["text"], symbol=fx["symbol"], doc_key=fx["doc_key"]))
        row = _row(rows, "order_amendment")
        assert row["amount_inr_cr"] == pytest.approx(expected_amt)
        assert row["status"] == "unverified"
    gst = T242_CASES["E53"]
    assert fe.event_rows(_doc(gst["title"], gst["text"], symbol=gst["symbol"], doc_key=gst["doc_key"]))[0] == []


@pytest.mark.parametrize("cid", ["E09", "E13", "E14", "E15", "E18"])
def test_t242_fix3_debt_servicing_is_not_fund_raise(cid: str) -> None:
    fx = T242_CASES[cid]
    rows, _missing = fe.event_rows(_doc(fx["title"], fx["text"], symbol=fx["symbol"], doc_key=fx["doc_key"]))
    assert not [r for r in rows if r["kind"] == "fund_raise"], rows


def test_t242_fix4_results_releases_and_rollups_dropped_while_e01_kept() -> None:
    e04 = T242_CASES["E04"]
    rows_04, _ = fe.event_rows(_doc(e04["title"], e04["text"], symbol=e04["symbol"], doc_key=e04["doc_key"]))
    assert not [r for r in rows_04 if r["kind"] == "capex_approval"], rows_04

    e45 = T242_CASES["E45"]
    rows_45, _ = fe.event_rows(_doc(e45["title"], e45["text"], symbol=e45["symbol"], doc_key=e45["doc_key"]))
    assert not [r for r in rows_45 if r["kind"] == "order_win"], rows_45

    e01 = T242_CASES["E01"]
    capex = _row(fe.event_rows(_doc(e01["title"], e01["text"], symbol=e01["symbol"], doc_key=e01["doc_key"]))[0],
                 "capex_approval")
    assert capex["amount_inr_cr"] == pytest.approx(200.0) and capex["status"] == "unverified"


def test_t242_fix5_multi_item_orders_emit_all_items_and_total() -> None:
    e41 = T242_CASES["E41"]
    rows_41, _ = fe.event_rows(_doc(e41["title"], e41["text"], symbol=e41["symbol"], doc_key=e41["doc_key"]))
    orders_41 = sorted((r for r in rows_41 if r["kind"] == "order_win"), key=lambda r: r["seq"])
    assert len(orders_41) == 2
    assert orders_41[0]["amount_inr_cr"] == pytest.approx(296.7713, rel=1e-4)
    assert orders_41[1]["amount_inr_cr"] == pytest.approx(376.5576, rel=1e-4)
    assert all(r["value_total"] == pytest.approx(673.32) for r in orders_41)

    e44 = T242_CASES["E44"]
    rows_44, _ = fe.event_rows(_doc(e44["title"], e44["text"], symbol=e44["symbol"], doc_key=e44["doc_key"]))
    orders_44 = sorted((r for r in rows_44 if r["kind"] == "order_win"), key=lambda r: r["seq"])
    assert len(orders_44) == 2
    assert [r["amount_inr_cr"] for r in orders_44] == pytest.approx([24.235, 11.02])
    assert all(r["customer"] is None for r in orders_44)
    assert all(r["value_total"] == pytest.approx(35.255) for r in orders_44)


def test_t242_fix6_duplicate_raise_steps_stage_and_verify_once() -> None:
    e11 = _doc(
        "PFA the outcome of the RIC Meeting held today.",
        "This is further to our intimation dated November 14, 2024 made in relation to the issuance of equity "
        "shares on Rights Basis for an amount not exceeding Rs. 35,000 Lakhs so approved by the Board of Directors. "
        "Draft Letter of Offer: listing the Rights Equity Shares to be allotted pursuant to this Issue.",
        symbol="SEPC", doc_key="sepc-e11", filing_date="2024-12-23", known_at="2024-12-23T21:41:35",
    )
    e06 = _doc(
        "We hereby inform the Exchange of the Outcome of the RIC Meeting held today.",
        "This is further to our intimation dated December 23, 2024 regarding the Draft Letter of Offer filed in "
        "relation to the proposed Rights issue of equity shares for an amount not exceeding Rs. 35,000 Lakhs. "
        "the Rights Issue Committee has approved the addendum to the DLOF.",
        symbol="SEPC", doc_key="sepc-e06", filing_date="2025-04-16", known_at="2025-04-16T18:52:38",
    )
    e20 = _doc(
        "Extra-Ordinary General Meeting to be held on Thursday, July 30, 2026 at 11.00 A.M.",
        "Intimation of Notice of the Extra-Ordinary General Meeting of APAR Industries Limited for seeking approval "
        "from the members for: 1. To approve raising of funds through issuance of securities of the Company "
        "aggregating up to ₹ 2,500.00 crores through a qualified institutions placement, rights issue, preferential "
        "allotment, or a combination thereof.",
        symbol="APARINDS", doc_key="apar-e20", filing_date="2026-07-06", known_at="2026-07-06T19:07:33",
    )
    e07 = _doc(
        "Summary of Proceedings of the Extra-Ordinary General Meeting (EGM) of APAR Industries Limited held on Thursday, July 30, 2026",
        "The following Agenda item of business as set out in the Notice of EGM was recommended for members' "
        "consideration and approval: 1. To approve raising of funds through issuance of securities of the Company "
        "upto Rs. 2,500 Crores.",
        symbol="APARINDS", doc_key="apar-e07", filing_date="2026-07-30", known_at="2026-07-30T17:22:39",
    )
    rows = fe.event_rows(e11)[0] + fe.event_rows(e06)[0] + fe.event_rows(e20)[0] + fe.event_rows(e07)[0]
    fe._assign_raise_ids(rows)
    by_key = {r["doc_key"]: r for r in rows}
    assert by_key["sepc-e11"]["raise_stage"] == "proposed" and by_key["sepc-e11"]["status"] == "unverified"
    assert by_key["sepc-e06"]["raise_stage"] == "proposed" and by_key["sepc-e06"]["status"] == "unverified"
    assert by_key["sepc-e11"]["raise_id"] == by_key["sepc-e06"]["raise_id"]
    assert by_key["apar-e20"]["raise_stage"] == "proposed"
    assert by_key["apar-e07"]["raise_stage"] == "approval" and by_key["apar-e07"]["status"] == "unverified"
    assert by_key["apar-e20"]["raise_id"] == by_key["apar-e07"]["raise_id"]


@pytest.mark.parametrize("cid,expected_amt,expected_customer", [
    ("E22", 10.0, "Northern Railway"),
    ("E33", 18.0, "Bajaj Energy Private Limited"),
    ("E42", 854.5671, "Steel Authority of India Limited - IISCO Steel Plant (ISP), Burnpur"),
])
def test_t242_counter_genuine_orders_still_pass(cid: str, expected_amt: float, expected_customer: str) -> None:
    fx = T242_CASES[cid]
    row = _row(fe.event_rows(_doc(fx["title"], fx["text"], symbol=fx["symbol"], doc_key=fx["doc_key"]))[0],
               "order_win")
    assert row["amount_inr_cr"] == pytest.approx(expected_amt, rel=1e-4)
    assert row["customer"] == expected_customer
    assert row["status"] == "verified"


# ---- T-242 round 2 fixes (new20 + pilot counter-tests) ----------------------------------------------------
def test_t242_r2_fix1_capacity_rejections_and_new_rules() -> None:
    # e113: acquisition of 49% of LBPL (plant commissioned Dec 2021) -> rejected
    e113 = _doc(
        "This is in continuation of our letter dated 05.02.2026. Please find enclosed disclosure under Regulation 30",
        "Acquisition of equity shares in Leafiniti Bioenergy Private Limited. 1 Name of the Target Company: "
        "LBPL owns and operates CBG Plant with the capacity of 10.2 TPD. 10 Brief background: In December 2021, "
        "LBPL commissioned its first press mud based CBG plant with a capacity to produce 10.2 TPD of CBG.",
        symbol="GAIL", filing_date="2026-03-18",
    )
    assert not [r for r in fe.event_rows(e113)[0] if r["kind"] == "capacity_commissioned"]

    # e84: results press release with 600 MW Khavda foundation stone + Q2 52.83 MW bullet -> rejected
    e84 = _doc(
        "Please refer the attachment.",
        "Sub: Press Release. Press Release NLCIL REGISTERS HIGHEST EVER REVENUE FROM OPERATIONS. "
        "Major Highlights during the Q2 2025-26 "
        "• Hon'ble Prime Minister of India laid the foundation stone for NLCIL's 600 MW solar project at Khavda. "
        "• The first phase (52.83 MW) of the 300 MW Solar Power Project at Barsingsar, Rajasthan was successfully commissioned.",
        symbol="NLCINDIA", filing_date="2025-10-29",
    )
    assert not [r for r in fe.event_rows(e84)[0] if r["kind"] == "capacity_commissioned"]

    # e44: MoU press release restating Apr 2024 10 MW unit -> rejected
    e44 = _doc(
        "Please find enclosed a copy of Press Release on 'GAIL and Cummins sign MoU for collaboration on clean energy at IEW 2025'.",
        "GAIL and Accelera by Cummins have signed a Memorandum of Understanding (MoU) to collaborate in green energy. "
        "GAIL which always has been promoting clean energy, commissioned a 10 MW Green Hydrogen unit at its plant at "
        "Vijaipur, Guna Distt. M.P in April 2024.",
        symbol="GAIL", filing_date="2025-02-14",
    )
    assert not [r for r in fe.event_rows(e44)[0] if r["kind"] == "capacity_commissioned"]

    # e77: 52.83 MW commissioned phase 1, not 300 MW project name
    e77 = _doc(
        "Please refer the attachment.",
        "Sub: Disclosure under Regulation 30 – Commencement of Commercial Operation of Solar Power Project. "
        "In terms of Regulation 30, we write to inform that the first phase of the “300 MW Solar Power Project” of the "
        "Company, with a capacity of 52.83 MW has been successfully commissioned and declared commercially operational "
        "at Barsingsar, Distt. Bikaner, Rajasthan.",
        symbol="NLCINDIA", filing_date="2025-08-26",
    )
    r77 = _row(fe.event_rows(e77)[0], "capacity_commissioned")
    assert r77["capacity_value"] == pytest.approx(52.83)
    assert r77["capacity_unit"] == "mw"
    assert r77["plant"] == "Barsingsar"

    # e29: 660 MW Ghatampur COD; plant never 'India'
    e29 = _doc(
        "Press release dated 12.12.2024",
        "Sub: Intimation under SEBI (LODR) Regulations, 2015 – Press Release. "
        "We hereby furnish herewith a copy of the Press Release dated 12.12.2024. PRESS RELEASE "
        "NLC INDIA LIMITED'S FIRST SUPERCRITICAL POWER PLANT BEGINS COMMERCIAL OPERATION "
        "NLC India Limited (NLCIL) proudly announces the commencement of commercial operations of the first unit of "
        "its 3 x 660 MW Ghatampur Thermal Power Plant (GTPP) in Uttar Pradesh. Notably, this 660 MW capacity addition "
        "marks the first fossil fuel-based Thermal Power Plant commissioned in India in this financial year.",
        symbol="NLCINDIA", filing_date="2024-12-12",
    )
    r29 = _row(fe.event_rows(e29)[0], "capacity_commissioned")
    assert r29["capacity_value"] == pytest.approx(660.0)
    assert r29["plant"] != "India"


def test_t242_r2_fix1_missed_commissioning_filings_and_r_counter_tests() -> None:
    chhara = _doc(
        "We wish to inform about the successful commissioning of LNG Regasification terminal of 5 MMTPA capacity at Chhara, Gujarat.",
        "Sub.: Commissioning of LNG Regasification Terminal set up by wholly owned subsidiary HPCL LNG Limited. "
        "Dear Sir / Madam, we wish to inform about the successful commissioning of LNG Regasification Terminal of "
        "5 MMTPA capacity at Chhara, Gujarat set up by M/s HPCL LNG Ltd. The Terminal has been set up at an approx. "
        "investment of Rs. 4750 Crores.",
        symbol="HINDPETRO", filing_date="2025-01-13",
    )
    r_chhara = _row(fe.event_rows(chhara)[0], "capacity_commissioned")
    assert r_chhara["capacity_value"] == pytest.approx(5.0)
    assert r_chhara["capacity_unit"] == "mmtpa"
    assert r_chhara["plant"] == "Chhara"
    assert r_chhara["status"] == "unverified"

    visakh = _doc(
        "Commissioning of Residue Upgradation Facility with World's first LC-Max Unit at HPCL Visakh Refinery",
        "Sub: Commissioning of Residue Upgradation Facility with World's first LC-Max Unit at HPCL Visakh Refinery. "
        "Dear Sir(s), Pursuant to Regulation 30, we wish to inform that HPCL has successfully commissioned the Residue "
        "Upgradation Facility (RUF) at its 15 MMTPA Visakh Refinery. With a capacity of 3.55 MMTPA, RUF employs "
        "advanced LC-Max based residue hydrocracking technology.",
        symbol="HINDPETRO", filing_date="2026-01-03",
    )
    r_visakh = _row(fe.event_rows(visakh)[0], "capacity_commissioned")
    assert r_visakh["capacity_value"] == pytest.approx(3.55)
    assert r_visakh["capacity_unit"] == "mmtpa"
    assert r_visakh["plant"] == "HPCL Visakh Refinery"
    assert r_visakh["status"] == "unverified"

    sk_solar = _doc(
        "Commissioning of Solar Power Plant",
        "Sub: Intimation under Regulation 30(6) - Reappointment of Mr. Rajendra Gandhi as Managing Director and "
        "Commissioning of Solar Power Plant. "
        "2. Commissioning of Solar Power Plant: The Company commissioned 4 MWp of Solar Power Plant on roof top of "
        "newly built Unit 3 at a cost of Rs. 13.88 cr.",
        symbol="STOVEKRAFT", filing_date="2024-08-10",
    )
    r_solar = _row(fe.event_rows(sk_solar)[0], "capacity_commissioned")
    assert r_solar["capacity_value"] == pytest.approx(4.0)
    assert r_solar["capacity_unit"] == "mwp"
    assert r_solar["status"] == "unverified"

    sk_foundry = _doc(
        "Commissioning of Cast Iron foundry",
        "Sub: Commissioning of Cast Iron foundry "
        "Pursuant to the Regulation 30, we wish to inform that today, i.e., 25 November 2024, the Company commissioned "
        "the newly constructed Cast Iron Foundry at Harohalli factory. The said foundry is built at a cost of Rs. 40 "
        "Crores. The Foundry's current installed capacity of 2.2 million pieces per annum and has been designed to "
        "reach 4.4 million pieces per annual in future.",
        symbol="STOVEKRAFT", filing_date="2024-11-25",
    )
    r_foundry = _row(fe.event_rows(sk_foundry)[0], "capacity_commissioned")
    assert r_foundry["capacity_value"] == pytest.approx(2.2)
    assert r_foundry["capacity_unit"] == "mn_pieces"
    assert r_foundry["plant"] == "Harohalli"
    assert r_foundry["status"] == "unverified"

    # Counter-tests for graded R rows: pilot E05 (BLUEJET) & new20 id=175 (GAIL GMPL)
    bluejet_e05 = _doc(
        "The Company at its existing facility at Ambernath has successfully commissioned multi-product production block",
        "Sub: Disclosure under Regulation 30 – Commissioning of multi- product Production block at Ambernath [Unit II]. "
        "Blue Jet Healthcare Limited at the Company's existing Unit 2 facility situated at Ambernath, Maharashtra, "
        "has successfully completed commissioned multi-product Production block and commenced manufacturing of Validation "
        "Batches w.e.f 29th June 2024. 1. Existing capacity 1020.90 KL. 3. Installed capacity addition 120 KL.",
        symbol="BLUEJET", filing_date="2024-06-30",
    )
    r_e05 = _row(fe.event_rows(bluejet_e05)[0], "capacity_commissioned")
    assert r_e05["capacity_value"] == pytest.approx(120.0) and r_e05["status"] == "unverified"

    gail_175 = _doc(
        "Successfully Commissions 1.25 million tons per annum PTA Manufacturing Plant at Mangalore",
        "GAIL Mangalore Petrochemicals Limited (GMPL), a wholly owned subsidiary of GAIL (India) Limited (GAIL) has "
        "successfully commissioned its 1.25 MTPA Purified Terephthalic Acid (PTA) manufacturing plant located in the "
        "Mangalore Special Economic Zone (MSEZ), Karnataka. In the year 2023, GAIL acquired JBPL through the CIRP.",
        symbol="GAIL", filing_date="2026-11-05",
    )
    r_175 = _row(fe.event_rows(gail_175)[0], "capacity_commissioned")
    assert r_175["capacity_value"] == pytest.approx(1.25) and r_175["capacity_unit"] == "mtpa"
    assert r_175["status"] == "unverified"


def test_t242_r2_fix2_fund_raise_rules_and_r_counter_tests() -> None:
    # e127: Market Capitalisation Rs.46,660 Cr must not produce fund_raise
    e127 = _doc(
        "Please refer the attachment",
        "Press Release: NLCIL Records Historic Financial Performance. "
        "Listing of NIRL through fresh issue of equity shares approved. "
        "NLCIL's shares traded at an All Time Highest Ever Market Price of Rs.336.50 per share with Market "
        "Capitalisation reached more than Rs.46,660 Cr.",
        symbol="NLCINDIA", filing_date="2026-05-13",
    )
    assert not [r for r in fe.event_rows(e127)[0] if r["kind"] == "fund_raise"]

    # e122: company investing in another firm (Nimble Vision) must not produce fund_raise
    e122 = _doc(
        "Intimation for execution of Shareholders Agreement",
        "A Share Subscription and Shareholders Agreement has been executed amongst WABAG and Nimble Vision Private "
        "Limited. WABAG shall subscribe to 955 Equity Shares of Nimble Vision, for an investment of ~ INR 3.00 Crores. "
        "First right to share subscription in case of issuance of shares.",
        symbol="WABAG", filing_date="2026-04-17",
    )
    assert not [r for r in fe.event_rows(e122)[0] if r["kind"] == "fund_raise"]

    # e52: NCD allotment with SEBI template 'In case of preferential issue ... Not Applicable' -> instrument='ncd'
    e52 = _doc(
        "Issue of Unsecured, Redeemable, Non-Convertible, Non-Cumulative, Taxable Debentures on Private Placement Basis",
        "Sub.: Issue of Unsecured, Redeemable, Non-Convertible, Non-Cumulative, Taxable Debentures on Private Placement "
        "Basis. The Company had issued Unsecured, Redeemable, Non-Convertible, Non-Cumulative, Taxable Debentures of "
        "Rs.1,00,000/- each aggregating to Rs. 2500 Crores on private placement basis. "
        "ii. post allotment of securities - outcome of the subscription. "
        "4. In case of preferential issue the listed entity shall disclose the following additional details: Not Applicable",
        symbol="HINDPETRO", filing_date="2025-04-29",
    )
    r52 = _row(fe.event_rows(e52)[0], "fund_raise")
    assert r52["amount_inr_cr"] == pytest.approx(2500.0)
    assert r52["instrument"] == "ncd"
    assert r52["raise_stage"] == "allotment"

    # e35: QIP board approval 'not exceeding ₹ 350 Crores' -> raise_stage='approval'
    e35 = _doc(
        "Outcome of the Board meeting held today",
        "Sub: Outcome of the Board meeting held today. The Board of Directors transacted: "
        "2. Raising of funds by way of issuance of equity shares for an aggregate amount not exceeding ₹ 350 Crores "
        "by way of qualified institutions placement ('QIP'). Type of issuance (further public offering, rights issue, "
        "qualified institutions placement, preferential allotment etc.): Qualified institutional placements (QIP) "
        "under Companies (Prospectus and Allotment of Securities) Rules, 2014.",
        symbol="DEEPINDS", filing_date="2024-12-28",
    )
    r35 = _row(fe.event_rows(e35)[0], "fund_raise")
    assert r35["amount_inr_cr"] == pytest.approx(350.0)
    assert r35["instrument"] == "qip"
    assert r35["raise_stage"] == "approval"

    # Counter-test: Pilot R E17 (SANDUMA QIP with 'permitted to invest in such issuance') & new20 id=32 (YASHO)
    e17 = _doc(
        "Outcome of the Board meeting",
        "Sub: Outcome of Board Meeting. The Board considered and approved raising of funds by way of issuance of "
        "Equity Shares for an aggregate amount not exceeding ₹1,000 crore by way of Qualified Institutions Placement "
        "(QIP) to such investors that may be permitted to invest in such issuance of Equity Shares.",
        symbol="SANDUMA", filing_date="2024-09-16",
    )
    r17 = _row(fe.event_rows(e17)[0], "fund_raise")
    assert r17["amount_inr_cr"] == pytest.approx(1000.0)
    assert r17["instrument"] == "qip"
    assert r17["raise_stage"] == "approval"
    assert r17["status"] == "unverified"

    yasho_32 = _doc(
        "Please find attached outcome",
        "Sub: Outcome of Board Meeting. The Board has approved the issuance of upto 6,57,895 fully paid-up equity "
        "shares on a preferential basis at a price of ₹1,900/- per equity share aggregating to a total consideration "
        "of ₹1,25,00,00,500/-. The preferential allotment is proposed to be made to Malabar India Fund Limited.",
        symbol="YASHO", filing_date="2024-12-18",
    )
    r32 = _row(fe.event_rows(yasho_32)[0], "fund_raise")
    assert r32["amount_inr_cr"] == pytest.approx(125.0001)
    assert r32["instrument"] == "preferential"
    assert r32["raise_stage"] == "approval"
    assert r32["status"] == "unverified"


def test_t242_r2_fix3_customer_cleanup_dotted_and_contract_label() -> None:
    lic = _doc(
        "Intimation for securing Digital workplace solutions contract from LIC worth Rs. 138.44 crores",
        "1 Name of the entity awarding — the | Life Insurance Corporation (LIC) order(s)/contract(s) "
        "2 significant terms and conditions of order(s)/contract(s) awarded in brief; Supply of Desktops "
        "7 broad consideration or size of the order(s)/contract(s); Rs. 138.44 crores",
        symbol="DSSL",
    )
    assert _row(fe.event_rows(lic)[0], "order_win")["customer"] == "Life Insurance Corporation (LIC)"

    nabard = _doc(
        "Dynacons secures Prestigious Contract worth Rs. 233 crores from NABARD",
        "1 name of the entity awarding the | National Bank for Agriculture and Rural order(s)/contract(s) "
        "Development (NABARD) 2 significant terms and conditions of order(s)/contract(s) awarded in brief; CBS "
        "7 broad consideration or size of the order(s)/contract(s); Rs. 233 crores",
        symbol="DSSL",
    )
    assert _row(fe.event_rows(nabard)[0], "order_win")["customer"] == (
        "National Bank for Agriculture and Rural Development (NABARD)"
    )

    cpcl = _doc(
        "WABAG secures order worth INR 145 Crores from Chennai Petroleum Corporation Limited",
        "Sub.: WABAG secures order worth INR 145 Crores from Chennai Petroleum Corporation Limited "
        "Ref.: Intimation under Regulation 30 of the SEBI Regulations. Please find enclosed intimation about "
        "securing order worth INR 145 Crores from Chennai Petroleum Corporation Limited ('CPCL').",
        symbol="WABAG",
    )
    assert _row(fe.event_rows(cpcl)[0], "order_win")["customer"] == "Chennai Petroleum Corporation Limited"

    bapco = _doc(
        "WABAG secures 7 years Operation Contract order worth around USD 14 Million (INR 121 Crores approx.)",
        "WABAG continues to expand its presence securing an order worth ~USD 14 Million (~INR 121 Crores) from "
        "BAPCO Refining B.S.C (BAPCO) towards operation (O&M) of Industrial Wastewater Treatment Plant for 7 years.",
        symbol="WABAG",
    )
    assert _row(fe.event_rows(bapco)[0], "order_win")["customer"] == "BAPCO Refining B.S.C (BAPCO)"

    gpt_rvnl = _doc(
        "Press Release dated June 04, 2024 for the order bagged valued Rs. 547 Crores.",
        "GPTINFRA Bags Order Valued at Rs. 547 Crore. "
        "Name of the entity awarding the contract : Rail Vikas Nigam Limited "
        "Nature of contract : Construction of Viaduct Portion "
        "Size of contract : Rs. 547 Crore",
        symbol="GPTINFRA",
    )
    assert _row(fe.event_rows(gpt_rvnl)[0], "order_win")["customer"] == "Rail Vikas Nigam Limited"


def test_t242_r2_fix4_amendment_subject_gate_and_cancellation_customer() -> None:
    # e55: SEBI LODR boilerplate 'and amendments thereof' must not classify a new order as order_amendment
    e55 = _doc(
        "Please find enclosed intimation for securing order worth Rs. 18.84 crores for CTS Scanner from Bank of Baroda",
        "Sub: Intimation Under Regulation 30 of the SEBI Regulations, 2015. Dear Sir/Madam, "
        "Pursuant to Regulation 30 of the SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015, "
        "and amendments thereof, please find enclosed intimation for securing order worth Rs. 18.84 Crores for "
        "CTS Scanners from Bank of Baroda. "
        "1 Name of the entity awarding the order(s)/contract(s) Bank of Baroda "
        "7 broad consideration or size of the order(s)/contract(s); Rs. 18.84 Crores",
        symbol="DSSL",
    )
    r55 = _row(fe.event_rows(e55)[0], "order_win")
    assert r55["amount_inr_cr"] == pytest.approx(18.84)
    assert r55["customer"] == "Bank of Baroda"

    # e31: cancellation keeps customer Saudi Water Authority
    e31 = _doc(
        "Update on our earlier intimation dated September 06, 2024",
        "Sub.: Update on our earlier intimation dated September 06, 2024 titled 'WABAG wins an order from "
        "Saudi Water Authority worth USD 317 Million (~SAR 1,190 Million / ~INR 2,700 Crores) towards a 300 MLD Plant' "
        "Ref.: Intimation under Regulation 30. With reference to our above intimation relating to 300 MLD Plant Order, "
        "we hereby inform that the Customer has notified all tender participants that the said tender stands cancelled.",
        symbol="WABAG", filing_date="2024-12-17",
    )
    r31 = _row(fe.event_rows(e31)[0], "order_amendment")
    assert r31["amount_inr_cr"] == pytest.approx(-2700.0)
    assert r31["customer"] == "Saudi Water Authority"


def test_t242_r2_fix5_capex_revisions_and_annual_revenue() -> None:
    # e56: revised to X vis-a-vis Y keeps prior cost and delta in detail
    e56 = _doc(
        "Intimation under Regulation 30 of the SEBI (LODR) Regulations, 2015",
        "Pursuant to completion of the TEV study, the estimated cost of the aforementioned project has been revised "
        "to ₹1,982.79 Crores vis-à- vis preliminary project cost of approximately ₹1,950 Crores, as approved by the "
        "Board at its meeting held on 9th August, 2023.",
        symbol="DEEPAKFERT", filing_date="2025-06-10",
    )
    r56 = _row(fe.event_rows(e56)[0], "capex_approval")
    assert r56["amount_inr_cr"] == pytest.approx(1982.79)
    assert "cost revision" in r56["detail"] and "1950" in r56["detail"] and "+32.79" in r56["detail"]
    assert r56["status"] == "unverified"

    # e78: model reply with 'annual revenue' goes to value_annual (and computes value_total over 15y tenure)
    e78 = _doc(
        "Intimation for entering into a long term agreement with a leading MNC",
        "Yasho Industries Limited has entered into a long-term supply agreement for a period of 15 Years. "
        "4 Time period; 15 years 5 Broad commercial consideration; Approximately Rs 150 Cr annual revenue "
        "starting from end of FY 27.",
        symbol="YASHO", filing_date="2025-09-04",
    )
    (r78,) = fe.model_rows(
        e78, ["order_win"],
        _model_reply(
            amount_inr_cr=150.0,
            value_text="Approximately Rs 150 Cr annual revenue starting from end of FY 27",
            customer="A global multinational corporation",
            execution_months=180.0,
        ),
    )
    assert r78["value_annual"] == pytest.approx(150.0)
    assert r78["value_total"] == pytest.approx(2250.0)
    assert r78["status"] == "unverified"


def test_t242_r2_fix6_main_prints_rupee_safely_on_cp1252(monkeypatch: pytest.MonkeyPatch) -> None:
    import io
    import shutil
    import sys

    work = Path(".tmp/t242_cp1252")
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    try:
        db_path = work / "events.db"
        rep_path = work / "report.md"
        doc = _doc("New Order", "The Company received an order of ₹ 100 Crores from Acme Limited.")
        row, _ = fe.event_rows(doc)
        fe.write_db(db_path, row, [], {"stores": 1, "docs": 1, "classified_filings": 1, "by_class": {"order_win": 1}})
        buf = io.BytesIO()
        cp1252_out = io.TextIOWrapper(buf, encoding="cp1252", errors="strict")
        monkeypatch.setattr(sys, "stdout", cp1252_out)
        rc = fe.main(["--report", str(db_path), "--report-file", str(rep_path)])
        cp1252_out.flush()
        assert rc == 0
        assert "T-231 filing events" in buf.getvalue().decode("cp1252")
    finally:
        shutil.rmtree(work, ignore_errors=True)


# ---- T-242 round 3: per-kind gate, fund-raise vetoes, raise stage, amendment, capacity, capex, customers -------
def test_t242_r3_fix1_only_a_graded_kind_is_verified() -> None:
    assert fe.VERIFIED_KINDS == frozenset({"order_win"})
    fund = _doc(
        "Outcome of Board Meeting - Issue of listed, rated, secured, redeemable non-convertible debentures",
        "The Board of Directors of the Company at its meeting held today has approved the issuance of 2,50,000 "
        "listed, rated, secured, redeemable non-convertible debentures aggregating up to INR 250,00,00,000.",
    )
    row = _row(fe.event_rows(fund)[0], "fund_raise")
    assert row["status"] == "unverified" and row["detail"].startswith("kind_not_gated: fund_raise")
    order = _doc("New orders worth Rs. 816 Crores",
                 "The Company has secured new orders of Rs. 816 crores across its various businesses.")
    assert _row(fe.event_rows(order)[0], "order_win")["status"] == "verified"


@pytest.mark.parametrize("title,text", [
    ("GNG Electronics Limited has informed the Exchange regarding execution of Supplemental and Amendatory Agreement "
     "with ICICI Bank Limited",
     "The Company has entered into a Supplemental and Amendatory Agreement to the Facility Agreement with ICICI Bank "
     "Limited. The Overall limits stand enhanced from INR 400 million to INR 720 million."),
    ("Pursuant to Regulation 30 and 33 of SEBI (LODR) Regulations 2015",
     "The Board further took note that due to non-receipt of balance 75% amount with respect to 560000 warrants "
     "within a period of 18 months, which was allotted on 22.02.2023, an amount of 25% received against allotment of "
     "said warrants amounting to Rs. 2,35,20,000/- has been forfeited."),
    ("Revision of Credit Facilty availed with Kotak Mahindra Bank Limited.",
     "The Company has revised its existing credit facility arrangement with Kotak Mahindra Bank Limited. Initially, "
     "the total sanctioned credit facility was INR 5000 lakhs comprising an overdraft facility of INR 1000 lakhs. The "
     "Company has surrendered the overdraft facility of INR 1000 lakhs, thereby reducing the total sanctioned limit "
     "to INR 4000 lakhs."),
    ("Information under Reg 30 of SEBI",
     "Investment in Wholly-Owned Subsidiary Company. The Company has invested 1,50,00,000 equity Shares of Spark "
     "Minda Green Mobility Systems Private Limited, the wholly owned subsidiary, for an amount of INR 15 crores by "
     "way of subscription to rights issue of Rs. 10 each."),
])
def test_t242_r3_fix2_agreement_updates_are_not_a_fund_raise(title: str, text: str) -> None:
    rows, _missing = fe.event_rows(_doc(title, text))
    assert not [r for r in rows if r["kind"] == "fund_raise"], rows


def test_t242_r3_fix2_own_issue_with_facility_boilerplate_still_raises() -> None:
    doc = _doc(
        "Intimation of allotment of equity shares under Qualified Institutions Placement",
        "The Fund Raising Committee approved the issue and allotment of 91,11,630 Equity Shares to the eligible "
        "qualified institutional buyers at the issue price of ₹ 955 per Equity Share aggregating to ₹ 870.16 crores. "
        "The proceeds are held in escrow as per the working capital facility sanction letter.",
    )
    row = _row(fe.event_rows(doc)[0], "fund_raise")
    assert row["amount_inr_cr"] == pytest.approx(870.16) and row["raise_stage"] == "allotment"


def test_t242_r3_fix3_board_approval_is_not_an_allotment() -> None:
    board = _doc(
        "Outcome of Board Meeting - Issue of listed, rated, secured, redeemable non-convertible debentures",
        "The Board of Directors of the Company at its meeting held today has approved the issuance of 2,50,000 "
        "listed, rated, secured, redeemable non-convertible debentures, having a face value of up to INR 10,000 each "
        "aggregating up to INR 250,00,00,000. tenure of the instrument - date of allotment and date of maturity: "
        "Shall be provided at the time of Allotment of respective NCDs.",
    )
    assert _row(fe.event_rows(board)[0], "fund_raise")["raise_stage"] == "approval"
    done = _doc("Allotment of 900000 equity shares pursuant to warrants conversion.",
                "The Company has allotted 9,00,000 Equity Shares pursuant to exercise of Convertible Warrants at an "
                "issue price of INR 115.50 per share.")
    assert _row(fe.event_rows(done)[0], "fund_raise")["raise_stage"] == "allotment"


def test_t242_r3_fix4_l1_and_loss_reduction_are_awards() -> None:
    l1 = _doc(
        "EMS Limited has informed the exchange regarding Intimation of Lowest Bidder (L-1) in tender at UPCL VCVGS "
        "Urja Bhawan, Dehradun",
        "EMS Limited is the lowest bidder (L-1) in the tender for Supply, Installation, Testing & Commissioning of "
        "Infrastructure Works_Loss Reduction on turnkey basis. The estimated order value is approximately "
        "Rs.14810.69 Lacs (Rupee Fourteen Thousand Eight Hundred Ten lacs and Sixty-Nine Thousand Only). The details "
        "of the works are as under: S. No. Particulars Details 1. Name(s) of the entity awarding the order [s) "
        "/Contract(s) SE, Corporate, C and P-I, UPCL VCVGS Urja Bhawan, Dehradun 3. Whether order(s) /contract(s) "
        "have been awarded by domestic /international entity Domestic Entity (L – 1 Status) 7. Broad consideration "
        "or size of the order(s) contract(s) Estimated order value is approximately Rs.14810.69 lacs (Rupee Fourteen "
        "Thousand Eight Hundred Ten Lacs and Sixty-Nine Thousand Only).",
    )
    rows, _missing = fe.event_rows(l1)
    assert not [r for r in rows if r["kind"] == "order_amendment"], rows
    # T-242 round 6: an L1-only intimation is not an order yet; the printed value is kept, the status is not.
    l1_row = _row(rows, "order_win")
    assert l1_row["amount_inr_cr"] == pytest.approx(148.1069)
    assert (l1_row["status"], l1_row["why"]) == ("unverified", "l1_only")

    loa = _doc(
        "EMS Limited has informed the exchange regarding Intimation of Receipt of letter of award for Development of "
        "Distribution Infrastructure-loss reduction works at EDC Dehradun rural circle",
        "EMS Limited has received a letter of award for Development of Distribution Infrastructure-loss reduction "
        "works at EDC Dehradun rural Circle. The order value is approximately Rs.14,112.14 Lacs (Rupee Fourteen "
        "Thousand One Hundred Twelve lacs and Fourteen Thousand Only). The details of the works are as under: "
        "S. No. Particulars Details 1. Name(s) of the entity awarding the order [s) /Contract(s) Uttarakhand Power "
        "Corporation Ltd 3. Whether order(s) /contract(s) have been awarded by domestic /international entity "
        "Domestic Entity (Letter of award) 7. Broad consideration or size of the order(s) contract(s) Order value of "
        "Rs. 14,112.14 Lacs (Rupee Fourteen Thousand One Hundred Twelve lacs and Fourteen Thousand Only).",
    )
    rows, _missing = fe.event_rows(loa)
    assert not [r for r in rows if r["kind"] == "order_amendment" and (r["amount_inr_cr"] or 0) < 0], rows
    assert _row(rows, "order_win")["amount_inr_cr"] == pytest.approx(141.1214)


def test_t242_r3_fix5_stale_numeric_commissioning_date_is_vetoed() -> None:
    old = _doc(
        "Updates on Poly Aluminium Chloride Plant at Vadodara. For more details, kindly refer attached file.",
        "The Company had successfully commissioned 32,000 TPA of Poly Aluminium Chloride Plant (18% PAC) at Coelho "
        "Complex, Vadodara, which had informed to the stock exchanges vide our letter dated 01.08.2018. In the "
        "existing facility of PAC plant, the Company has now installed further Spray dryer to convert a part of "
        "liquid PAC to PAC powder.",
        filing_date="2025-02-04",
    )
    assert not [r for r in fe.event_rows(old)[0] if r["kind"] == "capacity_commissioned"]
    fresh = _doc(
        "Commencement of commercial production of Instant Coffee at its Instant Coffee Subsidiary unit by adding "
        "2000 MTPA",
        "The Company has commenced commercial production of Instant Coffee at its Instant Coffee Subsidiary unit by "
        "adding 2000 MTPA w.e.f. 01.04.2026.",
        filing_date="2026-04-02",
    )
    assert _row(fe.event_rows(fresh)[0], "capacity_commissioned")["capacity_value"] == pytest.approx(2000.0)


def test_t242_r3_fix6_a_stake_purchase_is_not_capex() -> None:
    doc = _doc(
        "Transrail to enter renewable power generation through proposed 49% investment in 990 MW solar portfolio in "
        "Maharashtra",
        "Transrail Lighting Limited today announced that its Board of Directors has approved the proposed acquisition "
        "of a 49% equity stake in NOPL Pace Green Energy Private Limited, at a cash consideration of Rs. 20 cr. The "
        "indicative total project cost is approximately ₹3,900 crore, and debt financing has been sanctioned by "
        "reputed financial institution.",
        symbol="TRANSRAILL", filing_date="2026-10-19",
    )
    assert not [r for r in fe.event_rows(doc)[0] if r["kind"] == "capex_approval"]


def test_t242_r3_fix7_customer_forms_fill_the_awarder() -> None:
    forms = [
        ("Name(s) of the entity awarding the order [s) /Contract(s) Jaypee Infratech Limited 2. Significant terms "
         "and conditions", "Jaypee Infratech Limited"),
        ("Name(s) of the entity awarding the order [s) /Contract(s) UP Jal Nigam (Urban) 2. Significant terms and "
         "conditions", "UP Jal Nigam (Urban)"),
        ("Name of the entity awarding the contract Mahamana Pandit Madan Mohan Malaviya Cancer Centre & Homi Bhabha "
         "Cancer Hospital (MPMMCC), Banaras Hindu University (BHU), Varanasi Nature of contract Extension",
         "Mahamana Pandit Madan Mohan Malaviya Cancer Centre & Homi Bhabha Cancer Hospital (MPMMCC)"),
        ("Name of the entity awarding the order(s)/contract(s) Details Autonomous Scientific Society under the "
         "administrative control of Ministry of Electronics & Information Technology, Government of India (b) "
         "Significant terms", "Autonomous Scientific Society"),
    ]
    for text, expected in forms:
        raw = fe._annexure_awarders(text)
        assert raw and fe._clean_party(raw[0], from_annexure=True) == expected, (text, raw)
    doc = _doc("New orders worth Rs. 1,025 Crores",
               "KEC International has secured new orders of Rs. 1,025 crores: 765 kV GIS Substation in India, "
               "from Power Grid Corporation of India Limited (PGCIL) for T&D projects.")
    assert _row(fe.event_rows(doc)[0], "order_win")["customer"] == "Power Grid Corporation of India Limited (PGCIL)"


def test_t242_r3_fold_keeps_two_orders_whose_values_differ() -> None:
    def order_doc(amount_cr: float, filing_date: str, known_at: str, key: str) -> dict[str, Any]:
        return _doc(
            f"We are pleased to enclose a copy of the press release with respect to new orders of Rs. "
            f"{amount_cr:,.0f} Crores secured by the Company.",
            f"KEC International Ltd. has secured new orders of Rs. {amount_cr:,.0f} crores across its businesses. "
            "765 kV GIS Substation in India, from Power Grid Corporation of India Limited (PGCIL).",
            symbol="KEC", doc_key=key, filing_date=filing_date, known_at=known_at,
        )

    rows = fe.event_rows(order_doc(1025.0, "2024-06-26", "2024-06-26T17:50:00", "a"))[0] \
        + fe.event_rows(order_doc(1017.0, "2024-07-02", "2024-07-02T17:58:00", "b"))[0]
    assert len(fe._fold_same_order(rows, [])) == 2


# ---- T-242 round 4: customer clean-up, order roll-ups, aggregates, cross-filing duplicates -------------------

def test_t242_r4_customer_starts_and_ends_where_the_entity_does() -> None:
    doc = _doc(
        "Attached Herewith the copy of Intimation of purchase order received from Provigil Surveillance Limited",
        "We would like to inform you that the subsidiary has received a Purchase Order from South Central Railway, "
        "Secunderabad Division for supply of systems. Annexure A: 1. Name of the entity awarding the "
        "Order/Contract South Central Railway, Secunderabad Division 2. Significant terms and conditions of the "
        "Order/Contract awarded in brief Supply of systems 7. Broad consideration or size of the Order/Contract "
        "Rs. 4.10 crores",
        symbol="MCLOUD",
    )
    assert _row(fe.event_rows(doc)[0], "order_win")["customer"] == (
        "South Central Railway, Secunderabad Division")
    assert fe._clean_party("Dakshin Gujarat Vij Company Limited (DGVCL) Dear Sir/Madam") == (
        "Dakshin Gujarat Vij Company Limited (DGVCL)")
    assert fe._clean_party("Twenty-Five Downtown Realty Limited Dear Sir/ Madam") == (
        "Twenty-Five Downtown Realty Limited")
    assert fe._clean_party("Signatureglobal (India) Limited Mumbai") == "Signatureglobal (India) Limited"


def test_t242_r4_a_printed_description_is_customer_desc() -> None:
    for text in ("A hyperscale partner", "Domestic Telecom Operator", "Leading telecom infrastructure company",
                 "key customers in the renewable energy sector"):
        assert fe._is_customer_description(text), text
    for text in ("Hinduja Group Limited", "CIDCO", "South Central Railway, Secunderabad Division"):
        assert not fe._is_customer_description(text), text
    model = _doc(
        "Intimation of receipt of order under Regulation 30 of SEBI LODR 2015",
        "Name of the entity awarding the order(s)/contract(s) Domestic Telecom Operator "
        "7. Broad consideration or size of the order(s)/contract(s) approx. INR 960 cr.",
        symbol="STLTECH",
    )
    raw = json.dumps({"events": [{"kind": "order_win", "amount_inr_cr": 960,
                                  "value_text": "approx. INR 960 cr.",
                                  "customer": "Domestic Telecom Operator"}]})
    row = fe.model_rows(model, ["order_win"], raw)[0]
    assert row["customer"] is None and row["customer_desc"] == "Domestic Telecom Operator"
    assert "customer_desc" in fe.COLUMNS and "customer_desc TEXT" in fe.SCHEMA
    old = sqlite3.connect(":memory:")
    old.execute("CREATE TABLE event (event_id INTEGER PRIMARY KEY, customer TEXT)")
    fe._ensure_event_columns(old)
    assert "customer_desc" in {r[1] for r in old.execute("PRAGMA table_info(event)")}


def test_t242_r4_an_awarder_with_a_bracketed_place_is_named() -> None:
    doc = _doc(
        "Attached Herewith the copy of Intimation of purchase order received from Provigil Surveillance Limited",
        "We wish to inform our shareholders that the wholly owned subsidiary has received a Purchase Order from "
        "GAIL (India) Limited. The Purchase Order has been awarded through the Government e-Marketplace (GeM) "
        "platform. The total value of the contract is ₹127.62 million.",
        symbol="MCLOUD",
    )
    assert _row(fe.event_rows(doc)[0], "order_win")["customer"] == "GAIL (India) Limited"


def test_t242_r4_a_period_rollup_is_not_an_order_win() -> None:
    doc = _doc(
        "The Company is pleased to announce that it has been awarded orders worth INR 900 crores in FY 24 to "
        "provide integrated optical solutions to the leading service providers in the country.",
        "The Company is pleased to announce that it has been awarded orders worth ~INR 900 crore in FY24 to "
        "provide integrated optical solutions to the leading service providers in the country.",
        symbol="STLTECH", filing_date="2024-04-02",
    )
    assert not [r for r in fe.event_rows(doc)[0] if r["kind"] == "order_win"]
    assert fe._ORDER_ROLLUP.search("orders received during the year")
    assert fe._ORDER_INFLOW_TITLE.search("Consolidated order inflow for FY27")
    assert fe._ORDER_INFLOW_TITLE.search("Order intake for the quarter")
    # a genuine order-win release quoting its own order inflow is not a period aggregate (KEC/TRANSRAILL)
    assert not fe._ORDER_INFLOW_TITLE.search("KEC International wins New Orders of Rs. 1,034 crores")


def test_t242_r4_the_title_aggregate_survives_a_split_table() -> None:
    doc = _doc(
        "Sugs LLoyd Limited secures Rs. 214.27 crore Orders from TPSODL & TPWODL.",
        "Subject: Intimation of receipt of Letter of Intent (LOI) from TP Southern Odisha Distribution Limited "
        "(TPSODL) and TP Western Odisha Distribution Limited (TPWODL). The aggregate order value (Including GST) "
        "from TPSODL and TPWODL for the three-year contract period is ₹ 2,14,27,36,930/- (Rupees Two Hundred "
        "Fourteen Crore Twenty-Seven Lakh Thirty-Six Thousand Nine Hundred and Thirty Only). "
        "1. Name of the entity awarding the order(s)/contract(s) TP Southern Odisha Distribution Limited "
        "TP Western Odisha Distribution Limited 2. Significant terms and conditions of the order(s)/contract(s) "
        "awarded As per Contract 7. Broad consideration or size of the order(s)/contract(s) The aggregate order "
        "value (Including GST) for the three- year contract period is ₹ 1,15,01,93,663 (Rupees One Hundred "
        "Fifteen Crore One Lakh Ninety-Three Thousand Sixty-Three Only), comprising: Year 1 (01.10.2026 to "
        "30.09.2027): ₹ 37,99,46,865",
        symbol="SUGSLLOYD", filing_date="2026-09-01",
    )
    rows = [r for r in fe.event_rows(doc)[0] if r["kind"] == "order_win"]
    assert len(rows) == 1
    assert rows[0]["amount_inr_cr"] == pytest.approx(214.27)
    assert rows[0]["value_total"] == pytest.approx(214.27)


def test_t242_r4_the_next_day_press_release_is_the_same_order() -> None:
    first = _doc(
        "Sugs LLoyd Limited secures Rs. 214.27 crore Orders from TPSODL & TPWODL.",
        "Subject: Intimation of receipt of Letter of Intent (LOI) from TP Southern Odisha Distribution Limited "
        "(TPSODL) and TP Western Odisha Distribution Limited (TPWODL). The aggregate order value (Including GST) "
        "from TPSODL and TPWODL for the three-year contract period is ₹ 2,14,27,36,930/-. "
        "1. Name of the entity awarding the order(s)/contract(s) TP Southern Odisha Distribution Limited "
        "TP Western Odisha Distribution Limited 2. Significant terms and conditions of the order(s)/contract(s) "
        "awarded As per Contract 7. Broad consideration or size of the order(s)/contract(s) The aggregate order "
        "value (Including GST) for the three- year contract period is ₹ 1,15,01,93,663 comprising: Year 1 "
        "(01.10.2026 to 30.09.2027): ₹ 37,99,46,865",
        symbol="SUGSLLOYD", doc_key="first", filing_date="2026-09-01", known_at="2026-09-01T18:00:00",
    )
    second = _doc(
        "Sugs LLoyd Wins Rs. 214.27 Crore Orders from TPSODL and TPWODL for Three-Year Distribution Network "
        "maintenance Contracts in Odisha.",
        "Sub: Sugs Lloyd Wins ₹214.27 Crore Orders from TPSODL and TPWODL for Three-Year Distribution Network "
        "Maintenance Contracts in Odisha. We are pleased to inform that the Company has received Letters of "
        "Intent from TPSODL and TPWODL. The total order value is ₹214.27 Crore.",
        symbol="SUGSLLOYD", doc_key="second", filing_date="2026-09-02", known_at="2026-09-02T10:00:00",
    )
    rows = fe.event_rows(first)[0] + fe.event_rows(second)[0]
    amends: list[dict[str, Any]] = []
    kept = [r for r in fe._fold_same_order(rows, amends) if r["kind"] == "order_win"]
    assert len(kept) == 1 and kept[0]["doc_key"] == "first"
    assert [a["amends"] for a in amends] == ["first"]


def test_t242_city_after_company_suffix_cut_but_public_body_name_kept():
    from reality_engine.research import filing_events as fe
    assert fe._clean_party("Signatureglobal (India) Limited Mumbai") == "Signatureglobal (India) Limited"
    assert fe._clean_party("Municipal Corporation Jodhpur") == "Municipal Corporation Jodhpur"
    assert fe._clean_party("Uttar Pradesh Jal Nigam, Lucknow") == "Uttar Pradesh Jal Nigam"


# ---- T-242 round 5: this step's own amount, raise stage map, duplicates, vetoes -------------------------
R5_AMOUNTS = {
    # a QIP allotment whose total the OCR printed without its currency mark; the paid-up capital after the
    # issue is a different number and never adds to it (fresh4 #10)
    "qip_printed_total": (
        "Outcome of the Fund Raising Committee Meeting held on 04th December, 2025 for approval of allotment of "
        "12793102 equity shares of a face value of Rs. 10/- each at a price of Rs. 145/- per Equity Share. "
        "we wish to inform you that the Fund Raising Committee of the Company at its meeting held today, i.e. "
        "December 04, 2025, approved the issue and allotment of 1,27,93, 102 Equity Shares, to eligible QIBs at "
        "the issue price of 145 per Equity Share, aggregating to 1,85,49,99,790 (Rupees One Hundred Eighty-Five "
        "Crore Forty-Nine Lakh Ninety-Nine Thousand Seven Hundred Ninety Only), pursuant to the QIP. Pursuant "
        "to the allotment of Equity Shares under the QIP, the paid-up equity share capital of the Company stands "
        "increased from 53,04,93,890 consisting of 5,30,49,389 Equity Shares to 65,84,24,916 consisting of "
        "6,58,42,491 Equity Shares.",
        185.5),
    # a conversion allotment: the 25% receipt at the earlier warrant allotment is not this step (fresh4 #12)
    "conversion_25pct": (
        "Allotment of equity shares pursuant to conversion of warrants. This is in furtherance to our earlier "
        "intimation dated 11th September 2025, wherein it was informed that the Company had allotted 15,00,000 "
        "fully convertible warrants of Rs. 10/- each for cash at an issue price of Rs. 124/- per warrant, on a "
        "preferential basis. At the time of the allotment of warrants, the Company had received an amount of "
        "Rs. 4,65,00,000/- being 25% of the total consideration (i.e, Rs. 31/- per warrant) from the allottee. "
        "We hereby inform you that the Board of Directors of the Company has approved the allotment of 8,00,000 "
        "Equity Shares of face value of Rs. 10/- each at an issue price of Rs. 124/- per Equity Share, fully "
        "paid-up, aggregating to Rs. 9,92,00,000/- upon conversion of 8,00,000 warrants.",
        9.92),
    # a conversion of part of an earlier warrant issue: the earlier aggregate and the 75% balance are not this
    # step, the shares x the issue price are (fresh4 #13)
    "conversion_of_part": (
        "Allotment of Equity Shares pursuant to conversion of Warrants exercised by a fund at an issue price of "
        "₹425/-. This is in continuation to the disclosure dated 5th December, 2025 wherein the Company had "
        "allotted 1,17,64,705 Convertible Warrants at an issue price of ₹425/- per Warrant, aggregating to "
        "₹499,99,99,625/- through preferential allotment to Promoter and Non-Promoters. The warrant holder has "
        "exercised its right to convert all the Warrants held by them and accordingly the Company has today "
        "allotted, 3,52,941 Equity Shares of face value of ₹1/- each to the holder. The allotment has been made "
        "upon the receipt of the balance payment of ₹11,24,99,943.75/- (i.e. 75% of ₹14,99,99,925/-).",
        15.0),
    # a warrant conversion: the 75% balance of the same step's exercise price is a component (fresh4 #20, #57)
    "conversion_75pct": (
        "Disclosure under Regulation 30 - Conversion of equity warrants into equity shares. We hereby inform you "
        "that the Board of Directors of the Company through Circular Resolution on today i.e., Tuesday, 29th "
        "April, 2025, inter alia, approved the allotment of 28,00,000 (Twenty-Eight Lakhs) Equity Shares having "
        "Face value of Rs. 10/- each at an issue price of Rs. 25/- (Rupees Twenty-Five Only) (including a premium "
        "of Rs. 15 per share) fully paid up upon exercising the option available with the Share Warrant Holder to "
        "convert 28,00,000 (Twenty-Eight Lakhs) Convertible Warrants: “The allotment has been made for cash, "
        "upon the receipt of the remaining exercise price of Rs. 15/- per warrant (being an equivalent amount to "
        "75% of the Warrant exercise price of Rs. 25/- per warrant) aggregating to Rs. 5,25,00,000/- (Rupees Five "
        "Crores Twenty Five Lakhs Only).” In this regard the details are enclosed herewith in Annexure I. "
        "Post allotment of securities - Outcome of the subscription, issue price, number of allottees. Allotment "
        "of 28,00,000 Equity shares of face value Rs. 10/- each fully paid up at a premium of Rs. 15/-, "
        "aggregating to Rs. 7,00,00,000/- in the ratio of 1:1 - One Equity share for every warrant exercised. "
        "Name of Allottees Category Number of Warrants converted into Equity Shares Total Consideration Received "
        "(75%) (Amount in Rs.)",
        7.0),
    # a QIP whose aggregate is printed in millions; the pre-issue paid-up capital is not part of it (fresh4 #54)
    "qip_millions": (
        "Outcome of the Board Meeting held today i.e. August 16, 2024 for the purpose of allotment of equity "
        "shares pursuant to QIP. approved the issue and allotment of 1,06,95,187 Equity Shares of face value of "
        "₹ 5/- each, to eligible QIBs at the issue price of ₹ 935.00/- per Equity Share including a premium of "
        "₹ 930.00/- per Equity Share, aggregating to ₹ 10,000.00 million (Rupees Ten Thousand Million Only), "
        "pursuant to the QIP. Pursuant to the allotment of Equity Shares under the QIP, the paid-up equity share "
        "capital of the Company stands increased from ₹ 602.83 million consisting of 12,05,65,216 Equity Shares "
        "of face value of ₹ 5/- each to ₹ 656.30 million consisting of 13,12,60,403 Equity Shares of face value "
        "of ₹ 5/- each.",
        1000.0),
    # a board approval: the past year's QIP is background, not this step's enabling resolution (fresh4 #32)
    "enabling_resolution": (
        "Outcome of Board Meeting. The Board of Directors of the Bank at its meeting held today has inter-alia "
        "considered and approved the following: To seek shareholders’ approval in the ensuing Annual General "
        "Meeting for an enabling resolution to raise capital through QIP route to the tune of Rs.500 crore "
        "(including premium). Please note our Bank has been getting such approvals from the shareholders since "
        "the FY 2009 and it is only in the FY 2014-15, the Bank exercised the approval obtained and raised "
        "capital through QIP to the tune of Rs.350 crore.",
        500.0),
}


@pytest.mark.parametrize("case", list(R5_AMOUNTS))
def test_t242_r5_raise_step_amount_is_this_step_only(case: str) -> None:
    text, expected = R5_AMOUNTS[case]
    amount, how = fe.raise_step_amount(text)
    assert amount == pytest.approx(expected), (case, amount, how)
    assert how, case


def test_t242_r5_a_bundled_board_approval_still_adds_its_two_instruments() -> None:
    # two instruments, one board approval, two printed totals: the filing is one event worth both (round 4 #15)
    amount, _how = fe.raise_step_amount(
        "Outcome of the Board Meeting. The Board has approved the issue of equity shares for an amount of "
        "Rs. 92,39,01,888 on a preferential basis. The Board has also approved the issue of up to 30,24,00,000 "
        "warrants, each convertible into one equity share, for an amount of Rs. 30,24,00,000 on a preferential basis.")
    assert amount == pytest.approx(92.390188 + 30.24, rel=1e-6)


@pytest.mark.parametrize("title,text,expected", [
    # a committee that allotted the NCDs completed the allotment whatever the subject line says (round 5 #1)
    ("Allotment of Non Convertible Debentures",
     "In continuation to our outcome dated June 11, 2024, we wish to inform that, the Finance Committee of the "
     "Board of Directors in their meetings held today, allotted 300 senior, secured, unrated, unlisted, redeemable "
     "Non-convertible debentures (NCDs) of a face value of Rs. 10,00,000 each, aggregating to Rs. 30,00,00,000.",
     "allotment"),
    # "considered and approved the allotment of N shares" is the completed allotment (round 5 #23, #49)
    ("Please find enclosed file having details of allotment of securities",
     "the Board through circular resolution passed on November 05, 2026, has inter-alia considered and approved "
     "the allotment of 1,19,99,847 Equity Shares at an Issue price of INR 125 per Equity Share, aggregating to "
     "INR 149,99,80,875, pursuant to the Issue.",
     "allotment"),
    # a board that approved only the draft postal ballot notice has not raised anything yet (round 5 #53)
    ("Pursuant to Regulation 30 read with Part A of Schedule III, the Board of Directors at its meeting held today",
     "Sub.: Outcome of the Board Meeting held on Tuesday, July 28, 2026. 5) Approved the draft Postal Ballot "
     "Notice for seeking approval of the shareholders of the Company for the following matters: a. Approval for "
     "raising capital by way of Qualified Institutions Placement(s) to eligible investors through issuance of "
     "equity shares up to Rs. 600 crore.",
     "proposed"),
    # a board outcome that approved the issue and only convenes the EGM is an approval (round 5 #6, #33)
    ("Outcome of Board Meeting for raising of Funds by way of Issuance of Equity Shares by way of QIP",
     "This is with reference to our letter dated February 24, 2026, we wish to inform you that the Board of "
     "Directors of the Company, at its meeting held today, has inter-alia considered and approved the following "
     "matters: (i) Raising of funds by way of issuance of equity shares, for an aggregate amount not exceeding "
     "₹ 300 Crores; (ii) The Notice of Extraordinary General Meeting to seek approval of the shareholders for the "
     "aforesaid issuance and ancillary actions.",
     "approval"),
    # an exchange in-principle approval is an approval, not the listing (round 5 #7)
    ("Intimation of Inprinciple approval from the Stock Exchanges for issue of 4606294 Equity Shares of Rs.10 "
     "each on Preferential basis",
     "We are happy to inform you that, we have been granted In-principle approval from BSE Limited for issue of "
     "46,06,294 equity shares of Rs. 10 each at a price of Rs. 143/- per equity share on a preferential basis.",
     "approval"),
    # a listing approval is the step after the allotment
    ("Listing approval for the equity shares issued under the qualified institutions placement",
     "We wish to inform you that the Company has received the listing approval from the Stock Exchanges for the "
     "equity shares issued under the qualified institutions placement of Rs. 100 Crore.",
     "listing"),
])
def test_t242_r5_raise_stage_map(title: str, text: str, expected: str) -> None:
    row = _row(fe.event_rows(_doc(title, text))[0], "fund_raise")
    assert row["raise_stage"] == expected


@pytest.mark.parametrize("title,text", [
    # the subject is a subsidiary that allotted its own rights shares: the listed company issued nothing (#19)
    ("As Enclosed",
     "Pursuant to Regulation 30 of the Listing Regulations, this to inform you that a company Private Limited "
     "(\u201cSHIPL\u201d), Subsidiary of the listed company (\u201cthe Company\u201d), has on 30th March, 2026, allotted "
     "61,728 equity shares of face value of Rs. 100/- each at an issue price of Rs. 838.57/- per share "
     "aggregating to a total consideration of Rs. 5,17,63,249/-, by way of rights issue to the existing "
     "shareholder of SHIPL. Consequent to the said allotment, the Company's shareholding in SHIPL stands "
     "diluted from 98.28% to 68.04% of the total paid-up share capital."),
    # an exchange advisory on a warrant lock-in lapse is not an issuance (#21)
    ("Disclosure under Regulation 30 of SEBI (Listing Obligations and Disclosure Requirements) Regulations, 2015",
     "This is in relation to warrants issued by the Company up to 60,00,000, aggregating up to Rs. 127,23,00,000, "
     "on a preferential basis. Subsequently, certain warrants issued to the warrant holders matured and could "
     "not be kept under lock-in as per the prescribed time period. Basis the above, the Company has received an "
     "advisory letter from National Stock Exchange of India Limited dated November 13, 2024, for the warrants "
     "that could not be kept under lock-in and advised the Company to be careful in the future."),
    # "fund raising through debt" names no security: nothing was issued (#43)
    ("The Board of Directors at its meeting held on 15th January, 2025 has considered Capex Plan and Order intake",
     "The Board has approved capex plan of Rs 326.6 Crore to increase the manufacturing capacity of the existing "
     "plants. The Board also approved fund raising through debt upto Rs 236.6 Crore to fund the capex plan. The "
     "order intake for the half year ended 30th September, 2024 stands at Rs. 2,248 Crore while the total order "
     "book stood at Rs. 10,358 Crore."),
])
def test_t242_r5_not_an_issuance(title: str, text: str) -> None:
    assert not [row for row in fe.event_rows(_doc(title, text))[0] if row["kind"] == "fund_raise"]


def test_t242_r5_a_press_release_repeating_an_allotment_folds() -> None:
    allotment = _doc(
        "Outcome of the circular resolution passed by the Board of Directors on November 05, 2026",
        "the Board through another circular resolution passed on November 05, 2026, has inter-alia considered and "
        "approved the allotment of 1,19,99,847 Equity Shares at an Issue price of INR 125 per Equity Share, "
        "aggregating to INR 149,99,80,875, pursuant to the Issue.",
        symbol="AAA", doc_key="allotment", filing_date="2026-11-06", known_at="2026-11-06T09:00:00",
    )
    release = _doc(
        "PLEASE FIND ENCLOSED PRESS RELEASE DATED 05.11.2026 FOR QIP",
        "Sub: Press Release. enclosed is Press Release dated 5th November, 2026, titled \u201cSUCCESSFULLY RAISES "
        "RS. 150 CRORE THROUGH QIP, ISSUE FULLY SUBSCRIBED\u201d. The company has successfully raised \u20b9150 crore "
        "through a Qualified Institutional Placement (QIP), with the issue fully subscribed.",
        symbol="AAA", doc_key="release", filing_date="2026-11-06", known_at="2026-11-06T10:00:00",
    )
    rows = fe.event_rows(allotment)[0] + fe.event_rows(release)[0]
    amends: list[dict[str, Any]] = []
    kept = [row for row in fe._fold_same_raise(rows, amends) if row["kind"] == "fund_raise"]
    assert [row["doc_key"] for row in kept] == ["allotment"]
    assert [(a["doc_key"], a["amends"]) for a in amends] == [("release", "allotment")]


def test_t242_r5_a_notice_and_a_later_step_do_not_fold() -> None:
    board = _doc(
        "Outcome of Board Meeting",
        "The Board of Directors transacted: Raising of funds by way of issuance of equity shares for an aggregate "
        "amount not exceeding Rs. 400 Crores by way of qualified institutions placement (QIP).",
        symbol="AAA", doc_key="board", filing_date="2026-09-19", known_at="2026-09-19T10:00:00",
    )
    notice = _doc(
        "Notice of Postal Ballot",
        "Please find enclosed a copy of the Postal Ballot Notice seeking approval of the members of the Company "
        "for raising of funds by way of issuance of equity shares for an amount not exceeding Rs. 400 Crore "
        "through a qualified institutions placement.",
        symbol="AAA", doc_key="notice", filing_date="2026-09-26", known_at="2026-09-26T10:00:00",
    )
    allotment = _doc(
        "Outcome of the Board Meeting",
        "We wish to inform you that the Company has allotted 4,00,00,000 equity shares of face value of Rs. 10/- "
        "each at an issue price of Rs. 100/- per share, aggregating to Rs. 400 crore, pursuant to the qualified "
        "institutions placement.",
        symbol="AAA", doc_key="allotment", filing_date="2026-09-24", known_at="2026-09-24T10:00:00",
    )
    rows = fe.event_rows(board)[0] + fe.event_rows(notice)[0] + fe.event_rows(allotment)[0]
    amends: list[dict[str, Any]] = []
    kept = [row for row in fe._fold_same_raise(rows, amends) if row["kind"] == "fund_raise"]
    assert [row["doc_key"] for row in kept] == ["board", "notice", "allotment"]
    assert amends == []


# ---- T-242 round 6: the 8 wrong rows of the 60-row order_win audit ------------------------------------
def test_t242_r6_an_l1_only_intimation_is_unverified_but_a_received_award_stays() -> None:
    # fresh audit #7 (EMSLIMITED c315): the subject says L1 status, no LoA is received.
    jal = _doc(
        "EMS Limited has informed the exchange about the L1 Status awarded by UP Jal Nigam (Urban)",
        "June 17, 2025 Subject: Intimation of receipt of Lowest Bidder(L-1) status awarded by UP Jal Nigam (Urban) - "
        "Disclosure under Regulation 30 of the Securities and Exchange Board of India (Listing Obligations and "
        "Disclosure Requirements) Regulations, 2015, as amended (\u201cSEBI Listing Regulations\u201d) by EMS Limited "
        "(the \u201cCompany\u201d) Dear Sir/Ma\u2019am, Pursuant to the Regulation 30 read with schedule III of the "
        "Securities and Exchange Board of India (Listing Obligations and Disclosure Requirements) Regulations 2015, "
        "and SEBI circular no. GIR/CFD/CFD-PoD-I/P/CIR/2023/123 dated July 13,2023 (as amended); we are pleased to "
        "inform you that EMS Limited has receipt the lowest bidder (L-1) status awarded by UP Jal Nigam (Urban). The "
        "estimated order value (excluding GST) is approximately Rs. 18381.49 lakhs (Rupees Eighteen Thousand Three "
        "Hundred Eighty-one lakhs and Forty-Nine Thousand only). The details of the works are as under: S. No "
        "Particulars Details 1. Name(s) of the entity awarding the order [s) /Contract(s) UP Jal Nigam (Urban) 2. "
        "Significant terms and conditions of order(s) / contract(s) awarded in brief As per Contract 3. Whether "
        "order(s) /contract(s) have been awarded by domestic /international entity Domestic Entity (L-1) 4. Nature "
        "of order(s) /contract(s) Construction of various components for Fatehpur Sewerage and sewage treatment "
        "scheme Zone-1 Distt. Fatehpur. 5. Whether domestic or international Domestic Entity 6. Time period by "
        "which the order(s)/contract(s) is to executed 24 months 7. Broad consideration or size of the order(s) "
        "contract(s) Order value (excluding GST) of Rs. 18381.49 lakhs (Rupees Eighteen Thousand Three Hundred "
        "Eighty-one lakhs and Forty-Nine Thousand only).",
    )
    jal_row = _row(fe.event_rows(jal)[0], "order_win")
    assert (jal_row["status"], jal_row["why"]) == ("unverified", "l1_only")
    assert jal_row["amount_inr_cr"] == pytest.approx(183.8149)

    # audit #26: the LoA is received; a lowest-bidder mention elsewhere does not unverify it.
    kolkata = _doc(
        "Intimation of receipt of Letter of Acceptance (LOA) From the office of the Kolkata Municipal Corporation",
        "Subject: Intimation of receipt of Letter of Acceptance (LOA) from the office of The Kolkata Municipal "
        "Corporation - Disclosure under Regulation 30 of the SEBI (LODR) Regulations, 2015. Pursuant to Regulation "
        "30, we are pleased to inform you that EMS Limited has received a Letter of Acceptance (LOA) from the office "
        "of The Kolkata Municipal Corporation for the work of Pollution Abatement. The order value is approximately "
        "Rs.78197.91 Lakhs. The Company had earlier been declared the L-1 bidder for this project.",
    )
    kolkata_row = _row(fe.event_rows(kolkata)[0], "order_win")
    assert kolkata_row["status"] == "verified"
    assert kolkata_row["amount_inr_cr"] == pytest.approx(781.9791)

    # fresh3 #28: the LoA is received first and the press release later says "emerged as the lowest bidder".
    work_order = _doc(
        "We are please to inform you that the KMEW has received a work order from New Mangalore Port Authority "
        "(NMPA) for Maintenance Dredging at New Mangalore Port for the period of 3 years.",
        "Pursuant to Regulation 30 read with Schedule III of the Listing Regulations, we are pleased to inform you "
        "that Knowledge Marine & Engineering Works Limited has received a Work Order from New Mangalore Port "
        "Authority (NMPA). KMEW has secured its largest dredging order by receiving a Letter of Acceptance from NMPA "
        "valued at approximately Rs.303.17 crore. KMEW emerged as the lowest bidder, with its bid approximately "
        "10.16% below the competitor.",
    )
    assert _row(fe.event_rows(work_order)[0], "order_win")["status"] == "verified"


def test_t242_r6_a_subsidiary_order_is_labelled_and_keeps_its_status() -> None:
    cases = [
        # audit #24 (MCLOUD c22)
        (_doc("Attached Herewith the Regulation 30 for receipt of order",
              "Pursuant to Regulation 30 read with Schedule III of the SEBI (LODR) Regulations, 2015, we wish to "
              "inform that Provigil Surveillance Limited, a wholly owned subsidiary of the Company, has received a "
              "Letter of Acceptance (LOA) from South Western Railway, Hubli Division, for an aggregate contract "
              "value of INR 4.31 Crore Approx."),
         "Provigil Surveillance Limited", 4.31),
        # the printed "subsdiary" typo in a title
        (_doc("MAGELLANIC CLOUD LIMITED VIDE ITS SUBSDIARY SCANDRON PRIVATE LIMITED HAS SECURED ITS FIRST MAJOR "
              "LOGISTICS DRONE ORDER",
              "We wish to inform you that our subsidiary Scandron Private Limited has secured its first major "
              "logistics drone order from an Indian robotics firm, valued at Rs 43 crore."),
         "SCANDRON PRIVATE LIMITED", 43.0),
        # audit #42 (EFCIL c69)
        (_doc("Press Release on New Big Contract of Interior and Fit-out worth INR 57 Crore.",
              "In compliance with Regulation 30 of the SEBI (LODR) Regulations, 2015, we are pleased to inform you "
              "of a major development involving EFC Limited, our wholly-owned unlisted subsidiary. EFC Limited has "
              "been awarded an Interior and Fit-out Contract worth Rs. 57 crore from a leading MNC."),
         "EFC Limited", 57.0),
        # audit #49 (PACEDIGITK c312)
        (_doc("Award of Contract to Material Subsidiary- Lineage Power Private Limited by Advait Greenergy Private "
              "Limited.",
              "We would like to bring to your kind attention that M/s. Lineage Power Private Limited, a Material "
              "Subsidiary of the Company, has received order worth Rs. 997.10 Million (including taxes) from M/s. "
              "Advait Greenergy Private Limited."),
         "Lineage Power Private Limited", 99.71),
        # audit #58 (AURIONPRO c33)
        (_doc("Aurionpro announces one of its largest US markets wins with USD 33 million fintech engagement",
              "PRESS RELEASE Aurionpro Solutions Ltd Ninad Kelkar Ninad.kelkar@aurionpro.com AZN Partners "
              "Publicrelations Pvt Ltd Harry Pinto harry.pinto@aznpartners.com For further information, please "
              "contact: Aurionpro announces one of its largest US market wins with USD 33 million fintech "
              "engagement The significant order win from a leading US-based digital insurance payments platform "
              "will see Aurionpro deliver advanced AI-led technology solutions Mumbai/USA, May 21, 2026 - "
              "Aurionpro, through its US-based subsidiary Aurionpro Fintech Inc., is pleased to announce its "
              "largest order win in the US market with the signing of a strategic three-year engagement with one "
              "of the leading fintech platforms in the United States specializing in digital insurance payments. "
              "The engagement is expected to generate more than USD 33 million in revenue over the contract "
              "period."),
         "Aurionpro Fintech Inc", 33.0),
    ]
    for doc, name, amount in cases:
        row = _row(fe.event_rows(doc)[0], "order_win")
        assert row["entity_scope"] == "subsidiary", (name, row)
        assert row["detail"] == f"subsidiary: {name}", (name, row["detail"])
        assert row["status"] == "verified", (name, row)
        assert (row["amount_inr_cr"] if row["amount_inr_cr"] is not None else row["amount_usd_mn"]) \
            == pytest.approx(amount)

    # the filing names no subsidiary, only "a subsidiary": the scope stays the company (Wolf, 25 Nov).
    unnamed = _doc("Attached is the purchase order received by subsidiary company",
                   "We wish to inform you that the subsidiary has received a Purchase Order worth USD 4.70 million "
                   "(~INR 39 crores) for supply of equipment. The order is to be executed within one year.")
    assert _row(fe.event_rows(unnamed)[0], "order_win")["entity_scope"] == "company"

    # a third party's subsidiary is the customer, not the issuer's subsidiary (CAPACITE's TenX LOI).
    third_party = _doc(
        "Receipt of Letter of intent of Rs. 220 crore from TenX Realty Limited, (a step-down subsidiary of "
        "Raymond Limited)",
        "We wish to inform you that Capacit'e Infraprojects Limited has received Letter of Intent (LOI) from TenX "
        "Realty Limited, (a step-down subsidiary of Raymond Limited), for a total contract value of Rs. 220 crore.",
    )
    assert _row(fe.event_rows(third_party)[0], "order_win")["entity_scope"] == "company"


def test_t242_r6_a_press_release_headline_is_not_the_customer() -> None:
    # audit #54 (PACEDIGITK c312): the page-2 headline ran into the body name; the body names BSNL.
    doc = _doc(
        "Press Release.",
        "Pursuant to regulation 30 read with Schedule III of the SEBI (LODR) Regulations, 2015, please find "
        "enclosed herewith the Press Release dated January 01, 2026, for receipt of advance purchase order worth "
        "Rs. 94.35 Crore from Bharat Sanchar Nigam Limited (BSNL) to Lineage Power private limited a material "
        "Subsidiary of the Pace Digitek Limited. PRESS RELEASE Pace Digitek's Subsidiary Lineage Power Secures "
        "Massive Rs. 94.35 Crore Strategic Order from BSNL to Power India's Telecom Future BANGALORE - January 01, "
        "2026 - Pace Digitek Limited today announced a landmark achievement as its material subsidiary, Lineage "
        "Power Private Limited, has received a prestigious Order from Bharat Sanchar Nigam Limited (BSNL).",
    )
    row = _row(fe.event_rows(doc)[0], "order_win")
    assert row["customer"] == "Bharat Sanchar Nigam Limited (BSNL)"
    assert row["entity_scope"] == "subsidiary"
    assert "Lineage Power" in (row["detail"] or "")


# ---- T-242 round 7: structural customer, subsidiary, value and duplicate rules ----------------------------
def test_t242_r7_customer_rejects_fragments_segments_countries_headers_and_prefers_annexure() -> None:
    # Single generic words ('Public', 'Office') in a truncated title yield to the page-2 annexure awarder.
    annex_over_title = _doc(
        "Pursuant to Regulation 30, we submit that Company has received an order from Public ....",
        "The Company is pleased to announce that it has received an LOA for consultancy services and total order "
        "value of the project is Rs. 1,74,24,057/-. Annexure A: Name of the target entity details in brief such "
        "as size, turnover, etc. Public Works Roads Department, Government of Assam Whether the acquisitions "
        "would fall within related party transactions No Total cost or contract amount involved Rs. 1,74,24,057/-",
        symbol="AAA",
    )
    assert _row(fe.event_rows(annex_over_title)[0], "order_win")["customer"] == (
        "Public Works Roads Department, Government of Assam"
    )

    # 'Name of the entity awarding' stops before 'Whether the acquisitions' so 'Office' in title is replaced.
    office_annex = _doc(
        "We hereby submit that Company has received an order from Office ....",
        "The Company has received a work order worth Rs. 4,92,93,508/-. Annexure A: Name of the entity awarding "
        "the order(s)/contract(s); OFFICE OF THE EXECUTIVE ENGINEER P.W (WB) Project Division, Chhatrapati "
        "Sambhajinagar Whether the acquisitions would fall within related party transactions No",
        symbol="AAA",
    )
    assert _row(fe.event_rows(office_annex)[0], "order_win")["customer"] == (
        "OFFICE OF THE EXECUTIVE ENGINEER P.W (WB) Project Division, Chhatrapati Sambhajinagar"
    )

    # A company name containing 'Promoters' ('Yucca Promoters LLP') is not rejected by promoter boilerplate.
    promoters_llp = _doc(
        "Company receives Letter of Intent from Yucca Promoters LLP, Pune amounting to Rs. 85.43 Crores",
        "a) Name of the entity awarding the order(s)/contract(s); Yucca Promoters LLP, Pune "
        "g) Broad consideration or size of the order(s)/contract(s) Rs. 85.43 Crores (Including GST).",
        symbol="AAA",
    )
    assert _row(fe.event_rows(promoters_llp)[0], "order_win")["customer"] == "Yucca Promoters LLP"

    # A table header prefix ('Redevelopment(s) ...') is stripped/rejected in favour of the named entity.
    header_prefix = _doc(
        "Letter of Intent for Redevelopment of building amounting to Rs. 161.18 Crore",
        "The Company has received Letter of Intent (LOI) from MSEB holding Company Limited Amounting to Rs.161.18 "
        "Crore. a) Name of the entity awarding the order(s)/contract(s)/Redevelopment(s) MSEB Holding Company Limited "
        "b) Significant terms Not applicable g) Broad consideration Rs. 161.18 Crores",
        symbol="AAA",
    )
    assert _row(fe.event_rows(header_prefix)[0], "order_win")["customer"] == "MSEB Holding Company Limited"

    # Reject single generic words, own segments ('our ...'), bare countries/regions, datelines, and headers.
    for bad in ("Public", "Office", "Government", "Department", "Client",
                "our T&D business", "its infrastructure division", "the Company's EPC business",
                "Malaysia", "Middle East region",
                "Top US Institutional Supplier Mumbai - 17th May",
                "Redevelopment(s) Foo Bar Limited", "Appointment of Agency"):
        assert fe._clean_party(bad) is None, bad

    # Own segment and bare country orders leave customer empty instead of storing a wrong customer.
    own_seg = _doc(
        "PRESS RELEASE - COMPANY AWARDED NEW ORDERS OF RS. 2,273 CRORES",
        "The Company has secured new orders of ₹ 2,273 Crores. Nearly 56% of order intake till date is from "
        "our T&D business.",
        symbol="AAA",
    )
    assert _row(fe.event_rows(own_seg)[0], "order_win")["customer"] is None

    country = _doc(
        "Company has informed the exchange about receipt of order.",
        "The Company received its maiden overseas contract in the Rail and Metro segment from Malaysia for the "
        "Retrofit of the Mass Rapid Transport System, valued at USD 1 million.",
        symbol="AAA",
    )
    assert _row(fe.event_rows(country)[0], "order_win")["customer"] is None


def test_t242_r7_subsidiary_captures_quoted_and_multiple_names_and_rejects_units() -> None:
    # Quoted name before 'wholly owned subsidiary' (#30, #55).
    quoted = _doc(
        "General Business Updates",
        "We wish to inform you that \u201cKRN HVAC Products Private Limited\u201d, a wholly owned subsidiary of "
        "the Company has received an export order. Estimated Single Order Value: Approx. INR 55 Crore.",
        symbol="KRN",
    )
    r_quoted = _row(fe.event_rows(quoted)[0], "order_win")
    assert r_quoted["entity_scope"] == "subsidiary"
    assert r_quoted["detail"] == "subsidiary: KRN HVAC Products Private Limited"

    # Multiple subsidiaries before 'Subsidiaries of <Parent>' (#14, #49) and after '(material|step-down) subsidiaries'.
    multi_before = _doc(
        "Receipt of new orders",
        "We hereby inform you that Premier Energies International Private Ltd. and Premier Energies Photovoltaic "
        "Private Ltd., both subsidiaries of Premier Energies Limited, have received and accepted multiple orders "
        "amounting to a total value of INR 765 crore.",
        symbol="PREMIERENE",
    )
    r_mb = _row(fe.event_rows(multi_before)[0], "order_win")
    assert r_mb["entity_scope"] == "subsidiary"
    assert r_mb["detail"] == (
        "subsidiary: Premier Energies International Private Ltd; Premier Energies Photovoltaic Private Ltd"
    )

    multi_after = _doc(
        "Receipt of order by subsidiaries",
        "Our wholly owned material subsidiaries, Alpha Tech GmbH and Beta Energy LLP, have received an order "
        "worth Rs. 120 Crore from Northern Railway.",
        symbol="AAA",
    )
    r_ma = _row(fe.event_rows(multi_after)[0], "order_win")
    assert r_ma["entity_scope"] == "subsidiary"
    assert r_ma["detail"] == "subsidiary: Alpha Tech GmbH; Beta Energy LLP"

    # Capacity/unit tokens ('MW DC') never pass as a subsidiary name; the named subsidiary after marker wins (#60).
    unit_trap = _doc(
        "Bagging of order 20 MW AC/ 28.1 MW DC BY OUR SUBSIDIARY SUNPOWER ENERGY RESOURCE PRIVATE LIMITED "
        "(FORMERLY SUNPOWER LLP)",
        "Our Subsidiary Sunpower Energy Resource Private Limited (formerly known as Sunpower LLP) has been awarded "
        "20MWAC /28.1 MW DC EPC basis Letter of Intent by Shree Warana SSK Ltd. Broad consideration: Rs. 69 Crores.",
        symbol="AAA",
    )
    r_unit = _row(fe.event_rows(unit_trap)[0], "order_win")
    assert r_unit["entity_scope"] == "subsidiary"
    assert "MW" not in r_unit["detail"] and "DC" not in r_unit["detail"]
    assert "SUNPOWER ENERGY RESOURCE PRIVATE LIMITED" in r_unit["detail"]


def test_t242_r7_value_jv_share_past_delivered_and_quarterly_rollup() -> None:
    # JV filing printing gross value and company's 70% share stores the share and notes gross value (#23).
    jv_doc = _doc(
        "We submit that Company has received an order from Maharashtra ....",
        "The Monarch Surveyors and Engineering Consultants Limited has received Letter of Acceptance and the "
        "project have been awarded under a Joint Venture (JV), in which the Monarch Surveyors and Engineering "
        "Consultants Limited holds a 70% partnership stake and total order value of the project is Rs. "
        "23,53,47,000/-. As per MOU signed with a third-party, share of Monarch is 70% of the total order value. "
        "Accordingly, Monarch\u2019s order value is Rs. 16,47,42,900/-. Annexure A: Name of the target entity "
        "details in brief such as size, turnover, etc. Maharashtra Rural Roads Development Association Whether the "
        "acquisitions would fall within related party transactions No",
        symbol="MSECL",
    )
    r_jv = _row(fe.event_rows(jv_doc)[0], "order_win")
    assert r_jv["amount_inr_cr"] == pytest.approx(16.4743)
    assert r_jv["value_total"] == pytest.approx(23.5347)
    assert r_jv["share_pct"] == pytest.approx(70.0)
    assert r_jv["customer"] == "Maharashtra Rural Roads Development Association"
    assert "23.5347" in r_jv["detail"]

    # Partner's 60% share in a JV is skipped in favour of the issuer's 40% share.
    partner_jv = _doc(
        "Receipt of Letter of Acceptance from NHSRCL",
        "M/s. Partner-Issuer (JV) has received a Letter of Acceptance from NHSRCL for a total contract value of "
        "Rs. 384.72 crores. In the aforementioned Joint Venture, Partner Private Limited holds 60% share as the "
        "Lead Partner, while Issuer Infraprojects Limited holds a 40% share.",
        symbol="ISSUER",
    )
    r_pjv = _row(fe.event_rows(partner_jv)[0], "order_win")
    assert r_pjv["share_pct"] == pytest.approx(40.0)
    assert r_pjv["amount_inr_cr"] == pytest.approx(153.888)
    assert r_pjv["value_total"] == pytest.approx(384.72)

    # Past delivered/executed/earlier/previous order value is never chosen over the new order's value (#28).
    past_order = _doc(
        "Company has received new export order worth US $ 106673 from existing top institutional supplier",
        "The company has executed & delivered Export Order valued at US$ 50,000 (approximately ₹41.50 Lakhs), "
        "another export order valued at $ 197,793 (approximately ₹ 165 Lakhs) which shall be fully executed and "
        "delivered by end of July. Now Company has received an additional export order worth $ 106,673 "
        "(approximately ₹ 89 Lakhs).",
        symbol="AAA",
    )
    r_past = _row(fe.event_rows(past_order)[0], "order_win")
    assert r_past["amount_inr_cr"] == pytest.approx(0.89)

    # Quarterly roll-up ('orders worth X in Q2 FY 2027' / 'aggregating to X in the July-September quarter') vetoed.
    rollup = _doc(
        "Solar Co Secures New Orders Worth Rs. 4,001 Crore in Q2 FY 2027",
        "Solar Co Limited has received orders aggregating to ₹4,001 crores in the July\u2013September quarter. "
        "These orders come from a mix of major power producers and EPC companies.",
        symbol="AAA",
    )
    assert not [r for r in fe.event_rows(rollup)[0] if r["kind"] == "order_win"]


def test_t242_r7_press_release_duplicate_within_10_days_folds_with_amend() -> None:
    # Reg 30 filing with named customer + press release 2 days later with no customer named (#20 -> #38).
    reg30 = _doc(
        "Intimation of Receipt of Purchase order under Regulation 30",
        "Name of the entity awarding the order(s)/contract(s) Premia Solutionz Private Limited "
        "7. Broad consideration or size of the order(s)/contract(s) Approximately ₹6 Crore.",
        symbol="HIGHNESS", doc_key="reg30", filing_date="2026-09-26", known_at="2026-09-26T13:01:00",
    )
    pr = _doc(
        "Press Release pursuant to Regulation 30 of SEBI (LODR) Regulations, 2015.",
        "Subject: Press Release \u2013 Company Secures Approx. ₹6 Crore Order. "
        "Company has secured an approx ₹6 crore order from a domestic customer. Order Value: Approx ₹6.00 Crore.",
        symbol="HIGHNESS", doc_key="pr", filing_date="2026-09-28", known_at="2026-09-28T18:06:00",
    )
    rows = fe.event_rows(reg30)[0] + fe.event_rows(pr)[0]
    assert len(rows) == 2
    amends: list[dict[str, Any]] = []
    kept = [r for r in fe._fold_same_order(rows, amends) if r["kind"] == "order_win"]
    assert [r["doc_key"] for r in kept] == ["reg30"]
    assert [(a["doc_key"], a["amends"]) for a in amends] == [("pr", "reg30")]

    # A valued press release must never fold into an earlier valueless row.
    empty_prior = _doc(
        "Receipt of New Order from Apollo Healthco Limited",
        "We have received a purchase order from Apollo Healthco Limited.",
        symbol="VEER", doc_key="empty", filing_date="2024-04-01", known_at="2024-04-01T15:00:00",
    )
    valued_pr = _doc(
        "Press Release of New order received from Apollo Healthco Limited",
        "Press Release: Company secures New order worth ₹ 57.36 Lakhs from Apollo Healthco Limited.",
        symbol="VEER", doc_key="valued", filing_date="2024-04-02", known_at="2024-04-02T11:00:00",
    )
    rows2 = fe.event_rows(empty_prior)[0] + fe.event_rows(valued_pr)[0]
    amends2: list[dict[str, Any]] = []
    kept2 = [r for r in fe._fold_same_order(rows2, amends2) if r["kind"] == "order_win"]
    assert len(kept2) == 2 and amends2 == []
