# Evening Verification -- 2026-09-25 (VerifyGate, read-only)

> Owns ONLY `tasks/verification_evening_2026-09-25.md`. Read-only: CLI reads + `mode=ro` sqlite + scoped 5-file gate. No code/schema/DB edits, no drain launches, no migration runs. Frozen ref: `tasks/wave_evening_2026-09-25.md` Slice D.
> Live DB: `reality_engine/data/equity_intelligence.db` (26.1 GB). Runs executed 2026-09-26 UTC (evening wave of 2026-09-25).

## 0. Writer-contention check

- `reality_engine/data/ingestion_queue.lock` content: `00000000000000000000000` (23 B, mtime ~11 h before run = append-handle residue, not a held OS lock; the lock is held only while a writer process runs -- see `scripts/run_ingestion_queue.py::_acquire_queue_lock`).
- Live Python processes at verification time: single PID 11184 = omp harness runner (`runner-3kj5k8n1ubht7.py`), NOT an ingestion/drain writer. No `run_ingestion_queue`, `migrate_event_version`, or vector-index build running.
- Verdict: **no writer contention -- proceeded**. (Contract: would have yielded immediately otherwise.)

## 1. Goal criteria (5 -- promotion bar, shared wave goal)

1. **G1 excess**: cohort-clustered mean excess >= +500 bps net of measured costs, per horizon.
2. **G2 cohorts**: >= 30 weekly cohorts across >= 2 index regimes.
3. **G3 hit CI**: hit-rate CI lower bound > 0.5.
4. **G4 regimes**: same sign in both regimes.
5. **G5 placebo**: shuffle-entry-date placebo approx 0 (honest gate present and strategies pass through it, not around it).

Verdict mapping is in S6.

## 2. portfolio-ledger 4x4 (verbatim command + output)

Command:

```powershell
python reality_engine/cli.py portfolio-ledger --horizons 30,90,180,365 --universes nifty50,midcap150,smallcap250,microcap250
```

Exit 0, stderr empty, 6935 bytes stdout, wall ~2.1 s. Verbatim stdout:

```json
{
  "ok": true,
  "horizons": [
    30,
    90,
    180,
    365
  ],
  "universes": [
    "Nifty 50",
    "Nifty Midcap 150",
    "Nifty Smallcap 250",
    "Nifty Microcap 250"
  ],
  "cells": {
    "Nifty 50": {
      "30": {
        "n": 14,
        "mean_excess": -0.00201890668460844,
        "hit_rate_excess_gt0": 0.35714285714285715,
        "cohorts": {
          "2026-08-24": {
            "n": 5,
            "mean_excess": 0.00899079715518574
          },
          "2026-08-31": {
            "n": 6,
            "mean_excess": -0.007529831220745108
          },
          "2026-09-07": {
            "n": 2,
            "mean_excess": -0.00496828306955948
          },
          "2026-09-14": {
            "n": 1,
            "mean_excess": -0.01810312589685725
          }
        }
      },
      "90": {
        "n": 14,
        "mean_excess": -0.00201890668460844,
        "hit_rate_excess_gt0": 0.35714285714285715,
        "cohorts": {
          "2026-08-24": {
            "n": 5,
            "mean_excess": 0.00899079715518574
          },
          "2026-08-31": {
            "n": 6,
            "mean_excess": -0.007529831220745108
          },
          "2026-09-07": {
            "n": 2,
            "mean_excess": -0.00496828306955948
          },
          "2026-09-14": {
            "n": 1,
            "mean_excess": -0.01810312589685725
          }
        }
      },
      "180": {
        "n": 14,
        "mean_excess": -0.00201890668460844,
        "hit_rate_excess_gt0": 0.35714285714285715,
        "cohorts": {
          "2026-08-24": {
            "n": 5,
            "mean_excess": 0.00899079715518574
          },
          "2026-08-31": {
            "n": 6,
            "mean_excess": -0.007529831220745108
          },
          "2026-09-07": {
            "n": 2,
            "mean_excess": -0.00496828306955948
          },
          "2026-09-14": {
            "n": 1,
            "mean_excess": -0.01810312589685725
          }
        }
      },
      "365": {
        "n": 14,
        "mean_excess": -0.00201890668460844,
        "hit_rate_excess_gt0": 0.35714285714285715,
        "cohorts": {
          "2026-08-24": {
            "n": 5,
            "mean_excess": 0.00899079715518574
          },
          "2026-08-31": {
            "n": 6,
            "mean_excess": -0.007529831220745108
          },
          "2026-09-07": {
            "n": 2,
            "mean_excess": -0.00496828306955948
          },
          "2026-09-14": {
            "n": 1,
            "mean_excess": -0.01810312589685725
          }
        }
      }
    },
    "Nifty Midcap 150": {
      "30": {
        "n": 46,
        "mean_excess": -0.03352706177102002,
        "hit_rate_excess_gt0": 0.043478260869565216,
        "cohorts": {
          "2026-08-17": {
            "n": 8,
            "mean_excess": -0.04125690861242829
          },
          "2026-08-24": {
            "n": 14,
            "mean_excess": -0.03337697540539378
          },
          "2026-08-31": {
            "n": 16,
            "mean_excess": -0.024500968041253655
          },
          "2026-09-07": {
            "n": 6,
            "mean_excess": -0.035403346457568055
          },
          "2026-09-14": {
            "n": 2,
            "mean_excess": -0.0702381747432575
          }
        }
      },
      "90": {
        "n": 46,
        "mean_excess": -0.033650684892379906,
        "hit_rate_excess_gt0": 0.043478260869565216,
        "cohorts": {
          "2026-08-17": {
            "n": 8,
            "mean_excess": -0.04196774156024762
          },
          "2026-08-24": {
            "n": 14,
            "mean_excess": -0.03337697540539378
          },
          "2026-08-31": {
            "n": 16,
            "mean_excess": -0.024500968041253655
          },
          "2026-09-07": {
            "n": 6,
            "mean_excess": -0.035403346457568055
          },
          "2026-09-14": {
            "n": 2,
            "mean_excess": -0.0702381747432575
          }
        }
      },
      "180": {
        "n": 46,
        "mean_excess": -0.033650684892379906,
        "hit_rate_excess_gt0": 0.043478260869565216,
        "cohorts": {
          "2026-08-17": {
            "n": 8,
            "mean_excess": -0.04196774156024762
          },
          "2026-08-24": {
            "n": 14,
            "mean_excess": -0.03337697540539378
          },
          "2026-08-31": {
            "n": 16,
            "mean_excess": -0.024500968041253655
          },
          "2026-09-07": {
            "n": 6,
            "mean_excess": -0.035403346457568055
          },
          "2026-09-14": {
            "n": 2,
            "mean_excess": -0.0702381747432575
          }
        }
      },
      "365": {
        "n": 46,
        "mean_excess": -0.033650684892379906,
        "hit_rate_excess_gt0": 0.043478260869565216,
        "cohorts": {
          "2026-08-17": {
            "n": 8,
            "mean_excess": -0.04196774156024762
          },
          "2026-08-24": {
            "n": 14,
            "mean_excess": -0.03337697540539378
          },
          "2026-08-31": {
            "n": 16,
            "mean_excess": -0.024500968041253655
          },
          "2026-09-07": {
            "n": 6,
            "mean_excess": -0.035403346457568055
          },
          "2026-09-14": {
            "n": 2,
            "mean_excess": -0.0702381747432575
          }
        }
      }
    },
    "Nifty Smallcap 250": {
      "30": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      },
      "90": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      },
      "180": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      },
      "365": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      }
    },
    "Nifty Microcap 250": {
      "30": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      },
      "90": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      },
      "180": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      },
      "365": {
        "n": 0,
        "mean_excess": null,
        "hit_rate_excess_gt0": null,
        "cohorts": {}
      }
    }
  },
  "skipped": {
    "unmapped-universe": 24
  },
  "actions_evaluated": 66,
  "uncovered_actions": 6
}
```

Per-horizon summary (exact, machine-read from the JSON above):

- Nifty 50 30/90/180/365: n=14, mean=-0.00201890668460844 (-20 bps), hit=0.35714285714285715, 4 cohorts each (2026-08-24 n=5 +0.00899 / 2026-08-31 n=6 -0.00753 / 2026-09-07 n=2 -0.00497 / 2026-09-14 n=1 -0.01810), identical across horizons.
- Nifty Midcap 150 30: n=46, mean=-0.03352706177102002 (-335 bps), hit=0.043478260869565216, 5 cohorts; 90/180/365: n=46, mean=-0.033650684892379906 (-337 bps), hit same, 5 cohorts (only the 2026-08-17 cohort differs 30D vs longer: -0.0412569 vs -0.0419677).
- Nifty Smallcap 250 all horizons: n=0, null. Nifty Microcap 250 all horizons: n=0, null.
- `skipped.unmapped-universe=24`, `actions_evaluated=66`, `uncovered_actions=6`.

