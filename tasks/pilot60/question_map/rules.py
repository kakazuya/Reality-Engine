"""The question map for BAJFINANCE, HINDALCO and KEC, written by Claude from reading each bank question.

One rule: mids | measures | formula. Nothing here states a result: only ``build_map.py`` sets a
row's status, from what the stores hold. A measure is one of:
  fact:<atom>            fact_v4_pilot.db, per company
  macro:<atom>           fact_v4_pilot.db, market-wide
  p3:<table>[:<metric>]  extract_proto3.db
  doc:<doc_type>         chunks, documents held per company
  claim                  v4.db claim
  ann                    bse_announcements.db
  ei:<table>             equity_intelligence.db
  member                 fact_v4_pilot.db membership
  none:<name>            no store holds this yet
"""

C, H, L, O, V = "fact:price.close", "fact:price.high", "fact:price.low", "fact:price.open", "fact:price.volume"
D, DP, TV = "fact:price.delivery_qty", "fact:price.delivery_pct", "fact:price.traded_value"
SO, SMA = "fact:price.shares_out", "fact:price.sma"
IDX, COM, SER, POL, MCL, FLOW = "macro:macro.index_close", "macro:macro.commodity_close", "macro:macro.series", "macro:macro.policy", "macro:macro.claim", "macro:macro.flow"
REV, EBITDA, PAT, EPS, BOOK, DEBT, CASH = "fact:fin.revenue", "fact:fin.ebitda", "fact:fin.pat", "fact:fin.eps", "fact:fin.book_equity", "fact:fin.total_debt", "fact:fin.cash"
RCV, CAPEX, INT, INV, HOLD, PLEDGE = "fact:fin.receivables", "fact:fin.capex", "fact:fin.interest_expense", "fact:fin.inventory", "fact:hold.pct", "fact:hold.pledge_pct"
AR, CALL, DECK, NOTES, ANN, CLAIM, MEMBER = "doc:annual_report", "doc:concall", "doc:deck", "doc:results_notes", "ann", "claim", "member"
SEG, SEGF = "p3:company_segment_pnl", "fact:fin.segment_value"
OI, OBC, OB = "p3:order_intake", "p3:order_book_contract", "fact:fin.order_book"
NIM, GNPA, NNPA, CC, PCR = "p3:lender_metrics:nim_pct", "p3:lender_metrics:gnpa_pct", "p3:lender_metrics:nnpa_pct", "p3:lender_metrics:credit_cost_pct", "p3:lender_metrics:provision_coverage_pct"
BS, CF, MIX, PROJ, CAP, COST, RATING = "p3:balance_sheet_lines", "p3:cash_flow_lines", "p3:company_debt_mix", "p3:capex_project", "p3:company_capacity_utilisation", "p3:company_cost_structure", "p3:rating_action"
INSIDER, DEALS, ACTIONS, MEET = "ei:insider_trades_v2", "ei:bulk_block_deals", "ei:corporate_actions", "ei:board_meetings"

