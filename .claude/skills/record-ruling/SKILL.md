---
name: record-ruling
description: Record a new rule or correction from Shivam without losing a word - short line in tasks/RULINGS.md, his own words in RULINGS_VERBATIM.md, full wording kept forever in the ledgers. Use whenever Shivam gives a standing rule, changes one, or asks what an earlier rule said exactly.
---

# Recording rulings (Shivam 26 Nov 2026: two copies - never dilute a rule to fit a limit)

| Copy | File | Size | Read by |
|---|---|---|---|
| Short | `tasks/RULINGS.md` | <= 8,000 chars, 40 lines (doc_gate) | every session start |
| His words | `docs/rulings/RULINGS_VERBATIM.md` | no limit, append-only | anyone needing the exact rule |
| Full current + every earlier wording | `docs/rulings/RULINGS_FULL.md` | no limit, regenerated | toolings, reviews |
| Line history | `docs/ledgers/<FILE>_LEDGER.md` (RULINGS, STATE, AGENTS, TASKS) | no limit, append-only | audits |
| Before 8 Nov | `docs/rulings/RULINGS_full_2026-11-08.md` | frozen | history |

## Steps
1. Record: `python -m reality_engine.scripts.ruling add --section "<section>" --text "<short rule>" --quote "<his exact words>" [--check <gate tag>]`.
   The short text may be condensed; the quote is never edited (Hinglish/Hindi kept as he wrote it).
2. If the short file is full, condense OTHER lines - their earlier wording is preserved automatically: the pre-commit
   hook (`reality_engine/scripts/doc_ledger.py staged`) appends every added/removed line to the ledger and
   regenerates `RULINGS_FULL.md` in the same commit.
3. Memory: a feedback memory with the rule, **Why:**, **How to apply:**.
4. Tell the other manager (Eagle/Wolf) in 2-3 lines.
5. If the rule changes how work is done, update or add the skill that covers it (`.claude/skills/`).

## Looking up an exact earlier rule
`grep -n "<words>" docs/rulings/RULINGS_FULL.md docs/rulings/RULINGS_VERBATIM.md docs/ledgers/RULINGS_LEDGER.md`.
Rebuild the ledgers from git at any time: `python -m reality_engine.scripts.doc_ledger backfill`.
