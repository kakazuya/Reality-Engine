# Module 01: Data Ingestion Pipeline Specification

---

## 1. Overview & Cadence Schedule

The Ingestion Pipeline is responsible for gathering raw data from exchanges, regulatory feeds, Telegram forum channels, and external web portals.

```
+---------------------------------------------------------------------------------------+
|                              INGESTION EXECUTION SCHEDULE                             |
+-------------------+------------------------------------+------------------------------+
| Cadence           | Target Data Source                 | Primary Method               |
+-------------------+------------------------------------+------------------------------+
| Continuous (Live) | Telegram Channel Forum Threads     | Telethon MTProto Userbot     |
| Daily 17:45 IST   | NSE Full Bhavcopy & Delivery Pos.  | curl_cffi Session Downloader |
| Daily 18:00 IST   | BSE Scrip EOD Bhavcopy             | BSE Direct API Downloader    |
| Daily 18:30 IST   | BSE/NSE Financial Results & XBRL   | Corporate Actions Scraper    |
| Daily 19:00 IST   | Concall Transcripts & Presentations| Corporate Announcements Feed |
| Daily 19:30 IST   | FinanciallyFree Market Overview    | Playwright Persistent Session|
+-------------------+------------------------------------+------------------------------+
```

---

## 2. Symbol Master Synchronization

### Objective
Maintain an offline mapping dictionary between NSE Symbols, BSE Scrip Codes, ISINs, Company Names, and Common Market Aliases.

### Implementation
- **Source**: 
  - NSE Equity Master: `https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv`
  - BSE Scrip Master: `https://www.bseindia.com/corporates/List_Scrips.html`
- **Output Table**: `master_companies`
- **Sync Cadence**: Weekly (Sunday night) or on discovery of an unknown ticker.

```python
# Primary Strategy: Automated Sync
import io
import pandas as pd
from curl_cffi import requests

def sync_symbol_master():
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}
    url = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
    res = requests.get(url, headers=headers, impersonate="chrome120")
    df = pd.read_csv(io.StringIO(res.text))
    # Columns: SYMBOL, NAME OF COMPANY, SERIES, ISIN NUMBER
    return df[df['SERIES'] == 'EQ']
```

---

## 3. Layer 1: Fundamentals, Concalls & Disclosures (EOD)

### A. Corporate Financials & XBRL
* **Primary Source**: BSE Corporate Filings Endpoint (`https://api.bseindia.com/BseIndiaAPI/api/AnnSubCategoryGetData/w`)
  - Parameters: `scrip_code=""`, `category="Result"`, `from_date=today`, `to_date=today`
  - When an announcement contains an `.xml` or `.xbrl` attachment, parse it directly with `lxml` to extract Revenue, EBITDA, PAT, and EPS.
* **Fallback 1**: NSE Corporate Announcements API (`https://www.nseindia.com/api/corporate-announcements?index=equities`).
* **Fallback 2**: Screener.in / `yfinance` scraper for quarterly numbers.

### B. Earnings Concall Transcripts & Investor Presentations
* **Primary Source**: BSE Corporate Filings with Category `Company Update` / `Investor Presentation` / `Concall Transcript`.
* **Download Path**: `./data/pdfs/YYYY-MM-DD/{SYMBOL}_concall_{ID}.pdf`
* **Fallback 1**: NSE Corporate Filings attachments endpoint (`https://nsearchives.nseindia.com/corporate/...`).
* **Fallback 2**: Dedicated Concall repositories (ResearchBytes / Trendlyne public URLs).

---

## 4. Layer 2: Daily Technicals & Deliverable Position

### A. NSE Full Security Deliverable Bhavcopy (`sec_bhavdata_full`)
* **URL Structure**: `https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_DDMMYYYY.csv`
* **Data Fields**:
  - `SYMBOL`: NSE Ticker
  - `SERIES`: `EQ` (Equities) / `BE` (Book Entry/Trade-to-Trade)
  - `OPEN_PRICE`, `HIGH_PRICE`, `LOW_PRICE`, `CLOSE_PRICE`, `PREV_CLOSE`
  - `TTL_TRD_QNTY`: Total Traded Volume
  - `TURNOVER_LACS`: Turnover in Lakhs
  - `NO_OF_TRADES`: Number of Trades executed
  - `DELIV_QTY`: Deliverable Quantity (Institutional + Delivery volume)
  - `DELIV_PER`: Deliverable Percentage ($\frac{\text{DELIV\_QTY}}{\text{TTL\_TRD\_QNTY}} \times 100$)

```python
from curl_cffi import requests

def fetch_nse_bhavcopy(date_str: str) -> pd.DataFrame:
    # date_str in format: DDMMYYYY, e.g., '14082026'
    url = f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{date_str}.csv"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.nseindia.com/"
    }
    # Warm up session
    session = requests.Session(impersonate="chrome120")
    session.get("https://www.nseindia.com", headers=headers)
    
    res = session.get(url, headers=headers)
    if res.status_code == 200:
        df = pd.read_csv(io.StringIO(res.text.strip()))
        df.columns = df.columns.str.strip()
        return df[df['SERIES'].isin(['EQ', 'BE'])]
    raise RuntimeError(f"Failed to fetch Bhavcopy: HTTP {res.status_code}")
```

