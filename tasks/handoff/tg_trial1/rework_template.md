Goal: trial 1 rework of batch {b}. A first pass (free model) answered {batch} but gave up early: most partly/not_found answers used one search call. Re-answer those questions properly from each company's own store, so the trial measures the store, not the answerer.

Files:
- Read: {batch} (the questions) and {prev} (first-pass answers; keep any answer the check below does not list, copy its line as is).
- Write (in your worktree): trial1/answers_{b}.jsonl and trial1/calls_{b}.jsonl. Commit nothing else.
- Method, answer format, tool routes by theme and rules: tasks/handoff/tg_trial_answer_brief.md in your checkout (read it first, all of it), with {answers} = trial1/answers_{b}.jsonl, {calls} = trial1/calls_{b}.jsonl, {batch} = {batch}.

Steps:
1. Set REALITY_DATA_ROOT=C:/Users/warri/Downloads/Info_Diffusion_Model/reality_engine/data.
2. Copy every first-pass line whose status is "answered" into trial1/answers_{b}.jsonl unchanged.
3. For every other qid: answer again following the routes by theme, at least three different tools before partly/not_found, every call through p3ask with --qid <qid> --log trial1/calls_{b}.jsonl (a call without --log does not count).
4. Run python -m reality_engine.scripts.tg_trial check --answers trial1/answers_{b}.jsonl --calls trial1/calls_{b}.jsonl --batch {batch} --min-kinds 3 . A copied "answered" line with no logged call shows up as "no logged call": redo it with logged calls too. Repeat until it prints "rework": 0 or each listed qid has had 12 calls.

Accept: the check prints "rework": 0 (or lists only qids with 12 logged calls); one valid JSON line per qid.
Evidence: first pass of batch 04 had 30 of 44 answers partly/not_found after a single search; batch 03 logged no calls at all. p3ask works: python -m reality_engine.scripts.p3ask --db D:/RealityEngine/tg_build/measure10/c05/c05.db --qid 1 --log trial1/calls_{b}.jsonl fact symbol=MANINFRA metric=revenue as_of=2026-11-16 returns H1FY27 revenue.
Stop if: check passes, or 4 hours.
Budget: 4 hours, 12 tool calls per question.
No-ticket: Telegram store trial 1 (Shivam 16 Nov: build all, then randomised trials), tracked in store repair notes R-001..R-013
