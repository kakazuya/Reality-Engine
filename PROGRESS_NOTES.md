# open question bank — progress notes

- 2026-10-27 ~19:10 IST — read context pack, §2 families 12–20, gap table §10; bounded discovery over master_companies, mkt_nse_index_daily, mkt_commodity_daily, results_xbrl.filings (+ facts by file), concall_facts.cc_items, bse_announcements, results_notes.docs, policy_events/macro_events, bulk_block_deals, mkt_fii_dii_cash. Next: author 300 rows.
- 2026-10-27 ~19:55 IST — all 300 rows authored (20 archetypes × 15) and the 204-fact ground-truth table built from queries; builder emits jsonl + md; acceptance test passes. Next: final editorial pass on GT/question date alignment and gap canonicalisation.
- 2026-10-27 ~20:10 IST — aligned ground-truth facts to question dates (SIEMENS demerger, TRENT 2025 update, copper, flow), replaced a synthetic-ISIN entity (ZOMATO), canonicalised 37 gaps, idempotent rebuild verified. Remaining: final report only.
