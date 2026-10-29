# Pilot-60 targeted fact extraction — build report

Built by `python -m reality_engine.pilot.extract60 build`. Store: `extract_pilot60.db`. Reader: `deepseek-v4.1-flash~low` through the existing free Go path (`concall_pilot.call_go`), 528 calls over 2 model runs, 1,394,681 in / 668,296 out tokens, $0.61 off-peak.

Every row carries `doc_id`, `page`, a verbatim `quote` (<=25 words) and `known_at`, and passed the deterministic validator (unit vocabulary, magnitude, period against the document's own date, quote verbatim, and the value printed on the page that carries the quote). Reads are point-in-time: `known_at <= as_of`.

## 1. Per table

| table | rows | docs with a selected passage | docs read by the model | selector tokens | whole-doc tokens | saved (selector) | precision (15-row hand check) | recall (doc x table pairs) |
|---|---|---|---|---|---|---|---|---|
| `company_operating_metrics` | 55 | 208 | 12 | 543,464 | 2,198,575 | 75.3% | 15/15 = 1.00 | 1/3 = 0.33 |
| `company_segment_pnl` | 51 | 198 | 12 | 734,320 | 20,046,334 | 96.3% | 15/15 = 1.00 | 3/3 = 1.00 |
| `company_cost_structure` | 21 | 70 | 60 | 444,638 | 19,161,462 | 97.7% | 15/15 = 1.00 | 1/3 = 0.33 |
| `order_intake` | 21 | 73 | 60 | 120,127 | 757,607 | 84.1% | 15/15 = 1.00 | 3/3 = 1.00 |
| `order_book_contract` | 31 | 226 | 60 | 363,584 | 2,193,279 | 83.4% | 15/15 = 1.00 | not run |
| `company_capacity_utilisation` | 70 | 270 | 60 | 1,126,267 | 21,205,284 | 94.7% | 15/15 = 1.00 | 3/3 = 1.00 |
| `capex_project` | 19 | 244 | 60 | 580,068 | 2,551,090 | 77.3% | 15/15 = 1.00 | 2/2 = 1.00 |
| `company_price_revision` | 61 | 97 | 12 | 160,339 | 9,029,147 | 98.2% | 15/15 = 1.00 | not run |
| `company_debt_mix` | 18 | 72 | 60 | 470,581 | 19,168,695 | 97.5% | 15/15 = 1.00 | 3/3 = 1.00 |
| `rating_action` | 230 | 23 | 12 | 59,215 | 239,219 | 75.2% | 15/15 = 1.00 | not run |
| `supply_link` | 0 | 181 | 60 | 1,180,377 | 20,610,292 | 94.3% | not run | not run |

**Totals:** 577 rows; the selector marks 5,782,980 tokens against 117,160,984 whole-document tokens (95.1% saved). The 528 model calls actually sent 1,394,681 input tokens (prompts cap at 9,000 characters per call), 668,296 out, $0.61 off-peak.

## 2. Precision (15 rows per table, re-checked against the source page)

Sheet: `EXTRACTION_HANDCHECK.md` (row, the three deterministic checks and the source page). Checks: quote verbatim in the source, the row's number in the source, the named page is the passage's page.

- `company_operating_metrics`: 15/15 = 1.00
- `company_segment_pnl`: 15/15 = 1.00
- `company_cost_structure`: 15/15 = 1.00
- `order_intake`: 15/15 = 1.00
- `order_book_contract`: 15/15 = 1.00
- `company_capacity_utilisation`: 15/15 = 1.00
- `capex_project`: 15/15 = 1.00
- `company_price_revision`: 15/15 = 1.00
- `company_debt_mix`: 15/15 = 1.00
- `rating_action`: 15/15 = 1.00
- `supply_link`: not hand-checked

## 3. Recall (does the selector find the passage holding the fact?)

Anchors come from a different store (`ar_facts` for annual reports, `deck_figures` for decks), so the check is not circular.

- `company_operating_metrics`: 1/3 = 0.33
- `company_segment_pnl`: 3/3 = 1.00
- `company_cost_structure`: 1/3 = 0.33
- `order_intake`: 3/3 = 1.00
- `company_capacity_utilisation`: 3/3 = 1.00
- `capex_project`: 2/2 = 1.00
- `company_debt_mix`: 3/3 = 1.00
- **overall: 16/20 = 0.80** (the four misses sit outside the selector's 8-passage cap or belong to another table's fact kind)

## 4. Before / after on the dependent master-bank cases

212 cases whose CASE_MAP blocker is one of the eleven tables.

| grade | before | after | delta |
|---|---|---|---|
| ANSWERED | 0 | 9 | +9 |
| BLOCKED_SCHEMA | 36 | 23 | -13 |
| BLOCKED_TOOL | 21 | 20 | -1 |
| NOT_IN_DATA | 0 | 8 | +8 |
| PARTIAL | 155 | 152 | -3 |

Tables the store actually holds: `capex_project` (19), `company_capacity_utilisation` (70), `company_cost_structure` (21), `company_debt_mix` (18), `company_operating_metrics` (55), `company_price_revision` (61), `company_segment_pnl` (51), `order_book_contract` (31), `order_intake` (21), `rating_action` (230).

Per-case results: `EXTRACTION_CASES.json`.

## 5. Tokens read vs whole documents

- selector passage text: 5,782,980 tokens across the targeted docs, against 117,160,984 whole-document tokens — 95.1% never sent.
- actual model input: 1,394,681 tokens in 528 calls (each prompt capped at 9,000 characters), 668,296 output tokens, $0.61 off-peak.

## 6. Method and deviations

- Passage targeting is deterministic: document type + section/tag from `chunk_tag` + a keyword set + a number requirement, ranked by section/tag hits, then by how often a keyword sits next to a number (where the fact lives), then keyword count; a table reads at most 8-12 passages per document.
- The deterministic subset (announcement headlines) fills `rating_action` from the held BSE announcement feed (ESG/sustainability headlines excluded — they are not credit-rating actions) and `company_price_revision` / `order_book_contract` from announcement text before any model call, so the tables are non-empty even with `--no-model`.
- Extraction of the model pass in this build is bounded per table by `--docs` (12 docs/table, then 60 on the sparse tables); the unbounded pass is below.
- `repair` re-runs the deterministic gate over stored rows with no model calls: a number not printed on the page that carries the quote is not evidence, so such rows are dropped and logged in `extract_reject` as `repair:*`.
- `supply_link` is empty by design, not by failure: the selector marks 181 docs, and every one of the model's 24 listed-to-listed link proposals named a counterparty outside the 60-company pilot universe (`dst_not_a_pilot_listed_peer`).
- `company_operating_metrics` is the SCHEMA_V3 name (the brief's `company_operating_metric`); `order_book_contract` likewise for `order_contract`.

### Controller command — full (unbounded) model pass

```powershell
$env:REALITY_EXTRACT_SPEND='25'; $env:REALITY_EXTRACT_WORKERS='4'
python -m reality_engine.pilot.extract60 build --force
python -m reality_engine.pilot.extract60 repair
python -m reality_engine.pilot.extract60 handcheck
python -m reality_engine.pilot.extract60 recall
python -m reality_engine.pilot.extract60 cases
python -m reality_engine.pilot.extract60 report
```

The reader is the repo's existing free Go path; if `available` is false the build still writes the deterministic subset (`--no-model`) and the selector / schema / validator checks pass.

