"""Business-family taxonomy for the sector-label pilot.

FAMILIES: fine-grained business families with keyword regexes.  `COARSE` maps
each family to a coarse sector bucket (the granularity NSE calls a sector).
LABEL_FAMILY maps the exchange label vocabulary (NSE sectors/industries, BSE
macro sectors) onto those families.  Unknown labels fall back to keyword match.
"""
from __future__ import annotations

import re

# family -> (coarse bucket, regex of business terms)
FAMILIES = {
    "FINANCE": ("FINANCE", r"bank|nbfc|non[- ]banking|financ\w*|lending|loan|credit|insurance|"
                r"mutual fund|broking|brokerage|capital market|wealth management|"
                r"asset management|housing finance|microfinance|fintech|payment|deposit|"
                r"treasury|npa|securities|portfolio management|investment"),
    "IT": ("IT", r"software|information technology|it services|saas|erp|cloud|digital platform|"
           r"data cent|datacent|bpo|kpo|technology services|artificial intelligence|"
           r"it consultancy|it enabled|it-es|product engineering|cyber"),
    "HEALTHCARE": ("HEALTHCARE", r"pharma|pharmaceutical|drug|formulation|active pharmaceutical|"
                   r"api\b|hospital|healthcare|diagnostic|medical|surgical|clinic|ayurved|"
                   r"nutraceutical|biotech|vaccine|health service"),
    "CHEMICALS": ("CHEMICALS", r"chemical|petrochemical|specialty chem|dye|pigment|paint|coating|"
                  r"adhesive|resin|polymer|fertilizer|fertiliser|agrochemical|pesticide|"
                  r"crop protection|caustic|soda ash|fluorochem|rubber|plastic|laminate|"
                  r"solvent|oleochemical|surfactant|refractory|glass"),
    "TEXTILES": ("TEXTILES", r"textile|yarn|fabric|garment|apparel|cotton|denim|spinning|weaving|"
                 r"knitting|hosiery|silk|wool|home textile|readymade|suits|shirting|"
                 r"terry towel|linen"),
    "METALS": ("METALS", r"steel|iron ore|aluminium|aluminum|copper|zinc|brass|metal|alloy|mining|"
               r"ore\b|foundry|casting|scrap|ferro alloy|billet|ingot|sponge iron|"
               r"stainless|galvanis|wire|pipe|tube"),
    "AUTO": ("AUTO", r"automotive|auto component|automobile|vehicle|tyre|tire|wheel|axle|"
             r"braking|clutch|seating|two[- ]wheeler|passenger car|tractor|bike|scooter|"
             r"auto ancillary|auto parts|emission|ev component"),
    "CAPITAL_GOODS": ("CAPITAL_GOODS", r"engineering|machinery|machine tool|equipment|pump|valve|"
                      r"boiler|transformer|switchgear|electric motor|generator|compressor|"
                      r"bearing|gear|fabrication|structural|capital goods|electrical equipment|"
                      r"crane|conveyor|heat exchanger|industrial product|panel|instrument|"
                      r"hydraulic|pneumatic|wind turbine|solar module|rail system|locomotive|"
                      r"wagon|power cables?|electrical cables?|wire harness|fastener|forging|"
                      r"stamping|mould|die\b"),
    "CEMENT": ("CEMENT", r"cement|clinker|ready mix|rmc\b|concrete"),
    "CONSTRUCTION": ("CONSTRUCTION", r"construction|epc\b|infrastructure|civil|road|highway|"
                     r"bridge|contracting|project execution|turnkey|irrigation|dam\b|"
                     r"metro|railway track|real estate development"),
    "REALTY": ("REALTY", r"real estate|property developer|township|residential project|"
               r"commercial complex|housing project|land bank|rental income|mall"),
    "POWER": ("POWER", r"power generation|electricity|thermal power|hydro power|solar power|"
              r"wind power|renewable|power transmission|power distribution|energy generation|"
              r"captive power|independent power|ipp\b|power plant"),
    "OIL_GAS": ("OIL_GAS", r"crude oil|natural gas|petroleum|refinery|refining|lng|lpg|"
                r"exploration|upstream|downstream|fuel|petro product|lubricant|oil field|"
                r"drilling|gas pipeline"),
    "FMCG": ("FMCG", r"food product|beverage|dairy|edible oil|sugar|tea|coffee|spice|snack|"
             r"fmcg|packaged food|personal care|soap|detergent|shampoo|household product|"
             r"tobacco|cigarette|brewery|distillery|confectionery|bakery|flour|rice|"
             r"cattle feed|animal feed|nutrition"),
    "AGRI": ("AGRI", r"agricultur|agri[- ]|seed|plantation|horticulture|fishing|poultry|"
             r"fertiliser distribution|farm|coir|floriculture"),
    "RETAIL": ("RETAIL", r"retail|showroom|supermarket|e-commerce|franchise|store chain|"
               r"consumer retail|jewellery retail"),
    "CONSUMER_DURABLES": ("CONSUMER_DURABLES", r"air conditioner|refrigerator|appliance|fan\b|"
                          r"furniture|kitchenware|lighting|consumer durable|"
                          r"water heater|mixer|luminaire|sanitary ware"),
    "LEISURE": ("LEISURE", r"hotel|resort|restaurant|hospitality|tourism|amusement|club|"
                r"leisure|catering|banquet|cinema|multiplex"),
    "MEDIA": ("MEDIA", r"media|entertainment|film|broadcast|publishing|newspaper|advertising|"
              r"content production|gaming|ott|radio|printing"),
    "TELECOM": ("TELECOM", r"telecom|telecommunication|spectrum|mobile network|broadband|"
                r"optical fibre|tower infrastructure|5g|subscriber|telecom equipment"),
    "LOGISTICS": ("LOGISTICS", r"logistic|transport|freight|shipping|courier|warehouse|cargo|"
                  r"port\b|container|fleet|supply chain|3pl|last mile|trucking|shipping line"),
    "PACKAGING": ("PACKAGING", r"packaging|carton|corrugated|flexible packaging|bottle|closure|"
                  r"label printing|laminate tube|pouch|cap\b"),
    "DEFENCE": ("DEFENCE", r"defence|defense|aerospace|munition|shipbuilding|radar|missile|"
                r"armament|naval"),
    "PAPER": ("PAPER", r"paper|pulp|jute|timber|plywood|forest|wood|board mill"),
    "JEWELLERY": ("JEWELLERY", r"jewellery|jewelry|diamond|gems|ornament|gold|silver"),
    "EDUCATION": ("EDUCATION", r"education|school|university|training institute|e-learning|"
                  r"edtech|skill development"),
    "UTILITIES": ("UTILITIES", r"water supply|water treatment|gas distribution|utility|"
                  r"sewage|waste management|recycling|city gas"),
    "SERVICES": ("SERVICES", r"staffing|manpower|facility management|security services|"
                 r"consultancy|consulting|trading|distribution|commission|agency|"
                 r"rental|leasing|repair|maintenance|service provider"),
    "DIVERSIFIED": ("DIVERSIFIED", r"conglomerate|multi[- ]business|diversified|multi[- ]segment"),
}

