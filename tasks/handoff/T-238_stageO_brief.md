# T-238 stage O brief: transcript statements as whole management passages

Ticket: T-238 (Shivam 23 Nov 2026). Reviewer: Wolf (Opus).

Goal: Opus diagnosis `D:/RealityEngine/t238/statement_gap.md` (read it): hy4 matched 340/456 Opus statements on
SOMANYCERA transcripts; of 116 misses, 79 are the same sentences split over 2-3 hy4 rows, real loss ~8%. Sample of 40
misses: 26 split rows, 10 kept only as a number/guidance row, 2 truncated at PDF line breaks, 2 analyst text. 6 of 20
hy4-only statements are fragments with no subject ("It's going to be about the same."). Apply the three changes there
before hy4 reads the remaining ~4,700 transcript pages of the 91 companies (that job is paused for this).

Evidence: `reality_engine/v2/observations.py` (`PROMPT_TRANSCRIPT`, statement/guidance record checks, stage M 17.v in
`docs/V2_SCHEMA_CONTRACT.md`); Opus reference `D:/RealityEngine/t237/opus_facts.db`; stage-M hy4 output
`D:/RealityEngine/t238/obs_transcripts_m.db`; store `D:/RealityEngine/tg_build/measure10/c48/c48.db`.

Steps:
1. Prompt: a statement is one management speaker's continuous passage on one topic, verbatim from its first word to
   its last full stop (usually 2-5 sentences); never cut at a PDF line break; a passage crossing a page is stored on
   its first page. Management speakers only; never include the analyst's question; when an answer needs its question,
   put the topic in a new `question_context` field.
2. Every guidance row, and every number row whose sentence has forward or causal words (will, should, expect,
   guidance, target, because, due to, next N months/quarters), also emits that sentence as a statement row.
3. Script checks: quarantine a statement without end punctuation or ending on a function word (and/the/of/to/in);
   unverified `no_subject` when the row has no noun subject beyond pronouns and no measure; guidance whose value is in
   no statement row on its page is flagged `guidance_without_statement`.
4. Scorer: sentence-level match (an Opus sentence counts as matched if any hy4 statement on page +/-1 contains it at
   >= 80% token overlap); drop Opus statements whose speaker is an analyst.
5. Scoped re-read: SOMANYCERA's 166 transcript pages only (hy4); report sentence recall vs Opus before/after,
   fragments, guidance_without_statement, tokens/page.
6. Tests; doc 17.v update; DEVELOPER_GUIDE line.

Files: `reality_engine/v2/observations.py` (prompt, record parsing, statement checks only), tests, the two docs.
Another worker (stage N) edits the same file for deck period/basis/alias rules: do not touch those paths. Do not edit
tasks/STATE.md.

Accept: tests pass; typecheck clean; regress observations gate 0 newly broken on `D:/RealityEngine/t230/obs_91_i.db`;
SOMANYCERA sentence recall >= 88% with fragments <= 5%.

Stop if: recall falls below the stage-M baseline.

Budget: about 2 hours, DeepSeek max effort.
