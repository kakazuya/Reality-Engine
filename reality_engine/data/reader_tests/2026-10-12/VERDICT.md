# CodeCraft API models on the 40-page test (2026-10-12, free plan; test only)
| reader | pages | identifiable | Haiku's numbers | flagged numbers (checked on the slide) | median s |
|---|---|---|---|---|---|
| cc:claude-opus-5.5 | 40/40 | 94.0% | 100% | none | 39 |
| cc:claude-sonnet-5 | 40/40 | 94.1% | 100% | 2 years from footnotes ("May 20, 2019", "as of Dec 31, 2020"): junk, not misreads | 39 |
| cc:gpt-5.6-luna | 40/40 | 93.9% | 100% | 2 ALTERED: SVPGLOB p30 Gross Margin FY18/FY17 printed 24.5% / 12.8%, Luna wrote 13.3% / 9.1% (recomputed from the slide's own figures). Breaks the "report the printed number" rule | 36 |
| cc:gemini-3.7-flash | 6/40 (free 1M tokens ran out) | 100% | 100% | none | 31 |
The free 1M tokens covered ~126 pages (~8k tokens/page: these are reasoning models). Which model actually answers
cannot be verified, and the operator is anonymous: readings from it must stay tagged (model id 'cc:*') and replaceable.
