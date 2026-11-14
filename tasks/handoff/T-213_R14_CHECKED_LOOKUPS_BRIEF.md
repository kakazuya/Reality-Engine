# T-213 round 14: planned lookups, code checks, code-written follow-ups (no pack)

Archived 14 Nov (Wolf): the code is on tag `archive/Wolf-T-213-r14b` (not merged; replay lost to DS lean run B). Paths below are under reality_engine/ on that tag.

Ticket: T-213

Goal: one answer loop, driven by code, for any model. The model names the exact facts it needs; code fetches only
those rows; the model answers with citations; code checks the answer and, when a check fails, sends the model ONE
follow-up message written from what the check found; at most 2 follow-ups. No evidence pack, no seed pack (Shivam 14
Nov: dumping a gathered pack on the model is rejected).

Why (round 13 blind grades, Opus-graded, 236 answers): the store held the fact in every miss; 36 of 44 partly/wrong
answers were the answerer stopping early or searching the wrong source. Examples of the failure shapes (no truths here,
only shapes): an answer says the earlier guidance was "unchanged" without citing the earlier call; a "not found" while a
plain text search of the store finds the phrase; a "management said" figure whose transcript speaker is an analyst; a
correct percentage next to an amount stated 10x. Pack runs cost ~1M tokens/question; tool runs ~2 calls/question.

Evidence (read these, nothing else needed to start):
- Lookups: `reality_engine/scripts/p3ask.py` (`run(db, tool, args, qid, log)`, `TOOLS`, `_page`) -- call in-process.
- Model call over the Go API: `reality_engine/answer/plan_model.py` (`URL`, `resolve_key`, `call_model`; stable
  session id from ``session_id` in reality_engine/scripts/go_session.py`). Hydrogen: `reality_engine/answer/agy_call.py`.
- Validated plans and the menu: `plan_model.validate`, `reality_engine/answer/menu.py` (company menu under 8,000 chars).
- Number matching rules already written: `reality_engine/answer/answer_step.py` (offline re-check, separator/scale
  variants, calc inputs). Reuse; do not fork.
- Questions: `D:/RealityEngine/bluestar/answers/questions_in.json` (64, with as_of). Second company for the smoke:
  `D:/RealityEngine/aurobindo/aurobindo.db` with its questions file beside the answers folders.

Design (fixed; change only with a written reason in the result):
1. Turn 1 (model): question + as_of + company menu -> JSON plan: `parts` [{id, text, kind}] where kind is one of
   figure | compare_periods | change_between_calls | management_said | list | computed | other, and `lookups`
   [{part, tool, args}] (<= 12). Validate with `plan_model.validate`; one repair call on invalid JSON.
2. Code runs the lookups through `p3ask.run` with as_of forced, and returns COMPACT items: id, value/quote (<= 600
   chars), unit, period, basis, doc_key, page, known_at, speaker/role for transcript rows. No page dumps unless the
   model asked `page`. Item ids are stable (`L<n>`).
3. Turn 2 (model): answer JSON {answer, parts: [{id, status: answered|not_found, items: [L..], numbers:
   [{value, unit, items, formula?}], quotes: [{text, item}]}]}. The model may ask for more lookups instead of
   answering (<= 2 extra lookup turns, <= 20 lookups total per question).
4. Checks (code only, no model), each producing a machine-readable failure:
   C1 coverage: every part answered cites >= 1 item; every part has a status.
   C2 numbers: each number in the answer text matches a cited item value (separator, crore/lakh/mn/bn, % variants) or
      is recomputed from its cited inputs by `formula` within rounding.
   C3 quotes and speaker: each quote is a normalised substring of its item; a part of kind management_said whose
      cited transcript item has an analyst/moderator speaker fails.
   C4 not-found probe: for each not_found part, script search (FTS `search` with the part's key terms and the
      question's nouns, numbers in all variants, `cells` and `kpi` by the part's metric words) as_of; any hit on a page
      or row the model has not been shown fails the check and lists the top 3 (doc_key, page, known_at, 200-char
      snippet).
   C5 kind rules: change_between_calls / compare_periods must cite items from >= 2 distinct documents or periods;
      management_said must cite the latest transcript known on or before as_of unless the part names another call;
      every cited item has known_at <= as_of.
5. Follow-up (code-written text, sent in the SAME conversation): one short paragraph per failed check naming the part,
   what was missing, and the concrete next lookup or the probe's pages. Never "look harder", never "are you sure".
   Max 2 follow-ups; then accept, with each still-unsupported part labelled "not found after: <lookups + probe>".
6. Model adapters: `go` (DeepSeek V4.1 Flash, max effort, Go key 1, stable session id) and `agy` (Hydrogen high,
   tools disabled in the prompt: the loop is the only route to data). Same loop, same checks.

Steps:
1. Tests first, `tests/test_checked_lookups.py`, model mocked (fixture items, no store needed for
   C1-C3 and C5; a tiny fixture sqlite for C4): one failing case and one passing case per check; a follow-up text
   test (names the part, contains the probe's page, contains no generic exhortation); a loop test (fail -> follow-up ->
   pass; and fail x3 -> labelled not_found_after); token/turn counters recorded.
2. Module `answer/checked_lookups.py` with CLI:
   `python -m reality_engine.answer.checked_lookups --set bluestar --model go|agy --out <dir> [--limit N] [--qids ...]`
   writing `answers.jsonl` (ds_a shape: qid, question, as_of, answer, tools, sources, confidence + turns,
   followups, checks_failed_first, checks_failed_final, tokens_in, tokens_out, seconds) and `calls.jsonl` (one line
   per model turn and per lookup).
3. Smoke, off-peak only, model `go`: 5 Blue Star questions (`--limit 5`) and 3 Aurobindo questions. Report per
   question: turns, follow-ups sent and why, tokens, seconds. Do NOT grade answers and do not open any truth, grade,
   report or answers folder; Claude grades blind.
4. Docs: an "O21. Checked lookups (T-213, round 14)" block in `docs/DEVELOPER_GUIDE.md` (design, checks, CLI, files);
   PROGRESS_NOTES lines.

Files: new `answer/checked_lookups.py`, new test file, `docs/DEVELOPER_GUIDE.md`; small reuse edits in
`answer_step.py` / `plan_model.py` only if a function must be made importable (no behaviour change, say so). Stores are
read-only. Outputs of the smoke under this worktree's `.tmp/r14_smoke/`.
Accept: python -m pytest tests/test_checked_lookups.py -q
Test command: python -m pytest tests/test_checked_lookups.py reality_engine/tests/test_plan_model.py -q
Pitfalls: no evidence pack anywhere (do not import evidence_pack.gather); a check must never pass an answer by
loosening (no fuzzy number match beyond the listed variants); follow-up text must come only from check results; as_of
on every lookup; run pytest per file; check free RAM before the smoke (stop under 2 GB); never print the key.
Stop if: a check needs a per-question or per-company rule; the Go API refuses tool-free chat turns; peak hours begin
(06:30 IST) before the smoke -- leave the smoke for Claude to run and say so; 3 hours.
Budget: 3 hours, 300 tool calls.