# coarse bucket -> set of labour categories accepted as "same sector"
COARSE_EQUIV = {
    "IT": {"IT"},
    "FINANCE": {"FINANCE"},
    "HEALTHCARE": {"HEALTHCARE"},
    "CHEMICALS": {"CHEMICALS"},
    "TEXTILES": {"TEXTILES"},
    "METALS": {"METALS", "MINING"},
    "AUTO": {"AUTO", "CAPITAL_GOODS"},
    "CAPITAL_GOODS": {"CAPITAL_GOODS", "AUTO"},
    "CEMENT": {"CEMENT", "CONSTRUCTION_MATERIALS", "CONSTRUCTION"},
    "CONSTRUCTION": {"CONSTRUCTION", "CEMENT", "REALTY"},
    "CONSTRUCTION_MATERIALS": {"CEMENT", "CONSTRUCTION_MATERIALS"},
    "REALTY": {"REALTY", "CONSTRUCTION"},
    "POWER": {"POWER", "UTILITIES"},
    "UTILITIES": {"UTILITIES", "POWER", "OIL_GAS"},
    "OIL_GAS": {"OIL_GAS", "ENERGY", "UTILITIES"},
    "FMCG": {"FMCG", "CONSUMER", "AGRI"},
    "AGRI": {"AGRI", "FMCG"},
    "RETAIL": {"RETAIL", "CONSUMER_SERVICES", "FMCG"},
    "CONSUMER_DURABLES": {"CONSUMER_DURABLES", "CONSUMER"},
    "LEISURE": {"LEISURE", "CONSUMER_SERVICES"},
    "MEDIA": {"MEDIA"},
    "TELECOM": {"TELECOM"},
    "LOGISTICS": {"LOGISTICS", "SERVICES"},
    "PACKAGING": {"PACKAGING", "CHEMICALS", "PAPER"},
    "DEFENCE": {"DEFENCE", "CAPITAL_GOODS"},
    "PAPER": {"PAPER", "FOREST"},
    "JEWELLERY": {"JEWELLERY", "CONSUMER_DISCRETIONARY"},
    "EDUCATION": {"EDUCATION", "CONSUMER_SERVICES"},
    "SERVICES": {"SERVICES"},
    "DIVERSIFIED": {"DIVERSIFIED"},
    "CONSUMER_SERVICES": {"CONSUMER_SERVICES", "RETAIL", "LEISURE", "EDUCATION"},
}

