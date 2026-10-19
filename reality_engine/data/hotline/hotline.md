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
