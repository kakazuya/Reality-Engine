---
description: Derive at scale substrate writers
---

# lane-code-derive - Derive-at-scale substrate writers

> Read `.kilo/LANES.md` first. You own ONLY `reality_engine/processing/business_profiler.py`, `reality_engine/processing/policy_engine.py`, `reality_engine/processing/moat_scorer.py`, `reality_engine/scripts/run_supply_peer.py`, `reality_engine/scripts/run_quality_peer.py`, `reality_engine/scripts/run_policy_peer.py`, `reality_engine/tests/test_derived_substrate.py`. **never edit files you do not own; never write DB tables you do not own; worktree-local helper scripts must be deleted before merge or listed in the lane report**

## 1. business_profiler.py - derive_universe_profiles(...)

- Reuse vocabulary present in existing rows for archetype (Platform/Tollbooth/Subscription SaaS/Asset-Heavy OEM/Asset-Light OEM/Network/Marketplace/Commodity).
- Heuristics from `annual_financials` (roce_pct, opm_pct, debt_to_equity): e.g. roce_pct >15 + opm_pct >20 -> Tollbooth/Platform high pricing, high recurrence; D/E >1.0 -> capital intensive; else heuristic defaults per archetype.
- notes marker `'Derived from financials+industry heuristics FY26'`, idempotent (never overwrite non-derived rows - check qualitative_notes not containing Derived marker and existing isin-derived? skip).
- Signature: `derive_universe_profiles(universe="nifty200", limit=None, overwrite=False, ...)` or similar - keep existing `seed_business_profiles` untouched.

## 2. policy_engine.py - seed_derived_policy_risks(...)

- Industry->policy-template map (11 entries): Steel/safeguard duty, Rail/cafe push, Defence/DAP, Power/Renewables PLI, Pharma-USFDA, IT-visa, Fertilizer-subsidy, Banks-rate cycle, Auto-EV PLI, Cement-infra, Mining-export duty.
- For each master_companies industry match, insert via `repo.upsert_regulatory_political_risk` with severity/probability heuristics (e.g. Steel -2.5*0.6, Rail +3.5*0.8 etc), idempotent on UNIQUE(symbol,policy_name).
- Signature: `seed_derived_policy_risks(universe="nifty200", limit=None, include_derived=False)` style, preserve existing `seed_canonical_policy_risks_full`.

## 3. moat_scorer.py - derived moat path

- Reuse formula `0.25*SC+0.25*NE+0.20*CA+0.20*IA+0.10*ES` with per-archetype defaults (ARCHETYPE_METRICS). Derive scores from financials + archetype, idempotent, never overwrite curated BACKFILL_CATALOG rows unless overwrite flag.

## 4. scripts/run_supply_peer.py - geographic exposure at scale

- Extend to all master companies: default `IND 96/92` (revenue/asset) + EXPORTER_OVERRIDES dict for `TCS/INFY/HCLTECH/WIPRO/TECHM/DRREDDY/SUNPHARMA/CIPLA/AUROPHARMA/TATAMOTORS/BAJAJ-AUTO/BHARATFORGE/HINDALCO/VEDL/NALCO` keyed by symbol (exact overrides from task).
- Add argparse `--universe {nifty200,nifty500,all}` + `--limit` (int). DEFAULT BEHAVIOR UNCHANGED (no args -> same as before ~30 symbols).

## 5. scripts/run_quality_peer.py & run_policy_peer.py

- Add optional `--universe {nifty200,nifty500,all}` + `--include-derived` flag.
- DEFAULT BEHAVIOR UNCHANGED when flags absent (existing tests pass).

## 6. Preserve existing entry points

- Keep every existing `main()`/argparse entry point exactly. New args are optional with defaults. `lane-code-cli` will import robustly via subprocess fallback.

## 7. New test file reality_engine/tests/test_derived_substrate.py

- Use fixtures isolated pattern (`reality_engine/db/fixtures.py` - `create_isolated_test_db` / `isolated_test_context` or temp DatabaseManager with temp dir).
- Test: derive functions create rows, idempotent second run changes nothing, curated rows not overwritten.

## 8. Sub-agents

Fan out via Task where marked: one sub-agent per derived function (business, policy, moat, supply, quality/policy scripts) in parallel; parent integrates edits serially.

## 9. Tests

No existing test suite listed beyond new file, but ensure:
```powershell
python -m unittest reality_engine.tests.test_derived_substrate
```
GREEN. Existing `test_moat_backfill` etc must stay green.

## 10. Do NOT git commit/merge

## 11. REPORT

```
REPORT lane-code-derive
- Files changed: business_profiler.py, policy_engine.py, moat_scorer.py, run_supply_peer.py, run_quality_peer.py, run_policy_peer.py, test_derived_substrate.py
- Tests: test_derived_substrate GREEN/RED, other suites GREEN/RED
- Artifacts: derived writers idempotent YES/NO, --universe flags added YES, default behavior unchanged YES
- Worktree-local helpers deleted or listed: none / [list]
```

Args: `$ARGUMENTS` forwarded.
