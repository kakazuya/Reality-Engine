# T-242: statement window (sentence snap + referent widen) and recheck dedupe - measurement

The 394 surprise audit 2 (`C:/RealityEngine/t242/audit_tx394_2/`, dsh 76ad80de) passed 53/7/0/0; every P row was one
defect: the stored statement began after the words that give it meaning. Rules in
`reality_engine/v2/obs_speaker.py` (`widen_statement`, called by `attach_statement_speakers`) and
`reality_engine/v2/observations.py` (`dedupe_repeats`, called at the end of `recheck_db`). No prompt change: the
transcript v3 window fingerprint stays `2fae7ddac53e` (`reality_engine/v2/read_gates.json`), the page prompt stays
`12e603811501`.

## Per-DB scan (in-process over every `record_type='statement'` row; read-only on the copies)

| DB | statements | snapped | widened | noted | changed | changed % | not verbatim | label crossings |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| tx394_v3_r4 | 55,219 | 2,537 | 5,026 | 4,697 | 7,222 | 13.079% | 0 | 0 |
| fy27_v3_r3 | 27,951 | 1,159 | 2,836 | 2,228 | 3,821 | 13.670% | 0 | 0 |

877 and 358 documents read from the full394 and universe_fy27 stores (0 missing). Both are under the 15% stop, every
changed statement is a whitespace-normalised substring of its page, and no widened start crosses a printed speaker
label. `noted` = left unchanged with the `referent_outside_window:` detail note (no status change).

## 20 sentence-snap samples

- `ACMESOLAR` id=118554 p11: And, of course, so these, you can say around aggregating to around 2,500 megawatts of ... -> And then we have Bikaner 3, again, where bay is ready, so you can transmit the battery power. And, of course, so these, you can say around aggregating to around 2,500 megawatts ...
- `ADANIPOWER` id=120687 p7: NCLT has reserved the order actually for both, Coastal Energen as well as Lanco ... -> In case of Coastal Energen, the NCLT has reserved its order. NCLT has reserved the order actually for both, Coastal Energen as well as Lanco Amarkantak.
- `ALLCARGO` id=121923 p5: The segment is now witnessing green shoots and freight rates have also started ... -> LCL volumes for the Q4 FY24 stood at 2.1 million CBM which is flat compared to the last quarter. The segment is now witnessing green shoots and freight rates have also started ...
- `APARINDS` id=124320 p5: According to CEA, India's substation capacity addition saw a good momentum in ... -> In terms of the transmission line and substation addition: According to CEA, India's substation capacity addition saw a good momentum in the first half of FY'26 ...
- `ASHIANA` id=124534 p3: Cash flow continues to be healthy, driven by better collections. -> The company posted pre-tax operating cash flow of INR122.62 crores during the quarter. Cash flow continues to be healthy, driven by better collections.
- `ASHOKA` id=127113 p3: Q1 FY27 has started on a mixed note for infrastructure sector. On one hand, ... -> Let me begin by giving you a brief perspective on industry environment and then take you through some of the key developments of Ashoka during the quarter. Q1 FY27 has started ...
- `ASKAUTOLTD` id=128801 p6: and we are confident that in the last Q4, we will be around 80% of the capacity ... -> Our Bangalore plant, which was our 18th plant, is running at near optimum capacity utilization ... and we are confident that in the last Q4, we will be around 80% of the capacity ...
- `ASTRAMICRO` id=129893 p5: Beyond manufacturing, we are also making great steps in innovation. I'm pleased ... -> We successfully built and delivered wide profile of high-technology systems like RF 5G, Ashlesha and Rohini modules ... Beyond manufacturing, we are also making great steps in innovation.
- `BEML` id=130202 p12: But what I can share with you right now is we are pretty hopeful that the needed ... -> So, next year order book pipeline for mining will be even better. But what I can share with you right now is we are pretty hopeful ...
- `BETA` id=131086 p9: On the margin front, the reported margins that we have kind of disclosed include ... -> We would prefer to keep it that way, and idea is to underpromise and overdeliver. On the margin front, the reported margins ...
- `BHAGYANGR` id=131181 p6: And the joint petition has been filed before the honorable NCLT Hyderabad bench ... -> BHAGYANAGAR INDIA LIMITED ... And the joint petition has been filed before the honorable NCLT Hyderabad bench with respect to the scheme of demerger.
- `BPLPHARMA` id=131973 p6: Varenyam Healthcare was at INR 11.6 crores, which was lower than Q3, and that's ... -> The standalone business saw a sequential recovery to INR 56.5 crores and Varenyam Healthcare was at INR 11.6 crores ...
- `BRAHMINFRA` id=132629 p9: So that it will take at least 2 years from here because that is into the Delhi H ... -> And one of our GBA matter is going on regarding the suit matter is approximately INR50 crores, INR60 crores matter. So that it will take at least 2 years ...
- `CANBK` id=134298 p14: Yeah, let me explain to you, sir. I was sharing with you for the last four quart ... -> Yeah, let me explain to you, sir. I was sharing with you for the last four quarters that we have ...
- `CAPACITE` id=136137 p5: So, as I speak to you today, we are already there in Mumbai. -> We have delivered more than six or seven projects in Delhi NCR and of course Mumbai MMR. So, as I speak to you today, we are already there in Mumbai.
- `CLSEL` id=137697 p14: And my brother Vijay Setia is kind of a scientist. -> And you see the production, you see, we have to see if there is the least broken we are very careful on every part ... And my brother Vijay Setia is kind of a scientist.
- `CUB` id=139215 p5: Our Gross NPA has reduced to 1.73% in 1QFY27. Both Gross NPA and Net NPA ... -> 24 crores of technically written-off accounts. So, the trend of recovery more than slippages continues ...
- `DEEDEV` id=141341 p4: The primary objective of our IPO proceeds were to fund our working capital requi ... -> While Bansalji has already discussed the business outlook, I will now provide a more detailed review of our financial performance for the past quarter. The primary objective ...
- `DEEPAKFERT` id=143745 p6: On the outlook front, Ammonia prices have rebounded above $400 already. A planne ... -> Higher natural gas consumptions due to start-up and shut down cycle ... further weigh on t ...
- `DEEPAKNTR` id=144725 p15: So total spend will be around in the range of INR 3,200 crore. -> Further this year, we'll spend around another INR 1,000 crore to INR 1,500 crore this year further. So total spend will be around in the range of INR 3,200 crore.

