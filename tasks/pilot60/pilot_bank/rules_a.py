"""Rules for MB0001-MB0330, written by Claude. Each template family runs: 3 plain, terse, Hinglish, shifted, industry, index, as-of, trap."""
from build import K, M, S, X


def fam(n, plain, terse, hing, shift, ind, idx, pit, trap, ev=None, t="CDAN", fit=None, ind_fit=None, code="nifty500", pit_as_of="2026-06-30", shift_as_of=None):
    m = lambda i: f"{n + i:04d}"
    for i in range(3):
        S(m(i), plain, ev, t, fit)
    S(m(3), terse, ev, t, fit)
    S(m(4), hing, ev, t, fit)
    S(m(5), shift, ev, t, fit, as_of=shift_as_of)
    M(m(6), ind, ev, t if "X" in t else t + "X", ind_fit or fit)
    M(m(7), idx, ev, t if "X" in t else t + "X", fit, idx=code)
    S(m(8), pit, ev, t, fit, as_of=pit_as_of)
    S(m(9), trap, ev, t, fit)


# Shivam's own 20 test questions in short form
S("0001", "{sym} products + close on {prev_date}", None, fit=None)
S("0002", "{sym} latest AR: control change", '"change in control" OR "change of control" OR "change in ownership"', "A")
S("0003", "{sym} business + segments", '"reportable segment" OR "operating segment" OR "business segment"', "AN")
S("0004", "{sym} P/B now vs stored")
S("0005", "{sym} {ev_date} concall remark", "demand OR margin", "C")
S("0006", "{sym} segment revenue, latest quarter", '"segment revenue"', "NA")
S("0007", "{name} net NPA %", '"net npa" OR "net stage" OR nnpa', "CDAN", "lender")
S("0008", "{sym} 3-yr price CAGR{?has3y}")
S("0009", "{sym} Note 5 of {note5_q} results + geo split", 'geographical OR geographic', "NA")
S("0010", "{sym} public shareholding Sep 2026{?shp}")
M("0011", "Why gold stocks fell Jun-Jul 2026: {cohort}", "gold", "CDX", "jewel", min_n=1)
M("0012", "Securitisation leader QoQ/YoY with NPA guard: {cohort}", 'securitisation OR securitised OR "direct assignment"', "CDAN", "lender")
S("0013", "HPCL: Q4FY26 profit then Q1FY27; earliest PIT signal", None, fit="HINDPETRO")
S("0014", "{sym} move 10-18 Sep 2026 + vs Nifty")
S("0015", "{sym}: customs duty hit, then return vs Nifty", '"customs duty" OR "import duty" OR tariff', "CDA", "export")
K("0016", "RBI repo hike 7 Oct 2026 causes; PIB or RBI only", pol="repo", as_of="2026-10-19")
M("0017", "Electronics demand CY2026: who benefits among {cohort}", "electronics", "CDAX", "elec")
K("0018", "Coal gasification policy vs the earlier scheme", pol="gasification")
M("0019", "{cohort} on El Nino and monsoon risk", '"el nino" OR monsoon', "CDA", "fmcg sugar fertagri")
M("0020", "Tax holiday and data centres so far: {cohort}", '"data centre" OR "data center"', "CDA")

for i, (a, b) in enumerate([
    ("What was {name}'s delivered quantity (not total traded quantity) on {d1_date} and {d2_date}, NSE and BSE, with the combined total per day?", None),
    ("What is {name}'s promoter holding as of September 2026{?shp}?", None),
    ("How many manufacturing facilities does {name} report in its investor presentation of {ev_date}?", '"manufacturing facilities" OR "manufacturing plants" OR "manufacturing units"'),
    ("What are the key products of {name} per its investor presentation of {ev_date}, and whom did it mention as acquired?", "acquired OR acquisition"),
    ("How many equity shares does {name} have, and what is the promoter holding, as of the latest data{?shp}?", None),
    ("What did {name} show on page {ev_page} of its {ev_doc} dated {ev_date} about capacity?", 'capacity'),
    ("What did {name} say about capacity expansion on its {ev_date} earnings call?", '"capacity expansion"'),
    ("What was the YTD high price of {name} in 2026 (value and date) up to {last_date}?", None),
    ("What did {name} say about newly commissioned facilities, as of the latest data?", 'commissioned'),
    ("Per the {ev_date} earnings call of {name}: what did it say about an MoU, and how will EBITDA margins progress?", 'MoU OR "memorandum of understanding"'),
]):
    t = {2: "D", 3: "D", 5: "D", 6: "C", 8: "CDA", 9: "C"}.get(i, "CDAN")
    S(f"{21 + i:04d}", a, b, t)

