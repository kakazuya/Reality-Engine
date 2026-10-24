# deck_figures schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\deck_figures.db` (9.9 GB)

## bad_docs
rows: ~9 · key columns: sha256, path, strikes, last_page, ts

- `sha256` TEXT
- `path` TEXT
- `strikes` INTEGER
- `last_page` INTEGER
- `ts` TEXT

## call_log
rows: ? · key columns: ts, model

- `ts` REAL
- `model` TEXT

## chart_trends
rows: ~1.7k · key columns: isin, symbol, known_at

- `sha256` TEXT
- `page_no` INT
- `symbol` TEXT
- `isin` TEXT
- `known_at` TEXT
- `measure` TEXT
- `span` TEXT
- `trend` TEXT
- `model` TEXT

## deck_sources
rows: 26.4k · key columns: isin, symbol, known_at

- `source` TEXT
- `source_id` TEXT
- `symbol` TEXT
- `isin` TEXT
- `exch_code` TEXT
- `known_at` TEXT
- `title` TEXT
- `url` TEXT
- `local_path` TEXT
- `sha256` TEXT
- `size_bytes` INTEGER
- `status` TEXT
- `error` TEXT
- `fetched_at` TEXT

## doc_pages
rows: ~41.1k · key columns: sha256, n_pages

- `sha256` TEXT
- `n_pages` INTEGER

## facts
rows: 13.6M · key columns: period, metric

- `sha256` TEXT
- `page_no` INTEGER
- `prompt_version` TEXT
- `model` TEXT
- `line_no` INTEGER
- `metric` TEXT
- `period` TEXT
- `raw_number` TEXT
- `value` REAL
- `unit` TEXT
- `is_final` INTEGER

## facts_metric_fts
rows: ~15.1M · key columns: metric

- `metric`

## facts_unit_fix
rows: ~6.4M · key columns: fact_rowid, old_unit, new_unit, how

- `fact_rowid` INTEGER
- `old_unit` TEXT
- `new_unit` TEXT
- `how` TEXT

## outputs
rows: ~822.2k · key columns: sha256, page_no, prompt_version, model, settings, run_ts, seconds, in_tok

- `sha256` TEXT
- `page_no` INTEGER
- `prompt_version` TEXT
- `model` TEXT
- `settings` TEXT
- `run_ts` TEXT
- `seconds` REAL
- `in_tok` INTEGER
- `out_tok` INTEGER
- `usd` REAL
- `raw_output` TEXT

## pages
rows: 815.8k · key columns: isin, symbol, known_at, doc_id

- `sha256` TEXT
- `page_no` INTEGER
- `prompt_version` TEXT
- `doc_id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `doc_type` TEXT
- `known_at` TEXT
- `route` TEXT
- `text_chars` INTEGER
- `text_numbers` INTEGER
- `img_cov` REAL
- `primary_recall` REAL
- `second_recall` REAL
- `final_model` TEXT
- `n_facts` INTEGER
- `status` TEXT
- `error` TEXT
- `run_ts` TEXT

## second_queue
rows: ? · key columns: sha256, page_no, prompt_version, task, jpeg, primary_res, queued_ts, tries

- `sha256` TEXT
- `page_no` INTEGER
- `prompt_version` TEXT
- `task` TEXT
- `jpeg` TEXT
- `primary_res` TEXT
- `queued_ts` TEXT
- `tries` INTEGER

## spend
rows: ~71.6k · key columns: ts, model, in_tok, out_tok, usd

- `ts` REAL
- `model` TEXT
- `in_tok` INTEGER
- `out_tok` INTEGER
- `usd` REAL

## unlabeled_charts
rows: ? · key columns: isin, symbol, known_at

- `sha256` TEXT
- `page_no` INTEGER
- `symbol` TEXT
- `isin` TEXT
- `known_at` TEXT
- `title`
- `other_estimates`

## unlabeled_charts_all
rows: ? · key columns: isin, symbol, known_at

- `sha256` TEXT
- `page_no` INTEGER
- `symbol` TEXT
- `isin` TEXT
- `known_at` TEXT
- `title`
- `other_estimates`