## 20 referent-widen samples

- `ACMESOLAR` id=118626 p18: But what is happening is also another 40, 50 gigawatt of FDRE and this one where ... -> Actually, right now, the current calculation of CEA is you need around 200 gigawatt hour of battery to come to this if you don't add any more solar. But what is happening is also another 40, 50 gigawatt ...
- `ADANIPOWER` id=120737 p10: So those things are taken into consideration first and only then do we decide if ... -> So, for example, the quality of the equipment, how well the plant has been maintained, how well-endowed it is in terms of key indicators ... So those things are taken into consideration first ...
- `ALLCARGO` id=121942 p7: So, it is purely a function of supply and demand. There are also certain trade l ... -> If you want to ship something from Asia to Latin America today, you need to plan one month in advance ... So, it is purely a function of supply and demand.
- `APARINDS` id=124319 p5: This initiative is designed to unlock the region's vast untapped hydro potential ... -> 6.4 trillion which is $77 billion transmission plan aims to evacuate over 76 gigawatts of hydroelectric capacity from the Brahmaputra basin by 2047. This initiative is designed to ...
- `ASHIANA` id=124565 p5: The various parameters that they have used to go to suit on it. -> So on this, yes, 226 customers have gone to the consumer forum and it's also they're trying to make it a class action suit ... The various parameters that they have used ...
- `ASHOKA` id=127567 p5: The breakup of order book is as follows: Roads and Railways projects compromise ... -> This is excluding orders received post 31st March 2025 of INR795 crores. The breakup of order book is as follows ...
- `ASKAUTOLTD` id=128897 p12: And I would like to assure that now we'll be working hard to achieve the revised ... -> However, if something is left, we'll further always happy to clarify because we are a very transparent company. And I would like to assure that ...
- `ASTRAMICRO` id=129956 p11: We see -- we are fairly optimistic, honestly, guys, that given the kind of depth ... -> That path has to be chalked out by that time. We see -- we are fairly optimistic, honestly, guys ...
- `AXISOL` id=130130 p5: All of this is done with the objective that diversified revenue streams are crea ... -> We have three trademarks and we have nine patents pending. All of this is done with the objective ...
- `BEML` id=130223 p2: The 21 cubic meter rope shovel, this was done in a period of three years from sc ... -> It will undergo extensive trials for a year and then EMI AMC next year around August, September ... The 21 cubic meter rope shovel ...
- `BETA` id=131041 p6: But on an average, you can expect easily a CAGR of around 30% on this business. -> But sometimes the tenders do slip into from one financial year to another financial year. But on an average, you can expect easily a CAGR of around 30% on this business.
- `BHAGYANGR` id=131174 p5: And BIL is in the perfect position, perfectly placed to tap into all these indus ... -> Because, EV requires a lot more copper than regular cars, power and electrification is also a big growth factor, and renewable energy. And BIL is in the perfect position ...
- `BPLPHARMA` id=131742 p6: The plant is expected to be operational by 2027 and the current pace of construc ... -> Varenyam Biolifesciences Census will be aiming to get UGMP approval ... The plant is expected to be operational by 2027 ...
- `BRAHMINFRA` id=132603 p8: And suppose one year back that award will be decided, but till date the departme ... -> So whatever the interest part till date, that is consolidated into the principal part. And suppose one year back that award will be decided ...
- `CANBK` id=134185 p4: This is a basic minimum, based on the existing circumstances, we have given it, ... -> This is a basic minimum, based on the existing circumstances, we have given it, madam. But we are definitely confident that we can perform. What we are doing is outperform ...
- `CAPACITE` id=136109 p4: And that has definitely resulted in some increase. -> So what you can actually do -- and the company has improved upon the payment terms from earlier a month to 15-day good payment cycle for the labor force. And that has definitely resulted in ...
- `CLSEL` id=137697 p14: And my brother Vijay Setia is kind of a scientist. -> And you see the production, you see, we have to see if there is the least broken we are very careful on every part. If there is low broken, this gain is higher. And my brother ...
- `CUB` id=139362 p24: Hopefully, we would like to maintain this momentum and continue for this quarter ... -> And we want to maintain the cost to income at the desired level with automation with AI ... Hopefully, we would like to maintain this momentum ...
- `DEEDEV` id=141372 p5: While in previous earnings calls, we have stated that during next quarter result ... -> With a robust order book and a strategy focused on leveraging increased capital expenditure ... While in previous earnings calls, we have stated ...
- `DEEPAKFERT` id=143133 p3: This performance once again strongly validates three fundamental strategies at p ... -> What is more is in H1 itself, we are almost touching last full year's profits in view of the 93% jump in PAT of H1 itself. This performance once again strongly validates three fundamental strategies ...

