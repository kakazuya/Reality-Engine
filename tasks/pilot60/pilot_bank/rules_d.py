"""Rules for MB0831-MB1073, written by Claude. Reddit-style asks: the outside company is replaced with a pilot stock that has the evidence; opinions are restated as what the data shows."""
from build import K, M, S, X

X_FO = "Stock futures and options data (open interest, rollover, strikes) is not held; only the market-wide macro.oi side file is"
S("0831", "{name}: did delivery strengthen in the week of the September 2026 expiry against the week before?")
K("0832", "Market-wide, does cash volume pick up in expiry week? Use the index turnover series, and say what it can show.")
M("0833", "Among {cohort}: which kept cash-market delivery above its own average through the September 2026 expiry?", None, fit="HINDALCO SAIL POWERGRID GRASIM DLF HINDUNILVR BAJFINANCE SUNPHARMA")
X("0834", X_FO)
S("0835", "As of 19 October 2026, was {name}'s delivery percentage higher on the 29 September 2026 expiry than on ordinary sessions that month?")
K("0836", "Market-wide, which sessions in 2026 had the widest Nifty 50 opening gap, and how much of it survived to the close?")
M("0837", "As of 30 September 2026, which of {cohort} had gapped more than 2%, and did delivery confirm the gap?", None, fit="HINDALCO SAIL POWERGRID GRASIM DLF HINDUNILVR BAJFINANCE SUNPHARMA", as_of="2026-09-30")
X("0838", "ADR and overnight US prices are not held")
K("0839", "On the sessions when held Brent rose most in 2026, how did the Nifty 50 move at the next open?")
X("0840", "US tech index data is not held")
for mid, q, in [
    ("0841", "{name}: its most recent dividend ex-date and amount, and how did the stock trade into it?"),
    ("0843", "{name} ka latest dividend: record date aur ex-date mein difference kyu hai, aur kya dekhna chahiye?"),
    ("0844", "As of 19 October 2026, what had {name} announced about its latest payout, and when did it go ex?"),
]:
    S(mid, q, 'dividend', "XCA")
