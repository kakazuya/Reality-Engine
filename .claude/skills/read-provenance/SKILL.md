---
name: read-provenance
description: Every stored row records which model, gateway, harness and prompt read it, and when (Shivam 26 Nov). Use when writing a reader, a loader, a new table, or when deciding which model's rows to replace or discard.
---

# Read provenance (Shivam 26 Nov 2026)

Why: models get better and cheaper; we must know exactly which rows a model/gateway/harness/prompt produced, compare
them with a new read, and discard or replace them. Raw documents stay on Drive (`gdrive:InfoDiffusion_archive`) so any
part can be re-read.

## Columns every model-read row carries
| Column | Example | Source |
|---|---|---|
| `reader` | `hy4-flash-free` | MODELS registry key |
| `read_model` | `opencode-go/hy4-flash-free` | `observations.read_provenance()` |
| `read_gateway` | `opencode-go`, `opencode-zen`, `kilo-gateway`, `google-ai-studio`, `deepseek-api`, `local-cli` | `observations.gateway_of(entry)` from the entry's base URL |
| `read_harness` | `reality_engine.v2.observations (direct HTTP)`, `agy`, `claude-code`, `dsh`, `opencode` | env `REALITY_READ_HARNESS` (default our script) |
| `prompt_fp` | `results:e6d289ddd672` | `read_gate.fingerprint(doc_type)` per run |
| `read_at` | ISO timestamp | at write |

## Where it is done
- `reality_engine/v2/observations.py`: `MIGRATIONS` adds the columns to any output DB; `write_rows` fills them.
- `reality_engine/scripts/backfill_read_provenance.py`: fills rows read before 26 Nov (from `reader` + `page_reply`).
- `reality_engine/scripts/load_observations.py`: carries them into store `obs_fact` (`_select_list` gives NULL for an
  older source DB).
- `reality_engine/research/filing_events.py`: the same four columns on every `event` row (`read_provenance()` fills
  them in `_insert`); `_ensure_event_columns` adds them to an old events DB, and the `load_observations` column union
  carries them into store `filing_event`.

## When you add a reader or a table
- Add the same columns (TEXT NOT NULL DEFAULT '') and fill them at write; a migration for old DBs; a backfill.
- Not yet done (26 Nov): KPI / guidance extractors, OCR fill, agy/Claude page reads.
- Test: one row written -> four columns set; one old DB backfilled.

## Using it
- "Which rows did model X read?": `SELECT ... WHERE read_model=? AND read_at BETWEEN ...` in the hy4 DB or `obs_fact`.
- Replacing a model: new output DB beside the old, loader priority per company (docs/CONTINUOUS_STORE_ARCHITECTURE.md).