GENERIC_LABELS = {
    "diversified", "diversified fmcg", "diversified metals", "services", "consumer services",
    "commercial services & supplies", "other consumer services", "other utilities",
    "industrial products", "industrial manufacturing", "miscellaneous", "general",
    "trading", "distribution", "others", "other", "consumer goods", "commodities",
    "manufacturing", "consumer", "industrials", "materials", "real estate",
    "diversified commercial services", "diversified consumer products",
    "trading & distributors", "other construction materials", "other textile products",
    "other food products", "other agricultural products", "other electrical equipment",
    "other financial services", "other capital market related services",
}

# ---------------------------------------------------------------- NSE mapping
NSE_SECTOR = {
    "Information Technology": "IT",
    "Financial Services": "FINANCE",
    "Healthcare": "HEALTHCARE",
    "HEALTHCARE SERVICES": "HEALTHCARE",
    "Chemicals": "CHEMICALS",
    "Textiles": "TEXTILES",
    "TEXTILES": "TEXTILES",
    "Metals & Mining": "METALS",
    "Automobile and Auto Components": "AUTO",
    "AUTOMOBILE": "AUTO",
    "Capital Goods": "CAPITAL_GOODS",
    "Construction Materials": "CEMENT",
    "Construction": "CONSTRUCTION",
    "CONSTRUCTION": "CONSTRUCTION",
    "Realty": "REALTY",
    "Power": "POWER",
    "Oil Gas & Consumable Fuels": "OIL_GAS",
    "Fast Moving Consumer Goods": "FMCG",
    "CONSUMER GOODS": "FMCG",
    "Consumer Durables": "CONSUMER_DURABLES",
    "Consumer Services": "CONSUMER_SERVICES",
    "Media Entertainment & Publication": "MEDIA",
    "Telecommunication": "TELECOM",
    "Services": "SERVICES",
    "SERVICES": "SERVICES",
    "Utilities": "UTILITIES",
    "Forest Materials": "PAPER",
    "Diversified": "DIVERSIFIED",
}

