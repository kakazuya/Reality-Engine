# T-242: filing events model-first r2 - fix the fresh8 grade's W/J kinds (agy Hydrogen high, 26 Nov 2026, Eagle)

Ticket: T-242

Goal: the first fresh grade of the model-first build (530433b3, prompt fp 546696b94a21) failed:
- order_win 53/1/6/0 (W+J 10%);
- fund_raise 39/2/16/3 (W+J 31.7%).

The bar is <= 5% W+J. Fix each W/J kind below with STRUCTURAL script checks in reality_engine/research/filing_events.py.
Script first; change the prompt only where a script cannot see the cause. A prompt change gives a new fp, so you
re-read the touched filings and count the requests.

Files: reality_engine/research/filing_events.py, reality_engine/tests/test_filing_events_model.py,
docs/DEVELOPER_GUIDE.md (filing-events entry), docs/research/T-231_filing_events.md.

Evidence: D:/RealityEngine/t242/grades/events_fresh8_model_first.md. The graded packs are
C:/RealityEngine/t242/audit_orderwin_fresh8/pack.jsonl and events_grade_fundraise_fresh8/pack.jsonl (ids = `id`). The
grader's reasons are in the note. The build is C:/RealityEngine/t242/fresh8/events_mf_fresh8.db with cache
model_cache.jsonl. Page text is in C:/RealityEngine/tg_build/full394/<store>/<store>.db doc_page, read-only.

Steps:
1. fund_raise: not a raise. The filing prints one of the following, so the row goes to skip_log with its reason:
   - "consideration other than cash" or "share swap";
   - "Scheme of Amalgamation/Arrangement" allotment;
   - ESOP / ESOS / Incentive Plan / options exercise;
   - a subsidiary's own DRHP/IPO, or an OFS by the company.

   Evidence ids 19, 31, 32, 53, 45, 42, 56. Counter-test: a preferential issue for cash in the same company stays.
2. fund_raise: intimation only. A Reg 29 / Reg 50 notice of a FUTURE board meeting that "will consider" is
   stage `intimation`, never stored (ids 21, 49).
3. fund_raise amounts:
   - (a) Unit check. A value_text with no crore/lakh/million/bn word is rupees: amount = digits / 1e7. Id 22 printed
     "INR 3,849,088,060", which is 384.91 cr, but 3.8e11 was stored. Generally, refuse an amount over 1,00,000 cr.
   - (b) Same-meeting legs. When one filing prints several legs for one meeting (equity + warrants + QIP, or NCD + CP),
     store the printed total if there is one. Otherwise store the sum of the legs with detail listing each, or one row
     per instrument (ids 17, 25, 54). Never one leg alone.
   - (c) Issue price. price_per_share is the issue price (face + premium) when "premium of Rs X" is printed
     (ids 26, 38).
   - (d) Shares as printed. Indian commas: id 52 printed 7,50,00,000, which is 75,000,000, but 10x was stored.
   - (e) Boilerplate. An amount taken from an "About <Company>" paragraph is never the raise (id 40).
   - (f) Computed amount (from the c858aea0 review). When only shares x price is printed, store amount = shares x
     price / 1e7, method 'computed', with the inputs in detail.
4. Duplicates (fund_raise J 8, 36, 44):
   - the same doc text filed twice: keep one;
   - a same-day "Revised" outcome supersedes the original (keep the revised).
5. order_win:
   - (a) A capex/plant/capacity press release that mentions an order only as background ("has already secured", "the
     JV has secured") is not an order win (ids 31, 49, 60).
   - (b) A filing that says "further to our disclosure dated ..." or "additional announcement in relation to" with no
     new value is a repeat: skip with a link to the earlier filing (ids 34, 39).
   - (c) Several orders printed in one filing: one row per order. A band floor like "INR 300 Cr+" is never an exact
     amount; store it in detail as a band (id 19).
   - (d) An INR equivalent printed beside a foreign-currency value is stored in amount_inr_cr (id 15).
6. Tests: one per kind, with quoted page text from the packs, plus a counter-test per kind.
7. Measure on copies: rebuild fresh5-8 from the cache where the prompt is unchanged, into
   C:/RealityEngine/t242/model_v2/. Report:
   - every graded row in the fresh5/6/7 packs and in both fresh8 packs, with old grade and new state. Targets: every
     fresh8 W/J fixed, skipped or unverified, and >= 95% of graded R rows unchanged;
   - counts per kind and per skip reason;
   - hy4 requests used.

Do NOT grade your own output. Eagle grades a new store set (fresh9) after the merge.

Accept:
- tests pass (per file);
- >= 90% of the fresh8 W/J rows are fixed, skipped or unverified;
- >= 95% of graded R rows across fresh5-8 are unchanged;
- no stored amount without its printed value_text, except method 'computed' with inputs.

Stop if: more than 5% of graded R rows change after two attempts, or hy4 errors exceed 5% of requests.
Budget: about 2.5 hours. Write scope: your worktree, plus C:/RealityEngine/t242/model_v2/ only.
