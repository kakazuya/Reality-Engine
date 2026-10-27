"""Build the 300-question open question bank (tasks/QUESTION_BANK_OPEN_2026-10-27.{jsonl,md}).

Every question is hand-authored (no slot-swapping). Stock entities are resolved
read-only from master_companies; every ground_truth cites a fact id that carries the
exact SQL that produced it (tasks/question_bank_open_facts_2026-10-27.json).

Run:  python tasks/build_question_bank_open_300.py
Check: python tasks/build_question_bank_open_300.py --check
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "tasks"
OUT_JSONL = TASKS / "QUESTION_BANK_OPEN_2026-10-27.jsonl"
OUT_MD = TASKS / "QUESTION_BANK_OPEN_2026-10-27.md"
FACTS_FILE = TASKS / "question_bank_open_facts_2026-10-27.json"
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or ROOT / "reality_engine" / "data")

ARCH = {
    "A01": ("Commissioning / go-live dates", "12"),
    "A02": ("Demand and ramp timing", "12"),
    "A03": ("Inverse topic screen", "13"),
    "A04": ("Auditor opinion", "14"),
    "A05": ("Auditor and KMP exits", "14"),
    "A06": ("Red flags", "14"),
    "A07": ("Market move -> why", "15"),
    "A08": ("Single-stock move -> why", "15"),
    "A09": ("Commodity transmission", "16"),
    "A10": ("FX / rates transmission", "16"),
    "A11": ("Business economics", "17"),
    "A12": ("Forward policy impact", "18"),
    "A13": ("Supply chain / second order", "19"),
    "A14": ("Guidance vs delivery", "3,12"),
    "A15": ("Order book and execution", "2,12"),
    "A16": ("Capital allocation", "1,3"),
    "A17": ("Flows and ownership", "2,4"),
    "A18": ("Event study", "9"),
    "A19": ("Cross-sector what-if", "16,18"),
    "A20": ("Bizarre / out-of-scope", "20"),
}

FACTS = {f["id"]: f for f in json.loads(FACTS_FILE.read_text(encoding="utf-8"))}

# macro_events rows split by provenance: MEV_* rows carry a doc_id; hand-seeded
# event ids (including PHASE5_* fixtures) do not and must never become evidence.
EVENTS: dict[str, set[str]] = {"sourced": set(), "unsourced": set()}

QUESTIONS: list[dict] = []


def Q(arch, question, ents, period, as_of, kind, evidence, steps, forbidden,
      gt=None, cov="yes", note="", gap=None, why="", flags=""):
    QUESTIONS.append(dict(arch=arch, q=question, ents=ents, period=period, as_of=as_of,
                          kind=kind, ev=evidence, steps=steps, forb=forbidden, gt=gt,
                          cov=cov, note=note, gap=gap, why=why, flags=flags))


# ---------------------------------------------------------------- A01 (15)
Q("A01", "KEI Industries' first phase at Sanand: what month did it actually get commissioned, and how far behind the original plan was that?", "KEI", "FY26-Q1FY27", None, "date",
  "concall_facts.cc_items (list_name='capacity_and_projects', KEI) with the quote and call date; the prior call's stated date; deck_figures for the same quarter if the plant was on a slide",
  "pull every KEI capacity statement in date order -> take the first stated commissioning window -> take the commissioning statement -> subtract the two and name the slip in months",
  "quoting only the later 'we commissioned' line and hiding that a date was promised earlier; inventing the original month",
  gt="cc.KEI.capacity_and_projects", cov="yes", note="slip is stated as 'around 6 months' in the same quote; the original month is implied, not directly quoted.",
  why="tests dated-statement tracking and slippage arithmetic on a real commissioning event")
Q("A01", "Dixon's Vivo joint venture: from which quarter does management expect it to start showing up in revenue?", "DIXON", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects) for DIXON; the concall transcript of that quarter; any deck slide on the JV",
  "locate the JV statement -> state the quarter management named -> note whether it is a 'commence operations' or a 'revenue' date",
  "converting 'commence operations' into a revenue date without saying so",
  gt="cc.DIXON.capacity_and_projects", cov="yes",
  why="distinguishes an operations date from a revenue-recognition date")
Q("A01", "Tata Power's renewables arm: how much capacity was already commissioned when management spoke, and how much was due 'in the next few weeks'?", "TATAPOWER", "Q2 FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for TATAPOWER; the renewables segment slide in the deck; results_notes for capitalisation disclosures",
  "read the MW split in the call -> separate 'commissioned' from 'will get commissioned' -> compare the total with the stated operating capacity",
  "adding the pipeline to installed capacity; treating 'next few weeks' as done",
  gt="cc.TATAPOWER.capacity_and_projects", cov="yes",
  why="tests commissioned-versus-pipeline separation")
Q("A01", "SRF is putting up a second pharma-intermediate plant at Dahej. How much is the capex and over what commissioning window did management guide?", "SRF", "FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for SRF; the capex slide in the deck; ar_facts capital-commitment facts",
  "find the plant statement -> take the capex and the window -> check the AR/notes for capital work-in-progress corroboration",
  "rounding a guided window into a fixed date; quoting a capex without the plant",
  gt="cc.SRF.capacity_and_projects", cov="yes",
  why="tests capex-plus-date extraction on a chemical intermediate plant")
Q("A01", "Cochin Shipyard's ISRF joint venture with Drydocks World, Dubai: by when is it targeted to be in place, and what is it conditional on?", "COCHINSHIP", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects) for COCHINSHIP; board-approval announcement in bse_announcements; deck slide on the JV",
  "read the board note and the call -> state the target window -> state the condition ('subject to approvals') separately",
  "reporting the target as a completed JV; dropping the approval condition",
  gt="cc.COCHINSHIP.capacity_and_projects", cov="yes",
  why="tests condition-bearing timeline extraction")
Q("A01", "IRCTC's payment-aggregator application: what did RBI extend the deadline to, and has the licence actually come through since?", "IRCTC", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects) for IRCTC; any later announcement in bse_announcements; results_notes",
  "find the stated RBI extension date -> search later calls/announcements for a licence grant -> if none, say NOT IN DATA for the licence",
  "assuming the extension equals a licence; giving a grant date with no document",
  gt="cc.IRCTC.capacity_and_projects", cov="partial", note="the RBI extension date is quoted; no later grant document in the stores.",
  gap="NEW GAP: no regulatory-licence outcomes table; a licence grant is only findable if the company announces it",
  why="tests an answered part from a stale document plus an explicit NOT IN DATA part")
Q("A01", "APLAPOLLO 8 MT by FY28 — slipped or on track?", "APLAPOLLO", "FY26-FY28", None, "date",
  "concall_facts.cc_items (capacity_and_projects) for APLAPOLLO across the last four calls; capex in results_notes; deck capacity slides",
  "take the earliest FY28 statement -> take the latest -> compare the target tonnage and date -> state current capacity from the results/AR",
  "using one slide for both 'current' and 'target'; assuming the plan slipped without a later quote",
  gt="cc.APLAPOLLO.capacity_and_projects", cov="partial", note="the FY28 target is quoted; current capacity sits in the deck/AR, not in the same statement.",
  gap="NEW GAP: capacity is only in prose/slides, there is no company-capacity time series",
  why="tests guidance persistence across calls without a capacity table")
Q("A01", "Titagarh Rail Systems is 'ready to ramp up' wagon output. To what monthly run-rate, and what single condition does management put on doing it?", "TITAGARH", "FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for TITAGARH; demand_commentary items; the wagon-orders section of the deck",
  "read the ramp statement -> state the run-rate -> state the trigger condition -> check demand_commentary for what is blocking it",
  "presenting the 1,200/month level as the current run-rate; dropping the condition",
  gt="cc.TITAGARH.capacity_and_projects", cov="yes",
  why="tests conditional capacity answers, the exact shape of a real investor question")
Q("A01", "Adani Green: what renewable-capacity milestone did management claim in Q1 FY27, and how does it split between this quarter and earlier years?", "ADANIGREEN", "Q1 FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for ADANIGREEN; results_notes note on commissioned projects; deck capacity chart",
  "read the milestone -> read the note's split (current quarter / FY26 / earlier) -> check the sum against the milestone",
  "quoting a cumulative GW figure as quarterly addition",
  gt="cc.ADANIGREEN.capacity_and_projects", cov="yes",
  why="tests cumulative-versus-incremental capacity reasoning")
Q("A01", "NTPC has over 33 GW under construction. What is the coal/hydro/renewable split, and which of those is the largest single block?", "NTPC", "Q1 FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for NTPC; the capacity pipeline slide in the deck; results_notes",
  "read the three-way split -> name the largest block -> compare with NTPC's stated renewable target",
  "summing the split to 33 GW when it does not; calling the renewable block the largest without checking",
  gt="cc.NTPC.capacity_and_projects", cov="yes",
  why="tests numeric extraction with a three-way split")
Q("A01", "RVNL's BharatNet work: what execution timeline did management give, and what happens after the build phase?", "RVNL", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects) for RVNL; order_book items; results_notes",
  "read the timeline -> note the extra duct/fibre months -> note the maintenance phase -> state the total horizon",
  "adding the maintenance phase to the build timeline",
  gt="cc.RVNL.capacity_and_projects", cov="yes",
  why="tests multi-phase timeline reading")
Q("A01", "Afcons' Mumbai-Ahmedabad high-speed-rail C2 package: what is the current status of the two tunnel-boring machines?", "AFCONS", "FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for AFCONS; project status in the deck; bse_announcements if a drive was flagged",
  "find the TBM statement -> state whether drives have started -> state whether it is 'as per schedule'",
  "reading 'commenced initial drives' as 'completed tunnelling'",
  gt="cc.AFCONS.capacity_and_projects", cov="yes",
  why="tests careful status reading on a long-dated infra package")
Q("A01", "BEL ka QRSAM order kis approval ka wait kar raha hai, aur kab tak? (Hinglish)", "BEL", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects) for BEL; order_book items; bse_announcements for the order after approval",
  "find the approval named in the call -> state the expected window -> check later announcements for the actual order",
  "calling the order won before CCS approval; giving an approval date with no filing",
  gt="cc.BEL.capacity_and_projects", cov="yes",
  why="tests defence-order approval-stage vocabulary")
Q("A01", "UltraTech's capacity is 184 million tonnes including India Cements and Kesoram. What is the target it is being expanded to, and over what period?", "ULTRACEMCO", "FY27-FY30", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for ULTRACEMCO; the expansion slide in the deck; acquisition announcements",
  "separate organic from acquired tonnes -> read the target -> read the horizon -> check the current base includes both acquisitions",
  "treating the acquired capacity as organic growth; quoting a target without its base",
  gt="cc.ULTRACEMCO.capacity_and_projects", cov="partial", note="the 184 MT base is quoted; the target number is cut off in the stored quote and must come from the deck.",
  gap="NEW GAP: capacity targets live in slide text that is not quantized, so a number can be missing from the extracted quote",
  why="tests base-plus-target capacity answers and honest partial coverage")
Q("A01", "Hindalco's renewable-energy capacity: how much does it have, of what mix, and what did management say it does to cost?", "HINDALCO", "Q1 FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects) for HINDALCO; segment results; management commentary on power cost",
  "read the MW figure -> read the solar/wind/hydro split -> state the pump-storage tie-up -> link to power cost only if stated",
  "inventing a cost saving per MW; adding contracted capacity to commissioned",
  gt="cc.HINDALCO.capacity_and_projects", cov="partial", note="MW and mix are quoted; the cost effect is not quantified in the stored quote.",
  gap="NEW GAP: no company power-cost series linked to renewable capacity",
  why="tests a capacity answer where the economic link is only qualitative")

# ---------------------------------------------------------------- A02 (15)
Q("A02", "Titagarh says it will only ramp wagons once demand is 'sustainable'. What did management say the current network run-rate is, and what is it below?", "TITAGARH", "FY27", None, "fact",
  "concall_facts.cc_items (demand_commentary, TITAGARH); capacity_and_projects; the wagon-industry slide in the deck",
  "read the target run-rate -> read the achieved run-rate -> state the gap -> state the demand condition management gave",
  "treating the target run-rate as achieved; ignoring the qualifying sentence",
  gt="cc.TITAGARH.demand_commentary", cov="yes",
  why="tests demand-conditioned ramp reading, not a simple number lookup")
Q("A02", "Dixon's operating margin compressed because the mobile-PLI benefit expired. When does management expect the margin to normalise, and on what?", "DIXON", "FY27", None, "fact",
  "concall_facts.cc_items (margin_and_cost_commentary, DIXON); results_notes margin note; XBRL EBITDA margin for Q1 FY27",
  "read the compression reason -> read the normalisation driver and quarter -> check Q1 FY27 margin against the prior quarter",
  "attributing margin compression to commodity costs when the stated cause is a policy expiry",
  gt="cc.DIXON.margin_and_cost_commentary", cov="partial", note="the cause is quoted; the normalisation quarter is not in the stored item.",
  gap="NEW GAP: policy-incentive expiry is not a tagged event, so its margin effect cannot be traced across quarters",
  why="tests cause-plus-recovery-timing reasoning from a margin comment")
Q("A02", "KEI's operating margin improved in FY26. By how much, and what does that say about the pricing environment for cables?", "KEI", "FY25-FY26", None, "fact",
  "concall_facts.cc_items (margin_and_cost_commentary, KEI); results_notes margin note; XBRL revenue and cost lines for the four quarters",
  "read the margin change -> compute it from XBRL if both years exist -> state what management attributed it to",
  "asserting a pricing environment from a margin number alone",
  gt="cc.KEI.margin_and_cost_commentary", cov="yes",
  why="tests margin-change arithmetic and the limit of what a single quote supports")
Q("A02", "UltraTech says cement demand for the country grew about 4% in the quarter. What did management give as the reason the market is not stronger?", "ULTRACEMCO", "Q1 FY27", None, "fact",
  "concall_facts.cc_items (demand_commentary, ULTRACEMCO); the demand slide in the deck; results_notes",
  "take the growth number -> take the stated drags -> separate seasonal from structural drags",
  "inventing a monsoon or election effect that management did not state",
  gt="cc.ULTRACEMCO.demand_commentary", cov="partial", note="the 4% is quoted; the drag list must come from the full transcript.",
  gap="NEW GAP: demand commentary is not tagged by cause, so cross-company demand screens cannot be built",
  why="tests demand-growth reading and refusing to add unstated causes")
Q("A02", "IndiGo reported revenue ahead of its own expectation. What did management say about the demand environment and when it expected to add capacity?", "INDIGO", "Q1 FY27", None, "fact",
  "concall_facts.cc_items (demand_commentary, INDIGO); the capacity/ASKM slide in the deck; results_notes",
  "read the demand statement -> read the capacity guidance -> check the two are about the same period",
  "mixing calendar and fiscal capacity guidance; treating 'ahead of expectation' as guidance raise",
  gt="cc.INDIGO.demand_commentary", cov="partial", note="the demand quote is stored; the capacity number is on the slide, not in this item.",
  gap="NEW GAP: no ASKM/capacity time series in the stores",
  why="tests demand-versus-capacity separation for an airline")
Q("A02", "Polycab has started BharatNet execution. Over how many years does that run, and from when?", "POLYCAB", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects, POLYCAB); order/story in the deck; results_notes on the project",
  "find when execution started -> state the duration -> state whether the start is a quarter or a month",
  "giving a completion date as start plus duration without a calendar check",
  gt="cc.POLYCAB.capacity_and_projects", cov="yes",
  why="tests start-plus-duration date construction")
Q("A02", "Suzlon says 4.5 GW of manufacturing capacity is fully operational. When does that capacity convert into revenue, and what gates it?", "SUZLON", "FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects, SUZLON); order_book items; results_notes on manufacturing",
  "read the capacity -> read the conversion gate (orders/execution) -> state what management said about the pipeline",
  "equating installed capacity with revenue capacity",
  gt="cc.SUZLON.capacity_and_projects", cov="partial", note="capacity is quoted; the conversion gate is only partly in the same statement.",
  gap="NEW GAP: no order-to-revenue conversion table",
  why="tests the classic 'capacity is not revenue' distinction")
Q("A02", "Amber Enterprises signed a manufacturing collaboration covering Oppo, OnePlus and Realme. When was it executed, and when does management expect it to matter?", "AMBER", "FY26-FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects, AMBER); the customer slide in the deck; results_notes on the agreement",
  "read the execution date -> read the expected contribution period -> state the customers covered",
  "naming a customer the filing does not name; giving a revenue date management did not give",
  gt="cc.AMBER.capacity_and_projects", cov="partial", note="the June 18 execution date is quoted; the revenue timing is not in the stored item.",
  gap="NEW GAP: customer-contract start dates are not tagged, so a start date cannot be screened for",
  why="tests contract-timing extraction and refusal to invent revenue timing")
Q("A02", "Jubilant FoodWorks has close to 3,600 stores, about 2,530 in India. When does management expect store additions to return to guidance, and why the pause?", "JUBLFOOD", "FY26-FY27", None, "explanation",
  "concall_facts.cc_items (demand_commentary, JUBLFOOD); the store-network slide in the deck; results_notes on store adds",
  "read the store count -> read the stated reason for slower adds -> find any guidance statement for the return",
  "presenting a store count as a store-add run-rate; assuming a date not guided",
  cov="partial", note="store counts are stored; the return-to-guidance date is not, so that half is NOT IN DATA.",
  gap="NEW GAP: no store-count/additions time series",
  why="tests a timing question where the honest answer is a count plus NOT IN DATA")
Q("A02", "SAIL ne Q1FY27 mein capital repairs aage khiske kyun, aur output kab recover hoga? (Hinglish)", "SAIL", "Q1 FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects, SAIL); the production slide in the deck; results_notes on shutdowns",
  "read why the repairs were advanced -> read the expected end -> read the output effect -> separate scheduled from one-off",
  "treating a planned shutdown as a demand signal; giving an end date that was not stated",
  gt="cc.SAIL.capacity_and_projects", cov="partial", note="the advancement and its reason are quoted; the end date/output effect is only partly there.",
  gap="NEW GAP: no plant-shutdown or production calendar",
  why="tests planned-maintenance versus demand reasoning")
Q("A02", "Muthoot Finance opened 177 branches in a year. When does gold-loan demand seasonally peak, and what did management say about branch-level demand?", "MUTHOOTFIN", "FY26-FY27", None, "explanation",
  "concall_facts.cc_items (capacity_and_projects, MUTHOOTFIN); the branch-network slide in the deck; results_notes",
  "read branch adds -> read the seasonality statement -> separate structural branch growth from seasonal demand",
  "turning a branch count into a demand forecast; inventing a festive-season uplift",
  cov="partial", note="branch adds are stored; the demand seasonality is only in commentary.",
  gap="NEW GAP: no NBFC branch/demand time series",
  why="tests separating distribution build from demand timing")
Q("A02", "TEXRAIL 100 leasing rakes — when?", "TEXRAIL", "FY27", None, "fact",
  "concall_facts.cc_items (capacity_and_projects, TEXRAIL); the leasing slide in the deck; order_book items",
  "read the rake count -> read the period management used ('near term') -> check the order book for the wagons behind it",
  "presenting 100 rakes as an order; giving a precise date for 'near term'",
  gt="cc.TEXRAIL.capacity_and_projects", cov="yes",
  why="tests vague-timeline handling on a leasing plan")
Q("A02", "Ircon has a new dedicated-freight-corridor project in the pipeline. What is the status of the tender, and when does revenue start?", "IRCON", "FY27", None, "date",
  "concall_facts.cc_items (capacity_and_projects, IRCON); order_book items; bse_announcements for any award",
  "read what was announced -> read whether tenders have floated -> if no date, say NOT IN DATA for revenue start",
  "inventing a tender date; treating an announced corridor as an Ircon order",
  gt="cc.IRCON.capacity_and_projects", cov="partial", note="the project is quoted as announced with no date; award and revenue timing are NOT IN DATA.",
  gap="NEW GAP: no tender/award pipeline table",
  why="tests the boundary between announcement and order")
Q("A02", "When does the cement industry get its next round of price increases, and what would have to change in demand for that?", "industry:cement", "FY27", "2026-10-07", "explanation",
  "the cement demand statement for ULTRACEMCO (and any other cement company call); the demand slide; regional price commentary",
  "read the demand growth -> read the pricing comment -> state the condition for a price round -> label the forecast as inference",
  "presenting a price-rise forecast as a reported fact; using a post-as-of call",
  gt="cc.ULTRACEMCO.demand_commentary", cov="partial", note="one demand data point is quoted; a forward price round is inference, not in data.",
  gap="NEW GAP: no industry price series (cement, steel, cable) in the stores",
  why="tests an industry timing question with an explicit as-of and an inference label")
Q("A02", "BEL ne FY27 ke liye 15% growth bola tha — kaunsa half-year usko uthana padega, aur management ne kya skew bataya? (Hinglish)", "BEL", "FY27", None, "fact",
  "concall_facts.cc_items (guidance, BEL); results_xbrl quarterly revenue for FY26 quarters; the order-book slide",
  "take the guidance -> compute the required H2 growth from FY26 quarterly revenue -> state the skew management described",
  "using annual guidance as a quarterly number; ignoring seasonality",
  gt="cc.BEL.guidance", cov="partial", note="the 15% is quoted; the H2 skew is in the transcript, not in this item.",
  gap="NEW GAP: guidance is not linked to the actual quarterly series, so guidance-vs-delivery needs hand work",
  why="tests forward guidance against the actual seasonality")

# ---------------------------------------------------------------- A03 (15)
Q("A03", "Konsi companies ne FY27 ke liye EBITDA margin recovery ka guidance diya hai, aur har ek ka evidence kya hai? (Hinglish)", "SUZLON, BEL", "FY27", "2026-10-07", "list",
  "concall_facts.cc_items (list_name='guidance') for every covered company; results_notes margin notes; XBRL EBITDA margin per quarter",
  "scan guidance items for margin words -> for each hit, quote the metric, period and value -> drop any hit without a period -> return company, quote, call date",
  "returning a company name without the quote; treating a past margin recovery as forward guidance; using a call after the as-of date",
  gt="cc.SUZLON.guidance", cov="partial", note="guidance items are stored but not tagged by topic, so the scan is recall-limited.",
  gap="G6", why="tests an inverse topic screen, the directly named family-13 shape")
Q("A03", "Q1FY27 price hikes — cables, paints, steel", "KEI, POLYCAB, ASIANPAINT", "Q1 FY27", None, "list",
  "concall_facts.cc_items (pricing_and_competition); results_notes; deck price-action slides",
  "scan pricing items -> keep only forward price actions -> state product and rise -> reject vague 'pricing stable' lines",
  "counting a price cut as a hike; citing an analyst question as a company statement",
  cov="partial", note="pricing commentary exists but no price-hike event is tagged, so the list cannot be exhaustive.",
  gap="G6", why="tests inverse screening on an event with no event store")
Q("A03", "Which managements said a plant or line goes live in H2 FY27? terse: H2FY27 commissioning list", "TATAPOWER, DIXON", "H2 FY27", "2026-10-07", "list",
  "concall_facts.cc_items (capacity_and_projects) across all covered companies; deck timelines; bse_announcements for commissioning",
  "collect dated go-live statements -> keep H2 FY27 only -> for each, state plant, date and the call it came from",
  "including dates already passed as of the as-of date; mixing a target date with an actual commissioning",
  gt="cc.TATAPOWER.capacity_and_projects", cov="partial", note="two go-live statements are quoted; a complete H2FY27 list needs an untagged scan.",
  gap="G6", why="tests a terse keyword query over dated forward statements")
Q("A03", "Which companies described demand as weak or below plan in Q1 FY27, and which described it as strong? Give both lists.", "TITAGARH, ULTRACEMCO, INDIGO", "Q1 FY27", None, "list",
  "concall_facts.cc_items (demand_commentary) for the covered set; deck demand slides; results_notes",
  "read each demand item -> classify weak/strong/flat on the words used -> quote the classifying sentence -> keep the two lists separate",
  "classifying 'grown 4%' as weak without the management's own framing; merging the lists",
  gt="cc.TITAGARH.demand_commentary", cov="partial", note="demand items exist but the direction field is not populated consistently.",
  gap="G6", why="tests a two-sided inverse screen and evidence-based classification")
Q("A03", "Which managements said working capital or receivables from government clients worsened last quarter?", "RVNL, NBCC, IRCON", "Q1 FY27", None, "list",
  "concall_facts.cc_items (balance_sheet_and_cash); results_notes working-capital notes; XBRL receivables where tagged",
  "scan cash/working-capital items -> keep only those blaming receivables/PSU clients -> quote the sentence",
  "treating a generic 'working capital stable' line as a worsening; inventing a receivable number",
  cov="partial", note="commentary is stored; receivable balances are not tagged in XBRL for all companies.",
  gap="G11", why="tests a governance-adjacent working-capital screen")
Q("A03", "Which companies announced fresh orders above Rs 1,000 crore in Q1 FY27? Include the order value and the period of execution.", "RVNL, HAL, TEXRAIL, BEL", "Q1 FY27", None, "list",
  "concall_facts.cc_items (order_book); bse_announcements for order wins; deck order slides",
  "collect order announcements -> keep above the threshold -> state value and execution period -> drop orders without a value",
  "mixing order inflow with order book; adding multi-year framework agreements as one-quarter orders",
  gt="cc.RVNL.order_book", cov="partial", note="RVNL's 5,417 crore inflow is quoted; a complete threshold screen needs tagged order values.",
  gap="G6", why="tests a numeric-threshold inverse screen with an execution-period requirement")
Q("A03", "Kaunsi mid-caps ne FY27 ke liye 20% se zyada revenue growth guide kiya hai? (Hinglish)", "BEL", "FY27", "2026-10-07", "list",
  "concall_facts.cc_items (guidance) filtered to revenue growth; XBRL revenue base to check the percentage is meaningful",
  "read each revenue-growth guidance -> keep above 20% -> quote it -> state the base period and whether it is organic",
  "treating '15% plus upside' as above 20%; using guidance without its base",
  cov="partial", note="only guidance items already extracted are visible; the threshold cannot be applied as a SQL filter.",
  gap="G6", why="tests a Hinglish numeric screen and the base-period trap")
Q("A03", "Which managements said they are evaluating acquisitions or inorganic growth, and which have actually signed something?", "KAYNES, AMBER, COCHINSHIP", "FY26-FY27", None, "list",
  "concall_facts.cc_items (capacity_and_projects, guidance); bse_announcements for JV/acquisition filings; results_notes",
  "split 'evaluating' from 'signed' -> for signed ones, quote the filing date and the counterparty -> label the rest as intent",
  "counting an MoU as a completed acquisition; blending intent and signed deals",
  gt="cc.COCHINSHIP.capacity_and_projects", cov="partial", note="one signed JV is quoted; intent statements are not tagged.",
  gap="G6", why="tests intent-versus-completion separation in an M&A screen")
Q("A03", "Which companies flagged input-cost inflation in Q1 FY27, and which input did each name?", "ASIANPAINT, APOLLOTYRE, KEI", "Q1 FY27", None, "list",
  "concall_facts.cc_items (margin_and_cost_commentary); results_notes cost notes; commodity series to check the named input moved",
  "scan cost commentary -> extract the named input -> check the relevant commodity series in the same window -> keep only supported claims",
  "accepting 'input costs rose' without an input name; using a commodity move that happened after the call",
  cov="partial", note="cost commentary is stored; the commodity-to-company input map does not exist as a table.",
  gap="G12", why="tests an inverse screen that must join commentary to a commodity series")
Q("A03", "Kaunsi company ne FY26 mein buyback ya special dividend announce kiya? Date aur amount ke saath batao. (Hinglish)", "TRENT, SIEMENS", "FY26", None, "list",
  "corporate_actions (action_type, subject, ex_date); bse_announcements for the board approval; results_notes",
  "read corporate actions -> keep buyback/dividend -> state amount per share and ex-date -> separate ordinary from special",
  "counting a bonus as a dividend; giving an ex-date as the announcement date",
  cov="partial", note="corporate_actions has dividends and bonuses; 'special' is not a separate field.",
  gap="NEW GAP: dividend/buyback rows are not classified as ordinary vs special, so the screen needs manual reading",
  why="tests a shareholder-return screen with date-type discipline")
Q("A03", "Which companies said their order book covers more than two years of revenue? Give the cover multiple you computed.", "HAL, TEXRAIL, RVNL", "FY27", None, "ranking",
  "concall_facts.cc_items (order_book) for the value; results_xbrl revenue for the trailing four quarters; deck order-book slides",
  "take order book -> take trailing revenue -> divide -> rank -> state the basis (consolidated/standalone) for each",
  "mixing a standalone order book with consolidated revenue; using a stale order book",
  gt="cc.HAL.order_book", cov="partial", note="HAL's 2,54,538 crore order book is quoted; trailing revenue must be summed from XBRL.",
  gap="G11", why="tests a derived ranking where the input basis must be stated")
Q("A03", "Which managements said they will reduce net debt this financial year, and by how much?", "TATASTEEL, SUZLON, JSWSTEEL", "FY27", None, "list",
  "concall_facts.cc_items (balance_sheet_and_cash); results_notes debt note; XBRL finance cost and borrowings",
  "collect deleveraging statements -> keep quantified ones -> state target and base -> drop unquantified intent",
  "adding a target reduction to an actual reduction; using gross debt for a net-debt claim",
  cov="partial", note="qualitative deleveraging commentary is stored; quantified targets are sparse.",
  gap="G11", why="tests quantification discipline in a debt screen")
Q("A03", "Which companies said export demand recovered in the last two quarters, and which markets did they name?", "KPRMILL, WELSPUNLIV, ARVIND, SUNPHARMA", "FY26-FY27", None, "list",
  "concall_facts.cc_items (demand_commentary); results_notes geographic split; deck export-share slides",
  "scan demand items for export words -> keep recovery claims -> name the market -> check the geographic split where available",
  "treating a tariff-driven one-off as a demand recovery; naming a market the company did not name",
  cov="partial", note="export commentary is untagged; market-level attribution is not stored as a field.",
  gap="G6", why="tests an export-demand screen with geographic corroboration")
Q("A03", "Which companies claimed capacity-utilisation improvement last quarter, and which gave the utilisation number?", "ULTRACEMCO, SAIL, DIXON", "Q1 FY27", None, "list",
  "concall_facts.cc_items (capacity_and_projects, key_numbers); deck utilisation slides; results_notes",
  "split 'improved' from 'improved to X%' -> keep the numeric ones -> state plant/segment -> note the missing denominators",
  "inventing a utilisation percentage from a qualitative line",
  cov="partial", note="utilisation is mostly qualitative; only some calls give a number.",
  gap="NEW GAP: no plant-level utilisation or production series for manufacturers",
  why="tests a screen that must report which answers are qualitative")
Q("A03", "Which managements said margin has bottomed and expect recovery next quarter? Kaun si companies ne bottom bola? (Hinglish)", "DIXON, KEI", "FY27", None, "list",
  "concall_facts.cc_items (margin_and_cost_commentary, guidance); results_notes; XBRL quarterly margin series",
  "collect 'bottomed' claims -> check the following quarter's actual margin -> report both the claim and whether it held",
  "honouring the claim without the following quarter; calling a one-quarter bounce a trend",
  gt="cc.DIXON.margin_and_cost_commentary", cov="partial", note="the compression statement is quoted; a 'bottomed' claim is not stored as a field.",
  gap="G6", why="tests an inverse screen with a forward claim that later data can falsify")

# ---------------------------------------------------------------- A04 (15)
Q("A04", "What was the auditor's opinion on Reliance's latest quarterly results, and was it modified in any way?", "RELIANCE", "Q1 FY27", None, "fact",
  "results_xbrl.filings (audit_opinion, audited, consolidated, dissem_ts); results_notes.docs (auditor_report flag); the results-notes chunk on the audit statement",
  "read the filing's audit_opinion field -> state the type -> state whether the accounts were audited or reviewed -> quote the note",
  "calling a review report an audit opinion; claiming the absence of a flag means an unmodified opinion",
  gt="opin.RELIANCE", cov="partial", note="the NSE field carries the declaration type only; no emphasis-of-matter or KAM text.",
  gap="NEW GAP: auditor opinion is stored as the NSE declaration ('unmodified'/'statement on impact') and not as opinion type + EOM + KAM",
  why="tests the difference between a declaration and a full audit opinion")
Q("A04", "Tata Steel's Q1 FY27 filing: did it carry an audit qualification, and what exactly does the stored field say?", "TATASTEEL", "Q1 FY27", None, "fact",
  "results_xbrl.filings for TATASTEEL; results_notes; the standalone vs consolidated filings",
  "read both basis filings -> state the field value -> say what it does NOT establish",
  "inferring 'no qualification' from 'Not applicable'; ignoring the standalone filing",
  gt="opin.TATASTEEL", cov="partial", note="field says 'Not applicable' for the consolidated unaudited filing; that is not proof of a clean opinion.",
  gap="NEW GAP: no opinion-type taxonomy, so 'no qualification' cannot be asserted from the store",
  why="tests reading a data field for what it is, not what it seems")
Q("A04", "Which companies filed a 'Statement on impact of audit qualification' with their latest results? How many, and which large caps?", "RELIANCE, TATASTEEL", "latest quarter", "2026-10-07", "list",
  "results_xbrl.filings (audit_opinion) grouped by symbol/period; results_notes for the qualification text",
  "filter filings on the declaration value -> count -> list large caps -> for two, read the notes chunk for the actual qualification",
  "listing companies without checking the quarter; presenting the count as the number of qualified opinions",
  cov="partial", note="the filings flag the statement exists (1,653 rows); the qualification text is not extracted as a field.",
  gap="NEW GAP: audit-qualification text is not extracted; only the filing flag exists",
  why="tests a governance screen where the store proves existence but not content")
Q("A04", "Yes Bank's latest quarter: what auditor opinion was filed, and is this an audited period?", "YESBANK", "Q2 FY27", None, "fact",
  "results_xbrl.filings (audit_opinion, audited, period_end); results_notes; the bank's results-notes chunk",
  "read the filing -> state the opinion field -> state audited/reviewed -> flag that bank taxonomies differ",
  "using the Ind AS template for a bank; assuming Q2 is audited",
  gt="opin.YESBANK", cov="yes",
  why="tests taxonomy awareness on a bank filing")
Q("A04", "Mankind ki subsidiary mein auditor resignation kab hui, aur kya file hua? (Hinglish)", "MANKIND", "Sep 2026", "2026-10-07", "date",
  "bse_announcements (symbol=MANKIND, headline) with NEWS_DT/DissemDT; the attachment if archived; results_notes",
  "find the announcement -> name the subsidiary -> state the date and what it says -> note if the reason is absent",
  "presenting a subsidiary auditor exit as the listed company's auditor resigning",
  gt="ann.MANKIND.auditor", cov="yes",
  why="tests entity-level precision in a governance event (parent vs subsidiary)")
Q("A04", "Milefur's statutory auditor resigned. When was it filed, and what reason was given?", "MILEFUR", "Sep 2026", None, "date",
  "bse_announcements (headline and dissemination time); the resignation attachment if it is in the archive; results_notes",
  "find the filing -> give the dissemination time -> look for the reason in the attachment -> if unavailable, say NOT IN DATA for the reason",
  "inventing a reason; conflating the appointment filing that follows with the resignation",
  gt="ann.MILEFUR.auditor", cov="partial", note="the resignation and date are in the metadata; the reason lives in the attachment and is not parsed.",
  gap="NEW GAP: announcement attachments are not text-extracted, so resignation reasons are NOT IN DATA",
  why="tests the metadata-versus-attachment boundary on a real auditor exit")
Q("A04", "Picturehouse's secretarial auditor resigned. Who was the firm and when did the filing land?", "PICTUREHS", "Sep 2026", None, "date",
  "bse_announcements (headline text, NEWS_DT); the attachment; results_notes",
  "read the headline for the firm's name -> give the timestamp -> separate secretarial from statutory auditor",
  "treating a secretarial auditor as the statutory auditor",
  gt="ann.PICTUREHS.secaud", cov="yes",
  why="tests auditor-role distinction inside a governance question")
Q("A04", "Is there any going-concern doubt flagged in the latest quarterly results of small caps? terse: going concern Q1FY27", "SUZLON, MILEFUR", "Q1-Q2 FY27", "2026-10-07", "NOT IN DATA",
  "results_notes chunks (auditor/going-concern wording); results_xbrl.filings.audit_opinion; bse_announcements",
  "search notes text for 'going concern' -> if the store has no tagged flag, say the data cannot answer it -> name what would be needed",
  "answering 'no' from silence; inferring going-concern status from a loss",
  cov="no", note="no going-concern flag exists; a text search over 23k note chunks is not a screen.",
  gap="NEW GAP: no going-concern flag and no opinion-type taxonomy in any store",
  why="tests a governance question the data genuinely cannot answer")
Q("A04", "emphasis-of-matter paragraphs in latest results filings", "TATASTEEL, SUZLON", "latest quarter", "2026-10-07", "NOT IN DATA",
  "results_xbrl.filings; results_notes; ar_facts",
  "check whether an EOM field or tag exists -> if not, state NOT IN DATA -> show what a good answer would cite",
  "substituting 'unmodified declaration' for an EOM check",
  cov="no", note="audit_opinion holds the declaration only; EOM is not extracted anywhere.",
  gap="NEW GAP: emphasis-of-matter paragraphs are not extracted or tagged",
  why="tests refusal with an explicit data-requirement statement")
Q("A04", "What were HDFC Bank's key audit matters in its latest annual report, and did any repeat?", "HDFCBANK", "FY26", "2026-10-07", "list",
  "ar_facts for HDFCBANK (auditor/KAM category); ar_docs for the report date; results_notes",
  "find the auditor's report section -> read KAMs -> compare with the prior year -> quote each",
  "using a generic auditor-report template; naming a KAM without the page",
  cov="partial", note="AR facts are extracted, but KAM headings are not a tagged category, so this relies on text search.",
  gap="G6", why="tests long-document governance extraction with page provenance")
Q("A04", "Suzlon's latest results: what did the auditor's declaration say?", "SUZLON", "Q1 FY27", None, "fact",
  "results_xbrl.filings for SUZLON; results_notes; the notes chunk",
  "read the filing -> state the declaration -> note the audited/reviewed status -> check for any qualification statement",
  "inventing a qualified opinion because the company has a history of losses",
  gt="opin.SUZLON", cov="partial", note="the field gives the declaration; the underlying report text is not extracted.",
  gap="NEW GAP: no opinion-type taxonomy",
  why="tests prior-belief resistance: a troubled company can still file an unmodified declaration")
Q("A04", "For Reliance and Tata Steel, do the standalone and consolidated filings carry the same auditor declaration in Q1 FY27?", "RELIANCE, TATASTEEL", "Q1 FY27", None, "fact",
  "results_xbrl.filings (consolidated field, audit_opinion, audited); results_notes (basis)",
  "pull both basis rows -> compare opinion and audited flags -> report divergence with the exact field values",
  "collapsing standalone and consolidated into one answer",
  gt="opin.RELIANCE", cov="partial", note="both basis rows exist; the flags differ in meaning, so equality is not a like-for-like comparison.",
  gap="NEW GAP: opinion field semantics differ by basis and taxonomy, with no controlled vocabulary",
  why="tests basis handling in a governance answer")
Q("A04", "What did the latest annual report say about auditor remuneration, and how fast is it rising?", "DIXON, KEI", "FY24-FY26", None, "fact",
  "ar_facts (auditor remuneration category) for both companies; ar_docs for the report years; results_notes",
  "find the remuneration note -> take two years -> compute the change -> state the basis",
  "comparing a standalone year with a consolidated year; inventing a fee",
  cov="partial", note="APR facts carry many item names; auditor fee may appear under a different label, so coverage is uneven.",
  gap="G6", why="tests two-year comparison inside long documents")
Q("A04", "Which companies have filed a 'Declaration of unmodified opinion' for every quarter in the last four quarters?", "RELIANCE, HAL, COALINDIA, PERSISTENT", "last 4 quarters", "2026-10-07", "list",
  "results_xbrl.filings grouped by symbol and period; results_notes",
  "group filings by company -> require the declaration in every quarter and both bases -> list -> exclude companies with missing quarters",
  "counting a missing filing as a clean opinion",
  cov="partial", note="the declaration field is unevenly populated ('Not applicable' for many unaudited quarters), so a clean streak is hard to prove.",
  gap="NEW GAP: opinion declaration is optional in the NSE XBRL and absent for many quarters",
  why="tests a screen that must handle missing data without imputing it")
Q("A04", "Titagarh's Q1 FY27 results: opinion declared, and does it match what the results notes say?", "TITAGARH", "Q1 FY27", None, "fact",
  "results_xbrl.filings; results_notes.docs (auditor_report) and the notes chunk; the results PDF page",
  "read the filing -> read the notes -> compare the two representations -> report any mismatch",
  "treating the notes flag (0/1) as the opinion text",
  gt="opin.TITAGARH", cov="partial", note="the notes store has a boolean auditor_report flag, not the opinion text.",
  gap="NEW GAP: results_notes stores auditor_report as a flag, not as an extractable opinion",
  why="tests cross-store agreement on a governance fact")

# ---------------------------------------------------------------- A05 (15)
Q("A05", "List the statutory auditor resignations filed in September 2026, with company and date. terse: auditor resignation Sep 2026", "MILEFUR, MANKIND, PICTUREHS", "Sep 2026", "2026-10-07", "list",
  "bse_announcements (SUBCATNAME='Resignation of Statutory Auditors', DissemDT); the attachments; results_notes",
  "filter the announcement category -> sort by dissemination time -> keep September -> report company, date, role (statutory vs secretarial)",
  "including secretarial auditors in a statutory list; using NEWS_DT instead of DissemDT",
  gt="ann.MILEFUR.auditor", cov="partial", note="the category is reliable but the attachment reason is not parsed.",
  gap="NEW GAP: announcement attachments are not text-extracted",
  why="tests a governance list that must respect the filing category and the date field")
Q("A05", "How many auditor-resignation and auditor-appointment filings are in the announcement store, and what does the gap between them say?", "MILEFUR, PICTUREHS", "2019-2026", None, "fact",
  "bse_announcements (SUBCATNAME counts) for 'Resignation of Statutory Auditors' and 'Appointment of Statutory Auditor/s'",
  "count both subcategories -> compare -> explain that appointments include routine rotations -> do not infer a churn rate",
  "presenting the ratio as an auditor-churn rate; ignoring rotations",
  cov="yes", note="counts are exact; interpretation is inference and must be labelled.",
  why="tests count-based reasoning with an interpretation guard")
Q("A05", "Kaynes Technology filed a 'Change in Management' on 13 May 2026. Who changed, in what role, and when did it take effect?", "KAYNES", "May 2026", None, "fact",
  "bse_announcements (symbol=KAYNES, headline, DissemDT); the attachment; results_notes",
  "locate the filing -> read the attachment for name and role -> state the effective date -> if unreadable, say NOT IN DATA",
  "inferring a CFO exit from the headline; giving an effective date not in the filing",
  gt="ann.KAYNES.mgmt", cov="partial", note="the headline and time are stored; the name and role are in the attachment.",
  gap="NEW GAP: KMP changes are not extracted into a person/role table",
  why="tests a KMP-change question where the event is known but the detail is not")
Q("A05", "CFO churn 2024-2026 listed companies", "KAYNES, PICTUREHS", "2024-2026", "2026-10-07", "list",
  "bse_announcements (headlines mentioning CFO/company secretary/resignation); results_notes; the annual report's director report",
  "search headlines by role words -> verify each is a KMP change -> state company, role, date -> mark unverifiable ones",
  "counting a board appointment as churn; using an interim appointment as the permanent exit",
  cov="partial", note="role is free text in the headline, so recall is limited and no person table exists.",
  gap="NEW GAP: no KMP person/role/date table for churn analysis",
  why="tests a multi-year governance screen with text-only evidence")
Q("A05", "TruAlt ke promoter ne kab pledge banaya, aur kitne shares ka? (Hinglish)", "TRUALT", "Sep 2026", None, "fact",
  "bse_announcements (TRUALT, pledge headline, DissemDT); the SAST/PIT attachment; shareholding if available",
  "find the pledge filing -> name the pledgor -> give the date -> state the quantity only if the filing states it -> skip the percentage if shareholding is absent",
  "inventing a pledge percentage; giving an intimation date as the creation date",
  gt="ann.TRUALT.pledge", cov="partial", note="the acreator and date are in the headline; the percentage needs the shareholding store, which is a 40-row stub.",
  gap="NEW GAP: shareholding/pledge percentages are not usable at scale (40 rows)",
  why="tests a pledge event where only the qualitative part is answerable")
Q("A05", "Which company appointed an auditor to a casual vacancy in the last quarter, and whose resignation created it?", "MANKIND, MILEFUR", "Q2 FY27", None, "list",
  "bse_announcements (SUBCATNAME='Appointment of Statutory Auditor/s', headline); the attachment; results_notes",
  "find appointment filings that name the outgoing firm -> pair with the preceding resignation -> report the pair or state the gap",
  "pairing firms by name similarity without a date window",
  cov="partial", note="appointment headlines often name the outgoing firm, but pairing is manual.",
  gap="NEW GAP: no auditor-firm entity table, so rotation chains cannot be built",
  why="tests relational reasoning across two announcement types")
Q("A05", "Welcorp filed an intimation about its credit rating. Who took the action and when was the press release issued?", "WELCORP", "Oct 2026", "2026-10-20", "date",
  "bse_announcements (WELCORP, headline, DissemDT); the CARE press release; results_notes",
  "read the headline -> name the agency -> give the dissemination date -> state whether it was an action or a review",
  "treating a rating review as an upgrade/downgrade; giving the announcement date as the rating date",
  gt="ann.WELCORP.rating", cov="yes",
  why="tests rating-action date and agency attribution")
Q("A05", "Which companies disclosed a SEBI penalty or show-cause notice in Q2 FY27, and what was the amount?", "POLICYBZR, CYIENT, PICTUREHS", "Q2 FY27", "2026-10-07", "list",
  "bse_announcements (headline search on SEBI/penalty); the attachment; results_notes contingent-liability note",
  "search headlines -> keep enforcement actions -> read the attachment for the amount -> exclude investor-relation boilerplate",
  "treating every SEBI mention as a penalty; giving an amount not stated",
  cov="partial", note="regulatory filings are only in the headline + attachment; amounts need the attachment text.",
  gap="NEW GAP: enforcement actions are not extracted as events with amounts",
  why="tests a red-flag screen with amount extraction risk")
Q("A05", "Which companies disclosed GST or income-tax demand notices in the last quarter, and were they material?", "KEI, POLYCAB, JUBLFOOD", "Q2 FY27", "2026-10-07", "list",
  "bse_announcements (tax/demand headlines); results_notes contingent liabilities; the attachment",
  "find tax-demand filings -> read the amount and the company's materiality statement -> rank by amount over PAT",
  "calling an ordinary assessment notice a red flag; assuming materiality without the ratio",
  cov="partial", note="tax notices appear as headlines; materiality needs the note text and PAT.",
  gap="NEW GAP: tax notices are not structured events with amounts",
  why="tests materiality judgement, not just event listing")
Q("A05", "Which companies filed a director resignation in September 2026, and did any cite a reason?", "PICTUREHS, MILEFUR", "Sep 2026", "2026-10-07", "list",
  "bse_announcements (resignation headlines, DissemDT); the attachment; results_notes",
  "filter resignation filings -> separate director, auditor and company secretary -> read reasons where present",
  "merging director and auditor resignations into one count",
  cov="partial", note="role is not a field; it must be read from the headline.",
  gap="NEW GAP: no board/KMP event table",
  why="tests role classification from free-text headlines")
Q("A05", "What is TruAlt's promoter pledge as a percentage of promoter holding in the latest quarter? terse: TRUALT pledge %", "TRUALT", "latest quarter", "2026-10-07", "NOT IN DATA",
  "shareholding (promoter_pledged_pct); bse_announcements; SAST disclosures",
  "check the shareholding store -> if the row is absent, say NOT IN DATA -> state that the pledge filing gives creation but not the percentage",
  "computing a percentage from the number of pledged shares without the promoter base",
  gt="shp.count", cov="no", note="shareholding has 40 rows total and no pledge percentage for most names.",
  gap="NEW GAP: shareholding store is a 40-row stub; pledge/holder percentages are not available at scale",
  why="tests an ownership question the store cannot answer, with evidence of why")
Q("A05", "Cluster of insider buying in Sep-Oct 2026: which promoters or KMPs bought, and how much? terse: insider buys Sep-Oct 2026", "SUZLON, TITAGARH", "Sep-Oct 2026", "2026-10-24", "NOT IN DATA",
  "insider_trades (symbol, acquirer, value_inr_lacs, transaction_type); bse_announcements PIT disclosures; the snapshot events table",
  "check insider_trades -> report row count -> state that PIT disclosures exist as announcements but are not extracted -> NOT IN DATA",
  "presenting an announcement headline as a completed transaction; inventing a value",
  gt="insider.count", cov="no", note="insider_trades has 0 rows; PIT disclosures are announcements only.",
  gap="NEW GAP: the insider-trades table is empty; insider buying/selling cannot be screened",
  why="tests an ownership/flow screen against an empty store")
Q("A05", "On 23 October 2026 Cyient saw a large bulk deal. Who sold, at what price, and how did the stock react?", "CYIENT", "2026-10-23", "2026-10-24", "fact",
  "bulk_block_deals (deal_date, client_name, side, qty, price); daily_price_delivery (close, change_pct) for the same date; bse_announcements",
  "read the deal row -> compute the deal value -> compare the deal price with the close -> report the day's return",
  "calling a bulk deal a block deal; valuing at the closing price",
  gt="deal.CYIENT.2026-10-23", cov="yes",
  why="tests deal-level arithmetic and the bulk-versus-block distinction")
Q("A05", "Did any company's auditor resign within a year of a qualified opinion? Name the company and the two dates.", "MILEFUR, MANKIND", "2023-2026", "2026-10-07", "list",
  "results_xbrl.filings (audit_opinion by year); bse_announcements (resignation filings); results_notes",
  "for each resignation, look back 12 months of filings for a qualification statement -> pair them -> report or say none found",
  "pairing by company name across subsidiaries; ignoring the subsidiary level",
  cov="partial", note="qualification flags exist; resignations are headlines. Joining the two is manual and subsidiary-blind.",
  gap="NEW GAP: no issuer/auditor entity resolution across parent and subsidiary filings",
  why="tests a governance join across two stores with an entity-resolution trap")
Q("A05", "Did any auditor resign citing 'other commitments' or lack of time in the last year? Kaun sa auditor ne reason diya? (Hinglish)", "PICTUREHS, MILEFUR", "2025-2026", "2026-10-07", "NOT IN DATA",
  "bse_announcements (resignation filings); the resignation attachments; results_notes",
  "find resignation filings -> check whether the reason text is available -> if only metadata, say the reason is NOT IN DATA",
  "inferring a reason from the category; quoting a template sentence as the reason",
  cov="partial", note="resignation filings are metadata; reasons sit in unparsed attachments.",
  gap="NEW GAP: announcement attachments are not text-extracted",
  why="tests a Hinglish governance question at the metadata boundary")

# ---------------------------------------------------------------- A06 (15)
Q("A06", "Which promoters created a fresh pledge over their shares between August and September 2026, and which were top-ups on an existing pledge?", "TRUALT, ROYAL, RELTD", "Aug-Sep 2026", "2026-10-01", "list",
  "bse_announcements (SAST/PIT pledge headlines, DissemDT); the pledge disclosures; shareholding (mostly unavailable)",
  "collect pledge filings -> read creation vs release from the headline -> separate new pledge from top-up -> state the pledgor",
  "counting a release as a creation; inferring a pledge percentage without the share base",
  gt="ann.TRUALT.pledge", cov="partial", note="creation/release is readable from headlines; top-up vs new needs the disclosure attachment.",
  gap="NEW GAP: pledge events are not structured (no quantity/percentage per pledgor)",
  why="tests red-flag screening from disclosure headlines")
Q("A06", "Which Q2 FY27 results notes disclose a related-party transaction that grew sharply year on year?", "ICICILIFE, NESTLEIND", "Q2 FY27", "2026-10-20", "list",
  "results_notes (note header/body, known_at); notes_fts search on 'related party'; results_xbrl where RPT is tagged",
  "search note chunks for related-party notes -> compare two periods if both are stated -> rank by growth -> quote the note",
  "treating an accounting-policy note as an RPT; comparing a half-year with a quarter",
  cov="partial", note="notes are stored and searchable, but RPT amounts are not extracted as structured facts.",
  gap="G11", why="tests a qualitative red-flag screen over freshly-ingested results notes")
Q("A06", "Which companies show receivables growing much faster than revenue in the last reported year?", "RVNL, NBCC, IRCON, KEC", "FY26", "2026-10-07", "ranking",
  "results_xbrl or annual_financials (revenue, receivables); results_notes working-capital note; AR balance-sheet facts",
  "pull revenue and receivables for two years -> compute growth both -> rank by the gap -> state the basis",
  "using a standalone number against a consolidated one; ranking on a single year without the base",
  cov="partial", note="receivables are not consistently tagged in XBRL across taxonomies.",
  gap="G11", why="tests a derived red-flag ranking with basis discipline")
Q("A06", "Which companies disclosed a tax or regulatory demand in Q2 FY27 that is large relative to their profit?", "KEI, POLYCAB, JUBLFOOD", "Q2 FY27", "2026-10-20", "ranking",
  "bse_announcements (tax/SEBI headlines); results_notes contingent-liability note; results_xbrl PAT for the denominator",
  "collect demands -> divide by trailing PAT -> rank -> state whether the company called it material",
  "calling every notice material; using a quarterly PAT against an annual demand without saying so",
  cov="partial", note="amounts and the materiality statement sit in attachments/notes; the ratio is manual.",
  gap="NEW GAP: enforcement/tax events are not extracted with amounts and no materiality ratio exists",
  why="tests materiality-based ranking rather than event listing")
Q("A06", "Welcorp disclosed a credit-rating intimation in October 2026. Was it an upgrade, a downgrade or a review, and how would you tell?", "WELCORP", "Oct 2026", "2026-10-20", "fact",
  "bse_announcements (headline, DissemDT); the CARE press release; results_notes",
  "read the headline -> open the release -> identify action vs review -> quote the rating and outlook",
  "calling every rating intimation a downgrade; quoting a rating without the agency",
  gt="ann.WELCORP.rating", cov="partial", note="the headline names CARE; the action needs the press release body.",
  gap="NEW GAP: rating actions are not structured (agency/old/new/outlook)",
  why="tests a governance-adjacent event where the headline under-determines the answer")
Q("A06", "Which companies wrote down inventory or took an impairment in Q1 FY27, and how large was it against EBITDA?", "TATASTEEL, JSWSTEEL, SAIL", "Q1 FY27", "2026-10-07", "list",
  "results_notes (exceptional items/impairment note); results_xbrl exceptional items and EBITDA; AR for goodwill",
  "find the note -> take the amount -> divide by EBITDA -> list -> separate inventory from goodwill impairment",
  "mixing an exceptional item with an operating cost; using a consolidated EBITDA for a standalone write-down",
  cov="partial", note="notes are stored; the XBRL exceptional-item concept is not mapped for every taxonomy.",
  gap="G11", why="tests red-flag quantification with a mapped concept risk")
Q("A06", "Which segment of which company swung from profit to loss last quarter, while the company reported a profit overall?", "ULTRACEMCO, HINDALCO, SRF", "Q1 FY27", "2026-10-07", "list",
  "results_xbrl segment facts (if tagged); deck segment slides; results_notes segment note",
  "read segment results -> find a sign change -> reconcile to the consolidated profit -> quote the segment",
  "using a revenue segment split as a profit split; ignoring unallocated costs",
  cov="partial", note="segment contexts exist in XBRL but are not mapped to a metric per taxonomy.",
  gap="G11", why="tests segment-level red-flag detection where the concept map is incomplete")
Q("A06", "Which companies have operating cash flow persistently below reported profit, and for how many years?", "RVNL, NBCC, IRCON", "FY23-FY26", "2026-10-07", "list",
  "annual_financials (cash flow, net profit); results_notes; AR cash-flow statement facts",
  "pull CFO and PAT for four years -> compute the gap each year -> keep companies with a persistent gap -> quote the series",
  "calling a one-year working-capital swing a red flag; using EBITDA for cash flow",
  cov="partial", note="annual_financials carries CFO for a subset; coverage differs by company.",
  gap="G11", why="tests multi-year cash-quality screening")
Q("A06", "Kisi company ne debt covenant breach ya restructuring disclose kiya kya? (Hinglish)", "SUZLON, TATASTEEL, JSWSTEEL", "Q2 FY26-Q2 FY27", "2026-10-07", "list",
  "results_notes (borrowing note); bse_announcements; results_xbrl finance cost and borrowings",
  "search notes for covenant/restructuring wording -> verify against the borrowing note -> quote the sentence",
  "inferring a breach from a high debt ratio",
  cov="partial", note="covenant disclosures are in notes text; no structured flag.",
  gap="G6", why="tests text-based red-flag detection with a false-positive guard")
Q("A06", "Which companies disclosed a plant shutdown or force majeure in the last quarter, and what did they say the financial effect was?", "SAIL, HINDALCO, SRF", "Q1-Q2 FY27", "2026-10-07", "list",
  "bse_announcements (shutdown/force majeure); results_notes; concall capacity items",
  "find shutdown announcements -> read the stated effect -> separate planned maintenance from unplanned -> quote",
  "treating planned capital repairs as a demand event",
  gt="cc.SAIL.capacity_and_projects", cov="partial", note="SAIL's advanced capital repairs are quoted; other shutdowns are headline-only.",
  gap="NEW GAP: no plant-event table (shutdown/force majeure) with capacity and duration",
  why="tests operational-event red-flag reading")
Q("A06", "Which companies are in a 5% or lower price band on results day, and did the band change before the announcement?", "DIXON, KEI, TITAGARH", "Q1-Q2 FY27", "2026-10-07", "list",
  "price_bands (band, date, remarks); bse_announcements for the results date; daily_price_delivery for the move",
  "join band rows to results dates -> note the band -> check whether the band was revised around the date",
  "assuming a 20% band for every stock; using the band after the event",
  gt="bands.span", cov="no", note="price_bands has only hundreds of dates across 2022-2026, so band-on-a-date is largely missing.",
  gap="G8", why="tests a surveillance-data question against a known coverage hole")
Q("A06", "Q1FY27 audit-qualification statements — how many", "TATASTEEL, SUZLON, MILEFUR", "Q1 FY27", "2026-10-07", "list",
  "results_xbrl.filings (audit_opinion='Statement on impact of audit qualification'); master_companies market_cap_tier",
  "filter filings by declaration -> join to the bucket -> count -> list mid-caps -> quote the declaration",
  "counting subsidiaries or duplicate basis rows twice",
  cov="partial", note="the statement flag exists; the qualification content does not.",
  gap="NEW GAP: audit-qualification text and a controlled opinion type are absent",
  why="tests a governance screen joined to market-cap buckets")
Q("A06", "Which companies' results notes mention a related-party loan or advance to a promoter-group entity?", "ICICILIFE, PICTUREHS, MILEFUR", "Q2 FY27", "2026-10-20", "list",
  "results_notes/notes_fts on 'loan' + 'related party'; the note chunk; bse_announcements",
  "search note text -> keep promoter-group recipients -> quote the note -> note the amount if given",
  "treating a subsidiary loan as a promoter loan; assuming a name in the note is a group entity",
  cov="partial", note="text search works; entity classification of the counterparty does not exist.",
  gap="NEW GAP: no related-party counterparty entity map",
  why="tests the hardest red flag: RPT direction and beneficiary")
Q("A06", "Which company changed its statutory auditor twice in three years, and is that a red flag here?", "MILEFUR, PICTUREHS, KAYNES", "FY24-FY26", "2026-10-07", "list",
  "bse_announcements (resignation + appointment subcategories); results_xbrl.filings; results_notes",
  "build a timeline per company -> count changes in 36 months -> compare with the statutory rotation rule -> label the flag",
  "counting a rotation required by law as a red flag; missing an interim appointment",
  cov="partial", note="filing categories allow a timeline, but firm identity is free text.",
  gap="NEW GAP: no auditor-firm entity table; rotation chains are manual",
  why="tests rule-aware red-flag judgement (rotation vs churn)")
Q("A06", "Promoter selling before results: which companies show it in the last two quarters? terse: promoter sale before results", "TRUALT, SUZLON, TITAGARH", "Q1-Q2 FY27", "2026-10-07", "NOT IN DATA",
  "insider_trades; SAST/PIT announcements; shareholding",
  "check the insider store -> report it is empty -> state that PIT filings are headlines only -> NOT IN DATA",
  "using a pledge filing as a sale; inferring selling from a price fall",
  gt="insider.count", cov="no", note="insider_trades has 0 rows; SAST/PIT transactions are not extracted.",
  gap="NEW GAP: no insider/SAST transaction store at scale",
  why="tests the seed red flag that the data cannot currently answer")

# ---------------------------------------------------------------- A07 (15)
Q("A07", "On 4 June 2024 the Nifty 50 fell 5.93%. What was the sector dispersion that day, and what kind of market move was it?", "index:Nifty 50", "2024-06-04", "2024-06-04", "explanation",
  "mkt_nse_index_daily (Nifty 50 and sector indices, date, pct_change, close); mkt_fii_dii_cash for the session",
  "read the index move -> read at least four sector indices -> order them -> classify as a broad risk-off with a PSU/financials epicentre",
  "explaining the cause with a document published after 4 June; inventing an election statement",
  gt="idx.Nifty 50.2024-06-04", cov="partial", note="the price side is exact; the causal document (election result) is not in any store.",
  gap="NEW GAP: no macro-event calendar for election results, verdict days or policy surprises",
  why="tests the seed market-move question: price yes, cause must be labelled")
Q("A07", "4 June 2024 wale hafte mein Nifty ka move kya tha, aur ek din ka number kaafi hai? (Hinglish)", "index:Nifty 50", "2024-05-31 to 2024-06-07", "2024-06-07", "fact",
  "mkt_nse_index_daily for 2024-05-31 and 2024-06-07; daily sector indices in between",
  "take both closes -> compute the weekly return -> compare with the single-day fall -> state that a one-day look overstates the drawdown",
  "reporting the single-day fall as the weekly move",
  gt="idx.Nifty 50.2024-06-07", cov="yes",
  why="tests window choice, the most common analytical error in 'why did it fall' questions")
Q("A07", "On 4 June 2024, Nifty PSU Bank fell 15.14% while Nifty FMCG rose 0.95%. What does that pair tell you about positioning?", "index:Nifty PSU Bank, index:Nifty FMCG", "2024-06-04", "2024-06-04", "explanation",
  "mkt_nse_index_daily for both sector indices on the date; daily_price_delivery for the constituents; mkt_fii_dii_cash",
  "read both moves -> identify the pre-event positioning (state-owned vs defensive) -> state the rotation without naming a cause that is not stored",
  "claiming a sector rotation from one day alone; attributing the cause to a document after the date",
  gt="idx.Nifty PSU Bank.2024-06-04", cov="partial", note="both index moves are exact; the positioning explanation is inference.",
  why="tests dispersion reasoning and label discipline")
Q("A07", "4 Jun 2024 top losers, turnover floor applied", "RECLTD, PFC, BHEL, ADANIPORTS, SAIL", "2024-06-04", "2024-06-04", "ranking",
  "daily_price_delivery (change_pct, turnover) for the date; master_companies ownership/PSU flags if present",
  "rank losers above a turnover floor -> group by ownership (PSU vs private) -> report the concentration",
  "ranking illiquid microcaps with no turnover floor; treating F&O-linked lenders as a sector",
  gt="px.RECLTD.2024-06-04", cov="partial", note="returns are exact; the ownership grouping comes from master data that is partly stale.",
  gap="G4", why="tests a loser ranking with a liquidity floor and a grouping step")
Q("A07", "The Union Budget 2026-27 was presented on Sunday 1 February 2026. What did the Nifty 50 do on the first trading session after it?", "index:Nifty 50", "2026-02-01 to 2026-02-02", "2026-02-02", "fact",
  "mkt_nse_index_daily for 2026-02-02 and the preceding session; the Budget policy events with published_at",
  "confirm 1 February is not a trading day -> take the next session -> report the move -> quote the Budget-line event if used",
  "reporting a 1 February close that does not exist; assuming a Saturday/Sunday session",
  gt="idx.Nifty 50.2026-02-02", cov="partial", note="the session move is exact; the Budget-to-sector linkage needs the policy events table.",
  why="tests holiday-aware event dating, a repeated real-world trap")
Q("A07", "What did the Nifty 50 do on the first session after the 2025-26 Budget on Saturday 1 February 2025?", "index:Nifty 50", "2025-02-01 to 2025-02-03", "2025-02-03", "fact",
  "mkt_nse_index_daily for 2025-02-03 and the prior session; policy events published around the Budget",
  "find the next trading day -> report the move -> compare with the 2026 Budget session",
  "using the Budget speech date as the market reaction date",
  gt="idx.Nifty 50.2025-02-03", cov="yes",
  why="tests the same trap one year earlier and cross-year comparison")
Q("A07", "On 23 March 2020 the Nifty 50 fell 12.98%. What evidence in the store dates the cause, and what is NOT in the store?", "index:Nifty 50", "2020-03-23", "2020-03-23", "explanation",
  "mkt_nse_index_daily; mkt_fii_dii_cash; the national lockdown is a macro event that must be cited if present",
  "report the move -> search macro_events for a lockdown entry -> if absent, label the cause as external knowledge and state NOT IN DATA for a stored document",
  "citing a later document as contemporaneous evidence",
  gt="idx.Nifty 50.2020-03-23", cov="partial", note="the index move is exact; no stored contemporaneous document for the lockdown.",
  gap="NEW GAP: no stored macro event for the 2020 lockdown",
  why="tests a historical crash question where the data supports the price but not the cause")
Q("A07", "On 1 February 2021 the Nifty 50 rose 4.74%. Which policy lines in the store were published around that date, and do they explain it?", "index:Nifty 50", "2021-02-01", "2021-02-01", "explanation",
  "mkt_nse_index_daily; policy_events (published_at, policy_name, direction); pib_releases for the date window",
  "read the index move -> pull policy events in a +/-3 day window -> state whether any is large enough to explain it -> label the residual as inference",
  "asserting a Budget cause from a policy row with no amount; using a post-date event",
  gt="idx.Nifty 50.2021-02-01", cov="partial", note="the index move is exact; policy coverage around 2021-02 is thin.",
  gap="G10", why="tests policy-evidence retrieval for a known market move")
Q("A07", "On 24 February 2022 the Nifty 50 fell 4.78%. What was happening in crude, and does the crude move support a geopolitical read?", "index:Nifty 50, commodity:crude_brent", "2022-02-24", "2022-02-24", "explanation",
  "mkt_nse_index_daily; mkt_commodity_daily (crude_brent) for the date; macro_events",
  "read the index move -> read Brent close -> state the joint move -> label the geopolitical cause as inference if no document is stored",
  "stating the invasion as a stored fact; using the closing price to time an intraday event",
  gt="cmd.crude_brent.2022-02-24", cov="partial", note="index and crude closes are exact; no stored event document for the invasion.",
  gap="NEW GAP: no macro-event calendar for geopolitical shocks",
  why="tests cross-series corroboration of a market move")
Q("A07", "On 24 September 2026 the Nifty 50 fell 1.64% but PB Fintech fell 36%. Was this a market move or a stock event?", "index:Nifty 50, POLICYBZR", "2026-09-24", "2026-09-25", "explanation",
  "mkt_nse_index_daily; daily_price_delivery for POLICYBZR; bse_announcements around the date; the analyst call intimation",
  "compare the index and stock moves -> ratio them -> check whether other constituents moved together -> classify as idiosyncratic",
  "attributing the stock crash to the index; using the 27 September clarification as if known on the 24th",
  gt="px.POLICYBZR.2026-09-24", cov="partial", note="both moves are exact; the reason inside the analyst call is not stored as text.",
  gap="G6", why="tests idiosyncratic-versus-systematic attribution with an as-of cut")
Q("A07", "On 7 April 2025 the Nifty 50 fell 3.24%. Which stored policy event is closest, and does the date match?", "index:Nifty 50", "2025-04-07", "2025-04-07", "fact",
  "mkt_nse_index_daily; macro_events (event_date); policy_events (published_at); pib_releases",
  "read the index move -> pull events in a +/-3 day window -> state which (if any) matches -> do not force a match",
  "matching a tariff headline from a different month; asserting a cause from proximity alone",
  gt="idx.Nifty 50.2025-04-07", cov="partial", note="the index move is exact; the tariff-event store has no 7 April 2025 entry.",
  gap="G12", why="tests event-date matching discipline on a tariff-driven selloff")
Q("A07", "The RBI hiked the repo rate 25 bps to 5.50% on 7 October 2026. Did the Nifty 50 or the rate-sensitive indices move that day, and can the day's move be separated from the hike?", "policy:pol.rbi_hike, index:Nifty 50, index:Nifty Bank, index:Nifty Auto", "2026-10-07", "2026-10-08", "fact",
  "policy_events (id 21732: policy_name, direction_for_industry, sectors, published_at; quote_ok=1, source_kind=doc, source_id=12803); mkt_nse_index_daily for 2026-10-07 (Nifty 50, Nifty Bank, Nifty Auto, Nifty Metal); the prior session 2026-10-06 as the base",
  "read the policy row and its document date -> read the same-day index moves -> compare the rate-sensitive indices with the broad index -> state that one session is weak evidence for a single cause",
  "assuming a policy event must show up in the index; calling a rate-sensitive sector's move proof of the hike",
  gt="pol.rbi_hike", cov="partial", note="the policy row and the index moves are exact; the store has no attribution model, so cause and effect cannot be measured.",
  gap="NEW GAP: no event-study harness to separate a policy day from the tape", why="tests event-day attribution discipline when the policy itself is dated")
Q("A07", "On 23 October 2026 FIIs bought and DIIs bought much more. Who absorbed the supply, and did the index fall anyway?", "index:Nifty 50", "2026-10-23", "2026-10-24", "fact",
  "mkt_fii_dii_cash (fii_net_cr, dii_net_cr, nifty_change_pct); mkt_nse_index_daily",
  "read both flows -> read the index move -> state that DII buying dominated -> avoid inferring causality from one session",
  "calling a single-session flow a trend; saying FIIs sold when the net is positive",
  gt="flow.2026-10-23", cov="yes",
  why="tests flow-versus-price reading, with a sign trap")
Q("A07", "For September 2026, what were the aggregate FII and DII cash flows, and how many sessions are they based on?", "index:Nifty 50", "2026-09", "2026-10-01", "fact",
  "mkt_fii_dii_cash (daily rows aggregated by month); mkt_nse_index_daily for the month",
  "sum both flow columns for the month -> count sessions -> state the net direction for each -> compare with the month's index move",
  "averaging instead of summing; using partial-month data",
  gt="flow.2026-09", cov="yes",
  why="tests monthly aggregation with a session count")
Q("A07", "On 4 June 2024 the Nifty IT fell only 0.6% while Nifty Energy fell 12.47%. Kaun sa sector sabse zyada gira, aur kyun? (Hinglish)", "index:Nifty IT, index:Nifty Energy", "2024-06-04", "2024-06-04", "explanation",
  "mkt_nse_index_daily for both indices; the sector index list; daily_price_delivery for large constituents",
  "rank the sector indices -> state the two extremes -> explain the IT defensiveness only from evidence (FX, US exposure) -> label inference",
  "inventing a sector reason; using a post-date report",
  gt="idx.Nifty Energy.2024-06-04", cov="partial", note="the sector moves are exact; the reason is inference.",
  why="tests a Hinglish sector-dispersion question")

# ---------------------------------------------------------------- A08 (15)
Q("A08", "Siemens fell 42.93% on 7 April 2025. Was that a real loss of value? Explain with the corporate-action record.", "SIEMENS", "2025-04-07", "2025-04-07", "explanation",
  "corporate_actions (action_type=MERGER, subject=Demerger, ex_date); daily_price_delivery (close, prev_close, change_pct); adjusted price series",
  "read the corporate action -> read the raw fall -> state that the ex-date adjustment explains it -> use the adjusted series to quantify the real return",
  "calling a demerger ex-date fall a crash; using the raw series for a total-return claim",
  gt="ca.SIEMENS.demerger", cov="yes",
  why="tests corporate-action awareness, the single most misleading 'why did it fall' case")
Q("A08", "PB Fintech fell 36% on 24 September 2026. What was scheduled that day, and what did the exchange ask for afterwards?", "POLICYBZR", "2026-09-24 to 2026-09-27", "2026-09-27", "explanation",
  "daily_price_delivery; bse_announcements (analyst-call intimation 24 Sep, clarification on price movement); the call transcript if stored",
  "read the fall -> find the same-day analyst-call intimation -> find the later exchange clarification -> state that the reason text is not in the store",
  "asserting the call content; using the 27 September clarification as known on the 24th",
  gt="px.POLICYBZR.2026-09-24", cov="partial", note="the fall and the two filings are exact; the call content is not stored as text.",
  gap="NEW GAP: price-movement clarifications are filings without extracted reasons",
  why="tests an event chain (fall -> call -> clarification) with a strict as-of")
Q("A08", "Kaynes fell 20.15% on 14 May 2026. What did the company file the previous evening, and what else was in that filing batch?", "KAYNES", "2026-05-13 to 2026-05-14", "2026-05-14", "explanation",
  "daily_price_delivery; bse_announcements for 2026-05-13 (results outcome, financial results, change in management); results_notes",
  "list the prior-evening filings -> read the results and the management change -> state which is the better explanation and why",
  "picking one filing without listing the batch; asserting causality from timing alone",
  gt="ann.KAYNES.mgmt", cov="partial", note="the filings and dates are exact; the actual content sits in attachments.",
  gap="NEW GAP: announcement attachments are not text-extracted",
  why="tests multi-filing event attribution")
Q("A08", "Trent fell 14.77% on 7 April 2025. Was there a company disclosure before the open, and what kind of update was it?", "TRENT", "2025-04-05 to 2025-04-07", "2025-04-07", "explanation",
  "bse_announcements (TRENT, update for Q4/FY, DissemDT); daily_price_delivery; corporate_actions (no ex-date that day)",
  "find the pre-market update -> read its category -> rule out a corporate action -> state what is and is not established",
  "calling a business update a results filing; ignoring the market-wide fall that day",
  gt="ann.TRENT.update2025", cov="partial", note="the update filing and the fall are exact; the update's content is in the attachment.",
  gap="NEW GAP: no parsed text for business updates",
  why="tests separating a company update from a market-wide selloff")
Q("A08", "REC Ltd and PFC both fell more than 23% on 4 June 2024 with no company filing that day. What explains a move of that size in a lender?", "RECLTD, PFC", "2024-06-04", "2024-06-04", "explanation",
  "daily_price_delivery (both symbols, change_pct); bse_announcements (absence of filing); mkt_nse_index_daily (Nifty PSU Bank); mkt_fii_dii_cash",
  "show the stock moves -> show no company filing -> show the PSU bank index move -> state that the cause is sector/market, not company",
  "inventing a company-specific cause; ignoring the sector index",
  gt="px.RECLTD.2024-06-04", cov="partial", note="all price facts are exact; the political cause is not in the store.",
  gap="NEW GAP: no election-result macro event",
  why="tests the no-filing case: a large move with no company disclosure")
Q("A08", "BHEL 4 Jun 2024 volume and delivery", "BHEL", "2024-06-04", "2024-06-04", "fact",
  "daily_price_delivery (volume, turnover, delivery_pct); the 20-day average volume from the same table",
  "read the day's volume -> compare with the trailing average -> read the delivery share -> state whether it was panic selling or delivery-based",
  "treating delivery percentage as a sentiment score; ignoring the volume base",
  gt="px.BHEL.2024-06-04", cov="yes",
  why="tests volume/delivery interpretation on a crash day")
Q("A08", "Adani Ports fell 21.15% on 4 June 2024. How does that compare with the Nifty 50 and what does the delivery data add?", "ADANIPORTS", "2024-06-04", "2024-06-04", "fact",
  "daily_price_delivery; mkt_nse_index_daily; the stock's prior-week returns",
  "compare the stock return with the index -> read delivery -> place the move in the stock's own volatility context",
  "calling a 21% move normal because the index fell; ignoring the prior trend",
  gt="px.ADANIPORTS.2024-06-04", cov="yes",
  why="tests excess-move framing, not raw return")
Q("A08", "SAIL fell 20.02% on 4 June 2024 and Nifty Metal fell 10.63%. What share of the stock move is explained by the sector?", "SAIL", "2024-06-04", "2024-06-04", "explanation",
  "daily_price_delivery (SAIL); mkt_nse_index_daily (Nifty Metal); peer steel returns",
  "compute the stock-minus-sector residual -> state the residual -> note that a single day cannot separate beta from stock effect",
  "claiming the residual is company-specific with no filing evidence",
  gt="px.SAIL.2024-06-04", cov="yes",
  why="tests a simple market-model residual and its limits")
Q("A08", "Suzlon fell 9.65% on 28 July 2026 and the results were filed at 15:11 that day. What is the correct event window?", "SUZLON", "2026-07-28", "2026-07-28", "explanation",
  "results_xbrl.filings (dissem_ts); daily_price_delivery (intraday close, change_pct); bse_announcements",
  "check the filing time against market hours -> if filed during the session, the same-day move is contaminated -> state the window that is clean",
  "using the full-day return as the reaction to an intraday filing",
  gt="px.SUZLON.2026-07-28", cov="partial", note="filing time and close are exact; there is no intraday price series to isolate the post-filing move.",
  gap="NEW GAP: no intraday bars, so intraday-filing event windows cannot be cleanly measured",
  why="tests event-window construction with filing timestamps")
Q("A08", "Bharat Electronics fell 4.46% on 28 July 2026, the session after its results. Was the market reaction consistent with the numbers?", "BEL", "2026-07-28", "2026-07-28", "explanation",
  "results_xbrl.filings (dissem_ts 27 Jul 16:38); daily_price_delivery 27 and 28 Jul; XBRL revenue/PAT for Q1 FY27",
  "confirm the filing was after close -> use the next session -> compare the move with the reported numbers and guidance",
  "using the filing-day move; assuming a negative reaction implies bad numbers",
  gt="px.BEL.2026-07-28", cov="partial", note="the move and the filing time are exact; the surprise component needs consensus, which is not stored.",
  gap="NEW GAP: no consensus/estimate store, so 'beat or miss' cannot be measured",
  why="tests post-close event handling and the missing-expectations problem")
Q("A08", "Mankind Pharma fell 4.13% on 31 July 2026 after results the previous evening. What two filings should you check before calling it a results reaction?", "MANKIND", "2026-07-30 to 2026-07-31", "2026-07-31", "explanation",
  "results_xbrl.filings (dissem_ts); bse_announcements for 30-31 July; the subsidiary auditor-resignation filing on 28 Sep is NOT relevant here",
  "list filings in the window -> separate results from other disclosures -> check the earlier subsidiary event date -> rule it out",
  "importing the September auditor news into a July reaction; using the filing-day move",
  gt="px.MANKIND.2026-07-31", cov="yes",
  why="tests an as-of discipline trap where a later governance event tempts the answer")
Q("A08", "KEI rose 9.49% on 4 August 2026 after results filed at 20:52 on 3 August. What did the numbers say about margin?", "KEI", "2026-08-03 to 2026-08-04", "2026-08-04", "explanation",
  "results_xbrl.filings (dissem_ts); daily_price_delivery for 3-4 Aug; XBRL revenue and margin; the margin commentary item",
  "confirm the after-close filing -> use the next session -> compute the margin change -> link to the FY26 margin statement",
  "using the 3 August move; treating a one-day 9.5% move as proof of a trend",
  gt="cc.KEI.margin_and_cost_commentary", cov="partial", note="the margin statement is quoted; the Q1 margin arithmetic needs XBRL cost lines.",
  gap="G11", why="tests an after-close event window plus a margin check")
Q("A08", "Polycab fell 3.83% on 17 July 2026, the day after results filed at 15:59. What was the actual reaction window?", "POLYCAB", "2026-07-16 to 2026-07-17", "2026-07-17", "explanation",
  "results_xbrl.filings (dissem_ts 16 Jul 15:59); daily_price_delivery 16 and 17 Jul",
  "check the filing time -> note it was during the session -> state that the 16th is partly contaminated and the 17th is the cleaner day",
  "treating the 16th as a pre-event day",
  gt="px.POLYCAB.2026-07-17", cov="yes",
  why="tests an intraday-filing window choice with no clean data")
Q("A08", "Titagarh rose 2.06% on 13 August 2026 after results the previous evening. Was the reaction large relative to its own volatility?", "TITAGARH", "2026-08-12 to 2026-08-13", "2026-08-13", "explanation",
  "daily_price_delivery (13 Aug change, 20-day average absolute move); results_xbrl.filings (dissem_ts 12 Aug 19:56); bse_announcements",
  "compute the move -> compute the trailing average absolute move -> state whether it is a meaningful surprise -> avoid calling it a miss/beat",
  "calling a 2% move a 'strong reaction' without a volatility base",
  gt="px.TITAGARH.2026-08-13", cov="yes",
  why="tests reaction-size normalisation")
Q("A08", "Dixon fell 2.02% on 31 July 2026 but the results were filed at 18:12, after the close. Kaun sa din ka move actually the reaction hai? (Hinglish)", "DIXON", "2026-07-31 to 2026-08-03", "2026-08-03", "explanation",
  "results_xbrl.filings (dissem_ts); daily_price_delivery for 31 Jul and 3 Aug; the pre-close move",
  "confirm after-close filing -> name the next session as the reaction day -> give both moves -> explain the contamination rule",
  "using the same-day fall as the results reaction",
  gt="px.DIXON.2026-08-03", cov="yes",
  why="tests an Hinglish event-window question with an after-close filing")

# ---------------------------------------------------------------- A09 (15)
Q("A09", "Copper went from 5.0875 on 20 May 2024 to 6.559 on 30 September 2026. How would that hit a cable maker's margin, and what has actually happened to KEI's margin?", "KEI, POLYCAB, commodity:copper", "2024-05-20 to 2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (copper, both dates); ar_facts (copper share of raw material); concall margin commentary; XBRL gross margin by quarter",
  "state the copper move -> get copper's share of cost from the AR -> compute the gross-cost impact at unchanged prices -> compare with the realised margin -> state pass-through",
  "assuming full pass-through; inventing a cost share; using the copper series after its last date",
  gt="cmd.copper.2026-09-30", cov="partial", note="both copper closes are exact; the cost share must be hand-read from the AR, with no structured input-cost table.",
  gap="NEW GAP: no company input-cost-share table; copper exposure is prose in the AR",
  why="tests the seed copper-to-cable reasoning chain end to end")
Q("A09", "What share of a cable maker's raw-material cost is copper, and where in the filing is it stated?", "POLYCAB, KEI", "FY26", None, "fact",
  "ar_facts (raw material consumed, cost of materials); results_notes; the AR notes on material cost",
  "find the material-cost note -> isolate copper/ aluminium -> divide by total material cost -> cite document and page",
  "quoting an industry rule of thumb as a filing number; mixing standalone and consolidated",
  cov="partial", note="the AR facts carry cost lines but not a copper-only split for every year.",
  gap="G6", why="tests cost-structure extraction with a page citation")
Q("A09", "Copper is up about 29% from May 2024. Does that help Hindustan Copper more than it hurts the cable makers, and why?", "HINDCOPPER, KEI, commodity:copper", "2024-05-20 to 2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily; results_xbrl/ar_facts for HINDCOPPER revenue and cost; cable-maker margin",
  "separate producer (price taker, margin up) from converter (cost up, pass-through lag) -> quantify each only from filings",
  "assuming a producer's margin rises one-for-one with price; ignoring hedging",
  gt="cmd.copper.2026-09-30", cov="partial", note="the commodity series is exact; HINDCOPPER's quarterly numbers are thin.",
  gap="G11", why="tests the same input on both sides of the value chain")
Q("A09", "Brent was 99.08 on 24 February 2022 and 103.53 on 30 September 2026. Kaise crude ka asar paint companies ke margin par padta hai? (Hinglish)", "ASIANPAINT, commodity:crude_brent", "2022-02-24 to 2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (crude_brent); ar_facts (crude-derivative share of material cost); concall margin commentary; XBRL gross margin",
  "state the crude path -> trace it to crude-linked inputs (solvents, resins) -> take the cost share from the AR -> show the margin history in past crude moves",
  "saying paints are 'crude-linked' without a share; assuming immediate pass-through",
  gt="cmd.crude_brent.2026-09-30", cov="partial", note="crude closes are exact; the derivative cost share is AR prose.",
  gap="NEW GAP: no derived-input cost map (crude -> solvents/resins) per company",
  why="tests a second-order commodity chain, not a direct input")
Q("A09", "How much of an airline's cost is fuel, and what does a $4 move in Brent do to IndiGo's EBITDA?", "INDIGO, commodity:crude_brent", "FY27", "2026-10-07", "explanation",
  "ar_facts/airline cost note (fuel share); concall cost commentary; mkt_commodity_daily; results_xbrl EBITDA",
  "get the fuel share -> convert Brent to ATF with a stated assumption -> compute the EBITDA sensitivity -> state that the ATF crack is an assumption",
  "using Brent directly as ATF; presenting a sensitivity as a reported number",
  gt="cc.INDIGO.demand_commentary", cov="partial", note="the cost commentary is quoted; the fuel share and crack must be assembled by hand.",
  gap="NEW GAP: no ATF/crack series and no fuel-share field",
  why="tests a sensitivity with an explicitly declared assumption")
Q("A09", "Crude at $103 should hurt tyre makers through carbon black and synthetic rubber. Which listed tyre company is most exposed, and what does the AR say?", "APOLLOTYRE, MRF, BALKRISIND, commodity:crude_brent", "2026-09-30", "2026-10-07", "ranking",
  "ar_facts (raw material note by company); concall cost commentary; mkt_commodity_daily",
  "collect raw-material mixes -> rank by crude-linked share -> check each company's stated pass-through -> report the ranking with shares",
  "ranking by market cap instead of exposure; assuming the same mix for all tyre makers",
  gt="cmd.crude_brent.2026-09-30", cov="partial", note="crude close exact; the per-company raw-material mix is AR text, unevenly extracted.",
  gap="NEW GAP: no product-level raw-material mix table",
  why="tests a cross-company exposure ranking")
Q("A09", "Crude at $103: what happens to the oil marketing companies' marketing margin, and what did IOC or BPCL say about under-recovery?", "IOC, BPCL, commodity:crude_brent", "FY27", "2026-10-07", "explanation",
  "concall_facts (margin_and_cost_commentary); results_notes; mkt_commodity_daily; XBRL marketing margin proxies",
  "state the crude level -> state the retail-price setting rule -> read management's under-recovery comment -> separate policy from market",
  "assuming retail prices follow crude; inventing an under-recovery number",
  gt="cmd.crude_brent.2026-09-30", cov="partial", note="the crude level is exact; marketing margins need segment data and the price-setting rule is policy, not market.",
  gap="NEW GAP: no daily retail fuel price series to compute marketing margin",
  why="tests a policy-intermediated commodity transmission")
Q("A09", "Coal is a fuel input for NTPC and Tata Power. The coal series ends in December 2025; can you still answer a 2026 coal-cost question?", "NTPC, TATAPOWER, commodity:coal_newcastle", "2026", "2026-10-07", "NOT IN DATA",
  "mkt_commodity_daily (coal_newcastle) last date; results_notes fuel-cost note; concall cost commentary",
  "check the series end -> report zero rows after 2025-12-26 -> state that a 2026 coal-cost answer must use company fuel-cost disclosures, labelled as such",
  "extrapolating a 2026 coal price; presenting a stale series as current",
  gt="coal.after2025", cov="no", note="coal_newcastle has 0 rows after 2025-12-26, so no 2026 coal transmission can be evidenced from the series.",
  gap="G12", why="tests a stale-series refusal, the exact gap flagged in the seed list")
Q("A09", "US HRC 1,275 hai — Indian tube maker ke liye kaun sa price matter karta hai? (Hinglish)", "APLAPOLLO, JSWSTEEL, commodity:steel_hrc_us", "2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (steel_hrc_us); ar_facts/notes on HRC sourcing; concall margin commentary; domestic steel price commentary",
  "state the US benchmark -> state that the Indian input is domestic HRC -> find the domestic price or pass-through -> refuse to use the US series as the Indian price",
  "treating US HRC as the Indian procurement price; ignoring import parity and duties",
  gt="cmd.steel_hrc_us.2026-09-30", cov="partial", note="the US benchmark is exact; the Indian HRC price is not in the store.",
  gap="NEW GAP: no domestic steel price series; only a US HRC benchmark",
  why="tests benchmark-versus-procurement-price discipline")
Q("A09", "Gold was 2,028 on 7 August 2020 and 4,186.7 on 30 September 2026. Kaun jeetta hai—jeweller ya gold-loan NBFC? (Hinglish)", "TITAN, MUTHOOTFIN, commodity:gold", "2020-08-07 to 2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (gold); results_xbrl for both companies; concall commentary on gold price; AR inventory/LTV notes",
  "state the gold move -> jeweller: inventory gain vs demand destruction -> lender: LTV and disbursement effect -> compare from filings, not intuition",
  "assuming jewellers always win on gold; ignoring the gold-loan LTV cap",
  gt="cmd.gold.2026-09-30", cov="partial", note="gold closes are exact; the LTV rule is regulatory, not in the store.",
  gap="NEW GAP: no gold-loan LTV/regulatory parameter store",
  why="tests opposite-sign transmission from one commodity")
Q("A09", "Aluminium was 3,285 on 30 September 2026. Who gains and who loses among Hindalco, Vedanta and a downstream user?", "HINDALCO, VEDL, commodity:aluminium", "2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily; results_xbrl for the producers; ar_facts downstream input note",
  "state the price -> producer margin vs downstream cost -> check each company's integration -> rank",
  "treating an integrated producer as a pure price taker",
  gt="cmd.aluminium.2026-09-30", cov="partial", note="the price is exact; integration levels are AR prose.",
  gap="NEW GAP: no integration/cost-curve table",
  why="tests value-chain sign reasoning for a metal")
Q("A09", "iron ore series — SAIL and JINDALSTEL 2026 margin", "SAIL, JINDALSTEL, commodity:iron_ore_62", "2026", "2026-10-07", "explanation",
  "mkt_commodity_daily (iron_ore_62 last date); ar_facts iron-ore cost note; results_xbrl",
  "check the series end -> state the last observation -> if it is current, compute the input move -> else label the limit",
  "quoting a 2025 price as the 2026 cost; ignoring captive mines",
  cov="partial", note="the iron-ore series is present into 2026-10; captive-mining share is the bigger driver and is AR prose.",
  gap="NEW GAP: no captive-versus-merchant input share",
  why="tests input-series freshness plus the captive-mine caveat")
Q("A09", "Natural gas was 3.026 on 30 September 2026. What does that do to a urea maker's cost, given administered prices?", "RCF, CHAMBLFERT, commodity:natural_gas", "2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (natural_gas); ar_facts gas cost note; policy_events for subsidy/price rules",
  "state the gas price -> state the administered urea price -> compute the margin effect only under the policy rule -> label the policy dependency",
  "treating gas cost as fully passable when the output price is administered",
  gt="cmd.natural_gas.2026-09-30", cov="partial", note="the gas close is exact; the subsidy rule is not a structured parameter.",
  gap="G10", why="tests a commodity chain whose transmission is policy-mediated")
Q("A09", "Copper is also an input for switchgear and transformers. Does the SIEMENS/ABB margin tell the same story as the cable makers'?", "SIEMENS, ABB, commodity:copper", "FY26-FY27", "2026-10-07", "explanation",
  "concall margin commentary for SIEMENS/ABB; ar_facts material cost; mkt_commodity_daily; XBRL gross margin",
  "compare copper intensity and pricing power -> show the two margin paths -> state why equipment makers pass through more slowly",
  "assuming every copper user has the same pass-through",
  gt="cmd.copper.2026-09-30", cov="partial", note="copper is exact; per-company copper intensity is not stored.",
  gap="NEW GAP: no input-intensity table by industry",
  why="tests comparing pass-through across two copper users")
Q("A09", "A copper spike hits cable makers, who sell to EPC contractors on fixed-price contracts. Who eats the loss, and how do you prove it?", "KEC, POLYCAB, commodity:copper", "FY26-FY27", "2026-10-07", "explanation",
  "concall material-cost commentary for KEC; contract price-variation clauses in the AR; mkt_commodity_daily",
  "map the chain -> check for price-variation clauses -> read KEC's margin in a copper-up quarter -> state who bears it",
  "assuming fixed-price means no pass-through; ignoring escalation clauses",
  gt="cmd.copper.2024-05-20", cov="partial", note="the copper move is exact; contract clauses are AR prose with no structured flag.",
  gap="G6", why="tests second-order contractual transmission")

# ---------------------------------------------------------------- A10 (15)
Q("A10", "The rupee went from 81.48 on 30 September 2022 to 96.05 on 30 September 2026. Which listed exporters gained most, and how do you measure it?", "TCS, INFY, SUNPHARMA, commodity:usdinr", "2022-09-30 to 2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (usdinr); results_xbrl revenue and margins; ar_facts geographic/currency exposure; concall FX commentary",
  "state the depreciation -> find each company's USD revenue share -> compute the translated-revenue effect -> check the reported margin path",
  "multiplying total revenue by the FX move; ignoring hedging and local-currency costs",
  gt="cmd.usdinr.2026-09-30", cov="partial", note="both FX points are exact; the USD revenue share is AR prose.",
  gap="NEW GAP: no currency-exposure table per company",
  why="tests the seed rupee-to-IT question with a measured exposure")
Q("A10", "Rupee depreciation helps Infosys but hurts importers. For a pharma exporter, what are the two opposing channels?", "SUNPHARMA, commodity:usdinr", "FY27", "2026-10-07", "explanation",
  "concall FX commentary; ar_facts geographic split and imported API cost; results_xbrl margin",
  "name the translation gain -> name the imported-input cost -> state which dominates for this company from disclosures",
  "assuming exporters always benefit; ignoring API imports from China",
  gt="cmd.usdinr.2022-09-30", cov="partial", note="FX points are exact; the import-content split is AR prose.",
  gap="NEW GAP: no import-content field",
  why="tests two-channel reasoning on one FX move")
Q("A10", "Rupee at 96 puts pressure on a paint company that imports crude derivatives. How would you show it in the numbers?", "ASIANPAINT, commodity:usdinr", "2026-09-30", "2026-10-07", "explanation",
  "mkt_commodity_daily (usdinr, crude_brent); ar_facts material cost; results_xbrl gross margin; concall FX/pricing commentary",
  "state both moves -> compute the rupee cost of the import basket -> compare with the gross-margin path -> state the pass-through lag",
  "double-counting crude and FX; assuming immediate price hikes",
  gt="cmd.usdinr.2026-09-30", cov="partial", note="FX and crude closes are exact; the import basket is not stored.",
  gap="NEW GAP: no import-basket composition table",
  why="tests a two-input joint shock")
Q("A10", "RBI raised the repo by 50bp to 5.9% on 30 September 2022. What does that do to a vehicle-finance NBFC's spread, and how fast?", "CHOLAFIN, SHRIRAMFIN", "2022-09-30", "2022-10-31", "explanation",
  "pib_releases (repo decision, PRID 1863686); results_xbrl interest cost and NIM proxies; concall cost-of-funds commentary",
  "read the policy action -> read the NBFC's borrowing mix -> compute the repricing lag -> check the reported cost of funds in the next two quarters",
  "assuming an instant full pass-through; using a bank's NIM for an NBFC",
  cov="partial", note="the repo action is a real PIB release; the NBFC's borrowing mix is AR/notes prose.",
  gap="NEW GAP: no structured policy-rate series in the store; repo moves come from PIB text",
  why="tests rate transmission to a lender with a repricing lag")
Q("A10", "RBI ne 1 Oct 2025 ko repo hold kiya — HFC margins par kya asar, aur market ne cut price kiya tha? (Hinglish)", "AAVAS, CANFINHOME", "2025-10-01", "2025-10-31", "explanation",
  "pib_releases (RBI MPC statement); results_xbrl cost of funds; daily_price_delivery for HFC stocks around the date",
  "read the policy hold -> read HFC cost-of-funds commentary -> compare the stocks' move with the decision -> separate rate path from expectations",
  "calling a hold a cut; using a post-date MPC decision",
  cov="partial", note="the PIB release is real; no structured rate-expectation series exists.",
  gap="G10", why="tests policy-hold reading and expectations discipline")
Q("A10", "Repo cuts are supposed to help realty. What is the actual channel from repo to a DLF or Prestige sale, and how many steps are there?", "DLF, PRESTIGE", "FY27", "2026-10-07", "explanation",
  "policy_events/pib_releases on rates; concall affordability commentary; results_xbrl interest cost; the home-loan rate pass-through",
  "repo -> home-loan rate -> EMI/affordability -> sales velocity -> developer cash flow -> land buying; label each step's evidence",
  "claiming a rate cut immediately lifts sales; skipping the EMI step",
  cov="partial", note="no company-level affordability or sales-velocity table exists.",
  gap="NEW GAP: no sales-velocity/affordability series",
  why="tests a multi-step transmission chain where most steps are unobserved")
Q("A10", "A rate cut compresses a bank's NIM but lifts loan growth. For HDFC Bank, which effect dominated last cycle, and what does the disclosure say?", "HDFCBANK, SBIN", "FY26-FY27", "2026-10-07", "explanation",
  "results_xbrl NIM proxies; concall margin commentary; policy_events for rate moves",
  "read the NIM path -> read loan growth -> compare -> state which dominated and over what window",
  "computing NIM from total income alone; mixing standalone and consolidated",
  cov="partial", note="bank taxonomies differ; NIM is not a direct XBRL concept.",
  gap="G11", why="tests banking metric construction from a non-standard taxonomy")
Q("A10", "Muthoot's cost of funds rises with the repo. How does that interact with the gold-loan yield cap, and who bears it?", "MUTHOOTFIN", "FY26-FY27", "2026-10-07", "explanation",
  "results_xbrl finance cost; concall spread commentary; policy_events on rate moves",
  "read cost of funds -> read yield -> compute spread -> state the cap and who bears the squeeze",
  "ignoring the regulatory yield cap; using a bank's benchmark",
  cov="partial", note="cost and yield are in filings; the cap is regulatory prose, not a parameter.",
  gap="G10", why="tests a rate transmission with a regulatory constraint")
Q("A10", "A weaker rupee raises an airline's dollar costs. What are the two biggest USD cost lines for IndiGo, and how are they disclosed?", "INDIGO, commodity:usdinr", "FY26-FY27", "2026-10-07", "explanation",
  "ar_facts FX exposure/hedging note; concall cost commentary; results_xbrl other expenses",
  "read the FX note -> name aircraft/lease and fuel as USD lines -> state the hedge -> quantify only what is disclosed",
  "assuming all costs are USD; ignoring the hedge",
  gt="cmd.usdinr.2026-09-30", cov="partial", note="the FX level is exact; the USD cost split is in the AR note, not a field.",
  gap="NEW GAP: no FX-exposure note extraction",
  why="tests cost-side FX analysis for a services company")
Q("A10", "Shipping earns in dollars and spends partly in rupees. What does rupee depreciation do to SCI's margin?", "SCI, commodity:usdinr", "FY27", "2026-10-07", "explanation",
  "ar_facts freight and cost note; results_xbrl revenue/expense; concall FX commentary",
  "state the revenue currency -> state the cost currency -> show the net translation -> check for hedging",
  "assuming a pure exporter benefit; ignoring bunker (USD) costs",
  gt="cmd.usdinr.2022-09-30", cov="partial", note="FX points are exact; the revenue/cost currency split is AR prose.",
  gap="NEW GAP: no currency-mismatch field",
  why="tests net-currency-position reasoning")
Q("A10", "For a life insurer, what do higher rates do to the embedded value, and does that show up in the disclosures?", "HDFCLIFE", "FY26-FY27", "2026-10-07", "explanation",
  "results_xbrl (insurance taxonomy); annual report embedded-value note; policy_events on rates",
  "rates -> discount rate -> EV -> new-business margin; state which is disclosed and which is inferred",
  "treating EV as a market-price series; ignoring the product mix",
  cov="partial", note="insurance taxonomy is sparse; EV is not a direct XBRL fact.",
  gap="G11", why="tests a rate-sensitive metric that is only partly in the stores")
Q("A10", "Repo up 250bp over two years: how would an auto-finance NBFC's spread move, and what does Bajaj Finance's disclosure show?", "BAJFINANCE, SHRIRAMFIN", "FY23-FY25", "2026-10-07", "explanation",
  "results_xbrl interest cost/NIM; concall spread commentary; policy_events for the rate path",
  "read the rate path -> read cost of funds -> read yield -> compute the spread change -> state the lag",
  "assuming yields reprice as fast as costs",
  cov="partial", note="the rate path is text-derived; NIM construction needs the NBFC taxonomy.",
  gap="G11", why="tests spread construction under a multi-year rate cycle")
Q("A10", "Rupee at 96 for an electronics manufacturer that imports components: what does it do to Dixon's margin and what is the hedge?", "DIXON, commodity:usdinr", "FY27", "2026-10-07", "explanation",
  "ar_facts import/hedging note; concall margin commentary; results_xbrl gross margin",
  "state the import share -> compute the cost effect -> read the pass-through to customers -> state the hedge",
  "assuming a full pass-through to brand customers; ignoring the PLI incentive",
  gt="cmd.usdinr.2026-09-30", cov="partial", note="the FX level is exact; the import share and pass-through are commentary.",
  gap="NEW GAP: no import-content field for manufacturers",
  why="tests an importer's FX exposure, the mirror image of the IT case")
Q("A10", "IRFC lends to Indian Railways at fixed spreads funded by bonds. Kaise rate cut se uski profitability badalti hai? (Hinglish)", "IRFC, RECLTD", "FY27", "2026-10-07", "explanation",
  "results_xbrl interest income/expense; concall spread commentary; policy_events on rates",
  "read asset-liability repricing -> spread effect -> state the lag and the funding mix",
  "assuming a rate cut always helps; ignoring fixed-rate assets",
  cov="partial", note="repricing schedule is in the AR, not a field.",
  gap="G11", why="tests a Hinglish rate question for a concessional lender")
Q("A10", "KPITTECH rupee depreciation margin impact", "KPITTECH, PERSISTENT, commodity:usdinr", "FY27", "2026-10-07", "explanation",
  "results_xbrl revenue and employee cost; concall FX commentary; ar_facts currency split",
  "revenue translates immediately -> costs partly rupee -> margin effect depends on the local-cost share -> compare two firms",
  "assuming the same margin effect for all IT firms",
  gt="cmd.usdinr.2026-09-30", cov="partial", note="FX level exact; local-cost share is not a field.",
  gap="NEW GAP: no onshore/offshore revenue-cost split",
  why="tests within-sector dispersion on one FX move")

# ---------------------------------------------------------------- A11 (15)
Q("A11", "How do food-delivery fees affect a quick-commerce operator's profitability, and which line items move?", "JUBLFOOD, DEVYANI", "FY27", "2026-10-07", "explanation",
  "concall_facts (margin_and_cost_commentary); results_xbrl revenue and delivery cost; results_notes; deck unit-economics slides",
  "split commission, delivery fee and advertising -> map each to revenue or cost -> compute contribution per order only where disclosed -> state gaps",
  "inventing a per-order contribution; using GMV as revenue",
  cov="partial", note="the unit-economics bridge is only in decks and commentary; no order-level data.",
  gap="NEW GAP: no unit-economics store (orders, AOV, take rate, delivery cost per order)",
  why="tests the seed business-economics question with an honest evidence map")
Q("A11", "EV makers are discounting heavily. Which listed EV maker's margin is most exposed, and what does the disclosure say about discounting?", "OLECTRA, ATHERENERG, OLAELEC", "FY26-FY27", "2026-10-07", "ranking",
  "results_xbrl revenue and gross margin; concall discounting commentary; results_notes",
  "read gross margin trend -> read discount commentary -> rank by margin sensitivity -> state the volume assumption",
  "comparing a loss-making maker's margin with a profitable one without the base",
  cov="partial", note="gross margin is available; discount per vehicle is not disclosed as a field.",
  gap="NEW GAP: no discount/incentive field and no vehicle-registration volume feed",
  why="tests a discount-driven margin question with a data ceiling")
Q("A11", "Brokers earn float income on client balances. How much of Angel One's revenue is float income, and what happens when rates fall?", "ANGELONE", "FY26-FY27", "2026-10-07", "explanation",
  "results_xbrl revenue split; annual report float-income note; policy_events for rates",
  "find float income -> divide by total revenue -> state the rate sensitivity -> check the disclosure",
  "mixing float income with broking revenue; assuming client balances are stable",
  cov="partial", note="revenue is tagged; the float split needs the AR note.",
  gap="G11", why="tests a business-model revenue decomposition")
Q("A11", "A food-delivery platform raises its take rate by 100bp. Who pays, and how does that reach EBITDA?", "JUBLFOOD, DEVYANI", "FY27", "2026-10-07", "explanation",
  "concall take-rate commentary; results_xbrl revenue; deck unit economics; competitor commentary",
  "take rate -> restaurant commission -> menu price -> order volume -> EBITDA; label each elasticity as assumed",
  "assuming no volume response; counting GMV as revenue",
  cov="partial", note="take rate is commentary; no order-volume series.",
  gap="NEW GAP: no order/GMV series",
  why="tests elasticity reasoning where every step needs an assumption")
Q("A11", "Fuel is the largest variable cost for an airline. At what load factor does a marginal flight turn contribution-positive, and what does IndiGo disclose?", "INDIGO", "FY27", "2026-10-07", "explanation",
  "concall cost commentary; results_xbrl revenue and fuel cost; deck cost-per-ASK slides",
  "read cost per ASK and yield -> compute the break-even load factor -> check against reported load factor",
  "computing break-even from total costs including fixed; ignoring the network effect",
  cov="partial", note="ASK/RASK are deck metrics; the cost-per-ASK series is not a table.",
  gap="NEW GAP: no airline operating-statistics series",
  why="tests unit-economics arithmetic on an airline")
Q("A11", "Maruti pays a royalty to Suzuki. How does a depreciation in the yen or rupee change that cost, and how much of revenue is it?", "MARUTI", "FY26", "2026-10-07", "explanation",
  "ar_facts royalty/related-party note; results_xbrl other expenses; concall royalty commentary",
  "find the royalty rate -> apply it to net sales -> state the currency -> quantify only if disclosed",
  "using a industry-standard royalty rate; ignoring that the rate is on net sales",
  cov="partial", note="the royalty note is in the AR; the rate is not a structured field.",
  gap="G6", why="tests a related-party cost channel")
Q("A11", "Cement mein 80% vs 70% utilisation par UltraTech ka EBITDA kitna badalta hai? (Hinglish)", "ULTRACEMCO", "FY26-FY27", "2026-10-07", "explanation",
  "concall utilisation and cost commentary; results_xbrl revenue/EBITDA; deck capacity and utilisation slides",
  "read capacity and volumes -> compute utilisation -> read fixed-cost share -> compute the EBITDA swing per 10pp",
  "assuming a fixed cost share; using despatch as production",
  gt="cc.ULTRACEMCO.capacity_and_projects", cov="partial", note="capacity is quoted; volume and fixed-cost share are deck/notes items.",
  gap="NEW GAP: no volume/production series for cement",
  why="tests operating-leverage reasoning from limited disclosure")
Q("A11", "EPC contractors are paid late by government clients. How does that change RVNL's return on capital, and where is the working-capital disclosure?", "RVNL", "FY26-FY27", "2026-10-07", "explanation",
  "results_notes working-capital note; annual_financials CFO and capital employed; concall receivable commentary",
  "read receivable days -> read CFO -> compute ROCE effect -> state the client mix",
  "computing ROCE from profit only; ignoring the capex-light model",
  gt="cc.RVNL.order_book", cov="partial", note="order inflow is quoted; receivable days need the notes and balance sheet.",
  gap="G11", why="tests working-capital-to-ROCE reasoning")
Q("A11", "Paint companies talk about premiumisation. What does that do to gross margin per litre, and can you measure it from the filings?", "ASIANPAINT", "FY26", "2026-10-07", "explanation",
  "results_xbrl revenue and material cost; concall volume/value commentary; deck product-mix slides",
  "read volume growth vs value growth -> infer mix -> read material cost -> state what cannot be separated",
  "claiming a mix effect from value growth alone",
  cov="partial", note="volume and value are both disclosed but not in one structured series.",
  gap="NEW GAP: no volume series; premiumisation is a qualitative claim",
  why="tests the limit of mix analysis from aggregate revenue")
Q("A11", "BHARTIARTL ARPU vs subscriber split FY26", "BHARTIARTL", "FY26", "2026-10-07", "explanation",
  "results_xbrl revenue; concall ARPU and subscriber commentary; deck operating metrics",
  "take ARPU and subscribers -> decompose revenue growth -> state the residual -> cite the disclosure",
  "assuming all growth is ARPU; mixing India and Africa",
  cov="partial", note="ARPU is commentary; India/Africa split needs the segment note.",
  gap="G11", why="tests a two-factor revenue decomposition")
Q("A11", "Gold-loan ticket sizes are rising. What does that do to Muthoot's loan-to-value and risk, and where is it disclosed?", "MUTHOOTFIN", "FY26-FY27", "2026-10-07", "explanation",
  "concall ticket-size and LTV commentary; results_xbrl loan book; annual report LTV note",
  "read ticket size -> read LTV -> state the regulatory cap -> compute the risk only if the gold price move is stated",
  "assuming a higher ticket is riskier without the LTV; ignoring the gold price",
  gt="cc.MUTHOOTFIN.capacity_and_projects", cov="partial", note="branch adds are quoted; ticket size and LTV are commentary.",
  gap="NEW GAP: no gold-loan LTV/ticket-size series",
  why="tests a lending unit-economics question")
Q("A11", "A retailer's store payback depends on capex per store and store EBITDA. What payback does Trent's disclosure imply, and what is missing?", "TRENT, VMART", "FY26", "2026-10-07", "explanation",
  "results_xbrl capex (cash-flow); concall store-add and payback commentary; deck store economics",
  "read capex per store -> read store EBITDA -> compute payback -> state the missing assumptions",
  "using total capex including warehousing; assuming a store's first-year EBITDA",
  cov="partial", note="store-level capex is not disclosed; only aggregate capex.",
  gap="NEW GAP: no store-level capex/EBITDA disclosure store",
  why="tests unit economics when the unit is not disclosed")
Q("A11", "Semiconductor content per car is rising. Does that help Motherson more than a car-volume recovery would?", "MOTHERSON, SONACOMS", "FY27", "2026-10-07", "explanation",
  "concall content-per-vehicle commentary; ar_facts product mix; results_xbrl revenue growth; auto volume data (absent)",
  "separate content growth from volume growth -> compare revenue growth with vehicle production -> state the attribution limit",
  "attributing all growth to content; using global volume data not in the store",
  cov="partial", note="no vehicle-production series in the store, so the decomposition is commentary-led.",
  gap="NEW GAP: no auto production/registration volume series",
  why="tests content-versus-volume attribution")
Q("A11", "Data-centre capex is booming. Which listed power-equipment name has the clearest revenue link, and how would you size it?", "CUMMINSIND, TATAPOWER, POWERINDIA", "FY27", "2026-10-07", "explanation",
  "concall capacity/order commentary; results_xbrl segment revenue; ar_facts customer/segment mix",
  "identify the equipment sold into data centres -> read the segment revenue -> size the data-centre share -> state the uncertainty",
  "calling a whole segment data-centre revenue; using an unstated order",
  cov="partial", note="segment revenue exists; data-centre share is not disclosed separately.",
  gap="NEW GAP: no end-market revenue split",
  why="tests sizing a theme exposure from segment data")
Q("A11", "Hospital ARPOB is the key unit metric. What drives it at Apollo, and how much is price versus occupancy?", "APOLLOHOSP", "FY26", "2026-10-07", "explanation",
  "concall ARPOB/occupancy commentary; results_xbrl segment revenue; deck operating metrics",
  "take ARPOB and occupancy -> decompose revenue -> state price versus volume -> cite the deck",
  "calling ARPOB growth volume growth; mixing mature and new hospitals",
  cov="partial", note="operating metrics are in decks and calls, not in a structured series.",
  gap="NEW GAP: no hospital operating-metrics series",
  why="tests a service-sector unit-economics decomposition")

# ---------------------------------------------------------------- A12 (15)
Q("A12", "India Semiconductor Mission 2.0 was announced with a Rs 1,000 crore allocation. Which listed companies does it actually reach, and by what channel?", "DIXON, AMBER, KAYNES, SYRMA, policy:pol.ism2", "FY27", "2026-10-07", "ranking",
  "policy_events (policy_name, amount, sectors, published_at); master_companies industry; concall plant commentary; results_xbrl capex",
  "read the policy amount and stage -> map to installed semiconductor/EMS capacity -> rank by disclosed exposure -> state that no listed pure-play fab exists",
  "calling every EMS company a semiconductor beneficiary; adding a subsidy to revenue",
  gt="pol.ism2", cov="partial", note="the policy is exact; company-level linkage is industry tags plus commentary, not a structured exposure.",
  gap="G10", why="tests policy-to-company mapping and refusing to overclaim")
Q("A12", "The US announced a 100% tariff on generic drug imports from 2028. Which listed Indian pharma exporters are most exposed, and how would you rank them?", "SUNPHARMA, AUROPHARMA, LUPIN, DRREDDY, policy:pol.usdrug100", "2028", "2026-10-07", "ranking",
  "policy_events (direction, sectors, effective_date); ar_facts US revenue share; concall US commentary; results_xbrl segment revenue",
  "read the policy and its date -> get each company's US revenue share -> rank -> state the effective-year offset",
  "ignoring the 2028 effective date; counting API sales as generic formulations",
  gt="pol.usdrug100", cov="partial", note="the policy row is exact; US revenue shares are AR/concall prose.",
  gap="NEW GAP: no geography revenue split as a structured field for the ranking",
  why="tests forward-tariff impact ranking with a date offset")
Q("A12", "A 200% tariff on generic drug imports from 2029 also exists in the policy store. How does that change the answer versus the 100% line from 2028?", "SUNPHARMA, DRREDDY, policy:pol.usdrug200", "2029", "2026-10-07", "explanation",
  "policy_events (both drug-tariff rows, amounts, dates); the two effective years; company US exposure",
  "compare the two rows -> state the rate and date differences -> state which firms can absorb via US manufacturing -> keep the ranking conditional",
  "treating the higher rate as the binding one without the later date; double-counting both",
  gt="pol.usdrug200", cov="partial", note="both policy rows are exact; company mitigation (US plants) is AR prose.",
  gap="G10", why="tests two-policy comparison with effective dates")
Q("A12", "US ne Indian exports par extra 10% duty lagayi — kaunse textile exporters sabse zyada expose hain? (Hinglish)", "KPRMILL, WELSPUNLIV, ARVIND, policy:pol.us10", "FY27", "2026-10-07", "ranking",
  "policy_events (direction, sectors); ar_facts geographic split; concall US commentary; results_xbrl revenue",
  "read the policy -> get US revenue shares -> rank -> state the pass-through assumption",
  "assuming all textile revenue is US-bound; ignoring the relief event in the same store",
  gt="pol.us10", cov="partial", note="the policy is exact; US revenue share is AR prose.",
  gap="NEW GAP: no structured geographic revenue split for exporters",
  why="tests a tariff-exposure ranking on a labour-intensive sector")
Q("A12", "The Samudra Manthan offshore-exploration scheme carries Rs 84,084 crore. Who benefits among listed oil and gas names, and over what horizon?", "ONGC, GAIL, IOC, policy:pol.samudra", "FY27", "2026-10-07", "ranking",
  "policy_events (amount, stage, sectors); macro_events; results_xbrl capex; concall offshore commentary",
  "read the scheme amount and stage -> map to E&P capex -> rank by order exposure -> state that the horizon is multi-year",
  "adding the scheme amount to FY27 revenue; assuming all of it is listed-company capex",
  gt="pol.samudra", cov="partial", note="the amount and stage are exact; the listed share of the spend is not in the store.",
  gap="G10", why="tests a large-scheme impact question with materiality discipline")
Q("A12", "PMAY-U 2.0 approved another 1.93 lakh houses. Which sectors and listed names gain, and how big is that versus annual demand?", "ULTRACEMCO, SAIL, CANFINHOME, policy:pol.pmay", "FY27", "2026-10-07", "explanation",
  "policy_events (amount/stage); census or housing-start series (absent); results_xbrl volumes; concall housing commentary",
  "read the approval -> convert houses to cement/steel demand with a stated per-unit assumption -> compare with annual industry demand -> label labels",
  "presenting a per-house cement number as a filed fact",
  gt="pol.pmay", cov="partial", note="the approval is exact; per-house demand coefficients are assumptions.",
  gap="NEW GAP: no housing-start or per-unit material coefficient table",
  why="tests policy-to-demand arithmetic with declared assumptions")
Q("A12", "CAQM Direction 98 requires PTZ-camera monitoring for red-category industries in NCR. Which listed companies must spend, and roughly how much?", "NOCIL, KPRMILL, SRF, policy:pol.caQM98", "FY27", "2026-10-07", "explanation",
  "policy_events (sectors list, effective_date); AR plant locations; results_xbrl capex; bse_announcements",
  "read the policy scope -> match plant locations -> state the capex only if disclosed -> otherwise say NOT IN DATA for the amount",
  "inventing a capex per plant; assuming every listed chemical company is in NCR",
  gt="pol.caQM98", cov="partial", note="the policy scope is exact; plant locations are AR text and the capex is not quantified.",
  gap="NEW GAP: no plant-location register linked to policy scope",
  why="tests a compliance-cost policy question with a location join")
Q("A12", "The FY26 Budget cut customs duty on flat-rolled steel products to 15%, effective 1 May 2025. Who gains and who loses among listed companies, and in what order?", "SAIL, TATASTEEL, TITAGARH, policy:pol.steel_flat_cut", "2025-05-01", "2025-05-31", "explanation",
  "policy_events (id 9074: old_value, new_value, direction_for_industry='mixed', effective_date, published_at; quote_ok=1, source_kind=doc, source_id=12402); results_xbrl margins; concall steel-cost commentary; daily_price_delivery for 2025-05-02 only as a reaction check",
  "read the duty row and its effective date -> separate mills (import competition) from steel users (input cost) -> order by transmission: mills on price first, users as contracts reprice -> state that the store quantifies neither",
  "treating a duty cut as a subsidy; inventing a rupee impact; using the announcement date as the effective date",
  gt="pol.steel_flat_cut", cov="partial", note="the duty change and the effective date are exact; company-level price and cost pass-through are not fields.",
  gap="G10", why="tests sign reversal on a duty cut and the announcement-versus-effective date split")
Q("A12", "Union Budget 2026-27 set the railway rolling-stock capex at Rs 52,109 crore. Which listed railway names does it reach first, and which only after the award cycle?", "RVNL, IRCON, TEXRAIL, TITAGARH, policy:pol.rail_rollingstock", "FY27", "2026-10-07", "ranking",
  "policy_events (id 11174: amount_inr_crore, old_value, new_value, stage; quote_ok=1, source_kind=doc, source_id=12405); concall order-book commentary; results_xbrl revenue; bse_announcements for awards",
  "read the rolling-stock line and the prior-year figure -> map rolling stock to wagon/coach makers first and EPC/civil later -> rank by award timing -> state the lag assumption",
  "assuming the whole outlay is orderable in one year; treating PSU EPC names as rolling-stock beneficiaries",
  gt="pol.rail_rollingstock", cov="partial", note="the budget line is exact (BE 52,109 vs RE 50,008 crore); award timing per company is commentary.",
  gap="G10", why="tests a budget-line-to-supplier ranking with an explicit timing lag")
Q("A12", "India signed the EU FTA on 27 January 2026, due in force at end-2026. Which listed textile exporters gain, and what did they do on the day?", "KPRMILL, WELSPUNLIV, GOKEX, policy:pol.eufta_textile", "2026-01-27", "2026-01-28", "explanation",
  "policy_events (id 21779: policy_name, sectors, effective_date; quote_ok=1, source_kind=doc, source_id=12800) plus id 21770 which dates the signing; daily_price_delivery for 2026-01-27 (KPRMILL, WELSPUNLIV, GOKEX); mkt_nse_index_daily for the same day; ar_facts geography",
  "read the FTA row and the dated signing -> read each exporter's move on 27 January -> compare with the index -> state that a one-day move is weak evidence and that duty-free access starts only when the FTA is in force",
  "calling a one-day move proof of an FTA benefit; treating the signing date as the in-force date",
  gt="pol.eufta_textile", cov="partial", note="the signing date and the day's moves are exact; EU revenue shares are AR prose and the FTA is not in force yet.",
  gap="NEW GAP: no structured geographic revenue split for exporters",
  why="tests dated trade-policy attribution and the signing-versus-in-force distinction")
Q("A12", "The FY26 Budget set up a Rs 20,000 crore Nuclear Energy Mission for SMR R&D, and the SHANTI Act opened plant operations to private firms. Which listed companies can actually bid, and where is the gap?", "NTPC, BHEL, policy:pol.nuclear_smr", "FY27-2047", "2026-10-07", "NOT IN DATA",
  "policy_events (id 4026: amount_inr_crore, end_date; id 13603: SHANTI stage=notified; both quote_ok=1, source_kind=doc, source ids 78 and 12423); results_xbrl segment revenue; ar_facts nuclear capability; no nuclear order-pipeline table",
  "read the mission amount and the SHANTI stage -> check which listed firms disclose nuclear credentials -> state that the reactor supply chain is largely PSU/unlisted -> say NOT IN DATA for the order pipeline",
  "calling an EPC firm a nuclear beneficiary without a credential; summing a mission outlay into revenue",
  gt="pol.nuclear_smr", cov="no", note="the mission and the Act are sourced; there is no nuclear capability register or order pipeline, so the bid list cannot be built.",
  gap="NEW GAP: no nuclear-sector capability or order pipeline data",
  why="tests a forward policy where the honest answer is a capability gap")
Q("A12", "GST process reforms were notified in October 2026. Which listed sectors gain most from simpler compliance, and does the store let you size it?", "DIXON, TRENT, JUBLFOOD", "Oct 2026", "2026-10-23", "explanation",
  "pib_releases (GST reform release, release_date); policy_events (tax rows); results_xbrl; concall compliance commentary",
  "read the reform -> identify the operating burden it removes -> rank sectors by compliance intensity -> state that no quantum is stored",
  "inventing a tax saving; treating a process reform as a rate cut",
  cov="partial", note="the PIB release exists; there is no quantified compliance-cost saving.",
  gap="G10", why="tests a policy with no quantifiable company effect")
Q("A12", "anti-dumping signal — which Indian makers gain", "KPRMILL, NOCIL, AARTIIND", "FY27", "2026-10-07", "list",
  "policy_events (tariff_trade signals, sectors); ar_facts import competition note; results_xbrl margins",
  "read the signal (a signal, not a duty) -> list affected product categories -> state that no duty rate or date exists -> rank only qualitatively",
  "treating a signal as a notified duty; naming an import share that is not stored",
  cov="partial", note="the signal is stored without a rate or effective date, so the impact cannot be quantified.",
  gap="G10", why="tests policy-stage literacy: signal versus notified duty")
Q("A12", "TDB-DST signed a Rs 130 crore RDI support agreement with BigEndian Semiconductors. Kaunsi listed company ko iska fayda? (Hinglish)", "DIXON, KAYNES, SYRMA", "Oct 2026", "2026-10-23", "NOT IN DATA",
  "pib_releases (release date, body); master_companies; policy_events",
  "read the release -> check whether the beneficiary is listed -> if unlisted, say so -> name listed proxies only as inference",
  "claiming a listed company is the beneficiary; adding the amount to an EMS order book",
  cov="no", note="the beneficiary is a private company; the release does not name listed suppliers.",
  gap="NEW GAP: no private-company-to-listed-supplier map",
  why="tests a policy release whose direct beneficiary is not investable")
Q("A12", "One Budget customs line cut duty on iron and steel articles from 25% to 15%. Which listed names sit on each side of that line, and why is the sign opposite?", "SAIL, TITAGARH, policy:pol.steel_articles_cut", "2025-05-01", "2025-05-31", "explanation",
  "policy_events (id 9075: old_value 25%, new_value 15%, direction_for_industry='mixed', sectors=['Steel','Engineering'], effective_date; quote_ok=1, source_kind=doc, source_id=12402); ar_facts product lists; results_xbrl segments",
  "read the row's direction and sectors -> identify the protected side (domestic article fabricators) and the consuming side (wagon/engineering) -> state the sign for each -> note that the store records 'mixed' without magnitudes",
  "reading 'mixed' as 'no effect'; adding a rupee impact the row does not carry",
  gt="pol.steel_articles_cut", cov="partial", note="the duty change, both sectors and the 'mixed' direction are exact; the rupee split is not stored.",
  gap="G10", why="tests sign reasoning from a policy row that names both sides")
# ---------------------------------------------------------------- A13 (15)
Q("A13", "Who makes the wagons Indian Railways buys, and who supplies those wagon makers with steel? Name both layers.", "TITAGARH, TEXRAIL, SAIL, JSWSTEEL", "FY27", "2026-10-07", "list",
  "ar_facts (products/customers and raw material for each layer); concall order commentary; results_xbrl segment revenue",
  "layer 1: wagon makers -> layer 2: steel suppliers -> cite each claim to the AR section -> state whether the supply is captive or merchant",
  "naming a steel supplier without a filing; assuming one supplier",
  cov="partial", note="both layers are named in ARs, but customer-supplier links are prose, not a graph.",
  gap="G6", why="tests basic supply-chain layering with citations")
Q("A13", "Defence indigenisation gave BEL and HAL large orders. Which second-layer listed suppliers gain, and how do you establish the link?", "BEL, HAL, ASTRAMICRO, DATAPATTNS, SOLARINDS", "FY27", "2026-10-07", "list",
  "ar_facts customer/concentration notes; concall order commentary; bse_announcements sub-contract wins",
  "for each supplier, find the defence customer statement -> map to BEL/HAL -> state the order or halal evidence -> rank by stated share",
  "assuming a supplier to defence is a supplier to BEL; inventing a contract",
  cov="partial", note="supplier links are AR prose; no contract graph exists.",
  gap="G6", why="tests second-layer identification with evidence, not ticker similarity")
Q("A13", "The TCS on coal and iron-ore sales doubles to 2% from 1 April 2026. Who is hit first, who second, and does any listed layer gain?", "COALINDIA, NMDC, SAIL, TITAGARH, policy:pol.tcs_minerals", "FY27", "2026-10-07", "explanation",
  "policy_events (id 9247: old_value 1%, new_value 2%, sectors, effective_date; quote_ok=1, source_kind=doc, source_id=12406); results_xbrl cost lines; concall input-cost commentary",
  "read the rate change -> order the layers: mineral sellers at the point of sale, steel at input, wagon makers at steel price -> state the sign per layer -> say plainly that no listed layer gains and only the exchequer does",
  "treating a tax as a benefit to producers; assuming downstream pass-through is immediate",
  gt="pol.tcs_minerals", cov="partial", note="the rate and effective date are exact; per-company cost exposure is not quantified.",
  gap="G10", why="tests a cost-shock chain where the honest answer has no listed winner")
Q("A13", "Copper goes into cables, which go into EPC projects. Who bears the copper risk in that three-layer chain, and what contract feature decides it?", "POLYCAB, KEC, commodity:copper", "FY27", "2026-10-07", "explanation",
  "concall material-cost commentary; AR price-variation clause; mkt_commodity_daily; results_xbrl margins",
  "map layers -> find the escalation clause -> show who is exposed at each layer -> state the deciding contract term",
  "assuming fixed-price contracts have no escalation",
  gt="cmd.copper.2026-09-30", cov="partial", note="the commodity move is exact; contract clauses are AR prose.",
  gap="G6", why="tests contract-aware supply-chain risk")
Q("A13", "Semiconductor Mission 2.0 should lift EMS assembly. Which chemical and material suppliers sit under that, and is the link disclosed?", "DIXON, KAYNES, SRF, AARTIIND", "FY27", "2026-10-07", "list",
  "ar_facts product/customer notes for the chemical names; concall electronics-material commentary; results_xbrl segment revenue",
  "identify the material (specialty gases, fluoropolymers, laminates) -> find the disclosing company -> state the link only if filed",
  "calling a specialty-chemical company a semiconductor supplier without a product line",
  cov="partial", note="product lines are in ARs; semiconductor-grade qualification is rarely disclosed.",
  gap="G6", why="tests deep second-order mapping with a qualification caveat")
Q("A13", "solar module chain — BORORENEW glass/EVA link", "BORORENEW, ACMESOLAR, WAAREEENER", "FY27", "2026-10-07", "explanation",
  "ar_facts product/customer; concall solar commentary; results_xbrl segment revenue; policy_events for solar schemes",
  "module makers -> glass/EVA supplier -> verify the product and customer -> state the linkage",
  "assuming a solar-adjacent name is a supplier; ignoring import competition",
  cov="partial", note="product lines are disclosed; customer concentration is thin.",
  gap="G6", why="tests a specific second-order solar chain")
Q("A13", "BharatNet needs optical fibre and telecom gear. Which listed suppliers gain, and how is the award flowing?", "STLTECH, HFCL, TEJASNET, RVNL", "FY27", "2026-10-07", "list",
  "concall order commentary; bse_announcements order wins; results_xbrl revenue; RVNL BharatNet commentary",
  "map the project -> fibre/gear suppliers -> find disclosed awards -> state the execution timeline from RVNL",
  "counting a trial order as a BharatNet award; ignoring the EPC layer",
  gt="cc.RVNL.capacity_and_projects", cov="partial", note="the RVNL timeline is quoted; supplier awards are only where announced.",
  gap="G6", why="tests a multi-supplier project chain")
Q("A13", "Cochin Shipyard's Drydocks World JV will need steel and marine equipment. Which listed companies are the plausible suppliers, and what is the evidence standard?", "COCHINSHIP, SAIL, JSWSTEEL", "FY27", "2026-10-07", "explanation",
  "concall JV commentary; AR procurement note; results_xbrl; bse_announcements",
  "read the JV scope -> identify procurement categories -> name only suppliers with a filed link -> otherwise label as inference",
  "naming a steel company from geography alone; treating a JV approval as an order",
  gt="cc.COCHINSHIP.capacity_and_projects", cov="partial", note="the JV target is quoted; procurement links are not disclosed.",
  gap="G6", why="tests the evidence standard for naming a supplier")
Q("A13", "The Mumbai-Ahmedabad high-speed-rail packages use TBMs. Which listed companies supply the civil inputs, and what does Afcons' own disclosure say?", "AFCONS, ULTRACEMCO, JSWSTEEL", "FY27", "2026-10-07", "explanation",
  "concall AFCONS project commentary; results_xbrl; ar_facts for cement/steel suppliers (if named)",
  "read the package status -> identify cement/steel as inputs -> find any named supplier -> otherwise state the gap",
  "asserting a supplier relationship from a project name",
  gt="cc.AFCONS.capacity_and_projects", cov="partial", note="project status is quoted; supplier names are not disclosed.",
  gap="G6", why="tests inference versus disclosure in a project chain")
Q("A13", "EV adoption badhne se kaunse auto-component names jeetenge aur kaun harenge? (Hinglish)", "MOTHERSON, SONACOMS, UNOMINDA, MOTHERSON", "FY27", "2026-10-07", "explanation",
  "concall EV-content commentary; ar_facts product mix; results_xbrl segment revenue",
  "content per EV vs ICE -> winners (electronics, thermal) -> losers (engine parts) -> cite each company's own statement",
  "calling every auto ancillary an EV winner",
  cov="partial", note="product mix is disclosed; EV revenue share is not a field.",
  gap="NEW GAP: no EV revenue-share field",
  why="tests a two-sided disruption chain")
Q("A13", "Airline fleet expansion means more MRO and leasing. Which listed names capture that, and which part is NOT IN DATA?", "INDIGO, MOTHERSON", "FY27", "2026-10-07", "NOT IN DATA",
  "concall fleet/lease commentary; ar_facts; master_companies industry; results_xbrl",
  "map fleet expansion to MRO/leasing -> check listed coverage -> state that the MRO/lessor layer is mostly unlisted or foreign -> NOT IN DATA",
  "naming an unrelated listed company as an MRO play",
  cov="no", note="the MRO/lessor layer is largely unlisted; no listed pure-play is in the master.",
  gap="NEW GAP: no MRO/leasing listed-universe map",
  why="tests a supply-chain question with an empty listed layer")
Q("A13", "Hospital capex needs imported medical equipment. Which listed suppliers gain, and can the store quantify it?", "APOLLOHOSP", "FY27", "2026-10-07", "NOT IN DATA",
  "concall capex/bed-add commentary; ar_facts capex note; master_companies medical-equipment names (few)",
  "read bed additions -> estimate equipment spend -> check listed medical-equipment suppliers -> report the gap",
  "using a global equipment major as an Indian listed beneficiary",
  cov="no", note="no listed medical-equipment supplier of scale is in the master; the spend is an assumption.",
  gap="NEW GAP: no medical-equipment listed-universe map",
  why="tests a capex-chain question that ends in a data gap")
Q("A13", "US tariffs on Indian textiles have been 50% since August 2025. Which listed dye and chemical suppliers are exposed second-hand, and what is the evidence bar?", "ATUL, AARTIIND, KPRMILL, policy:pol.us50_textile", "FY27", "2026-10-07", "list",
  "policy_events (id 21769: direction_for_industry='negative', sectors, effective_date; quote_ok=1, source_kind=doc, source_id=12789); ar_facts product/customer; results_xbrl segment revenue; concall textile-chemical commentary",
  "read the tariff row and the sectors it names -> for each chemical name, find a disclosed textile-dye or textile-chemical exposure -> rank by the disclosure -> state that the link is prose, not a structured customer map",
  "calling a diversified chemical company a textile play without a disclosed exposure; assuming the 50% tariff is new in FY27",
  gt="pol.us50_textile", cov="partial", note="the tariff row is exact; textile-chemical exposure is AR/concall prose.",
  gap="G6", why="tests a second-hand negative chain with an explicit evidence bar")
Q("A13", "Budget 2026-27 put Rs 7,500 crore into railway signalling and telecom. Beyond the wagon makers, who in the listed universe gains second-hand, and in what order?", "RVNL, IRCON, RAILTEL, KEC, policy:pol.rail_signalling", "FY27", "2026-10-07", "ranking",
  "policy_events (id 11178: amount_inr_crore, old_value, new_value, sectors; quote_ok=1, source_kind=doc, source_id=12405); results_xbrl order proxies; concall commentary; bse_announcements for Kavach awards",
  "read the signalling line -> layer the chain: signalling OEMs and cables first, EPC and civils next, wagon makers later -> rank by award timing -> cite each company's rail exposure",
  "putting every infrastructure name in the rail basket; treating the rolling-stock outlay as signalling",
  gt="pol.rail_signalling", cov="partial", note="the budget line is exact (BE 7,500 vs RE 6,500 crore); per-company rail revenue share is not a field.",
  gap="G6", why="tests a layered ranking from a sourced budget line, not a macro event")
Q("A13", "Railway wagon banane wale ko steel kaun deta hai, aur scrap/CRGO pe exemption extend hone se chain mein kaun jeetta hai, kaun peeche reh jaata hai? (Hinglish)", "TITAGARH, TEXRAIL, SAIL, policy:pol.scrap_crgo_exempt", "FY27", "2026-10-07", "explanation",
  "policy_events (id 9618: old_value, new_value, effective_date, end_date; quote_ok=1, source_kind=doc, source_id=12406); ar_facts raw-material note for wagon makers; results_xbrl; concall steel-cost commentary",
  "name the steel layer -> name the wagon layer -> read the exemption extension -> state who gains (scrap-based steel and CRGO users) -> state that wagon makers see nothing directly and what would have to happen",
  "assuming wagon makers get the duty benefit directly; treating an extended exemption as a new subsidy",
  gt="pol.scrap_crgo_exempt", cov="partial", note="the exemption and its new end date are exact; the pass-through to wagon costs is not stored.",
  gap="G10", why="tests a Hinglish second-order chain on a sourced customs exemption")

# ---------------------------------------------------------------- A14 (15)
Q("A14", "BEL guided 15% revenue growth for FY27. What did Q1 FY27 actually deliver, and is the guidance still credible?", "BEL", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (guidance); results_xbrl Q1 FY27 revenue and the FY26 base; results_notes",
  "take the guidance -> take Q1 revenue -> compute the required run-rate -> compare with the FY26 seasonality -> state whether it is achievable",
  "annualising Q1 without seasonality; calling a miss from one quarter",
  gt="cc.BEL.guidance", cov="partial", note="the 15% guidance is quoted; the seasonality comparison needs the full quarterly XBRL series.",
  gap="G11", why="tests guidance-to-delivery arithmetic with seasonality")
Q("A14", "Suzlon guided a 17-18% EBITDA margin for FY27. What has it actually reported, and what is the gap?", "SUZLON", "FY27", "2026-10-07", "fact",
  "concall_facts.cc_items (guidance); results_xbrl EBITDA and revenue; the Q1 result",
  "take the guidance band -> compute the reported margin -> state the gap and the quarter -> do not annualise",
  "comparing a quarterly margin with an annual guidance without saying so",
  gt="cc.SUZLON.guidance", cov="partial", note="the band is quoted; the XBRL margin needs cost-line mapping.",
  gap="G11", why="tests a band guidance versus a point estimate")
Q("A14", "Tatapower said 200 MW was commissioned and another 500 MW would follow in weeks. Did the later disclosure confirm the 500 MW?", "TATAPOWER", "Q2-Q4 FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects); results_notes capitalisation note; bse_announcements commissioning",
  "take the promise -> search later disclosures for 500 MW -> report confirmation or NOT IN DATA",
  "treating a plan as delivered; using a different MW figure without reconciling",
  gt="cc.TATAPOWER.capacity_and_projects", cov="partial", note="the plan is quoted; no later commissioning note confirms it in the store.",
  gap="NEW GAP: no commissioning-event register",
  why="tests promise-versus-delivery with a confirmation search")
Q("A14", "SRF guided the Dahej second pharma plant in eight months with Rs 180 crore. Has it commissioned, and how would you check?", "SRF", "FY27", "2026-10-07", "date",
  "concall_facts.cc_items (capacity_and_projects); results_notes capital work-in-progress; bse_announcements",
  "compute the implied commissioning month -> search later calls/filings -> state confirmed or NOT IN DATA",
  "computing a month from 'next 8 months' without the call date; assuming completion",
  gt="cc.SRF.capacity_and_projects", cov="partial", note="the plan is quoted; the store has no commissioning event.",
  gap="NEW GAP: no capex-completion event register",
  why="tests converting a relative window into a date and then checking it")
Q("A14", "KEI's Sanand phase 1 was late by about six months and commissioned in December 2025. Did the company meet its own revised date?", "KEI", "FY26", "2026-10-07", "fact",
  "concall_facts.cc_items (capacity_and_projects); the prior call's revised date; results_notes; the margin commentary",
  "find the revised date -> find the commissioning statement -> compare -> state whether the revised date held",
  "using the original date for the test; ignoring the revision",
  gt="cc.KEI.capacity_and_projects", cov="yes",
  why="tests slip-then-deliver tracking, the honest version of a go-live question")
Q("A14", "Polycab ne Q1FY27 mein 3.2 billion capex kiya — annual plan se aage ya peeche? (Hinglish)", "POLYCAB", "FY27", "2026-10-07", "fact",
  "concall_facts.cc_items (capex); results_xbrl capex/cash flow; the capex slide",
  "take quarterly capex -> annualise -> compare with the stated plan -> state the shortfall or lead",
  "annualising a lumpy capex quarter without saying it is an assumption",
  gt="cc.POLYCAB.capex", cov="partial", note="the Q1 capex is quoted; the annual plan must come from the deck/commentary.",
  gap="NEW GAP: no capex guidance field",
  why="tests run-rate versus plan arithmetic with a lumpiness caveat")
Q("A14", "HAL's order book is about Rs 2.54 lakh crore. What revenue cover is that, and did management guide to converting it faster?", "HAL", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book); results_xbrl trailing revenue; the order-book slide",
  "take order book -> take trailing four-quarter revenue -> compute cover in years -> read the execution guidance",
  "dividing by one quarter's revenue; treating an order book as revenue",
  gt="cc.HAL.order_book", cov="partial", note="the order book is quoted; trailing revenue must be summed from XBRL.",
  gap="G11", why="tests order-book cover and execution guidance")
Q("A14", "RVNL's Q1 FY27 order inflow was Rs 5,417 crore. How does that compare with its annual revenue, and what does it imply for FY27?", "RVNL", "FY27", "2026-10-07", "fact",
  "concall_facts.cc_items (order_book); results_xbrl revenue; the order-book slide",
  "take the inflow -> compare with FY26 revenue -> compute book-to-bill -> state what it implies only if execution keeps pace",
  "treating inflow as revenue; mixing consolidated/standalone",
  gt="cc.RVNL.order_book", cov="partial", note="the inflow is quoted; the revenue base needs XBRL.",
  gap="G11", why="tests inflow-versus-book arithmetic")
Q("A14", "Texrail's order book is Rs 9,923 crore as of 30 June 2026. What is the execution period, and is it enough to meet guidance?", "TEXRAIL", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book, capacity_and_projects); results_xbrl revenue; the leasing plan",
  "take the order book -> split wagon vs leasing -> read the execution period -> compare with annual revenue",
  "assuming the whole order book executes in one year",
  gt="cc.TEXRAIL.order_book", cov="partial", note="the order book is quoted; the execution period comes from the same call, not a field.",
  gap="G6", why="tests order-book duration reasoning")
Q("A14", "UltraTech's volume growth and capacity additions: did the FY26 additions land on the guided date?", "ULTRACEMCO", "FY26", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects, demand_commentary); results_xbrl volumes if tagged; the capacity slide",
  "take the guided capacity addition -> take the reported capacity -> compare -> state the gap",
  "comparing a consolidated capacity with a standalone one",
  gt="cc.ULTRACEMCO.capacity_and_projects", cov="partial", note="the base capacity is quoted; the guided addition is in the deck.",
  gap="NEW GAP: no capacity series",
  why="tests capacity guidance delivery")
Q("A14", "IRCTC payment aggregator licence status Oct 2026", "IRCTC", "FY27", "2026-10-07", "date",
  "concall_facts.cc_items (capacity_and_projects); bse_announcements; results_notes",
  "read the extension -> search for the grant -> if absent, say NOT IN DATA and state what would prove it",
  "calling an extension a grant; using a news headline as a filing",
  gt="cc.IRCTC.capacity_and_projects", cov="partial", note="the deadline is quoted; no grant document in the store.",
  gap="NEW GAP: no regulatory-licence outcome register",
  why="tests a dated promise where the outcome is absent")
Q("A14", "Cochin Shipyard targeted the ISRF JV before the end of the financial year. Has the JV been signed, and what would confirm it?", "COCHINSHIP", "FY27", "2026-10-07", "date",
  "concall_facts.cc_items (capacity_and_projects); bse_announcements for JV signing; results_notes",
  "read the target -> search for a signing announcement -> state confirmed or NOT IN DATA -> name the proof document",
  "treating board approval as the JV",
  gt="cc.COCHINSHIP.capacity_and_projects", cov="partial", note="the target is quoted; no signing announcement is in the store.",
  gap="NEW GAP: no JV/agreement execution register",
  why="tests approval-versus-execution distinction")
Q("A14", "Adani Green claimed a 20 GW renewable milestone in Q1 FY27. What was the previous milestone, and how long did the last 5 GW take?", "ADANIGREEN", "FY24-Q1FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects); results_notes commissioning note; deck capacity chart",
  "find the previous milestone statement -> compute the time between -> state the run-rate -> check against the stated target",
  "assuming a constant build rate; using a cumulative figure as an annual addition",
  gt="cc.ADANIGREEN.capacity_and_projects", cov="partial", note="the milestone is quoted; the prior milestone needs an earlier call.",
  gap="NEW GAP: no capacity time series",
  why="tests milestone-to-run-rate arithmetic")
Q("A14", "Jubilant FoodWorks has about 3,600 stores. Did store additions hit the number it guided last year?", "JUBLFOOD", "FY26", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects, demand_commentary); deck store-network slide; results_notes",
  "take the guided additions -> take the reported count -> compute the change -> state the miss or hit",
  "comparing a total store count with an additions guidance",
  cov="partial", note="store counts are commentary; no guided-additions field.",
  gap="NEW GAP: no store-count time series",
  why="tests a simple guidance-versus-delivery check without a store of guidance")
Q("A14", "SAIL advanced capital repairs into Q1 FY27 to free up later quarters. Did the later quarters show the output recovery it implied?", "SAIL", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects); results_xbrl quarterly revenue; results_notes production",
  "read the promise -> compare later-quarter volumes -> state whether the recovery is visible -> do not infer from one quarter",
  "attributing a price-led revenue rise to volume recovery",
  gt="cc.SAIL.capacity_and_projects", cov="partial", note="the promise is quoted; quarterly volume is not a direct XBRL concept.",
  gap="G11", why="tests a delivery check on an operational promise")

# ---------------------------------------------------------------- A15 (15)
Q("A15", "RVNL's order inflow in Q1 FY27 was Rs 5,417 crore. What is its order book cover in years, and how much of the book is slow-moving?", "RVNL", "Q1 FY27", "2026-10-07", "fact",
  "concall_facts.cc_items (order_book); results_xbrl revenue; the order-book slide; results_notes on execution",
  "take inflow -> take total book -> take trailing revenue -> compute cover -> read the slow-moving/legacy portion",
  "using inflow as the order book; dividing by one quarter",
  gt="cc.RVNL.order_book", cov="partial", note="inflow is quoted; book and slow-moving split are in the deck.",
  gap="G6", why="tests order-book cover with an execution-quality check")
Q("A15", "Inside HAL's Rs 2.54 lakh-crore book: which platforms dominate, and how many years of revenue does the mix imply?", "HAL", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book); the order-book slide by platform; results_xbrl revenue; AR order note",
  "read the total -> read the platform split -> estimate years of revenue -> state the long-cycle nature",
  "assuming an even execution profile; treating a framework order as firm",
  gt="cc.HAL.order_book", cov="partial", note="the total is quoted; the platform split is a slide.",
  gap="G6", why="tests defence order-book composition awareness")
Q("A15", "Texrail's order book is Rs 9,923 crore. How much is wagons versus leasing, and which part is recurring?", "TEXRAIL", "Q1 FY27", "2026-10-07", "fact",
  "concall_facts.cc_items (order_book, capacity_and_projects); results_xbrl revenue; the segment note",
  "read the total -> split wagons and leasing -> state which is recurring -> compute cover",
  "calling the whole book recurring; mixing segment and consolidated",
  gt="cc.TEXRAIL.order_book", cov="partial", note="the total is quoted; the split needs the segment note/deck.",
  gap="G6", why="tests recurring-versus-one-off order book")
Q("A15", "BEL is waiting for CCS approval on QRSAM. Is that order already in the order book, and what happens to cover when it lands?", "BEL", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects, order_book); results_xbrl revenue; bse_announcements",
  "read the approval status -> state whether booked -> size the order if disclosed -> show the cover change",
  "adding an unapproved order to the book; using an unstated value",
  gt="cc.BEL.capacity_and_projects", cov="partial", note="the approval gate is quoted; the order value is not in the same item.",
  gap="G6", why="tests approved-versus-pipeline order book")
Q("A15", "Mazagon Dock's order book: how much is shipbuilding versus repairs, and which is more stable?", "MAZDOCK", "FY27", "2026-10-07", "explanation",
  "results_xbrl segment revenue; concall order commentary; deck order-book slide; AR order note",
  "read the split -> state the duration of each -> compare variability -> cite the deck",
  "treating repairs as growth; mixing order book and order intake",
  cov="partial", note="segment revenue exists; the order-book split needs the deck.",
  gap="G6", why="tests defence PSU order-book quality")
Q("A15", "Cochin Shipyard has an ISRF JV pipeline alongside its order book. How do you separate firm orders from JV optionality?", "COCHINSHIP", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects, order_book); results_xbrl revenue; bse_announcements",
  "list firm orders -> list the JV target -> state that the JV is not an order -> show the cover on firm orders only",
  "counting JV capacity as order book; using a target date as revenue",
  gt="cc.COCHINSHIP.capacity_and_projects", cov="partial", note="the JV target is quoted; firm order value is in the deck.",
  gap="G6", why="tests firm-versus-optionality separation")
Q("A15", "Ircon's order book: how much is the new dedicated-freight-corridor work, and has any of it been awarded?", "IRCON", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (capacity_and_projects, order_book); bse_announcements; results_xbrl revenue",
  "read what is awarded -> read what is only announced -> state that the DFC work is not in the book -> give the cover on awarded work",
  "counting announced corridors as order book",
  gt="cc.IRCON.capacity_and_projects", cov="partial", note="the project is quoted as announced; award status is NOT IN DATA.",
  gap="NEW GAP: no tender/award pipeline table",
  why="tests awarded-versus-announced order book")
Q("A15", "Rites' order book has been falling. Why, and what does management say about the pipeline?", "RITES", "FY26-FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book); results_xbrl revenue; the order-book slide; results_notes",
  "show the book trend -> read the stated reason -> read the pipeline comment -> separate execution from award weakness",
  "calling a book decline a revenue decline; ignoring execution burn",
  cov="partial", note="order-book levels are commentary; no structured series.",
  gap="G6", why="tests a declining order book, not just a growing one")
Q("A15", "KEC T&D book-to-bill FY27", "KEC", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book); results_xbrl revenue; the order slide",
  "take inflow -> take quarterly revenue -> compute book-to-bill -> compare with the execution commentary",
  "using a trailing book for a quarterly ratio; ignoring the slow-moving portion",
  cov="partial", note="order commentary is stored; the ratio needs both inputs by hand.",
  gap="G6", why="tests book-to-bill arithmetic")
Q("A15", "HG Infra ke order book mein EPC vs HAM kitna hai? (Hinglish)", "HGINFRA", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book, capacity_and_projects); results_xbrl revenue; AR HAM note",
  "split EPC/HAM -> state the risk in each -> check the HAM asset status",
  "treating HAM revenue as EPC margin; ignoring the concession life",
  cov="partial", note="HAM disclosures are AR prose; no structured split.",
  gap="G6", why="tests a road-EPC order book with concession nuance")
Q("A15", "Titagarh's wagon order book versus its 1,200/month capacity: at current orders, how many months of work is booked?", "TITAGARH", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book, capacity_and_projects, demand_commentary); results_xbrl revenue",
  "take the wagon order book -> divide by the monthly capacity -> compare with reported run-rate -> state the utilisation gap",
  "dividing the whole order book by wagon capacity; ignoring the non-wagon business",
  gt="cc.TITAGARH.capacity_and_projects", cov="partial", note="the capacity and demand condition are quoted; the wagon-only book needs the deck.",
  gap="G6", why="tests capacity-versus-book utilisation")
Q("A15", "Afcons' order book includes the MAHSR C2 package. What share is under execution, and what does the TBM status say about it?", "AFCONS", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book, capacity_and_projects); results_xbrl revenue; project slides",
  "read the book -> read the project status -> estimate the executed share -> state the risk in the remaining work",
  "counting a package's full value as unexecuted work",
  gt="cc.AFCONS.capacity_and_projects", cov="partial", note="TBM status is quoted; the executed share is not disclosed.",
  gap="G6", why="tests execution-stage reasoning inside an order book")
Q("A15", "NBCC's PMC order book is large but its receivables are old. How do you judge whether the book is worth its face value?", "NBCC", "FY27", "2026-10-07", "explanation",
  "results_xbrl revenue and receivables; results_notes working-capital note; concall order commentary",
  "take the book -> take receivable days -> compute cash conversion -> state the haircut logic",
  "taking the order book at face value; ignoring government-client collection risk",
  cov="partial", note="receivable data is in notes and the balance sheet; no aged-receivables field.",
  gap="G11", why="tests order-book quality versus cash")
Q("A15", "GR Infra's order book and margin guidance: does the book mix support the guided margin?", "GRINFRA", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book, guidance, margin_and_cost_commentary); results_xbrl margin",
  "read the book mix -> read the guided margin -> compare with realised margin -> state whether the mix supports it",
  "using a guided margin as realised; ignoring the HAM share",
  cov="partial", note="both book and guidance are commentary; no structured mix.",
  gap="G6", why="tests margin guidance against order-book mix")
Q("A15", "PNC Infratech's HAM assets are up for monetisation. Kaise order book se asset sale alag hai? (Hinglish)", "PNCINFRA", "FY27", "2026-10-07", "explanation",
  "concall_facts.cc_items (order_book, capacity_and_projects); results_xbrl revenue; bse_announcements for divestment",
  "separate construction revenue from asset sale proceeds -> state the book effect of each -> check for a filed divestment",
  "counting an asset sale as order book; double-counting HAM EPC and annuity",
  cov="partial", note="commentary only; no asset-sale event store.",
  gap="G6", why="tests Hinglish capital-recycling versus order-book distinction")

# ---------------------------------------------------------------- A16 (15)
Q("A16", "Which companies raised a QIP in FY26, and did the actual use of proceeds match the stated objects?", "KAYNES, DIXON, AMBER", "FY26", "2026-10-07", "list",
  "bse_announcements (QIP/board approval); results_notes/AR objects-versus-utilisation note; results_xbrl cash flow",
  "find the issue -> read the objects -> read the utilisation table in the next AR -> compare line by line -> flag deviation",
  "assuming objects were met because money was raised; using a later AR than the as-of",
  cov="partial", note="objects and utilisation are disclosed in AR notes, but there is no objects-versus-use table in the store.",
  gap="NEW GAP: no capital-raise objects/utilisation table",
  why="tests the exact capital-allocation question investors ask after a QIP")
Q("A16", "Is Polycab's capex funded by debt or internal accruals, and how does the disclosure show it?", "POLYCAB", "FY26-FY27", "2026-10-07", "fact",
  "results_xbrl cash flow (capex, borrowings); concall capex commentary; AR debt note",
  "read capex -> read operating cash flow -> read net debt change -> state the funding mix",
  "calling capex debt-funded from a rising gross block alone",
  gt="cc.POLYCAB.capex", cov="partial", note="quarterly capex is quoted; the funding mix needs the cash-flow statement.",
  gap="G11", why="tests funding-source reasoning from cash flow")
Q("A16", "Trent did a 1:2 bonus with ex-date 4 June 2026. What does that do to the EPS series, and how should a price chart treat it?", "TRENT", "2026-06-04", "2026-06-05", "fact",
  "corporate_actions (action_type=BONUS, subject, ex_date); daily_price_delivery around the date; adjusted price series; results_xbrl EPS",
  "read the bonus ratio -> restate the prior EPS -> use the adjusted series for returns -> state that raw price falls mechanically",
  "treating the ex-date price fall as a loss; comparing unadjusted EPS",
  gt="ca.TRENT.bonus", cov="yes",
  why="tests share-count restatement, a repeated capital-allocation trap")
Q("A16", "Suzlon has been cutting debt while spending on capacity. Which came first in the cash flow, and is the deleveraging real?", "SUZLON", "FY24-FY27", "2026-10-07", "explanation",
  "results_xbrl debt/finance cost; annual_financials cash flow; concall deleveraging commentary",
  "read net debt over three years -> read capex -> read operating cash flow -> state whether debt fell for operational or refinancing reasons",
  "calling a refinancing a repayment; using gross debt",
  cov="partial", note="debt series is spotty across years; commentary fills the gap.",
  gap="G11", why="tests deleveraging quality, not just the direction")
Q("A16", "RVNL and NBCC are asset-light but cash-hungry. How do they fund working capital, and what does that do to return on capital?", "RVNL, NBCC", "FY26", "2026-10-07", "explanation",
  "results_xbrl receivables/payables; results_notes; annual_financials CFO and capital employed",
  "compute working-capital days -> read the funding (client advances vs debt) -> compute ROCE effect",
  "calling an asset-light model capital-light without the receivable days",
  cov="partial", note="working-capital days need notes; no ready ratio.",
  gap="G11", why="tests capital efficiency in a PSU EPC")
Q("A16", "Which companies put money into a subsidiary or JV last year, and was it disclosed as a related-party transaction?", "COCHINSHIP, KAYNES, KFINTECH", "FY26", "2026-10-07", "list",
  "results_notes RPT note; bse_announcements; AR investment note; results_xbrl investments",
  "find the investment -> check the RPT disclosure -> state amount and counterparty -> flag if missing",
  "treating an ordinary subsidiary investment as an RPT red flag",
  gt="cc.COCHINSHIP.capacity_and_projects", cov="partial", note="the JV is quoted; the funding disclosure is in the AR note.",
  gap="G6", why="tests capital allocation into JVs and its disclosure")
Q("A16", "ITC and Colgate pay out most of their earnings. Is the payout covered by free cash flow, and what is left for growth?", "ITC, COLPAL", "FY26", "2026-10-07", "explanation",
  "results_xbrl dividend/PAT; annual_financials CFO and capex; AR dividend note",
  "compute payout ratio -> compute FCF -> compare -> state the residual for growth",
  "using PAT instead of FCF for coverage",
  cov="partial", note="dividends are in corporate_actions/AR; FCF needs cash-flow lines.",
  gap="G11", why="tests payout sustainability")
Q("A16", "buyback vs dividend choices FY26", "TRENT, SIEMENS", "FY26", "2026-10-07", "explanation",
  "corporate_actions (action_type); bse_announcements; AR treasury note; results_xbrl share count",
  "classify actions -> state the tax/signal difference -> name examples -> avoid asserting motive",
  "asserting management intent without a disclosure",
  cov="partial", note="actions are in corporate_actions; the reason is rarely disclosed.",
  gap="NEW GAP: no buyback/dividend policy field",
  why="tests capital-return choice with motive discipline")
Q("A16", "UltraTech bought India Cements and Kesoram. How was the acquisition funded, and what did it do to net debt/EBITDA?", "ULTRACEMCO", "FY25-FY26", "2026-10-07", "explanation",
  "bse_announcements (acquisition); results_xbrl borrowings/EBITDA; concall funding commentary",
  "read the deal value -> read the funding (cash/debt/equity) -> compute leverage change -> compare with the stated target",
  "assuming a cash deal without the funding disclosure",
  gt="cc.ULTRACEMCO.capacity_and_projects", cov="partial", note="the acquired capacity is quoted; the funding mix is in the concall/notes.",
  gap="G11", why="tests acquisition funding and leverage")
Q("A16", "Cochin Shipyard's ISRF JV needs capital. What is the committed amount, and who funds it?", "COCHINSHIP", "FY27", "2026-10-07", "fact",
  "bse_announcements (JV board approval); concall JV commentary; results_xbrl investments",
  "read the JV terms -> state the capital commitment -> state the partner share -> flag if undisclosed",
  "inventing a commitment; treating a board approval as funding",
  cov="partial", note="the JV target is quoted; the capital commitment is NOT IN DATA in the stored item.",
  gap="NEW GAP: no JV capital-commitment field",
  why="tests a capital question at the edge of disclosure")
Q("A16", "Tata Power ka renewable capex debt se fund ho raha hai ya internal accruals se? (Hinglish)", "TATAPOWER", "FY27", "2026-10-07", "explanation",
  "results_xbrl capex/borrowings; concall funding commentary; bse_announcements for stake sales",
  "read capex -> read funding commentary -> check for asset monetisation -> state the mix",
  "assuming project finance means no balance-sheet debt",
  gt="cc.TATAPOWER.capacity_and_projects", cov="partial", note="the MW plan is quoted; funding is commentary.",
  gap="G11", why="tests capex funding in a utility")
Q("A16", "JSW Steel's acquisitions added debt. Did the leverage ratio stay within the stated ceiling, and what did management say?", "JSWSTEEL", "FY26", "2026-10-07", "explanation",
  "results_xbrl net debt/EBITDA inputs; concall leverage commentary; bse_announcements acquisitions",
  "compute leverage -> compare with the stated ceiling -> read the mitigation plan",
  "using gross debt; ignoring EBITDA seasonality",
  cov="partial", note="leverage needs mapped XBRL lines; management ceiling is commentary.",
  gap="G11", why="tests leverage discipline against a stated policy")
Q("A16", "Angel One earns float income on client funds. How does it deploy that float, and what is the risk if rates fall?", "ANGELONE", "FY26", "2026-10-07", "explanation",
  "results_xbrl revenue mix; AR float/treasury note; policy_events rates",
  "read float income -> read deployment (FDs/liquid funds) -> state rate sensitivity -> avoid inventing a duration",
  "treating float income as fee income; assuming zero rate sensitivity",
  cov="partial", note="float split is AR prose; no duration table.",
  gap="G11", why="tests treasury capital allocation")
Q("A16", "A company issues fresh equity to fund capex. How does that change ROCE and EPS, and what should an investor check first?", "KAYNES, DIXON", "FY26-FY27", "2026-10-07", "explanation",
  "results_xbrl share count/equity; AR objects note; results_notes utilisation",
  "dilution -> capital employed -> ROCE path -> EPS bridge -> check objects and timeline",
  "comparing pre-issue EPS with post-issue EPS without dilution",
  cov="partial", note="share counts are in filings; the objects/use table is not structured.",
  gap="NEW GAP: no capital-raise objects/utilisation table",
  why="tests dilution and return arithmetic")
Q("A16", "Which company converted its capex into the best incremental ROCE over three years? Kaun sa company? (Hinglish)", "POLYCAB, DIXON, AMBER, KEI", "FY24-FY26", "2026-10-07", "ranking",
  "annual_financials/AR (capital employed, EBIT); results_xbrl; concall capex commentary",
  "compute incremental capital -> incremental EBIT -> rank -> state the basis and the lag",
  "ranking on absolute ROCE instead of incremental; ignoring capex still under construction",
  cov="partial", note="capital employed is spottily available; the ranking is hand-built.",
  gap="G11", why="tests a derived capital-allocation ranking with a lag caveat")

# ---------------------------------------------------------------- A17 (15)
Q("A17", "Which large caps saw the highest delivery percentage on 4 June 2024, and what does that say about who was selling?", "NTPC, RELIANCE, HINDALCO", "2024-06-04", "2024-06-04", "ranking",
  "daily_price_delivery (delivery_pct, total_volume, turnover_lacs); the 20-day average delivery for the same names",
  "rank by delivery percentage above a turnover floor -> compare with the trailing average -> state whether delivery rose or fell",
  "ranking by delivery percentage without a turnover floor; treating high delivery as buying",
  gt="px.NTPC.2024-06-04", cov="yes",
  why="tests delivery-data interpretation on a crash day")
Q("A17", "Which stocks traded above 50% delivery on 24 September 2026, and were they the biggest movers?", "POLICYBZR, NTPC", "2026-09-24", "2026-09-25", "list",
  "daily_price_delivery (delivery_pct, change_pct, turnover_lacs) for the date",
  "filter on delivery > 50% and turnover floor -> sort -> compare with the mover list -> state the overlap",
  "using a low-turnover stock; assuming delivery means institutional",
  gt="px.POLICYBZR.2026-09-24", cov="yes",
  why="tests an ownership-flow screen from delivery data")
Q("A17", "delivery-spike ratio leaders this week", "KEI, TITAGARH, DIXON", "latest session", "2026-09-24", "ranking",
  "daily_price_delivery (delivery_spike_ratio, delivery_conviction_score); the definition in the pipeline",
  "read the ratio -> explain the base period -> rank -> exclude low-volume names",
  "presenting the ratio without its base; treating it as a buy signal",
  gt="px.KEI.2026-09-24", cov="yes",
  why="tests a derived flow indicator and its definition")
Q("A17", "On 23 October 2026 Bonfiglioli saw several bulk deals. Who bought, at what price, and was it above or below the close?", "BONFIG", "2026-10-23", "2026-10-24", "fact",
  "bulk_block_deals (all rows for the symbol/date); daily_price_delivery (close); bse_announcements",
  "read the deals -> aggregate by client -> compare the deal price with the close -> state the premium/discount",
  "using one deal row as the whole picture; valuing at the close",
  gt="deal.BONFIG.2026-10-23", cov="yes",
  why="tests deal-level aggregation and price comparison")
Q("A17", "Which side was bigger on 23 October 2026, FII or DII, and what does the ratio say about the marginal buyer?", "index:Nifty 50", "2026-10-23", "2026-10-24", "fact",
  "mkt_fii_dii_cash (both nets, nifty change); the next few sessions for context",
  "compare the two nets -> compute the ratio -> state the marginal buyer -> avoid a trend claim from one day",
  "calling a one-day flow a trend; ignoring that both were positive",
  gt="flow.2026-10-23", cov="yes",
  why="tests flow-ratio arithmetic with a trend guard")
Q("A17", "Is there a same-day relationship between FII net flow and the Nifty move in 2026? Show the worst divergence day.", "index:Nifty 50", "2026", "2026-10-24", "explanation",
  "mkt_fii_dii_cash (fii_net_cr, nifty_change_pct) for the year; mkt_nse_index_daily",
  "join by date -> compute sign agreement -> find the largest divergence -> state that correlation is not causality",
  "asserting causation from correlation; using a partial year",
  cov="yes", note="both series are daily and complete for the year.",
  why="tests correlation reasoning on two stored series")
Q("A17", "What was the promoter holding in Titagarh last quarter? terse: TITAGARH promoter %", "TITAGARH", "latest quarter", "2026-10-07", "NOT IN DATA",
  "shareholding (promoter_pct, quarter_end); the SHP filing; bse_announcements",
  "check the shareholding store -> report the row count -> state that the store is a stub -> NOT IN DATA",
  "computing a percentage from another store; using a year-old figure",
  gt="shp.count", cov="no", note="shareholding has 40 rows total, so the latest quarter is missing for almost every company.",
  gap="NEW GAP: shareholding store is a 40-row stub",
  why="tests the most common ownership question against a broken store")
Q("A17", "Which small caps saw the biggest mutual-fund accumulation last quarter? terse: MF buying small caps", "TRENT, KEI, POLYCAB", "last quarter", "2026-10-07", "NOT IN DATA",
  "shareholding (mf_pct); the SHP filings; the MF holdings feed",
  "check the store for MF percentages -> report the stub -> NOT IN DATA",
  "inferring MF buying from price action",
  gt="shp.count", cov="no", note="no MF holdings feed; shareholding is a stub.",
  gap="NEW GAP: no MF/FPI holdings feed at scheme or company level",
  why="tests a flows question the data cannot answer")
Q("A17", "Which sectors did FIIs sell most in September 2026? terse: FII sector selling Sep 2026", "KEI, POLYCAB, TATAPOWER", "2026-09", "2026-10-07", "NOT IN DATA",
  "mkt_fii_dii_cash (aggregate only); index membership; sector mapping",
  "show the aggregate flow -> show that no sector split exists -> NOT IN DATA -> state what is needed",
  "allocating the total flow across sectors by market-cap weight",
  gt="flow.2026-09", cov="no", note="the flow table is market-aggregate only; no sector-level FII/DII split.",
  gap="NEW GAP: no sector-level flow data",
  why="tests a sector-flow question and the aggregation limit")
Q("A17", "Index inclusion se kisi stock mein move aaya kya? Ek case batao. (Hinglish)", "TRENT, DIXON, KEI", "FY26", "2026-10-07", "explanation",
  "index_membership (if populated); mkt_nse_index_daily; daily_price_delivery",
  "find a membership change -> measure the window return -> compare with the index -> state that inclusion dates are incomplete",
  "treating an announcement effect as the inclusion effect; using today's membership",
  cov="partial", note="index membership history is incomplete (G2), so the event date is unreliable.",
  gap="G2", why="tests an index-flow event study with a known history gap")
Q("A17", "Which stocks had the highest turnover on 4 June 2024, and was it concentrated in PSU financials?", "RECLTD, PFC, SAIL", "2024-06-04", "2024-06-04", "ranking",
  "daily_price_delivery (turnover_lacs, volume); master_companies PSU flag/industry",
  "rank by turnover -> group by ownership -> state concentration -> avoid inferring who traded",
  "ranking by volume instead of turnover; inferring buyer identity",
  gt="px.RECLTD.2024-06-04", cov="partial", note="turnover is exact; ownership flags in master data are partly stale.",
  gap="G4", why="tests turnover ranking and group concentration")
Q("A17", "How many sessions in 2026 had FIIs selling and DIIs buying, and what did the Nifty do on those days on average?", "index:Nifty 50", "2026", "2026-10-24", "ranking",
  "mkt_fii_dii_cash (fii_net_cr<0, dii_net_cr>0, nifty_change_pct); mkt_nse_index_daily",
  "filter the divergence sessions -> count -> average the index move -> state the dispersion",
  "averaging without dispersion; using the calendar year-to-date as a full year",
  cov="yes",
  why="tests a divergence screen with dispersion reporting")
Q("A17", "Delivery percentage around results: does a high-delivery reaction day predict the next week? Test it on KEI and Titagarh.", "KEI, TITAGARH", "2026-07-01 to 2026-10-07", "2026-10-07", "explanation",
  "daily_price_delivery (delivery_pct, change_pct) around the result dates; results_xbrl dissem_ts",
  "identify reaction days -> record delivery -> compute the next-week return -> state that two names cannot establish a rule",
  "claiming a predictive rule from two observations",
  gt="px.TITAGARH.2026-08-13", cov="partial", note="data exists, but two names are not a sample.",
  gap="NEW GAP: no event-study harness over delivery/price pairs",
  why="tests statistical honesty and repeating the anti-overfit rule")
Q("A17", "Which large caps saw delivery percentage fall the most in the week after 4 June 2024, and what does that signal?", "NTPC, RELIANCE, HINDALCO", "2024-06-04 to 2024-06-11", "2024-06-11", "list",
  "daily_price_delivery (delivery_pct) for the window; the 4 June base",
  "compare each name's delivery before and after -> rank the falls -> state that a fall may mean lower conviction or less forced selling",
  "calling a delivery fall bullish or bearish without the price context",
  gt="px.NTPC.2024-06-04", cov="yes",
  why="tests post-event flow decay interpretation")
Q("A17", "September 2026 mein FIIs ne kitna becha aur DIIs ne kitna kharida? (Hinglish)", "index:Nifty 50", "2026-09", "2026-10-01", "fact",
  "mkt_fii_dii_cash aggregated by month; the session count",
  "sum both -> state both signs -> give the session count -> compare with the index move",
  "giving one side only; using an average instead of a sum",
  gt="flow.2026-09", cov="yes",
  why="tests a Hinglish monthly flow question with exact sums")

# ---------------------------------------------------------------- A18 (15)
Q("A18", "Titagarh filed Q1 FY27 results at 19:56 on 12 August 2026. What is the correct reaction window, and what was the return?", "TITAGARH", "2026-08-12 to 2026-08-13", "2026-08-13", "fact",
  "results_xbrl.filings (dissem_ts); daily_price_delivery (13 Aug close/change); the prior close",
  "check the filing time against the close -> if after close, day+1 is the reaction -> report the return and the base close",
  "using the filing day's return; ignoring the after-close timestamp",
  gt="px.TITAGARH.2026-08-13", cov="yes",
  why="tests event-window construction from a filing timestamp")
Q("A18", "KEI filed Q1 FY27 results at 20:52 on 3 August 2026. What was the day-after return, and does it match the margin narrative?", "KEI", "2026-08-03 to 2026-08-04", "2026-08-04", "fact",
  "results_xbrl.filings (dissem_ts); daily_price_delivery (4 Aug); XBRL revenue and cost lines; the margin commentary",
  "confirm after-close -> take 4 Aug -> compute the return -> check the reported margin direction -> state agreement or not",
  "claiming a cause from the return; using the filing-day move",
  gt="px.KEI.2026-08-04", cov="yes",
  why="tests an after-close event window with a fundamental cross-check")
Q("A18", "BEL filed at 16:38 on 27 July 2026. The next session fell 4.46%. Was that a post-close or intraday filing?", "BEL", "2026-07-27 to 2026-07-28", "2026-07-28", "fact",
  "results_xbrl.filings (dissem_ts 16:38); the market close time; daily_price_delivery for both days",
  "compare the filing time with 15:30 -> it is post-close -> use the next session -> state the return",
  "using the 27 July move as the reaction",
  gt="px.BEL.2026-07-28", cov="yes",
  why="tests the 15:30 boundary, a small detail that flips many answers")
Q("A18", "HAL ne 14:19 par file kiya aur 1.75% chadha — kya yeh clean reaction hai? (Hinglish)", "HAL", "2026-08-12", "2026-08-12", "explanation",
  "results_xbrl.filings (dissem_ts); daily_price_delivery; intraday data (absent)",
  "see the filing was intraday -> state the same-day move mixes pre- and post-filing trades -> report it as contaminated, not clean",
  "calling an intraday-filing day a clean reaction",
  gt="px.HAL.2026-08-12", cov="partial", note="no intraday bars, so the pre/post split cannot be measured.",
  gap="NEW GAP: no intraday price bars for intraday-filing event windows",
  why="tests contaminated-window recognition")
Q("A18", "RVNL filed at 17:19 on 11 August 2026 and the stock closed flat the next day. What does a zero return tell you?", "RVNL", "2026-08-11 to 2026-08-12", "2026-08-12", "fact",
  "results_xbrl.filings (dissem_ts); daily_price_delivery (12 Aug close = prior close); volume",
  "confirm the filing window -> report the zero return -> check volume for whether anyone traded -> state that no move is still an information event",
  "calling a zero return 'no reaction' without volume; treating it as missing data",
  gt="px.RVNL.2026-08-12", cov="yes",
  why="tests the null-result case, which most QA sets omit")
Q("A18", "Tata Steel filed at 19:56 on 30 July 2026 and rose 1.48% the next session. How large is that versus its own typical daily move?", "TATASTEEL", "2026-07-30 to 2026-07-31", "2026-07-31", "fact",
  "results_xbrl.filings; daily_price_delivery (31 Jul); trailing 20-day absolute return",
  "compute the reaction -> compute the trailing average absolute move -> state the multiple -> avoid a beat/miss claim",
  "calling a 1.5% move significant for a high-beta steel stock",
  gt="px.TATASTEEL.2026-07-31", cov="yes",
  why="tests reaction normalisation by stock volatility")
Q("A18", "IRCTC filed at 20:43 on 12 August 2026 and fell 1.77% the next day. What two alternatives should be ruled out first?", "IRCTC", "2026-08-12 to 2026-08-13", "2026-08-13", "explanation",
  "results_xbrl.filings; daily_price_delivery; mkt_nse_index_daily (13 Aug -0.16%); bse_announcements",
  "check the index move -> check for a corporate action -> check for another filing -> then attribute the residual",
  "attributing a small move to results without checking the market",
  gt="px.IRCTC.2026-08-13", cov="yes",
  why="tests the market-adjusted residual, not the raw return")
Q("A18", "Jubilant FoodWorks filed at 16:30 on 13 August 2026. Why is the 14 August move the right window, and what was it?", "JUBLFOOD", "2026-08-13 to 2026-08-14", "2026-08-14", "fact",
  "results_xbrl.filings (16:30); daily_price_delivery 13-14 Aug; the market close",
  "classify the filing as post-close -> take the next session -> report the move",
  "using the 13 August +1.41% as the reaction",
  gt="px.JUBLFOOD.2026-08-14", cov="yes",
  why="tests post-close classification one hour after the bell")
Q("A18", "Suzlon filed at 15:11 on 28 July 2026, during the session, and fell 9.65% that day. What can and cannot be concluded?", "SUZLON", "2026-07-28", "2026-07-28", "explanation",
  "results_xbrl.filings (15:11); daily_price_delivery; intraday data (absent)",
  "state that 15:11 is inside the session -> the day mixes both -> conclude only that the market moved down on the day, not the filing effect",
  "claiming the full 9.65% is the results reaction",
  gt="px.SUZLON.2026-07-28", cov="partial", note="no intraday bars to split the 15:11 filing effect.",
  gap="NEW GAP: no intraday bars for intraday filings",
  why="tests an explicitly limited conclusion")
Q("A18", "Mankind filed at 20:15 on 30 July 2026 and fell 4.13% on 31 July. What was the market doing that day?", "MANKIND", "2026-07-30 to 2026-07-31", "2026-07-31", "explanation",
  "results_xbrl.filings; daily_price_delivery; mkt_nse_index_daily for 31 July; peer pharma moves",
  "get the market return -> compute the excess -> check pharma peers -> state the stock-specific residual",
  "using the raw return as the results effect",
  gt="px.MANKIND.2026-07-31", cov="partial", note="the stock move is exact; the index/peer same-day query is not in the fact set.",
  why="tests market adjustment on a result day")
Q("A18", "PB Fintech filed a clarification on price movement on Sunday 27 September 2026. What is the first session that can react, and what did it do?", "POLICYBZR", "2026-09-27 to 2026-09-28", "2026-09-28", "explanation",
  "bse_announcements (clarification filing, DissemDT); daily_price_delivery for the next session; the 24 September crash",
  "note the Sunday filing -> next trading session -> report that session -> state the file time and whether it precedes the open",
  "using the Sunday as a trading day; ignoring that the 25th had already moved",
  gt="ann.POLICYBZR.clarify", cov="partial", note="the clarification date is exact; the next-session return is not in the fact set.",
  why="tests non-trading-day event handling")
Q("A18", "Trent's 1:2 bonus had an ex-date of 4 June 2026. How should an event study treat that day?", "TRENT", "2026-06-04", "2026-06-04", "explanation",
  "corporate_actions (BONUS, ex_date); adjusted vs raw price series; daily_price_delivery",
  "read the ratio -> use the adjusted series or the theoretical ex-price -> state that raw close falls mechanically -> do not call it a loss",
  "computing a raw return across the ex-date",
  gt="ca.TRENT.bonus", cov="yes",
  why="tests corporate-action adjustment inside an event study")
Q("A18", "KAYNES 14 May 2026 — results or management change?", "KAYNES", "2026-05-13 to 2026-05-14", "2026-05-14", "explanation",
  "bse_announcements (13 May: results, financial results, change in management); daily_price_delivery; results_xbrl",
  "list the filings -> read the results content -> read the management change -> state that the store cannot separate the two, and say what would",
  "picking one explanation from timing alone",
  gt="px.KAYNES.2026-05-14", cov="partial", note="filings and returns are exact; the attachment content needed to separate causes is missing.",
  gap="NEW GAP: announcement attachments are not text-extracted",
  why="tests competing explanations from one filing batch")
Q("A18", "Cyient saw a bulk deal on 23 October 2026 and rose 7.81%. What does the deal data say about the direction of pressure?", "CYIENT", "2026-10-23", "2026-10-24", "explanation",
  "bulk_block_deals (client, side, qty, price); daily_price_delivery (close, change); bse_announcements",
  "read the deal side -> compare the deal price with the close -> state the pressure direction -> avoid a causal claim from one day",
  "assuming a bulk buy is bullish; ignoring the price paid",
  gt="px.CYIENT.2026-10-23", cov="yes",
  why="tests deal-side and price-versus-close reasoning")
Q("A18", "Across the twelve Q1 FY27 result reactions here, which stock's move was largest relative to its own volatility, and what is the caveat?", "TITAGARH, KEI, BEL, HAL", "Q1 FY27", "2026-08-20", "ranking",
  "results_xbrl.filings (dissem_ts); daily_price_delivery (reaction day and trailing 20-day absolute move)",
  "build the window for each -> normalise by trailing volatility -> rank -> state that twelve events are not a sample",
  "comparing raw returns across stocks with different volatility; claiming significance",
  cov="partial", note="the inputs exist; the ranking is hand-built and the sample is tiny.",
  gap="NEW GAP: no event-study harness with a volatility normaliser",
  why="tests a cross-event ranking with a statistical caveat")

# ---------------------------------------------------------------- A19 (15)
Q("A19", "If the monsoon fails, which listed sectors are most exposed, and in what order would the effect show up?", "COROMANDEL, CHAMBLFERT, EIDPARRY, BALRAMCHIN", "FY27", "2026-10-07", "ranking",
  "ar_facts revenue mix; results_xbrl segment revenue; policy_events (MSP/subsidy); macro series (rainfall absent)",
  "map: rainfall -> crop area -> agri-input demand -> sugar/agri processing -> tractor demand; rank by revenue sensitivity; label every coefficient as an assumption",
  "presenting a rainfall forecast as data; inventing an elasticity",
  cov="partial", note="no rainfall series is stored; the sector map is inference from AR mixes.",
  gap="G12", why="tests a what-if with an explicit missing macro series")
Q("A19", "Crude is already at 103.53 on 30 September 2026. If it holds, which listed sectors lose most, and which gain?", "ASIANPAINT, INDIGO, IOC, GAIL, commodity:crude_brent", "FY27", "2026-10-07", "ranking",
  "mkt_commodity_daily (crude_brent); ar_facts input shares; results_xbrl margins; concall pass-through commentary",
  "list users and producers -> take each input share -> rank by cost impact -> separate upstream gain from downstream loss",
  "treating crude as unambiguously bad for the market; ignoring upstream producers",
  gt="cmd.crude_brent.2026-09-30", cov="partial", note="the price is exact; per-company input shares are AR prose.",
  gap="NEW GAP: no input-cost-share table",
  why="tests a two-sided commodity what-if at a real price")
Q("A19", "If US tariffs rise another 25 points, which listed exporters are most exposed, and what would you check first?", "KPRMILL, WELSPUNLIV, SUNPHARMA, MOTHERSON", "FY27", "2026-10-07", "ranking",
  "policy_events (tariff rows); ar_facts geographic split; results_xbrl segment revenue; concall US commentary",
  "map tariffs -> US revenue share -> pass-through ability -> rank; state that the tariff level is a scenario, not a stored policy",
  "quoting a hypothetical rate as a stored event",
  gt="pol.us10", cov="partial", note="one real US tariff line is stored; the +25 scenario is not.",
  gap="G10", why="tests scenario reasoning anchored on a real policy row")
Q("A19", "If the rupee goes to 100, who wins and who loses among listed companies? Give both sides with a channel each.", "INFY, SUNPHARMA, ASIANPAINT, INDIGO, commodity:usdinr", "FY27", "2026-10-07", "ranking",
  "mkt_commodity_daily (usdinr 96.05); ar_facts currency exposure; results_xbrl margins",
  "take the current level -> take the move to 100 -> exporters gain on translation, importers lose -> rank by FX sensitivity",
  "assuming every exporter gains equally; ignoring hedges",
  gt="cmd.usdinr.2026-09-30", cov="partial", note="the spot level is exact; sensitivity is not a stored field.",
  gap="NEW GAP: no FX-sensitivity field",
  why="tests an FX what-if with a real starting point")
Q("A19", "Gold is 4,186.7. If it goes to 5,000, do jewellers or gold-loan NBFCs do better, and why is the answer not obvious?", "TITAN, MUTHOOTFIN, MANAPPURAM, commodity:gold", "FY27", "2026-10-07", "explanation",
  "mkt_commodity_daily (gold); results_xbrl; concall demand/LTV commentary; AR inventory note",
  "jeweller: inventory gain vs volume loss -> lender: collateral value vs LTV cap -> compare the two under a demand assumption",
  "assuming jewellers always benefit from higher gold",
  gt="cmd.gold.2026-09-30", cov="partial", note="the gold level is exact; the demand elasticity is an assumption.",
  gap="NEW GAP: no gold-demand or LTV series",
  why="tests opposite-sign reasoning in a what-if")
Q("A19", "coal scarcity FY27 — which sectors, answerable?", "NTPC, TATAPOWER, ULTRACEMCO, commodity:coal_newcastle", "FY27", "2026-10-07", "NOT IN DATA",
  "mkt_commodity_daily (coal_newcastle ends 2025-12-26); results_notes fuel note; concall fuel commentary",
  "check the coal series -> zero rows after 2025-12-26 -> say the 2026 scarcity cannot be evidenced from the series -> state what would fix it",
  "extrapolating a coal price; using a stale series",
  gt="coal.after2025", cov="no", note="coal_newcastle has 0 rows after 2025-12-26.",
  gap="G12", why="tests a what-if blocked by a stale series")
Q("A19", "If the FY27 public capex of Rs 12.2 lakh crore is spent as budgeted, which listed sectors see it first, which later, and who loses?", "SAIL, TATASTEEL, TITAGARH, policy:pol.public_capex", "FY27", "2026-10-07", "explanation",
  "policy_events (id 9329: amount_inr_crore, old_value, new_value, sectors; quote_ok=1, source_kind=doc, source_id=12404); results_xbrl revenue; concall order commentary",
  "read the capex line and its base -> order sectors by spend transmission: EPC/construction, then cement/steel, then capital goods -> state that the row names no listed loser -> state that fiscal financing cost is outside the row",
  "adding the capex to a company's revenue; naming a listed loser the policy row does not support",
  gt="pol.public_capex", cov="partial", note="the outlay and the named sectors are exact; the per-sector split and the financing cost are not in the row.",
  gap="G10", why="tests a cross-sector what-if with an explicit 'no listed loser' guard")
Q("A19", "If the semiconductor incentive doubles, which listed companies benefit first and which only in the second round?", "DIXON, KAYNES, SYRMA, SRF, policy:pol.ism2", "FY27", "2026-10-07", "ranking",
  "policy_events (ISM 2.0); results_xbrl capex; concall semiconductor commentary",
  "first round: fabs/ATMP (mostly unlisted) -> second round: EMS, materials, equipment -> rank by disclosed exposure",
  "calling an EMS company a fab beneficiary",
  gt="pol.ism2", cov="partial", note="the policy is exact; the listed exposure map is not.",
  gap="G10", why="tests round-one versus round-two policy beneficiaries")
Q("A19", "If the RBI cuts 100bp over a year, which listed sectors re-rate first, and what breaks the chain?", "CHOLAFIN, AAVAS, DLF, HDFCBANK", "FY27", "2026-10-07", "ranking",
  "policy_events/pib_releases on rates; results_xbrl NIM/cost of funds; concall rate commentary",
  "repo -> funding cost -> NIM -> loan growth -> affordability -> realty sales; rank by repricing speed; name the break (deposit competition)",
  "assuming a rate cut mechanically lifts all financials",
  cov="partial", note="no structured policy-rate series; rate moves are PIB text.",
  gap="G10", why="tests a rate-cut what-if with repricing lags")
Q("A19", "If data-centre capex doubles, which listed companies see it first, and is the exposure measurable?", "CUMMINSIND, POWERINDIA, TATAPOWER, POLYCAB", "FY27", "2026-10-07", "ranking",
  "concall data-centre commentary; results_xbrl segment revenue; ar_facts end-market note",
  "map capex -> equipment -> power -> cables; rank by disclosed share; state the missing field",
  "assuming a utility's whole revenue is data-centre linked",
  cov="partial", note="end-market split is not disclosed as a field.",
  gap="NEW GAP: no end-market revenue split",
  why="tests theme exposure sizing")
Q("A19", "If EV penetration hits 30%, which listed auto-component names lose and which gain? Give both sides.", "MOTHERSON, SONACOMS, UNOMINDA, BOSCHLTD", "FY30", "2026-10-07", "ranking",
  "concall EV-content commentary; ar_facts product mix; results_xbrl segment revenue",
  "map ICE-only parts -> losers; EV content -> winners; rank by revenue share; state the assumption",
  "assuming every auto ancillary is an EV winner",
  cov="partial", note="product mix is disclosed; EV revenue share is not.",
  gap="NEW GAP: no EV revenue-share field",
  why="tests a disruption what-if with two-sided exposure")
Q("A19", "If China+1 accelerates, which listed sectors win, and what is the first evidence you would look for?", "DIXON, KPRMILL, SRF, AARTIIND", "FY27", "2026-10-07", "explanation",
  "concall China+1 commentary; ar_facts capacity/customers; results_xbrl export revenue",
  "map the shift -> capacity additions -> customer wins -> look for disclosed new clients -> state the evidence bar",
  "claiming a shift from a single client win",
  cov="partial", note="commentary exists; no customer-win or capacity-commitment table.",
  gap="G6", why="tests a structural what-if with an evidence standard")
Q("A19", "If container freight rates spike, which listed exporters lose and does a shipping line gain?", "SCI, KPRMILL, WELSPUNLIV", "FY27", "2026-10-07", "explanation",
  "results_xbrl freight cost; concall freight commentary; ar_facts export share; freight-rate series (absent)",
  "exporter: freight as a cost share -> margin; shipping line: revenue up -> margin; state that no freight series is stored",
  "inventing a freight rate",
  cov="partial", note="no freight-rate series in the stores.",
  gap="G12", why="tests a what-if whose driver series is missing")
Q("A19", "If GST rates are cut on consumer durables, who gains more: a durables maker or an FMCG company?", "VOLTAS, CROMPTON, HINDUNILVR", "FY27", "2026-10-07", "explanation",
  "policy_events (GST/tax rows); results_xbrl revenue and elasticity proxies; concall price/pass-through commentary",
  "rate cut -> price fall -> volume elasticity -> margin; compare an elastic durables category with a staple -> rank",
  "assuming a rate cut is fully passed on; ignoring the elasticity difference",
  cov="partial", note="no GST rate history per product is stored.",
  gap="G10", why="tests an elasticity-based what-if")
Q("A19", "Agar crude $100 ho jaye to kaunse listed sectors sabse zyada peedit honge? (Hinglish)", "ASIANPAINT, INDIGO, APOLLOTYRE, commodity:crude_brent", "FY27", "2026-10-07", "ranking",
  "mkt_commodity_daily (crude_brent at 103.53); ar_facts input share; results_xbrl margins",
  "name the users -> cost share -> pass-through -> rank -> label assumptions",
  "treating crude as bad for every sector",
  gt="cmd.crude_brent.2026-09-30", cov="partial", note="the crude level is exact; input shares are prose.",
  gap="G12", why="tests a Hinglish commodity what-if")

# ---------------------------------------------------------------- A20 (15)
Q("A20", "What will Reliance's share price be on Diwali 2027?", "RELIANCE", "Diwali 2027", "2026-10-27", "NOT IN DATA",
  "daily_price_delivery and any model output; there is no forecast store with a target price",
  "state that this is a forecast -> check for a stored model or consensus -> if absent, NOT IN DATA -> state that only a scenario range could be offered, labelled",
  "producing a price target as if it were data; presenting a scenario as a forecast",
  cov="no", note="no forecast or consensus store; the question is out of scope for a fact database.",
  gap="NEW GAP: no consensus or target-price store",
  why="tests the out-of-scope boundary, the family-20 requirement")
Q("A20", "How many electric two-wheelers did Ola Electric deliver in September 2026?", "OLAELEC, ATHERENERG", "Sep 2026", "2026-10-27", "NOT IN DATA",
  "no Vahan/registration table; company announcements if any; results_xbrl revenue",
  "check for a registration feed -> absent -> check for a monthly disclosure -> if absent, NOT IN DATA",
  "dividing quarterly revenue by a price to invent units",
  cov="no", note="no vehicle-registration or monthly volume feed.",
  gap="NEW GAP: no Vahan/EV registration feed",
  why="tests a volume question the database cannot answer")
Q("A20", "What is Dixon's CEO paid, and how has that changed in three years?", "DIXON", "FY24-FY26", "2026-10-27", "fact",
  "ar_facts (managerial remuneration category); ar_docs for the years; results_notes",
  "find the remuneration note -> take three years -> state the basis -> flag if only one year is extracted",
  "comparing a total remuneration with a salary only",
  cov="partial", note="remuneration is in AR notes; extraction across three reports is uneven.",
  gap="G6", why="tests a mundane governance question inside long documents")
Q("A20", "Which company will be the next Nifty 50 inclusion, and when?", "index:Nifty 50", "future", "2026-10-27", "NOT IN DATA",
  "index_membership history (incomplete); mkt_nse_index_daily; no methodology or candidate list",
  "check the membership store -> report the gap -> say inclusion requires the NSE methodology and float data -> NOT IN DATA",
  "naming a candidate from market-cap rank alone",
  cov="no", note="index membership history is incomplete (G2) and no methodology/candidate store exists.",
  gap="G2", why="tests a forward index question with two missing inputs")
Q("A20", "What exactly did the RBI governor say about the rupee at the last MPC, and does the store have his words?", "index:Nifty 50", "last MPC", "2026-10-27", "fact",
  "pib_releases (RBI MPC releases, body text); policy_events (rate rows); no RBI speech transcript store",
  "find the MPC release -> quote the rupee passage if present -> if absent, say the statement is not in the store",
  "paraphrasing a speech that is not stored; quoting a news summary as the governor",
  cov="partial", note="the MPC release body is stored; the press-conference remarks are not.",
  gap="G10", why="tests source-level precision for an official quote")
Q("A20", "How much of Titagarh does FII money own right now?", "TITAGARH", "latest quarter", "2026-10-27", "NOT IN DATA",
  "shareholding (fii_pct); the SHP filing; no FPI holdings feed",
  "check the shareholding store -> stub -> NOT IN DATA -> state that the SHP filing would answer it",
  "using an index weight as ownership; using a stale row",
  gt="shp.count", cov="no", note="shareholding is a 40-row stub.",
  gap="NEW GAP: shareholding store is a 40-row stub",
  why="tests an ownership question against a known stub")
Q("A20", "How many shares did TruAlt's promoter actually pledge in September 2026?", "TRUALT", "Sep 2026", "2026-10-27", "fact",
  "bse_announcements (pledge headline, DissemDT); the SAST/PIT attachment; shareholding",
  "find the filing -> read the attachment for the share count -> if unparsed, say the count is NOT IN DATA",
  "quoting a percentage without a base; assuming the headline count",
  gt="ann.TRUALT.pledge", cov="partial", note="the pledgor and date are stored; the share count is in the attachment.",
  gap="NEW GAP: pledge quantity is not extracted",
  why="tests the difference between a pledge event and its size")
Q("A20", "Why exactly did Milefur's auditor resign? Give the auditor's own words.", "MILEFUR", "Sep 2026", "2026-10-27", "NOT IN DATA",
  "bse_announcements (resignation filing); the attachment; results_notes",
  "find the filing -> the reason is in the attachment -> if unparsed, quote nothing and say NOT IN DATA",
  "inventing a reason; quoting a template sentence as the auditor's words",
  gt="ann.MILEFUR.auditor", cov="partial", note="the filing and date exist; the reason text does not.",
  gap="NEW GAP: announcement attachments are not text-extracted",
  why="tests the hardest part of a governance question: the reason")
Q("A20", "Which listed company had the highest employee attrition in FY26?", "TCS, INFY, WIPRO", "FY26", "2026-10-27", "list",
  "ar_facts (employee/attrition category); results_notes; concall HR commentary",
  "search the AR facts for attrition -> keep companies with a stated number -> rank -> state that coverage is partial",
  "comparing attrition definitions across companies without saying so",
  cov="partial", note="attrition appears in some IT ARs and calls but is not a tagged field.",
  gap="G6", why="tests a cross-company HR metric with definition risk")
Q("A20", "How much did Suzlon pay its statutory auditor last year?", "SUZLON", "FY26", "2026-10-27", "fact",
  "ar_facts (auditor remuneration); ar_docs; results_notes",
  "find the auditor-remuneration note -> take the year -> state whether it includes subsidiaries -> cite the page",
  "mixing audit fee with total services; using a standalone figure for a consolidated group",
  cov="partial", note="the note is in the AR; extraction depends on the item label.",
  gap="G6", why="tests a precise number inside a long document")
Q("A20", "What is the exact copper content per kilometre of a 33 kV cable?", "POLYCAB, commodity:copper", "n/a", "2026-10-27", "NOT IN DATA",
  "AR product specifications; deck technical slides; no engineering BOM store",
  "check for a technical specification in the filings -> absent -> NOT IN DATA -> state that this is an engineering parameter",
  "deriving it from revenue and copper cost",
  cov="no", note="engineering specifications are not in any store.",
  gap="NEW GAP: no product-level bill-of-materials data",
  why="tests an engineering question the database should refuse")
Q("A20", "Which mid-cap will double in 2027?", "DIXON, KEI, TITAGARH", "2027", "2026-10-27", "NOT IN DATA",
  "price history and any model output; no forecast store",
  "state it is a forecast -> no consensus/target store -> NOT IN DATA -> offer only historical base rates if asked",
  "producing a list as if it were analysis; using momentum as a forecast",
  cov="no", note="no forecast store; the question is out of scope.",
  gap="NEW GAP: no consensus or target-price store",
  why="tests refusal of a pure prediction request")
Q("A20", "SRF FY26 patent count by chemistry", "SRF", "FY26", "2026-10-27", "fact",
  "ar_facts (R&D/patent category); the AR business review; results_notes",
  "find the R&D section -> take the patent count -> state the chemistry -> flag if only a narrative is present",
  "counting applications as grants; inventing a number",
  cov="partial", note="R&D narrative is in the AR; a patent count is not always disclosed.",
  gap="G6", why="tests an intangible-asset question with narrative-only sources")
Q("A20", "How much money did retail investors lose on 4 June 2024, in rupees?", "index:Nifty 50", "2024-06-04", "2024-06-04", "NOT IN DATA",
  "mkt_nse_index_daily and market-cap proxies; no investor-level holdings data",
  "show the index fall -> show that investor-level P&L needs holdings -> NOT IN DATA -> state that only an aggregate market-cap loss could be approximated, labelled",
  "presenting a market-cap fall as investor loss; assuming retail held the index",
  cov="partial", note="market-level price data exists; investor-level holdings do not.",
  gap="NEW GAP: no investor-level holdings data",
  why="tests the difference between a market move and an investor outcome")
Q("A20", "What did the Finance Minister say about capital-gains tax in the 2026 Budget, and is the exact sentence stored?", "index:Nifty 50", "2026-02-01", "2026-02-02", "fact",
  "pib_releases (Budget release, body); policy_events (tax rows); macro_events (Budget speech)",
  "find the Budget release -> search for capital gains -> quote if present -> otherwise say the speech text is not stored",
  "paraphrasing from memory; quoting a summary as the speech",
  cov="partial", note="the Budget release body is stored; the full speech may not be.",
  gap="G10", why="tests exact-quote retrieval from policy text")

# ---------------------------------------------------------------- build
ALLOWED_KINDS = {"fact", "date", "list", "ranking", "explanation", "NOT IN DATA"}
BUCKET_ORDER = ["LARGE", "MID", "SMALL", "MICRO"]
HINGLISH_RE = __import__("re").compile(
    r"\b(kaun|kaunsi|kaunse|kaise|kya|kitna|kitne|batao|mein|hai|hain|se|par|sabse|aur|karo|nahi|yeh|woh)\b", __import__("re").I)


def load_universe():
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(DATA / "equity_intelligence.db", timeout_s=60)
    ents = {}
    for r in con.execute("SELECT nse_symbol,isin,bse_code,company_name,industry,sector,market_cap_tier FROM master_companies WHERE nse_symbol IS NOT NULL"):
        ents[r[0]] = dict(symbol=r[0], isin=r[1], bse_code=r[2], name=r[3], industry=r[4],
                          sector=r[5], bucket=r[6], basic_industry=None)
    try:
        for sym, bi in con.execute("SELECT symbol,basic_industry FROM company_industry WHERE symbol IS NOT NULL"):
            if sym in ents and bi:
                ents[sym]["basic_industry"] = bi
    except Exception:
        pass
    return ents


def load_macro_event_guard():
    """Split macro_events ids: sourced (doc_id set, not PHASE5_) vs unsourced."""
    from reality_engine.db.readonly import connect_ro
    con = connect_ro(DATA / "equity_intelligence.db", timeout_s=30)
    for eid, doc_id in con.execute("SELECT event_id, doc_id FROM macro_events"):
        (EVENTS["sourced"] if doc_id is not None and not eid.startswith("PHASE5_")
         else EVENTS["unsourced"]).add(eid)


def assert_sourced_fact(fid):
    """Reject a ground-truth fact that rests on an unsourced macro_events row or a PHASE5_* id."""
    if "PHASE5_" in fid.upper():
        raise SystemExit(f"{fid}: PHASE5_* fixture facts are rejected")
    if fid not in FACTS:
        raise SystemExit(f"missing ground-truth fact {fid!r}")
    f = FACTS[fid]
    blob = fid + " " + f["sql"] + " " + json.dumps(f["value"], ensure_ascii=False, default=str)
    if "PHASE5_" in blob.upper():
        raise SystemExit(f"{fid}: PHASE5_* fixture reference in fact")
    for eid in EVENTS["unsourced"]:
        if eid in blob:
            raise SystemExit(f"{fid}: drawn from unsourced macro_events row {eid!r} (doc_id is null)")
    if "macro_events" in f["sql"].lower() and not any(eid in blob for eid in EVENTS["sourced"]):
        raise SystemExit(f"{fid}: a macro_events fact must name a sourced MEV_* row")


def resolve(ents_str, universe, qid):
    out = []
    for raw in [e.strip() for e in ents_str.split(",") if e.strip()]:
        if raw.lower().startswith("index:"):
            out.append({"type": "index", "name": raw.split(":", 1)[1].strip()})
        elif raw.lower().startswith("policy:"):
            fid = raw.split(":", 1)[1].strip()
            out.append({"type": "policy", "id": fid, "name": FACTS[fid]["value"].get("policy") if fid in FACTS else None})
        elif raw.lower().startswith("event:"):
            eid = raw.split(":", 1)[1].strip()
            if eid not in EVENTS["sourced"]:
                raise SystemExit(f"{qid}: event {eid!r} is not a sourced macro_event (doc_id is null)")
            out.append({"type": "event", "id": eid, "name": FACTS.get("mev." + eid, {}).get("value", {}).get("name")})
        elif raw.lower().startswith("industry:"):
            out.append({"type": "industry", "name": raw.split(":", 1)[1].strip()})
        elif raw.lower().startswith("theme:"):
            out.append({"type": "theme", "name": raw.split(":", 1)[1].strip()})
        elif raw.lower().startswith("commodity:"):
            out.append({"type": "commodity", "name": raw.split(":", 1)[1].strip()})
        else:
            if raw not in universe:
                raise SystemExit(f"{qid}: unresolved stock symbol {raw!r}")
            u = universe[raw]
            out.append({"type": "stock", "symbol": raw, "isin": u["isin"], "bse_code": u["bse_code"],
                        "name": u["name"], "industry": u["industry"], "basic_industry": u["basic_industry"],
                        "market_cap_bucket": u["bucket"]})
    if not out:
        raise SystemExit(f"{qid}: no entities")
    return out


def _num(x):
    try:
        return f"{float(x):,.2f}".rstrip("0").rstrip(".")
    except Exception:
        return str(x)


def gt_text(fid):
    f = FACTS.get(fid)
    if not f:
        raise SystemExit(f"missing ground-truth fact {fid!r}")
    v = f["value"]
    if isinstance(v, list):
        return " | ".join(str(x.get("channel") or x) for x in v[:3])
    if not isinstance(v, dict):
        return str(v)
    if "pct" in v and "index" in v:
        return f"{v['index']} closed {_num(v['close'])} on {v['date']} ({_num(v['pct'])}%)"
    if "close" in v and "date" in v:
        name = v.get("symbol") or v.get("commodity") or v.get("index") or fid.split(".")[1]
        extra = ""
        if "change_pct" in v:
            extra = f", {_num(v['change_pct'])}%"
        if "delivery_pct" in v and v.get("delivery_pct") is not None:
            extra += f", delivery {_num(v['delivery_pct'])}%"
        return f"{name} closed {_num(v['close'])} on {v['date']}{extra}"
    if "fii_net_cr" in v:
        return f"FII net {_num(v['fii_net_cr'])} crore, DII net {_num(v['dii_net_cr'])} crore on {v.get('date', v.get('month'))}" + (f" ({v['sessions']} sessions)" if v.get("sessions") else "")
    if "opinion" in v:
        return f"{v['symbol']} {v.get('quarter')} ({v.get('period_end')}): audit_opinion = '{v['opinion']}', {v.get('audited')}, filed {str(v.get('dissem'))[:19]}"
    if "policy" in v:
        amt = f", Rs {_num(v['amount_cr'])} crore" if v.get("amount_cr") else ""
        when = v.get("effective_date") or v.get("published_at")
        when = f" [{when}]" if when else ""
        chg = (f", {v['old_value']} -> {v['new_value']}"
               if v.get("old_value") and v.get("new_value") else "")
        extra = f"; {v['market']}" if v.get("market") else ""
        return f"{v['policy']}{when} ({v.get('stage')}, {v.get('direction')}){amt}{chg}{extra}"
    if "headline" in v:
        return f"{v.get('symbol') or 'filing'}: \u201c{str(v['headline'])[:180]}\u201d filed {v.get('dt')}"
    if "client" in v:
        return f"{v['client']} {v['side']} {v['qty']} shares at {_num(v['price'])} on {v['date']}"
    if "ex_date" in v:
        return f"{v['symbol']} {v['subject']} ex-date {v['ex_date']}"
    if "channel" in v:
        return v["channel"]
    if "event_id" in v:
        return f"{v['name']} dated {v['date']}"
    if "metric" in v and v.get("value"):
        unit_val = str(v.get("unit") or "").strip()
        show_unit = bool(unit_val) and not str(v["value"]).strip().endswith(unit_val)
        unit = f" {unit_val}" if show_unit else ""
        per = f" ({v['period']})" if v.get("period") else ""
        q = f" \u2014 \u201c{str(v['quote'])[:180]}\u201d" if v.get("quote") else ""
        return f"{v['metric']}: {v['value']}{unit}{per}{q}"
    if "quote" in v:
        return f"\u201c{str(v['quote'])[:220]}\u201d"
    if "rows" in v:
        return f"row count {v['rows']}"
    if "companies" in v:
        return f"{v['companies']} companies / {v['filings']} filings for period_end 2026-09-30"
    if "rows_after_2025_12_26" in v:
        return f"{v['rows_after_2025_12_26']} coal rows after 2025-12-26"
    if "high" in v:
        return f"{v['symbol']} 2026 high {_num(v['high'])}, low {_num(v['low'])}"
    if "first" in v:
        return f"price_bands rows {v['first']}..{v['last']}"
    if "revenue" in v:
        rev = v["revenue"] / 1e7 if v["revenue"] else None
        pat = v["pat"] / 1e7 if v.get("pat") else None
        s = f"{v['quarter']} {v['basis']}: revenue Rs {_num(rev)} crore"
        if pat is not None:
            s += f", PAT Rs {_num(pat)} crore"
        return s + f" (filed {str(v.get('dissem'))[:19]})"
    return json.dumps(v, ensure_ascii=False)[:300]


def canon_gap(g):
    if not g or not g.startswith("NEW GAP"):
        return g
    rules = [
        (r"attachment", "NG01 announcement attachments are not text-extracted"),
        (r"intraday", "NG27 no intraday bars, so intraday-filing event windows cannot be measured"),
        (r"opinion|going.cons|emphasis|qualification", "NG02 audit opinion detail (type / EOM / going-concern / KAM) is not extracted"),
        (r"auditor-firm|issuer/auditor", "NG03 no auditor-firm or parent-subsidiary entity resolution"),
        (r"kmp|person/role|board/kmp", "NG04 no KMP/board person-role-date table"),
        (r"shareholding|pledge percentage|promoter|mf/fpi", "NG05 shareholding store is a 40-row stub (pledge/holder % unusable)"),
        (r"insider|sast", "NG06 insider/SAST transaction store is empty"),
        (r"pledge event|pledge quantity", "NG07 pledge events carry no quantity or percentage"),
        (r"enforcement|tax notice|rating action|materiality ratio", "NG08 enforcement / tax / rating events are not structured with amounts"),
        (r"objects|capital-raise", "NG09 no QIP/IPO objects-versus-utilisation table"),
        (r"revenue split|end-market|geography|import-content|import-basket|input-cost|input intensity|currency|fx|cost-structure|raw-material mix|bom|engineering|atf|gold-demand|derived-input|onshore", "NG10 no cost-share / geography / end-market / import-content table"),
        (r"price series|freight|rainfall|domestic steel", "NG11 no physical price, freight or weather series"),
        (r"capacity|utilisation|production|captive|shutdown|plant-shutdown|capital repair|housing-start|plant-location", "NG12 no capacity / utilisation / production time series"),
        (r"forecast|consensus|target-price", "NG16 no consensus or target-price store"),
        (r"store|branch|gmv|unit-economics|askm|airline operating|hospital operating|sales-velocity|auto production|volumes?|ticket-size|ltv", "NG13 no operating-metrics series (stores, orders, volumes, LTV)"),
        (r"licence|commissioning|capex-completion|jv|agreement execution", "NG14 no licence / commissioning / JV-execution event register"),
        (r"tender|award pipeline", "NG15 no tender/award pipeline table"),
        (r"vahan|vehicle-registration", "NG17 no Vahan / EV-registration feed"),
        (r"sector-level flow|sector flow", "NG18 no sector-level FII/DII flow split"),
        (r"investor-level", "NG19 no investor-level holdings data"),
        (r"theme|sector index|sector basket", "NG20 no theme map / sector index basket"),
        (r"macro-event|election|geopolitical|lockdown", "NG21 no macro-event calendar for elections, verdicts, geopolitical shocks"),
        (r"mro|medical-equipment|nuclear|private-company", "NG22 no map from unlisted / private layers to listed suppliers"),
        (r"dividend/buyback|buyback/dividend", "NG23 dividend/buyback rows are not classified ordinary vs special"),
        (r"guidance", "NG24 guidance is not linked to the actual quarterly series"),
        (r"order-to-revenue|customer-contract|customer", "NG25 no contract / customer / order-to-revenue linkage"),
        (r"policy-incentive", "NG26 no policy-incentive expiry event tag"),
        (r"event-study|harness", "NG28 no event-study harness (price x delivery x filing) with a volatility normaliser"),
        (r"revenue-share|integration/cost-curve|input-intensity|bill-of-materials", "NG10 no cost-share / geography / end-market / import-content table"),
        (r"demand commentary", "NG29 demand commentary is not tagged by cause"),
        (r"related-party", "NG25 no contract / customer / related-party linkage"),
        (r"clarification|business update", "NG01 announcement attachments are not text-extracted"),
    ]
    import re as _re
    low = g.lower()
    for pat, label in rules:
        if _re.search(pat, low, _re.I):
            return label
    return g.replace("NEW GAP: ", "NG99 ").split(";")[0]


def build_rows():
    universe = load_universe()
    load_macro_event_guard()
    for fid in FACTS:
        assert_sourced_fact(fid)
    rows = []
    counter = Counter()
    for q in QUESTIONS:
        counter[q["arch"]] += 1
        idx = counter[q["arch"]]
        qid = f"{q['arch']}-{idx:02d}"
        arch_name, family = ARCH[q["arch"]]
        ents = resolve(q["ents"], universe, qid)
        gt = gt_text(q["gt"]) if q["gt"] else None
        rows.append({
            "qid": qid,
            "archetype": f"{q['arch']} {arch_name}",
            "family": family,
            "question": q["q"],
            "entities": ents,
            "period": q["period"],
            "as_of": q["as_of"],
            "answer_kind": q["kind"],
            "rubric": {
                "required_evidence": q["ev"],
                "required_steps": q["steps"],
                "forbidden": q["forb"],
                "ground_truth": gt,
                "ground_truth_query": q["gt"],
            },
            "coverage": {"verdict": q["cov"], "note": q["note"], "gap_id": canon_gap(q["gap"])},
            "why": q["why"],
        })
    return rows


def validate(rows):
    assert len(rows) == 300, len(rows)
    assert len({r["qid"] for r in rows}) == 300
    by_arch = Counter(r["archetype"] for r in rows)
    assert len(by_arch) == 20, by_arch
    assert set(by_arch.values()) == {15}, by_arch
    for r in rows:
        assert r["question"].strip()
        assert r["rubric"]["required_evidence"] and r["rubric"]["required_steps"] and r["rubric"]["forbidden"], r["qid"]
        assert r["coverage"]["verdict"] in {"yes", "partial", "no"}, r["qid"]
        assert r["answer_kind"] in ALLOWED_KINDS, r["qid"]
        assert r["as_of"] is None or r["as_of"] <= "2026-10-27", r["qid"]
    blob = json.dumps(rows, ensure_ascii=False)
    for eid in sorted(EVENTS["unsourced"]):
        assert eid not in blob, f"unsourced macro_event {eid!r} leaked into the bank"
    assert "PHASE5_" not in blob, "PHASE5_* fixture id leaked into the bank"
    n_asof = sum(1 for r in rows if r["as_of"])
    n_hing = sum(1 for r in rows if "(Hinglish)" in r["question"])
    n_terse = sum(1 for r in rows if "terse:" in r["question"].lower() or len(r["question"].split()) <= 9)
    buckets = {e.get("market_cap_bucket") for r in rows for e in r["entities"] if e["type"] == "stock"}
    industries = {e.get("basic_industry") for r in rows for e in r["entities"] if e["type"] == "stock" and e.get("basic_industry")}
    sectors = {e.get("industry") for r in rows for e in r["entities"] if e["type"] == "stock" and e.get("industry")}
    print(f"rows=300 archetypes={len(by_arch)} as_of={n_asof} hinglish={n_hing} terse={n_terse} "
          f"buckets={sorted(b for b in buckets if b)} industries={len(industries)} sectors={len(sectors)}")
    assert buckets >= {"LARGE", "MID", "SMALL", "MICRO"}, buckets
    return dict(n_asof=n_asof, n_hing=n_hing, n_terse=n_terse, industries=len(industries),
                sectors=len(sectors), buckets=sorted(b for b in buckets if b))


def write_md(rows, stats):
    by_arch = {}
    for r in rows:
        by_arch.setdefault(r["archetype"], []).append(r)
    GAP_LABEL = {
        "G0": "ISIN anchor defective", "G2": "index membership history", "G4": "sector/industry PIT",
        "G5": "theme map", "G6": "layer-1 chunk tags (topic/known_at)", "G8": "price band 2022-02..2026-09",
        "G9": "results-notes backfill", "G10": "macro claim targets", "G11": "XBRL concept map",
        "G12": "dated macro/commodity series",
    }
    cov = Counter(r["coverage"]["verdict"] for r in rows)
    kinds = Counter(r["answer_kind"] for r in rows)
    gaps = {}
    for r in rows:
        g = r["coverage"]["gap_id"]
        if g:
            gaps.setdefault(g, []).append(r["qid"])
    L = []
    L.append("# 300 original investor questions — open bank (2026-10-27)\n")
    L.append("Hand-authored bank. It is not the 30-question reword bank (`QUESTION_BANK_300_2026-10-27.jsonl`); "
             "no question here is a rephrasing of one of Shivam's 30. Every stock resolves read-only from "
             "`master_companies`; every `ground_truth` names a fact whose SQL is listed in the appendix.\n")
    L.append("## Summary\n")
    L.append(f"- 300 rows, 20 archetypes × 15. Answer kinds: " +
             ", ".join(f"{k} {v}" for k, v in kinds.most_common()) + ".")
    L.append(f"- Coverage: yes {cov['yes']}, partial {cov['partial']}, no {cov['no']}.")
    L.append(f"- Point-in-time rows with a non-null `as_of`: {stats['n_asof']} (target 40+).")
    L.append(f"- Hinglish rows: {stats['n_hing']} (target 30+); terse keyword-style: {stats['n_terse']} (target 30+).")
    L.append(f"- Stock rows cover all four market-cap buckets and {stats['industries']} basic industries "
             f"across {stats['sectors']} sectors.\n")
    L.append("| Archetype | Family | Rows | yes | partial | no |")
    L.append("|---|---|---|---|---|---|")
    for arch, rs in by_arch.items():
        c = Counter(x["coverage"]["verdict"] for x in rs)
        L.append(f"| {arch} | {rs[0]['family']} | {len(rs)} | {c['yes']} | {c['partial']} | {c['no']} |")
    L.append("")
    L.append("| Market-cap bucket | Rows naming a stock in it |")
    L.append("|---|---|")
    for b in BUCKET_ORDER:
        n = sum(1 for r in rows for e in r["entities"] if e["type"] == "stock" and e.get("market_cap_bucket") == b)
        L.append(f"| {b} | {n} |")
    L.append("")
    L.append("## New gaps found\n")
    L.append("A gap is a question that cannot be answered well today. Each row is blocked by the gap named here; "
             "the full reason is in that row's `coverage.note`.\n")
    L.append("NG-SEED: 4 unsourced seeded macro_events (NUCLEAR_MISSION, RAIL_CAPEX_PUSH, "
             "STEEL_SAFEGUARD_DUTY, US_TARIFF_TEXTILE_RELIEF) plus 3 PHASE5_EVT_* are not "
             "quarantined in substrate_quarantine; any consumer could present them as real. "
             "(Checked: the 3 PHASE5_EVT_* are listed in substrate_quarantine under rule "
             "demo_macro_events; the 4 unsourced rows are not.)\n")
    L.append("| Gap | What is missing | Questions blocked |")
    L.append("|---|---|---|")
    for g, qids in sorted(gaps.items(), key=lambda kv: -len(kv[1])):
        if g.startswith("NEW GAP"):
            label = g.replace("NEW GAP: ", "")
            gid = "NG99"
        elif g.startswith("NG"):
            gid, label = g.split(" ", 1)
        else:
            gid, label = g, GAP_LABEL.get(g, g)
        L.append(f"| {gid} | {label} | {len(qids)}: {', '.join(qids[:8])}{' …' if len(qids) > 8 else ''} |")
    L.append("")
    for arch, rs in by_arch.items():
        L.append(f"## {arch}\n")
        L.append("| qid | Question | Entities | Period / as of | Kind | Coverage | Ground truth |")
        L.append("|---|---|---|---|---|---|---|")
        for r in rs:
            ents = ", ".join(e.get("symbol") or e.get("name") or e.get("id") or e.get("type") for e in r["entities"])
            per = r["period"] + (f" · as of {r['as_of']}" if r["as_of"] else "")
            gt = (r["rubric"]["ground_truth"] or "").replace("|", "\\|")
            q = r["question"].replace("|", "\\|")
            L.append(f"| {r['qid']} | {q} | {ents} | {per} | {r['answer_kind']} | {r['coverage']['verdict']} | {gt} |")
        L.append("")
    L.append("## Appendix — every query behind a ground truth\n")
    L.append("Fact id, the exact bounded SQL, and the observed value. Run read-only against "
             "`REALITY_DATA_ROOT`; `equity_intelligence`/`results_xbrl`/`concall_facts`/`bse_announcements` are the stores.\n")
    L.append("| Fact | Store | SQL / observed value |")
    L.append("|---|---|---|")
    used = []
    seen = set()
    for r in rows:
        fid = r["rubric"]["ground_truth_query"]
        if fid and fid not in seen:
            seen.add(fid)
            used.append((r["qid"], fid))
    for qid, fid in used:
        f = FACTS[fid]
        sql = f["sql"].replace("|", "\\|")
        val = json.dumps(f["value"], ensure_ascii=False, default=str).replace("|", "\\|")[:400]
        m = __import__("re").search(r"\b(equity_intelligence|results_xbrl|concall_facts|bse_announcements|results_notes)\.[a-z_]+", sql)
        if m:
            store = m.group(0)
        else:
            bare = {"policy_events": "equity_intelligence.policy_events",
                    "mkt_nse_index_daily": "equity_intelligence.mkt_nse_index_daily",
                    "daily_price_delivery": "equity_intelligence.daily_price_delivery",
                    "pib_releases": "equity_intelligence.pib_releases"}
            store = next((v for k, v in bare.items() if k in sql), "local fact")
        L.append(f"| {fid} (first used {qid}) | {store} | `{sql}` → `{val}` |")
    L.append("")
    OUT_MD.write_text("\n".join(L), encoding="utf-8")


def main():
    rows = build_rows()
    stats = validate(rows)
    if "--check" in sys.argv:
        print("check ok")
        return
    OUT_JSONL.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    write_md(rows, stats)
    print(f"wrote {OUT_JSONL.name} and {OUT_MD.name}")


if __name__ == "__main__":
    main()
