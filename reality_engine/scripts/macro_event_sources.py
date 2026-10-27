"""Record web/internal verification of macro_events rows that have no source document.

Creates ``macro_event_sources`` in equity_intelligence.db (one row per event x source) and upserts the
2026-10-28 verification of the four event_graph.py fixture events. Source rows are never modified.

    python -m reality_engine.scripts.macro_event_sources
"""
import sqlite3

from reality_engine import config

DDL = """
CREATE TABLE IF NOT EXISTS macro_event_sources (
    event_id            TEXT NOT NULL,
    claim               TEXT NOT NULL,          -- what the macro_events row asserts
    verdict             TEXT NOT NULL CHECK (verdict IN ('confirmed','partly_confirmed','contradicted','unverified')),
    verified_facts      TEXT,                   -- what the source actually says
    discrepancies       TEXT,                   -- where the stored row differs from the source
    source_url          TEXT NOT NULL,
    source_title        TEXT,
    publisher           TEXT,
    source_class        TEXT CHECK (source_class IN ('official','internal_official_doc','major_press','secondary','none')),
    robustness          TEXT CHECK (robustness IN ('high','medium','low','none')),
    internal_doc_id     INTEGER,                -- raw_documents.doc_id when the source is already held
    internal_policy_event_id INTEGER,           -- policy_events.id when a sourced row exists
    checked_at          TEXT NOT NULL,
    checked_by          TEXT NOT NULL,
    PRIMARY KEY (event_id, source_url)
)
"""

CHECKED_AT = "2026-10-28"
BY = "claude (web search + internal policy_events)"

STEEL = ("STEEL_SAFEGUARD_DUTY", "12% safeguard duty on steel imports, effective 2025-04-21; exceptions: stainless/specialty grades")
STEEL_FACTS = ("12% provisional safeguard duty on non-alloy and alloy flat steel products (HR, CR, metallic- and colour-coated), "
               "Ministry of Finance gazette notification 21 Apr 2025, 200 days, on imports below CIF thresholds of $675-964/t. "
               "Made definitive for 3 years (notice 30 Dec 2025), retrospective from 21 Apr 2025: 12% to 20 Apr 2026, "
               "11.5% to 20 Apr 2027, 11% to 20 Apr 2028.")
STEEL_DIFF = ("Stored text says 'steel imports'; the duty covers flat products only. Stainless/electrical/tinplate exclusion "
              "is confirmed for the definitive measure's scope, not explicitly for the April provisional notification. "
              "Country scope is reported inconsistently (China/Vietnam vs all except developing countries). "
              "Official gazette text not yet fetched into our store.")

RAIL = ("RAIL_CAPEX_PUSH", "Rail capex outlay +9% YoY in Union Budget 2026-27 (2026-02-01); Vande Bharat/Kavach prioritised")
RAIL_FACTS = ("Union Budget 2026-27 (1 Feb 2026): railway capital expenditure (budgetary support) about Rs 2.77 lakh crore, "
              "+9.9% over FY26 RE of Rs 2.52 lakh crore; total incl. other sources Rs 2.92-2.93 lakh crore. Reported growth "
              "ranges 5.4%-10% depending on the base (BE vs RE, budgetary support vs total).")
RAIL_DIFF = ("9% sits inside the reported 5.4-10% range (closest: 9.9% budgetary support vs FY26 RE). The 'Vande Bharat/"
             "Kavach prioritised' channel is not verified. Our store holds the Budget at a Glance (doc 12405) but only "
             "line items were extracted (rolling stock 52,109 cr, signalling & telecom 7,500 cr), not the total.")

NUC = ("NUCLEAR_MISSION", "Nuclear Energy Mission, 100 GW by 2047, incentives conditional on private participation, effective 2026-04-01")
NUC_FACTS = ("Union Budget 2025-26 speech (1 Feb 2025): Nuclear Energy Mission for R&D of Small Modular Reactors with a "
             "Rs 20,000 crore outlay; at least 5 indigenous SMRs operational by 2033; at least 100 GW nuclear by 2047; "
             "amendments to the Atomic Energy Act and the Civil Liability for Nuclear Damage Act for private participation.")