## The 7 audit evidence rows

| # | symbol | page | speaker | result | new statement |
|---|---|---|---|---|---|
| 6 | LLOYDSME | 6 | Riyaz Shaikh | widened | A significant part of this pertains to the debt acquired as part of the Chemaf acquisition, which we are actively working to renegotiate on more favourable terms which would bring our group net debt down meaningfully. We will keep investors informed as and when this materializes. |
| 20 | ZENTEC | 4 | Ashok Atluri | widened | So when we look at the whole scenario, the two major product segment that the world is actually really thirsting for, one is the training to upgrade their skill set, and second is the threat to neutralize the drones. So we are in the sweet intersection between both of these. |
| 26 | CAPACITE | 4 | Mr. Katyal, Rohit Katyal | widened | While significant increase in price has been witnessed for April 26 in the wholesale price index, the company, as a prudent measure, has factored INR10 crores in procurement cost in FY26. If the escalation receivable from the client matches this increase overall over the next 2 quarters, the provisions so made will be reversed. |
| 27 | SANGAMIND | 5 | Anurag Soni | widened | So export is about 33% to 40% of our business. It will remain in that range. |
| 29 | LANDMARK | 5 | Aryaman Thakker | widened | The Seal, the homologated Atto 3 and the eMAX 7 have received a strong response. The brand has an ambition to sell upwards of 10,000 units in the current calendar year. And to achieve this, they have a number of new launches planned. |
| 30 | INFOBEAN | 11 | Avinash Sethi | widened | I mean one is technically difficult and the other one is security concerns are there where companies are not willing to share their data to the AI engine because they are worried that what happens to the data? So we are debating those issues at this point in time. How much investment we have made in Gen-I? I would say we have 3 or 4 people working on that. And we are not making any investment or say in terms of building anything. We are making investment in terms of creating an ability to deploy these AI tools and apply it into, implement it into the organizations or our clients. But that is what we are doing right now. |
| 37 | POONAWALLA | 21 | Arvind Kapil | **noted, unchanged** | across the portfolio and you will get a firsthand sense of how individual products will be fairly solid. |