fam(31, "What does {name} make per its annual report, and what was its close on {prev_date}?",
    "{sym} products + close {prev_date}", "Bhai, {name} kya banati hai, aur {prev_date} ko kitne pe close hui? Short mein batao.",
    "What does {name} make, and what was its close on {d1_date}?",
    "Among the pilot stocks {cohort}, list what each makes and its close on 16 October 2026.",
    "For the pilot stocks in the NIFTY TOTAL MARKET ({cohort}), list what each makes and its close on 16 October 2026.",
    "As of 30 June 2026, what did {name}'s latest annual report say it makes, and what was its close that day?",
    "What does {name} make, and what was its close on {prev_date}? Give the document and price source.",
    '"business overview" OR "our business" OR products', "A", code="niftytotalmarket", ind_fit="capgood")
C = '"change in control" OR "change of control" OR "change in ownership" OR "change in promoter"'
fam(41, "What did {name}'s latest annual report ({ar_fy}) disclose about a change in ownership or control, and where in the report?",
    "{sym} latest annual report control change", "{name} ke latest annual report mein ownership ya control change ke baare mein kya likha hai? Kaunsa page?",
    "What did {name}'s {ar_fy} annual report disclose about a change in ownership or control, and where?",
    "Among the pilot stocks {cohort}, which disclosed a change in control or ownership in the latest annual report, and what changed?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), which disclosed a change in control or ownership in the latest annual report?",
    "As of 30 June 2026, what did {name}'s latest filed annual report say about a change in control or ownership?",
    "What did {name}'s latest annual report disclose about a change in control, on which page?", C, "A", ind_fit="power realty capgood")
SG = '"segment revenue" OR "reportable segment" OR "segment reporting"'
fam(51, "What is {name}'s business, and what segments and segment revenue did it report for {res_q}?",
    "{sym} business segments {res_q}", "{name} ka business kya hai aur segments kaunse hain? Latest results ke hisaab se segment revenue bhi batao.",
    "What did {name}'s {res_q} results disclose about its business and segments?",
    "Among the pilot stocks {cohort}, what are the reported segments and latest segment revenue?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what are the reported segments and latest segment revenue?",
    "As of 30 June 2026, what did {name}'s latest results and annual report disclose about its business and segments?",
    "For {name}, what are its business segments and segment revenue for {res_q}, and which filing carries them?", SG, "NA")
fam(61, "What is {name}'s P/B on the {last_date} close, and how does it compare with the stored ratio? State the price date and the book-value date.",
    "{sym} pb ratio stored vs computed", "{name} ka P/B ratio kitna hai? Stored ratio aur {last_date} ke close se nikaala hua ratio dono batao, aur farq kyun hai.",
    "What was {name}'s P/B on the {prev_date} close compared with the stored ratio?",
    "Among the pilot stocks {cohort}, rank by P/B computed from the close on 19 October 2026 and the latest annual-report book value.",
    "For the pilot stocks in the NIFTY 500 ({cohort}), rank by P/B computed from the close on 19 October 2026 and the latest annual-report book value.",
    "As of 31 March 2026, what was {name}'s P/B using the price and book value known by that date?",
    "What is {name}'s P/B now, and which book-value filing does it use?", '"net worth" OR "total equity"', "AN", pit_as_of="2026-03-31")
DM = 'demand AND margin'
fam(71, "What did {name}'s management say about demand and margins on its {ev_date} earnings call, and who said it?",
    "{sym} call {ev_date} management outlook", "{name} ki {ev_date} wali earnings call mein management ne demand aur margin ke baare mein kya kaha? Speaker aur quote batao.",
    "What did {name}'s management say about demand and margins on its {ev_date} call?",
    "Among the pilot stocks {cohort}, what did management say about demand and margins on their latest calls, with quoted evidence?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what did management say about demand and margins on their latest calls?",
    "As of 31 July 2026, what had {name}'s management last said on an earnings call about demand and margins?",
    "What did {name} say about demand and margins on its {ev_date} call? Quote the passage.", DM, "C", pit_as_of="2026-07-31")