NSE_INDUSTRY = {
    "AUTO ANCILLARIES": "AUTO", "Auto Components": "AUTO", "Automobiles": "AUTO",
    "Agricultural Commercial & Construction Vehicles": "AUTO",
    "Aerospace & Defense": "DEFENCE",
    "Agricultural Food & other Products": "AGRI",
    "Banks": "FINANCE", "Finance": "FINANCE", "Capital Markets": "FINANCE",
    "Insurance": "FINANCE", "Financial Technology (Fintech)": "FINANCE",
    "Beverages": "FMCG", "Food Products": "FMCG", "Diversified FMCG": "FMCG",
    "Cigarettes & Tobacco Products": "FMCG", "Personal Products": "FMCG",
    "Household Products": "FMCG", "CONSUMER NON DURABLES": "FMCG",
    "CONSTRUCTION": "CONSTRUCTION", "Construction": "CONSTRUCTION",
    "Cement & Cement Products": "CEMENT", "Other Construction Materials": "CEMENT",
    "Chemicals & Petrochemicals": "CHEMICALS", "Fertilizers & Agrochemicals": "CHEMICALS",
    "Commercial Services & Supplies": "SERVICES", "Engineering Services": "CAPITAL_GOODS",
    "Consumable Fuels": "OIL_GAS", "Oil": "OIL_GAS", "Gas": "OIL_GAS",
    "Petroleum Products": "OIL_GAS",
    "Consumer Durables": "CONSUMER_DURABLES",
    "Diversified": "DIVERSIFIED", "Diversified Metals": "METALS",
    "Electrical Equipment": "CAPITAL_GOODS", "Industrial Manufacturing": "CAPITAL_GOODS",
    "Industrial Products": "CAPITAL_GOODS",
    "Entertainment": "MEDIA", "Media": "MEDIA", "Printing & Publication": "MEDIA",
    "Ferrous Metals": "METALS", "Non - Ferrous Metals": "METALS",
    "Metals & Minerals Trading": "METALS", "Minerals & Mining": "METALS",
    "HEALTHCARE SERVICES": "HEALTHCARE", "Healthcare Equipment & Supplies": "HEALTHCARE",
    "Healthcare Services": "HEALTHCARE", "Pharmaceuticals & Biotechnology": "HEALTHCARE",
    "HOTELS/ RESORTS AND OTHER RECREATIONAL ACTIVITIES": "LEISURE",
    "Leisure Services": "LEISURE",
    "IT - Hardware": "IT", "IT - Services": "IT", "IT - Software": "IT",
    "Other Consumer Services": "CONSUMER_SERVICES",
    "Other Utilities": "UTILITIES",
    "Paper Forest & Jute Products": "PAPER",
    "Power": "POWER",
    "Realty": "REALTY",
    "Retailing": "RETAIL",
    "TEXTILES - COTTON": "TEXTILES", "Textiles & Apparels": "TEXTILES",
    "Telecom - Equipment & Accessories": "TELECOM", "Telecom - Services": "TELECOM",
    "Transport Infrastructure": "LOGISTICS", "Transport Services": "LOGISTICS",
}

# ---------------------------------------------------------------- BSE mapping
# BSE's own industry vocabulary is not identical to NSE's; mapped explicitly so
# "Computers - Software" is IT, not Services, and "Telecom - Infrastructure" is
# not read as construction.
BSE_INDUSTRY = {
    "Auto Components & Equipments": "AUTO",
    "Residential, Commercial Projects": "REALTY",
    "Stationary": "PAPER",
    "Coal": "OIL_GAS",
    "Industrial Minerals": "METALS",
    "Holding Company": "DIVERSIFIED",
    "Tour, Travel Related Services": "LEISURE",
    "Seafood": "FMCG",
    "Consumer Electronics": "CONSUMER_DURABLES",
    "Telecom -  Equipment & Accessories": "TELECOM",
    "Telecom - Equipment & Accessories": "TELECOM",
    "Telecom - Infrastructure": "TELECOM",
    "Telecom - Cellular & Fixed line services": "TELECOM",
    "Computers - Software & Consulting": "IT",
    "Software Products": "IT",
    "IT Enabled Services": "IT",
    "Computers Hardware & Equipments": "IT",
    "Film Production, Distribution & Exhibition": "MEDIA",
    "TV Broadcasting & Software Production": "MEDIA",
    "Electronic Media": "MEDIA",
    "Advertising & Media Agencies": "MEDIA",
    "Printing & Publication": "MEDIA",
    "Pharmacy Retail": "RETAIL",
    "Speciality Retail": "RETAIL",
    "Power Trading": "POWER",
    "Power Generation": "POWER",
    "Oil Storage & Transportation": "OIL_GAS",
    "Trading - Metals": "METALS",
    "Precious Metals": "METALS",
    "Aluminium, Copper & Zinc Products": "METALS",
    "Castings & Forgings": "METALS",
    "Sponge Iron": "METALS",
    "Iron & Steel": "METALS",
    "Iron & Steel Products": "METALS",
    "Diversified Metals": "METALS",
    "Medical Equipment & Supplies": "HEALTHCARE",
    "Healthcare Research, Analytics & Technology": "HEALTHCARE",
    "Pharmaceuticals": "HEALTHCARE",
    "Hospital": "HEALTHCARE",
    "Non Banking Financial Company (NBFC)": "FINANCE",
    "Stockbroking & Allied": "FINANCE",
    "Investment Company": "FINANCE",
    "Other Bank": "FINANCE",
    "Logistics Solution Provider": "LOGISTICS",
    "Waste Management": "UTILITIES",
    "Water Supply & Management": "UTILITIES",
    "Commodity Chemicals": "CHEMICALS",
    "Specialty Chemicals": "CHEMICALS",
    "Petrochemicals": "CHEMICALS",
    "Paints": "CHEMICALS",
    "Fertilizers": "CHEMICALS",
    "Pesticides & Agrochemicals": "CHEMICALS",
    "Plastic Products - Consumer": "CHEMICALS",
    "Cement & Cement Products": "CEMENT",
    "Civil Construction": "CONSTRUCTION",
    "Heavy Electrical Equipment": "CAPITAL_GOODS",
    "Other Electrical Equipment": "CAPITAL_GOODS",
    "Packaging": "PACKAGING",
    "Paper & Paper Products": "PAPER",
    "Gems, Jewellery And Watches": "JEWELLERY",
    "Household Appliances": "CONSUMER_DURABLES",
    "Hotels & Resorts": "LEISURE",
    "Education": "EDUCATION",
    "Garments & Apparels": "TEXTILES",
    "Trading - Textile Products": "TEXTILES",
    "Lubricants": "OIL_GAS",
    "Oil Exploration & Production": "OIL_GAS",
    "Sugar": "FMCG",
    "Dairy Products": "FMCG",
    "Animal Feed": "FMCG",
    "Tea & Coffee": "FMCG",
    "Personal Care": "FMCG",
}