Reading: identical to the morning baseline (S2 of `tasks/verification_2026-09-25.md`) to the last digit. Nothing >= +500 bps. All horizons identical per universe = realized-window T9 diagnostic (exits are stop/target dates).

## 3. run-calibration (verbatim command + output)

Command:

```powershell
python reality_engine/cli.py run-calibration
```

Exit 0, stderr empty, 4323 bytes stdout, wall ~2.8 s. Verbatim stdout:

```json
{
  "ok": true,
  "status": "ok",
  "mode": "ensemble",
  "horizon_days": 5,
  "folds": 3,
  "folds_improved": 1,
  "folds_decided": 3,
  "mean_delta": -0.00048291246271969747,
  "median_delta": -0.001144411838234096,
  "recommend_apply": false,
  "detail": [
    {
      "fold": 1,
      "train_to": "2026-07-01",
      "eval_from": "2026-07-09",
      "eval_to": "2026-07-27",
      "n_train": 3,
      "n_eval": 13,
      "weights": {
        "factor_statistical": 0.23218173241706067,
        "policy_macro": 0.12502272201262352,
        "business_quality": 0.4432118786511281,
        "supply_chain": 0.19958366691918766
      },
      "stats": {
        "factor_statistical": {
          "n": 0,
          "mean_edge": 0.0,
          "stderr": null,
          "t": 0.0,
          "shrunk_to_prior": true
        },
        "policy_macro": {
          "n": 3,
          "mean_edge": -0.042295,
          "stderr": 0.006442,
          "t": -6.566,
          "shrunk_to_prior": false
        },
        "business_quality": {
          "n": 3,
          "mean_edge": 0.005441,
          "stderr": 0.002127,
          "t": 2.558,
          "shrunk_to_prior": false
        },
        "supply_chain": {
          "n": 3,
          "mean_edge": -0.001813,
          "stderr": 0.001409,
          "t": -1.287,
          "shrunk_to_prior": false
        }
      },
      "edge_uniform": -0.0028447902120279024,
      "edge_weighted": -0.003989202050261998,
      "delta": -0.001144411838234096,
      "improved": false
    },
    {
      "fold": 2,
      "train_to": "2026-07-27",
      "eval_from": "2026-08-04",
      "eval_to": "2026-08-20",
      "n_train": 21,
      "n_eval": 13,
      "weights": {
        "factor_statistical": 0.12806107918007775,
        "policy_macro": 0.2906463069399741,
        "business_quality": 0.2906463069399741,
        "supply_chain": 0.2906463069399741
      },
      "stats": {
        "factor_statistical": {
          "n": 3,
          "mean_edge": -0.019955,
          "stderr": 0.010461,
          "t": -1.908,
          "shrunk_to_prior": false
        },
        "policy_macro": {
          "n": 24,
          "mean_edge": 0.004215,
          "stderr": 0.00621,
          "t": 0.679,
          "shrunk_to_prior": true
        },
        "business_quality": {
          "n": 24,
          "mean_edge": -0.000544,
          "stderr": 0.000969,
          "t": -0.561,
          "shrunk_to_prior": true
        },
        "supply_chain": {
          "n": 24,
          "mean_edge": 0.0002,
          "stderr": 0.000508,
          "t": 0.393,
          "shrunk_to_prior": true
        }
      },
      "edge_uniform": 0.006327048067874877,
      "edge_weighted": 0.004109662536265788,
      "delta": -0.002217385531609089,
      "improved": false
    },
    {
      "fold": 3,
      "train_to": "2026-08-20",
      "eval_from": "2026-08-28",
      "eval_to": "2026-09-15",
      "n_train": 39,
      "n_eval": 13,
      "weights": {
        "factor_statistical": 0.20166498990609077,
        "policy_macro": 0.3950050302817277,
        "business_quality": 0.20166498990609077,
        "supply_chain": 0.20166498990609077
      },
      "stats": {
        "factor_statistical": {
          "n": 4,
          "mean_edge": -0.009975,
          "stderr": 0.012422,
          "t": -0.803,
          "shrunk_to_prior": true
        },
        "policy_macro": {
          "n": 42,
          "mean_edge": 0.006295,
          "stderr": 0.004511,
          "t": 1.395,
          "shrunk_to_prior": false
        },
        "business_quality": {
          "n": 42,
          "mean_edge": -0.000161,
          "stderr": 0.000764,
          "t": -0.211,
          "shrunk_to_prior": true
        },
        "supply_chain": {
          "n": 42,
          "mean_edge": -0.000187,
          "stderr": 0.000399,
          "t": -0.47,
          "shrunk_to_prior": true
        }
      },
      "edge_uniform": -0.00024941267131307193,
      "edge_weighted": 0.0016636473103710204,
      "delta": 0.0019130599816840925,
      "improved": true
    }
  ],
  "applied": false,
  "scores_published": 1,
  "reason": "no out-of-sample improvement"
}
```