fam(81, "What was {name}'s segment revenue for {res_q}, with the absolute number for each reported segment?",
    "{sym} segment revenue {res_q}", "{name} ka {res_q} segment revenue kitna tha, segment-wise absolute numbers ke saath? Source bhi do.",
    "What was {name}'s segment revenue for {res_q}, per the results filed on {res_date}?",
    "Among the pilot stocks {cohort}, rank by reported segment revenue for Q1FY27.",
    "For the pilot stocks in the NIFTY MIDCAP 150 ({cohort}), rank by reported segment revenue for Q1FY27.",
    "As of 30 June 2026, what segment revenue had {name} last reported?",
    "What was {name}'s segment revenue for {res_q}, and which filing carries it?", '"segment revenue"', "NA", code="niftymidcap150")
NP = '"net npa" OR nnpa OR "net stage" OR "net non-performing"'
fam(91, "What was {name}'s net NPA (or net stage 3) % in its latest disclosure, and which filing carries it?",
    "{sym} net npa latest", "{name} ka net NPA percentage latest filing mein kitna tha? Gross aur net dono batao.",
    "What was {name}'s net NPA % in the disclosure of {ev_date}?",
    "Among the pilot lenders {cohort}, rank by net NPA % in the latest disclosure, with the source for each.",
    "For the pilot lenders in the NIFTY 500 ({cohort}), rank by net NPA % in the latest disclosure.",
    "As of 30 June 2026, what net NPA % had {name} last reported?",
    "What was {name}'s net NPA %, and in which document is it stated?", NP, "CDAN", "lender")
fam(101, "What was {name}'s 3-year price CAGR to 19 October 2026, using split- and dividend-adjusted closes? State both endpoint dates.{?has3y}",
    "{sym} 3y cagr adjusted", "{name} ka pichle 3 saal ka adjusted price CAGR kya raha? Start aur end date saaf likho.",
    "What was {name}'s 3-year adjusted price CAGR to 30 September 2026? State both endpoint dates.{?has3y}",
    "Among the pilot stocks {cohort}, what was the 3-year adjusted price CAGR to 19 October 2026, ranked?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what was the 3-year adjusted price CAGR to 19 October 2026, ranked?",
    "As of 30 June 2026, what was {name}'s 3-year adjusted price CAGR?",
    "What was {name}'s 3-year adjusted price CAGR across its {ca_type} of {ca_date}?", None, code="nifty500")
fam(111, "Note 5 of {name}'s {note5_q} results: what does it say, and is a geographic revenue split disclosed?",
    "{sym} results note 5 geo split {note5_q}", "{name} ke {note5_q} results ki note 5 mein kya likha hai, aur geographic revenue split kya hai? Quote ke saath.",
    "Note 5 of {name}'s {note5_q} results: what does it say?",
    "Among the pilot stocks {cohort}, which disclose a geographic revenue split in their results or annual report, and what is it?",
    "For the pilot stocks in the NIFTY IPO ({cohort}), which disclose a geographic revenue split, and what is it?",
    "As of 30 June 2026, what did note 5 of {name}'s latest results say?",
    "What does note 5 of {name}'s {note5_q} results say? Quote it.", 'note OR geographical', "N", code="niftyipo")
fam(121, "What is {name}'s public shareholding as of September 2026{?shp}?",
    "{sym} public shareholding Sep 2026", "{name} mein public shareholding Sep 2026 tak kitni hai? Promoter aur public dono ka percentage filing se batao.",
    "What is {name}'s public shareholding as of 30 June 2026{?shp}?",
    "Among the pilot stocks {cohort}, rank by public shareholding as of Sep 2026.",
    "For the pilot stocks in the NIFTY MIDCAP 100 ({cohort}), rank by public shareholding as of Sep 2026.",
    "As of 30 June 2026, what was {name}'s public shareholding per the latest filing on or before that date?",
    "What is {name}'s public shareholding as of Sep 2026, and which filing carries it?", None, code="niftymidcap100")
