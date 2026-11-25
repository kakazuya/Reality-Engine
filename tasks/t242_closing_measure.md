# T-242: closing remarks and deferral rule - measurement

## Per-DB scan (in-process over every `record_type='statement'` row)

| DB | statements | old rule drops | new rule drops | incremental | incremental % | closing / deferral | figure drops |
|---|---:|---:|---:|---:|---:|---|---:|
| tx394_v3_r4 | 55219 | 0 | 14 | 14 | 0.025% | 3 / 11 | 0 |
| fy27_v3_r3 | 27951 | 12 | 14 | 2 | 0.007% | 2 / 0 | 0 |

## 20 sampled dropped lines (new rule, both DBs)

- [NEW] `tx394_v3_r4` id=225494 UJJIVANSFB p12 [deferral] :: Yes, we will get back on this a little later.
- [NEW] `tx394_v3_r4` id=125447 ASHIANA p5 [deferral] :: We will get back to you later on this.
- [already dropped] `fy27_v3_r3` id=66154 ADFFOODS p4 [closing] :: I will now hand over to Srini, who will take you through the financial performance in greater detail. Thank you, and over to you, Srini.
- [already dropped] `fy27_v3_r3` id=75588 AMBER p4 [closing] :: Now let me hand over to Sudhir Goyal, our CFO, for the financial highlights.
- [already dropped] `fy27_v3_r3` id=78751 ANTHEM p14 [closing] :: On the other side, Gawir will answer the other.
- [already dropped] `fy27_v3_r3` id=101675 BBOX p9 [closing] :: Yes, that's a good question and good assumption, Bajrang.
- [already dropped] `fy27_v3_r3` id=92345 AYE p8 [closing] :: Yes, I think that's a excellent question.
- [NEW] `tx394_v3_r4` id=175724 KTKBANK p15 [closing] :: liabilities, assets, guidance I had already given, continuous efforts for recovery, continuous effort for slippage improvement, continuous effort for recovery under NPA as well as technically written off account and improving the other income through third-party products, all these products, through all these sources, bank is quite confident. With my team, I am able to drive this business forward. That is an assurance from my side. Thank you very much. Thank you one and all.
- [already dropped] `fy27_v3_r3` id=105581 BHARTIARTL p4 [closing] :: With this, I will now hand over to Shashwat for an update on India business.
- [NEW] `tx394_v3_r4` id=183314 MEDANTA p18 [closing] :: Thank you, everybody, for your questions and for joining us today. Just to wrap up, as we step into our next phase of growth, we, of course, remain committed to our original philosophy of delivering the highest quality of care at the highest standard to the highest values, we believe that through this approach, we'll continue to expand our footprint in a responsible manner, invest in our people in a responsible manner and also continue to bring the highest quality and higher standard of infrastructure as close to the communities as possible.
- [NEW] `tx394_v3_r4` id=184678 MODINATUR p14 [deferral] :: On an annual basis I will have to check that number, we will get back to you on that.
- [already dropped] `fy27_v3_r3` id=78166 ANGELONE p24 [closing] :: Let Vineet take that question.
- [NEW] `fy27_v3_r3` id=82189 ARKADE p14 [closing] :: Okay, thank you. Thank you for participating in this running conference. I hope you were able to answer your questions satisfactorily and at the same time offer insights into our business. If you have any further questions or would like to know more about the company, please reach out to our investor relations manager at Valorem Advisers.
- [NEW] `tx394_v3_r4` id=201266 RUSHIL p10 [deferral] :: I can get back to you with this question once I have the right information in hand.
- [NEW] `tx394_v3_r4` id=225903 UJJIVANSFB p8 [deferral] :: We will come back to you on that as the year progresses.
- [already dropped] `fy27_v3_r3` id=83259 ARVINDFASN p4 [closing] :: I would like to now hand it over to Amisha Jain to take us through the specifics and more details about our financial performance.
- [already dropped] `fy27_v3_r3` id=89531 AURUM p6 [closing] :: I will now hand over to Shrikant to take us through the financial results.
- [already dropped] `fy27_v3_r3` id=62720 ABDL p9 [closing] :: Okay, I think this is a very important question you raised.
- [NEW] `fy27_v3_r3` id=78880 ANTHEM p17 [closing] :: Thank you everybody. Once again, it was very nice talking to all of you. As we have said before, Anthem endeavors to be totally transparent, be accurate, and continues to be well-governed. This is something that we are very mindful of and we will continue to do that.
- [NEW] `tx394_v3_r4` id=226920 UJJIVANSFB p18 [deferral] :: We will come back to you on that.

## All incremental drops (new rule minus the old greeting/boilerplate rule)

