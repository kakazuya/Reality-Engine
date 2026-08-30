---
description: Integrate all lanes and merge lane DBs in main repo
---

# merge-lanes - Integrate all lanes in MAIN repo (LOCAL context, not a worktree)

> Run ONLY in the MAIN repo (not a worktree). Reads `.kilo/LANES.md` merge order first. **never edit files you do not own; respect LANES.md ownership**

## 0. Pre-check

Read `.kilo/LANES.md` merge order:
1. lane-code-repo
2. lane-code-cli -> lane-code-derive -> lane-code-distill (any order after repo)
3. lane-funda (DB funda)
4. lane-filings (DB filings)

## 1. Confirm lane branches merged

Ask user to confirm all lane worktree branches are merged/applied. Expected branches:

- `lane-code-cli`
- `lane-code-repo`
- `lane-code-derive`
- `lane-code-distill`

Via Agent Manager "Apply" or `git merge lane-code-*`. Run:
```powershell
git branch --list "lane-*"
git status
```
List which branches exist and are merged (git log --oneline --graph --all -20). If not merged, instruct user to Apply via Agent Manager first and re-run this command.

## 2. Full test suite

```powershell
python -m unittest discover -s reality_engine/tests -p "test_*.py"
```

Report GREEN/RED per module, total failures/errors. Do NOT proceed to DB merge if critical code tests fail – report and stop.

## 3. Backup main DB

```powershell
Copy-Item reality_engine\data\equity_intelligence.db reality_engine\data\equity_intelligence.db.pre_lane_merge -Force
Get-ChildItem reality_engine\data\equity_intelligence.db* | Select-Object Name, Length
```
Print size before/after.

## 4. Find and merge lane DBs

Glob for lane DBs:
```powershell
Get-ChildItem -LiteralPath ".kilo/worktrees" -Recurse -Filter "equity_intelligence.db" -ErrorAction SilentlyContinue | Select-Object FullName, Length
# Expected patterns:
# .kilo/worktrees/lane-funda-*/reality_engine/data/equity_intelligence.db  -> mode funda
# .kilo/worktrees/lane-filings-*/reality_engine/data/equity_intelligence.db -> mode filings
```
If not found, ask user for manual paths.

For each found lane DB, run dry-run first then real:

```powershell
python reality_engine/scripts/merge_lane_db.py --main reality_engine/data/equity_intelligence.db --lane <found> --mode funda --dry-run
python reality_engine/scripts/merge_lane_db.py --main reality_engine/data/equity_intelligence.db --lane <found> --mode funda

python reality_engine/scripts/merge_lane_db.py --main reality_engine/data/equity_intelligence.db --lane <found> --mode filings --dry-run
python reality_engine/scripts/merge_lane_db.py --main reality_engine/data/equity_intelligence.db --lane <found> --mode filings
```

Use correct mode per glob (funda vs filings). If a worktree has both kinds (should not), prompt.

Print per-table inserted/updated counts. Transactional – on error, restore from backup and report.

## 5. Substrate population on main DB

After DB merges, run:

```powershell
python reality_engine/cli.py backfill --days 5
python reality_engine/cli.py seed-peers
# fallback if seed-peers not present yet (lane-code-cli not merged):
python reality_engine/scripts/run_supply_peer.py
python reality_engine/scripts/run_quality_peer.py
python reality_engine/scripts/run_policy_peer.py
python reality_engine/scripts/run_factor_peer.py
python reality_engine/scripts/run_moe_eod.py

# curated params + derived expansion
python reality_engine/cli.py seed-ontologies
# derived helpers (if new flags exist):
python reality_engine/scripts/run_quality_peer.py --universe all --include-derived
python reality_engine/scripts/run_supply_peer.py --universe all
# or via python -c "from reality_engine.processing.distillation_engine import distillation_engine; distillation_engine.derive_company_parameters(universe='all', limit=None)"
```

Report OK/FAIL per command (seed-peers steps OK/FAIL, backfill rows).

## 6. Causal graph and correction

```powershell
python reality_engine/cli.py spawn-event-graph --event US_TARIFF_TEXTILE_RELIEF --max-hops 3
python reality_engine/cli.py spawn-event-graph --event STEEL_SAFEGUARD_DUTY --max-hops 3
python reality_engine/cli.py spawn-event-graph --event RAIL_CAPEX_PUSH --max-hops 3
python reality_engine/cli.py spawn-event-graph --event NUCLEAR_MISSION --max-hops 3

python reality_engine/cli.py correct-event --event US_TARIFF_TEXTILE_RELIEF
python reality_engine/cli.py correct-event --event STEEL_SAFEGUARD_DUTY
python reality_engine/cli.py correct-event --event RAIL_CAPEX_PUSH
python reality_engine/cli.py correct-event --event NUCLEAR_MISSION

python reality_engine/cli.py correct-eod --universe nifty200 --update-substrate
```

Report OK/FAIL per event, ripples created, lens rank changes.

## 7. Verify

```powershell
python reality_engine/cli.py audit-data --json
```

Expect `funnel_tables_missing` empty (or only genuinely justified entries – explain if not). If not empty, show which tables missing.

Spot-check 3 random symbols end-to-end:

```powershell
python reality_engine/cli.py inspect-stock RELIANCE   # top-10
python reality_engine/cli.py inspect-stock TCS         # Nifty500-only example (or another nifty500 not in nifty200)
python reality_engine/cli.py inspect-stock POLYPLEX    # smallcap outside Nifty500
```

Check each shows ISIN, distilled parameters, moat, policy ENI, geographic exposure. Report pass/fail.

## 8. Do NOT git commit

Do NOT run `git commit` in this command – user decides when to commit merged result.

## 9. REPORT

```
REPORT merge-lanes
- Branches merged: lane-code-cli YES/NO, lane-code-repo YES/NO, lane-code-derive YES/NO, lane-code-distill YES/NO
- Tests: discover GREEN/RED (failures=N, errors=N)
- Backup: pre_lane_merge size=N MB OK/FAIL
- Lane DBs found: funda=[paths], filings=[paths]
- Merge dry-run + real: funda inserted/updated per table [counts], filings updated/inserted [counts] OK/FAIL
- Substrate: backfill 5d rows=N OK/FAIL, seed-peers OK/FAIL (supply/quality/policy/factor/moe per-step), seed-ontologies OK/FAIL
- Causal: spawn 4 events OK/FAIL (ripples each), correct-event 4 OK/FAIL, correct-eod OK/FAIL
- Verify: audit-data funnel_tables_missing=[...] OK/FAIL, inspect-stock RELIANCE/TCS/POLYPLEX OK/FAIL
- Overall: PASS/FAIL with next steps
```

Args: `$ARGUMENTS` forwarded to audit-data if needed. If no lane DBs found, report "no lane DBs - code lanes only".