for i, q in enumerate([
    "Why did {cohort} move in June-July 2026? Give the gold move, any PIB or RBI evidence, and what the companies said.",
    "Why did {cohort} move in April-May 2026? Give the crude move, any PIB or RBI evidence, and what the companies said.",
    "Why did {cohort} move in Jun-Jul 2026? Use the gold price series and name the source you rely on.",
    "{cohort} stocks move Jun-Jul 2026 why",
    "{cohort} Jun-Jul 2026 mein kya hua aur kyun? Evidence do, aur batao kaun sabse zyada affected hua.",
    "What caused the move in {cohort} in June-July 2026? Use the commodity series and company evidence from that window only.",
    "For {cohort}, what moved in Jun-Jul 2026, and what do the macro and company evidence say caused it?",
    "How did the gold price move in Jun-Jul 2026 hit {cohort} differently, and which one was worst?",
    "By 31 July 2026, why had {cohort} moved? Use only evidence known by that date.",
    "Why did {cohort} move in 7-19 Oct 2026? Name the series used.",
]):
    M(f"{131 + i:04d}", q, "gold OR crude" if i == 1 else "gold", "CDAN", "oil" if i == 1 else "jewel", as_of="2026-07-31" if i == 8 else None, min_n=1)
SEC = 'securitisation OR securitised OR "direct assignment" OR "co-lending"'
for i, q in enumerate([
    "Among {cohort}, who disclosed the most securitisation or direct-assignment activity, with net NPA shown beside it? Show the comparison.",
    "Among {cohort}, who leads securitised lending in the latest disclosure, and what is its net NPA?",
    "For {cohort}, what securitisation or co-lending is disclosed, with net NPA beside it?",
    "securitisation co-lending {cohort} net npa",
    "{cohort} mein securitisation ya co-lending ka leader kaun hai? Net NPA ke saath batao.",
    "Among {cohort}, what securitisation was disclosed in January-March 2026, and how did net NPA move?",
    "Among {cohort}, which is the securitisation leader with a net-NPA guard, and what is the evidence?",
    "For {cohort}, rank by securitised lending disclosed, with the net-NPA guard.",
    "As of 30 June 2026, which of {cohort} looked like the securitisation leader, and on what evidence?",
    "Which of {cohort} led securitised lending, and in which filing is the figure stated?",
]):
    M(f"{141 + i:04d}", q, SEC, "CDAN", "lender", as_of="2026-06-30" if i == 8 else None)
for i, (q, kind) in enumerate([
    ("Among {cohort}, which swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time?", "M"),
    ("Among {cohort}, which swung from profit in Q4FY26 to a loss in Q1FY27, and when was that first visible point-in-time?", "M"),
    ("For HPCL, how did profit move from Q4FY26 to Q1FY27, when was it visible point-in-time, and from which filing?", "S"),
    ("HPCL q4fy26 profit q1fy27 profit earliest pit", "S"),
    ("HPCL ka Q4FY26 aur Q1FY27 ka profit kya tha? Sabse pehle kaunsa data point visible tha, date ke saath batao.", "S"),
    ("For the January-March 2026 and April-June 2026 quarters, how did HPCL's profit move, and when did that first become visible?", "S"),
    ("Among {cohort}, which swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest point-in-time evidence?", "M"),
    ("Among {cohort}, which swung from profit in Q4FY26 to a loss in Q1FY27, and what was the earliest evidence?", "M"),
    ("As of 30 June 2026, what did the data already show about HPCL's profit in Q4FY26 and the crude move in the quarter?", "S"),
    ("Using the crude price series, when did HPCL's Q4FY26-to-Q1FY27 profit trend first become visible?", "S"),
]):
    mid = f"{151 + i:04d}"
    if kind == "M":
        M(mid, q, None, fit={0: "chem", 1: "media fmcg", 6: "oil", 7: "oil"}[i], min_n=1)
    else:
        S(mid, q, fit="HINDPETRO", as_of="2026-07-31" if i == 8 else None)
for i, q in enumerate([
    "For {name}, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, against the Nifty 50 over the same windows?",
    "For {name}, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, and how did delivery behave?",
    "For {name}, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026 against the Nifty 50 and the rupee?",
    "{sym} move Sep 2026 vs nifty",
    "{name} 10-18 September 2026 ke beech kitna chala aur 18-28 September mein kitna? Nifty 50 ke saath batao.",
    "For {name}, explain the September 2026 move using the Nifty 50, and give the session-by-session delivery.",
]):
    S(f"{161 + i:04d}", q)
