# T-241 brief: model-free post-read fix pass for hy4 transcript observations (DeepSeek codes, Eagle reviews)

Start: off-peak only (after 15:30 IST Mon-Fri), one worker, worktree `dsh/<job>`; Eagle confirms with Wolf first.
Speaker is OUT of scope: Hydrogen job `fe39146a` builds `reality_engine/v2/obs_speaker.py` (speaker + role
carry-over). Call it if it is merged when you start; otherwise leave a clearly marked hook and do not re-implement.

## Evidence (Eagle hand audit, 24 Nov; `D:/RealityEngine/reports/2026-11-24_hy4_transcript_audit.md` + `.xlsx`)
- Snapshot (read only, never open the live `D:/RealityEngine/t241/obs_transcripts_394.db`):
  `C:/Users/warri/AppData/Local/Temp/claude/12b5f02fd3b7ce95/82f0cda6-8a84-4831-a260-84b9a6b057ad/scratchpad/obs394.db`.
  Copy it into your worktree `.tmp/` and work on the copy.
- 110 graded rows: 40 right, 49 partial, 11 wrong, 10 junk. Golden lines (grade, key, defect class, expected
  fields where the fix is mechanical): `D:/RealityEngine/t241/hy4_audit_golden.jsonl`. Page text for each graded
  item: `D:/RealityEngine/t241/items.jsonl` (`page_text`).
- Whole-snapshot counts (158,060 served number+guidance rows):
  period empty 49,016 / a call date 31,886 / free text 61,194 (only ~16k in Qn FYyy / Hn FYyy / FYyy form);
  9,200 rows print a range ('12% to 15%', '600-700', '50%, 52%') with `value_high` NULL;
  3,198 rows with a crore unit and `scale=1.0` (the rest carry 1e7);
  587 growth/change rows whose label says declined/drop/fell/degrowth/down/decreased but `value > 0`;
  ~8,200 small integers 1-12 with an empty or ordinal unit (list markers 'number 1', 'Q2 FY25' -> 2, '4-star',
  postcode '400 051' -> 400, 'just 2 months back' -> 2).
- Worked examples (golden items): #18 NEWGEN 'License revenue declined by 19.2%' stored +19.2; #4 SANGAMIND
  '12% to 15%' kept 12; #103 JAIBALAJI 'INR105-110 crores' scale 1.0; #10 DEEDEV 'the quarter' (call 19 Aug 2024 ->
  Q1 FY25); #26 MBAPL postcode as launch_year.

## Steps
1. Read `docs/FIX_LOOP.md`, `reality_engine/scripts/regress.py`, `reality_engine/research/selector.py`, and the
   observation schema in `reality_engine/v2/observations.py` (use `code-tools outline`, do not read all 5k lines).
2. New module `reality_engine/v2/obs_postfix.py`, CLI
   `python -m reality_engine.v2.obs_postfix --db <copy.db> --out <out.db> [--only sel.json] [--dry-run]`:
   copies `--db` to `--out`, applies the fixes below to the copy only, writes a `postfix_log` table
   (observation_id, rule, field, old, new) and prints per-rule counts. Never writes the input.
   a. **range**: if `value_high` IS NULL and `value_text` has two numbers joined by to / - / – / ',' / 'or' with
      the same unit, set `value_high` to the larger, `value` to the smaller. Skip dates, ratios '60:40', and
      'x of y'.
   b. **scale**: unit text names crore/cr -> 1e7, lakh -> 1e5, million/mn -> 1e6, billion/bn -> 1e9 when `scale` is 1.0;
      if `unit` holds only the scale word, keep the noun (sq ft, MW, tonnes, pumps) from `value_text`/label.
   c. **sign**: for measures named *growth* / *change* / *_bps*: a falling word in `printed_label` or the
      statement sentence and `value > 0` -> `value = -value`, `direction = 'down'`. Never flip when 'decline in
      cost/NPA/debt' is a reduction the measure already names (e.g. *_reduction*).
   d. **junk**: set `status='quarantined'`, `status_reason='postfix_junk:<why>'` for: list markers, a year or
      quarter number stored as the value (value equals the digits of a period/FY token in `value_text`), postcodes
      (6 digits with a space, 'Mumbai – 400 051'), star ratings, hypotheticals ('let's say', 'imagine', 'for
      example', 'suppose') in the printed label. Quarantine, never delete.
   e. **period**: from the transcript's own call quarter (first pages print 'Q2 FY25 Earnings Call'; else derive
      from `known_at`: the quarter that ended before the call), map 'the quarter' / 'this quarter' / 'for the
      quarter' / 'during the quarter' -> that Qn FYyy; 'this year' / 'current year' / 'full year' / 'FY' -> its FYyy;
      'next year' -> FYyy+1; 'H1' / 'H2' -> Hn FYyy; '9 months' / '9M' -> 9M FYyy. A call date stays only for
      stock measures (order book, headcount, cash, capacity, stores). Keep the printed text in `period_source`.
      Unresolvable text stays as is.
3. Golden gate: append `D:/RealityEngine/t241/hy4_audit_golden.jsonl` to `reality_engine/tests/golden/observations.jsonl`
   only if regress accepts its fields; if a needed field (`value_high`, `direction`) is not in
   `PIPELINES['observations'].allowed`, add it there (that is the only regress change allowed). Then
   `python -m reality_engine.scripts.regress observations --db <out.db> --baseline <copy.db>`.
4. Tests `reality_engine/tests/test_obs_postfix.py` (temp sqlite, one case per rule plus each skip case above).
5. Docs: `docs/FIX_LOOP.md` (the new pass, one paragraph) and `docs/PILOT3_BLUEPRINT.md` observations section
   (what each rule changes). No docs, no merge.

## Limits / pitfalls
- No model calls, no network. Work on copies; never open the live hy4 DB (it is being written).
- Rules are general, never per company or per symbol; no company literal in code.
- Do not re-implement speaker; do not change `observations.py` reading behaviour.
- RAM: run pytest per file. Do not run a full-snapshot pass more than twice; use `--only` while developing.

## Accept (Eagle checks before merge)
- `regress` prints GATE: pass (0 newly broken RIGHT rows) on the 110 golden lines and the existing 265.
- Per-rule counts printed and close to the evidence counts above (range ~9k, scale ~3.2k, sign <= 587,
  junk a few thousand, period tens of thousands); Eagle hand-reads 20 random `postfix_log` rows per rule.
- `pytest reality_engine/tests/test_obs_postfix.py -q` passes; basedpyright clean on the new files.

## Stop rule / report
Stop when the accept list passes or after 3 hours. Report: branch, head, per-rule counts, regress summary, and
any rule you skipped with the rows that made you skip it.
