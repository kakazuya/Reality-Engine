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