M("0842", "Among {cohort}: which went ex-dividend most recently, with the amount each declared?", 'dividend', "XCA")
M("0845", "Among {cohort}: which paid a dividend in the September 2026 quarter, and how much per share?", 'dividend', "XCA", "lender power oil")
M("0846", "On 16 October 2026, which of {cohort} were in a 5% or lower price band on heavy volume?", None, fit="HINDOILEXP IDEA AURUM DOLLAR KHADIM HMVL")
M("0847", "Among {cohort}: is a 5% or lower band a trap? Show price and delivery on band-hit days.", None, fit="HINDOILEXP IDEA AURUM DOLLAR KHADIM HMVL")
M("0848", "Among {cohort}: float and delivery, is it value or a float too small to trust?", None, fit="DDEVPLSTIK DOLLAR BIGBLOC KHADIM HMVL WPIL ASAHISONG")
S("0849", "As of 19 October 2026, how many of the last 20 sessions had {name} closed at its upper price band?", fit="HINDOILEXP IDEA AURUM DOLLAR KHADIM HMVL")
S("0850", "{name} ka price kya hai: sasta lag raha hai ya bas sasta dikh raha hai, aur delivery se kya samajhna?", fit="IDEA HMVL DOLLAR")
M("0851", "If the RBI cuts the repo by 25bp, which of {cohort} reprice deposits first, and what do they say?", 'deposits OR "cost of funds"', "CDA", "lender")
M("0852", "If crude holds above $90 for a quarter, how does that reach {cohort}'s input costs?", 'crude', "CDA", "chem pack paint oil")
M("0853", "Which of {cohort} would respond fastest if the government raises the PLI outlay again?", 'PLI', "CDA")
M("0854", "As of 19 October 2026, what would a 10% copper rise do to the costs of {cohort}?", 'copper', "CDA")
M("0855", "Which of {cohort} gain most if the 10-year yield falls 50bp, and which lose on the second round?", '"interest rate"', "CDA", "lender realty infra")
S("0856", "{name}'s weekly closes: did the base before its 52-week high lead to a breakout or a fade over the following 20 sessions?")
S("0857", "As of 19 October 2026, had {name} built higher highs or lower highs over the last 60 sessions?")
M("0858", "{cohort} ke chart par higher-highs base ban raha hai kya, ya sirf ek bounce hai?", None, fit="HINDALCO SAIL")
M("0859", "In the data-centre theme, which of {cohort} gives the cleanest proxy, by what they disclose?", '"data centre" OR "data center"', "CDA")
M("0860", "Green hydrogen: {cohort} is theme par kya kehte hain, aur revenue kitna aata hai?", '"green hydrogen"', "CDA")
M("0861", "Against the held gold series, how did {cohort} do over 2026, and which was the better proxy?", None, fit="jewel", min_n=1)
S("0862", "{name}'s scheme or demerger: which approvals were pending at the filing of {ann_date}, and how did the stock trade into it?", ann="demerger|scheme of arrangement")
S("0863", "{name}: did a promoter or government stake sale happen, and how did the price react?", ann="stake|offer for sale|OFS")
M("0864", "Among {cohort}: which announced schemes still need an NCLT order, and what is the expected completion window?", 'NCLT', "CDAX")
S("0865", "{name} listed around {list_date}. What was its first-session close, and how did that compare with its first-day range?", fit="ipo")
M("0866", "Among {cohort}: which trades below its first-session close today?", None, fit="ipo")
S("0867", "{name} ke listing ke baad valuation kis multiple par dekhna sahi hai? First session aur aaj ka close batao.", fit="ipo")
S("0868", "If the data-centre build-out doubles, is {name} a second-order winner, or does the spend land elsewhere first?", '"data centre" OR "data center"', "CDA")
M("0869", "Which of {cohort} feel a doubling of data-centre capex, and in what order?", '"data centre" OR "data center"', "CDA")
M("0870", "As of 19 October 2026, which of {cohort} had disclosed order wins in green hydrogen?", '"green hydrogen"', "CDAX", min_n=1)
S("0871", "{name} {res_q} results date: when, and was it pre-intimated?")
M("0872", "Among {cohort}: when were Q2FY27 results scheduled, and how many intimated late?", '"board meeting" AND results', "X")
M("0873", "As of 19 October 2026, how many of {cohort} had not intimated a results date for the September quarter?", '"board meeting" AND results', "X")
ENT = "{name} moved {react_pct}% after {res_q}. Where is the close against its pre-result range and 52-week high, and what did delivery do?"
S("0874", ENT)
S("0875", "How far is {name} from its 52-week high, and what is its P/E against its own history?")
S("0876", "How far is {name} from its 52-week low, and how did it trade into its last results?")
S("0877", "How has {name} moved since listing on {list_date}, and does its reported growth back it?", fit="ipo")
S("0878", "{name} ka {rise_date} ko {rise_pct}% ka move aur uske baad pullback kitna tha? Results ke aas-paas kya hua?")
M("0879", "Among {cohort}: which carries the least balance-sheet risk relative to its cash generation?", '"net debt"', "CDA", "HINDALCO GRASIM")
M("0880", "Among {cohort} in the Tata group: which is the cleaner proxy for group capex, by its own disclosure?", 'capex', "CDA", "TMPV TATAELXSI INDHOTEL")
M("0881", "Among {cohort}: which has the best NIM and credit cost this quarter, and which is most exposed to a slippage cycle?", '"credit cost" OR NIM', "CDA", "lender")
M("0882", "Among {cohort}: which has the order book to revenue cover that best protects it if capex slows?", '"order book"', "CD", "defence epc capgood")
M("0883", "Among {cohort}: which earns a spread on capex, and which just executes it?", 'capex OR "regulated"', "CDA", "infra")
S("0884", "{name}'s first session on {list_date}: what was its first-day close compared with the first-session open?", fit="ipo")
S("0885", "{name}'s listing on {list_date}: what was the first-day return, and how much was gone within a month?", fit="ipo")
S("0886", "{name}: did the first-month move after listing on {list_date} line up with results, or was it mostly scarcity?", fit="ipo")
M("0887", "Among {cohort}: how did each trade in its first year after listing?", None, fit="ipo")
M("0888", "After listing, which of {cohort} trades at the biggest premium to book?", None, fit="ipo")
S("0889", "After the Tata Motors demerger into {name}, how should the cost basis split, and what does the corporate-action record show?", fit="TMPV")
S("0890", "{name}'s price history across a change of name or symbol: does the ISIN stay the same?", fit="ANANDRATHI TMPV GMRAIRPORT HEGAM")
S("0891", "{name}'s demerger: which listed entity holds which business, and what happens between the record date and listing?", 'demerger', "CDAX")
S("0892", "{name} had a {ca_type} with ex-date {ca_date}. What price should the stock have opened at, and what did it open at?")
X("0893", "No pilot stock has a government offer for sale held")
M("0894", "Which regulator action hit {cohort}, when was it disclosed, and how did the price react on the first session after?", '"show cause" OR penalty OR SEBI', "X")
S("0895", "{name}: what has SEBI concluded or asked, what is still open, and which disclosures changed the risk?", 'SEBI AND (penalty OR order OR "show cause")', "XA")
S("0896", "{name}'s shareholder lock-in: what is still restricted, and when does it end?", '"lock-in"', "AX")
S("0897", "{name}'s preferential allotment: which SEBI pricing rule set the floor, and did it dilute more than announced?", '"preferential"', "AXC")
S("0898", "For {name}, what does LODR require within 24 hours, and did its filing of {ann_date} meet that clock?", ann="outcome of board meeting|change in|acquisition|resign")
for mid, q in [
    ("0899", "{name}: which price band applies now, and when was it last changed?"),
    ("0900", "{name}: what band applies, and how does delivery behave on the days it touches the band?"),
    ("0901", "{name}: did the band change after the last reset, and did the change coincide with a volume spike?"),
    ("0902", "{name}: how many sessions were locked at the lower band in its longest streak, and what ended it?"),
    ("0903", "{name}: did the price band widen, and how did delivery change when it did?"),
]:
    S(mid, q, fit="HINDOILEXP IDEA AURUM DOLLAR KHADIM HMVL")