Key: folds=3, folds_decided=3, folds_improved=1, mean_delta=-0.00048291246271969747, median_delta=-0.001144411838234096, recommend_apply=false, applied=false, reason="no out-of-sample improvement". Gate healthy (T8): refuses when starved. (Fold windows shifted vs morning because the 5-day-horizon fold grid is date-relative: eval_to now 2026-07-27/2026-08-20/2026-09-15; fold 3 improved=true in isolation but the ensemble still refuses.)

## 4. Live counts (read-only sqlite, `mode=ro`)

All queries via `sqlite3.connect("file:reality_engine/data/equity_intelligence.db?mode=ro", uri=True)` -- SELECT/PRAGMA only, zero writes:

```sql
SELECT MAX(date) FROM daily_price_delivery;
SELECT MAX(date) FROM nse_index_breadth;
SELECT MAX(date) FROM eod_scrip_calls;
SELECT COUNT(*) FROM eod_scrip_calls;
SELECT status, COUNT(*) FROM portfolio_actions GROUP BY status;
SELECT action, COUNT(*) FROM portfolio_actions GROUP BY action;
SELECT action, COUNT(*) FROM portfolio_actions WHERE status='closed' GROUP BY action;
SELECT action, COUNT(*) FROM portfolio_actions WHERE status='open' GROUP BY action;
SELECT COUNT(*) FROM document_chunks;
SELECT COUNT(*) FROM document_chunks WHERE content IS NULL;
SELECT doc_type, COUNT(*) FROM corporate_documents GROUP BY doc_type ORDER BY 2 DESC;
SELECT is_processed, COUNT(*) FROM corporate_documents GROUP BY is_processed;
SELECT doc_type, COUNT(*) FROM corporate_documents WHERE COALESCE(is_processed,0)<>1 GROUP BY doc_type ORDER BY 2 DESC;
SELECT COUNT(*) FROM corporate_documents WHERE is_processed=2;
SELECT name, sql FROM sqlite_master WHERE type='trigger';
PRAGMA table_info(corporate_documents);
PRAGMA table_info(document_chunks);
```

Verbatim results:

- `MAX(daily_price_delivery.date)` = **2026-09-24**
- `MAX(nse_index_breadth.date)` = **2026-09-24**
- `MAX(eod_scrip_calls.date)` = **2026-09-24**; `COUNT(eod_scrip_calls)` = **5480**
- `portfolio_actions` status: closed **681**, open **160** (total 841)
- `portfolio_actions` all: BUY **165**, HOLD **667**, SELL **9**
- closed split: BUY **58** / HOLD **615** / SELL **8** (closed BUY+SELL = 66)
- open split: BUY **107** / HOLD **52** / SELL **1**
- `document_chunks` = **1685464**; NULL-content chunks = **0** (matches dispatch baseline 1,685,464 / 0 exactly)
- `corporate_documents` by type: [["OTHER_FILING", 37150], ["ANNUAL_REPORT", 26614], ["CONCALL_TRANSCRIPT", 18516], ["ANNOUNCEMENT", 16085], ["FINANCIAL_RESULT", 2747], ["INVESTOR_PRESENTATION", 1615], ["OFFER_DOCUMENT", 904]]
- `is_processed`: [[0, 91929], [1, 11701], [2, 1]] (pending 91,929 incl. exactly 1 quarantined sentinel `=2`; processed 11,701)
- pending (`COALESCE(is_processed,0)<>1`) by type: [["OTHER_FILING", 37150], ["ANNUAL_REPORT", 26263], ["ANNOUNCEMENT", 16085], ["CONCALL_TRANSCRIPT", 9140], ["FINANCIAL_RESULT", 2707], ["INVESTOR_PRESENTATION", 585]] (ANNUAL_REPORT pending **26263** = 26,262 + 1 quarantined, matching dispatch)

### 4a. Event columns (PRAGMA verbatim)

`corporate_documents` (17 cols -- event-date/version columns PRESENT, delta vs morning baseline which had 14):

