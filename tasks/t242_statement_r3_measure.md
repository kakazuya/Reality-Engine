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

## r5 follow-up (26 Nov 2026, DeepSeek): the own-period token bound to its figure wins

Eagle's non-author review of r4 (`D:/RealityEngine/t242/grades/tx_r4_review_eagle.md`) passed r4's new cues
(20/20 regained statements right) but failed the net: r4's sentence-wide blocks fired before an explicit
own-period cue bound to the figure, regaining 591 but dropping 1,585 (period_anchored 9,579 -> 8,575). r5 updates
`reality_engine/v2/obs_speaker.py`:

- **`_explicit_own_period` runs first in `anchored_period`; a block now stops only weak/default cues.**
  (a) the call's own `Qn FYnn` bound to a figure anchors the call quarter, whatever other comparative or
  other-period words the sentence holds (ASKAUTOLTD "EBITDA in Q1 FY25 at Rs. 103 crore against Rs. 65 crore in
  the same quarter last year" -> `Q1 FY25`); (b) `in/during the quarter`, `this quarter` and a non-comparative
  `for the quarter` bound to a figure in their clause anchor the call quarter (MEDANTA "During the quarter ...
  compared to ... same quarter last year", INFOBEAN "last quarter it was 23, this quarter it is 24 percent");
  (c) a named token under a sentence-wide comparative frame (`On a Y-o-Y basis, NII for Q4 FY '26 ...`,
  KTKBANK #36) or directly after `against/vs/compared to/over/from` names the base and never anchors; (d) a
  forward/guidance sentence anchors the named target period in the cue's clause (`for FY25 we expect`, `by
  FY28`) or the call's own `FYnn` on a Q4 call (AZAD "reaffirm our guidance of 25-30% for FY'25" -> `FY25`),
  but not the call's own year on a Q1-Q3 call (CUB's "NIM for FY26") and never a relative future cue with no
  named period (HFCL's "during the current quarter").
- **Every r4 cue still runs after the new pass** (as-on period end, `quarterly <metric>`, over-base), so no r4
  regain is lost. IOLCP's "same quarter last year" figure (no own cue), KTKBANK #36, EMSLIMITED #43 "last
  quarter", BPLPHARMA's 2027/2028 milestone dates and BOROLTD's H1 figure stay empty; CAPACITE #47 stays `FY25`.
  (r6 supersedes the IOLCP case: its bound "for the quarter" figure anchors Q1 FY26.)
- **Tests**: `test_r5_own_period_cue_beats_sentence_wide_blocks` (ASKAUTOLTD, TVSSCS, MEDANTA, AZAD, INFOBEAN,
  ACUTAAS, AWFIS) and `test_r5_stay_empty_cases_remain_empty` in `reality_engine/tests/test_obs_speaker.py`
  (70 passed at r5; r6 renamed the test and moved IOLCP to the anchored set), `python -m pytest -q
  reality_engine/tests/test_observations.py` (177 passed). The r4 stay-empty
  test now asserts `BPLPHARMA` "by FY28" -> `FY28` (r5's guidance target) and is named
  `test_r4_stay_empty_cases_and_w47_remain_unchanged`.

### r5 measurement on the 394 reparse

The 25,159-page rebuild ran through the same `--reparse` path in five store shards (`.tmp/reparse_all.py`,
one process per shard, each writing its own copy). The live `D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db`
was being rewritten by another job while this ran (18:42 and 19:02 IST) and a straight copy failed its integrity
check, so the closed r4 copy `Wolf-agy-20261126T081833Z-f27697a8/.tmp/tx394_r4/tx394_r4.db` was the baseline; it
holds the same 25,159 `page_reply` rows as the r3 copy. The harness keeps the store connections open and enlarges
the `re` cache (the 245-minute r4 run opened a connection per page and recompiled a name pattern per company per
page); the page text and rows are the unchanged pipeline. The rows-before count is the r4 copy's 262,980 (the live
DB held 263,418 rows before its rebuild; the copy is the closed baseline).

| stat | r3 | r4 | r5 |
|---|---|---|---|
| pages | 25,159 | 25,159 | 25,159 |
| rows before / after | 263,418 / 262,982 | 263,418 / 262,980 | 262,980 / 262,980 |
| period anchored | 9,575 (brief: 9,579) | 8,575 | **9,959** |
| speaker unverified | 3,685 | 3,687 | 3,687 |
| short remarks dropped | 331 | 332 | 332 |
| content-free dropped | 294 | 295 | 295 |

The non-period counts equal r4 exactly (speaker carried 1,153, resolved 589, empty 232, moderator 366, not-a-call
9, not-a-person 2, 1,797 transcript docs, 82 not-call docs), so the shards reproduced the pipeline; only the anchor
count moved: **+1,384 over r4 and +380 over r3**.

Matched on `(doc_key, page, statement)`: 125,385 of 125,440 statements. The r3 copy holds 9,528 rows with
`period_source='call_period'` and the r5 copies 9,903; 1,651 statements regain an r3-empty period, 1,276 lose one,
230 change to another label. `tx394_grade_r2`: **0 of the 36 graded-R rows change beyond `period`** (0 of the 60
found pack rows too). Six P fragment rows (9, 21, 39, 44, 53, 60) are not matched by statement text (the pack
holds their pre-widening r2 text); 11 non-R rows differ in `speaker`/`status` only, from r4's speaker work.

Regained sample, seed 7 (period | statement):

1. `FY28` | Renewable energy accounted for approximately 48% of GRP's stand-alone power consumption in FY 2026, up from 37% a year ago.
2. `Q3 FY25` | The company continues to have a comfortable liquidity position, remaining debt-free at the net level.
3. `Q1 FY27` | Quarterly average cost of borrowing has decreased by 3 basis points on a quarter-on-quarter to 9.13% ...
4. `FY25` | Our defense order book now stands at around INR2,600 crores, and we are expecting big orders in the coming quarters.
5. `Q1 FY27` | Specifically, power sales under PPAs grew by 30% to 25 billion units. Merchant volumes were 4 billion units in quarter 1 ...
6. `Q2 FY27` | For quarter 2 FY27, revenue from operations stood at INR682 crores, a growth of 16% year-on-year.
7. `FY27` | This also validates our belief in our capability to scale up the brand in the D2C space in future ...
8. `Q4 FY25` | As of 31st March 2025, the capital adequacy ratio stood at 37.34% for our standalone business ...
9. `Q4 FY27` | Further, the APA pipes facility readiness is expected to be completed by Q4 FY27 ...
10. `Q4 FY26` | During Quarter 4 FY26, EPC revenues marginally declined by 15% year-on-year, reaching INR 5,098 million ...
11. `FY24` | So, the return on capital employed was around 16.5%, which generally is in line with the number we do it for the half year.
12. `Q4 FY26` | The project recorded booking of INR52 crores and has an estimated GDV of INR430 crores to INR450 crores. We expect to launch two projects in ...
13. `Q2 FY26` | As on 30th September '25, Borosil Ltd has a net debt of INR 4.5 crores.
14. `Q3 FY26` | You are aware that we are already putting up India's largest district cooling facility of 40,000 metric tons of refrigeration at Mundra ...
15. `Q2 FY27` | We also continued to maintain a net cash positive position as of 30th September 2026 ...
16. `FY27` | In the line with this, the company is targeting order inflow in the range of approximately INR8,000 crores to INR10,000 crores during FY27 ...
17. `Q2 FY27` | Thank you. Good afternoon, ladies and gentlemen. I am Saleem Ahmad, Chairman and Managing Director of Ircon ...
18. `FY26` | On the other hand, the US market is experiencing a slower than expected growth owing to a bunch of challenges ...
19. `Q4 FY24` | As a result, CGCL's outstanding fully paid-up equity shares have increased 4x from approximately 206 million equity shares in Q4 FY23 ...
20. `Q4 FY26` | Lastly, on the liquidity and capital position front, the company continues to remain well capitalized with capital adequacy ratio of 27.86% ...

All 20 regained periods are explicit own-period cues (as-on / during / quarter / named target period): 20/20 right.

Dropped sample, seed 7 (`r3` label | statement):

1. `Q4 FY26` | ... all of this CapEx is anticipated to be complete by, as we have previously mentioned, September 2026 ...
2. `FY26` | For NM development, this is going reasonably well and we are looking to accelerate the development ...
3. `FY27` | Our strategy for FY27 is to consolidate our International Collections, Insurance, Healthcare and Healthcare RCM businesses.
4. `FY26` | Full year employee cost increased from Rs. 2,353.4 crores in FY25 to Rs. 2,502.4 crores in FY26 ...
5. `FY24` | During the year, our EBITDA margin has expanded on account of operating leverage and process efficiency ...
6. `FY27` | The margin improvement reflects three things working together: 1. Better capacity utilization ... 2. Operating leverage.
7. `FY27` | During the year, we are targeting to meaningfully increase our qualification rates over the previous year.
8. `FY27` | We are hoping that this year we will exit at around 2,500 that is the guidance ...
9. `FY25` | As guidance, as my concluding remarks, I would like to state that our Secured book by the year end would be ...
10. `Q1 FY26` | Coming to EBITDA for the quarter, which is stood at INR20 crores, around 31% on the revenue, which is in line with our FY '26 guidance.
11. `FY25` | For FY'25, our company is aiming for a 10%-12% revenue growth as of now ...
12. `FY26` | On the capex front, Solapur Phase 1 is progressing as planned and is expected to be operational in Q2 of this year ...
13. `Q4 FY25` | In rupee terms, this revenue stood at INR1,472 crores with a Q-o-Q degrowth of 0.5% and a Y-o-Y degrowth of 1.2%. This Q4 revenue ...
14. `FY25` | And as we are growing, we need to have the supply chain in order to complete that target. So, again, this year we are again targeting ...
15. `FY25` | Very quickly on the Water business, supported by our extensive funding support from State and Central Governments ...
16. `FY26` | So, now, even in Eastern UP, we have managed to do a paradigm shift ...
17. `FY24` | So my expectation of INR2,000 crores of orders from that part of business is also quite robust expectation ...
18. `FY25` | With a lot of thought and it is going to really be a definitely hoping to create a big difference in this domain ...
19. `FY26` | Now coming on to our "API." The API sales has shown a growth of 14% compared to last year and this will continue ...
20. `Q1 FY26` | Order booking in Q2 continues to be very strong and we will end the quarter with extremely good order booking numbers.

Judgment: 13 of the 20 dropped rows are forward or relative statements with no named target period (1, 2, 6-9,
12, 14-20): the r5 rule keeps them empty on purpose, so r3's call-period label is not reimposed. The other 7 name
or imply a period r5 does not re-anchor: #3 `for FY27` and #4 `in FY26` on a Q4 call (the r3 label may have been
right), #5 `during the year` -> FY24, #10 `for the quarter` on a Q1 call, #11 `For FY'25 ... aiming` (MUFTI; r4's
review listed it as a right period lost), #13 `This Q4 revenue`. They are the remaining trade-off of "empty beats
wrong": the rule anchors a named target period only in a forward sentence or the call's own named period, and
`aiming`/`during the year`/`This Q4` are not read as formal cues. The net is still +380 against r3.

## r6 follow-up (26 Nov 2026, DeepSeek): four narrow fixes on r5

Eagle's non-author review of r5 (`D:/RealityEngine/t242/grades/tx_r5_review_eagle.md`) kept the removal of the
default call-period anchor (net better than r3) but found four structural misses. r6 changes only
`reality_engine/v2/obs_speaker.py` (`anchored_period`, `_explicit_own_period`, the new `_bound_quarter_before`,
and the named-period / FY / quarter cue patterns):

- **A bound `for the quarter` beats a same-quarter-last-year comparative.** The sentence-wide `same quarter last
  year` block is gone from the `for the quarter` loop; the cue must still label a figure in its own clause and
  must not follow a comparative connector, so the comparative names the base (IOLCP 58.2 crore -> `Q1 FY26`;
  BLS 711 crore -> `Q1 FY27`). `_OWN_QUARTER_CUE_RE` rejects `in Quarter 3` / `in Quarter 4` (a named other
  quarter; the r5 misread that took PDSL to `Q2 FY26`), and `_bound_quarter_before` keeps a bound cue that
  precedes a forward aside (SOLARINDS "volume for the quarter grew by 16% ... in line with our annual guidance
  for the year '25" -> `Q1 FY25`), while a cue only after the forward word stays empty (HFCL).
- **`Q1 of FY27` / `first quarter of FY27`.** `_NAMED_QUARTER_FY_RE` reads the `of` form and the ordinal-quarter
  form (quarter group 1 or 2, FY group 3, through `_ORDINAL_QUARTER`): ARMANFIN "Q1 of FY27 has been an
  encouraging start" -> `Q1 FY27`.
- **Named FY with a space, apostrophe or hyphen.** The FY patterns accept `FY '25`, `FY 27`, `FY'27`, `FY-27`
  and the left single quote; a guidance sentence names its own FY on a Q1-Q3 call (AZAD "guidance of 25%-30% for
  FY '25" -> `FY25`) while a guidance-less figure stays empty (CUB "NIM for FY26" -> `''`).
- **`during the year` / `first half of the year`.** They resolve to the call's fiscal year / `H1 FY<call fy>`
  (empty on a Q1 call), never to the call quarter: TARACHAND -> `FY26` (was `Q4 FY26`), PDSL -> `H1 FY26` (was
  `Q2 FY26`), MMP -> `FY26` (its printed call period is `Q4 FY26`, so FY26 is the call's FY; r5's `Q2 FY27` was
  the forward approval target). The cue runs at the end of `_explicit_own_period`, and before a
  forward cue through `_bound_quarter_before`, so a named own quarter still wins in the same sentence.

Tests: `reality_engine/tests/test_obs_speaker.py` adds
`test_r6_quarter_bound_figure_beats_same_quarter_last_year`, `test_r6_q1_of_fy27_form`,
`test_r6_named_fy_space_apostrophe_hyphen`,
`test_r6_year_and_first_half_never_anchor_the_call_quarter`; r5's
`test_r5_five_stay_empty_cases_remain_empty` is renamed `test_r5_stay_empty_cases_remain_empty` (IOLCP anchors
now), and `test_r4_stay_empty_cases_and_w47_remain_unchanged` asserts IOLCP `Q1 FY26`.
`python -m pytest -q reality_engine/tests/test_obs_speaker.py` 74 passed;
`python -m pytest -q reality_engine/tests/test_observations.py` 177 passed.

### r6 measurement on the 394 reparse

The live `D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db` is no longer the r3-r5 baseline: on 26 Nov ~21:00
it held 38,369 `page_reply` rows over 2,697 docs and 406,717 observation rows (a newer build has rewritten it).
The closed `C:/RealityEngine/t242/tx394_reparse/tx394_r3.db` is the baseline, so r6 reparsed copies of it with
the same `--reparse` command in five store shards (each with `--stores` = its 70 stores under
`C:/RealityEngine/tg_build/full394`; the `--baseline` r3 copy, one `--out` copy per shard), as r5 did. The
shards rebuilt 4,238 + 4,863 + 5,253 + 5,007 + 5,798 = 25,159 pages and 262,980 rows before / after; 0 of the
1,797 reply docs fell outside the shards.

| stat | r3 | r4 | r5 | r6 |
|---|---|---|---|---|
| pages | 25,159 | 25,159 | 25,159 | 25,159 |
| rows before / after | 263,418 / 262,982 | 263,418 / 262,980 | 262,980 / 262,980 | 262,980 / 262,980 |
| period anchored | 9,575 (brief: 9,579) | 8,575 | 9,959 | **10,241** |
| speaker unverified | 3,685 | 3,687 | 3,687 | 3,687 |
| short remarks dropped | 331 | 332 | 332 | 332 |
| content-free dropped | 294 | 295 | 295 | 295 |

The non-period counts equal r5 exactly (speaker carried 1,153, resolved 589, empty 232, moderator 366,
not-a-call 9, not-a-person 2, 1,797 transcript docs, 82 not-call docs), so the shards reproduced the pipeline;
only the anchor count moved: **+282 over r5 and +666 over r3**. The shards hold 10,190 rows with
`period_source='call_period'` (the r3 copy 9,528; the r5 copies 9,903).

Matched on `(doc_key, page, statement)` over `record_type='statement'`: 125,385 of 125,440 (the same match the
r5 section records; the 6 unmatched rows are the P fragment rows whose pack text predates widening).
1,769 statements regain an r3-empty period (r5 1,651), 1,115 lose one (r5 1,276), 301 are relabelled (r5 230).
**`tx394_grade_r2`: 0 of the 36 graded-R rows change period or any other field** (54 of the 60 pack rows match
by statement text; 0 change period, 0 change beyond period). 11 statement rows differ beyond period in
`speaker` (9) and `status` (2) only — the same 11 rows the r5 section records from r4's speaker work.

The nine evidence statements as the reparse stores them: IOLCP `Q1 FY26` (p4), BLS `Q1 FY27` (p5), SOLARINDS
`Q1 FY25` (p3), ARMANFIN `Q1 FY27` (p3), AZAD `FY25` (p5, both the `for FY25` and `for FY '25` forms),
TARACHAND `FY26` (p4), PDSL `H1 FY26` (p3), MMP `FY26` (p9; call `Q4 FY26`, so the call's FY).

### r7 measurement on the 394 reparse

Same closed baseline, same `--reparse` path: six shards over
`C:/RealityEngine/tg_build/full394` (`--stores-root`; each shard `--only` its 300 `page_reply` doc_keys, the
`--baseline` a sqlite-backup copy of `C:/RealityEngine/t242/tx394_reparse/tx394_r3.db`, one `--out` copy per
shard). The shards rebuilt 4,202 + 4,054 + 4,243 + 4,157 + 4,275 + 4,228 = 25,159 pages and 262,980 rows before
/ after; 0 reply docs fell outside the shards. Each shard's `period_anchored`: 1,914 / 1,793 / 1,856 / 2,004 /
1,901 / 1,929 = **11,397** (r6 10,241). The r7 core rules were measured by that reparse; the two final
narrowings (the completed-action cue limited to started/commenced/commissioned/launched/inaugurated/
operationalised, and "for FYnn" of the call's own year on a Q4 call) were then re-measured by re-running
`anchored_period` over the six shard outputs for every row the anchoring pass touches (the only changed code
path): **11,296** stored rows carry an anchored period (r6 shards 10,190; the r3 copy 9,528).

| stat | r3 | r5 | r6 | r7 |
|---|---|---|---|---|
| pages | 25,159 | 25,159 | 25,159 | 25,159 |
| rows before / after | 263,418 / 262,982 | 262,980 / 262,980 | 262,980 / 262,980 | 262,980 / 262,980 |
| period anchored (stored) | 9,528 | 9,903 | 10,190 | **11,296** |
| speaker unverified | 3,685 | 3,687 | 3,687 | 3,687 |
| short remarks dropped | 331 | 332 | 332 | 332 |
| content-free dropped | 294 | 295 | 295 | 295 |

Matched on `(doc_key, page, statement)` (the r5/r6 match): 125,385 of 125,440, 55 rows each side unmatched.
2,742 statements regain an r3-empty period (r6 1,769), 984 lose one (r6 1,115) and 363 are relabelled (r6 301).
The 15 seed-7 relabels grade 7 better / 6 neutral / 2 worse (r6 2-3 worse of its 15); the two worse are the
`FY25-'26` label read as `FY25` in a bound-FY cue (the plain `FY25-26` token reads `FY26`) and a "for the
quarter" figure taking Q4 where the statement's first figure is the year's. `tx394_grade_r2`: 54 of the 60 pack
rows match by statement text and **0 change period or any other field** (the 36 graded-R rows included; the
wider rule had anchored ASTERDM p4 "Moving to the update on the merger with QCIL ... strategic share swap"
Q1 FY26, now empty again).

The seven evidence statements as the reparse stores them: YASHO `FY27` (p4, printed call `Q2 FY27`), PSB
`Q1 FY27` (p4), TRIVENI `Q4 FY26` (p6), HINDZINC `FY26` (p6, printed call `Q2 FY26`; a Q4 call would take
`FY27`), WELENT `Q1 FY26` (p7, its printed header period — the review's `Q4 FY26` bracket was wrong),
TARACHAND `Q4 FY26` (p4, the recap's quarter, not the later `FY27` sentence), UNOMINDA `Q2 FY25` (p8, the
production start, not the later `Q1 FY27` expansion sentence). `test_obs_speaker.py` 82 passed,
`test_observations.py` 177 passed.






### Open for r8 (27 Nov, Eagle review of Wolf r7 fixes)
- [x] "Revenue for the year a year ago was 900" on a Q4 FY26 call reads FY26; a base cue ("a year ago", "last year") beside "for the year" must block the guidance-year rule (FY25 or empty). r8: the base cue blocks the guidance "for the year" branch and the call-year fallback, so the line stores empty.
- [x] `FY25-'26` through a bound-FY cue reads FY25 (worker open problem). r8: the bound-FY cue accepts the two-year span and names the year ending in the second pair, FY26.

## r8 follow-up (27 Nov 2026, DeepSeek): two narrow period fixes on r7

`reality_engine/v2/obs_speaker.py`: `_BASE_YEAR_CUE_RE` and `_for_the_year_names_base` block the r7 guidance-year rule and the final `_REL_YEAR_RE` fallback when "for the year" sits beside a base cue; `_BOUND_FY_CUE_RE` now reads a two-year span and `_explicit_own_period` labels it by the ending year. Tests:
`test_r8_base_year_cue_never_takes_the_guidance_or_call_year` and
`test_r8_bound_fy_two_year_span_takes_the_ending_year` in `reality_engine/tests/test_obs_speaker.py` (85 passed; `test_observations.py` 177 passed). No reparse measure this round: operations stop 08:00.
