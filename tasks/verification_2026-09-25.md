# Verification — 2026-09-25 (VerifyLedger, read-only)

> Owns NO code files. Read-only: CLI reads + `mode=ro` sqlite + scoped unittests. No schema/DB edits, no drain launches, no migration.
> Commands run 2026-09-25 against live `reality_engine/data/equity_intelligence.db`.

## 1. Goal criteria (5 — promotion bar per horizon, next_wave_plan §5 / strategy_tracker header / desk_meeting §2)

1. **G1 excess**: cohort-clustered mean excess ≥ +500bps net of measured costs, per horizon.
2. **G2 cohorts**: ≥30 weekly cohorts (≥13 for 20D) across ≥2 index regimes.
3. **G3 hit CI**: hit-rate CI lower bound > 0.5.
4. **G4 regimes**: same sign in both regimes.
5. **G5 placebo**: shuffle-entry-date placebo ≈ 0 (honest gate present and strategies fail/pass through it, not around it).

Verdict mapping is in §6. Blocking gap in §7.

## 2. portfolio-ledger 4x4 (verbatim command + output)

Command:

```powershell
python reality_engine/cli.py portfolio-ledger --horizons 30,90,180,365 --universes nifty50,midcap150,smallcap250,microcap250
```

Exit 0, stderr empty, 6657 bytes stdout. Verbatim stdout (`/tmp/verify_ledger.json`):

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
      "30": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}},
      "90": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}},
      "180": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}},
      "365": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}}
    },
    "Nifty Microcap 250": {
      "30": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}},
      "90": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}},
      "180": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}},
      "365": {"n": 0, "mean_excess": null, "hit_rate_excess_gt0": null, "cohorts": {}}
    }
  },
  "skipped": {
    "unmapped-universe": 24
  },
  "actions_evaluated": 66,
  "uncovered_actions": 6
}
```

> Per-horizon summary below is machine-generated from the parsed JSON and is exact:
> N50 30/90/180/365: n=14, mean=-0.00201890668460844, hit=0.35714285714285715, 4 cohorts each, identical across horizons.
> Midcap 30: n=46, mean=-0.03352706177102002, hit=0.043478260869565216, 5 cohorts; 90/180/365: n=46, mean=-0.033650684892379906, hit same, 5 cohorts.
> Smallcap/Microcap all horizons: n=0, null. `skipped.unmapped-universe=24`, `actions_evaluated=66`, `uncovered_actions=6`.

Reading: Nifty50 −20bps (n=14, 4 cohorts), Midcap −335/−337bps (n=46, 5 cohorts), small/micro n=0. All horizons identical per universe = realized-window `min(close, entry+h)` T9 diagnostic (exits are stop/target dates). Nothing ≥ +500bps.

## 3. run-calibration (verbatim command + output)

Command:

```powershell
python reality_engine/cli.py run-calibration
```

Exit 0, stderr empty, 4161 bytes stdout. Verbatim stdout (`/tmp/verify_calib.txt`):

```json
{
  "ok": true,
  "status": "ok",
  "mode": "ensemble",
  "horizon_days": 5,
  "folds": 3,
  "folds_improved": 1,
  "folds_decided": 3,
  "mean_delta": -0.001095273591064889,
  "median_delta": -0.0014892300053403144,
  "recommend_apply": false,
  "detail": [
    {
      "fold": 1,
      "train_to": "2026-07-01",
      "eval_from": "2026-07-09",
      "eval_to": "2026-07-24",
      "n_train": 3,
      "n_eval": 12,
      "weights": {
        "factor_statistical": 0.23218173241706067,
        "policy_macro": 0.12502272201262352,
        "business_quality": 0.4432118786511281,
        "supply_chain": 0.19958366691918766
      },
      "stats": {
        "factor_statistical": {"n": 0, "mean_edge": 0.0, "stderr": null, "t": 0.0, "shrunk_to_prior": true},
        "policy_macro": {"n": 3, "mean_edge": -0.042295, "stderr": 0.006442, "t": -6.566, "shrunk_to_prior": false},
        "business_quality": {"n": 3, "mean_edge": 0.005441, "stderr": 0.002127, "t": 2.558, "shrunk_to_prior": false},
        "supply_chain": {"n": 3, "mean_edge": -0.001813, "stderr": 0.001409, "t": -1.287, "shrunk_to_prior": false}
      },
      "edge_uniform": -0.002404610159922746,
      "edge_weighted": -0.00389384016526306,
      "delta": -0.0014892300053403144,
      "improved": false
    },
    {
      "fold": 2,
      "train_to": "2026-07-24",
      "eval_from": "2026-08-03",
      "eval_to": "2026-08-18",
      "n_train": 20,
      "n_eval": 12,
      "weights": {
        "factor_statistical": 0.12806107918007775,
        "policy_macro": 0.2906463069399741,
        "business_quality": 0.2906463069399741,
        "supply_chain": 0.2906463069399741
      },
      "stats": {
        "factor_statistical": {"n": 3, "mean_edge": -0.019955, "stderr": 0.010461, "t": -1.908, "shrunk_to_prior": false},
        "policy_macro": {"n": 23, "mean_edge": 0.005265, "stderr": 0.006393, "t": 0.824, "shrunk_to_prior": true},
        "business_quality": {"n": 23, "mean_edge": -0.000797, "stderr": 0.000977, "t": -0.816, "shrunk_to_prior": true},
        "supply_chain": {"n": 23, "mean_edge": 0.000346, "stderr": 0.000508, "t": 0.682, "shrunk_to_prior": true}
      },
      "edge_uniform": 0.008032251158211821,
      "edge_weighted": 0.006092106459422043,
      "delta": -0.0019401446987897782,
      "improved": false
    },
    {
      "fold": 3,
      "train_to": "2026-08-18",
      "eval_from": "2026-08-26",
      "eval_to": "2026-09-10",
      "n_train": 37,
      "n_eval": 12,
      "weights": {
        "factor_statistical": 0.18765221638749877,
        "policy_macro": 0.4370433508375037,
        "business_quality": 0.18765221638749877,
        "supply_chain": 0.18765221638749877
      },
      "stats": {
        "factor_statistical": {"n": 4, "mean_edge": -0.009975, "stderr": 0.012422, "t": -0.803, "shrunk_to_prior": true},
        "policy_macro": {"n": 40, "mean_edge": 0.008028, "stderr": 0.004554, "t": 1.763, "shrunk_to_prior": false},
        "business_quality": {"n": 40, "mean_edge": -0.000368, "stderr": 0.000788, "t": -0.467, "shrunk_to_prior": true},
        "supply_chain": {"n": 40, "mean_edge": -0.000102, "stderr": 0.000414, "t": -0.245, "shrunk_to_prior": true}
      },
      "edge_uniform": 0.008749536279076745,
      "edge_weighted": 0.00889309021001217,
      "delta": 0.00014355393093542536,
      "improved": true
    }
  ],
  "applied": false,
  "scores_published": 1,
  "reason": "no out-of-sample improvement"
}
```

Key: folds=3, folds_decided=3, folds_improved=1, recommend_apply=false, applied=false, reason="no out-of-sample improvement". Gate healthy (T8): refuses when starved.

## 4. Live counts (read-only sqlite, `mode=ro`)

Queries issued (all `sqlite3.connect("file:reality_engine/data/equity_intelligence.db?mode=ro", uri=True)`):

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
SELECT COUNT(*) FROM document_chunks WHERE fiscal_period IS NOT NULL;
SELECT doc_type, COUNT(*) FROM corporate_documents GROUP BY doc_type ORDER BY 2 DESC;
SELECT is_processed, COUNT(*) FROM corporate_documents GROUP BY is_processed;
SELECT doc_type, COUNT(*) FROM corporate_documents WHERE is_processed=0 GROUP BY doc_type ORDER BY 2 DESC;
PRAGMA table_info(document_chunks);
PRAGMA table_info(corporate_documents);
```

