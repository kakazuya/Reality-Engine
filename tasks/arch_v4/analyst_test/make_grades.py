"""Hand grades for the 40 analyst-agent rows, with the fixed kill rule.

Every ``looked_up`` value was read separately from the pilot stores with SQL, not from
the agent's tool log.  Run once after ``recheck_numbers.py``; writes ``grades.jsonl``
and ``summary.json``.
"""
from __future__ import annotations

import json
import math
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNS = HERE / "runs"

G = [
    # qid, verdict, reason_code, cause, reason, looked_up, tool
    ("Q01", "CORRECT_NOT_IN_DATA", "DATA_GAP", "data_gap",
     "The FY25 annual report (known 2025-09-02) has no change-in-control disclosure; the only Clause 5A text in the store is the FY24 AR. The answer's negative finding is correct.",
     "FY25 AR chunk set: no 'Clause 5A' / 'impact the management or control'; FY24 AR chunk 57495 p167 carries the Clause 5A no-agreements text.",
     "SQL chunks_v3_pilot.db chunk/doc"),
    ("Q02", "CORRECT_NOT_IN_DATA", "DATA_GAP", "data_gap",
     "Only raw price.close is held (602.60 on 2023-09-29; 1481.90 on 2026-09-30); no split/dividend-adjusted atom exists. The answer correctly says the adjusted series is not in data.",
     "price.close 602.60 (2023-09-29) and 1481.90 (2026-09-30); raw CAGR 34.98% is computable but is not the asked adjusted measure.",
     "SQL fact_v4_pilot.db fact"),
    ("Q03", "WRONG", "MEASURE_NOT_ANSWERED", "reasoning",
     "Q1FY27 Note 5 is Employee benefits expense in the standalone results (30.54 / 2.20 / -2.40 Cr) and Net profit margin (5.56% / 4.50% / 6.26%, 'Refer note 5') in the consolidated ratio annexure. The answer calls Note 5 'Debenture redemption reserve: NA NA NA', a different table line. The geographic split is correctly reported absent.",
     "Standalone Note 5: 30.54, 2.20, -2.40 Cr; consolidated Note 5: net profit margin 5.56%, 4.50%, 6.26%; no geographic revenue split.",
     "SQL chunks_v3_pilot.db chunk (107528/107530/107557)"),
    ("Q04", "CORRECT_NOT_IN_DATA", "DATA_GAP", "data_gap",
     "JUBLINGREA's latest hold.pct is 2026-06-30 (public 53.79%); no Sep 2026 row exists. The answer correctly says Sep 2026 is not in data and gives the latest.",
     "hold.pct public 53.79% at 2026-06-30 (known 2026-07-15); no 2026-09-30 row.",
     "SQL fact_v4_pilot.db fact"),
    ("Q05", "RIGHT", "EXACT", "none",
     "Sep 2026 public shareholding is 40.11%, exactly the answer.",
     "hold.pct holder_class=public, 2026-09-30 = 40.11, known 2026-10-16.",
     "SQL fact_v4_pilot.db fact"),
    ("Q06", "WRONG", "MEASURE_NOT_ANSWERED", "reasoning",
     "The impact is computable from the held price series: WPIL closed 670.85 on 31 Jan 2025, 610.40 on 3 Feb (-9.0%) and 398.75 by 14 Feb (-40.6%). The answer says the held data has no quantified impact, which is false. The rolling tariff-news correlation is not held.",
     "price.close 670.85 (2025-01-31), 610.40 (2025-02-03), 398.75 (2025-02-14); no tariff-news series.",
     "SQL fact_v4_pilot.db fact"),
    ("Q07", "ILL_POSED", "PREMISE_FALSE", "premise",
     "GRASIM's segments are Cement, Chemicals, Cellulosic Fibres, Financial Services and Building Materials; it has no dairy business, so the 'dairy peers' premise is false. The answer correctly notes the premise does not apply.",
     "fin.segment_value dims: Cement, Chemicals, Cellulosic Fibres, Financial Services, Building Materials.",
     "SQL fact_v4_pilot.db fact"),
    ("Q08", "RIGHT", "EXACT", "none",
     "Sep 2026 promoter holding is 44.58%, exactly the answer.",
     "hold.pct promoter 44.58% at 2026-09-30, known 2026-10-16.",
     "SQL fact_v4_pilot.db fact"),
    ("Q09", "ILL_POSED", "PREMISE_FALSE", "premise",
     "POWERGRID reports Transmission, Consultancy and Telecom segments; it has no manufacturing facilities, so the premise is false. The answer says not in data.",
     "fin.segment_value segments: Transmission, Consultancy, Telecom.",
     "SQL fact_v4_pilot.db fact"),
    ("Q10", "RIGHT", "EXACT", "none",
     "Promoter holding 53.28% at 2026-09-30; total shares 181,410,000; the derived promoter count 96,655,248 = 0.5328 x 181,410,000. The answer gives both the total and the promoter count.",
     "hold.pct promoter 53.28% (2026-09-30, known 2026-10-17); price.shares_out 181,410,000 (2026-10-19); 0.5328 x 181,410,000 = 96,655,248.",
     "SQL fact_v4_pilot.db fact"),
    ("Q11", "RIGHT", "EXACT", "none",
     "Share count 103,477,000 and promoter holding 75.0% at 2026-09-30, exactly the answer.",
     "price.shares_out 103,477,000 (2026-10-19); hold.pct promoter 75.0% (2026-09-30, known 2026-10-10).",
     "SQL fact_v4_pilot.db fact"),
    ("Q12", "CORRECT_NOT_IN_DATA", "DATA_GAP", "data_gap",
     "No investor deck dated 2026-07-29 is held; the nearest is 2026-08-10. The answer correctly says not in data.",
     "doc table: no BOSCHLTD deck known 2026-07-29; nearest deck 2026-08-10.",
     "SQL chunks_v3_pilot.db doc"),
    ("Q13", "WRONG", "MEASURE_NOT_ANSWERED", "reasoning",
     "The question asks the capacity-expansion timeline. The answer returns a capex table and mixes deck vintages: 1,058->1,137 KTPA chlorine derivatives is from the Q3FY26 deck (10 Feb 2026), while the Q4FY26 deck (20 May 2026) it cites shows 996->1,075 KTPA and says ECH/CPVC 50 KTPA are under pre-commissioning. It omits the Lyocell mid-2027 timeline.",
     "Q4FY26 deck chunk 50321: 1,505->1,530 KTPA chlor-alkali; 996->1,075 KTPA chlorine derivatives; ECH/CPVC under pre-commissioning. Q3FY26 deck chunk 49178: 1,058->1,137; CPVC commissioning Q4FY26. Lyocell phase 1 55 KTPA commissioning mid-2027 (chunk 50317).",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q14", "RIGHT", "EXACT", "none",
     "YTD high 1,620.7 first reached 2026-06-25 and matched 2026-06-29, exactly the answer.",
     "price.high max 1620.7 on 2026-06-25 and 2026-06-29.",
     "SQL fact_v4_pilot.db fact"),
    ("Q15", "PARTIAL", "PART_MISSING", "data_gap",
     "The answer cites real FY25 AR disclosures (Phase 2 group-captive solar commissioning, ~75% green energy; BGSW lab in a vacated hangar expected 2HY2025; ChiP plant) with pages. It does not give a clean statement of 'newly commissioned facilities' and mixes relocations/upgrades; deck/concall have no explicit statement.",
     "AR p60/p174: Phase 2 group captive solar commissioning, ~75% green energy; BGSW lab expected 2HY2025; p148 ChiP Chennai plant.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q16", "ILL_POSED", "PREMISE_FALSE", "premise",
     "EDELWEISS is a financial-services group (Agency business, Holding company activities, Unallocated); it has no manufacturing facilities. The premise is false; the answer says not in data.",
     "fin.segment_value segments: Agency business, Holding company activities, Unallocated.",
     "SQL fact_v4_pilot.db fact"),
    ("Q17", "PARTIAL", "PART_MISSING", "data_gap",
     "The margin profile 16-20%, Q2 consolidated 18.87%, standalone 20.01%, H1 16.09% and the prior-quarter blip are verified. No MOU/partner is mentioned in the held concall, so the denial is fair, but the full normalisation path (H2 recovery, ~17% normalised, 15-20% target) is omitted.",
     "claims 621981 (16-20%), 621986 (18.87%), 621991 (20.01%), 621996 (16.09%); no MOU in concall chunks 93093/95052.",
     "SQL v4.db claim + chunks_v3_pilot.db chunk"),
    ("Q18", "ILL_POSED", "PREMISE_FALSE", "premise",
     "KALYANKJIL is a jewellery retailer; the held data has no mobile-PLI/mobile segment. The premise is false; the answer correctly rejects it and gives the actual margin commentary.",
     "KALYANKJIL annual report/claims: jewellery retail; no mobile-PLI; Q1FY27 concall old-gold/cash-for-gold margin commentary.",
     "SQL chunks_v3_pilot.db chunk / v4.db claim"),
    ("Q19", "ILL_POSED", "PREMISE_FALSE", "premise",
     "SUNPHARMA is a pharmaceutical company with 40 manufacturing sites; no 4.5 GW capacity. The premise is false; the answer correctly says so.",
     "SUNPHARMA annual report/results notes: 40 global manufacturing sites; no 4.5 GW figure.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q20", "RIGHT", "EXACT", "none",
     "SAIL fell from 166.35 to 133.05 (-20.02%) and Nifty Metal fell from 10,048.55 to 8,980.15 (-10.63%) on 2024-06-04; 10.63/20.02 = 53.10%. The answer's share is correct.",
     "SAIL price.close 166.35 (2024-06-03) -> 133.05 (2024-06-04), -20.02%; Nifty Metal macro.index_close 10,048.55 -> 8,980.15, -10.63%; calculator 10.63/20.02 = 0.530969.",
     "SQL fact_v4_pilot.db fact"),
    ("Q21", "ILL_POSED", "PREMISE_FALSE", "premise",
     "APLAPOLLO is a steel-pipes maker; the held documents have no Sanand plant/phase 1. The premise is false; the answer says not in data.",
     "APLAPOLLO annual report plants: Raipur and Dubai; no 'Sanand' in held chunks.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q22", "ILL_POSED", "PREMISE_FALSE", "premise",
     "The ISRF JV belongs to Cochin Shipyard; SUNPHARMA has no ISRF JV in the held related-party/JV disclosures. The premise is false; the answer says not in data.",
     "SUNPHARMA annual report related-party/JV notes: no ISRF; no 'ISRF' in held chunks.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q23", "WRONG", "VALUE_WRONG", "reasoning",
     "The CEO is Sanjay Raghuraman; the held remuneration tables list him at 19.34M and 17.36M (FY25 AR) and 21.27M (FY24 AR). The answer calls the MD (T.S. Kalyanaraman) the CEO, reports his 112.76M/111.74M pay, and says CEO pay is not disclosed. Wrong person and a false negative; 111.7/112.8/0.9 are rounded/mental and fail the number check.",
     "AR FY25 p93: Sanjay Raghuraman 19.34 / 17.36; AR FY24 p93: Sanjay Raghuraman 21.27 / 19.34 and share-based 93.07; T.S. Kalyanaraman 111.74 -> 112.76 -> 121.20 (MD).",
     "SQL chunks_v3_pilot.db chunk (55823, 68619, 68496)"),
    ("Q24", "WRONG", "VALUE_WRONG", "arithmetic",
     "The expiry/ordinary split double-counts 2026-10-08 and omits 2026-10-09: expiry sessions Oct 1/8/15 average 50.97%, but ordinary sessions average 55.37% (the answer says 54.56%). The 'No' direction is right, but the supporting averages are wrong.",
     "delivery_pct NSE: Oct 1 53.35, Oct 5 54.16, Oct 6 61.82, Oct 7 52.54, Oct 8 53.80, Oct 9 61.15, Oct 12 53.93, Oct 13 56.94, Oct 14 51.44, Oct 15 45.77, Oct 16 48.16, Oct 19 58.22; expiry avg 50.97; ordinary avg 55.37.",
     "SQL fact_v4_pilot.db fact"),
    ("Q25", "WRONG", "TOOL_GAP", "tool_gap",
     "The held daily/weekly price series support a chart/pattern read, but the agent has no charting/pattern tool and says the data cannot answer. The data exists; this is a tool gap, not a data gap.",
     "HINDALCO price.close/high/low/open daily 2019-2026 (2025-10-23 close 792.4 -> 2026-10-19 900.5; high 1,150 on 2026-05-27; low 774.6 on 2025-11-24).",
     "SQL fact_v4_pilot.db fact"),
    ("Q26", "ILL_POSED", "PREMISE_FALSE", "premise",
     "The entity is HEG Ltd (INE545A01024), not a newly listed HEG Advanced Materials; there is no prospectus or listing-day move in the held data, and 2021-10-27 is simply the first price date. The premise is false.",
     "price.close first date 2021-10-27 = 440.58 (store start, not a listing day); no prospectus/listing-day document; entity master symbol blank.",
     "SQL fact_v4_pilot.db fact / chunks_v3_pilot.db"),
    ("Q27", "PARTIAL", "PART_MISSING", "data_gap",
     "Order-inflow announcements are absent for Hindalco (a commodity producer); the flow data is right: DII 24.23% (Sep-25) -> 19.95% (Jun-26), FII 32.10% -> 35.60%. But the answer does not compute the last two quarters' returns or test which explains them.",
     "hold.pct DII 24.23 (2025-09-30) -> 19.95 (2026-06-30); FII 32.10 -> 35.60; price.close 886.70 (2025-12-31), 956.60 (2026-06-30), 941.80 (2026-09-30), 900.45 (2026-10-19); no order-inflow announcements.",
     "SQL fact_v4_pilot.db fact"),
    ("Q28", "PARTIAL", "PART_MISSING", "data_gap",
     "CWIP is 50,419 Cr consolidated at 30 Jun 2026 and 29,603 Cr at 31 Dec 2024; depreciation is 5.28%/yr for the first 12 years then ~1.1-1.3%/yr. The answer gives these but not CWIP as a share of the balance sheet, and capitalised interest is not held.",
     "deck chunk 51553: consolidated CWIP 50,419 Cr (30 Jun 2026), standalone 6,673 Cr; chunk 48862: 29,603 Cr (31 Dec 2024); concall chunk 36472: 5.28% initial 12 years, ~1.1-1.3% thereafter over 23 years.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q29", "ILL_POSED", "PREMISE_FALSE", "premise",
     "INDHOTEL's segments are Hotel Services and Air and Institutional Catering; it has no BPC or fashion segment. The premise is false; the answer correctly says the framing does not match.",
     "fin.segment_value segments: Hotel Services, Air and Institutional Catering.",
     "SQL fact_v4_pilot.db fact"),
    ("Q30", "PARTIAL", "PART_MISSING", "data_gap",
     "The answer gives real payback anecdotes (Taj Ganges 100-room wing PBT-positive in Q1, 40% EBITDA margin; Ekta Nagar break-even in 100 days) but not a standard 'new store at maturity' earnings or per-store capex/payback. The 500-600 Cr routine-capex figure is not in the tool results (flagged).",
     "chunk 95562: Taj Ganges new 100-room wing PBT-positive first quarter, 40% EBITDA margin; chunk 94215: Ekta Nagar break-even within 100 days; chunk 94824: FY26 capex >1,000 Cr, ~650 Cr renovations. No per-store capex/maturity figure.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q31", "ILL_POSED", "PREMISE_FALSE", "premise",
     "ANANDRATHI is a wealth-management firm, not a bank/NBFC; it reports no NIM or loan growth. The premise is false; the answer correctly says so.",
     "No NIM/loan series in the fact store; annual report wealth-management/AUM/fee business; debt/equity 0.02-0.03.",
     "SQL fact_v4_pilot.db chunk/fact"),
    ("Q32", "CORRECT_NOT_IN_DATA", "DATA_GAP", "data_gap",
     "The store has consolidated/standalone debt but no holdco-level split and no asset-monetisation repayment amount. The answer correctly says not in data; the net-debt/EBITDA ratios it quotes are a nearby measure.",
     "fin.total_debt/book_equity by basis; no holdco split; no monetisation repayment figure in claims/chunks.",
     "SQL fact_v4_pilot.db fact / v4.db claim"),
    ("Q33", "RIGHT", "EXACT", "none",
     "Nitin Pai's 24 Apr 2026 concall statement is verbatim: 'all our revenues and growth or lack of it is organic'. The answer correctly says growth is organic and no acquisition/goodwill effect is in the held data.",
     "concall chunk 94576 p16 (2026-04-24): 'all our revenues and growth or lack of it is organic'; revenue FY25 3,729.05 Cr -> FY26 3,757.42 Cr; no goodwill atom.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q34", "ILL_POSED", "PREMISE_FALSE", "premise",
     "UFBL is a restaurant/food-hospitality company (Barbeque-Nation), not an air-conditioner manufacturer. The premise is false; the answer correctly says so.",
     "UFBL annual report/chunks: restaurant/casual dining; no AC business.",
     "SQL chunks_v3_pilot.db chunk"),
    ("Q35", "WRONG", "TOOL_GAP", "tool_gap",
     "TATAELXSI's daily high/low/volume are held (Jul-Sep 2026). The answer says the volume series is truncated and no range can be determined; it did not page the series or compute the edges/tests. Data exists; tool gap.",
     "price.high max 3,857.0 (2026-08-10), price.low min 3,169.0 (2026-09-24); daily volume series held.",
     "SQL fact_v4_pilot.db fact"),
    ("Q36", "WRONG", "TOOL_GAP", "tool_gap",
     "The store has price.close and a price.sma series (20-day, no period dim); 50/200-day SMAs can be computed from daily closes, which are held. The answer says they cannot be computed; tool gap.",
     "price.sma latest 170.924 (2026-10-19; one series, no 50/200 dim); price.close daily 2019-2026.",
     "SQL fact_v4_pilot.db fact"),
    ("Q37", "WRONG", "TOOL_GAP", "tool_gap",
     "Earnings dates are in the results/announcement chunks and price/volume are held; the gap-fill analysis is computable by paging the series. The answer says the dates/analysis are not in the store; tool gap.",
     "results/announcement chunks for ANANDRATHI; price.close/volume daily; no precomputed gap atom.",
     "SQL chunks_v3_pilot.db / fact_v4_pilot.db"),
    ("Q38", "PARTIAL", "PART_MISSING", "tool_gap",
     "EPS rose 27.28 (FY25) to 43.34 (FY26), +58.9% (calculator 58.87; the answer's 58.9 is unsupported/mental). The Nifty series is held (macro.index_close), so relative strength is computable; the answer says it is absent. Defence-theme evidence is correctly absent.",
     "fin.eps consolidated FY25 27.28, FY26 43.34; macro.index_close Nifty 50 held; no defence references.",
     "SQL fact_v4_pilot.db fact"),
    ("Q39", "WRONG", "TOOL_GAP", "tool_gap",
     "UNIVASTU's ISIN INE562X01013 is in the pilot universe (blank symbol); fact/price atoms exist. The answer used the name, got 'not a pilot symbol', and concluded not in data. Entity-resolution failure, not a data gap.",
     "pilot_universe ISIN INE562X01013 (symbol blank); fact atoms and price.close 140.5 on 2026-09-24.",
     "SQL fact_v4_pilot.db fact"),
    ("Q40", "PARTIAL", "PART_MISSING", "reasoning",
     "The values for 2026-09-22 (delivery 70.70%, qty 75,026, close 222.04) and 2026-09-24 (61.04%, 41,158, 220.22) are correct, but the two sessions are not consecutive and the question's 'two days' event is ambiguous (many >60% pairs).",
     "delivery_pct/qty/close 2026-09-22: 70.70%, 75,026, 222.04; 2026-09-24: 61.04%, 41,158, 220.22; many other >60% sessions.",
     "SQL fact_v4_pilot.db fact"),
]


