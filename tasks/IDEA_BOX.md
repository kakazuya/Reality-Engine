# Idea box

Shivam, 12 Nov 2026: ideas we still have to test are not tickets. Tickets (`tasks/TASKS.md`) hold only in-scope work
(a fix, a removal, a test with an accept command); rules live in `tasks/RULINGS.md`; ideas live here. An idea becomes a
ticket only when it is scoped into the current work with an accept test, and a backtest-ready hypothesis moves to
`tasks/HYPOTHESIS_REGISTER.md` (FRAMEWORK s5 decides what earns a place in the book).

Each entry: id (I-NNN), the idea in one or two sentences, why it might matter (the question or decision it serves),
what data it needs and whether we hold it, source (who/when, ticket it came from), status (`parked` | `next` |
`promoted to T-NNN` | `promoted to H-NNN` | `dropped: reason`).

| id | idea | why it might matter | data needed / held | source | status |
|---|---|---|---|---|---|
| I-001 | Our own 1-2 year revenue and earnings estimate per company from held facts (trend, guidance, order book, margins), against the growth the current price implies (reverse DCF at a sector discount rate); test whether the gap predicts 6m-2y returns, point in time. | P/E and P/S lag when the market pays a premium; the market looks 6 months to 2 years ahead, so the gap may show whether it sees the company as we do. | Held: financials, guidance, KPI rows, prices (valuation_daily). Needs: a discount-rate rule, the factor-reward result (T-118/I-002) first. | T-119, Shivam 8 Nov (closed 12 Nov) | parked |
| I-002 | Recurring factor-reward engine: at every rebalance date, per stock, sector and regime, measure which held factors were rewarded over the next 6m/12m/24m (point in time) and report the statistical mode of rewarded factors and how it shifts. Four factors still unmeasured: ROE/ROCE, pledge, FPI/MF changes, guidance revisions. | Rewards are not fixed laws (ruling 10 Nov); a frozen ranking would mislead the 6m-2y prediction goal. T-118 measured only one pooled 2019-2026 cross-section. | Held: prices 2019+, ratio_panel, shp_category, guidance, flows. Backtest-ready neighbours: H04, H14, H18, H19, H23 in tasks/HYPOTHESIS_REGISTER.md. | T-176, Shivam 10 Nov (closed 12 Nov) | parked |
| I-003 | Main-vs-branch store diff script: copy a store, build with main and with the branch, diff every table (rows lost/added/moved period); merge refused if a previously right row is lost | T-192 needed three hand rebuilds of pilot10 to catch hidden group targets and a crash | store copies, build profiles (held) | Eagle 12 Nov (T-192 review) | next |
| I-004 | Golden rows per store: 5-10 hand-verified rows per company asserted after every rebuild and at merge | right rows lost silently in rebuilds; checks live in reviewer memory | grader-verified rows (held in grade notes) | Eagle 12 Nov | parked |
| I-005 | Versioned schema: `schema_version` table + numbered migrations; build parts and lookups check it | `count_basis` added by one part crashed ratios and would have broken pilot3_holding on all stores | schema.py (held) | Eagle 12 Nov (T-192 r3) | next |
| I-006 | One typed reply contract (coverage block) for every tool, one test over all tools | 8 of 21 T-196 misses were replies that looked complete | T-197 coverage block | Eagle 12 Nov (T-196) | parked |
| I-007 | Split giant modules (kpi.py ~3,300 lines, lookups_pilot3.py, guidance.py) by job, no behaviour change | workers spend 26-41 calls before first edit; typecheck times out on kpi.py | code (held) | Eagle 12 Nov | parked |
| I-008 | Test tiers: ~60 s smoke set per commit, full suite per file nightly; fix sandbox tmp_path failures | one-process pytest hit 7.9 GB; a test file hung 20+ min; workers add tmp_path workarounds | tests (held) | Eagle 12 Nov | parked |
| I-009 | reality-data routes each symbol to the store that holds it (company -> store map) instead of one `REALITY_PILOT3_DB` | switching to aurobindo needed a committed `.mcp.json` edit that also changed Wolf's sessions | store company tables (held) | Eagle 12 Nov (T-195) | next |
| I-010 | Machine-check every countable claim in a worker report (counts, tests, files) before review | self-reports overstated ("0 group targets lost", "found=true" on partial answers) | worker results, store copies | Eagle 12 Nov | parked |
| I-011 | Pre-commit secret scan + ruff | keys for DeepInfra, Go, Kite in use; a leak is costly | none | Eagle 12 Nov | parked |
| I-012 | Store backup retention: keep last 2 `*_before_*.db` locally, older to Drive via raw_to_drive; data_inventory flags excess | backups pile up 3-5 per store at ~150 MB | raw_to_drive (held) | Eagle 12 Nov | parked |
