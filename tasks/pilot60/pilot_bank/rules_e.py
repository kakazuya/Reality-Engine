"""Corrections after the first build and audit, written by Claude. Each replaces the earlier rule for that question."""
import build
from build import CH, K, M, S, X


def redo(*mids):
    for m in mids:
        mid = "MB" + m
        del build.RULES[mid]
        build.ORDER.remove(mid)


# results_notes has no numbered-note table, so note questions read the held results text
NOTE = '"note 5" OR "note no 5" OR "note no. 5"'
GEO = 'geographical OR geographic OR "geographical segment"'
redo("0009", "0111", "0112", "0113", "0114", "0115", "0116", "0117", "0118", "0119", "0120", "0098", "0207", "0210", "0347", "0405", "0406", "0513", "0684", "0741")
S("0009", "{sym} results of {ev_date}: geographic split", GEO, "NA")
for m in ("0111", "0112", "0113"):
    S(m, "{name}'s results filed {ev_date}: what do the notes say on segments, and is a geographic revenue split disclosed?", GEO, "NA")
S("0114", "{sym} results notes geo split {ev_date}", GEO, "NA")
S("0115", "{name} ke {ev_date} wale filing mein geographic revenue split kya hai? Consolidated basis, quote ke saath.", GEO, "NA")
S("0116", "{name}'s {ev_doc} of {ev_date}: what geographic revenue split does it disclose?", GEO, "NA")
M("0117", "Among {cohort}: which disclose a geographic revenue split in results or annual report, and what is it?", GEO, "NA")
M("0118", "For {cohort}, what geographic revenue split does each disclose?", GEO, "NA", "export")
S("0119", "As of 30 June 2026, what geographic split had {name} last disclosed?", GEO, "NA", as_of="2026-06-30")
S("0120", "What geographic split does {name}'s {ev_doc} of {ev_date} state? Quote it.", GEO, "NA")
M("0098", "Among the pilot lenders {cohort}, rank by net NPA % in the latest disclosure, with the source for each.", '"net npa" OR nnpa OR "net stage" OR "net non-performing"', "CDANX", "lender")
M("0207", "For {cohort}, how does the coal-gasification policy differ from the earlier scheme, and what have they said on coal?", "coal", "CDA", "power metal cement", pol="gasification")
M("0210", "How does the coal-gasification policy change affect {cohort}, and what does the held coal series show?", "coal", "CDA", "power metal cement", pol="gasification")
S("0347", "{name}'s operating margin moved in its latest quarter. When does management expect it to normalise, and on what?", 'margin AND (normalise OR normalize OR normalisation OR normalization)', "C")
X("0405", "No pilot stock has an auditor resignation citing a reason; nothing held can answer it")
M("0406", "Among {cohort}: what promoter pledge do filings or reports disclose, and has it risen or fallen?", 'pledge OR pledged OR encumbrance', "CAX")
M("0513", "Tax collected at source on coal and iron-ore sales doubles to 2% from 1 April 2026. Who among {cohort} is hit first, and does any gain?", 'coal OR "iron ore"', "CDA", "metal power", pol="TCS", min_n=1)
X("0684", "The one pilot sugar company has no current price or filing data")
X("0741", "No pilot stock has an index-exclusion event in its documents")

# Stock questions that ask for management's words need a document behind them, not only prices
redo("0905", "0907", "0930", "0931", "0932", "0933", "0912", "0910", "0909")
S("0905", "{name} moved {react_pct}% after {res_q}. Was the move in the numbers, the guidance, or the pre-result positioning?", "guidance", "CN")
S("0907", "{name} moved {react_pct}% after {res_q}. Did the market react to margins, guidance or the rupee?", "guidance AND margin", "CN")
S("0930", "{name}: did its order wins convert into revenue this quarter, or is the book growing faster than billing?", '"order book" OR "order inflow"', "CD")
S("0931", "{name} {res_q}: was any margin expansion real, or a one-off, and what did management guide?", 'margin AND guidance', "CDN")
S("0932", "{name}: did the quarter's growth come from mix or discounts, and what does that say about margin?", 'mix AND margin', "CDN")
S("0933", "{name}: which segment drove {res_q}, and did the market react to the consolidated or segment story?", '"segment revenue" OR "segment results"', "CDN")
S("0912", "How much has {name} moved over 12 months, and what did it report on margin in {res_q}?", "margin", "CDN")
S("0910", "What does {name} say has improved in the business over two years, and what is the price change?", 'improved OR improvement', "CD")
S("0909", "How far is {name} from its 52-week high, and what do revenue, margin and debt show over the last four quarters?", 'revenue AND margin AND debt', "CDN")

