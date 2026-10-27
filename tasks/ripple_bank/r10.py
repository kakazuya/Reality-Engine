"""R10 — information leakage: a delivery spike or position build in the 4 sessions before day 0.

Day 0 follows the 2026-10-27 rule (NEXT_SESSIONS_PLAN): a filing disseminated before 15:30 IST on session T
has day 0 = T; a filing at or after 15:30 has day 0 = the next session. The leakage window is the 4 sessions
BEFORE day 0. The question is always who moved first, and whether that is evidence or coincidence.
"""

from _lib import R, H, T

EV = "the event (known_at)"


def hops(event, ev_evidence, store_hop):
    return [
        H(event, "day 0 session",
          "the 3:30 rule maps the dissemination timestamp to a session; a post-15:30 filing belongs to the next day",
          "up", "0-1 session",
          "event_day0(known_at, day0_session, timing_bucket, rule); no table applies the rule today",
          "partial", "day0_session"),
        H("day 0", "the 4 sessions before day 0",
          "the window is built backwards from the session; a forward window from the announcement is a different test",
          "mixed", "-4 to -1 sessions",
          "event_leakage_window(sessions_before_day0); daily_price_delivery",
          "partial", "leakage_window"),
        H("the window", "the footprint",
          "a delivery spike is only a footprint against the stock's own floor; a busy day is not leakage",
          "up", "same session",
          "daily_price_delivery(delivery_pct, delivery_spike_ratio); " + store_hop,
          "yes", None),
        H("the footprint", "a named actor",
          "only filings name an actor: insider trades, bulk and block deals, pledge and SAST disclosures",
          "mixed", "0-1q",
          "insider_trades_v2(known_at); bulk_block_deals(client_name); corporate_documents",
          "partial", "leakage_window"),
    ]