```text
[[0, "id", "INTEGER", 0, null, 1], [1, "isin", "TEXT", 1, null, 0], [2, "symbol", "TEXT", 1, null, 0], [3, "doc_type", "TEXT", 1, null, 0], [4, "title", "TEXT", 1, null, 0], [5, "doc_date", "DATE", 1, null, 0], [6, "source_url", "TEXT", 0, null, 0], [7, "local_file_path", "TEXT", 0, null, 0], [8, "file_size_bytes", "INTEGER", 0, null, 0], [9, "sha256_hash", "TEXT", 0, null, 0], [10, "is_processed", "BOOLEAN", 0, "0", 0], [11, "created_at", "TIMESTAMP", 0, "CURRENT_TIMESTAMP", 0], [12, "source", "TEXT", 0, null, 0], [13, "discovery_source", "TEXT", 0, null, 0], [14, "event_date", "TEXT", 0, null, 0], [15, "event_source", "TEXT", 0, null, 0], [16, "doc_version", "INTEGER", 0, "1", 0]]
```

`document_chunks` (18 cols -- event-date/version columns PRESENT, delta vs morning baseline which had 15):

```text
[[0, "chunk_id", "INTEGER", 0, null, 1], [1, "doc_id", "INTEGER", 0, null, 0], [2, "chunk_index", "INTEGER", 1, null, 0], [3, "content", "TEXT", 1, null, 0], [4, "embedding", "TEXT", 0, null, 0], [5, "published_date", "TEXT", 0, null, 0], [6, "timestamp_start_sec", "INTEGER", 0, null, 0], [7, "timestamp_end_sec", "INTEGER", 0, null, 0], [8, "sector_id", "INTEGER", 0, null, 0], [9, "industry_id", "INTEGER", 0, null, 0], [10, "symbol", "TEXT", 0, null, 0], [11, "isin", "TEXT", 0, null, 0], [12, "fiscal_period", "TEXT", 0, null, 0], [13, "fiscal_confidence", "REAL", 0, null, 0], [14, "fiscal_source", "TEXT", 0, null, 0], [15, "event_date", "TEXT", 0, null, 0], [16, "event_source", "TEXT", 0, null, 0], [17, "doc_version", "INTEGER", 0, "1", 0]]
```

### 4b. Trigger bodies (verbatim -- honest-NULL migration NOT yet clean)

`sqlite_master` triggers:

```sql
-- trg_chunks_event_stamp
CREATE TRIGGER trg_chunks_event_stamp AFTER INSERT ON document_chunks WHEN NEW.event_date IS NULL OR NEW.event_source IS NULL OR NEW.doc_version IS NULL BEGIN UPDATE document_chunks SET event_date = COALESCE(NEW.event_date, NEW.published_date, date('now')), event_source = COALESCE(NEW.event_source, CASE WHEN NEW.event_date IS NOT NULL THEN 'explicit' WHEN NEW.published_date IS NOT NULL THEN 'published_date' ELSE 'ingest_time' END), doc_version = COALESCE(NEW.doc_version, 1) WHERE chunk_id = NEW.chunk_id; END;

-- trg_corpdocs_event_stamp
CREATE TRIGGER trg_corpdocs_event_stamp AFTER INSERT ON corporate_documents WHEN NEW.event_date IS NULL OR NEW.event_source IS NULL OR NEW.doc_version IS NULL BEGIN UPDATE corporate_documents SET event_date = COALESCE(NEW.event_date, NEW.doc_date, date('now')), event_source = COALESCE(NEW.event_source, CASE WHEN NEW.event_date IS NOT NULL THEN 'explicit' WHEN NEW.doc_date IS NOT NULL THEN 'doc_date' ELSE 'ingest_time' END), doc_version = COALESCE(NEW.doc_version, 1) WHERE id = NEW.id; END;

-- trg_rawdocs_event_stamp
CREATE TRIGGER trg_rawdocs_event_stamp AFTER INSERT ON raw_documents WHEN NEW.event_date IS NULL OR NEW.event_source IS NULL OR NEW.doc_version IS NULL BEGIN UPDATE raw_documents SET event_date = COALESCE(NEW.event_date, NEW.published_date, date('now')), event_source = COALESCE(NEW.event_source, CASE WHEN NEW.event_date IS NOT NULL THEN 'explicit' WHEN NEW.published_date IS NOT NULL THEN 'published_date' ELSE 'ingest_time' END), doc_version = COALESCE(NEW.doc_version, 1) WHERE doc_id = NEW.doc_id; END;
```

