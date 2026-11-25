# T-242 transcript statement gate: measurement (26 Nov 2026)

Measured on a copy of `D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db` (`.tmp/t242_copy.db`, source read-only,
copy is scratch). Script-level rules only, no model call: `obs_speaker.greeting_only` (the non-content drop) and
`obs_speaker.anchored_period` (the prepared-remark period) applied to every `record_type='statement'` row; the copy
deleted the rows the new rules drop and wrote the anchored periods, then was discarded with the worktree.
Evidence: `D:/RealityEngine/hy4_out/obs_transcripts_394_v3.db.audit/ckpt_0014.fix.md` (FAIL 41R/15P/0W/4J, 26 Nov
04:55) and the packs `C:/RealityEngine/t242/tx394_ckpt1{2,3,4}/pack.jsonl` with the grades in
`C:/RealityEngine/t242/grades/tx394_ckpt001{2,3,4}_sonnet.md`.

## Numbers

| Measure | Value |
|---|---|
| statements in the copy | 125,880 |
| dropped by the NEW rules | 48 (0.04%) |
| dropped by the pre-existing closing-remarks rule (unchanged) | 20 |
| statements with an empty qc and period anchored | 9,571 (7.60%) |
| J rows of ckpt_0014 (pack 5, 27, 31, 42) dropped | 4 of 4 |
| P period rows of ckpt_0014 (pack 15, 18, 25, 28) anchored | 4 of 4: `Q1 FY26`, `FY26`, `H1 FY26`, `FY26` |
| graded R rows of the ckpt 12/13/14 packs protected | 132 |
| of those, dropped or changed | 0 |

The 3% stop (a rule may drop at most 3% of statements) is not near: 0.04%.

## J proof (all four dropped)

| pack row | observation_id | symbol | why |
|---|---|---|---|
| 5 | 379879 | GOLDIAM | every sentence is a promise to answer on e-mail |
| 27 | 141627 | DEEDEV | thanks + "open the floor for questions" |
| 31 | 235411 | ZENTEC | "informal survey ... seeing the products in action" (the demo break) |
| 42 | 217043 | TEXRAIL | "You will see that it does not end here." |

## 20 random drops (seed 7)

1. 235410 ZENTEC: I would like to actually physically show the products once.
2. 159283 IIFL: Maybe I'll have a look and get back to you.
3. 241189 UNOMINDA: I don't think I have readily available, Raghu, current import share for sunroof, but we'll definitely get back to you on this.
4. 334970 SAGILITY: With that, I'm happy to take questions and hand it over back to Siddharth.
5. 138386 CLSEL: Can we get back to you on that, please?
6. 141627 DEEDEV: Thank you all for joining the call. With this, I would like to open the floor for questions.
7. 274039 DEEDEV: So, as far as you are seeking some future guidance, I would request you to wait for some time, ...
8. 151223 GREENPLY: With this, I would like to open the floor for Q&A session.
9. 235694 ZENTEC: We can now take questions.
10. 297519 MACPOWER: Sir, we can take this offline later on.
11. 379460 GOLDIAM: I'll have to get back to you but currently the expenditure will be in tunes of the people ...
12. 268150 GKENERGY: I now request the moderator to open the floor for questions and answers.
13. 191345 ORIRAIL: ... I will cross-check it and get back to you.
14. 124293 APARINDS: we will get into more details ... and then finally open up the floor to questions.
15. 144682 DEEPAKNTR: With that, I would now request the moderator to open the floor for question-and-answer session, please.
16. 255881 MMP: That will be difficult to answer right now, but let's connect offline and we can let you know about that.
17. 253797 AGARIND: I would now like to take questions, if any.
18. 379461 GOLDIAM: So, Bhavya, if you could share where you pulled that up from later and we will get back with further details.
19. 151737 GREENPLY: Yes, I think we will get back on this volume value data.
20. 256124 TDPOWERSYS: I'd be happy to answer your questions once again after this call.

All 20 are call logistics or a deferral; none carries a figure or a business statement.

## Near misses the rules deliberately keep

- HINDZINC 262201: "Coming to the closure, we keep our cost and capex guidance intact, and now I open the floor for
  your questions." A floor line carrying measures is a statement, so a floor sentence with a measure word is never
  dropped.
- MSTCLTD 184913: a 60-word sentence that begins "if I can take the questions one by one" but then describes the
  company's business mandate; the floor rule only applies at 24 words or fewer and with no measure word.
- NOCIL 271983: "We see this trough as temporary and are quite positive to get back on a volume growth path." A
  recovery phrase ("get back on a ... growth path") is not a deferral.
- ZENTEC 235413: "one of the products has been demonstrated to them and they said this is exactly what we want" is a
  business statement about a demo, not the demo break itself.

## Notes

- The period anchor is passed in by the caller as `call_quarter(known_at)` (the label the reader was given), never
  guessed inside `obs_speaker`; an unparsed call period or a statement with no relative word leaves the row as is.
- "this quarter" resolves to the call quarter; "half year"/"first half"/"H1" to H1/H2 of the call's FY; "this/the/
  current/full year" to the call's FY; "previous/last/prior year" to the prior FY.
- The 4 P rows of ckpt_0014 (observation_id 376044, 377607, 271775, 203115) are `H1 FY26`, `FY26`, `FY26`, `Q1 FY26`;
  the copy's statement rows had no `period` before the rule, and 9,571 statements now carry one.
