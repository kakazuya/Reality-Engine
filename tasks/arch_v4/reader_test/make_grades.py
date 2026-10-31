"""Hand grades for the 40 frozen questions.  One row per question, written after reading
the question, the bank rubric/gold and the retrieved chunks; no row was dropped."""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
V = {
 "Q01": ("RIGHT", "none", "Exact bank gold; quote verbatim."),
 "Q02": ("WRONG", "reading", "Quote verifies 470 MW but the answer adds 53 MW, 30 MW and 523 MW that are not in the quote, and misreads hydro as 'idle'; the cost-effect part is not answered."),
 "Q03": ("RIGHT", "none", "Why (repairs advanced at IISCO/Durgapur/Bokaro) and recovery (Q2-Q4 volumes higher) both answered from a verbatim quote."),
 "Q04": ("CORRECT_NOT_STATED", "scope", "The pilot corpus has no SAIL shutdown/force-majeure disclosure (one rumour-verification announcement only); the capital-repairs passage is not a shutdown. The market-wide premise cannot be answered from a SAIL-only binding."),
 "Q05": ("RIGHT", "none", "Correctly separates the Q1 promise from realised later-quarter output; no later-quarter results were known at 2026-10-07."),
 "Q06": ("RIGHT", "none", "Internal-accrual funding stated verbatim."),
 "Q07": ("CORRECT_NOT_STATED", "data_gap", "No POLICYBZR announcement after 2026-08-13 in the corpus; the 24/27 Sep 2026 filings and the price move are absent."),
 "Q08": ("RIGHT", "none", "FY25 control judgement, pages 230/290 and the disclosure all given; page citations are provenance, not company numbers."),
 "Q09": ("RIGHT", "none", "1,200 wagons/month and the sustainable-demand condition both quoted."),
 "Q10": ("PARTIAL", "reading", "Gives two of the three KAMs in the retrieved passage (IT program development, life-insurance revenue timing) but omits IT operations and cannot say whether any repeated."),
 "Q11": ("CORRECT_NOT_STATED", "data_gap", "No 13 May 2026 Change in Management announcement in the corpus (the 13 May document is the investor deck)."),
 "Q12": ("RIGHT", "none", "Next-fiscal restoration ('27-'28) and the three drivers quoted."),
 "Q13": ("PARTIAL", "retrieval", "15% guidance and confidence are right, but Q1 FY27 actual growth (20%) is in chunk 95675, which was not among the ten excerpts; the answer says the actual is not stated."),
 "Q14": ("CORRECT_NOT_STATED", "ask_mismatch", "15% guidance is in the call, but no half-year skew is stated; the question's specific ask has no held answer."),
 "Q15": ("CORRECT_NOT_STATED", "data_gap", "No 28 Sep 2026 auditor-resignation filing for Bharat Serums in the corpus."),
 "Q16": ("RIGHT", "none", "Three-year BharatNet execution and the March start both quoted."),
 "Q17": ("CORRECT_NOT_STATED", "data_gap", "Only Trent decks are held for Apr 2025; the 5 Apr 2025 pre-open update is absent."),
 "Q18": ("CORRECT_NOT_STATED", "data_gap", "The Q1 FY27 concall (chunk 96033) states operating margin 12.43% but is known 2026-08-10, after this question's 2026-08-04 as_of; the 3 Aug results filing does not state an operating margin. The reader correctly did not use the later call."),
 "Q19": ("WRONG", "reading", "Answer says 'not stated' while quoting the annual report's 'no qualification' sentence: self-contradictory, and the quote is from the AR, not the Q1 filing."),
 "Q20": ("WRONG", "reading", "Q1 FY27 call (chunk 95489, in the ten excerpts) states 8.7 MT commissioned and 200.1 MT domestic capacity, 212.7 MT by FY27; the model said not stated."),
 "Q21": ("CORRECT_NOT_STATED", "data_gap", "Only the 12 May 2025 cover letter is held; the call transcript body is absent (one chunk)."),
 "Q22": ("PARTIAL", "reading", "12 facilities is right; the answer says locations are not stated although the deck lists business/plant detail. Count without locations is partial."),
 "Q23": ("WRONG", "reading", "Quote is a paraphrase, not verbatim ('NCLT-approved' vs the report's wording), and it comes from the FY26 annual report rather than the Q1 results asked about."),
 "Q24": ("RIGHT", "none", "FY26 consolidated statutory-auditor fee of Rs 1.48 crore quoted."),
 "Q25": ("PARTIAL", "reading", "Three-year implementation timeline right; the same chunk says the second part is 10 years of maintenance, which the answer wrongly calls not stated."),
 "Q26": ("PARTIAL", "reading", "Correctly says conversion timing is not stated, but the gates quoted are industry-wide (4.2 GW, transmission/land), not Suzlon's 4.5 GW capacity; no company-specific gate is quoted."),
 "Q27": ("RIGHT", "none", "CCS approval and 'maximum by September' both quoted."),
 "Q28": ("PARTIAL", "reading", "FY26 pay (Rs 703 lakh incl. Rs 295 lakh commission) right; the three-year change is not stated and no prior-year figures are given."),
 "Q29": ("CORRECT_NOT_STATED", "data_gap", "Only the 29 Jul 2026 cover letter is held; the call transcript body is absent (one chunk)."),
 "Q30": ("CORRECT_NOT_STATED", "data_gap", "Rs 3.2 bn Q1 capex is stated, but no annual plan is held, so ahead/behind cannot be answered. The answer string is 'not stated' though it carries the capex quote."),
 "Q31": ("CORRECT_NOT_STATED", "ask_mismatch", "The 4% demand sentence exists in chunk 90704 but gives no reason the market is not stronger; the asked reason is not stated (and 90704 was not retrieved)."),
 "Q32": ("CORRECT_NOT_STATED", "data_gap", "Sanand phase 1 was commissioned Dec 2025 after a ~6-month delay; no revised target date is stated, so 'did it meet its revised date' has no held answer."),
 "Q33": ("PARTIAL", "reading", "QRSAM is not in the order book and the Rs 55,000 cr pipeline / Rs 30,000 cr QRSAM split is quoted; the cover effect is not answered."),
 "Q34": ("RIGHT", "none", "Exact bank gold; Q3 of the current fiscal quoted."),
 "Q35": ("PARTIAL", "reading", "10.46% vs 10.18% quoted correctly; the second ask (what it says about the cable pricing environment) is left unanswered."),
 "Q36": ("RIGHT", "none", "December 2025 commissioning and ~6-month delay both quoted."),
 "Q37": ("RIGHT", "none", "33 GW split (16.5 coal / 1.9 hydro / 15 renewable) quoted; coal correctly named largest."),
 "Q38": ("PARTIAL", "reading", "Answers the 2023 initial pledge (26% of shares) from a Nov 2025 call, not the latest Sep 2026 pledge; the exact share count is not given."),
 "Q39": ("CORRECT_NOT_STATED", "data_gap", "No Sep 2026 pledge announcement is held for TruAlt (latest announcements Aug/Oct 2026); the share count is absent."),
 "Q40": ("PARTIAL", "reading", "184 -> 212 MT target right; the same chunk states a 3-year delivery window, which the answer wrongly calls not stated."),
}

res = {json.loads(l)["qid"]: json.loads(l) for l in (HERE / "results.jsonl").read_text(encoding="utf-8").splitlines()}
rows = []
for qid, (verdict, failure, why) in V.items():
    r = res[qid]
    rows.append({
        "qid": qid, "mid": r["mid"], "symbol": r["symbol"], "verdict": verdict,
        "failure": failure, "rationale": why, "status": r["status"],
        "quote_ok": bool((r.get("verify") or {}).get("quote_ok")),
        "gold_in_top10": r["gold_in_topk"],
        "wrong_with_real_quote": verdict in ("WRONG", "PARTIAL") and bool((r.get("verify") or {}).get("quote_ok")),
        "total_secs": r.get("total_secs"),
    })
rows.sort(key=lambda x: x["qid"])
(HERE / "grades.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in rows), encoding="utf-8")
print("wrote", len(rows), "grades")
from collections import Counter
print(Counter(x["verdict"] for x in rows))
print(Counter(x["failure"] for x in rows))
