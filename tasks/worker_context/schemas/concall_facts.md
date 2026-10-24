# concall_facts schema

File: `C:\Users\warri\Downloads\Info_Diffusion_Model\reality_engine\data\concall_facts.db` (741 MB)

Concall transcript extraction store: one row per processed concall document, extracted guidance/analyst items as text, QA checks and FTS.

## cc_docs
rows: 9.3k · key columns: doc_id, isin, symbol

- `doc_id` INTEGER
- `isin` TEXT
- `symbol` TEXT
- `filed_at` TEXT
- `status` TEXT
- `model` TEXT
- `key_name` TEXT
- `chars` INTEGER
- `in_tok` INTEGER
- `out_tok` INTEGER
- `cost_usd` REAL
- `seconds` REAL
- `checks_json` TEXT
- `raw_json` TEXT
- `error` TEXT
- `run_at` TEXT
- `priority` INTEGER
- `period_discussed` TEXT
- `period_q` INTEGER
- `period_fy` INTEGER

## cc_item_checks
rows: ~87.9k · key columns: doc_id, list_name, idx

- `doc_id` INTEGER
- `list_name` TEXT
- `idx` INTEGER
- `value_in_quote` INTEGER
- `period_in_quote` INTEGER
- `direction_supported` INTEGER
- `speaker_role` TEXT
- `speaker` TEXT
- `metric_key` TEXT
- `value_low` REAL
- `value_high` REAL
- `value_is_pct` INTEGER
- `item_fy` INTEGER
- `computed_direction` TEXT
- `prev_doc_id` INTEGER
- `prev_value_mid` REAL
- `checked_at` TEXT

## cc_items
rows: 645.0k · key columns: doc_id, list_name, idx, isin

- `doc_id` INTEGER
- `list_name` TEXT
- `idx` INTEGER
- `isin` TEXT
- `filed_at` TEXT
- `metric` TEXT
- `value` TEXT
- `unit` TEXT
- `period` TEXT
- `basis` TEXT
- `direction` TEXT
- `firmness` TEXT
- `signal` TEXT
- `statement` TEXT
- `quote` TEXT
- `item_json` TEXT

## cc_items_fts
rows: ~717.8k · key columns: rowid

- `metric`
- `statement`
- `quote`
