# Hotline log (append-only, newest at the bottom; format in README.md)

### 2026-10-20 03:15 IST Claude hotline opened
Shared context for Claude and the DeepSeek / Go workers is live: read README.md in this folder first. First worker
job: write decisions.md (the Chesterton-fence log) from the session digests in generated/sessions/.

### 2026-10-20 03:23 IST DeepSeek decisions.md written
Wrote `decisions.md` (this folder) from the five session digests in `generated/sessions/` (INDEX.md order: 10203977,
09835e54, 4d48c9da, 8fcab707, 0f0c2aa6). It has **121 entries**, grouped by topic, newest first inside each topic;
every entry gives what happened or broke, the fix or rule, why it exists, and what breaks if removed, with the digest
date and the commit only where the digest shows one. Entry count per topic: DeepSeek harness and worker protocol 14,
OpenCode / Go / Zen limits 11, transcript readers and concall extraction 18, embeddings and vector indexes 24,
PIB and the policy register 10, Drive upload 9, crash recovery and job durability 9, market-data derivations 2,
data correctness and query layer 18, hotline and worker context 6.

Sourced only from the digests; no facts from elsewhere. What the digests do not settle (kept as open, not guessed):
whether Zen works at 3 calls at a time after the IP block; the Beam/MiniMax blind label check (not run, ingestion not
started); Nebius batch creation refused with 403; the 768-dimension Gemini-001 storage check; Nemotron 1B-NVFP4 and
cross-host vector parity (untested; no 3B size exists); policy-register final completion; the snapshot keep count and
the order-win LLM decision; and the digest set stops at 03:13 on 2026-10-20, so nothing after that is covered here.

### 2026-10-20 03:40 IST Shivam (relayed verbatim by Claude) department structure and order of work
Shivam's words: "You become a senior, DeepSeek becomes your junior. And DeepSeek has 2 reportees, Beam and Minimax. So
Beam and Minimax will report to DeepSeek. DeepSeek will report to Opus. That's how the process would run. Like a
department." And: "after beam and minimax complete the transcripts for other years apart from 2026 and the 2026 other
than DeepSeek['s] transcripts as well, [after that] we will do the embeddings again on ARs" with Nemotron FP4 (1B NVFP4,
chosen over BF16 on 2026-10-20: same retrieval at $0.010 vs $0.015 per M tokens). And: "don't hitch it [FP4] for the
transcripts, hitch it for the annual reports only. Currently transcripts I will run from beam and minimax first,
because it has context and meaning, not just bare facts."

What this means for you (DeepSeek):
- Beam (beam-free) and MiniMax (minimax-m3.1-flash-free~high) read transcripts into concall_facts.db; you review their
  output for meaning, label and period correctness, report to Claude in this file, and propose prompt fixes. You do
  not read transcripts in bulk yourself (paid); you check samples.
- Transcript search vectors: Nemotron-3-Embed-8B (DeepInfra) for transcripts, decks and macro/PIB
  (data/vector_index_nemotron8b). Annual reports: Nemotron-3-Embed-1B-NVFP4 later, after the transcript reading ends.
- Started 03:21-03:36 IST: Beam 32 calls at a time, MiniMax 16, both Go keys, queue shard Beam doc_id%4 in {1,2,3},
  MiniMax doc_id%4 == 0, PEAD/Telegram companies first then newest first.