Verbatim results:

- `MAX(daily_price_delivery.date)` = **2026-09-24**
- `MAX(nse_index_breadth.date)` = **2026-09-24**
- `MAX(eod_scrip_calls.date)` = **2026-09-24**; `COUNT(eod_scrip_calls)` = **5480**
- `portfolio_actions` status: closed **681**, open **160** (total 841)
- `portfolio_actions` all: BUY **165**, HOLD **667**, SELL **9**
- closed split: BUY **58** / HOLD **615** / SELL **8** (closed BUY+SELL = 66)
- open split: BUY **107** / HOLD **52** / SELL **1**
- `document_chunks` = **1,653,367**; fiscal-labeled (`fiscal_period IS NOT NULL`) = **292,246**
- `corporate_documents` by type: OTHER_FILING 37150 / ANNUAL_REPORT 26614 / CONCALL_TRANSCRIPT 18516 / ANNOUNCEMENT 16085 / FINANCIAL_RESULT 2747 / INVESTOR_PRESENTATION 1615 / OFFER_DOCUMENT 904 (total 103,631)
- `is_processed`: 0 → **93246**, 1 → **10385**
- unprocessed (`is_processed=0`) by type: OTHER_FILING 37150 / ANNUAL_REPORT **26263** / ANNOUNCEMENT 16085 / CONCALL_TRANSCRIPT **10456** / FINANCIAL_RESULT 2707 / INVESTOR_PRESENTATION 585
- `chunk_index_meta.json`: `{"rows": 1398908, "skipped_malformed": 0, "skipped_empty": 0, "dim": 384, "dtype": "float32", ..., "built_at": "2026-09-24T04:19:39", "build_seconds": 999.3, "error": null, "source_chunks_at_build": 1642865}` → index stale by ~10.5k chunks vs live 1,653,367.
- Failed lookups (recorded honestly, schema has different names): `eod_prices(trade_date)` — no such table (correct table is `daily_price_delivery(date)`); `corporate_documents.ingestion_status` — no such column (correct split is `is_processed`); `nse_index_breadth.trade_date`, `eod_scrip_calls.call_date` — no such columns (correct is `date`).

