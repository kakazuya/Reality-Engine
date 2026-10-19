# Hotline: shared context between Claude (orchestrator) and DeepSeek / Go workers

Set up 2026-10-20 on Shivam's request: every worker must see what Claude sees (the whole conversation, the tool calls,
the tries and fixes, the live machine state), and both sides read and write the same files, so a question asked
of either is answered from the same facts.

## Read first, in this order
1. `tasks/FRAMEWORK.md` (authority, Shivam's rules), then `tasks/STATE.md` (live hand-off).
2. Claude's memory: `C:\Users\warri\.claude\projects\C--Users-warri-Downloads-Info-Diffusion-Model\memory\MEMORY.md`
   (one line per memory; open the linked files that bear on the task). Facts there are dated; check before acting.
3. `decisions.md` (this folder): what was tried, what broke, the fix, and why the fix exists (Chesterton fences).
   Do not remove or bypass a fence without reading why it is there.
4. `generated/sessions/INDEX.md`, then the session digests it lists (Shivam's messages, Claude's replies, one line
   per command run with the start of its result). Newest session first.
5. `generated/context_now.md`: running jobs, log tails, upload/disk rates, Drive upload timetable.

`generated/` is rebuilt by `run_deepseek_harness.py` before every worker run (session_digest.py + worker_context.py),
so it is never older than the task. It is git-ignored; everything else here is committed.

## Write
- `hotline.md`: append-only, newest at the bottom. One entry per question or answer:
  `### <YYYY-MM-DD HH:MM IST> <who: Shivam | Claude | DeepSeek> <topic>` then the text. Answers cite the file and line
  their numbers come from, and say plainly what the files do not show.
- `decisions.md`: append when a fix or a rule is made: what happened, the fix, why, and the commit.

## Rules for workers
- Facts only from these files, the repo and the machine; say "not in the files" rather than guess.
- Never print or copy API keys. Never start, stop or edit a running job unless the task says so.
- Shivam's standing rules (FRAMEWORK.md, memory): free models unless he approves paid; DeepSeek runs at xhigh,
  off-peak 15:30-06:30 IST; DeepSeek harness runs DeepSeek models only (Beam, MiniMax, LongCat go through OpenCode).
