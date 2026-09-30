# Reality Engine — Testing Manual (Build Phases 1-6 + Likes + Visual + Lifecycle)

**Locked core:** `FUNDAMENTAL_REALITY_ENGINE_OBJECTIVES.md:1` + `AGENTS.md:3` + `postgres_schema.sql:748`. **DB `reality_engine/data/equity_intelligence.db` 40.93 MB WAL 10477 pages 743 files 577 MB**. **Tests `57 OK`**.

---

## 1. Top-Down Funnel (Objectives §1)

**Manual:** `reality_engine/db/postgres_schema.sql:7` `v_wide_moat_candidates` `Moat=0.25SC+0.25NE+0.20CA+0.20IA+0.10ES Wide≥3.5` `v_policy_adjusted_screen ENI=Severity×Prob agg≥0` `financial_metrics roic_wacc_spread>0.05`

**Test:**
```bash
python reality_engine/db/seed_fundamental.py
# expect 3 countries, 12 industries 10>=4.0
python reality_engine/processing/moat_scorer.py
# expect HAL 3.65 Wide POLYPLEX 2.65 Narrow
python reality_engine/processing/policy_engine.py
# expect ENI -3.23 agg -0.29 fail
python -m unittest reality_engine.tests.test_quant_hardening
```

---

## 2. Earnings Equation 5 Ways (§10 Investor52)

**Source:** `reality_engine/data/inbox/text/investor52_transcript.txt` 14 chunks `YT-INV52-EG`

**Test:** Ask `What are 5 ways earnings grow? Reduce Costs (gross/operating/net margin peer <30), Increase Price (pricing_power_score), Sell More Units (secular≥4), Acquire (debt_to_ebitda gate>1.5), New Markets (geographic_exposure)` → `moat_scorer` + `quarterly_financials yoy_pat_growth_pct` decomposition.

---

## 3. Lynch 6 Stock Types (§11)

**Source:** `winstock_transcript.txt` 16 chunks `YT-INV52-WIN`

**Test:** Query `Stalwart 10-19% Costco 9%/13% 200% , Fast Grower >20% , Slow <10% , Cyclical wave 25%, Turnaround drop→recovered <10%, Asset hidden` → `business_model_profiles lifecycle_stage` + `panic_monitor.py` wave detection.

---

## 4. Adjacent Possible + Graph Theory (§9 4 Levels, DEKO-619)

**Source:** `reality_engine/data/inbox/text/deko_adjacent_possible_transcript.txt` 5 chunks

**Test:** Query graph `causal_engine.trace_ripple_chain(event_id=1)` → PN=∏Pi S=|MN|×20/(1+ln(1+Lag)) steel duty 3.8/0m S76 → -2.43/3m 20.37 → -1.41/9m 8.54

---

## 5. Multimodal Ingestion (PDF/YouTube/MP3/PPTX/HTML Likes)

**Like any file:** Drop into `reality_engine/data/inbox/likes/` or `python reality_engine/cli.py ingest-like --file "C:\path\to\file.pdf" --source_url https://youtube.com/watch?v=...`

**Test:**
```bash
Get-ChildItem reality_engine/data/inbox/likes/*
python reality_engine/ingestion/pdf_ingestor.py
python reality_engine/ingestion/youtube_transcriber.py
# Verify
sqlite3 reality_engine/data/equity_intelligence.db "SELECT count(*) FROM corporate_documents WHERE symbol='POLYPLEX'" # 2
sqlite3 reality_engine/data/equity_intelligence.db "SELECT count(*) FROM intelligence_fts WHERE symbol='DEKO-619'" # 5
sqlite3 reality_engine/data/equity_intelligence.db "SELECT count(*) FROM visual_evidence_artifacts" # 100
```

---

## 6. Visual Alpha — Local GPU RapidOCR (§12)

**Pipeline:** `yt-dlp bestvideo[height<=720]` 77/64 MB → `ffmpeg fps=1/5` 24 frames → `rapidocr_onnxruntime DmlExecutionProvider+CPU 0.9s` → `visual_evidence_artifacts` `Financial_Table_Slide` `confidence 0.87-0.92` `data/visual_snapshots/YT-INV52-*/frame_*.jpg`

**Test:**
```bash
python -c "import sqlite3; print(list(sqlite3.connect('reality_engine/data/equity_intelligence.db').execute('SELECT symbol,count(*) FROM visual_evidence_artifacts GROUP BY symbol')))"
# expect YT-INV52-EG 38 YT-INV52-EG-HI 19 WIN 28 WIN-HI 15 hi-res spacing "Earnings growth is what makes" not merged
Get-ChildItem reality_engine/data/visual_snapshots -Recurse | Measure-Object
```

---

## 7. 4-Pillar Pruning & Lifecycle (§6)

**DB:** `pruning_decay_config` YouTube 3m λ0.231 Concall 6m 0.115 Budget 12m 0.058 `v_ripple_decayed S(t)=S0·e^{-λt}` `document_chunks PARTITION BY RANGE 2026_q1..q4 ivfflat`