PRAGMA `document_chunks` (15 cols — event-date/version ABSENT):

```text
(0, 'chunk_id', 'INTEGER', 0, None, 1)
(1, 'doc_id', 'INTEGER', 0, None, 0)
(2, 'chunk_index', 'INTEGER', 1, None, 0)
(3, 'content', 'TEXT', 1, None, 0)
(4, 'embedding', 'TEXT', 0, None, 0)
(5, 'published_date', 'TEXT', 0, None, 0)
(6, 'timestamp_start_sec', 'INTEGER', 0, None, 0)
(7, 'timestamp_end_sec', 'INTEGER', 0, None, 0)
(8, 'sector_id', 'INTEGER', 0, None, 0)
(9, 'industry_id', 'INTEGER', 0, None, 0)
(10, 'symbol', 'TEXT', 0, None, 0)
(11, 'isin', 'TEXT', 0, None, 0)
(12, 'fiscal_period', 'TEXT', 0, None, 0)
(13, 'fiscal_confidence', 'REAL', 0, None, 0)
(14, 'fiscal_source', 'TEXT', 0, None, 0)
```

PRAGMA `corporate_documents` (14 cols — event-date/version ABSENT):

```text
(0, 'id', 'INTEGER', 0, None, 1)
(1, 'isin', 'TEXT', 1, None, 0)
(2, 'symbol', 'TEXT', 1, None, 0)
(3, 'doc_type', 'TEXT', 1, None, 0)
(4, 'title', 'TEXT', 1, None, 0)
(5, 'doc_date', 'DATE', 1, None, 0)
(6, 'source_url', 'TEXT', 0, None, 0)
(7, 'local_file_path', 'TEXT', 0, None, 0)
(8, 'file_size_bytes', 'INTEGER', 0, None, 0)
(9, 'sha256_hash', 'TEXT', 0, None, 0)
(10, 'is_processed', 'BOOLEAN', 0, '0', 0)
(11, 'created_at', 'TIMESTAMP', 0, 'CURRENT_TIMESTAMP', 0)
(12, 'source', 'TEXT', 0, None, 0)
(13, 'discovery_source', 'TEXT', 0, None, 0)
```

