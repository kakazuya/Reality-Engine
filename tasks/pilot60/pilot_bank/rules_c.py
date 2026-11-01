"""Rules for MB0631-MB0830, written by Claude. Chain questions assert no company fact, so their words stay and the scope becomes named pilot stocks with evidence."""
from build import CH, K, M, S, X

for mid, ev, fit in [
    ("0631", 'copper OR "fixed price" OR "price variation"', "epc input"), ("0632", 'rubber OR "carbon black"', "auto"), ("0633", 'steel AND (OEM OR forging)', "auto steel"),
    ("0634", 'aluminium OR conductor', "HINDALCO KEC POWERGRID"), ("0635", '"steel" AND (escalation OR "fixed price")', "epc steel"), ("0636", 'crude AND (dealer OR margin)', "paint"),
    ("0638", '"subsidy" OR urea OR tractor', "fertagri auto"), ("0639", 'cotton', "textile"), ("0640", 'gold AND inventory', "jewel"), ("0641", '"iron ore"', "steel"),
    ("0642", 'coal AND power', "HINDALCO POWERGRID NLCINDIA"), ("0643", '"soda ash" OR glass', "GRASIM"), ("0644", 'pulp OR packaging OR paper', "pack"), ("0645", 'China AND (intermediate OR dumping OR pricing)', "chem"),
    ("0646", 'ethanol OR sugar', "sugar HINDPETRO UBL"), ("0647", '"freight" AND import*', None), ("0648", 'rubber OR "carbon black"', "auto chem"), ("0649", '"pet coke" OR petcoke', "cement"), ("0650", 'copper OR steel', "capgood"),
    ("0651", '"data centre" OR "data center"', None), ("0652", 'FTA OR "free trade"', "textile"), ("0653", 'US AND tariff', "textile export"), ("0654", 'generic OR CDMO', "pharma"), ("0655", 'NIM OR "cost of funds"', "lender"),
    ("0656", '"interest rate" OR repo', "realty cement lender"), ("0657", '"credit growth" OR capex', "capgood lender"), ("0658", 'insurance', "lender wealth"), ("0659", 'ECB OR "external commercial" OR "foreign currency"', "infra"),
    ("0660", 'FPI OR "foreign portfolio"', None), ("0661", 'export AND realisation OR hedging', "export"), ("0662", 'deposits AND NIM', "lender"), ("0663", 'defence AND (JV OR "joint venture" OR FDI)', "defence"),
    ("0664", 'MSME OR MSE', "lender"), ("0665", 'agrochem* OR "crop protection" OR farmer', "fertagri chem"), ("0666", '"order book" AND (road OR highway)', "epc"), ("0667", '"Jal Jeevan" OR pipe', "epc APLAPOLLO"),
    ("0668", 'state AND (award OR government)', "epc"), ("0669", 'discom OR receivable', "power"), ("0670", 'seed OR farm', "fertagri auto"), ("0671", 'NIM OR "cost of deposits"', "lender"), ("0672", 'spread OR "cost of funds"', "lender"),
    ("0673", 'rupee OR forex', "it"), ("0674", 'rupee OR API', "pharma"), ("0675", 'rupee OR currency', "auto elec"), ("0676", '"interest cover" OR "import content" OR "cash cycle"', None), ("0677", 'deposits', "lender"),
    ("0678", '"commercial paper"', "lender"), ("0679", 'liquidity', "lender"), ("0680", 'CRR', "lender"), ("0681", 'spread OR prepayment', "lender"), ("0682", '"interest rate" AND (demand OR entry)', "TMPV BOSCHLTD BAJFINANCE"),
    ("0683", 'tariff AND renewable', "power"), ("0684", 'cane', "sugar"), ("0685", 'rupee OR "foreign currency"', "export"), ("0686", 'subsidy', "fertagri lender"), ("0687", 'gold AND rupee OR gold AND inventory', "jewel"),
    ("0688", 'refinanc* OR "discount rate"', "infra"), ("0689", 'inventory AND (steel OR write)', "steel"), ("0690", 'hedge OR "mark-to-market"', "export"), ("0691", 'Europe AND (shipping OR "Red Sea" OR freight)', "export"), ("0692", 'steel AND (US OR tariff)', "steel metal auto"),
    ("0693", 'dumping', "chem"), ("0694", 'generic AND US', "pharma"), ("0695", 'CBAM OR "carbon border"', "metal"), ("0696", '"edible oil" OR palm', "fmcg"), ("0697", 'garment OR Bangladesh OR capacity', "textile"),
    ("0698", '"under-recovery" OR "under recovery" OR "marketing margin"', "oil"), ("0699", 'component AND (export OR localisation)', "elec"), ("0700", 'export AND order', "export"), ("0701", 'US AND EU', "export"), ("0702", 'coal AND power', "HINDALCO NLCINDIA POWERGRID"),
    ("0703", 'copper AND inventory OR hedging', "input"), ("0704", 'QIP OR "fund raise"', None), ("0705", 'freight OR shipping', "export import"), ("0706", 'rubber', "auto"), ("0707", 'gold', "jewel"), ("0708", 'competitor OR "market share"', None),
    ("0709", 'milk OR monsoon', "fmcg"), ("0710", 'US AND EU AND tariff', "export"), ("0711", 'PLI OR module', None), ("0712", 'module OR solar', "power metal"), ("0713", 'acquisition AND cement', "cement"), ("0714", '"market share"', "input"),
    ("0715", 'paint', "paint"), ("0716", 'safeguard OR imports', "steel"), ("0717", 'OEM', "auto"), ("0718", '"fund raise" OR QIP OR capex', "chem"), ("0719", '"home loan" OR spread', "lender"), ("0720", 'insurance', "lender wealth"),
    ("0721", 'CDMO OR contract', "pharma chem"), ("0722", 'defence', "defence"), ("0723", 'PLI', "elec"), ("0725", 'aggregator OR delivery', "qsr"), ("0726", 'aero OR traffic', "airport"), ("0727", 'packaging', "pack"), ("0728", 'garment OR capacity', "textile"),
    ("0729", '"personal loan" OR "credit cost"', "lender"), ("0731", 'QIP OR "fund raise" OR "rights issue"', None), ("0732", 'pledge', None), ("0733", 'index AND inclusion', None), ("0734", '"stock split" OR "sub-division"', None), ("0735", 'buyback', None), ("0736", 'repay AND equity', None),
    ("0737", 'IPO', None), ("0738", '"offer for sale"', None), ("0739", 'rating AND debt', None), ("0740", 'guidance AND promoter', None), ("0741", 'index AND exclusion', None), ("0743", 'insider', None), ("0744", 'promoter AND "open market"', None), ("0745", 'pledge AND invo*', None),
    ("0746", '"rights issue"', None), ("0747", 'demerger', None), ("0748", 'warrants', None), ("0749", 'buyback AND tender', None), ("0750", 'IRR OR "cost of capital"', None), ("0752", 'crude', "paint"), ("0753", 'NIM', "lender"),
    ("0754", '"cost of funds"', "lender"), ("0755", 'hedge AND rupee', "it export"), ("0756", 'steel AND margin', "auto steel"), ("0757", 'monsoon AND (rural OR tractor)', "fmcg auto"), ("0758", 'rural AND wage', "fmcg auto"), ("0759", 'capex AND government', "epc"),
    ("0760", 'defence AND order', "defence"), ("0761", 'commissioning AND delay', None), ("0762", 'PLI AND incentive', None), ("0763", 'QIP OR "preferential"', None), ("0764", 'freight', None), ("0765", 'rating AND downgrade', None), ("0766", 'tariff AND order', "export"),
    ("0767", '"price hike" OR "price increase"', None), ("0768", 'inventory AND margin', None), ("0769", 'repay AND debt', None), ("0770", 'QIP', None), ("0771", 'rupee AND (aluminium OR coal)', "metal"), ("0772", 'treasury OR NIM', "lender"), ("0773", 'copper', "input"), ("0774", 'crude', "oil"),
    ("0775", 'US AND EU', "textile"), ("0776", 'freight', "export"), ("0777", '"coking coal" OR captive', "steel"), ("0778", 'spread OR disbursement', "lender"), ("0779", 'gold AND inventory', "jewel"), ("0780", 'subsidy OR PLI', None), ("0781", 'Europe AND rupee OR import AND euro', "auto"),
    ("0782", 'wage', "retail fmcg"), ("0783", '"data centre" OR "data center"', "capgood"), ("0784", 'safeguard OR steel', "GRASIM TMPV SAIL HINDALCO"), ("0785", 'insurance', "lender wealth"), ("0786", '"electric vehicle" OR EV', "auto"), ("0787", '"pet coke" OR petcoke', "cement"), ("0788", 'coal AND tariff', "power"),
    ("0789", 'US AND India', "pharma"), ("0790", '"credit cost"', "lender"),
]:
    CH(mid, ev, fit, min_n=1)