NUC_DIFF = ("Stored event_date 2026-04-01 is wrong: announced 2025-02-01. The stored 'relief 1%' has no basis. The Rs 20,000 "
            "crore / 5 SMRs by 2033 facts are missing from the stored row.")

TEX = ("US_TARIFF_TEXTILE_RELIEF", "US 30% tariff reduction on Indian textiles, effective 2026-04-01; exceptions dyes and yarn; conditional on setting up a US manufacturing plant")
TEX_FACTS = ("Real event: India-US interim trade framework announced early Feb 2026. US tariffs on Indian goods cut from 50% "
             "(25% reciprocal + 25% Russia-oil penalty) to an 18% reciprocal rate; the Russia-linked 25% removed effective "
             "7 Feb 2026; applies across textile products; some silk lines at 0%. Before that, 50% US tariffs had applied "
             "since Aug 2025 (RBI MPC minutes, policy_events 21769).")
TEX_DIFF = ("No source found for the stored 30% figure, the 2026-04-01 date, the dyes/yarn exceptions or the US-plant "
            "condition. They match the example fixture in processing/event_graph.py (_SUPPLY_CHAIN_FIXTURES), not any "
            "filing. The real cut was 50% -> 18% from 7 Feb 2026. Official US text (White House order / USTR) not yet fetched.")

ROWS = [
    # event, claim, verdict, facts, diff, url, title, publisher, class, robustness, doc_id, policy_event_id
    (*STEEL, "confirmed", STEEL_FACTS, STEEL_DIFF,
     "https://www.spglobal.com/commodity-insights/en/news-research/latest-news/metals/042125-india-imposes-12-safeguard-duty-on-flat-steel-imports-for-200-days",
     "India imposes 12% safeguard duty on flat steel imports for 200 days", "S&P Global Commodity Insights", "major_press", "high", None, None),
    (*STEEL, "confirmed", STEEL_FACTS, STEEL_DIFF,
     "https://www.business-standard.com/markets/news/tata-steel-sail-jsl-gain-up-to-3-after-govt-imposes-safeguard-duty-125042200194_1.html",
     "Tata Steel, SAIL, JSL gain after govt imposes safeguard duty", "Business Standard", "major_press", "high", None, None),
    (*STEEL, "confirmed", STEEL_FACTS, STEEL_DIFF,
     "https://www.argusmedia.com/en/news-and-insights/latest-market-news/2770881-india-extends-import-duties-on-flat-steel-to-3-years",
     "India extends import duties on flat steel to 3 years", "Argus Media", "major_press", "high", None, None),
    (*STEEL, "confirmed", STEEL_FACTS, STEEL_DIFF,
     "https://www.theweek.in/wire-updates/business/2025/04/21/del99-biz-ld-steel-safeguard-duty.html",
     "Govt imposes 12 pc safeguard duty on certain steel products for 200 days (PTI)", "The Week / PTI", "major_press", "medium", None, None),

    (*RAIL, "partly_confirmed", RAIL_FACTS, RAIL_DIFF,
     "https://www.business-standard.com/budget/news/indian-railways-record-capex-fy27-high-speed-rail-freight-corridor-126020100735_1.html",
     "Budget 2026: Indian Railways to see record capex of Rs 2.92 trillion in FY27", "Business Standard", "major_press", "high", None, None),
    (*RAIL, "partly_confirmed", RAIL_FACTS, RAIL_DIFF,
     "https://www.newsonair.gov.in/union-budget-2026-27-allocates-record-%e2%82%b92-78-lakh-crore-for-railways-says-minister-ashwini-vaishnaw",
     "Union Budget 2026-27 allocates record Rs 2.78 lakh crore for Railways (Minister)", "All India Radio (Prasar Bharati)", "official", "high", None, None),
    (*RAIL, "partly_confirmed", RAIL_FACTS, RAIL_DIFF,
     "https://www.indiabudget.gov.in/doc/Budget_at_Glance/budget_at_a_glance.pdf",
     "Union Budget FY2026-27 - Budget at a Glance", "Ministry of Finance", "internal_official_doc", "high", 12405, None),
    (*RAIL, "partly_confirmed", RAIL_FACTS, RAIL_DIFF,
     "https://www.angelone.in/news/economy/union-budget-2026-indian-railways-gets-allocated-2-93-lakh-crore-capex-up-5-4",
     "Union Budget 2026: Indian Railways gets Rs 2.93 lakh crore capex, up 5.4%", "Angel One", "secondary", "medium", None, None),

    (*NUC, "partly_confirmed", NUC_FACTS, NUC_DIFF,
     "https://www.indiabudget.gov.in/doc/bspeech/bs2025_26.pdf",
     "Union Budget 2025-26 Speech", "Ministry of Finance", "internal_official_doc", "high", 64, 563),
    (*NUC, "partly_confirmed", NUC_FACTS, NUC_DIFF,
     "https://static.pib.gov.in/WriteReadData/specificdocs/documents/2025/feb/doc202521492801.pdf",
     "PIB Budget 2025-26 highlights", "Press Information Bureau", "internal_official_doc", "high", 78, 3826),
    (*NUC, "partly_confirmed", NUC_FACTS, NUC_DIFF,
     "https://world-nuclear-news.org/articles/indian-budget-launches-nuclear-energy-mission",
     "Indian budget launches Nuclear Energy Mission", "World Nuclear News", "major_press", "high", None, None),

    (*TEX, "contradicted", TEX_FACTS, TEX_DIFF,
     "https://www.newsonair.gov.in/fieo-welcomes-finalisation-of-india-us-trade-deal/",
     "FIEO welcomes finalisation of India-US trade deal (3 Feb 2026)", "All India Radio (Prasar Bharati)", "official", "high", None, None),
    (*TEX, "contradicted", TEX_FACTS, TEX_DIFF,
     "https://www.newsonair.gov.in/textile-sector-hails-interim-trade-agreement-between-india-us",
     "Textile sector hails interim trade agreement between India-US (18 Feb 2026)", "All India Radio (Prasar Bharati)", "official", "high", None, None),
    (*TEX, "contradicted", TEX_FACTS, TEX_DIFF,
     "https://www.india-briefing.com/news/india-us-trade-deal-tariff-cut-export-investment-outlook-2026-2-42367.html/",
     "India-US Trade Deal Cuts Tariffs, Lifts Export Outlook", "India Briefing (Dezan Shira)", "secondary", "medium", None, None),
    (*TEX, "contradicted", TEX_FACTS, TEX_DIFF,
     "internal:policy_events/21769",
     "US 50% tariffs on Indian exports since Aug 2025 (RBI MPC minutes)", "Reserve Bank of India", "internal_official_doc", "high", 12789, 21769),
]