BSE_SECTOR = {
    "Industrials": "CAPITAL_GOODS",
    "Financial Services": "FINANCE",
    "Healthcare": "HEALTHCARE",
    "Energy": "OIL_GAS",
    "Utilities": "UTILITIES",
    "Telecommunication": "TELECOM",
    "Information Technology": "IT",
    "Materials": "MATERIALS",
    "Commodities": "COMMODITIES",
    "Consumer Discretionary": "CONSUMER_DISCRETIONARY",
    "Consumer Staples": "FMCG",
    "Fast Moving Consumer Goods": "FMCG",
    "Consumer": "CONSUMER",
    "Services": "SERVICES",
    "Diversified": "DIVERSIFIED",
    "Real Estate": "REALTY",
    "Communication Services": "MEDIA",
    "Manufacturing": "MANUFACTURING",
}

# Multi-word business terms checked BEFORE the broad FAMILIES regexes, so a
# "steel structures" maker is not filed under steelmaking and "critical power"
# is not filed under telecom.
SEGMENT_TERMS = [
    (r"critical power|power supply|uninterruptible|ups\b|inverter|charger|charging|"
     r"battery pack|power systems?", "CAPITAL_GOODS"),
    (r"steel structures?|fabricat|structurals?|engineering goods?|machine building", "CAPITAL_GOODS"),
    (r"bearing|bushings?|thrust washer|piston rings?", "AUTO"),
    (r"stationery|writing instrument|notebook", "PAPER"),
    (r"content publishing|publishing|print media", "MEDIA"),
    (r"sez\b|special economic zone|realty|property", "REALTY"),
    (r"learning solutions?|edtech|education", "EDUCATION"),
    (r"water treatment|ion exchange|membrane|water solution", "UTILITIES"),
    (r"logistics|warehous|supply chain", "LOGISTICS"),
    (r"diagnostic|patholog|hospital", "HEALTHCARE"),
    (r"securities|broking|capital market|investment", "FINANCE"),
    (r"digital operations?|digital technologies?|digital experiences?|it services?|"
     r"business process management|technology services", "IT"),
    (r"engineering products?|process equipment|heat exchangers?|ejectors?|"
     r"vacuum systems?", "CAPITAL_GOODS"),
    (r"retail banking|corporate banking|treasury|banking services", "FINANCE"),
    (r"toll|annuity|road assets?|highway concession|concession", "LOGISTICS"),
    (r"^train\b|^flight\b|^bus\b|ticketing|airline", "LEISURE"),
    (r"^retail\b|retail segment|retail chain", "RETAIL"),
    (r"lubricants?|specialty oils?|greases?", "OIL_GAS"),
    (r"packaging", "PACKAGING"),
    (r"watch components?|watches|bracelet|jewellery", "JEWELLERY"),
]