### 2026-10-20 03:47 IST DeepSeek reader review 1 (Beam vs MiniMax)
Read `reality_engine/data/hotline/README.md` first, then reviewed 6 Beam + 4 MiniMax `status='ok'` concall docs (8 random items each, seed 20261020, 80 items) against the source PDFs (pymupdf). Beam: 46/48 faithful, 2 material errors (ESTER: INR 1,600 cr ELITe JV total booked as Ester capex, though management says it is off Ester's books and Ester's share is ~INR 250-270 cr; GRWRHITECH: 300+ studios labelled `new` though "well on track" means maintained). MiniMax: 30/32 faithful, 2 material errors (SINGERIND: Rs 2.3 cr income tax taken from an analyst's question with no label; BASF: global parent capex in the India guidance list). The Rs 200 cr SINGERIND order-book item is a field defect, not a misattribution: `inflow_or_pipeline` labels it "confirmed analyst's figure". Verdict: Beam keep with fix; MiniMax keep with fix, conditional secondary — gate the numeric lists with a value-in-quote check and re-test before scaling (reader-admission verdict; the running job and DB were not touched). Full report, every wrong item with quote and reason, and the prompt fixes: `reality_engine/data/hotline/review_readers_1.md`. The DB was live during the review (Beam 93→230, MiniMax 13→54 `ok` docs); sample docs unchanged; no DB writes.

### 2026-10-20 03:55 IST DeepSeek prompt v3 and 6.6 gate spec
Wrote `reality_engine/data/concall_pilot/prompt_v3.md` from v2: same list/field names, enums and placeholders; v2 rules
1-10 retained and renumbered to 13, with review §6.1-6.5 and 6.7-6.10 merged; short ELITe/BASF scope example and
SINGERIND analyst-number example included. One optional field placement added, `question_gist` on
guidance/capex/key_numbers, so 6.2/6.6 have a carrier for a confirmed analyst's number; it stays in `item_json` only, so
`cc_items` columns, DDL and the loader's value/metric mapping are unchanged. `reality_engine/data/hotline/prompt_v3_changes.md` has the v2 -> v3 rule map
and the precise 6.6 mechanical gate: lists `key_numbers`, numeric `guidance`, `capex`, `order_book`; fields `value`/
`amount`; token-level quote match, with only the exact "(confirmed analyst's figure)" + analyst-carrier + non-bare
management-confirmation exception; drop before insert and audit in `checks_json`. The review's §6.6 note that
`cc_item_checks.value_in_quote` is NULL for Beam/MiniMax rows is carried into the spec as a re-run requirement. No
database, loader or running job was touched; field names came from the loader DDL and the review, not a DB read.

### 2026-10-20 04:14 IST DeepSeek reader review 2 (Beam vs MiniMax, prompt v3)
Read README.md, `review_readers_1.md` and `prompt_v3_changes.md` first. Reviewed **all 4** MiniMax v3 docs (48352 KAJARIACER, 89596 TRITONV, 61804 NH, 45580 IZMO; run_at 04:02-04:04) and **4 random** Beam v3 docs (58510 MOLDTECH, 91769 V2RETAIL, 39301 HINDALCO, 31717 FREDUN; seed 20261021), 8 items each = 64, against the PDF transcripts; 64/64 quotes are verbatim. Material errors: **0/32 MiniMax, 0/32 Beam**. v2 was 2/48 Beam (4.2%) and 2/32 MiniMax (6.3%), but the samples are not paired: neither BASF nor SINGERIND (the v2 MiniMax failures) nor ESTER/GRWRHITECH (the v2 Beam failures) was re-read, so the rate change is a new sample, not a measured fix; 0/32 still has a 95% upper limit of 10.9%, and Fisher p is 0.51/0.49. Item-level: every analyst-origin number (KAJARIACER #0/#8, NH guidance#5, FREDUN guidance#6) identifies the analyst's figure — #8 and NH#5 carry the exact `(confirmed analyst's figure)` label, #0 an extended label and passes on the number being in its own quote; every subsidiary/JV capex or guidance names its entity (Kerovit, Tritonvalves Future Tech, Climatech, izmoMicro); reiterated guidance uses `maintained` on 10 items; no null-amount capex. **Condition met as intended, not literally:** 3 analyst-origin numbers are stored (all labelled), and KAJARIACER's INR 120 cr Kerovit capex is still in the company capex list but labelled "not prospective company capex guidance". **Main operational finding:** the new gate counts are on only **52/111 Beam v3 docs and 1/4 MiniMax v3 docs**; gated and ungated docs are interleaved in run order (two loader paths writing), so the gate did not cover 3 of the 4 MiniMax docs and no per-reader gate rate can be quoted. Also, `"Yes, yes, this number is correct."` (6 tokens) passes the bare-confirmation rule. Verdict: **MiniMax scale up yes**, conditional on confirming the gate on the MiniMax worker and fixing the 15 TRITONV `basis` blanks + that bare quote; **Beam keep** as primary, lint fixes only (order_book duplicates key_numbers, capex+inventory, period "current quarter"/"later", one blank unit, Novelis unnamed). Speed: MiniMax 177 s/doc vs Beam 56 s/doc, both free and inside the 300 s rule. Correction to review 1: "Future Tech" is real ("Tritonvalves Future Tech Private Limited"), so its "invented entity" note in §4.2 is wrong. DB read-only; no running job touched. Full report, every flagged item, gate table and the paired-doc comparison: `reality_engine/data/hotline/review_readers_2.md`. What it does not show: whether BASF/SINGERIND now pass under v3, recall/completeness, and the 111-doc Beam v3 corpus after 04:07 (Beam v3 grew 89 -> 111 during the review).

### 2026-10-20 04:25 IST Claude review 2 accepted; correction on the "ungated path"
Thanks for review 2. Condition 1 was a logging gap on my side, not an ungated path: every doc runs machine_check ->
value_in_quote_ok, but checks_json only recorded gate keys when an item was DROPPED, so 3 clean MiniMax docs showed no
gate counts. From now on checks_json always carries "vq_checked" (items examined by the gate) plus the drop counts.
MiniMax scaled to 16 workers on prompt v3 with --reread-models, so BASF (14752) and SINGERIND (80180) are re-read
under v3 in their queue turn; please use them as the regression test in review 3. Condition 2 (basis blanks, bare
confirmation on KAJARIACER key_numbers#8) noted for prompt v4 with the order_book/key_numbers duplication.
