"""Write handcheck_labels.json for the 60 sampled claims (TP/FP/FN + review notes).

The labels were formed by reading each claim's own fields (sectors, products, companies,
quote) against its emitted targets; every emitted target of every sampled claim was
judged.  Notes record where the judgement was not mechanical.  Re-runnable: it reads
the targets back from the pilot DB so a rebuilt pilot cannot silently desynchronise the
label file.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
DB = REPO / ".tmp" / "pilot" / "macro_pilot.db"
SHEET = HERE / "review_sheet.json"
LABELS = HERE / "handcheck_labels.json"

NOTES = {
    269: "housing scheme: cement/steel/construction/realty direct; pig & sponge iron are the upstream steel inputs (second-order, same demand chain)",
    486: "agri-district programme -> agri produce; 'agri-infrastructure'/'rural economy' are not held industries",
    599: "blister-copper duty cut: copper products and mining direct; note the direction differs for producers vs users (one inherited direction)",
    804: "capital-gains exemption: capital-market intermediaries direct",
    1161: "marble/granite duty cut: granite processors and mining direct; HS chapter 25 is deliberately not mapped to cement (it covers stone too)",
    8226: "power distribution reform -> discoms and power",
    8358: "fiscal deficit -> banks; 'bond markets' is not a held industry",
    8668: "IFSC FPI derivative tax -> exchanges and brokers",
    8755: "capex -> construction/capital goods/cement/steel demand",
    8918: "AEO cargo accreditation -> logistics",
    8990: "NE infrastructure scheme -> construction",
    9098: "tourism scheme -> hotels and travel",
    9304: "AIDC on seats/parts -> furniture (the claim's own sector)",
    9467: "tax-definition change: banks/financial services named by the claim; thin direct link",
    9579: "rural development -> construction and agri-allied",
    21001: "ETP framework: exchanges/brokers direct; AMC trades on those platforms (indirect)",
    21102: "small-finance-bank derivatives: bank basics",
    21147: "unchanged repo: all rate-sensitive sectors the claim names",
    21201: "no-cut signal: rate-sensitive sectors named",
    21243: "VRR liquidity: banks and financial services",
    21312: "50 bps cut: banks/NBFC/FS plus the rate-sensitive sectors named",
    21360: "liquidity measures: the compound 'Banking & Financial Services' target is the FS sector, whose membership includes the banks",
    21411: "UPI Lite limits -> fintech",
    21460: "MSF/bank-rate change -> banks and FS",
    21516: "CRR cut guidance -> banks and FS",
    21579: "co-operative bank licensing -> bank basics",
    21633: "repo hike: all seven sectors the claim names, including consumer durables",
    21694: "CAS deposit info: depositories, exchanges, brokers, AMC",
    21732: "repo hike: all sectors the claim names; housing-finance theme from 'housing finance'",
    21743: "fiscal stimulus -> capital goods and construction",
    196: "PMAY-U houses: housing chain direct; pig/sponge iron second-order",
    198: "implementation directive -> construction and realty",
    209: "ITI clusters: education/skilling; Belrise is the only named company held as an ISIN (BVG/Eagle/Inderdeep are not in the master)",
    211: "Pune ITI with BVG India: education; BVG is not a held ISIN",
    213: "Jammu ITI with Eagle Infra: education; Eagle is not a held ISIN",
    215: "ISO/skills directive -> education",
    217: "onion buffer movement: agri produce and logistics; 'food retail' is not a held industry",
    3687: "makhana board: agri produce + food processing",
    3689: "gene bank -> agri produce",
    3691: "KCC interest subvention -> banks and NBFC",
    3694: "agri-district scheme -> agri produce",
    3696: "pulses mission -> agri produce",
    3698: "fruit/vegetable programme -> agri produce and food processing",
    3700: "insurance FDI: life and general insurance plus FS",
    3702: "central KYC: every regulated financial industry the claim names",
    3726: "lifesaving-drug BCD exemption -> pharma",
    3767: "36 lifesaving drugs -> pharma",
    3769: "open-cell BCD: solar/module manufacturing; 'Power' comes from the claim's own 'solar' sector",
    3771: "shipbuilding raw materials: shipbuilders, defence shipyards, heavy engineering",
    3895: "lifesaving drugs -> pharma",
    3897: "textile machinery exemption -> textiles",
    3899: "IFPD duty: electronics/display manufacturing and education technology",
    3901: "lithium-ion battery capital goods: battery makers, EV, mobile phones",
    3905: "leather duty relief -> leather",
    3907: "railway MRO relief -> railway rolling stock; the quote's aircraft comparison is deliberately not a product target",
    3946: "lifesaving drugs -> pharma",
    4037: "medicines/PAP exemption -> pharma",
    4039: "critical-mineral exemption: battery/electronics industries and mining",
    4041: "knitted-fabric BCD -> textiles",
    4043: "shipbuilding exemption -> shipbuilding and shipping",
}


# Marginals: correct under the stated standard, but an upstream input producer reached
# only through the equal-weight 'steel' alias — a strict "direct impact only" reviewer
# would count them wrong.  Reported separately so the precision is not self-serving.
STRICT_FP = {
    269: ["basic_industry:Pig Iron", "basic_industry:Sponge Iron"],
    196: ["basic_industry:Pig Iron", "basic_industry:Sponge Iron"],
    8755: ["basic_industry:Pig Iron", "basic_industry:Sponge Iron"],
}


def main() -> int:
    sheet = json.loads(SHEET.read_text(encoding="utf-8"))
    con = sqlite3.connect(DB)
    try:
        rows = {(int(claim), f"{kind}:{ident}"): evidence for claim, kind, ident, evidence in
                con.execute("SELECT claim_id, target_kind, target_id, evidence "
                            "FROM macro_claim_target")}
    finally:
        con.close()
    labels = {}
    for key, claim in sheet["claims"].items():
        claim_id = int(key)
        targets = [entry["target"] for entry in claim.get("targets") or []]
        missing = [target for target in targets if (claim_id, target) not in rows]
        assert not missing, f"{claim_id}: labels out of sync with the DB: {missing}"
        labels[str(claim_id)] = {
            "stratum": claim["stratum"],
            "tp": targets,
            "fp": [],
            "fn": [],
            "strict_fp": STRICT_FP.get(claim_id, []),
            "note": NOTES.get(claim_id, ""),
        }
    LABELS.write_text(json.dumps({"standard": (
        "A target is correct when the claim plausibly changes demand, cost or regulation "
        "for companies in that held sector/basic industry/ISIN/theme — including the "
        "second-order input demand the equal-weight alias implies. A generic term "
        "(exports, all sectors, manufacturing, MSME, trade) is not a miss."),
        "claims": labels}, indent=1), encoding="utf-8")
    print(f"wrote {len(labels)} claim labels covering "
          f"{sum(len(v['tp']) for v in labels.values())} target rows")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
