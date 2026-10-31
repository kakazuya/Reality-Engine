# Task — triage every NOT-IN-DATA case: fetch it, proxy it, or prove it is truly absent

## Goal
Shivam's rule (30 Oct 2026): "not in data" is not an acceptable answer by itself.

For every bank case that the v4 registry marks `not_in_data`, decide ONE of:
- **(a) FETCH:** the data can be obtained free and with modest effort (≤1 day of build for the whole class). Name the exact source (URL / API / file), the format, the history depth, the point-in-time column, and the target table/atom.
- **(b) PROXY:** the data is genuinely hard to get. Name the proxy or workaround from data we HOLD or can fetch (a), the assumption it rests on, and an honest confidence level. For example:
  - rainfall → IMD weekly + reservoir levels + kharif sowing;
  - consensus → our own estimate from trend + guidance + the opinions DB.
- **(c) ABSENT:** neither works. List what was tried and why it fails.

## Inputs
- `tasks/arch_v4/concept_registry.json` and `tasks/arch_v4/registry_coverage.md`: the 150 NID cases, their atoms and reasons (gap / absent).
- `tasks/master_bank/MASTER_BANK.jsonl`: the question text and rubric.
- `tasks/SCHEMA_FINAL_2026-10-29.md` §5–6: the class-b tables and the 211-case fetch stream.
- `tasks/RETRIEVAL_GAPS.md`, `tasks/PIPELINE_TODO.md`, `tasks/project_market_data_backfill` notes in `tasks/STATE.md`.
- The data catalogue: `reality_engine/data/*.db` and the pilot stores. Use the reality-data `catalog` tool or read-only SQL.
- Existing fetchers: `reality_engine/` fetch/ingest modules and `D:\RealityEngine\raw\runners`. List them; do not run them.
- Web checks are allowed to confirm that a source exists and is free: fetch a page or an API index only, no bulk downloads.

## Do
1. Group the NID cases by missing atom (classes), not by case. Expect ~10–20 classes.
2. Triage each class into a / b / c with the fields above. Check at least one real URL/API per (a) class.
3. For each (a) class: estimate build hours, and how many cases it unlocks.
4. For each (b) class: give the proxy recipe as a registry formula over held atoms where possible, plus an example answer for one real case.
5. Sort the plan by cases unlocked per hour.

## Rules
- Read-only on all data; never read a DB from D: (it is an HDD).
- Write only `tasks/arch_v4/NID_TRIAGE.md` and `tasks/arch_v4/nid_triage.json`.
- No bulk fetches, no installs, no paid models.

## Acceptance checks
- `tasks/arch_v4/nid_triage.json` covers every NID case id in `concept_registry.json`. Each case has a class and a verdict a/b/c.
- Every (a) class has a verified source URL.
- Every (b) class has a proxy recipe and one worked example.
- `NID_TRIAGE.md` has the plan sorted by cases per hour, plus totals: cases a/b/c, build hours.

## Test command(s)
```bash
python -c "import json;d=json.load(open('tasks/arch_v4/nid_triage.json'));print(len(d['cases']), {v:sum(c['verdict']==v for c in d['cases']) for v in 'abc'})"
```

## Report
- Totals a/b/c.
- The top 5 classes by cases per hour.
- The (c) list with reasons.
- Tool-call count.