M("0167", "For {cohort}, what explains the move in 10-18 Sep 2026 and 18-28 Sep 2026?", None, fit="HINDALCO KALYANKJIL HINDPETRO")
M("0168", "Among {cohort}, which moved most in 10-18 Sep 2026 and 18-28 Sep 2026, against gold over the same windows?", None, fit="jewel", min_n=1)
S("0169", "As of 17 September 2026, what was {name}'s move since 10 September 2026, and what was the Nifty 50's?", as_of="2026-09-17")
S("0170", "For {name}, what was the move in 10-18 Sep 2026 and 18-28 Sep 2026, and on which sessions is a delivery row missing?")
TAR = '"customs duty" OR "import duty" OR "basic customs" OR tariff'
TQ = "How did {name} trade in the 60 sessions after the 1 February 2025 Budget's customs changes against the Nifty 50, and what did it say about customs duty or tariffs?"
for i in range(3):
    S(f"{171 + i:04d}", TQ, TAR, "CDA", "export import")
S("0174", "{sym} customs duty sensitivity, 60 sessions from Feb 2025", TAR, "CDA", "export import")
S("0175", "{name} par 1 February 2025 ke customs changes ka kitna asar pada, aur company ne customs duty ya tariff par kya kaha?", TAR, "CDA", "export import")
S("0176", "How did {name}'s return against the Nifty 50 change over the 12 months after March 2025, and what did it say about tariffs?", TAR, "CDA", "export import")
M("0177", "Among {cohort}, how did each trade in the 60 sessions after the 1 February 2025 customs changes, and what did each say about them?", TAR, "CDA", "export import")
M("0178", "For the pilot stocks in the NIFTY 500 ({cohort}), how did each trade in the 60 sessions after the 1 February 2025 customs changes?", TAR, "CDA", "export import", idx="nifty500")
S("0179", "As of 31 March 2026, how had {name} traded since the 1 February 2025 customs changes, and what had it said about tariffs?", TAR, "CDA", "export import", as_of="2026-03-31")
S("0180", "For {name}, what was the return from 1 February 2025 to {last_date} on adjusted prices across its {ca_type} of {ca_date}?")
K("0181", "For the repo rate hike of 25 bps to 5.50% on 2026-10-07, what were the causes, and which source published it first?", pol="repo")
K("0182", "For the increase in devolution of states' share in taxes (2026-02-01), what were the causes, and which source published it first?", pol="Devolution")
K("0183", "What did the RBI Governor's Statement of 7 October 2026 give as the causes, and which source published it first?", pol="repo")
K("0184", "rbi repo hike 2026-10-07 causes pib or rbi", pol="repo")
K("0185", "RBI ne 2026-10-07 ko repo rate kyun badhaya? Causes batao, aur ye PIB ne publish kiya ya sirf RBI ne?", pol="repo")
K("0186", "For the repo hike to 5.50% of 2026-10-07, what were the causes, and was it published by PIB or only by the RBI?", pol="repo")
M("0187", "For {cohort}, how does the 2026-10-07 RBI action transmit, and which sectors are named in the policy document?", None, fit="lender", pol="repo")
M("0188", "For the pilot stocks in the NIFTY TOTAL MARKET ({cohort}), how did each react to the RBI action of 2026-10-07?", None, idx="niftytotalmarket", pol="repo")
K("0189", "As of 19 October 2026, what did the record show about the causes of the RBI action of 2026-10-07, and who published it first?", pol="repo")
K("0190", "What were the causes of the RBI action of 2026-10-07, and was it published by PIB or only by RBI? Name the document.", pol="repo")
EL = "electronics"
M("0191", "For the Electronics Component Manufacturing Scheme approvals (2025-11-17), why does it matter for demand, and what do {cohort} say?", EL, "CDA", "elec", pol="Electronics")
M("0192", "For the R&D in IT/Electronics measures (2026-02-01), why does it matter for demand, and what do {cohort} say?", EL, "CDA", "elec it", pol="Electronics")
M("0193", "Using the policy record on electronics, what does it say about demand in CY2026, and what do {cohort} say?", EL, "CDA", "elec", pol="Electronics")
M("0194", "electronics demand cy2026 who benefits: {cohort}", EL, "CDA", "elec")
M("0195", "CY2026 mein electronics demand ke baare mein {cohort} ne kya kaha? Structural hai ya cyclical?", EL, "CDA", "elec")
M("0196", "What do {cohort} say about electronics demand in CY2026, and is the trend structural or cyclical in their words?", EL, "CDA", "elec")
M("0197", "For {cohort}, what does the policy record say about electronics demand in CY2026?", EL, "CDA", "elec", pol="Electronics")
M("0198", "For the pilot stocks in the NIFTY 500 ({cohort}), what does company evidence say about electronics demand in CY2026?", EL, "CDA", "elec", idx="nifty500")
M("0199", "As of 30 June 2026, what was known about the electronics demand trend from {cohort}?", EL, "CDA", "elec", as_of="2026-06-30")
M("0200", "What do the held documents of {cohort} say about electronics demand in CY2026, with the document for each?", EL, "CDA", "elec")
GAS = "gasification"
K("0201", "For the coal/lignite gasification scheme (2026-02-01), how does it differ from the earlier scheme, and which industries does it hit?", pol=GAS)
K("0202", "How does the National Green Hydrogen Mission progress note (2025-12-16) differ from the coal-gasification scheme, and which industries does it hit?", pol="Hydrogen")
K("0203", "Using Budget FY2026-27, how does the coal-gasification policy differ from the earlier scheme, and which industries does it hit?", pol=GAS)
K("0204", "coal gasification policy vs earlier scheme", pol=GAS)
K("0205", "Coal gasification ke naye policy aur pehle wale scheme mein kya farq hai? Kaunsi industries affected hain, aur PIB/Budget se evidence do.", pol=GAS)
K("0206", "How do India's coal-gasification policy steps differ from the earlier scheme, and which industries do they hit?", pol=GAS)
M("0207", "For {cohort}, how does the coal-gasification policy differ from the earlier scheme, and what have they said on coal?", "coal", "CDA", "power", pol=GAS)
M("0208", "For the pilot stocks in the NIFTY 500 ({cohort}), what does the coal-gasification policy mean, and is any named in policy_events?", "coal", "CDA", "power metal", pol=GAS, idx="nifty500")
K("0209", "As of 31 December 2025, what did the coal-gasification record say? Use only documents known by that date.", pol=GAS, as_of="2025-12-31")
M("0210", "How does the coal-gasification policy change affect {cohort}, and what does the held coal series show?", "coal", "CDA", "power", pol=GAS)
NINO = '"el nino" OR monsoon'
for i, q in enumerate([
    "What did {name} say about El Nino or the monsoon in its documents, and how did it say it would handle the risk?",
    "What did {name} say about El Nino or the monsoon on its calls and in its reports?",
    "What did {name} say about El Nino or monsoon risk, and in which document?",
    "{sym} el nino monsoon margins",
    "{name} ne El Nino ya monsoon ke asar par kya kaha? Management ne kaise handle karne ko kaha?",
    "What did {name} say about monsoon risk, and how does it affect margins in its words?",
]):
    S(f"{211 + i:04d}", q, NINO, "CDA")
