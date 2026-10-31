# 30 random chunks checked against their PDF pages

checked 30; all three checks passed: 26

| chunk | symbol | type | page | found page | text | page no. | known_at | match |
|---|---|---|---|---|---|---|---|---|
| 167622 | ALKEM | annual_report | 156 | 156 | OK | OK | 2020-07-16T17:20:59 | OK |
| 29185 | DOLLAR | annual_report | 88 | 88 | OK | OK | 2022-07-05T18:09:04 | OK |
| 6557 | ASHOKA | announcement | 118 | 118 | OK | OK | 2019-08-24T13:24:56 | OK |
| 194394 | HMVL | annual_report | 269 | 269 | OK | OK | 2022-08-29T21:49:43 | OK |
| 72098 | ASHIANA | deck | 28 | 28 | OK | OK | 2021-08-11T21:31:37 | OK |
| 64197 | EDELWEISS | annual_report | 142 | 142 | OK | OK | 2020-09-03T23:54:13 | OK |
| 58514 | GMRAIRPORT | announcement | 8 | 8 | OK | OK | 2019-10-15T11:10:07 | OK |
| 36580 | NLCINDIA | announcement | 380 | 380 | OK | OK | 2022-09-14T18:15:02 | OK |
| 193062 | IDEA | annual_report | 274 | 274 | OK | OK | 2022-08-07T14:21:56 | OK |
| 26869 | BAJFINANCE | deck | 15 | 15 | OK | OK | 2022-04-26T18:29:23 | OK |
| 177393 | TATAELXSI | annual_report | 41 | 41 | OK | OK | 2021-06-01T20:00:46 | OK |
| 194162 | HMVL | annual_report | 100 | 100 | OK | OK | 2022-08-29T21:49:43 | OK |
| 142965 | DLF | annual_report | 117 | 117 | OK | OK | 2023-07-13T17:25:55 | OK |
| 22791 | KHADIM | concall | 5 | 5 | OK | OK | 2021-10-27T15:07:02 | OK |
| 154795 | TEJASNET | announcement | 0 | 1 | OK | FAIL | 2024-01-19T21:23:44 | FAIL |
| 110605 | ASHIANA | announcement | 0 | 1 | OK | FAIL | 2020-07-18T15:01:16 | FAIL |
| 8332 | PIDILITIND | deck | 3 | 3 | OK | OK | 2020-02-11T11:12:28 | OK |
| 7812 | PIDILITIND | announcement | 0 | 1 | OK | FAIL | 2019-12-02T16:23:13 | FAIL |
| 24562 | APLAPOLLO | announcement | 397 | 397 | OK | OK | 2022-01-06T17:31:47 | OK |
| 57315 | IMPEXFERRO | annual_report | 45 | 45 | OK | OK | 2019-09-02T10:56:06 | OK |
| 60991 | HINDUNILVR | announcement | 11 | 11 | OK | OK | 2020-07-01T17:58:48 | OK |
| 132476 | DOLLAR | deck | 28 | 28 | OK | OK | 2022-08-10T20:33:47 | OK |
| 157816 | TMPV | announcement | 13 | 13 | OK | OK | 2019-06-27T21:03:12 | OK |
| 6957 | GMRAIRPORT | announcement | 1 | 1 | OK | OK | 2019-09-17T17:19:10 | OK |
| 147128 | PRESTIGE | annual_report | 43 | 43 | OK | OK | 2023-08-29T19:35:38 | OK |
| 52125 | TMPV | results_notes | 4 | 4 | OK | OK | 2019-05-20T16:09:57 | OK |
| 187701 | GRASIM | deck | 30 | 29 | OK | FAIL | 2022-02-14T14:36:01 | FAIL |
| 170364 | HINDALCO | annual_report | 55 | 55 | OK | OK | 2020-08-14T16:30:06 | OK |
| 183849 | KHADIM | annual_report | 150 | 150 | OK | OK | 2021-09-06T23:41:04 | OK |
| 142854 | DLF | annual_report | 35 | 35 | OK | OK | 2023-07-13T17:25:55 | OK |

## Failures as found

| chunk | symbol | type | issue | snippet |
|---|---|---|---|---|
| 154795 | TEJASNET | announcement | page_from=0 (unknown) | January 19, 2024 The Secretary National Stock Exchange of India Ltd Exchange  |
| 110605 | ASHIANA | announcement | page_from=0 (unknown) | a sshisne  you are in safe hands  18% July 2020  The Secretary  Bombay Stock |
| 7812 | PIDILITIND | announcement | page_from=0 (unknown) | Pidilite  2ndDecember, 2019  The Secretary  BSE Ltd.  Corporate Relationship |
| 187701 | GRASIM | deck | found on page 29, declared 30 | Grasim Industries Limited | Earnings Presentation | Q3 FY22 | Financial Overvie |