S("0904", "Why did {name} move on 4 June 2024, and which inputs were known before the open?")
S("0905", "{name} moved {react_pct}% after {res_q}. Was the move in the numbers, the guidance, or the pre-result positioning?")
S("0906", "Why did {name} move {rise_pct}% on {rise_date}, and how did its sector index do?")
S("0907", "{name} moved {react_pct}% after {res_q}. Did the market react to margins, guidance or the rupee?")
S("0908", "{name} moved around the demerger record date. How much of the move was the mechanical price adjustment?", fit="TMPV")
S("0909", "{name} is below its 52-week high. What do revenue, margin and debt show over the last four quarters?")
S("0910", "{name} has been flat. What has improved in the business over two years, and what is the price change?")
S("0911", "What does {name} say on market share, how does that show in the numbers, and what is the cash position?", '"market share"', "CDA")
S("0912", "{name} has run up. How much, and is its reported margin still improving?")
S("0913", "{name}'s lock-in: did the supply hit the price, and what did delivery show?", '"lock-in"', "AX")
S("0914", "In 2026's month of heaviest market-wide FII selling, how did {name} move, and how much lines up with the outflow?")
S("0915", "{name}: did DII holdings offset FII holdings last quarter, and what did the shareholding pattern show?{?shp}")
S("0916", "{name}: is DII accumulation visible in the shareholding pattern?{?shp}")
S("0917", "{name}: did order announcements or institutional holdings better explain the last two quarters of returns?{?shp}", '"order book"', "CD")
M("0918", "{cohort}: which saw the bigger FII ownership change last year, and did the price gap follow?", None, fit="SUNPHARMA ALKEM")
S("0919", "If the budget raises duties on its products, how much of {name}'s revenue is exposed, and what did the last change do to volumes?", 'duty AND volume', "C", "UBL HINDUNILVR")
M("0920", "Defence budget line: which of {cohort} has the revenue visibility that matches its valuation?", 'defence', "CDA", "defence")
M("0921", "Infrastructure capex: does it show first in {cohort}'s revenue, and with what lag?", 'capex', "CD", "epc", min_n=1)
M("0922", "A higher import duty: who benefits among {cohort}, and what happens to the customer's cost?", '"import duty" OR "basic customs"', "CDA")
M("0923", "Raw material moves: which of {cohort} has the best pass-through history?", '"pass through" OR "pass on" OR "passed on"', "C")
for mid, q in [
    ("0924", "{name}: how has promoter pledge moved over the last four quarters?{?shp}"),
    ("0925", "{name}: is promoter pledge rising alongside debt?{?shp}"),
    ("0926", "{name}: did the promoter group change its stake in the last year, and what did that do to the free float?{?shp}"),
    ("0927", "{name}: has promoter pledge fallen, and what has debt done?{?shp}"),
]:
    S(mid, q)