M("0217", "For {cohort}, what did managements say about El Nino or monsoon, and how are they handling it?", NINO, "CDA", "fmcg sugar fertagri chem")
M("0218", "For the pilot stocks in the NIFTY 500 ({cohort}), how exposed are they to El Nino or monsoon, in their own words?", NINO, "CDA", idx="nifty500")
S("0219", "As of 30 June 2026, what had {name} said about El Nino or monsoon risk?", NINO, "CDA", as_of="2026-06-30")
S("0220", "What did {name} say about El Nino or monsoon on {ev_date}, in its {ev_doc}?", NINO, "CDA")
DC = '"data centre" OR "data center" OR "data centres" OR "data centers"'
K("0221", "For the startup tax holiday extension (2025-02-01), what does the policy record state?", pol="tax holiday")
X("0222", "A 2022 housing tax holiday: no pilot company evidence on it, and it is outside the company data window")
M("0223", "How has the data-centre tax holiday played out so far, and what do {cohort} say on data centres?", DC, "CDA", pol="data cent")
M("0224", "data centre tax holiday outcome 2025-2026: {cohort}", DC, "CDA", pol="data cent")
M("0225", "Data-centre tax holiday ka kya outcome raha? Policy record aur {cohort} ke comments se evidence do.", DC, "CDA", pol="data cent")
M("0226", "How has the data-centre tax holiday played out so far, and what do {cohort} say?", DC, "CDA", pol="data cent")
M("0227", "For {cohort}, how has the tax holiday played out, and what do the companies and policy documents say?", DC, "CDA", pol="data cent")
M("0228", "For the pilot stocks in the NIFTY 500 ({cohort}), what has the data-centre tax holiday meant so far?", DC, "CDA", idx="nifty500", pol="data cent")
M("0229", "As of 1 February 2026, what had {cohort} said on data centres, using only evidence known by that date?", DC, "CDA", as_of="2026-02-01")
M("0230", "How has the data-centre tax holiday played out so far for {cohort}? Name the policy document.", DC, "CDA", pol="data cent")
fam(231, "What was {name}'s delivered quantity (not total traded quantity) on {d1_date} and {d2_date}, NSE and BSE, with the combined total per day?",
    "{sym} delivery {d1_date} and {d2_date} nse bse", "{name} ka delivered quantity {d1_date} aur {d2_date} ko kitna tha? NSE, BSE aur dono ka total alag-alag batao.",
    "What was {name}'s delivered quantity on {prev_date} and {last_date}, NSE and BSE, with the combined total per day?",
    "Among the pilot stocks {cohort}, what was the delivered quantity on NSE and BSE on 15 and 16 September 2026, ranked?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what was the delivered quantity on NSE and BSE on 14 and 15 July 2026, ranked?",
    "As of 30 June 2026, what delivered quantity had {name} recorded on its last two sessions on NSE and BSE?",
    "What was {name}'s delivered quantity on {d1_date} and {d2_date} on NSE and BSE? Say if one exchange has no row.", None)