Consequence: bulk ~26k annuals stay HELD until event-date/version columns land (handover §4 item 1 still open).

## 5. Scoped suites (verbatim tails)

Commands (no full discovery, no linters):

```powershell
python -m unittest reality_engine.tests.test_sip_backtest
python -m unittest reality_engine.tests.test_portfolio_ledger
python -m unittest reality_engine.tests.test_horizon_excess
```

Verbatim results:

- `test_sip_backtest`: `Ran 17 tests in 0.060s — OK` (exit 0).
- `test_portfolio_ledger`: `Ran 29 tests in 3.580s — OK` (exit 0; expected seed-skip lines: `seed skip (quarantined): GHOSTQ`, `seed skip (no_call): NOCALL`, `seed skip (no_price): NOPRICE`).
- `test_horizon_excess`: `Ran 37 tests in 3.622s — OK` (exit 0; one pre-existing `ResourceWarning: unclosed file ... p1_grid_roundtrip_*.json` at `test_horizon_excess.py:663`, test still passes).

Full tails saved at `/tmp/verify_test_{sip_backtest,portfolio_ledger,horizon_excess}.txt` (stdout+stderr+exit).

## 6. Verdict — met/unmet mapping to the 5 goal criteria

| # | Criterion | Evidence (this file) | Met? |
|---|---|---|---|
| G1 | ≥+500bps clustered net per horizon | §2: best cell Midcap −335bps, N50 −20bps, small/micro n=0; all horizons identical (T9 realized-window diagnostic). Nothing positive, let alone +500bps. | **UNMET** |
| G2 | ≥30 weekly cohorts (≥13 for 20D), ≥2 regimes | §2: N50 4 cohorts, Midcap 5 cohorts; small/micro 0. Closed BUY+SELL count 66 (§4) is a row count, not cohorts. | **UNMET** |
| G3 | hit CI lower > 0.5 | §2: hit N50 0.357, Midcap 0.043 — point estimates already < 0.5, so any CI lower bound is also < 0.5. | **UNMET** |
| G4 | same sign 2 regimes | §2: N50 and Midcap both negative — same sign but the wrong sign (losses, not edge); small/micro have no data, so no second confirming regime with edge. | **UNMET** (no regime shows edge) |
| G5 | placebo ≈ 0 gate | P1 grid placebos ≈ 0 is the honest gate (test_findings §6); current book fails through it (reject/reject stands — negative excess, §2). Calibration likewise refuses (`recommend_apply: false`, §3). Gate present and working, but no strategy passes it. | **GATE PRESENT / NO PASS** |

Overall: **0/5 met. CEO verdict stands — NO live edge today, paper only** (desk_meeting §1). REVOKED items (SELL +527bps, blended +29.8, T10 confirmation, T11 trend) stay revoked; nothing in this verification re-opens them.

## 7. Blocking gap (single)

**Cohort-clustered positive edge does not exist in the live book.** Means are negative (§2), cohorts are 4–5 not ≥30 (G2), hit rates < 0.5 (G3), calibration confirms no out-of-sample improvement (§3: `recommend_apply: false`, mean_delta −0.0011). Unblocks only via the ordered next actions (desk_meeting §5): (1) event-date/version columns + insert-stamping → release bulk; (2) guidance-change diff writer (dated deltas — only mechanism proven on-ledger, SBIN −1); (3) F1 forensic screen → F2 vol-scaled momentum grid → F3 breadth/VIX, each past the full 5-criterion bar with placebo; (4) calibration re-run post-P0b with ≥2 lenses voting; (5) slippage audit + universe-map fix (24 `unmapped-universe` skipped, 6 uncovered actions, small/micro n=0 — §2).