M("0928", "Among {cohort}: which had the biggest promoter stake sale in the last year, and did the stock absorb it?", None, fit="BOSCHLTD PIDILITIND GRASIM HINDUNILVR SUNPHARMA HINDALCO DLF IDEA")
for mid, q in [
    ("0929", "{name} {res_q}: which line item explains the market's {react_pct}% reaction?"),
    ("0930", "{name}: did its order wins convert into revenue this quarter, or is the book growing faster than billing?"),
    ("0931", "{name} {res_q}: was any margin expansion real, or a one-off, and what did management guide?"),
    ("0932", "{name}: did the quarter's growth come from mix or discounts, and what does that say about margin?"),
    ("0933", "{name}: which segment actually drove {res_q}, and did the market react to the consolidated or segment story?"),
]:
    S(mid, q)
M("0934", "{cohort}: which has the better EV mix and margin, and does the market pay for it?", '"electric vehicle" OR EV', "CDA", "TMPV BOSCHLTD", min_n=1)
M("0935", "{cohort} on spread, return on assets and credit cost: which is the cleaner compounder?", '"credit cost"', "CDA", "lender")
M("0936", "{cohort}: which is growing revenue per store faster, and is the data comparable?", 'stores OR showrooms', "CDA", "retail jewel qsr")
M("0937", "{cohort}: which has the better working-capital cycle, and does the margin gap justify the valuation gap?", '"working capital"', "CDA", "SAIL APLAPOLLO")
M("0938", "{cohort}: how much of revenue is US, and which is more exposed to a price-erosion shock?", '"price erosion" OR US', "CDA", "pharma")
for mid, q in [
    ("0939", "What is {name}'s P/E, what growth does that assume, and what has the company delivered?"),
    ("0940", "What is {name}'s multiple today, and is its reported growth enough to grow into it, or is margin expansion needed too?"),
    ("0941", "{name} on EV/sales: what does the multiple imply about the path to profit, and which segment has to carry it?"),
    ("0942", "What is {name}'s P/B, and what ROE would justify it?"),
    ("0943", "Is {name} profitable or loss-making in its latest results, and what metric should valuation be judged on?"),
]:
    S(mid, q)