- `tx394_v3_r4` id=125447 ASHIANA p5 [deferral] :: We will get back to you later on this.
- `tx394_v3_r4` id=125449 ASHIANA p5 [deferral] :: We will revert back to you.
- `tx394_v3_r4` id=132053 BRAHMINFRA p6 [closing] :: As this is our first earnings call, we see this as the beginning of a more transparent and consistent engagement with the investor community. We remain committed to disciplined growth and operational excellence for all stakeholders. I would like to now hand over to Mr. Vivek Malhotra, General Manager Finance, who will take you through the detailed financial performance for Q4 and FY26.
- `tx394_v3_r4` id=151740 GREENPLY p5 [deferral] :: We will get back to you on the same.
- `tx394_v3_r4` id=165599 JWL p13 [deferral] :: So we will revert back to you on this in a couple of days.
- `tx394_v3_r4` id=175724 KTKBANK p15 [closing] :: liabilities, assets, guidance I had already given, continuous efforts for recovery, continuous effort for slippage improvement, continuous effort for recovery under NPA as well as technically written off account and improving the other income through third-party products, all these products, through all these sources, bank is quite confident. With my team, I am able to drive this business forward. That is an assurance from my side. Thank you very much. Thank you one and all.
- `tx394_v3_r4` id=183314 MEDANTA p18 [closing] :: Thank you, everybody, for your questions and for joining us today. Just to wrap up, as we step into our next phase of growth, we, of course, remain committed to our original philosophy of delivering the highest quality of care at the highest standard to the highest values, we believe that through this approach, we'll continue to expand our footprint in a responsible manner, invest in our people in a responsible manner and also continue to bring the highest quality and higher standard of infrastructure as close to the communities as possible.
- `tx394_v3_r4` id=184672 MODINATUR p14 [deferral] :: So, we will get back to you with that data piece.
- `tx394_v3_r4` id=184678 MODINATUR p14 [deferral] :: On an annual basis I will have to check that number, we will get back to you on that.
- `tx394_v3_r4` id=201266 RUSHIL p10 [deferral] :: I can get back to you with this question once I have the right information in hand.
- `tx394_v3_r4` id=225494 UJJIVANSFB p12 [deferral] :: Yes, we will get back on this a little later.
- `tx394_v3_r4` id=225903 UJJIVANSFB p8 [deferral] :: We will come back to you on that as the year progresses.
- `tx394_v3_r4` id=226920 UJJIVANSFB p18 [deferral] :: We will come back to you on that.
- `tx394_v3_r4` id=227088 UJJIVANSFB p8 [deferral] :: Okay, we can come back to you on that.
- `fy27_v3_r3` id=78880 ANTHEM p17 [closing] :: Thank you everybody. Once again, it was very nice talking to all of you. As we have said before, Anthem endeavors to be totally transparent, be accurate, and continues to be well-governed. This is something that we are very mindful of and we will continue to do that.
- `fy27_v3_r3` id=82189 ARKADE p14 [closing] :: Okay, thank you. Thank you for participating in this running conference. I hope you were able to answer your questions satisfactorily and at the same time offer insights into our business. If you have any further questions or would like to know more about the company, please reach out to our investor relations manager at Valorem Advisers.

## Graded packs: rows the new rule would drop

| pack | graded rows | dropped | R dropped |
|---|---:|---:|---:|
| regrade_fy27_r3 | 60 | 0 | 0 |
| regrade_tx394_r4 | 60 | 1 | 0 |
| tx394_ckpt6 | 60 | 3 | 0 |
| tx394_ckpt7 | 60 | 1 | 0 |
| tx394_ckpt8 | 60 | 0 | 0 |
| audit_tx394 | 60 | 0 | 0 |
| audit_txfy27 | 0 | 1 | 0 |

- regrade_tx394_r4 id=56 grade=J KTKBANK p15 [closing] :: liabilities, assets, guidance I had already given, continuous efforts for recovery, continuous effort for slippage improvement, continuous effort for recovery under NPA as well as technically written off account and improving the other income through third-party products, all these products, through
- tx394_ckpt6 id=29 grade=J UFLEX p3 [closing] :: Thank you, Surajit and welcome to all the participants for the Q2 earnings call of UFlex.
- tx394_ckpt6 id=32 grade=J SINGERIND p5 [closing] :: Very ﬁne quesƟon, Ashok.
- tx394_ckpt6 id=50 grade=J NH p8 [closing] :: On the second part, maybe I'll defer to Sandhya or Anesh on that, insurance sitting inside a listed company.
- tx394_ckpt7 id=17 grade=J ELLEN p10 [deferral] :: Regarding your question on FY23, maybe we'll be able to get back to you post this call.
- audit_txfy27 id=10 grade=? ANTHEM p17 [closing] :: Thank you everybody. Once again, it was very nice talking to all of you. As we have said before, Anthem endeavors to be totally transparent, be accurate, and continues to be well-governed. This is something that we are very mindful of and we will continue to do that.

## Evidence rows

- `regrade_tx394_r4` #56 KTKBANK closing remarks: dropped.
- `tx394_ckpt7` #17 ELLEN after-call deferral: dropped.
- `audit_txfy27` #10 ANTHEM closing thank-you + governance platitude: dropped (no grades.csv and the
  Hydrogen grader's final answer is not on this laptop; the row is the cited J and is visually J).
- `audit_txfy27` #17 ICICIGI closing pleasantries around an outlook: NOT dropped (the `But ...` clause is
  substantive; it is the cited P, not a J).
- `regrade_tx394_r4` #19 TARACHAND 'Thank you for the question, Mr. Jehan. ... Rs. 80 Crores ...': kept.

Commands: `python .tmp/t242_measure.py` (worktree on `PYTHONPATH`);
`python -m pytest reality_engine/tests/test_obs_speaker.py -q` (36 passed),
`python -m pytest reality_engine/tests/test_v2_guards.py -q` (18 passed);
`python -m reality_engine.v2.read_gate status` (transcript page-prompt fp 12e603811501, unchanged);
v3 window prompt fp 2fae7ddac53e unchanged.