* **Fallback 1**: `pybhav` library downloading UDiFF Bhavcopy (`BhavCopy_NSE_CM_...csv.zip`) + `MTO_DDMMYYYY.DAT` (Deliverable trade positions).
* **Fallback 2**: BSE Daily Equity Bhavcopy (`https://www.bseindia.com/markets/MarketInfo/BhavCopy.aspx`).

---

## 5. Layer 3: Telegram Forum Threads & OCR Ingestion

### A. Telethon MTProto Client Architecture
* **Library**: `Telethon` (Async Python MTProto framework).
* **Topic / Thread Routing**:
  - Supergroup channels use the Telegram Forum Topics feature.
  - Listen for `events.NewMessage(chats=TARGET_CHANNELS)`.
  - Extract `message.reply_to_msg_id` (indicates Thread Root Message ID).
  - Categorize by Topic Name (e.g., *"Chart Breakouts"*, *"Quarterly Results Analysis"*, *"Sector Trends"*).

```python
from telethon import TelegramClient, events
import os

client = TelegramClient('data/telegram_session', API_ID, API_HASH)

@client.on(events.NewMessage(chats=TARGET_CHANNELS))
async def handle_incoming_telegram_message(event):
    msg = event.message
    thread_id = msg.reply_to_msg_id or 0
    text_content = msg.message or ""
    media_path = None
    
    if msg.photo or (msg.file and msg.file.mime_type.startswith('image/')):
        os.makedirs('data/images/telegram', exist_ok=True)
        media_path = await msg.download_media(file=f'data/images/telegram/{msg.id}')
    
    # Send to processing queue for RapidOCR and Symbol extraction
    await enqueue_telegram_item(msg.id, thread_id, text_content, media_path, msg.date)
```

* **Fallback 1**: `Pyrogram` async client with identical handler routing.
* **Fallback 2**: Telegram Desktop local export folder watcher (`watchdog` file observer).

---

## 6. Layer 3: Authenticated FinanciallyFree Scraper

### A. Portal Architecture (`financiallyfree.in/tools/market-overview`)
* **Challenge**: The portal requires Google Gmail OAuth login. Automated scraping via simple HTTP requests is rejected.
* **Solution**: `Playwright` persistent browser context.

### B. Execution Flow
1. **Initial Interactive Handshake (Run Once Manually)**:
   - Script opens non-headless Chromium pointing to persistent folder `./data/browser_profile`.
   - User logs in via Google OAuth.
   - Session tokens, local storage, and cookies are persisted on disk.
2. **Automated Headless EOD Run (Daily 19:30 IST)**:
   - Script launches headless Chromium using `./data/browser_profile`.
   - Navigates directly to `https://www.financiallyfree.in/tools/market-overview`.
   - Intercepts AJAX/XHR JSON responses containing sector advance/decline, market breadth, and sector momentum metrics.
   - Extracts rendered tables into structured DataFrame $\to$ saved to SQLite.
   - Closes browser instance (freeing RAM immediately).

```python
from playwright.async_api import async_playwright

async def scrape_financially_free():
    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir="./data/browser_profile",
            headless=True,
            viewport={"width": 1920, "height": 1080}
        )
        page = await context.new_page()
        
        # Intercept backend API calls
        captured_data = {}
        async def handle_response(response):
            if "api" in response.url and "json" in response.headers.get("content-type", ""):
                captured_data[response.url] = await response.json()
        
        page.on("response", handle_response)
        await page.goto("https://www.financiallyfree.in/tools/market-overview", wait_until="networkidle")
        
        # Fallback: Extract DOM table elements if API interception is blocked
        dom_tables = await page.evaluate("() => document.querySelector('table')?.innerText")
        await context.close()
        return captured_data, dom_tables
```

* **Fallback 1**: Chrome Extension dumping session cookies to `./data/cookies.json` read by `curl_cffi`.
* **Fallback 2**: Full-page screenshot capture $\to$ RapidOCR table parser.

---

## 7. Long-Term Historical Backfill Strategy (>60 Days to 5+ Years)

When initializing the database or analyzing multi-year structural cycles, the system employs a **3-Track Hybrid Ingestion Architecture**:

```
                                +---------------------------------------------------+
                                |   LONG-TERM HISTORICAL BACKFILL (>60d to 5-10y)   |
                                +-------------------------+-------------------------+
                                                          |
                 +----------------------------------------+---------------------------------------+
                 |                                        |                                       |
+----------------+----------------+      +----------------+----------------+     +----------------+----------------+
| TRACK 1: MULTI-YEAR OHLCV       |      | TRACK 2: HISTORICAL DELIVERY    |     | TRACK 3: 5-10Y FINANCIALS & XBRL|
| - yfinance (Fast bulk download) |      | - nse-archives / pybhav         |     | - BSE Historical Corp Feed      |
| - 5-10 years daily price data   |      | - chartiny/nse-sec-bhavdata-full|     | - Screener.in Python Scraper    |
| - Establishes 50/200 EMA & 52W  |      | - Computes multi-year Delivery  |     | - Populates 20-quarter P&L, BS  |
|   high multi-year baselines     |      |   accumulation baselines        |     |   and Concall links             |
+---------------------------------+      +---------------------------------+     +---------------------------------+
```

