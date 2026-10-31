# Continue — shareholding XBRL for the 60 pilot names

The first run stopped on a provider timeout at about 07:26 IST while running the full pilot fetch. `reality_engine/scripts/fetch_shp_xbrl_pilot.py` and `.tmp/shp_xbrl_raw/` (52 KB) are in this worktree, uncommitted. Do not start over: read them, then finish `tasks/dsh_tasks/V4_SHP_XBRL_PILOT_2026-10-31.md`. All its limits and acceptance checks stand. Run the fetch so it can resume and does not hold up the conversation for long stretches. Do not commit; the reviewer commits.

## Test command(s)
```bash
python -m pytest reality_engine/tests/test_v4_shp_xbrl.py -q
```

## Acceptance checks
As in the original brief.