RULES = [
 ("MB0002#MS MB0041#MS MB0044#L MB0044#MS MB0045#MS MB0046#MS MB0047 MB0048 MB0049#MS MB0050#MS", [AR], "Quote the annual-report passage on change in control, with page"),
 ("MB0005#L MB0030#L MB0321#L MB0324#L MB0325#L MB0326#L MB0329#L MB0330#L MB0327", [CALL, CLAIM], "Quote the call passage"),
 ("MB0012 MB0141 MB0142 MB0143 MB0145 MB0146 MB0147 MB0148 MB0149 MB0150", ["none:securitisation_volume", NNPA, NOTES, CALL], "Rank securitised volume; show net NPA beside it"),
 ("MB0014#L MB0161#L MB0164#L MB0165#L MB0169#L", [C, IDX], "Stock return minus Nifty 50 return over the window"),
 ("MB0163#L", [C, IDX, SER], "Stock return beside Nifty 50 and USDINR over the window"),
 ("MB0162#L MB0166#L MB0170#L", [C, D, IDX], "Window return; delivery per session; list missing sessions"),
 ("MB0167", [C, IDX, ANN, CLAIM], "Window return against index, with filings in the window"),
 ("MB0020 MB0223 MB0229", [POL, CLAIM, CALL, DECK], "Policy passage plus what each company said, by known_at"),
 ("MB0023#L", [DECK], "Count facilities from the named deck, with page"),
 ("MB0032#L MB0037 MB0040#L", [AR, C], "Business passage, plus traded close on the date"),
 ("MB0053#L MB0053#MS MB0055#L MB0083#L MB0087", [AR, SEG, SEGF], "Business passage; segment revenue for the quarter"),
 ("MB0067 MB0068 MB0942#L", [C, SO, BOOK], "P/B = close x shares / book equity; show inputs"),
 ("MB0078 MB0364", [CLAIM, CALL], "Demand and margin statements from the latest call"),
 ("MB0096#L", [NNPA, NOTES], "Net NPA % from the named disclosure"),
 ("MB0104#L MB0107 MB0108", [C, "none:adjusted_close_series"], "CAGR over 3 years on the split- and bonus-adjusted close"),
 ("MB0112#L", [NOTES], "Quote segment and geography notes"),
 ("MB0127 MB0130#L MB0247 MB0248 MB0250#L MB0578", [HOLD], "Holding at the quarter end; name the filing"),
 ("MB0276#L MB0277 MB0278", [HOLD, SO], "Exact share count from filings, promoter holding"),
 ("MB0187 MB0207", [POL, CLAIM], "Policy passage, plus what each company said"),
 ("MB0218 MB0606 MB0602", [CLAIM, CALL, AR], "Exposure in the company's own words"),
 ("MB0231#L MB0232#L MB0237 MB0238", [D], "Delivered quantity NSE plus BSE per day"),
 ("MB0267 MB0268 MB0270#L", [DECK], "Products and acquisitions from the deck, with page"),
 ("MB0285#L MB0290#L", [DECK], "Quote the named page of the named deck"),
 ("MB0287 MB0288", [DECK, CAP], "Capacity slides from the latest deck"),
 ("MB0293#L MB0295#L MB0297 MB0298", [CALL, PROJ], "Capacity timeline from the call, with capex"),
 ("MB0028#L MB0301#L MB0307 MB0308", [H], "Highest high in the window, with date and exchange"),
 ("MB0312#L MB0316#L MB0317 MB0318", [DECK, CALL, AR, PROJ], "Commissioned facilities, by document type"),
 ("MB0337#L", [CALL, PROJ, CAP], "Compare stated targets across calls, by date"),
 ("MB0345#L", [CAP, CALL, DECK], "Renewable capacity, mix and stated cost effect"),
 ("MB0355#L", [ANN, CALL], "Shutdown disclosure and stated recovery date"),
 ("MB0371 MB0882", [OI, OB, REV], "Cover = order book / trailing revenue; show inputs"),
 ("MB0372", [CLAIM, MIX, DEBT], "Stated net-debt reduction against held debt"),
 ("MB0377#L MB0379#L MB0387", [NOTES, "none:audit_opinion"], "Auditor opinion field from the results filing"),
 ("MB0382#L MB0393#L", [ANN], "Read the named filing; give parties and dates"),
 ("MB0383 MB0384 MB0385#L", [AR, NOTES], "Audit passages from the report"),
 ("MB0402 MB0420", [INSIDER, ANN], "Insider trades by person and quarter"),
 ("MB0403#L MB0599#L", [DEALS, C], "Deal party, side and price; first session's reaction"),
 ("MB0407 MB0418", [AR, NOTES, "none:related_party_lines"], "Related-party lines, year on year"),
 ("MB0414 MB0415", [ANN, CALL, AR], "Search disclosures for the event; quote the effect"),
 ("MB0424 MB0581", [C, TV], "Return or turnover on the date, ranked, with the floor stated"),
 ("MB0430#L", [C, IDX], "Stock move against Nifty 50 on the date"),
 ("MB0437#L MB0439#L MB0590#MS MB0591#L MB0596#L MB0600 MB0894", [C, ANN], "Day 0 from known_at; move on the first session that can react, against own volatility"),
 ("MB0814#L MB0815#L MB0816#L MB0820#L MB0829#L", [C, V, D, ANN, CALL], "Day 0 from known_at; the 4 sessions before it"),
 ("MB0440", [C, ANN, CLAIM], "Move on the date, filings that day"),
 ("MB0441#L", [V, D], "Volume and delivery on the date"),
 ("MB0443#L", [C, IDX, MEMBER], "Stock move against its sector index; share explained"),
 ("MB0453 MB0461 MB0464 MB0514 MB0854 MB0635 MB0650 MB0703 MB0773 MB0771 MB0692 MB0695", [COM, CLAIM, COST, AR], "Input share of cost x commodity move; contract terms as stated"),
 ("MB0458#L", [COM, CLAIM, COST], "Coal series to Dec 2025; 2026 cost from filings only"),
 ("MB0460 MB0605", [COM, CLAIM, DECK], "Gold move against stated gold-loan or inventory exposure"),
 ("MB0469#L MB0470#L MB0472#L MB0473#L MB0476 MB0477#L MB0479#L MB0984#L MB0985#L MB0753 MB0754 MB0772 MB0778 MB0672 MB0677 MB0678 MB0719 MB0729 MB0790 MB0881 MB0935", [POL, NIM, CC, MIX, CLAIM], "Repo path against NIM, credit cost and borrowing mix per quarter; lag computed"),
 ("MB0491#L", [DECK, CLAIM], "Ticket size and loan-to-value as disclosed"),
 ("MB0494 MB0859 MB0610 MB0869 MB0508 MB0511 MB0512 MB0524 MB0608 MB0612 MB0853 MB0860 MB0883 MB0519 MB0516#L", [CLAIM, AR, DECK, SEG], "Disclosed exposure by theme; say where it is not measurable"),
 ("MB0532#MS MB0533#MS MB0541#MS MB0542#MS MB0545#MS MB0546#MS MB0547#MS MB0548#MS MB0551#MS MB0553#MS MB0544#MS MB0930#MS", [OI, OB, REV, CALL], "Order book, intake and cover per quarter; compare with billing"),
 ("MB0543#MS MB0550#MS", [OBC, CALL, DECK], "Order book split by segment or contract type, as disclosed"),
 ("MB0917#MS", [OI, HOLD, C], "Returns against order announcements and institutional holding"),
 ("MB0556", [ANN, "none:qip_use_of_proceeds"], "QIP filing; stated objects against use"),
 ("MB0557#L MB0559#L MB0564#L MB0567#L MB0972#L MB0994#L MB0997#L", [CF, BS, MIX, PROJ, DEBT, EBITDA, CLAIM], "Net debt = debt - cash; net debt / EBITDA; funding from the cash flow"),
 ("MB0560 MB0879 MB0739 MB0736", [BS, CF, RCV, DEBT, RATING], "Working capital, leverage and rating; return on capital computed"),
 ("MB0569#L MB0962#L MB0770 MB0731 MB0704 MB0737 MB0748", [SO, EPS, ACTIONS, ANN], "Shares before and after; EPS and value per share"),
 ("MB0571 MB0584 MB0833 MB0837 MB1070#L MB1073#L MB1073#MS MB0583 MB1032#L", [DP, C, V], "Delivery % against own average, and price after"),
 ("MB0580", [MEMBER, C], "Move around an index membership change"),
 ("MB0657 MB0659 MB0666 MB0667 MB0668 MB0686 MB0711 MB0676 MB0734 MB0750 MB0783", [POL, SER, CLAIM, AR, BS], "Trace each hop to a held table; name the hop with no data"),
 ("MB0841#L MB0844#L MB0845 MB1013#L", [ACTIONS, C], "Dividend and ex-date; how it traded into it"),
 ("MB0856#L MB0858 MB1024#L MB1027#L MB1031#MS MB1034#L MB1035#L MB1038#MS MB1044#L MB1048 MB1049#L MB1050#L MB1051#L MB1053#L MB1054#L MB1025#L MB0876#L", [C, H, L, O, V, SMA], "Computed from the daily series; define the pattern and show each session"),
 ("MB0871#L", [MEET, ANN], "Board-meeting intimation and results date"),
 ("MB0897#MS MB0898#L", [ANN, "none:regulation_text"], "Filing times against the rule's stated clock"),
 ("MB0906#L MB0863#L", [C, IDX, ANN, HOLD], "Move against index; filings or holding change"),
 ("MB0914#L", [C, FLOW], "Worst FII month; stock move in it"),
 ("MB0927#MS", [PLEDGE, DEBT], "Pledge % and debt, by period"),
 ("MB0928", [HOLD, C], "Largest fall in promoter stake; price after"),
 ("MB0931#L", [NIM, C, CALL], "Quarter's margin against guidance; one-offs named"),
 ("MB0933#L", [SEG, C, CALL], "Segment that drove the quarter, against the reaction"),
 ("MB0943#L MB0954#L MB0961#L MB0991#L", [PAT, EBITDA, BOOK, CAPEX, REV, SEG], "Profit, return on capital and reinvestment rate computed; show inputs"),
 ("MB0968#L", [GNPA, PCR], "Provision coverage and stressed book, by quarter"),
 ("MB1006#L MB1007#L", [AR, BS, "none:listed_stake_values"], "Stakes held from the report, at market price"),
 ("MB1012#L", [ACTIONS, CF, PAT], "Payout = dividends / profit; compare with capex"),
 ("MB1017#L", [REV, RCV], "Quarterly revenue and receivables, by season"),
 ("MB1019#L", [CLAIM, AR], "Filing evidence that would break the thesis; not a verdict"),
]
