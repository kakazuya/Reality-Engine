# Workspace journal: learnings across sessions (newest first)

Ruling (Shivam, 13 Nov): every session writes an entry twice: once on crossing ~400k tokens of context, once when
Shivam says to wrap up. Each entry: work done, what worked, what did not and why, what to improve in input / design /
architecture / execution / output. Every new session reads the latest entry first (the start hook prints its
"Carry forward" bullets). Transcripts and the run ledger keep WHAT happened; this file keeps WHY and what we learned.
Keep entries short; facts with numbers; no repetition of STATE or tickets.

## 2026-11-14 06:20 Wolf (same session): round 14 checked lookups built, replayed, failed

Work done: T-213 r14 + r14b (checked_lookups.py, 29 tests) built by two DeepSeek workers; replay on the 29 r13-miss
questions: 6 right / 12 partly / 11 wrong vs DS tool run B 19/9/1 on the same questions; ~32k in + 16k out tokens,
164 s per question. T-208 r3 merged (PVRINOX 20,620/21,051 = XBRL); s10 stores rebuilt live; T-212 XBRL 2,597 symbols.

What did not, and why:
- C4 probe = keyword FTS over the whole store: hits were director bios, staff lists, e-voting text; the model spent
  both follow-ups rebutting them. A check is only as good as the search behind its follow-up.
- Items capped at 600 chars split Q&A: the analyst's question without the MD's reply (BS-025, BS-020).
- statements terms=AND and a 12-lookup plan cap starved the model; DS tool runs read whole pages freely.
- holding rows reached the model without values (item extraction bug, BS-058).

What to improve: keep code checks for coverage/numbers/speaker, but make the follow-up a scoped instruction
("read the latest call / this quarter's deck / the AR section, whole pages") rather than keyword hits; no item cap on
transcript Q&A; test any new loop on 5 known-miss questions before a full replay.

Carry forward: Shivam to choose the next round-14 design; bluestar.db rebuild with the T-208 r3 reader (exceptional
items 23.02); r13 branch + r14/r14b branches unmerged (r14 not to merge as default path).

## 2026-11-14 05:00 Wolf (neo-r13-blind-grading): T-207 accept, PVRINOX fix worker, Q2 XBRL gap, r13 grades

Work done: T-207 closed (Shivam: accepted, continuous) -> ruling amended, T-211 month-end job opened. T-208 r3 worker
started (printed reader: OCR words for garbled pages, wrapped labels, reconciliation guard). Found results_xbrl.db holds
Q2FY27 for 307 symbols only (index stale since ~2 Nov) -> T-212, fetch running (4,205 files). Graded r13 (236 answers).

What worked:
- Grading by SQL/page-text scripts (g.py in the session scratchpad) instead of MCP tools: one pilot3_search reply was
  ~10k tokens; a regex over doc_page with 150-char windows gave the same truth in ~1k. 196 answers graded in ~2 h.
- A consistency pass across graders caught BS-040 (company-wide order book used as the segment's) graded right by me
  and the same pattern graded wrong by the agy grader on BS-008; aligned to the stricter rule.

What did not, and why:
- agy Opus grader: one batch of 40 answers = 159k fresh + 1.4M cached tokens and the whole 5-h Claude quota on the
  Google account. Eagle's "after 13:30" timing was a quota wait; 8 batches would need ~7 windows. Fix: the grader should
  get a compact truth sheet per question (or SQL access) instead of exploring with MCP tools.

What to improve:
- Answer path (36 of 44 misses = routing): answers stop at the first tool reply. Round 14 should make the model name
  each fact it needs and check off each part of the question before answering (BS-026 PLI, BS-037, BS-049, BS-056).

Carry forward:
- Review T-208 r3 worker 20261113T210004Z-c8d0d947; T-212 parse + raw to Drive, rerun after the 14 Nov deadline.
- Round 14 brief (lean planned lookups) against DS B baseline 54/64, 2 calls/question.

## 2026-11-14 03:15 Eagle wrap-up (sv-seed-pack-test-plan): Hydrogen arms, four workers, pack design rejected

Work done: rulings recorded (agy = `gemini-4-hydrogen-high` only, Flash dropped; Opus 5.5 medium grades; Go key 1
only). Merged: Go key-1 clean-up (written by Hydrogen, coding trial 1), T-209 universe SHP/pledge/balance-sheet store,
T-208 r1+r2 unseen stores (KEI, MEDANTA, PVRINOX) with 411 pages HP-OCR'd, T-210 factor deep-study engine (panel run
not done: RAM). Board: 8 merged tickets closed; 5 old worktrees tagged `archive/*` and removed. T-205 r13 harness
reviewed (63 tests) but NOT merged; Hydrogen arm S stopped at 18/64, arm P at 26/64 by Shivam.

What worked:
- Briefs with a stop rule on code changes: T-208 r2 stopped instead of storing PVRINOX revenue 1,051 for 21,051 and
  named three causes. RAM gate in the T-210 brief avoided a reaper kill.
- Hydrogen as coder: followed a file-list brief, found 20 more call sites than named, separated pre-existing test
  failures correctly (18 min, 441k tokens). With `--dangerously-skip-permissions` it runs shell commands (43 tonight).
- Own-sample checks caught: BS-040 grader error (5141.78 printed without a comma), garbled text layer passed as ok.

What did not, and why:
- My scheduling: two answer arms + a Hydrogen trial in parallel on 3.6 GB free with three workers -> Claude Code killed
  all five of my jobs. Rule I broke: check free RAM before each launch, run heavy jobs one at a time.
