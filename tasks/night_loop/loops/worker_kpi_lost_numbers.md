# Worker: restore the numbers KPI round 3 lost

Goal: on this branch, `checkpages run` finds at least 145 again (KEC at least 29, BAJFINANCE 59, HINDALCO 57), by a general rule, without bringing back the wrong rows rounds 1 to 3 and the three-faults round removed.

Ticket: T-066

Evidence: measured by Opus on 5 Nov from each branch's worktree. Round 2 `ee3dcd0` found 145. Round 3 `233f75e` found 139, and the tip `195b0f4` also 139. So the loss is inside `git diff ee3dcd0 233f75e -- reality_engine/pilot3/kpi.py reality_engine/pilot3/lexicon/`. The six lost numbers, with the quote on the page:
- KEC024, 6303 INR crore, Q1FY27, `pilot60_history/KEC/results_press_release/fa8775d4-41cf-418e-9b25-48b664485d29.pdf` p2: "Order Intake of Rs. 6,303 crore"
- KEC024, 6300 INR crore, Q1FY27, `decks_full/cb/cb0b44e7feba2e3fa6f36ee670e09aa6ea68933cb68e53586d1ca839b09a6ad0.pdf` p12: "order intake of over Rs. 6,300 Cr across T&D, Civil, Renewables, Cables & Conductors and Transportation businesses"
- KEC025 and KEC095, 36267 INR crore, 31 Mar 2026, `pilot60_history/KEC/results_press_release/7fe36e59-8b29-4c0c-847e-04818d440671.pdf` p3: "Order Book as on 31 March 2026 of Rs. 36,267 crore"
- KEC097, 39325 INR crore, Q2FY26, `pilot60_history/KEC/results_press_release/8bac0a9b-0988-4d1b-9e47-deeaeaf55725.pdf` p3: "YTD Order Book of Rs. 39,325 crore"
- HINDALCO061, 1000 USD per tonne, `concall_pdfs/ac/ac3a8eaa74742c2a2a50d070d7740c8ae0264e757dbf93c53d39f6261e089746.pdf` p14: "the overall EBITDA per ton that we've been talking about off that facility would be north of $1,000 per ton"
Five of the six are plain sentences "<metric> of Rs. N crore". Start there: find which round 3 change rejects them (`_quote_owns_value`, `_neg_context`, `sentence_rows`, the outlier gate or the review rules). Also in KEC: the three-faults report says dev questions KEC-088, 094, 095 and 129 lost `order_intake` for H1FY27 and Q2FY27; round 2 held those periods, the tip holds only FY26, FY27, Q1FY27, Q2FY26, Q3FY26. If the same rule explains them, fix them too. Do not read the hidden question set.

Code: `reality_engine/pilot3/kpi.py`, about 2,000 lines: use `outline`, do not read it whole.

Fast check, seconds, repeat freely: `python -m reality_engine.pilot3.checkpages run --work D:\RealityEngine\pilot10\scratch\cp_t066`. Look only at the lines for these six.

Files: `reality_engine/pilot3/kpi.py`, `reality_engine/pilot3/lexicon/*.yaml` except `results_lines.yaml` and `topics.yaml`, `reality_engine/tests/test_pilot3_kpi.py`, your lines in `docs/PILOT3_BLUEPRINT.md` and guide O2 in `docs/DEVELOPER_GUIDE.md`. Do not touch `tasks/`.

Accept:
1. `checkpages run` as above: at least 145, KEC at least 29, HINDALCO at least 57, BAJFINANCE 59. Print the totals.
2. `python -m pytest reality_engine/tests/test_pilot3_kpi.py -q`: all pass, no assertion loosened, one new test from these sentences.
3. Copy `D:\RealityEngine\pilot10\scratch\w_kpi7.db` to `w_kpi8.db` in that folder by sqlite3 `backup`, then `python -m reality_engine.pilot3.build --profile tasks/night_loop/pilot10_profile.json --part kpi --symbols KEC --out D:\RealityEngine\pilot10\scratch\w_kpi8.db` and print KEC's `order_intake` periods. `python -m reality_engine.night_eval.answerable --db D:\RealityEngine\pilot10\scratch\w_kpi8.db --qset tasks/night_loop/questions/dev.jsonl --out D:\RealityEngine\pilot10\scratch\a1_kpi8.json`: print KEC's count (at least 64, 66 if the H1FY27 and Q2FY27 periods come back).
4. Hand read 10 KEC rows the fix brings back against their quotes, listed in the report.

Rules: general wording, no company names in code. The current baseline is what Opus measured above; do not call a baseline stale without running it. One build only. Do not run `guards`.

Stop if: free RAM stays under 2.5 GB for 10 minutes, or a restored number can only come back by undoing a tested fix: then report which test and which row, and stop.

Budget: 40 tool calls. End with the checkpages totals, A1 for KEC, the hand read and a `Docs updated:` line.