# Rescued after the reads: the documents do not explain these, but prices, the gold series or the policy record can answer a narrower question
GOLD = {
    "0011": "{cohort}: move in Jun-Jul 2026 against the gold series",
    "0131": "How did {cohort} move in June-July 2026, and how did the held gold series move over the same window?",
    "0133": "How did {cohort} move in Jun-Jul 2026 against the gold price series (USD/oz)? Name the series and dates used.",
    "0134": "{cohort} move Jun-Jul 2026 vs gold",
    "0135": "{cohort} Jun-Jul 2026 mein kitna chala, aur gold series usi window mein kitna chala?",
    "0136": "From the commodity series and closes in June-July 2026 only, how did {cohort} move against gold?",
    "0137": "For {cohort}, what was the move in Jun-Jul 2026, and what did gold do over the same window?",
    "0138": "How did {cohort} differ in Jun-Jul 2026 against the gold series, and which was worst?",
    "0139": "By 31 July 2026, how had {cohort} moved since 1 June 2026, and how had gold moved? Use only data known by that date.",
    "0140": "How did {cohort} move in 7-19 Oct 2026 against the gold series? Say if the series ends before the window.",
}
redo(*GOLD)
for m, q in GOLD.items():
    M(m, q, None, fit="jewel", min_n=1, as_of="2026-07-31" if m == "0139" else None)
POLICY = {
    "0191": ("What does the policy record state on the Electronics Component Manufacturing Scheme approvals of 2025-11-17: amounts, sectors and companies named?", "Electronics"),
    "0192": ("What does the policy record state on R&D in IT and electronics of 2026-02-01: amounts and sectors named?", "Electronics"),
    "0193": ("What does the policy record say on electronics, and which companies does it name?", "Electronics"),
    "0197": ("Which companies and sectors does the policy record name for electronics?", "Electronics"),
    "0198": ("Which pilot stocks does the policy record on electronics name, if any?", "Electronics"),
    "0199": ("As of 30 June 2026, what did the policy record state on electronics, and which companies were named?", "Electronics"),
    "0200": ("What does the policy record say on electronics, and is any sales series for refurbished goods held?", "Electronics"),
    "0208": ("Which companies are named in policy_events for coal gasification, and is any a pilot stock?", "gasification"),
    "0210": ("What does the policy record state on coal gasification, and how far does the held coal series run?", "gasification"),
    "0224": ("data centre tax holiday policy record 2025-2026", "data cent"),
    "0225": ("Data-centre tax holiday par policy record mein kya likha hai? Budget ya PIB ka evidence do.", "data cent"),
    "0226": ("What does the policy record state on the tax holiday for data-centre operations in India?", "data cent"),
    "0227": ("What do the policy documents say on the data-centre tax holiday, and which companies do they name?", "data cent"),
    "0228": ("Which pilot stocks does the policy record on the data-centre tax holiday name, if any?", "data cent"),
    "0230": ("What does policy_events hold on a data-centre tax holiday, with dates and source?", "data cent"),
    "0497": ("What does the policy record state on the US tariff on generic drugs: rate, start and source?", "generic"),
    "0498": ("The policy store has generic-drug tariff lines for 2028 and 2029. How do the two lines differ?", "generic"),
    "0500": ("What does the policy record state on the Samudra Manthan offshore-exploration scheme: amount, horizon and sectors?", "Samudra"),
    "0502": ("What does CAQM Direction 98 require per the policy record, and for which industries?", "CAQM"),
    "0503": ("What does the policy record state on the customs duty on flat-rolled steel: old and new rate, and effective date?", "flat-rolled"),
    "0504": ("What does the policy record state on Budget 2026-27 railway rolling-stock capex: amount and source?", "rolling"),
    "0507": ("What does the policy record state on the GST process reforms of October 2026, and which sectors are named?", "GST"),
    "0513": ("What does the policy record state on tax collected at source on coal and iron-ore sales: old and new rate, and effective date?", "TCS"),
    "0694": ("What does the policy record state on the generic-drug tariff timeline, and which pilot exporter is named, if any?", "generic"),
    "0789": ("What does the policy record state on the US generic-drug tariff, by rate and year?", "generic"),
}
redo(*POLICY)
for m, (q, term) in POLICY.items():
    K(m, q, pol=term)