All seven are verbatim page substrings. Six of the seven are widened. #37 cannot be fixed on its own page: the page
begins with the middle of a sentence that started on the previous page ("... the quality of the calibration that you
are doing across the portfolio ..."), so rule 3 applies (the turn starts on an earlier page): the statement is left
alone and `status_reason` gains `referent_outside_window:`. Widening it would pull text from the previous page and
break the "statement is a verbatim substring of its page" invariant, so the brief's "all 7 widened or snapped" and
its rule 3/page-start constraint cannot both hold for this row.

## Graded packs: rows whose statement text changes

`regrade_fy27_r3`, `tx394_ckpt6`, `audit_tx394` and `tx_fy27_surprise1` carry per-row grades; `regrade_tx394_r4`,
`tx394_ckpt7` and `tx394_ckpt8` have none on this laptop (their changed rows are listed with grade `?`).

| pack | graded rows | R rows | changed | changed R | changed other | grades file |
|---|---:|---:|---:|---:|---:|---|
| regrade_fy27_r3 | 60 | 48 | 5 | 2 | 3 | yes |
| regrade_tx394_r4 | - | - | 7 | 0 | 7 | no |
| tx394_ckpt6 | 60 | 48 | 7 | 5 | 2 | yes |
| tx394_ckpt7 | - | - | 7 | 0 | 7 | no |
| tx394_ckpt8 | - | - | 5 | 0 | 5 | no |
| audit_tx394 | 60 | 49 | 6 | 2 | 4 | yes |
| audit_tx394_2 | - | - | 13 | 0 | 13 | no (the 7 P rows are ids 6/20/26/27/29/30/37) |
| tx_fy27_surprise1 | 60 | 45 | 8 | 5 | 3 | yes |

Every changed statement is a verbatim page substring and the stored speaker is unchanged (the one speaker change,
`tx_fy27_surprise1` n=25 `Profit After Tax` -> empty, is the existing `speaker_not_a_person` rule on a W row, not the
window rule). The changed R rows:

- `regrade_fy27_r3` n=53 AXISCADES p18: "And aerospace, 51 crores ..." -> "And probably 90 to 105 in the next quarter. And aerospace, 51 crores ..."
- `regrade_fy27_r3` n=60 ALKEM p13: "For the full year, we maintained the same guidance ..." -> "So overall, the mix was better for us ... For the full year, we maintained the same guidance ..."
- `tx394_ckpt6` n=16 TARACHAND p10: "And because of these large machines ..." -> "See, ideally, I would say the range 58% to 62% ... And because of these large machines ..."
- `tx394_ckpt6` n=19 CANBK p6: "That's what actually I'm telling you sir ..." -> "- That's what actually I'm telling you sir ..."
- `tx394_ckpt6` n=28 TANLA p4: "On your first question, we have completed the acquisition ..." -> "Of course, some volumes here and there would have a quarter variation ... On your first question ..."
- `tx394_ckpt6` n=34 ICIL p7: "As this unfolds, it will all start resulting in ..." -> "So we have engaged with them. As this unfolds, it will all start resulting in ..."
- `tx394_ckpt6` n=40 VRLLOG p5: "The lower growth in tonnage and no improvements ..." -> "However, we have seen some exponential growth in the tonnage ... The lower growth in tonnage ..."
- `audit_tx394` n=1 PERMAGN p4: "Demand from the EV segment has remained muted ..." -> "For the electric vehicle and automotive segment: Demand from the EV segment has remained muted ..."
- `audit_tx394` n=21 KTKBANK p19: "But I am saying that as a percentage ..." -> "The growth in book will have a yield which will be higher in terms of the NII. But I am saying ..."
- `tx_fy27_surprise1` n=2 BCLIND p3: "That said, even with the lower-than-expected ethanol allocation ..." -> "These initiatives are expected to significantly strengthen ethanol demand from OMCs over medium to long term. That said, ..."
- `tx_fy27_surprise1` n=5 ATGL p6: "This time, we are targeting close to 80 to 90 CNG stations." -> "So our CNG stations, last year, we added some 68 CNG stations. This time, we are targeting close to 80 to 90 CNG stations."
- `tx_fy27_surprise1` n=19 ARKADE p5: "Existing pre-sales which we checked from the last quarter ..." -> "We are expecting to launch two projects in the upcoming quarter. Existing pre-sales ..."
- `tx_fy27_surprise1` n=22 BLUESTARCO p5: "A key positive was the strong inflow of data center MEP project orders ..." -> "While the revenue growth for the quarter was 13%, the margins were impacted. A key positive was ..."
- `tx_fy27_surprise1` n=23 360ONE p2: "Starting with the macros, Q2 was a quarter of two halves ..." -> "(same sentence moved back to its own start)"

## Repeat-row dedupe (`dedupe_repeats` in the `--recheck` path)

The ticket's key `(doc_key, page, measure, value_text, speaker)` also matches *distinct* rows: statement and guidance
rows print no `value_text`, so one speaker's different statements on a page share the key, and two numbers can share
a value with different labels. Measured with `python .tmp/t242/dedupe_extra.py`:

| DB | rows | exact repeats (whole printed content) | rows the narrow key calls repeats | of those, statement rows |
|---|---:|---:|---:|---:|
| tx394_v3_r4 (copy) | 117,926 | 0 | 14,558 | 12,456 |
| fy27_v3_r3 (copy) | 59,493 | 0 | 7,159 | 6,268 |
| live obs_transcripts_394_v3.db (read-only) | 228,601 | 0 | 28,860 | 24,996 |

So the two copies hold **no exact repeat**, and the live DB's reported 29,966 "repeats" are distinct observations
(one MACPOWER speaker has 30 different statements on page 24). The rule therefore keys the whole printed content
(doc_key, page, record_type, measure, printed label/axis, value, unit, scale, period, basis, dimensions, statement,
speaker, ...), keeps the verified row first and then the lowest `observation_id`, and drops the rest. On the copies it
drops 0 rows; `duplicate groups after = 0` under that key and a simulation of the loader's 1:1 copy into `obs_fact`
for KNRCON (3,161 rows) and BANKBARODA (1,563 rows) holds 0 duplicate statement groups. Unit test:
`test_dedupe_repeats_keeps_the_verified_row_then_the_lowest_id_and_scopes_by_page` (keeps `Total`/`North`/`South 0`
apart).

## Commands

```
python .tmp/t242/measure_window.py            # per-DB rule counts, packs, dedupe on .tmp copies
python .tmp/t242/samples.py                   # the 20+20 quoted samples above
python .tmp/t242/dedupe_extra.py              # exact vs narrow-key repeat counts (copies and live DB)
python -m pytest reality_engine/tests/test_obs_speaker.py reality_engine/tests/test_observations.py -q \
  -p no:cacheprovider -p nochmod_plugin --basetemp=.tmp/t242/pytest_base14   # 230 passed
python -m reality_engine.v2.read_gate status  # transcript page prompt 12e603811501; v3 window 2fae7ddac53e
```

`-p nochmod_plugin` is the sandbox workaround for pytest's mode-0700 temp dirs (`.tmp/t242/nochmod_plugin.py`); it is
not repo code.
