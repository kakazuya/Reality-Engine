# ar_facts schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\ar_facts.db` (19.1 GB)

Annual-report extraction store: document registry, ~33M extracted facts with quotes/units, processing provenance and FTS. Managed by the AR pipeline and hand-review overlays in equity_intelligence.

## ar_claims
rows: ~140.3k · key columns: doc_id

- `doc_id` INTEGER
- `owner` TEXT
- `run` TEXT
- `model` TEXT
- `ts` TEXT
- `status` TEXT

## ar_docs
rows: 33.7k · key columns: doc_id, isin, symbol

- `doc_id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `company` TEXT
- `fiscal_year` TEXT
- `fiscal_year_source` TEXT
- `filed_at` TEXT
- `filed_at_source` TEXT
- `sha256` TEXT
- `path` TEXT
- `n_pages` INTEGER
- `n_text_pages` INTEGER
- `n_pieces` INTEGER
- `status` TEXT
- `error` TEXT
- `ts` TEXT

## ar_facts
rows: 32.4M · key columns: doc_id, piece, isin, symbol, category

- `doc_id` INTEGER
- `piece` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `fiscal_year` TEXT
- `filed_at` TEXT
- `page` INTEGER
- `category` TEXT
- `item` TEXT
- `value_raw` TEXT
- `value` REAL
- `unit` TEXT
- `period` TEXT
- `basis` TEXT
- `quote` TEXT
- `model` TEXT
- `value_check` TEXT
- `prompt_version` TEXT

## ar_facts_dropped
rows: ~449.4k · key columns: doc_id, isin, symbol

- `doc_id` INT
- `piece` INT
- `isin` TEXT
- `symbol` TEXT
- `fiscal_year` TEXT
- `filed_at` TEXT
- `page` INT
- `category` TEXT
- `item` TEXT
- `value_raw` TEXT
- `value` REAL
- `unit` TEXT
- `period` TEXT
- `basis` TEXT
- `quote` TEXT
- `model` TEXT
- `value_check` TEXT
- `prompt_version` TEXT
- `dropped_reason`
- `dropped_ts`

## ar_facts_fts
rows: ~33.0M · key columns: rowid

- `item`
- `category`

## ar_facts_replaced
rows: ~31.5k · key columns: doc_id, isin, symbol

- `doc_id` INT
- `piece` INT
- `isin` TEXT
- `symbol` TEXT
- `fiscal_year` TEXT
- `filed_at` TEXT
- `page` INT
- `category` TEXT
- `item` TEXT
- `value_raw` TEXT
- `value` REAL
- `unit` TEXT
- `period` TEXT
- `basis` TEXT
- `quote` TEXT
- `model` TEXT
- `value_check` TEXT
- `prompt_version` TEXT
- `replaced_by`
- `replaced_ts`

## ar_pieces
rows: ~681.9k · key columns: doc_id, piece, prompt_version

- `doc_id` INTEGER
- `piece` INTEGER
- `prompt_version` TEXT
- `page_from` INTEGER
- `page_to` INTEGER
- `chars` INTEGER
- `model` TEXT
- `seconds` REAL
- `in_tok` INTEGER
- `out_tok` INTEGER
- `n_facts` INTEGER
- `status` TEXT
- `error` TEXT
- `raw_output` TEXT
- `ts` TEXT

## ar_skipped_pages
rows: ~521.2k · key columns: doc_id, page

- `doc_id` INTEGER
- `page` INTEGER
- `ref_doc_id` INTEGER
- `containment` REAL
- `ts` TEXT
