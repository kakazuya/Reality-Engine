# Workspace journal: learnings across sessions (newest first)

Ruling (Shivam, 13 Nov): every session writes an entry twice: once on crossing ~400k tokens of context, once when
Shivam says to wrap up. Each entry: work done, what worked, what did not and why, what to improve in input / design /
architecture / execution / output. Every new session reads the latest entry first (the start hook prints its
"Carry forward" bullets). Transcripts and the run ledger keep WHAT happened; this file keeps WHY and what we learned.
Keep entries short; facts with numbers; no repetition of STATE or tickets.

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