fam(241, "What is {name}'s promoter holding as of Sep 2026, per the latest filing{?shp}?",
    "{sym} promoter holding Sep 2026", "{name} mein promoter ki holding Sep 2026 tak kitni hai? Latest shareholding filing se number aur date batao.",
    "What is {name}'s promoter holding as of 30 June 2026, per the filing{?shp}?",
    "Among the pilot stocks {cohort}, what is the promoter holding as of Sep 2026, ranked from highest to lowest?",
    "For the pilot stocks in the NIFTY MIDSMALLCAP 400 ({cohort}), what is the promoter holding as of Sep 2026, ranked?",
    "As of 30 June 2026, what was {name}'s promoter holding per the latest shareholding filing on or before that date?",
    "What is {name}'s promoter holding as of Sep 2026, and which filing carries it?", None, code="niftymidsmallcap400")
FAC = '"manufacturing facilities" OR "manufacturing plants" OR "manufacturing units" OR "manufacturing locations"'
fam(251, "How many manufacturing facilities does {name} report in its investor presentation dated {ev_date}, and where are they?",
    "{sym} facilities deck {ev_date}", "{name} ke {ev_date} wale investor presentation ke hisaab se kitni manufacturing facilities hain, aur kahan? Slide ka reference bhi do.",
    "How many manufacturing facilities does {name} report in its presentation of {ev_date}?",
    "Among the pilot stocks {cohort}, how many manufacturing facilities does each report in its latest presentation?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), how many manufacturing facilities does each report in its latest presentation?",
    "As of 31 July 2026, how many manufacturing facilities did {name} report in its latest deck filed by that date?",
    "How many manufacturing facilities does {name} report in its presentation dated {ev_date}, on which slide?", FAC, "D", pit_as_of="2026-07-31")
ACQ = "acquired OR acquisition OR acquire"
fam(261, "Per {name}'s deck of {ev_date}, what are its key products, and which company did it mention as acquired?",
    "{sym} products acquisitions deck {ev_date}", "{name} ke {ev_date} wale deck mein main products kya hain, aur kis company ke acquisition ka mention hai?",
    "Per {name}'s deck of {ev_date}, what are its key products and acquisitions?",
    "Among the pilot stocks {cohort}, what products and acquisitions does each report in its latest presentation?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what products and acquisitions does each report in its latest presentation?",
    "As of 30 June 2026, what did {name}'s latest deck disclose about its products and acquisitions?",
    "What are {name}'s key products and latest acquisition, per its deck of {ev_date}?", ACQ, "D")
fam(271, "How many equity shares does {name} have, and what is its promoter holding, as of the latest data{?shp}? Say which filing each number comes from.",
    "{sym} share count promoter holding", "{name} ke kitne equity shares hain aur promoter holding kitni hai? Dono numbers latest filing se, date ke saath batao.",
    "How many equity shares did {name} have, and what was its promoter holding, at 30 June 2026?",
    "Among the pilot stocks {cohort}, give the latest exact share count and promoter holding for each, with the filing date.",
    "For the pilot stocks in the NIFTY LARGEMIDCAP 250 ({cohort}), give the latest exact share count and promoter holding for each, with the filing date.",
    "As of 30 June 2026, what were {name}'s exact share count and promoter holding?",
    "What are {name}'s exact share count and promoter holding now, after its {ca_type} of {ca_date}?", None, code="niftylargemidcap250")
