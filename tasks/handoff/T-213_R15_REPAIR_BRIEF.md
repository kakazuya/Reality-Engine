# T-213 round 15 repair pass: fix ONLY the answers the code checker flagged

Ticket: T-213
Goal: run B answered the 64 BLUESTARCO questions (54 right, 10 missed). A code checker
(`reality_engine/answer/answer_checker.py`) has read that answer set and the store and flagged
15 answers, each with a follow-up text built ONLY from its five checks. Repair the flagged
answers from the store. Keep every unflagged answer byte-for-byte: the checker says nothing
about them and editing them only risks the 54 that are right.

Inputs (read-only):
- `/CHECK_DSB` — the checker output, one JSON line per answer:
  `{"qid", "checks": [{"id", "ok", "fact"}], "followup"}`. `followup` is empty for an answer
  that passed all five checks. Repair only the lines where it is not empty.
- `D:/RealityEngine/bluestar/answers_ds_b/answers.jsonl` — the run-B answers, one line per
  question (qid, question, as_of, answer, tools, sources, sql_reason, confidence).

The five checks the follow-up text comes from (no model wrote it, no grades were used):
- **C1 look-ahead**: a cited source, or a document named in the answer ("FY26 annual report",
  "Q2FY27 call"), is known after the question's `as_of`.
- **C2 calls covered**: a question asking how something changed across calls must cite every
  transcript whose call falls in the window the question names (or the last four calls).
- **C3 speaker**: a sentence that attributes figures to management must have each figure on a
  cited transcript page under a management speaker label; the fact names the speaker the page
  shows instead.
- **C4 scope**: a segment question must carry the scope word, and the segment's own printed
  figure for that metric and date (found in the store) must be the one used — not the
  company-wide figure.
- **C5 dug before "not found"**: a part answered "not found / not stated" needs at least three
  of search, semantic, topic, cells and statements, a `page` read, and four distinct lookup
  tools in the run's calls log.

How to ask the store (shell, one call per lookup), from the repo root. Set this in EVERY shell
call, before python: `$env:REALITY_DATA_ALLOW_PAID_EMBED='1'` (PowerShell).
```
python -m reality_engine.scripts.p3ask --db D:/RealityEngine/bluestar/bluestar.db --qid <qid> --log .tmp/r15/answers_repaired/calls.jsonl <tool> key=value ...
```
Tools: `fact`, `cells`, `fin`, `ratio`, `kpi`, `guidance`, `statements`, `topic`, `semantic`,
`holding`, `tech`, `docs`, `search`, `page`, `calc`, `sql`
(the arguments are in `tasks/handoff/T-199_ANSWER_BRIEF.md`). Always pass
`as_of=<the question's as_of>`. Read WHOLE pages with `page`; a call or deck page can be long —
read the page the fact names and its neighbours. Never narrow a lookup to a 600-character item,
never run a store-wide keyword probe to guess, and there is no lookup cap: use as many calls
as the flagged part needs.

For each flagged qid, in order:
1. Read its `followup` text and its five checks. The facts name the document, page, missing
   call, speaker or printed figure — start there, with `page` on that document.
2. Confirm the fact against the page: is the figure on that page? under that speaker? is the
   named call missing from `sources`? is the segment's printed figure different? The checker
   can be imprecise about *which* part is wrong, so derive the correct part from the page.
3. Repair only the failed part. Keep the parts that passed verbatim (same figures, same
   sources). Use the store's printed wording; do not add a fact the page does not print.
4. Re-run the checker on the repaired line and read its output for that qid:
   ```
   python -m reality_engine.answer.answer_checker --db D:/RealityEngine/bluestar/bluestar.db \
       --answers .tmp/r15/answers_repaired --out .tmp/r15/recheck.jsonl --qid <qid>
   ```
   If a check still fails, one more repair round on that answer (max 2 follow-up rounds per
   answer). After the second round keep the better line and name the remaining flag in
   `change_note`.
5. Everything else stays as it is, including a "not found" that the store really does not hold
   — say which documents were read.

Output: `.tmp/r15/answers_repaired/answers.jsonl`, one JSON line per question for ALL 64
(unchanged ones copied from the input), same fields plus `"changed": true/false` and
`"change_note"` (what the checker flagged and what you changed; empty when unchanged).
`calls.jsonl` is written by p3ask. Both under `.tmp/r15/answers_repaired/` in your workspace.

Files: write only `.tmp/r15/answers_repaired/answers.jsonl` and `calls.jsonl` (and the
re-check output). The store, the run-B answer folder, the checker and everything else are
read-only. Do not edit code.

Accept: 64 lines, valid JSON, one per qid; every flagged qid either has `changed: true` with a
`change_note` naming its check, or `changed: false` with the reason the flag was not a defect.
Re-run the checker over the output folder and report the remaining flagged count.

Stop if: you would need to open anything under `D:/RealityEngine/bluestar/` other than
`bluestar.db` (through p3ask) and the input answers file; the grades, truth, key or any other
answer set (never); the web (never); p3ask fails for every call (report it).

Budget: 400 tool calls, 2 hours.
