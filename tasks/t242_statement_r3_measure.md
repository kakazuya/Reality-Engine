# T-242 transcript statements r3: the 394 reparse measurement (26 Nov 2026)

Fresh re-reparse of the live 394 baseline with the r3 code, no model call:

```bash
python -m reality_engine.v2.observations --stores-root C:/RealityEngine/tg_build/full394 \
    --doc-types transcript --transcript-prompt v3 --reparse \
    --baseline D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db \
    --out .tmp/tx394_r3/tx394_r3.db
```

The command rebuilt 25,159 transcript pages (1,797 calls) in 262,982 rows; the r2 copy rebuilt the same
25,159 pages into 262,989 rows. Source DBs are read-only; the copy was scratch.

## Reparse stats, r2 -> r3

| stat | r2 (`tx394_reparse/tx394_r2.db`) | r3 (`.tmp/tx394_r3/tx394_r3.db`) |
|---|---|---|
| pages | 25,159 | 25,159 |
| rows before / after | 263,418 / 262,989 | 263,418 / 262,982 |
| period anchored | 27,186 | 9,575 |
| short remarks dropped | 360 | 331 |
| content-free dropped | 299 | 294 |
| speaker unverified | 3,690 | 3,685 |

## The three W rows (accept: empty or correct)

| pack row | symbol | r2 period | r3 period | why |
|---|---|---|---|---|
| 36 | KTKBANK | `Q4 FY26` | `''` | a Y-o-Y comparative's 781 crore figure; the default anchor had taken the call quarter |
| 43 | EMSLIMITED | `Q4 FY26` | `''` | "results of the last quarter" (Q1 FY27 figures); the default anchor had taken the call quarter |
| 47 | CAPACITE | `Q4 FY25` | `FY25` | the statement names "EBITDA for FY '25"; the explicit FY cue now anchors FY25 |

W 57 (MSTCLTD: retracted statement corrected later on the same page) is unchanged; it is not one of the three
period rows this brief names.

## R rows of tx394_grade_r2 (36 pack rows)

- **0 R rows change beyond `period`.** No statement, speaker, question_context, measure or status differs.
- **5 R rows change in `period` only** (their period had come from the removed default anchor and now stores
  empty): HFCL #2 `Q3 FY26 -> ''`, ASTERDM #17 `Q1 FY26 -> ''`, POONAWALLA #18 `Q3 FY25 -> ''`, AEROFLEX #22
  `Q3 FY25 -> ''`, SAMBHV #48 `Q4 FY26 -> ''`. This is the period-only change the brief's stop clause allows.
- R rows whose explicit cue keeps their period unchanged: TRIVENI #11 (named Q3 FY25 = call), UNIMECH #30
  (`during the year` -> FY25), HITECH #59 (`for the quarter` -> Q3 FY26).
- R rows 5/16/30/45 that looked changed in an intermediate read were unprocessed baseline rows; the final copy
  matches them exactly.

## Per-rule counts across the copy (r2 copy -> r3 copy)

| rule | count |
|---|---|
| statement widened by the new connector/demonstrative fragment rule | 3,985 |
| statement widened by the r2 anaphor rule | 0 (already in the r2 copy) |
| copied speaker label stripped from the statement start | 363 (0 statements still start with a label) |
| statement `period` changed | 18,868: 17,742 emptied, 285 newly set, 841 changed to another label |
| `period_source='call_period'` rows | 27,022 -> 9,531 |
| statement rows with an empty period | 98,429 -> 115,911 |
| old statements with no exact/suffix match in r3 (re-cut or dropped) | 128 (0.10%) |

The label pass runs three times: before the window, after a snap (a snap can pull the printed label line into
the passage) and after speaker attribution (the model's speaker may differ from the resolved row speaker). A
scoped re-reparse of the 29 label-carrying documents with the final pass was applied on top of the full copy.

The fragment rows of the graded pack all widen: ADANIPOWER #9, HINDZINC #21, NITINSPIN #39, KRN #44, JDCABLES #53.
The label row BANKINDIA #60 loses its copied "Shri <Name>, MD & CEO" prefix.

## Files and tests

`reality_engine/v2/obs_speaker.py` (`anchored_period`, `widen_statement`, `strip_leading_speaker_label`,
`attach_statement_speakers`), `reality_engine/tests/test_obs_speaker.py` (65 passed);
`python -m pytest -q reality_engine/tests/test_observations.py` (176 passed).

## r4 follow-up (26 Nov 2026, Hydrogen): own-period cues and heading strip guard

Eagle's non-author review of r3 passed the drop of default `call_period` anchors but flagged five right periods
lost where the statement carried an own-period cue r3 did not read, plus one stripped metric heading (`CUB`
`'Cost-to-income ratio:'`). r4 updates `reality_engine/v2/obs_speaker.py`:

- **Own-period cues added to `anchored_period`**: (a) `as on / as at / as of / basis [the|of] <date>` matching the
  call's period end in any printed date form (`31st December 2024`, `31.12.2024`, `December 31, 2024`, `March 2026`);
  (b) `quarterly <metric/figure>` (with a figure in the sentence, excluding `quarterly basis`/`fluctuations`) and
  `this quarter's`; (c) `<figure> stood at / was / reached ... (growth|up|increase) over <date>` when `<date>` is
  exactly one year or one quarter before the call's period end.
- **Negative guards kept strict**: never anchors on forward cues (`will`, `expect`, `target`, `guidance`, `by FY..`,
  `next quarter`), `"same quarter last year"`, `"last quarter"`, explicit other `FY`/`H`/`Q` (and `_NAMED_FY_RE`
  requires `q == 4` so `NIM for FY26` on a Q1 call stays empty), or a future date; keeps r3's 7 stay-empty cases
  (`HFCL`, `IOLCP`, `CUB`, `BPLPHARMA`, `BOROLTD`, `KTKBANK` #36, `EMSLIMITED` #43) empty and `CAPACITE` #47 `FY25`.
- **Label strip guard**: `_is_heading_label` splits on hyphens/slashes and includes `ratio`/`ratios`/`yield`/`equity`/
  `assets`/`deposits`/`advances`; `strip_leading_speaker_label` only strips a leading label when it names a roster
  speaker (`known_names`) or carries a role word (`CEO`, `CFO`, `MD`, `Chairman`, `Director`, `Head`, `Officer`,
  `Moderator`, etc.), never a metric heading.

Tests in `reality_engine/tests/test_obs_speaker.py` (3 new tests covering the 5 regain cases, 7 stay-empty cases +
W #47, and `CUB` heading guard) and `reality_engine/tests/test_observations.py` both pass after the final edit.
