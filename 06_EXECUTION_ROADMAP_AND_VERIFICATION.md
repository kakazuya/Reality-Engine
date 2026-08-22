# Module 06: Execution Roadmap & Verification Milestones

---

## 1. Phased Execution Matrix

```
+-----------------------------------------------------------------------------------------------+
|                               PHASED IMPLEMENTATION TIMELINE                                  |
+---------+-----------------------------------+---------------------------+---------------------+
| Phase   | Subsystem Focus                   | Deliverables              | Exit Verification   |
+---------+-----------------------------------+---------------------------+---------------------+
| Phase 1 | Foundations & Bhavcopy Ingestion  | SQLite DB, NSE Downloader | Gate 1 Passed       |
| Phase 2 | Telegram Forum Listener & GPU OCR | Telethon + RapidOCR ONNX  | Gate 2 Passed       |
| Phase 3 | Fundamentals, Concalls & Vectors  | BSE XBRL, LanceDB BGE-M3  | Gate 3 Passed       |
| Phase 4 | Authenticated FinanciallyFree Scp | Playwright OAuth Session  | Gate 4 Passed       |
| Phase 5 | Cloud AI Tool-Calling & Alert Bot | Online Agent + TG Bot DM  | Gate 5 (Full E2E)   |
+---------+-----------------------------------+---------------------------+---------------------+
```

---

## 2. Detailed Phase Breakdowns

### Phase 1: Database Setup & NSE Bhavcopy / Delivery Pipeline
* **Tasks**:
  1. Initialize SQLite database (`equity_intelligence.db`) with WAL mode, pragmas, and schema tables.
  2. Implement `master_sync.py` to pull NSE `EQUITY_L.csv` and BSE Scrip master into `master_companies`.
  3. Implement `bhavcopy_downloader.py` using `curl_cffi` to fetch and parse `sec_bhavdata_full.csv`.
  4. Build historical backfill routine for the past 60 trading days to compute baseline 20-day delivery SMAs.
* **Verification Gate 1**:
  - Run `python scripts/test_bhavcopy.py --date 2026-08-14`.
  - Confirm $>2,000$ active equity rows inserted into `daily_price_delivery`.
  - Confirm Delivery Spike Ratios and Delivery Conviction Scores are computed without `NULL` values.

---

### Phase 2: Telegram Multi-Thread Listener & GPU RapidOCR Engine
* **Tasks**:
  1. Configure Telethon client session with MTProto credentials (`API_ID`, `API_HASH`).
  2. Implement forum topic/thread router capturing text and downloaded media into `./data/images/telegram/`.
  3. Set up `rapidocr-onnxruntime` utilizing DirectML/ROCm on AMD Radeon RX 6700 XT.
  4. Write entity extraction module matching OCR text against `master_companies` ticker database.
* **Verification Gate 2**:
  - Run `python scripts/test_ocr.py --sample_dir ./tests/sample_charts/`.
  - Benchmark 50 sample screenshots: Average inference time must be $<60\text{ ms/image}$, with $>90\%$ ticker extraction accuracy.

---

### Phase 3: Fundamentals, Concalls & LanceDB Vector Store
* **Tasks**:
  1. Implement `bse_corp_scraper.py` to ingest quarterly financial results, XBRL disclosures, and concall PDFs.
  2. Implement `doc_parser.py` using `PyMuPDF` for digital concall text extraction and chunking.
  3. Initialize `LanceDB` on NVMe SSD and configure `BAAI/bge-m3` embedding model on GPU.
  4. Build SQLite `FTS5` virtual table indexing concall transcripts and company disclosures.
* **Verification Gate 3**:
  - Run `python scripts/test_vector_search.py --symbol KAYNES --query "semiconductor plant capex"`.
  - Confirm relevant paragraph retrieval with cosine similarity $>0.82$ and execution latency $<25\text{ ms}$.

---

### Phase 4: Authenticated FinanciallyFree Web Portal Scraper
* **Tasks**:
  1. Implement one-time interactive script `login_browser.py` using Playwright with persistent context directory (`./data/browser_profile`).
  2. Implement headless automated worker `finfree_scraper.py` navigating to `/tools/market-overview`.
  3. Intercept XHR network payloads and parse DOM tables into `financially_free_breadth` table.
* **Verification Gate 4**:
  - Run `python scripts/test_finfree_scraper.py`.
  - Confirm automated headless extraction without triggering Google OAuth re-authentication challenges.

---

### Phase 5: Cloud AI Agent Tool-Calling & Daily Alpha Synthesis
* **Tasks**:
  1. Implement `quant_screener.py` computing daily composite scores and emitting Top 20 candidates.
  2. Build `tools.py` exposing SQLite and LanceDB query functions to the Cloud LLM API.
  3. Connect `cloud_agent.py` to execute iterative tool-calling and output the Pydantic `DailyAlphaReport`.
  4. Implement `notifier.py` using `python-telegram-bot` to dispatch formatted alpha reports to private Telegram DM.
* **Verification Gate 5 (Final End-to-End Test)**:
  - Run `python scripts/run_eod_pipeline.py`.
  - End-to-end execution must complete in $<60\text{ seconds}$ total, successfully dispatching a formatted Top 5 high-conviction report.

---

## 3. Failure Modes & Operational Runbook

| Failure Vector | Trigger Condition | Automated Fallback Protocol |
| :--- | :--- | :--- |
| **NSE Bhavcopy 403 / Akamai WAF** | Cookie expiration or IP block | Rotate `curl_cffi` browser fingerprint $\to$ fallback to `pybhav` UDiFF mirror $\to$ fallback to BSE Bhavcopy. |
| **Scanned Paper PDF Disclosures** | Extracted characters $< 300$ | Convert PDF pages to 300 DPI images $\to$ route through RapidOCR engine on GPU. |
| **Telegram FloodWaitError** | Excessive message download requests | Exponential backoff with jitter (`asyncio.sleep(e.seconds + 2)`). |
| **Google Session Expiry on Portal** | OAuth token expired after 30 days | Trigger local desktop push notification to re-run `login_browser.py` interactively. |
| **Cloud LLM Rate Limit (429)** | Provider concurrency limit | Immediate automated failover from primary model (e.g., Gemini 2.5) to secondary (Claude 3.5 Sonnet / GPT-4o). |