CAP = 'capacity OR licence OR license'
fam(281, "What does page {ev_page} of {name}'s investor presentation dated {ev_date} say about its manufacturing licence or capacity?",
    "{sym} deck page {ev_page} {ev_date}", "{name} ke {ev_date} wale investor presentation ke page {ev_page} par kya dikhaya gaya hai? Text ya quote ke saath batao.",
    "What does page {ev_page} of {name}'s presentation dated {ev_date} say about capacity?",
    "Among the pilot stocks {cohort}, what do the latest decks say on capacity or licensing slides?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what do the latest decks say on capacity or licensing slides?",
    "As of 30 September 2026, what did page {ev_page} of {name}'s latest deck filed by that date say?",
    "What does page {ev_page} of {name}'s presentation dated {ev_date} say? Quote it.", CAP, "D", pit_as_of="2026-09-30")
EXP = '"capacity expansion" OR "expand capacity" OR "capacity addition" OR "expansion of capacity"'
fam(291, "What did {name} say about its capacity expansion, and the completion timeline, on its {ev_date} earnings call?",
    "{sym} capacity timeline call {ev_date}", "{name} ne apni {ev_date} wali call mein capacity expansion ka kya timeline bataya? Completion date aur capex ke saath quote do.",
    "What did {name} say about capacity expansion on its {ev_date} call?",
    "Among the pilot stocks {cohort}, what capacity-expansion timelines did management give on their latest calls?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what capacity-expansion timelines did management give on their latest calls?",
    "As of 31 July 2026, what had {name} said about its capacity expansion timeline by that date?",
    "What did {name} say about its capacity expansion timeline on {ev_date}? Quote it.", EXP, "C", pit_as_of="2026-07-31")
fam(301, "What was {name}'s YTD high price in 2026 up to {last_date}, with the value and the date, and on which exchange?",
    "{sym} ytd high 2026", "{name} ka 2026 ka YTD high price kya tha, aur kis date ko? NSE ya BSE, exchange bhi batao.",
    "What was {name}'s YTD high price in 1 January-30 September 2026, with the value and the date, and on which exchange?",
    "Among the pilot stocks {cohort}, which made a new YTD high in 2026, with the value and date?",
    "For the pilot stocks in the NIFTY 200 ({cohort}), which made a new YTD high in 2026, with the value and date?",
    "As of 30 June 2026, what was {name}'s YTD high in 2026 up to that date, and on which day?",
    "What was {name}'s YTD high for 2026, raw and adjusted across its {ca_type} of {ca_date}?", None, code="nifty200")
COM = 'commissioned OR commissioning'
fam(311, "What did {name} say about its newly commissioned facilities, as of the latest data, and in which document type?",
    "{sym} newly commissioned facilities latest", "{name} ne apni nayi commissioned facilities ke baare mein sabse latest kya kaha hai? Deck, concall aur annual report check karke source do.",
    "What did {name} say about commissioned facilities in its {ev_doc} of {ev_date}?",
    "Among the pilot stocks {cohort}, what have the companies said about newly commissioned facilities across decks, calls and annual reports?",
    "For the pilot stocks in the NIFTY 500 ({cohort}), what have the companies said about newly commissioned facilities across decks, calls and annual reports?",
    "As of 30 June 2026, what had {name} said about its newly commissioned facilities, using only documents known by that date?",
    "What has {name} said about its newly commissioned facilities since January 2026? Name the document.", COM, "CDA")
MOU = 'MoU OR "memorandum of understanding"'
fam(321, "Per {name}'s {ev_date} earnings call, what did it say about its MoU with its partner, and how will EBITDA margins progress?",
    "{sym} mou margin path call {ev_date}", "{name} ki {ev_date} wali call mein MoU partner kaun hai, aur EBITDA margin ka path kya bataya gaya? Quote karo.",
    "Per {name}'s {ev_date} earnings call, what did it say about its MoU?",
    "Among the pilot stocks {cohort}, what MoUs or partnerships and margin paths did management disclose on their latest calls?",
    "For the pilot stocks in the NIFTY MIDCAP 150 ({cohort}), what MoUs or partnerships and margin paths did management disclose on their latest calls?",
    "As of 30 September 2026, what had {name} disclosed about its MoU and margin path?",
    "What did {name} say about its MoU and EBITDA margin path on {ev_date}? Quote it.", MOU, "C", code="niftymidcap150", pit_as_of="2026-09-30")