def wilson(k: int, n: int, z: float = 1.96) -> list[float]:
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return [round(centre - half, 4), round(centre + half, 4)]


def main() -> None:
    flags = {r["qid"]: r["new"] for r in
             (json.loads(line) for line in (RUNS / "number_recheck.jsonl").read_text(encoding="utf-8").splitlines())}
    questions = {q["qid"]: q for q in
                 (json.loads(line) for line in (HERE / "questions.jsonl").read_text(encoding="utf-8").splitlines())}
    out = []
    for qid, verdict, code, cause, reason, looked_up, tool in G:
        q = questions[qid]
        out.append({"qid": qid, "mid": q["mid"], "symbol": q.get("symbol"),
                    "verdict": verdict, "reason_code": code, "failure_cause": cause,
                    "reason": reason, "looked_up": looked_up, "tool": tool,
                    "number_check": flags.get(qid, {}), "graded_by": "hand, read grade definitions"})
    (HERE / "grades.jsonl").write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")
    counts = Counter(r["verdict"] for r in out)
    causes = Counter(r["failure_cause"] for r in out)
    denominator = sum(v for k, v in counts.items() if k not in ("ILL_POSED", "CORRECT_NOT_IN_DATA"))
    right = counts["RIGHT"]
    summary = {"n": len(out), "counts": dict(counts), "causes": dict(causes),
               "denominator": denominator, "right": right,
               "right_rate": round(right / denominator, 4),
               "wilson95": wilson(right, denominator),
               "rule": "kill if RIGHT < 50% of rows not ILL_POSED and not CORRECT_NOT_IN_DATA",
               "verdict": "KILL"}
    (HERE / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