S("0944", "When {name} entered or left an index in the stored record, did the stock move before or after the date?", fit="HEGAM UFLEX KEC ANANDRATHI KALYANKJIL DALBHARAT")
S("0945", "Was {name} added to an index in the stored record, and did any first big move come before that date?", fit="HEGAM UFLEX KEC ANANDRATHI KALYANKJIL DALBHARAT")
X("0946", "Index weights on rebalance days are not held")
X("0947", "A forced-selling estimate needs passive AUM and index weights, which are not held")
X("0948", "Index weights and reconstitution attribution are not held")
for mid, q, ev in [
    ("0949", "{name}: over its held history, has gross margin been stable, or did it track crude?", '"gross margin"'),
    ("0950", "{name}: is growth from price or volume?", 'volume AND price'),
    ("0951", "{name}: is recent growth from volume or from price and mix?", 'volume AND mix'),
    ("0952", "{name}: is the margin a brand premium or a gold artefact, and how would a gold spike change it?", 'gold AND margin'),
    ("0953", "{name}: has competition taken share, and what does the volume trend say?", '"market share" AND volume'),
    ("0954", "{name}: what has return on capital been through the cycle, and which business carries it?", 'ROCE OR ROIC'),
    ("0955", "{name}: its last capex round: what incremental return has it earned so far?", 'capex AND (ROCE OR ROIC OR returns)'),
    ("0956", "{name}: does ROCE clear the cost of capital after the working-capital build?", 'ROCE AND "working capital"'),
    ("0957", "{name}: is the return earned on new capacity or a cyclical order book, and what is the margin?", '"order book" AND margin'),
    ("0958", "{name}: after a regulatory change, did pricing lift ROCE?", 'ROCE'),
    ("0959", "{name}: between dividends and reinvestment, which has earned the better return over five years?", 'dividend AND capex'),
    ("0960", "{name}: what are the payout and capex, and is either limiting the other?", 'dividend AND capex'),
    ("0961", "{name}: is retained capital earning above the cost of equity, and should the payout change?", 'ROE AND dividend'),
    ("0962", "{name}: how much dilution has funded growth, and is per-share value growing as fast?", 'QIP OR "preferential"'),
    ("0963", "{name}: where is capex going, and what return has the last cycle produced?", 'capex AND EV OR capex AND JLR'),
    ("0964", "{name}: do receivables and inventory run ahead of revenue, and what does the cash conversion say?", '"cash conversion" OR "trade receivables"'),
    ("0965", "{name}: is cash upstreamed from subsidiaries, and what do the related-party notes say?", '"related party" AND dividend'),
    ("0966", "{name}: how are its large liabilities accounted for, and do assumptions flatter the loss?", 'spectrum OR AGR'),
    ("0967", "{name}: how much of the balance sheet is CWIP and capitalised interest, and when does it start depreciating?", 'CWIP OR "capital work"'),
    ("0968", "{name}: are provisions keeping pace with the stressed book, and how much is write-back?", 'provisions AND (stressed OR write)'),
    ("0969", "{name}: margin guidance over time. What was promised, what was delivered, and what is the gap?", 'guidance AND margin'),
    ("0970", "{name}: its margin guidance. Which call first changed it, and what did the market do after?", 'guidance AND margin'),
    ("0971", "{name}: growth guidance versus actual. Has it beaten its own number?", 'guidance AND growth'),
    ("0972", "{name}: what net-debt target did management give each time, and where is net debt now?", '"net debt" AND target'),
    ("0973", "{name}: a profitability timeline was given. Did it hit it, and what did that cost in growth?", 'profitability AND timeline'),
    ("0974", "{name}: what is contribution margin per unit, and how much profit comes from where?", '"contribution margin"'),
    ("0975", "{name}: is margin improving from scale or cut discounts, and what does that mean for growth?", 'discount AND margin'),
    ("0976", "{name}: what does a segment earn per order or unit, and is another diluting it?", 'segment AND margin'),
    ("0977", "{name}: revenue per square foot and inventory turns: how have they moved?", '"square foot" OR "sq. ft" OR "per sq"'),
    ("0978", "{name}: what does a new store earn at maturity, and how long is payback?", 'payback OR "store level"'),
    ("0979", "{name}: where are we in the cycle, and what is its cost position?", 'cycle AND cost'),
    ("0980", "{name}: capacity utilisation and spread now versus last downcycle, and how fast does margin mean-revert?", '"capacity utilisation" OR "capacity utilization"'),
    ("0981", "{name}: how much of the margin is cycle and how much is cost advantage?", 'cycle AND margin'),
    ("0982", "{name}: what does it say on destocking, inventory days and realisation?", 'destocking OR "inventory days"'),
    ("0983", "{name}: is the cycle a price war or a volume recovery, and what does cost per tonne say?", '"per tonne" OR "per ton"'),
    ("0984", "If the RBI cuts rates, what happens to {name}'s NIM first and loan growth second, and how long is the lag?", 'NIM'),
    ("0985", "{name}: does a rate cut help cost of funds before it helps AUM, and what does history say?", '"cost of funds" AND AUM'),
    ("0986", "Crude fell. How long before {name}'s raw-material cost falls, and what did it do last time?", 'crude AND "raw material"'),
    ("0987", "The rupee weakened. How much of {name}'s margin gain is translation versus hedging, and when does it show?", 'hedging AND margin'),
    ("0988", "Rubber and crude rose together. How did {name} pass through the last spike?", 'crude AND "pass"'),
    ("0989", "{name}: how much can it reinvest in capacity, and what has the last expansion earned?", 'expansion AND ROCE'),
    ("0990", "{name}: what does it say on demand and remaining capex, and is the incremental return above the last cycle?", 'capex AND demand'),
    ("0991", "{name}: what is the reinvestment need per rupee of new revenue, and does the return clear the hurdle?", 'capex AND PLI OR capex AND ROCE'),
    ("0992", "{name}: what is the new-plant runway, and how much of the order book depends on it?", '"order book" AND plant'),
    ("0993", "{name}: does capacity addition still make sense if demand slows, and what is utilisation today?", '"capacity addition" OR utilisation'),
    ("0994", "{name}: how much debt matures in the next two years, and can cash cover it without asset sales?", 'maturity AND debt OR repayment AND debt'),
    ("0995", "{name}: can operating cash flow cover interest, or is another capital raise likely?", '"interest" AND "cash flow"'),
    ("0996", "{name}: has the debt actually fallen, or moved into CWIP and JVs?", 'debt AND (CWIP OR "joint venture")'),
    ("0997", "{name}: what is net debt to EBITDA, and how is capex funded if refinancing narrows?", '"net debt" AND EBITDA'),
    ("0998", "{name}: how much of the leverage sits at the parent, and what did monetisation repay?", 'monetisation OR monetization'),
    ("0999", "{name}: does CFO track PAT, and are receivables days creeping?", '"receivable days" OR DSO OR "cash flow from operating"'),
    ("1000", "{name}: has unbilled revenue grown faster than revenue, and what does that say about recognition?", '"unbilled revenue"'),
    ("1001", "{name}: did DSO and CFO/PAT improve with the client mix?", 'DSO OR "client mix"'),
    ("1002", "{name}: how much of growth is acquisition versus organic, and what did that do to goodwill and cash conversion?", 'organic AND acquisition'),
    ("1003", "{name}: is margin expansion real, or capitalised development cost catching up?", '"development" AND capitalised'),
    ("1004", "{name}: what is the discount to its listed stakes, and has it widened?", '"listed" AND investments'),
    ("1005", "{name}: is the market cap above or below the value of its portfolio, and how has the gap behaved?", 'investments AND subsidiaries'),
    ("1006", "What stakes in other companies does {name} hold, and what is their per-share value versus the market price?", 'subsidiaries AND investments'),
    ("1007", "{name}: what are its pieces worth separately, and how much is the holding company?", 'subsidiaries AND segment'),
    ("1008", "{name}: do subsidiaries justify a market cap above the standalone business?", 'subsidiaries'),
    ("1009", "{name}: is the dividend covered by free cash flow after the capex plan?", '"free cash flow" OR dividend'),
    ("1010", "{name}: what happens to the payout if capex slows, per its dividend and capex disclosures?", 'dividend AND capex'),
    ("1011", "{name}: how much of the dividend is covered by core cash flow once reinvestment is funded?", 'dividend AND "cash flow"'),
    ("1012", "What is {name}'s payout, is it sustainable, and what does capex need?", 'dividend AND capex'),
    ("1013", "{name}: what is its dividend history, and what did the last downturn show?", 'dividend'),
    ("1014", "{name}: how concentrated is the customer base, and what would losing the top account do?", '"top customer" OR "top five" OR "top 5" OR "customer concentration"'),
    ("1015", "{name}: what share of revenue comes from top five customers, and how does that compare with order-book claims?", '"top five" OR "top 5" OR "top 10"'),
    ("1016", "{name}: how much revenue depends on the top client, and has that fallen?", '"top client" OR "top customer" OR "largest customer"'),
    ("1017", "{name}: seasonality: what does it do to quarterly revenue and working capital?", 'seasonal OR seasonality'),
]:
    S(mid, q, ev, "CDAN")