RIPPLE_CLAIM = "ripple_effects rows for this event: transmission elasticity, raw magnitude, probability and lag"
RIPPLE_DIFF = ("Assigned by hand in the processing/event_graph.py example fixture; no source exists for these numbers. "
               "The event's existence is a separate question (see the other rows for this event_id).")


def main():
    conn = sqlite3.connect(config.DB_PATH, timeout=60)
    conn.execute("PRAGMA busy_timeout=60000")
    with conn:
        conn.execute(DDL)
        for r in ROWS:
            conn.execute("INSERT OR REPLACE INTO macro_event_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (*r, CHECKED_AT, BY))
        for (event_id, n) in conn.execute(
                "SELECT event_id, COUNT(*) FROM ripple_effects WHERE event_id IN (?,?,?,?) GROUP BY 1",
                (STEEL[0], RAIL[0], NUC[0], TEX[0])).fetchall():
            conn.execute("INSERT OR REPLACE INTO macro_event_sources VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                         (event_id, f"{RIPPLE_CLAIM} ({n} rows)", "unverified", None, RIPPLE_DIFF,
                          f"internal:ripple_effects/{event_id}", None, None, "none", "none", None, None, CHECKED_AT, BY))
    for row in conn.execute("SELECT event_id, verdict, COUNT(*), GROUP_CONCAT(robustness) FROM macro_event_sources GROUP BY 1, 2"):
        print(row)


if __name__ == "__main__":
    main()