- A merge commit (T-210, 02:20) lost its second parent after a doc_gate refusal and carried only STATE; I deleted the
  branch. Recovered from the commit id at close (d0f4735f). Check `git show -s --format=%P` after any refused merge.
- Pack design (Shivam: "bullshit"): scripts union every route into a 100k-char pack and the model reads it like a PDF.
  Arm S re-sent the pack on every tool turn: median 140k fresh + 920k cached tokens/question, ~0.4% weekly Gemini
  per question (~27% per 64). DeepSeek lean tool runs did ~3 calls, ~22 s/question and scored 43-46 vs pack 40.
- The 3-question smoke said 78 s/question; real arm S median was ~170 s. Smoke on 3 easy questions misleads.

What to improve:
- Design (Shivam 14 Nov): round 14 = lean planned lookups: model names exact facts; tools return only those rows
  (value, period, basis, source, known_at, formula inputs); targeted follow-ups for gaps; no seed pack; compact tool
  replies. Measure right answers AND tokens per question, Hydrogen vs DeepSeek.
- Store: printed-results reader must take OCR words for garbled pages and join wrapped labels (T-208 guide).
- Execution: heavy runs one at a time; RAM check before each start; never parallel answer arms on the MSI.

Grading handover (next Wolf session, after 13:30 IST; Opus 5.5 medium via agy; do not merge r13 before):
```
cd C:/Users/warri/Downloads/IDM-worktrees/20261113T182621Z-4b624470
python -m reality_engine.answer.blind_grade make --set hyd_pack=D:/RealityEngine/bluestar/answers_r13/arm_p \
  --set hyd_seeded=D:/RealityEngine/bluestar/answers_r13/arm_s --set ds_pack=D:/RealityEngine/bluestar/answers_r12 \
  --set ds_a=D:/RealityEngine/bluestar/answers_ds_a --set ds_b=D:/RealityEngine/bluestar/answers_ds_b \
  --out D:/RealityEngine/bluestar/report_r13 --questions D:/RealityEngine/bluestar/answers/questions_in.json --batch 8
python -m reality_engine.answer.blind_grade run --out D:/RealityEngine/bluestar/report_r13 --workspace .
python -m reality_engine.answer.blind_grade decode --out D:/RealityEngine/bluestar/report_r13
```
Hydrogen answered only BS-001..BS-026 (P) and BS-001..BS-018 (S): compare all sets on those questions (paired), and
report the full-64 numbers for the DeepSeek sets separately. Grader rule added: search figures with and without
thousands separators. BS-040 truth in `report_r12/BS-040_check.md`.

Carry forward:
- Grade r13 (paired on the questions Hydrogen answered); then round 14 lean planned lookups, not packs.
- PVRINOX Q2FY27 revenue defect + its missing XBRL before the unseen-company verdict; T-172 frozen split.
- T-210 panel run when 7 GB RAM is free; T-207 accept from Shivam; restart dsh-worker MCP for the key-1 default.

## 2026-11-13 21:45 Wolf wrap-up (same session, closed on resume): loose ends and the next session's plan

Closing checks: doc sweep clean (round-4 brief reworded: its two new modules live on the unmerged branch); data
inventory regenerated (0 undocumented tables); no worker or grader running. Nothing pushed.

Left open, with where it lives:
- T-205 branch `dsh/20261113T103928Z-0a9aa11d` (c264b5a3) and its worktree are kept, NOT merged: code is sound
  (52 tests) but the path scored 40/64. Evidence: `D:/RealityEngine/bluestar/{pack_r9,pack_r11,answers_r12,report_r12}`;
  grades decoded in `report_r12/graded_decoded_r12.json`; key `key_private/key_r12.csv`.
- Unchecked: one new-path answer (the order-book-to-revenue question) cites an order book of Rs 5,141.78 crore the
  grader found on no held page; the judges' five non-verbatim prose quotes; Go key 2 "subscription required" (worker's
  report) and `pilot3/second_read.py` still trying key 2 first; three stale live assertions in `test_pilot3_tech.py`.
- Old worktrees still on disk (T-163 r4-7, T-132 r10-12 dsh branches of 10 Nov; three Wolf-agy): review or tag, then remove.
- Nine Eagle tickets shown merged in STATE but still OPEN on the board (T-177, 178, 182, 183, 185, 186, 187, 189, 190).