M("1018", "{cohort}: how much of the order book is EV, and how dependent on few customers?", '"electric vehicle" OR EV', "CDA", "auto", min_n=1)
for mid, q, ev in [
    ("1019", "For {name}, what evidence in filings would break the moat thesis: a new entrant's share, a dealer shift, or a gross-margin floor?", '"market share" OR "gross margin"'),
    ("1020", "For {name}, what evidence would prove quick commerce has damaged growth?", '"quick commerce"'),
    ("1021", "For {name}, what evidence in filings would prove the profitability path is broken rather than delayed?", 'profitability'),
    ("1022", "For {name}, what would prove the capex cycle has peaked: order growth, utilisation or receivable days?", '"order book" AND utilisation'),
    ("1023", "For {name}, what would break the growth thesis: a gold spike, lab-grown diamonds or a same-store slowdown?", '"lab grown" OR "same store" OR SSSG'),
]:
    S(mid, q, ev, "CDAN")
PX = [
    ("1024", "{name}: how many times since August 2026 did it retest the same zone, and did the third retest hold on lower volume?"),
    ("1025", "{name}: did it break below its 50-day average and reclaim it? Which close confirmed the reclaim, and what did delivery do?"),
    ("1026", "{name}: what are the range edges over the last two months, and how often was each tested on above-average volume?"),
    ("1027", "{name}: is its March 2026 low still valid, and how much volume sits at it?"),
    ("1028", "{name}: what is the first real support since its base, and is there enough history to trust it?"),
    ("1029", "{name}: when did it last make a new high, and was that confirmed by volume and delivery?"),
    ("1030", "{name}: at its last swing high on a delivery spike, did delivery stay high for the next five sessions?"),
    ("1031", "{name}: how many failed breakouts in the last year on below-average volume?"),
    ("1032", "{name}: does high delivery at a breakout predict a better 20-day hold than low delivery?"),
    ("1033", "{name}: near its 52-week high, has delivery fallen, and is the move driven by intraday traders?"),
    ("1034", "{name}: did the 50-day cross above the 200-day this year, and how did it behave in the 30 sessions after each cross?"),
    ("1035", "{name}: is it above its 200-day and below its 50-day? What has that meant for the next month historically?"),
    ("1036", "{name}: how far from its 200-day is it, and when did it last spend this long under the line?"),
    ("1037", "{name}: how close is the 50-day to the 200-day, and what did past crosses do for a long-term holder?"),
    ("1038", "{name}: which average has acted as the better entry line over the last three years?"),
    ("1039", "{name}: when RSI dipped below 30, how did the stock perform over the next 20 sessions the last three times?"),
    ("1040", "{name}: when overbought on RSI and making higher highs, what happened next?"),
    ("1041", "{name}: how long has RSI stayed above 70 before a 10% drawdown, historically?"),
    ("1042", "{name}: has an oversold RSI ever marked a durable low in this stock?"),
    ("1043", "{name}: how often has RSI making a higher low against a lower price low worked?"),
    ("1044", "{name}: how many sessions this year were within 2% of its 52-week high, and what followed?"),
    ("1045", "{name}: did its latest 52-week high come on declining volume, and what followed?"),
    ("1046", "{name}: how long did its last three drawdowns of 15% take to recover?"),
    ("1047", "{name}: what share of the last year's sessions were within 5% of the then-current 52-week high?"),
]
for mid, q in PX:
    S(mid, q)