def segment_family(name: str):
    """Best family for one segment name (multi-word terms first)."""
    for pattern, fam in SEGMENT_TERMS:
        if re.search(pattern, name, re.I):
            return fam
    fams = family_hits(name)
    if not fams:
        fams = text_signals(name)
    if not fams:
        return None
    return max(fams, key=lambda f: (fams[f], len(f)))


_COMPILED = {k: (v[0], re.compile(r"\b(?:" + v[1] + r")\b", re.I)) for k, v in FAMILIES.items()}

# Stricter signals for free text: boilerplate words (finance cost, transport of
# goods, product portfolio) must not decide the business.  Only distinctive
# industry terms count.
TEXT_SIGNALS = {
    "FINANCE": r"\b(?:nbfc|non[- ]banking financial|bank|banking|insurance|broking|"
               r"merchant banking|mutual fund|housing finance|microfinance|lending|"
               r"loan book|investment company|securities? (?:market|trading)|"
               r"capital market|asset management|deposits?|dealing in shares|"
               r"shares, debentures|debentures and securities)\b",
    "IT": r"\b(?:software|information technology|it services|saas|digital transformation|"
          r"technology services|data cent(?:er|re)|cloud|it consultancy|"
          r"business process management|digital operations?|digital solutions?)\b",
    "HEALTHCARE": r"\b(?:pharma\w*|formulations?|hospitals?|diagnostics?|"
                  r"active pharmaceutical|medical devices?|medical equipment|dental|"
                  r"otc|balms?|pain relief|analgesic|lozenges|health supplements?|"
                  r"healthcare)\b",
    "CHEMICALS": r"\b(?:chemicals?|dyes?|pigments?|specialty chem\w*|fertilis\w*|fertiliz\w*|"
                 r"agrochem\w*|pesticid\w*|caustic soda|soda ash|resins?|polymers?|paints?|"
                 r"camphor|menthol|fragrances?|coatings?)\b",
    "TEXTILES": r"\b(?:textiles?|yarn|fabrics?|garments?|apparel|cotton|denim|spinning|"
                r"weaving|hosiery)\b",
    "METALS": r"\b(?:steel|aluminium|aluminum|copper|zinc|ferro alloys?|iron ore|billets?|"
              r"ingots?|sponge iron|foundry|castings?|rolled products?|stainless|bentonite|"
              r"minerals?|mining)\b",
    "AUTO": r"\b(?:automotive|auto components?|automobiles?|two[- ]wheelers?|tyres?|tires?|"
            r"axles?|brakes?|clutch\w*|auto parts?|piston rings?|engine bearings?|bushings?|"
            r"thrust washers?|instrument clusters?|driver information|passenger vehicles?|"
            r"commercial vehicles?|oems?)\b",
    "CAPITAL_GOODS": r"\b(?:capital goods|machinery|machine tools?|pumps?|valves?|boilers?|"
                     r"transformers?|switchgear|compressors?|bearings?|gears?|cranes?|"
                     r"conveyors?|electrical equipment|engineering goods?|locomotives?|wagons?|"
                     r"generators?|electric motors?|heavy electrical|hoists?|material handling)\b",
    "CEMENT": r"\b(?:cement|clinker|ready[- ]mix concrete)\b",
    "CONSTRUCTION": r"\b(?:construction|epc|infrastructure projects?|civil works?|highways?|"
                    r"bridges?|roads?)\b",
    "REALTY": r"\b(?:real estate|property development|townships?|residential projects?|"
              r"commercial projects?|residential|commercial complex|land bank)\b",
    "POWER": r"\b(?:power generation|power plant\w*|electricity|solar power|wind power|"
             r"thermal power|renewable energy|power distribution|transmission lines?|"
             r"power trading|power supplies)\b",
    "OIL_GAS": r"\b(?:crude oil|natural gas|petroleum|refiner\w*|lng|lpg|oil and gas|"
               r"exploration and production|specialty oils?|lubricants?|greases?|coal|"
               r"oil storage|oil terminal)\b",
    "FMCG": r"\b(?:food products?|beverages?|dairy|edible oil|sugar|tea|coffee|spices?|"
            r"snacks?|fmcg|personal care|detergents?|soaps?|tobacco|cigarettes?|"
            r"nutrition|premix\w*)\b",
    "AGRI": r"\b(?:agricultur\w*|seeds?|plantations?|horticulture|poultry|animal feed)\b",
    "RETAIL": r"\b(?:retail\w*|showrooms?|supermarkets?|e-commerce)\b",
    "CONSUMER_DURABLES": r"\b(?:consumer durables?|air conditioners?|refrigerators?|appliances?|"
                         r"furniture|kitchenware|watches|water purifiers?|vacuum cleaners?)\b",
    "LEISURE": r"\b(?:hotels?|resorts?|restaurants?|hospitality|tourism|travel|tours?|"
                r"ticketing|booking platform)\b",
    "MEDIA": r"\b(?:media|entertainment|films?|broadcast\w*|cable television|"
              r"television broadcasting|publishing|advertising|ott)\b",
    "TELECOM": r"\b(?:telecom\w*|spectrum|broadband|optical fibre|5g|subscribers?)\b",
    "LOGISTICS": r"\b(?:logistics|freight|shipping|courier|warehous\w*|cargo|ports?|"
                 r"supply chain|transport services?|toll|annuity|concession|bots?)\b",
    "PACKAGING": r"\b(?:packaging|cartons?|corrugated|closures?|bottles?|fibc|woven sacks?|"
                 r"hdpe|polypropylene|flexible packaging)\b",
    "DEFENCE": r"\b(?:defence|defense|aerospace|munitions?|shipbuilding|radar|missiles?)\b",
    "PAPER": r"\b(?:paper|pulp|jute|plywood|timber)\b",
    "JEWELLERY": r"\b(?:jewellery|jewelry|diamonds?|gems?|watch components?)\b",
    "EDUCATION": r"\b(?:education|schools?|universit\w*|edtech)\b",
    "UTILITIES": r"\b(?:water supply|water treatment|water and wastewater|wastewater|"
                 r"sewage treatment|stps?|gas distribution|city gas|waste management|recycling)\b",
    "SERVICES": r"\b(?:staffing|manpower|facility management|security services|consultanc\w*|"
                r"trading (?:segment|business|of|activity)|trading house|distributors?)\b",
}
_TXT = {k: re.compile(v, re.I) for k, v in TEXT_SIGNALS.items()}