Finding for WriterSequence: event columns (`event_date`, `event_source`, `doc_version`) have landed on `corporate_documents` and `document_chunks` (trigger coverage now also includes `raw_documents`), BUT all three trigger bodies still contain `date('now')` as the terminal COALESCE fallback with an `'ingest_time'` source label -- the honest-NULL contract (NULL + `event_source='unknown'`, NEVER `date('now')`) is NOT yet satisfied. Slice A step 2 (DROP+CREATE clean triggers, verify no `date('now')` in `sqlite_master`) remains open at verification time.

## 5. Scoped 5-file gate, serial (verbatim tails + wall stamps)

Commands (serial, one process at a time, no full suites, no linters):

```powershell
python -m pytest reality_engine/tests/test_horizon_excess.py -q
python -m pytest reality_engine/tests/test_sip_backtest.py -q
python -m pytest reality_engine/tests/test_portfolio_ledger.py -q
python -m pytest reality_engine/tests/test_event_version.py -q
python -m pytest reality_engine/tests/test_desk_backtest.py -q
```

Verbatim results (tail lines, exit codes, wall):

- `test_horizon_excess`: tail `37 passed, 4 subtests passed in 3.34s` -- exit 0, wall ~4.2 s.
- `test_sip_backtest`: tail `17 passed in 0.11s` -- exit 0, wall ~1.6 s.
- `test_portfolio_ledger`: tail `29 passed, 2 subtests passed in 3.33s` -- exit 0, wall ~4.0 s.
- `test_event_version`: tail `12 passed in 0.83s` -- exit 0, wall ~2.3 s.
- `test_desk_backtest`: tail `33 passed in 0.28s` -- exit 0, wall ~0.9 s.

Total serial wall ~13 s. **5/5 green.** No test or verification asset was modified to obtain these results.

## 6. Verdict -- met/unmet mapping to the 5 goal criteria

| # | Criterion | Evidence (this file) | Met? |
|---|---|---|---|
| G1 | >=+500 bps clustered net per horizon | S2: best cell Midcap -335 bps, N50 -20 bps, small/micro n=0; all horizons identical (T9 realized-window diagnostic). Nothing positive, let alone +500 bps. | **UNMET** |
| G2 | >=30 weekly cohorts, >=2 regimes | S2: N50 4 cohorts, Midcap 5 cohorts; small/micro 0. Closed BUY+SELL count 66 (S4) is a row count, not cohorts. | **UNMET** |
| G3 | hit CI lower > 0.5 | S2: hit N50 0.357, Midcap 0.043 -- point estimates already < 0.5, so any CI lower bound is also < 0.5. | **UNMET** |
| G4 | same sign 2 regimes | S2: N50 and Midcap both negative -- same sign but the wrong sign (losses, not edge); small/micro have no data, so no second confirming regime with edge. | **UNMET** (no regime shows edge) |
| G5 | placebo approx-0 gate | Calibration refuses (`recommend_apply: false`, S3); book fails through the honest gate (negative excess, S2). Gate present and working, but no strategy passes it. | **GATE PRESENT / NO PASS** |

Overall: **0/5 met. CEO verdict stands -- NO live edge tonight, paper only.** REVOKED items (SELL +527 bps, blended +29.8, T10 confirmation, T11 trend) stay revoked; nothing in this verification re-opens them.

## 7. Deltas vs morning baseline (`tasks/verification_2026-09-25.md`, same-day)

- Ledger 4x4: identical to the last digit (N50 -20 bps n=14, Midcap -335/-337 bps n=46, small/micro n=0, unmapped 24, evaluated 66, uncovered 6). Book unchanged.
- Calibration: still refusing (`recommend_apply: false`); fold windows shifted (date-relative grid), mean_delta -0.00048 vs morning -0.00110 -- still negative, still no OOS improvement.
- Chunks: 1,653,367 -> **1,685,464** (+32,097, NULLs still 0) -- drain/migration writes landed between baseline and this run. Corp pending 93,246 -> **91,929** (-1,317), processed 10,385 -> **11,701** (+1,316), quarantine sentinel still exactly 1. EOD max still 2026-09-24; actions 681/160 unchanged.
- Schema: event-date/version columns NOW present on both tables (were absent in the morning) -- WriterSequence migration partially landed; triggers still carry `date('now')` fallback (S4b) -- honest-NULL cutover still open.
- Gate: morning ran 3 files via unittest; this evening ran the contract's 5 files serially via pytest -- 5/5 green (128 tests + 6 subtests).