M("1048", "{cohort}: which spent more of the last two years within 10% of its 52-week high, and does that predict anything?", None, fit="HINDALCO SAIL")
S("1049", "{name} gapped after {res_q}. Has the gap filled, and how many sessions did it take?")
S("1050", "{name} moved {react_pct}% after results. Did the gap act as resistance on the next two rallies?")
S("1051", "{name}'s open on the session after the 1 February 2026 Budget: was it a gap, and what did volume say?")
S("1052", "{name}: its largest up gap on a big delivery day. How much of it held by the close?")
S("1053", "{name}'s earnings gaps: which filled within a month, and did unfilled ones share a volume signature?")
for mid, q in [
    ("1054", "{name} against the Nifty 50 over a quarter: is relative strength turning, and what would confirm it?"),
    ("1055", "{name} versus the Nifty 50: how strong is relative strength, and did it come with earnings growth?"),
    ("1056", "{name}: what does the relative-strength line against the Nifty 50 say about rotation?"),
    ("1057", "{name} against the Nifty 50 over six months: is relative strength at an extreme that historically mean-reverts?"),
]:
    S(mid, q)
M("1058", "{cohort}: which has the better six-month relative strength against the Nifty 50, and does it match earnings?", None, fit="retail", min_n=2)
for m in ["1059", "1060", "1061", "1062", "1063", "1065", "1066", "1067", "1068"]:
    X(m, X_FO)
K("1064", "What does the held market-wide open-interest series show today, and is it at a level that marked short-term bottoms?")
for mid, q in [
    ("1069", "{name}: at its last 52-week high delivery spike, was it accumulation or a single block transfer?"),
    ("1070", "{name}: when delivery % jumped above 60% for two days, what was the volume, and did the price hold?"),
    ("1071", "{name}: delivery percentage falling while volume rises: what has that pattern preceded?"),
    ("1072", "{name}: delivery on circuit days: is it meaningful when the price is locked?"),
    ("1073", "{name}: delivery spikes with no price progress: distribution or absorption?"),
]:
    S(mid, q)