**Test:**
```bash
python reality_engine/processing/pruning_engine.py
# expect 5.0 half-life checks, tier hot12 warm37 cold
python reality_engine/cli.py prune-decayed-signals --dry-run --show-decayed
python reality_engine/cli.py run-distillation --symbol HAL --youtube 20 --concall 4
sqlite3 reality_engine/data/equity_intelligence.db "SELECT * FROM distillation_runs ORDER BY run_date DESC LIMIT 1"
# expect 24 vectors purged moat 3.7->4.4 Wide, Structural Milestone retained
```

---

## 8. Structural vs Ephemeral Segregation (Like Persistence)

**Schema:** `raw_documents.persistence_type ENUM STRUCTURAL_THEORY/CYCLICAL_SIGNAL/EPHEMERAL_NOISE is_structural_milestone bool half_life_months expiry_date = published_date+half_life*2`

**Test:**
```sql
SELECT persistence_type, half_life_months, is_structural_milestone, expiry_date FROM raw_documents WHERE title LIKE '%Adjacent%'; -- STRUCTURAL INF
SELECT * FROM v_ripple_decayed WHERE decayed_significance>=5; -- only live signals
SELECT * FROM raw_documents WHERE expiry_date < date('now'); -- expired ephemeral (PEAD quarter)
```

---

## 9. PEAD Top40 Pipeline (Likes → Facts)

**Seats:** `C:\Users\warri\AppData\Local\Temp\kilo\top40_800.json` 40 filings `reality_engine/data/pdfs/*_filing.pdf` 19-77 MB + `intelligence_fts 350->836` + `inbox_manifest 343`

**Test Polyplex dossier:**
```bash
python C:\Users\warri\AppData\Local\Temp\kilo\polyplex_quant.py
# expect master INE633B01018 MCap 3018 PEAD 60.3 Rev 2253.62 vs 1738.67 PAT 171 vs -59.81 EPS 29 vs -6.15 daily_price 6 rows corporate_docs 2 FTS 28 (10+18 PPT)
python -c "import sqlite3; print(sqlite3.connect('reality_engine/data/equity_intelligence.db').execute('SELECT doc_type,count(*) FROM corporate_documents WHERE symbol=\"POLYPLEX\" GROUP BY doc_type').fetchall())"
# expect [('FINANCIAL_RESULT',1),('INVESTOR_PRESENTATION',1)]
Get-ChildItem reality_engine/data/pdfs/*POLYPLEX* | Select Name,Length
```

---

## 10. Top-Down Screener & Orchestrator (Phase 6)

**Funnel:** `Industry secular≥4 -> Moat≥3.5 Stable -> Policy agg ENI≥0 -> ROIC>WACC>0.05 secondary solvency`

**Test:**
```bash
python -c "from reality_engine.processing.composite_screener import top_down_screen; print(top_down_screen(top_n=5).__len__())"
# expect 4 rows 200->168 industry->4 moat->4 policy->4 roic funneled, attrs funnel_stats
python reality_engine/cli.py screen --universe nifty200 --top 20 --top-down --dry-run
python reality_engine/cli.py run-daily-alpha --top-theses 5 --top-down
# expect 3 theses Policy Catalyst->Transmission->Moat->Verdict ROIC-WACC line
python -m unittest reality_engine.tests.test_agent_and_reporting
```

---

## 11. CLI vs UI Interface (§8 Plan)

**CLI** `reality_engine/cli.py` 12 commands: `seed-ontologies` `sync-master` `backfill --days 25` `run-phase1 --days 25 --top 200 --workers 8` `verify-checkpoint` `screen --top-down` `trace-causal-chain --node UNION_BUDGET_2026_RAIL_CAPEX --max-hops 3` `simulate-macro-shock` `process-inbox` `search-concall --symbol POLYPLEX` `dashboard --port 8501` `prune-decayed-signals` `run-distillation`

**UI** `reality_engine/ui/dashboard.py` 8-tab Streamlit alongside CLI: Overview, Graph Explorer (adjacent nodes), Serendipity Inbox, Moat Lab, Policy Radar decay curves λ, Visual Alpha (frame_snapshot_url), Adjacent Possible Lab Levels 1-4, Distillation Log. WCAG 2.1 AA `grid-cols-1 sm:2 lg:3` `aria-label`.

**Test:**
```bash
python reality_engine/cli.py --help
python reality_engine/cli.py dashboard --port 8501
# Check http://localhost:8501 8 tabs, no purple AI aesthetic, skeletons aria-busy
```

---

## 12. Global DB Health

```bash
Get-ChildItem reality_engine/data/equity_intelligence.db | Select @{N="SizeMB";E={[math]::Round($_.Length/1MB,2)}}
# 40.93 MB 10477 pages WAL
sqlite3 reality_engine/data/equity_intelligence.db "SELECT 'master',count(*) FROM master_companies UNION ALL SELECT 'daily',count(*) FROM daily_price_delivery UNION ALL SELECT 'quarterly',count(*) FROM quarterly_financials UNION ALL SELECT 'annual',count(*) FROM annual_financials UNION ALL SELECT 'forensic',count(*) FROM company_forensic_health UNION ALL SELECT 'corp',count(*) FROM corporate_documents UNION ALL SELECT 'fts',count(*) FROM intelligence_fts"
# 2732/67371/1102/913/200/4003/836/343/100
python -m unittest discover -s reality_engine/tests -p "test_*.py"
# 57 OK 75s
```

---

Run each block sequentially — all blocks form your grill harness.