ROWS = [

R("R10-01",
  "A bulk deal printed on POLYCAB on 14 Jan 2026 — the same session as its largest delivery spike of the year. "
  "Take day 0 as the deal session, look at the 4 sessions before it, and say who was in the tape before the "
  "block and whether the delivery pattern differs from the rest of January.",
  ["POLYCAB"],
  hops("bulk deal", "deal tape", "bulk_block_deals(deal_type, quantity, trade_price)"),
  ["a bulk deal has no 3:30 rule; the session is the event, so day 0 = the deal date",
   "the window is the 4 sessions BEFORE the deal, not the 4 after",
   "compare the delivery spike with the stock's own floor; 14 Jan is a real spike of 4.68x",
   "name the client only from bulk_block_deals, never from the price action"],
  T("market_series", "deal tape + delivery", True, ""),
  as_of="2026-01-14",
  gt="POLYCAB 14-Jan-2026: delivery 62.89%, delivery-spike ratio 4.68x, price -3.06%. Three POLYCAB bulk "
     "deals print between 2026-01-14 and 2026-03-18. The 2026-01-05 session is also 4.32x, so January 2026 "
     "was a sustained accumulation period, not a one-day event.",
  gt_query="SELECT date, delivery_pct, delivery_spike_ratio, change_pct FROM daily_price_delivery WHERE "
           "symbol='POLYCAB' AND date>='2026-01-01' ORDER BY delivery_spike_ratio DESC LIMIT 5; "
           "SELECT COUNT(*), MIN(deal_date), MAX(deal_date) FROM bulk_block_deals WHERE symbol='POLYCAB' "
           "AND deal_date>='2026-01-01'"),

R("R10-02",
  "KEI held its earnings call on 4 Aug 2026. Apply the 3:30 rule to the call intimation and to the results "
  "filing separately, then compare the 4 sessions before each day 0 with the 20 sessions before that.",
  ["KEI"],
  hops("results filing / call intimation", "corporate_documents", "corporate_documents(known_at)"),
  ["the filing and the call intimation are two events with two known_at values",
   "a call intimation before 15:30 and a results filing after it give two different day-0s",
   "the base rate must be the same stock's own history, not the market's"],
  T("company_disclosure", "results filing and call intimation", True, ""),
  as_of="2026-08-04",
  gt="KEI's most recent concall document in corporate_documents is dated 2026-08-04; that is the latest "
     "call date held, so the window can be built but the next quarter cannot yet.",
  gt_query="SELECT MAX(call_date) FROM corporate_documents WHERE symbol='KEI' AND doc_type LIKE '%concall%'"),

R("R10-03",
  "Take BEL's most recent order-win filing. If it was stamped after 15:30 IST, day 0 is the next session; if "
  "before, it is the same session. Which of the 4 sessions before day 0 carried an unusual delivery share?",
  ["BEL"],
  hops("order-win filing", "corporate_documents", "corporate_documents(known_at)"),
  ["the dissemination timestamp decides day 0; the date alone does not",
   "the announcement session itself is not in the leakage window when the filing is post-close",
   "the order value and the delivery must be independent evidence"],
  T("company_disclosure", "order-win exchange filing", True, ""),
  as_of="2026-10-23"),

R("R10-04",
  "Take FIVESTAR's most recent rating action. Both the agency release and the company disclosure have a "
  "timestamp; use the earlier one for day 0, then test whether the 4 sessions before it show accumulation.",
  ["FIVESTAR"],
  hops("rating action", "corporate_documents", "corporate_documents(known_at)"),
  ["the earlier of the agency release and the company disclosure is the known_at",
   "a rating action rarely leaks into the tape; a flat window is a finding, not a failure",
   "state the agency and the action, not just 'downgrade'"],
  T("company_disclosure", "rating agency release", True, ""),
  as_of="2026-10-23"),

R("R10-05",
  "DIVISLAB announced a capex programme on its earnings call. The transcript is usable only when it is "
  "published, not when the call happened. Build day 0 from the publication time and check the 4 sessions "
  "before it.",
  ["DIVISLAB"],
  hops("capex announcement", "concall_facts.cc_items", "concall_facts.cc_items(known_at)"),
  ["the call time and the transcript publication time are different known_at values",
   "use the later of the two for the text, because the text was not public earlier",
   "a capex statement is a company statement, not a filed contract"],
  T("company_disclosure", "earnings call transcript", True, ""),
  as_of="2026-10-14"),

R("R10-06",
  "A large steel group announces an acquisition outside trading hours. Work out which session is day 0 when "
  "the announcement is not on a trading day, then build the 4-session window that precedes it.",
  ["JSWSTEEL"],
  hops("acquisition announcement", "corporate_documents", "corporate_documents(bse_dissem_ts)"),
  ["a non-session announcement puts day 0 on the next session, and the four before it are the last four sessions",
   "the scheme document is filed later and is not usable earlier",
   "four sessions is not four calendar days"],
  T("company_disclosure", "acquisition announcement", True, ""),
  as_of="2026-09-30"),

R("R10-07",
  "Take HAL's most recent management-change filing. Build day 0 from its dissemination timestamp and check "
  "the 4 sessions before it. What does the filing actually name — the person, the role, and the date?",
  ["HAL"],
  hops("management change", "corporate_documents", "corporate_documents(known_at)"),
  ["the disclosure time is on the filing, not on the news article that repeated it",
   "a KMP change is a dated event, but there is no person-role table to join it to",
   "name the person only from the filing"],
  T("company_disclosure", "Reg-30 management-change filing", True, ""),
  as_of="2026-09-30"),

R("R10-08",
  "The US tariff on shrimp-class exports is in policy_events with its own published_at. Build day 0 for the "
  "Indian exporter from that timestamp and ask whether a 4-session window before an overnight policy is "
  "evidence of anything at all.",
  ["APEX"],
  hops("tariff announcement", "policy_events", "policy_events(published_at)"),
  ["a policy published abroad has a publication time in our row; use it",
   "an overnight event has a window only if someone knew earlier; the rubric must allow 'no leak possible'",
   "there is no tariff-exposure table, so the revenue share is an inference"],
  T("policy", "policy_events.id=21769 US tariffs on labour-intensive exports", True, ""),
  as_of="2026-02-20"),

R("R10-09",
  "The Union Budget speech is delivered inside the session, so day 0 is the speech session. Build the 4 "
  "sessions before it for the textile names and say whether positioning before a scheduled event is leakage "
  "or expectation.",
  ["KPRMILL", "ARVIND"],
  hops("budget speech", "policy_events", "policy_events(published_at)"),
  ["a scheduled event is not a leak; the window can only show positioning",
   "the budget documents are published after the speech and are not usable at the speech",
   "the rubric must label the window as expectation, not information"],
  T("policy", "policy_events budget rows (quote_ok=1)", True, ""),
  as_of="2026-02-01"),

R("R10-10",
  "The MPC statement is published before the close. Build day 0 for a bank from its timestamp, then check "
  "whether the 4 sessions before it contain anything a rule could call leakage.",
  ["HDFCBANK", "ICICIBANK"],
  hops("MPC statement", "policy_events", "policy_events(published_at)"),
  ["a scheduled policy is the least leak-prone event in the calendar; use it as the control",
   "the statement's own timestamp is the known_at, not the meeting date",
   "no market series carries a pre-positioning flag"],
  T("policy", "policy_events.id=21732 repo +25 bps on 2026-10-07", True, ""),
  as_of="2026-10-07"),

R("R10-11",
  "An index provider announces an inclusion and an effective date. That is two day-0s. Build both 4-session "
  "windows and say which one can show leakage and which one can only show flow.",
  ["CGPOWER"],
  hops("index inclusion", "corporate_documents", "corporate_documents(known_at)"),
  ["the announcement and the effective date are separate events",
   "passive flow happens at the effective date, so that window is flow, not information",
   "index_membership is one snapshot and cannot date the change"],
  T("market_series", "index circular", True, ""),
  as_of="2026-09-30"),

R("R10-12",
  "A PLI approval appears in a ministry release and later in the company's own disclosure. Take the earlier "
  "known_at for day 0 and ask whether the 4 sessions before it show accumulation.",
  ["AMBER"],
  hops("PLI approval", "policy_events", "policy_events(published_at)"),
  ["the ministry release and the company disclosure are two events with two times",
   "the approval is not the disbursement; the cash comes later",
   "an approval is a document, so the date must come from it"],
  T("policy", "policy_events scheme rows (quote_ok=1)", True, ""),
  as_of="2026-09-30"),

R("R10-13",
  "A demerger scheme is filed with the exchanges. The board approval and the filing are two candidate day-0s. "
  "Build both windows and say which one a leaker would have acted on.",
  ["GRASIM"],
  hops("scheme filing", "corporate_documents", "corporate_documents(bse_dissem_ts)"),
  ["the earlier of board approval and filing is the one that can leak",
   "a scheme is a document with a stamp; use the stamp",
   "a non-trading-day filing shifts day 0 to the next session"],
  T("company_disclosure", "scheme of arrangement filing", True, ""),
  as_of="2026-09-30"),

R("R10-14",
  "A company announces a stock split, which has no cash effect. Build day 0 and check the 4 sessions before "
  "it. This is the negative control: how often does a delivery spike appear before an event that cannot "
  "carry information?",
  ["KEI"],
  hops("split announcement", "corporate_actions", "corporate_actions(ex_date, broadcast_date)"),
  ["a mechanical event is the control; a spike here is noise",
   "the ex-date and the announcement date are different events",
   "report the control's base rate next to the event's"],
  T("market_series", "corporate action", True, ""),
  as_of="2026-09-30"),

R("R10-15",
  "Take APLAPOLLO's most recent pledge disclosure. Build day 0 from the dissemination timestamp and check the "
  "4 sessions before it for distribution rather than accumulation.",
  ["APLAPOLLO"],
  hops("pledge disclosure", "shareholding", "shareholding(broadcast_at, promoter_pledged_pct)"),
  ["a pledge invocation is a disclosure with a time",
   "the pledge store has no quantity and only 40 rows, so the size cannot be stated",
   "the direction of the pre-window is part of the answer, not an assumption"],
  T("company_disclosure", "pledge disclosure", True, ""),
  as_of="2026-10-23"),

R("R10-16",
  "A tax or regulatory demand order is uploaded to the exchange. Build day 0, check the 4 sessions before it, "
  "and say which document in the store actually contains the order and the amount.",
  ["JKPAPER"],
  hops("tax order", "bse_announcements", "bse_announcements(ann.dissemination_time, attachment)"),
  ["the announcement metadata is held but the attachment text is not extracted",
   "the amount must come from the order, not the headline",
   "a demand order is a contingent liability, not a cash outflow"],
  T("company_disclosure", "exchange announcement", True, ""),
  as_of="2026-10-23"),

R("R10-17",
  "Take ORIENTPPR's most recent auditor change. Build day 0 and check the 4 sessions before it. An auditor "
  "resignation should not leak, which makes it a second control.",
  ["ORIENTPPR"],
  hops("auditor change", "corporate_documents", "corporate_documents(known_at)"),
  ["the reason is in the attachment, which is not extracted",
   "the filing time decides day 0; the reason decides whether the event is material",
   "a resignation and an auditor-opinion qualification are different events"],
  T("company_disclosure", "auditor resignation filing", True, ""),
  as_of="2026-09-30"),

R("R10-18",
  "Take APARINDS' largest insider sale in insider_trades_v2. The intimation date gives day 0; check the 4 "
  "sessions before it and say whether the sale itself was the information or the response to it.",
  ["APARINDS"],
  hops("insider sale", "insider_trades_v2", "insider_trades_v2(intimation_date, known_at, qty, value_inr)"),
  ["an insider filing is disclosed after the trade, so the trade date and the intimation date differ",
   "use the intimation date for day 0 and the trade date for the window",
   "the sale could be diversification; the rubric must allow that"],
  T("market_series", "insider filings", True, ""),
  as_of="2026-10-23"),

R("R10-19",
  "A company cuts its guidance on the call and the transcript is published later. Build day 0 from the "
  "publication, then check the 4 sessions before it. Which document carries the cut?",
  ["KPITTECH"],
  hops("guidance cut", "concall_facts.cc_items", "concall_facts.cc_items(known_at)"),
  ["a guidance cut has no filing; the transcript is the document",
   "the transcript is usable only at its publication time",
   "a cut in guidance and a cut in the reported number are different events"],
  T("company_disclosure", "earnings call transcript", True, ""),
  as_of="2026-10-14"),

R("R10-20",
  "A buyback is announced after the close, so day 0 is the next session. Check the 4 sessions before it: is "
  "the pre-window evidence of a leak, or of price support before a tender?",
  ["POWERINDIA"],
  hops("buyback announcement", "corporate_documents", "corporate_documents(known_at)"),
  ["a post-close announcement shifts day 0 to the next session",
   "a tender is announced to all holders; the leak value is in the acceptance ratio",
   "check the deal tape for a seller before the announcement"],
  T("market_series", "corporate action", True, ""),
  as_of="2026-09-30"),
]
