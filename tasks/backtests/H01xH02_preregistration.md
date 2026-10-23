# H01 x H02 pre-registration — Stage 2 (declared before outcomes)

Written: `2026-10-21T20:24:01+00:00`. Snapshot `truth_2026-10-19.duckdb`, read-only; evidence 2021-2025.

Base H01 leg: positive PAT surprise, both-known entry, 180-session hold (the retained H01 lead in H01_signal_assessment.md).

Fixed combinations, exactly six tests, all pooled in BH:

1. **C1 confirm, M1, 180d:** H01 positive-PAT events with an M1 net-buy event in sessions [-20,+5] around the H01 decision. The confirming deal must be known before entry; entry is the later of the two t+1 opens. If several deals qualify, the latest t+1 open wins, ties by larger net buy, then later deal session.
2. **C2 confirm, M2, 180d:** same rule with M2.
3. **C3 contrast, M1, 180d:** mean confirmed minus mean unconfirmed H01 events. Unconfirmed means no M1 deal in the window. This is the decisive alpha test.
4. **C4 union book:** one long book holding H01 positive-PAT (180d) and H02 M1 (60d) events, equal weight per event within the existing caps, compared with each leg alone on CAGR, max drawdown and kill date.
5. **C5 score, 180d:** among M1-confirmed H01 events, rank by 0.5*z(PAT surprise) + 0.5*z(log M1 net deal value), fixed weights, no fitting; top tercile minus bottom tercile.
6. **C6 confirm, M1, 60d:** C1 at 60 sessions, to test whether flow confirmation speeds the drift.

No weight search, window search, horizon search or post-hoc cohort change. Anything else is exploratory and excluded from promotion/BH.