M("0751", "Copper moves 20% in a quarter. Using the quarterly margins of {cohort}, what was the last cycle's lag between the metal move and the margin trough, and does it hold across them?", 'copper', "CDANX", "input metal", min_n=1)
S("0637", "Edible-oil and crude-linked packaging costs rise into a weak rural quarter. {name} faces a cost push and a demand pull. Which shows up in its volume number first, and what rural signal does it cite?", 'rural AND volume', "CDA", "HINDUNILVR")
X("0724", "No pilot stock is a hospital chain")
X("0730", "No pilot stock is a pharmacy chain")
X("0742", "F&O ban history is not held")
for mid, q in [
    ("0791", "For a metal-linked margin trough, three signals compete: the metal price, the price-hike statement, and the delivery spike. Which turns first in our data, and is each point-in-time?"),
    ("0792", "Entry-segment two-wheeler demand: is the rural wage series, the scheme allocation or dealer inventory in our data, and which is point-in-time today?"),
    ("0793", "Bank NIM: are the weighted average call rate, the deposit rate and credit growth held, and is the deposit rate a point-in-time series?"),
    ("0794", "EPC margin: of the order book, the steel index and the award pipeline, which is in our data with a known_at?"),
    ("0795", "Export orders: of container freight, port throughput and the company's delivery spike, which can be read point-in-time?"),
    ("0796", "Capex revival: of order inflow, capital-goods production and credit growth, which is usable without look-ahead?"),
    ("0797", "Power demand: of plant load factor, coal stock days and the exchange price, which is held, and which leads the aluminium smelter's cost?"),
    ("0798", "Steel price: of the HRC index, mill inventory days and import volume, which is point-in-time in our data today?"),
    ("0799", "US generic drug erosion: of ANDA approvals, price-erosion commentary and distributor inventory, which can be dated from a filing?"),
    ("0800", "Cement demand: of dispatches, GST collection and pet coke, which is held, and which turns before the others?"),
    ("0801", "Freight: of the Baltic index, the container rate and the charter rate, which is published with a date usable in a backtest in our data?"),
    ("0802", "Foreign flow: of FPI limit headroom, index membership changes and the delivery spike, which is point-in-time and which is a revision risk?"),
    ("0803", "The rupee: of forward premium, spot and exporter commentary, which is a usable leading series in our data, and which is interpretation?"),
    ("0804", "NBFC credit cost: of bounce rates, disbursement growth and GNPA, which is point-in-time in a filing, and which is not published at all?"),
    ("0805", "Hotel or airport revenue per unit: of capacity, occupancy and pricing, which is dated in a filing?"),
    ("0806", "Dairy procurement: of rainfall, fodder price and the procurement price, which is a published series in our data?"),
    ("0807", "Auto replacement demand: of freight movement, kilometres run and dealer stock, which is in our data with a date?"),
    ("0808", "Capital-goods activity: of order inflow, GST on capital goods and credit to industry, which is held, and which is a revision risk?"),
    ("0809", "Lender fee income: of commission paid, disbursements and partner fee income, which is dated in a filing?"),
    ("0810", "A defence order: of the budget allocation, the award and the delivery, which is usable in a point-in-time test?"),
]:
    K(mid, q)
