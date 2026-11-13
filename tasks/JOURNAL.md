# Workspace journal: learnings across sessions (newest first)

Ruling (Shivam, 13 Nov): every session writes an entry twice: once on crossing ~400k tokens of context, once when
Shivam says to wrap up. Each entry: work done, what worked, what did not and why, what to improve in input / design /
architecture / execution / output. Every new session reads the latest entry first (the start hook prints its
"Carry forward" bullets). Transcripts and the run ledger keep WHAT happened; this file keeps WHY and what we learned.
Keep entries short; facts with numbers; no repetition of STATE or tickets.

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
