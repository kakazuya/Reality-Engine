# Task — backward requirements audit: what must exist before the checklist, ISIN-history map and company state can be built

## Goal
Shivam's standing rule (2026-10-27) is that no full run starts until the database schema is ready and the pilot passes one shared checklist script. Before anyone builds the checklist script, the ISIN-history map or `company_state_daily`, trace every requirement **backwards** to the data it depends on. Then report what already exists, what is partial and what is missing.

This audit is read-only. Its report gets reviewed before any build starts.

## Inputs (read these first)
- `tasks/LABELS_TAGGING_PLAN_2026-10-27.md`: the three tag layers, the opinions DB and the order of work.
- `tasks/QUERY_TEMPLATES_2026-10-27.md`: the 11 template families, slots, variations and pass rule.
- `tasks/ARCHITECTURE_OVERHAUL_2026-10-27.md`: the chunker v2 design. It mentions a `symbol_isin_history` table; check whether that table exists and is filled.
- `tasks/FRAMEWORK.md` and `tasks/STATE.md`.

## How
1. **Requirement list.** Make one row for each of:
   - every layer-1 tag;
   - every layer-2 field (`company_state_daily`);
   - every layer-3 macro-link field;
   - every opinions-DB field;
   - every slot and variation in the query templates.
2. **Trace each row backwards.** For each one, name the source table and columns it needs, using every DB in `reality_engine/data/` and the DuckDB snapshot. Open everything read-only with `reality_engine.db.readonly.connect_ro` and keep queries bounded. Then measure:
   - **Exists?** Name the table and column, or write MISSING.
   - **Coverage:** the share of the FY25+ universe it covers (known_at ≥ 2024-04-01; prices 2019+). Count the listed universe from `master_companies`, and split it into BSE+NSE, BSE-only and NSE-only.
   - **History depth:** whether it is dated (valid_from/valid_to or per-date) or only a current snapshot. A snapshot cannot serve as-of queries; flag it.
   - **Point-in-time source:** where its "known at" time comes from (dissemination time, broadcast time, filing date, or none), and whether any crawl date or doc_date is being used as a known time.
   - **Spot-check:** 5 random entities, comparing the stored value against the original record (filing or exchange file) where one is available locally.
3. **Specific checks:**
   - **ISIN changes.** Find real cases: splits, face-value changes, mergers, demergers, renames. Check whether price history and documents join across each change today. List 10 examples, each with old and new ISIN, symbol and date.
   - **Shares outstanding history.** Derive it from XBRL paid-up capital ÷ face value, check it against shareholding filings, and report the error rate on 20 companies.
   - **Index membership history and F&O list history.** Find what exists locally and which NSE sources (index-change notices, F&O lists) would fill the gaps. List only; no downloads.
   - **Sector, industry and basic industry.** Report the fill rate, and how many companies are missing one, split into BSE-only and NSE-only.
   - **Market-cap bucket as of a date.** Say whether it can be computed today, and what blocks it.
   - **Price bands** by date.
4. **Template feasibility.** For each of the 11 families × each entity level (stock, industry, sector, theme, index, mcap bucket, price band, policy), state which of these applies:
   - answerable now;
   - answerable once gap X is closed;
   - not answerable from our data, with the reason.

## Rules
- Read-only everywhere except this worktree.
- No network, no paid APIs, no commits.
- Do not open `reality_engine/data/results_notes.db` for writing. A running job owns it, so read it with `connect_ro` only.

## Acceptance checks
1. A requirements table covering every tag, field, slot and variation from the two plan docs. Each row carries: source, exists/coverage/history/PIT, and spot-check result.
2. The ISIN-change list (10 real cases), with the join result for each.
3. The shares-outstanding error table for 20 companies.
4. The feasibility matrix: 11 families × 8 entity levels.
5. A **build order**: the smallest set of gaps to close, in dependency order, each with its effort, its source, and whether it needs a fetch.
6. Every number traced to a query listed in an appendix.

## Test command(s)
```bash
python -c "print('audit only')"
```

## Report
Write it to `tasks/BACKWARD_REQUIREMENTS_AUDIT_2026-10-27_REPORT.md` in this worktree. Include the tables above, the build order, the open questions for Shivam, and your tool-call count.