S("0811", "A bulk or block deal printed on {name} on {bulk_date}. Take day 0 as the deal session, look at the 4 sessions before it, and say whether delivery differs from the rest of that month.")
S("0812", "{name}'s earnings call of {ev_date} and its results filing: apply the 3:30 rule to each separately, then compare the 4 sessions before each day 0 with the 20 sessions before that.", '"earnings call" OR analyst', "C")
S("0813", "Take {name}'s order-win filing of {ann_date} {ann_time}. Work out day 0 from the 15:30 rule. Which of the 4 sessions before day 0 carried an unusual delivery share?", ann="order|contract|LOA|letter of award")
S("0814", "Take {name}'s rating filing of {ann_date} {ann_time}. Use it for day 0, then test whether the 4 sessions before it show accumulation.", ann="rating")
S("0815", "{name} discussed capex on its call of {ev_date}. The transcript is usable only when published. Build day 0 from the known time and check the 4 sessions before it.", 'capex OR "capital expenditure"', "C")
S("0816", "{name} filed about an acquisition on {ann_date} at {ann_time}. Work out day 0, then build the 4-session window that precedes it.", ann="acqui")
S("0817", "Take {name}'s management-change filing of {ann_date} {ann_time}. Build day 0 and check the 4 sessions before it. What does the filing name: the person, the role and the date?", ann="change in (management|directorate)|appointment of|resignation of")
S("0818", "The US tariff is in policy_events with its own published_at. Build day 0 for {name} from that timestamp, and ask whether a 4-session window before an overnight policy is evidence of anything.", 'US AND tariff', "CDA", "export")
S("0819", "The Union Budget speech of 1 February 2026 is inside the session. Build the 4 sessions before it for {name} and say whether positioning before a scheduled event is leakage or expectation.", None, "CDA", "textile")
S("0820", "The MPC statement of 7 October 2026 is published before the close. Build day 0 for {name}, then check whether the 4 sessions before it contain anything a rule could call leakage.", None, "CDA", "lender")
S("0821", "{name} entered or left an index on a stored date. Take that date as day 0, build the 4-session window, and say what it can show.", None, "CDA", "HEGAM UFLEX KEC ANANDRATHI KALYANKJIL DALBHARAT")
S("0822", "{name} disclosed a PLI approval or scheme benefit on {ev_date}. Take the known date for day 0 and check whether the 4 sessions before it show accumulation.", 'PLI', "CDX")
S("0823", "{name}'s scheme or demerger filing of {ann_date} {ann_time}: build the 4-session window and say what a leaker would have acted on.", ann="demerger|scheme of arrangement|amalgamation")
S("0824", "{name} had a {ca_type} with ex-date {ca_date}, which has no cash effect. Build day 0 and check the 4 sessions before it. This is the negative control.")
S("0825", "Take {name}'s pledge disclosure of {ann_date} {ann_time}. Build day 0 and check the 4 sessions before it for distribution rather than accumulation.", ann="pledge|encumbr")
S("0826", "{name}'s tax or regulatory filing of {ann_date} {ann_time}: build day 0, check the 4 sessions before it, and say which document contains the order and the amount.", ann="tax|demand|penalty|GST")
S("0827", "Take {name}'s auditor filing of {ann_date} {ann_time}. Build day 0 and check the 4 sessions before it. It should not leak, which makes it a control.", ann="auditor")
S("0828", "Take {name}'s largest insider sale in insider_trades_v2. The intimation date gives day 0; check the 4 sessions before it and say whether the sale was the information or the response to it.", None, "CDA", "HINDALCO KEC UFLEX APLAPOLLO DLF")
S("0829", "{name} discussed its guidance on the call of {ev_date}. Build day 0 from the publication, then check the 4 sessions before it. Which document carries the change?", 'guidance AND (revised OR lowered OR cut)', "C")
S("0830", "{name} announced a buyback in the filing of {ann_date} {ann_time}. Work out day 0 from the 15:30 rule. Check the 4 sessions before it: leak or price support?", ann="buy.?back")
