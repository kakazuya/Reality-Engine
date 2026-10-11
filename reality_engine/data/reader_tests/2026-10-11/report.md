# Reader quality test, 2026-10-11 (40 pages, reference: Claude Haiku 5.5 + text layer)

| model | answered | figures | identifiable | Haiku's numbers found | unsupported numbers | median s |
|---|---|---|---|---|---|---|
| gemini-3.1-flash-lite@g1 | 40/40 | 1727 | 78.1% | 1460/1483 (98%) | 0 | 6.236802339553833 |
| dots-studio/dots-3-note-preview:free@kilo2 | 40/40 | 1650 | 85.4% | 1434/1483 (97%) | 1 | 7.409083843231201 |
| gemini-3.1-flash-lite@g2+low | 40/40 | 1734 | 72.2% | 1461/1483 (99%) | 3 | 5.5158960819244385 |

## gemini-3.1-flash-lite@g1: unsupported numbers (check on the page image)

## dots-studio/dots-3-note-preview:free@kilo2: unsupported numbers (check on the page image)
- ASRL_e653c187_p3.png: 2.0 (About Organic Products:)

## gemini-3.1-flash-lite@g2+low: unsupported numbers (check on the page image)
- TEJASNET_aeb22fe7_p6.png: 20.0 (Anniversary)
- NILAINFRA_1e1fa703_p22.png: 2.19 (52 week L)
- NILAINFRA_1e1fa703_p22.png: 6.2 (52 week H)