Plan for the next session, in order (each needs Shivam's word first):
1. Rule on T-205's next step. Recommended: keep plan + pack + script check, add at most two follow-up gather rounds
   for parts that are short or not_found, then answer again. Gate: no question right in round 12 may fall; judge the
   packs before the answer run; blind headless-Opus grade with the old runs beside it. Alternative: tool run seeded
   with the pack.
2. Measuring stick before more tuning: s10 raw fetch (T-168) and frozen split (T-172), so a few points mean something;
   then a NEW unseen company for the verdict (Blue Star and Aurobindo are development sets).
3. Structured layer at universe scale (script only): shareholding categories + pledge from exchange XML, balance-sheet
   lines from filed results; feeds the T-207 factors still unmeasured (pledge, FPI/MF change, ROE/ROCE).
4. T-207: Shivam's accept; then round 3 only if he wants regime coverage (needs a falling-market sample).
5. Document-layer scale stays behind the 95% gate: reader cost at scale and the parked v2 tickets (I-014) come back then.

## 2026-11-13 21:20 Wolf (neo-claim-worker-progress-review): direction-only session; factor rewards; answer path rounds 4-12

Work done: Shivam ruled Claude directs and reviews only, workers build. Board cut 86 -> 51 open (IDEA_BOX I-013..I-015).
T-207 factor-reward engine built in 2 rounds, audited, merged. T-205 answer path rounds 4-12 on one branch
(`dsh/20261113T103928Z-0a9aa11d`, c264b5a3, not merged): model-written plan from a store menu, union gather, reading
copy, one answer call, script calcs and citation check. Reader-judge of round-9 packs: enough 41 / partly 23 / missing 0
of 64. Blind headless-Opus grade of 64 seen Blue Star questions: new path 40 right (62.5%); the two 13 Nov tool runs
re-graded 43 and 46 (they were 47 and 53 on 13 Nov, so this grader is stricter; agreement 56 and 55 of 64).

What worked:
- Gates that compare with the previous round on the text the model will read; the worker stopped and named questions
  instead of tuning. An offline re-check of saved replies recovered a broken run with almost no new model calls.
- Judges with a helper script that refuses a row whose quote is not verbatim, one row saved per question.
- T-207: fixed thresholds in the brief, later additions labelled; an independent audit quoting the proving code line.
- Packs judged enough gave 33 of 41 right; packs judged partly 7 of 23: the judge predicts the grade.

What did not, and why:
- The new path does not beat the tool loop yet: 17 of 24 losses are evidence the pack never gathered. One fixed pack
  cannot follow up; the tool loop can.
- My errors: a 60,000-character cap never measured (rounds 7-8 lost evidence, round 9 undid it); a 210-minute hard
  stop for a ten-round session; three parallel Beam judges beside the worker's Beam calls (429 on Go key 1); not running
  the judge on round 6. My collinear-counting guess on T-207 was wrong; the round-2 test showed staleness.
- Round 10 ran 97 answers through a check that could not resolve item ids (about 6.1M input tokens) and reported the
  failure rate as a statistic.
- Re-grading the same answers moved 8-9 of 64 grades: 64 questions cannot separate designs a few points apart.

What to improve:
- Input: every brief names the previous round's file to compare against; every runner has a first-ten stop gate.
- Design: pack first, then a bounded follow-up (a second plan and gather for parts that are short) before the answer.
- Execution: no size or time limit without a measurement; Beam one worker at a time per key; judge early.
- Output: grade old and new sets together blind every time, so grader drift is visible.

Carry forward:
- T-205 not passed and not merged; Shivam to rule on the next step (bounded second gather vs tool run seeded with the pack).
- T-207 merged, awaits Shivam's accept: stable factors need only P&L, promoter holding, insider trades, prices.
- Larger frozen set (s10) is still the measuring-stick blocker; structured-layer build awaits Shivam's go.
- Grading goes to headless Opus (Shivam 13 Nov); paid DeepSeek allowed when Beam is rate limited.

## 2026-11-13 16:45 Eagle wrap-up (sv-t-199-blue-star-atom): evidence pack rounds 2-3

Work done since the entry below: evidence pack (T-205, Beam) round 2 (cap, per-call pages) and round 3 (symbol,
phrase search for figures, date periods, semantic pages per call, route_errors) merged (`708ab7aa`, `58d27ade`);
round-2 judge: enough 21 / partly 27 / missing 16 of 64 (`bluestar/pack/pack_judge_r2.csv`); round-3 judge running
at close (Beam job 20261113T100438Z-add44400, output `.tmp/judge/pack_judge.csv` in its worktree). Journal ruling,
start-hook pointer, memory note added (T-206).

What worked: measuring the gatherer alone with a reader-judge before building the answer step exposed the planner
bugs in one pass (empty symbol, wrong metric, wrong period, word-only page choice).

What did not, and why: Beam workers wrote outside their workspace despite the brief (write limits belong in the Stop
rule); the round-1 judge took 9 minutes for 64 large packs (treat fast judges as suspect; ask them to quote the found
text).

Carry forward:
- Read the round-3 judge (job 20261113T100438Z-add44400); if enough < ~55/64, switch to a model-written lookup plan.
- Then build the answer step + number post-check (DeepSeek, off-peak), test on a NEW unseen company.
- Briefs: write limits in the Stop rule; judges must quote the pack text they matched.

## 2026-11-13 Eagle (sv-t-199-blue-star-atom): Blue Star atom test, then the evidence-pack prototype

Objective: test the "atom" design (one stored row per printed figure, read by Haiku from page images) on an UNSEEN
company (Blue Star, 64 frozen questions) and reach >= 92% blind-graded right; then start the answerer redesign.

Work done:
- Rebuilt bluestar.db (263 docs, 5,749 pages), routed pages, OCR on the HP (129/143), Haiku read 773 unique
  table/chart pages (134 headless sessions), three DeepSeek rounds built `page_atom` (schema v10, 45,173 figures,
  25,672 verified), page embeddings (USD ~0.2). Answers: DeepSeek 82.8% / 73.4%, Haiku 56.2% (blind Opus, partly =
  wrong). Second "check every part" pass: 84.4% / 76.6% (seen set). Report `reports/2026-11-13_bluestar_atom_test.html`.
- Evidence-pack prototype (T-205, Beam): rounds 1-2 merged; judge says packs hold enough for 21/64, partly 27,
  missing 16. Round 3 (planner fixes) running at the time of writing.

What worked:
- The atom store: on unseen pages, financial-statement values 95.5% right, recall 81%. 60/64 questions were answered
  right by at least one run, and NO lost grade was missing data. The data side is close to done for financials.
- A seeded truth sample before the answer run: it found three structural defects (lost section headings, equal
  values merged, page unit on non-money cells) that fixture tests missed. Keep this step before every answer run.
- Headless `claude -p` Haiku sessions with a narrow tool list: cheap, isolated context (peak 89k), no pop-ups.
- Blind grading with shuffled X/Y/Z labels and a private key; graders find truth themselves; the root-cause column
  turned a score into a diagnosis (routing 39, compute 11, reading 6 of 56).

What did not work, and why:
- The answerer, not the store, loses the points: same brief, same store, DeepSeek 82.8% vs 73.4%. A model with tools
  stops early, misses a part, or says "not found" while the data is held. More data cannot fix this.
- A generic "re-check every part" pass gained only 1.6-3 points: it reused the same habit (stopped at statement rows,
  one run made 65 calls for 64 questions).
- Script-only planning for the evidence pack is brittle: an empty symbol silently disabled half the routes,
  "depreciation" mapped to P/E, "30 Sep 2026" became Q3. Word matching cannot bridge question wording and filing
  wording ("margin guidance" vs "6.5%-7%"). Silent route failures hid all of it until a judge read the packs.
- A figure-matching recall scorer measured noise (period fragments, doc ids, grader-computed numbers). A reader
  (judge) is the right measure for statement and list questions.
- Process slips: in-conversation Haiku subagents overran 100k on dense pages (fixed by headless + weighted
  batches); `page_reader`'s default doc types silently dropped announcements; `rclone link` made a public link
  (removed; never use `link`); my Pro limit hit 95% at 01:05 because 4 parallel Haiku sessions plus Opus graders ran.

What to improve:
- Input: questions are fine; give workers REAL samples (headers, defect rows) in the first brief, not after a
  failed round (round 2 and 4 of atoms were caused by briefs without store samples).
- Design: answering should be plan (cheap model writes all lookups at once) -> gather (script runs all, parallel,
  as_of filtered, every route logs errors) -> answer from the pack -> script check that every number is in the pack.
- Architecture: every lookup must fail loudly (route_errors in the pack); derived rows (capital_employed) need a
  definition test; defaults that filter (doc types) must be explicit.
- Execution: measure each stage alone before building the next (pack recall before the answer step was right);
  pace Pro-subscription work (2-3 parallel sessions, not 4) and say the token cost before launching.
- Output: one HTML report + Excel per run, disclosures section always (seen sets, overruns, spend).

Carry forward:
- The bottleneck is the answerer (39/56 losses routing); do not spend on more extraction for financials first.
- Evidence pack: script planning failed; next is a model-written plan executed by script (T-205 round 3/4).
- Before any answer run: seeded 20-page truth sample of the store, then blind grading with a private key.
- Blue Star questions are now SEEN: the 92% verdict needs a new unseen company.
- Open store defects: derived capital_employed, EPS unit, page_reader default doc types, sentence figures.
- Pro quota: Haiku sessions max 2-3 parallel; never `rclone link` (public link).

## 2026-11-14 10:45 IST, Wolf (session close)
- Work: worker review row for r14b; merged r12+r13 answer arms (lean tool runner, agy_call, seeded_run, blind_grade) with a manual merge (MSI_LAPTOP both sides, STATE ours); r14/r14b archived on tag `archive/Wolf-T-213-r14b`; all four worktrees and branches removed.
- Worked: tests 72 passed 1 skipped; doc sweep 0/0.
- Failed + why: merge_worker conflicted on STATE/MSI_LAPTOP because the branch edited shared docs; doc_gate refused the first commit without a STATE change.
- Improvements: T-210 7 GB need is unreachable on the MSI (~5.9 GB free at idle); chunk the panel or run on the HP.
- Carry forward: answer tuning on lean run B (next session, Shivam's design call); T-212 re-run by hand after 15 Nov 09:17; s10 verdict; T-211.

## 2026-11-14 13:50 IST, Wolf
- Work: T-213 r15: DeepSeek built `answer_checker.py` (C1 late source, C2 calls in window, C3 speaker, C4 segment scope, C5 searched before not-found) in 25 min; repair pass on the 15 flagged run-B answers in 20 min / 97 calls. T-210 handed to Hydrogen (agy) with a low-RAM brief. job_watch status + `agy-workers` mod show live Hydrogen steps/tools/tokens.
- Worked: run B 54/9/1 -> 57/7/0, no right answer lost; checker flags 9/10 misses at 6 false alarms, all 6 survived repair.
- Failed + why: a follow-up naming the right figure did not stop the agent mislabelling 7,229.22 as the segment book (C4 passes once a scope word is present); facts in older calls (Q3FY25 PLI, Q3FY26 label cost, Q1FY27 8-10%) stay unread because no check names those calls. Grades are not blind.
- Improvements: a theme-calls check (statements matching the question's theme words -> calls that must be read); C4 should compare the stated figure with the printed segment figure, not only look for a scope word.
- Carry forward: blind re-grade if Shivam wants the number firm; T-210 Hydrogen run; T-212 by hand after 15 Nov 09:17.

## 2026-11-15 15:30 IST, Wolf (session close)
- Work: T-210 merged (Hydrogen, Argon docs): factor_deep 3.7 -> 0.64 GB peak, full study 93 min. T-212 closed: 5,242 filings / 2,904 symbols, raw to Drive. agy default moved to Argon high (ruling). agy-workers status mod. Telegram priority build: refreshed topics 7/683, 653 companies in 60 days, mcap filter 800-20k (368), Haiku read 507 PEAD cards in 9 sessions (calibrated ~43k + 7k/sheet, all < 86k), tiered queue of 93. Tickets T-214/215/216 opened; T-178 to Wolf; T-205 dropped; T-208 done.
- Worked: header-crop + 12-card sheets cut image tokens ~10x; 2-then-4 calibration set session size first time; Haiku reads 24/24 right.
- Failed + why: two agy runs died on DNS drops (no retry in the runner); raw_to_drive delete is global (603 GB dry run) - caught by a dry run before use.
- Improvements: T-215 delete scope; T-216 agy retry; sparse factor arm needs NaN-tolerant scoring.
- Carry forward: T-214 plan file lists the pre-build fix order; start with T-178 and T-215.

## 2026-11-16 01:40 IST, Wolf (session close)
- Work: T-215 delete scope fixed (603 GB were `drive:` pseudo rows); T-178 salvage = audit-only; T-209 SHP raw to Drive; 10 Telegram stores built and measured (T-214 step 3); gap diagnosis (4 classes); fix A (shp NULL isin) and fix C (sector map) merged; fix B guidance rounds 1-3 rejected, round 4 running; HP laptop wiped before access ended; agy keeps Flash 3.8 medium and runs the model Shivam names; tickets T-217, T-218.
- Worked: trial on company 1 before the other nine; a read-only diagnosis worker gave file:line causes for the fix briefs; hand-reading every added guidance row and diffing on UNSEEN stores caught what "0 removed" on the worker's own stores hid (three times).
- Failed + why: I offered a batch build of 83 companies (Shivam: one at a time); a brief named a wrong file path; the guidance worded path took 4 rounds because each round was judged on stores the worker had seen; I had removed Flash from the allowlist for good (Shivam: never drop a model); background watches were reaped twice on low memory with 3 workers running.
- Improvements: T-218 part stamps + repair runner so a fix costs minutes on built stores; keep a rotating unseen-store pool for every extractor change; verify brief paths from the diagnosis output; 2 workers at a time on the MSI now the HP is gone.
- Carry forward: hand-off file `tasks/handoff/T-217_T-218_HANDOFF_2026-11-16.md`; review fix B round 4; restart agy-worker MCP; usage window ends Tue 17 Nov 10:30 IST.

## 2026-11-16 05:50 IST, Wolf (context past 400k; night run)
- Work: fix B round 4 rejected and closed (unseen stores: 61 added / about 39 right, 9 removed / 5+ right). T-218 built and used: part stamps (code hash, output hash, inputs), `store_repair` with a diff gate, repair notes R-001..R-006. T-217: `tg_questions.py`, 37 of 91 companies harvested by Flash. R-003 order wins (`order_wins.py`, table `order_win`) on all ten stores. R-006 printed-results scale fixed on store 1.
- Worked: the repair gate caught a real fault on its first use (stores rewrote quarter rows, preferred skipped); stopping a repair where rows stop changing made a fix cost 3-45 s per store instead of 263 s; reading one company end to end exposed five defects in an hour, and one (R-006) explained another (R-005); label-anchored reading of the SEBI order table worked on ten different issuers after four dry runs.
- Failed + why: `git checkout main` while background jobs ran from the branch removed their code for a few seconds; a Flash run deleted the shared harvest log and raw files (shared working folder); the harvest was reaped once on low memory; bash heredoc Python patches turned `\b` into backspace characters twice (use the Edit tool for anything with a backslash); the redo of one company ran alone before the batch and cost 15 minutes of parallel time; Flash five-hour quota ran out two companies short.
- Improvements: status line now saves usage figures (`.claude-neo/usage_status.json`), so pacing is measured; each harvest run has its own folder; stale check + `--part stale` is the one command after any extractor change.
- Carry forward: R-006 on stores 2-10 and pilot stores after a copy diff; R-004 shareholding categories; R-002 transcript fetch needs Shivam's go-ahead; R-001 guidance redesign; `order_win` is served by `pilot3_sql` only (no tool yet, no row checks yet); harvest batch 2 log `tg_build/harvest_batch2.log`.


## 2026-11-16 16:15 IST, Wolf (five-hour window ending)
- Work: R-004 shareholding merged and applied c01-c09; R-005 KPI lakh unit fixed (kpi + row_checks) and applied to 9 stores (c02 held for R-007); R-002 transcripts: NSE listing + 600 transcripts to Drive, BSE feed refilled 19 Oct-16 Nov and copied into the store database, 34 companies confirmed no call filed; c08 docs rebuild found nothing new. Notes now carry code/tables/tags/scope with a stores x parts grid (`reports/store_repair_grid.xlsx`); R-007 (deck vs annual report revenue) and R-008 (c07 share count) opened. T-217 harvest: 81/91 done, last 12 on Flash; three link-verification fixes (NSE archive name, site name in symbol, PDF text layer). T-219 opened: unified items (Shivam: local/Drive/GitHub only, no cloud tool).
- Worked: reading every refused diff before accepting caught c02's real conflict and c07's bad share count; checking value deltas (not only row counts) separated harmless re-keys from real changes.
- Failed + why: the three-company integration test cannot finish (pilot PDFs fetched one by one from Drive, >70 min); raw_to_drive --keep is case-sensitive and nearly uploaded 52 GB; Sonnet on agy did 1-11 tool calls per company and its quota lasted 3 companies; heredoc escapes broke a Python patch again (use Edit for backslashes).
- Carry forward: c02 R-005 after R-007; R-008; R-001 redesign; T-219 build; `tg_questions load` + `check` after the harvest (re-harvest q078/q079 on Flash if Shivam agrees); pilot60_history (19 GB) to Drive needs Shivam's OK; integration test needs a local pilot-PDF cache or a smaller fixture.

## 2026-11-17 11:20 IST, Wolf (session close)
- Work: trial 1 graded and reported (frozen 52/87 by the 9 Nov ruling, strict 43/87). Rulings: OCR after the HP = Kilo Dots + Haiku; store-repair notes scored (severity = companies hit, criticality wrong 3 / corrupt 2 / missed 1, priority), `note tally` maps trial failures to notes (R-019 added). R-017: KPI reader reads mns / '1,900+ Mn' / '(C in Million)', checker rule `own_scale`, rescale check reads only the printed number; 84 of 91 stores carry the fix (58 clean, 26 accepted after a row read of 122 lost rows), 6 held (c17 c36 c47 c57 c58 c65). Document map `pilot3/doc_map.yaml` + `doc_map.py`: sections per document type, scan of 91 stores, report `reports/2026-11-17_doc_map.xlsx`.
- Worked: measuring before fixing (60 of 69 failures sit in statements, notes, MD&A, decks, calls; 34 are held data read badly). The map found AR sections in 60-96% of 270 reports while no reader fills most of them.
- Failed + why: the R-017 kpi re-run also applied the R-010 OCR cells to stores built before it, so 48 runs were refused and needed a row read; my first own_scale version hid right lakh rows ("Rs. 193.76" read as .193.76), caught by the read, fixed.
- Improvements: run a part re-run only on stores whose stamp matches the code before the change, or split the diff by cause; the stored AR page text is clean line-per-cell (label, then current and prior values), so the statement reader can work on doc_page text without PDFs.
- Carry forward: AR statement reader (cash flow first, then BS/P&L every printed year, then PP&E/CWIP/commitments/revenue break-up/finance costs/segments) on doc_map-labelled pages with CFO+CFI+CFF and XBRL (FY25+) checks; widen BS/P&L headings; the 6 held R-017 stores; independent review of tg_trial check/merge, store_repair scoring, doc_map and the R-017 code; old unmerged branch dsh/20261110T104212Z-67ceeb28 to judge.

## 2026-11-18 06:55 IST, Eagle (session close; overnight run, Shivam asleep)
- Work: T-223 on branch `Eagle-T-223-readers`. Printed segment reader (5 review rounds) in stores: 2,632 rows/19 stores; `kpi_series` UNIQUE gains basis. AR notes reader (borrowings, revenue break-up, finance costs; 9 review rounds; note totals tied to the face statements) in stores: 6,329 rows/72 stores, replacing 4 wrong groups the first version stored. R-019 tool replies (value_cr, superseded guidance, holding totals first, BSE fallback, fact routes to printed quarters) merged. R-020 FYFY June labels found and fixed in 14 stores (1,334 -> 347 rows, all in 6 held stores; fix for those in agy opus review 3183ee70). store_repair waits for a store lock and skips a locked store. Rulings recorded: agy Hydrogen high codes first until 60% of the Gemini weekly limit, then peak -> agy, off-peak DeepSeek unless Go usage +10 points/24 h (log `D:/RealityEngine/ledger/go_usage.csv`); Argon medium for company question search.
- Worked: Hydrogen wrote all code from detailed briefs (file:line evidence, accept checks); DeepSeek reviewers in workspace-write worktrees (python runs; read-only sandbox could not) with own seeds and whole-output invariants; the tie-out to the face statements ended the add-up-gate defect loop in one round; accepting refused store runs only on an exact row match to the reviewed dry run (93 stores accepted that way) or a per-store page-checked verdict (R-020: 14 accepted, 6 held).
- Failed + why: in-note add-up gates kept admitting neighbour tables (rounds 5-6); a 25% "differs" tolerance let two sub-totals through (round 8); store_repair crashed twice on a lock from a concurrent dry run; authors' self-reported change counts were wrong in 3 of 5 rounds; running a part on stores built by older code brought unreviewed drift (R-020 c88 would have lost 79 right rows).
- Improvements: brief authors for base-vs-fix counts on store copies; anchor every reader to an independent figure; review drift separately from the change; give reviewers python (worktree + workspace-write).
- Carry forward: R-020 six held stores after review 3183ee70; notes lost-row follow-ups (multi-page notes c84, face candidates equal to the prior-year column c78 c59 c75, sub-total names); merge `Eagle-T-223-readers` to main (docs swept clean); restart reality-data; PP&E/CWIP, capital commitments, ratios note, pre-FY25 BS/P&L; trial 2; T-224 model router; remove merged worktrees.

## 2026-11-18 21:10 IST, Eagle (session close)
- Work: stores moved to C: SSD (junctions at D: paths, raw PDFs on D:). Repairs applied across the 91 Telegram stores: R-020 (84/91), R-013 confirmation ladder + FY confirm, R-021 XBRL-first conflict gate + follow-up, R-022 segments (85/91), ar_notes as-filed + restated (90/91); store_repair `--accept` now refuses a changed live store (fingerprint). OCR bake-off: RapidOCR CPU 97.7% (= HP TextRecognizer), DirectML 2x faster at 2000 px (`REALITY_OCR_MAX_SIDE`). Model-vs-script on 60 pages: scripts 4/60, Dots 87% placed right, HY4 80%; neither alone is servable. T-225 opened (blend: checker rebuild first). NAVKAR ruling: subsidiary keeps parent's call transcripts, labelled.
- Worked: before/after judge against XBRL quarter + annual facts caught round-1 losses of R-013 and R-021; reviews by a separate agy session caught the EPS-decimals defect; committing code before measuring kept agy work when quota ran out.
- Failed + why: an accept wiped Wolf's filing table on 17 stores (stale before.db replayed) -> fingerprint guard; my judge skipped pre-window periods, so c59 was accepted with Q2FY24 rows lost (fixed by follow-up); a merge commit carried no code (re-merged); a hung pytest ran 27 min unnoticed by a monitor that matched its own command line.
- Improvements: judge covers all periods; monitors match python/pytest processes only; accept checks the live fingerprint.
- Carry forward: T-225 (checker rebuild, then Dots + checker on c09 c31 c61 c87 c88); c75 December year-end; c60 restated FY24 segments; notes PP&E/CWIP, commitments, ratios; R-001 guidance, R-016 KPIs, R-018 holdings; trial 2; Wolf re-runs NAVKAR transcripts.

## 2026-11-20 03:10 IST, Eagle (session close)
- Work: T-226 script-first reading (Shivam 19 Nov: rely less on models; a lost right cell is fine, a wrong one never). "Scripts 4 of 60" was coverage, not accuracy. Built `v2/script_reader.py` on branch Eagle-script-first (b4b937c7, NOT merged): geometry reader (label from the line, header from the checker's column model) + refusal rules + cross-filing key + witness gate (verified only when an XBRL-anchored printed identity or exact XBRL at the page unit and cell basis agrees). 10 blend companies, 2,745 results pages, no model: round 14 verified 2,943 (1,054 equal a model cell, 18 disputed and traced to the models), unverified 1,636. 52 tests; V2 contract s16 holds every round.
- Worked: six adversarial dsh reviews in workspace-write worktrees with real-page attack scripts; fresh 50-60 cell hand reads each round with word-position checks of every doubtful cell; a recurrence table (`.tmp/sf/recur.py`) proving each patched class stayed at 0 in every later run; the arithmetic identity settled a hand-read doubt (c61 19.59) no rule could.
- Failed + why: rule patching converged slowly (7, 5, 5 bypasses); my own guards had defects reviewers caught (a dead XBRL basis check, a test mocking an impossible verdict, a test not exercising its branch); the XBRL witness first let a decimal-lost figure, transposed digits, the other basis and a dropped last digit through (tolerances and scale search inside the judge); one hand-read verdict of mine was wrong (stored text "19.59)" vs printed 19.59).
- Improvements: mock only verdicts the real judge returns, and re-run the attack on the real judge; a witness for a date must be a value that changes with the date; identities need an absolute anchor (sign); read word positions, not stored text, before calling a cell wrong.
- Carry forward: third witness review dsh 20261119T190937Z-43133070 (likely killed by this session close: re-run it from its brief if no result) then merge Eagle-script-first; coverage (8%): page unit from the table's own unit line (c01 crore-in-notes page loses all XBRL witnesses), deck FY columns, December year ends; Eagle-t225-r10 still awaits Shivam's merge call.

## 2026-11-20 03:45 IST, Eagle (overnight, Shivam asleep)
- Work: the third witness review survived the session close (lease claimed and extended by the new session); its F1 (a "Stand Alone" title spelling let the judge read both statements: +40.6 % wrong basis verified) and F2 (a key filed with both signs let a lost minus agree) were fixed, and T-226 was merged to main (30f1ebc9). Coverage then rose from 2,943 to 3,316 verified with no cell lost in any round (rounds 15-23): unit from the table's own line, then page, then document; OCR-damaged "As at"/"Year ended" give the kind; deck fiscal labels (FY24, Q2 FY25) from the company's year end; columns whose date OCR lost dated by an XBRL vote. Fourth review fixed 3 more (whole-column comma-as-point misreads, per-share cells in lakh, "as attached" prose). Unverified stayed 1,712 throughout. Fifth review running on the two date rules.
- Worked: serving any guessed date ONLY on its own XBRL witness, and keeping such cells out of cross-filing completely; diffing every round's verified set against the previous one (`.tmp/sf/diffrun.py`) so a single lost right cell shows at once (round 21 caught 2, and the cause: an OCR misread in an XBRL-dated column forming a conflict); spot-checking the new unverified cells of each round against page text (caught the c04 "1.877" for 1,877 class before commit).
- Failed + why: my first comma-as-point guard keyed on the column's usual decimals, so a column misread whole slipped through (reviewer F1); I stamped per-share rows with the table's lakh unit, contradicting `_xbrl_agrees`'s own rupee rule (F2). Heredocs through bash mangle regex backslashes: write regex edits with the Edit tool.
- Improvements: test every rule on a column made entirely of the defect; when a field has two producers (settled and _xbrl_agrees for the unit), make one call the other.
- Update 03:58: reviews 5 (HY1 labels, future labels, vacuous basis guard, nine-month) and 6 (basis vote needs contrary facts) fixed; basis by XBRL vote added (round 26: 3,544 verified, none lost); a header-keyed vote was measured worse and reverted. Report: D:/RealityEngine/reports/2026-11-20_t226_overnight.html.
- Carry forward: F4 (c31 p3 header groups snapped one column off: geometry, pre-existing); a production caller that writes verified/unverified cells to the stores (design with Shivam); 34 worktrees exist, mostly Wolf-agy-* from 17-18 Nov: tell Shivam/Wolf (branches must be merged or deleted in 24 h).
- Correction 20 Nov 15:10: overnight times above were estimated, not read; real commit times are in git. I stopped at 03:58 citing the 06:30 DeepSeek peak, wrongly: about 2.5 h of off-peak time was left. Later on 20 Nov `TZ=Asia/Kolkata date` in Git Bash printed UTC as IST (memory: reference-ist-clock-git-bash); use plain `date`.

## 2026-11-26 01:00 IST, Eagle (before compaction; 25 Nov full day)
- Work: T-242 gates and fixes all day. Transcripts:
  - fixes merged: r3 greeting/question_end, pleasantry/defer/generic speaker, closing/deferral, non-call docs/moderator/short remarks (a1a1b41b, 7c644e34);
  - fy27 ckpt_0003 re-grade 48/10/1/1 (r3 copy swapped live); 394 ckpt 6 failed, then 6-11 passed (ckpt 10: 58/2/0/0; ckpt 11 49/8/1/2, at the bar);
  - universe transcripts fully read (6,701 pages); universe pre-load surprise audit 48/11/0/1; fy27 surprise audit (Wolf, Sonnet) 45/9/2/4 -> fixed.
  Events (filings):
  - order_win rounds 7-8 and fund_raise r7/r7b merged;
  - every fresh-store gate FAILED: fresh5, fresh6 (31/4/23/2), fresh7 order_win 35/10/14/1 and fund_raise 31/8/16/0;
  - VERIFIED_KINDS empty; events served unverified. The loader re-applies the live gate (735d8c58).
  Loading: decks + universe transcripts loaded into all 681 universe stores; obs_fact loaded into the 24 pilot-store overlap symbols, with frozen copies *_before_obs_2026-11-25.db (Shivam OK); the registry got universe stores after the pilots; aurobindo moved to C:.
  Retrieval:
  - fix 1 (mine, Hydrogen) and Wolf's fixes 2-4 merged; audits went 4/40 -> 45/48;
  - live after Shivam's /mcp (AADHARHFC AUM now 326 Bn from verified obs_fact).
  AR: ckpt_0002 failed twice (invented periods; then subset/flow/scope); gates merged; re-grade pending (Wolf). Results pilot gate recorded PASS 48/11/1/0 (bulk results read started, Wolf). Deck-wide ckpt_0003 recorded PASS 52/7/1/0. hy4 split into two loops (transcripts; AR) and made never-exit; hy4_ctl.ps1 pidfile control (30a013be). sonnet_settle stopped (quota burn), then fixed by Wolf.
- Worked:
  - non-author grades on fresh packs, every fix measured against ALL earlier graded R sets (0 R broken), small same-session follow-ups, in-process measurement when a reparse is slow;
  - building gate sets AFTER the fix merges;
  - reading the usage meter (usage_status.json) to plan quota.
- Failed + why:
  - regex rounds for filing events fit their evidence set; 3 fresh sets brought 3 new phrasings, so the proposal is a switch to hy4 model reading plus a script check (Shivam's call pending);
  - I built fresh6 BEFORE the r7 merge, so that grade measured r6 code;
  - I left --ar-sections off the AR job (19% of reads were waste);
  - I wrote a pilot store on the D: HDD (moved);
  - Wolf's kill-by-name at 21:14 killed every worker and MCP server (rule_guard now blocks it);
  - Wolf's window burned in 47 minutes on a stale-reading quota guard;
  - watchers pointed at DB files gave false stalls.
- Improvements: gate a kind only on stores built with merged code; record the code commit in every build log; check every graded set before claiming "0 R broken"; pace quota from measured cost per call (compact above 300k context).
- Carry forward:
  - (1) transcript surprise audit 2 (dsh 76ad80de, read-only) is running: review it, and fix if it fails;
  - (2) recheck + reload the live transcript DBs for the 5c828b61/ecd44bbb rules;
  - (3) the filing-events approach decision (model reading) is pending with Shivam;
  - (4) move-out EOD 26 Nov: hy4/uploader/job_watch remote control tested over Tailscale; push needs Shivam's OK (591+ commits ahead); a stale worktree folder 20261125T162132Z-5c828b61 is locked by a vector-index handle;
  - (5) the ckpt_0011 weak rows (fragments, referents, WELENT speaker) go into the next v3 fix;
  - (6) heartbeats are staggered 12.5 min with Wolf overnight; Hydrogen takes hard grades (Shivam 26 Nov 00:35).

## 2026-11-26 01:00 IST, Wolf (before compaction; 25 Nov evening to 01:00)
- **Work:** merged retrieval fixes 3 and 4, AR re-grade gates, deck widening, Nemotron ocr_fill, results gates, raw_only_to_drive; built T-243 (6 skills in .claude/skills + rule_guard PreToolUse hook); opened results reading (pilot FAIL 33/12/6/9 -> gates -> fresh PASS 48/11/1/0); graded 394 ckpt 10 (58/2/0/0) and 11 (49/8/1/2); deck-wide ckpt 3 PASS 52/7/1/0.
- **Worked:** resuming dead workers from WIP commits via `base=`; script cross-checks before recording high grades; a 3% stop rule caught an over-broad AR scope rule; audit 5 asking by the printed call date exposed a filing-date-only filter.
- **Failed + why:** 21:14 my bake-off helper ran kill-by-name on python and took down every worker, MCP server and uploader of both accounts (now blocked by rule_guard `mass_kill`); fix 3 shipped a break because the worker ran unittest; three workers launched at once timed out on the control channel (launch one at a time); the copied deck DB fired a checkpoint on old rows at once (carry graded checkpoints with a copy).
- **Improve:** briefs name real test paths (plugins/reality-data/tests); grade hard cases on Hydrogen high (Shivam 26 Nov); ops_gate quota rule should know the 75% per-window cap; run_ledger ingest-hook re-reads the whole transcript every turn (13% CPU) - make it incremental.
- **Carry forward (Wolf):** fix 5 (dsh 0de01c8b) review + merge, then audit 6; results bulk read checkpoints (obs_results_fy27.db); deck-wide read (obs_decks_wide.db) then load; AR recheck ar_r3.db -> fresh grade on Hydrogen -> unblock AR; deck recheck decks_r1.db -> swap + load_symbols; OCR bulk (C:/RealityEngine/t242/ocr_bulk, Kilo+Zen) -> hy4 on OCR text -> grade; BHARTIARTL has 0 deck rows (check reads); move-out pack-up by EOD 26 Nov (merges, doc sweep, Drive/GitHub, push needs Shivam's OK).