def text_signals(body: str) -> dict:
    """Distinctive-term hit counts for free text."""
    out = {}
    for fam, rx in _TXT.items():
        n = len(rx.findall(body))
        if n:
            out[fam] = n
    return out


def family_of_label(text: str):
    """Map one exchange label string to a family, or None when unknown/generic."""
    if not text:
        return None
    t = text.strip()
    if t in NSE_INDUSTRY:
        return NSE_INDUSTRY[t]
    if t in NSE_SECTOR:
        return NSE_SECTOR[t]
    if t in BSE_INDUSTRY:
        return BSE_INDUSTRY[t]
    if t in BSE_SECTOR:
        return BSE_SECTOR[t]
    low = t.lower()
    if low in GENERIC_LABELS:
        return None
    best, best_len = None, 0
    for fam, (_, rx) in _COMPILED.items():
        for m in rx.finditer(t):
            if len(m.group(0)) > best_len:
                best, best_len = fam, len(m.group(0))
    return best


def family_hits(text: str):
    """All (family, count) keyword hits in a free-text business description."""
    out = {}
    for fam, (_, rx) in _COMPILED.items():
        n = len(rx.findall(text))
        if n:
            out[fam] = n
    return out


def coarse(family):
    return FAMILIES.get(family, (family, ""))[0]


# NSE-level sector parents: a label naming the parent is right at sector level
# for the child business (e.g. "Consumer Services" for a retailer).
SECTOR_PARENT = {
    "RETAIL": "CONSUMER_SERVICES", "LEISURE": "CONSUMER_SERVICES",
    "EDUCATION": "CONSUMER_SERVICES", "SERVICES": "SERVICES",
    "LOGISTICS": "SERVICES", "CONSUMER_SERVICES": "CONSUMER_SERVICES",
    "CEMENT": "CONSTRUCTION_MATERIALS", "MINING": "METALS",
    "AGRI": "FMCG",
}


def same_sector(a, b):
    ca, cb = coarse(a), coarse(b)
    if ca == cb:
        return True
    return SECTOR_PARENT.get(ca) == cb or SECTOR_PARENT.get(cb) == ca


def is_generic(text: str) -> bool:
    return (text or "").strip().lower() in GENERIC_LABELS