### Track 1: Multi-Year Price Action & Trend Baseline (`yfinance`)
* **Role**: Bulk-downloads 5 to 10 years of adjusted OHLCV for all ~2,500 NSE/BSE symbols (`TCS.NS`, `RELIANCE.NS`, `KAYNES.NS`).
* **Throughput**: ~2,000 tickers downloaded in $<90\text{ seconds}$ via `yfinance.download(tickers, period="5y", interval="1d", group_by="ticker", threads=True)`.
* **Limitation Addressed**: `yfinance` **does not contain Indian deliverable quantities**. Track 1 is strictly used to populate historical Stage-2 trend bases, 52-week highs, 200 EMAs, and long-term beta.

### Track 2: Multi-Year Deliverable Volumes & Bhavcopy (`nse-archives` / `chartiny`)
* **Role**: Backfills historical `DELIV_QTY` and `DELIV_PER` for past years.
* **Source**: Open-source maintained archive mirrors (e.g., `chartiny/nse-sec-bhavdata-full`, `pybhav`, or direct NSE archives).
* **Storage**: Ingested in bulk batches into `daily_price_delivery` to establish continuous rolling 20-day delivery averages.

### Track 3: Multi-Year Fundamentals & Concalls (BSE Archive + Screener)
* **Role**: Backfills 5 to 10 years (20 to 40 quarters) of balance sheets, P&L, cash flows, and concall PDFs.
* **Source**: BSE Corporate Announcement API with yearly date range filters (`from_date=01/01/2021&to_date=31/12/2021`) + Screener.in automated parser.

---

## 8. The Drop-In Research Inbox & Autonomous Knowledge Enricher

To allow effortless ingestion of external articles, institutional PDFs, macroeconomic essays, brokerage reports, and news clippings, the system maintains a **Dedicated Drop-In Folder**:

$$\text{User drops file into } \texttt{./data/inbox/} \longrightarrow \text{Automated Evening Run} \longrightarrow \text{Auto-Classification} \longrightarrow \text{Knowledge Graph \& DB Enriched}$$

```
+----------------------------------------------------------------------------------------------------+
|                                    USER DROP-IN INBOX (./data/inbox/)                               |
|        - Brokerage Reports (PDF), Industry Articles (TXT/MD), Scanned Excerpts (PNG/JPG)           |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                                 AUTONOMOUS INBOX PROCESSOR & PARSER                                |
|  1. File Detection: Scans ./data/inbox/ on every daily evening run                                 |
|  2. Extraction: PyMuPDF (PDFs) / RapidOCR on RX 6700 XT (Images) / Text Decoders                   |
|  3. Deduplication: SHA-256 Hash check against processed_files registry                             |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                               FRONTIER ENTITY & CAUSAL CLASSIFIER (LLM)                            |
|  - Identifies Entity Level: Specific Company (ISIN/Ticker), Sub-Industry, Sector, or Macro Theme   |
|  - Extracts Causal Edges: Sourcing dependencies, Capex plans, Margin trends, Regulatory shifts     |
|  - Categorizes Document: 'BROKERAGE_NOTE', 'INDUSTRY_REPORT', 'POLICY_ANALYSIS', 'CHANNEL_CHECK'   |
+-------------------------------------------------+--------------------------------------------------+
                                                  |
                                                  ▼
+----------------------------------------------------------------------------------------------------+
|                                 MULTI-STORE DATABASE & GRAPH ENRICHMENT                            |
|  - Injects distilled parameters into `company_distilled_parameters`                                |
|  - Creates/updates nodes and causal relationships in `graph_nodes` & `graph_causal_edges`          |
|  - Chunks and embeds text into `LanceDB` vector store with BGE-M3                                  |
|  - Indexes full text into SQLite `intelligence_fts`                                                |
|  - Moves processed file to `./data/processed/YYYY/MM/` with execution manifest log                 |
+----------------------------------------------------------------------------------------------------+
```

### Supported Drop-in File Types:
- `.pdf`: Multi-page institutional brokerage notes, annual report excerpts, sector whitepapers.
- `.txt` / `.md`: Copy-pasted articles, Substacks, forum analyses, management interview notes.
- `.png` / `.jpg` / `.webp`: Screenshots of research tables, sector supply-demand curves, brokerage charts (transcribed via GPU RapidOCR).

### Structured Ingestion Manifest:
Every processed file is logged in SQLite table `inbox_ingestion_manifest` with extracted tags, confidence score, detected tickers, and target graph node associations.


