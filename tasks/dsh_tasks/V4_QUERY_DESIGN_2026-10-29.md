# Task — v4 query design: concept registry + ask contract + text-only decomposer + answer contract

## Goal
The pilot gate is 27/2,681 strict (1.0%). Planner patching has plateaued: each round adds aliases and gains a few percent. Write ONE design document, `tasks/arch_v4/QUERY_V4_DESIGN.md`, and a generated **concept registry**, so that 3–4 build workers can implement it in parallel with disjoint file scopes.

Inputs:
- `tasks/STATE_FOR_ANY_AI_2026-10-29.md`;
- `tasks/arch_v3/QUERY_LAYER.md` (the current design);
- `tasks/SCHEMA_FINAL_2026-10-29.{md,sql}` and `tasks/SCHEMA_FINAL_CASES_2026-10-29.jsonl` (tables per case);
- `tasks/pilot_b/cases_pilot_b.jsonl`;
- `reality_engine/query/*` (router, decompose, planners, gate, answer, metrics, compute);
- `tasks/answer_bench/GATE_RESULTS_*_strict.jsonl` (the failure reasons);
- `tasks/master_bank/MASTER_BANK.jsonl`.

## Do
1. **Concept registry (generated, not hand-written).** Write `tasks/arch_v4/build_concept_registry.py`, which emits `tasks/arch_v4/concept_registry.json`. For every concept a bank case asks for, the registry gives:
   - concept id, aliases (from the question texts), unit, granularity (day/quarter/FY/event);
   - the table(s) + field(s) that hold it (from the schema SQL and the per-case table lists), and the planner that reads it;
   - the PIT column;
   - for derived concepts, the derivation (e.g. margin = EBITDA / revenue);
   - a "held" status per pilot ISIN coverage, or NOT IN DATA with the reason.

   Coverage must be: every one of the 1,073 cases maps all its asked concepts to registry entries. Report any that don't.
2. **Ask contract.** A typed `Ask`:
   - entity/entities and the entity level;
   - period window(s);
   - a list of **parts**: concept, qualifiers (exchange, basis raw/adjusted, consolidated/standalone), comparison/aggregation, output shape;
   - a judgement flag.

   Define it as a dataclass/JSON schema, with 20 worked examples taken from failing cases (MB0234, MB0280, MB0125, MB0996, MB0003, plus others), each showing its parts.
3. **Decomposer, text-only.** It parses the question TEXT into an `Ask`, using the registry's aliases + entity resolution + the period parser (the router's `period_bounds`). Master-bank fields (`template`, `family`, `chain`, `period`) must NOT be inputs; they are used only to evaluate decomposer accuracy. Specify the evaluation: per-part precision/recall against the bank's `rubric`/`chain`.
4. **Planner contract.** Each planner receives a list of parts and returns exactly one result per part: value(s), unit, period, ISIN, source + known_at, OR an explicit NOT IN DATA (with a reason from the registry). No extra rows. Map each of the 8 planners to the concepts it serves.
5. **Answer contract and renderer.** Each part is printed with its value, period and source. The strict grader checks part coverage directly against the `Ask` (no alias guessing).
6. **Migration plan.** Split the build into 3–4 work packages with disjoint files (registry + build script; decomposer; planner adapters; renderer + grader), with an acceptance test each. Estimate the gate gain per package from the failure reasons (the counts of `ask_match` / sub-question / substance failures each one fixes).

## Rules
- Read-only on data. Write only `tasks/arch_v4/*` (plus the generator script). No planner code changes in this task. Use no paid models and make no commits.

## Acceptance checks
- `python tasks/arch_v4/build_concept_registry.py` runs and writes the registry. A coverage report shows 1,073/1,073 cases with all their concepts mapped (or NOT IN DATA with a reason).
- `QUERY_V4_DESIGN.md` has all 6 sections plus the 20 worked examples.

## Test command(s)
```bash
python tasks/arch_v4/build_concept_registry.py --check
```

## Report
Give:
- the registry size (concepts, aliases, tables);
- the coverage numbers;
- the work packages with their estimated gain;
- the open questions for Shivam;
- your tool-call count.
