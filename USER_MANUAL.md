# Equity Intelligence & Market Reality Engine
## Complete Non-Technical User Manual & Operational Guide

---

## 1. What This System Does (In Plain English)

Think of this system as an **automated stock detective and market analyst**. 

Instead of guessing or listening to random social media tips, the system continuously reads and analyzes real-world market data for over 2,000 Indian companies listed on the NSE and BSE stock exchanges.

It answers four crucial questions before suggesting any stock:
1. **Are institutions quietly buying?** (Tracks whether big mutual funds and institutional investors are buying large delivery volumes, even during market dips).
2. **Is the company fundamentally growing?** (Checks quarterly sales growth, profit acceleration, and expanding profit margins).
3. **Is the company financially safe?** (Forensic health gate: Automatically rejects heavily indebted companies, high promoter debt pledging, or accounting red flags).
4. **How does government policy or global news affect it?** (Maps how Union Budget spending, railway capex, defence contracts, or crude oil prices flow down into company revenues).

---

## 2. Quick Start: 3 Simple Steps to Run the System

You don't need to know any programming. Just follow these 3 steps:

### Step 1: Open Your Terminal / PowerShell
- On Windows, press the **Windows Key**, type **PowerShell** or **Terminal**, and hit **Enter**.
- Make sure you are in the project folder:
```powershell
cd C:\Users\vermashi\Documents\kiloai\btask01
```

### Step 2: Initialize & Bootstrap the System (Run Once)
Run the automated bootstrap script to install dependencies, initialize directories, seed ontologies, and verify tests:
```powershell
.\bootstrap.ps1
```
*(Or simply run `python reality_engine/cli.py seed-ontologies` if dependencies are already installed)*
*What you will see:* A confirmation message saying `BOOTSTRAP COMPLETED SUCCESSFULLY.`

### Step 3: Launch the Visual Web Dashboard
To view everything in a clean web browser interface with charts and tables, run:
```powershell
python reality_engine/cli.py dashboard
```
- Open your browser (Chrome, Edge, Brave) and go to:  
  **`http://localhost:8501`**

---

## 3. Guide to the Web Dashboard (Tab by Tab)

The visual dashboard at `http://localhost:8501` is divided into 6 tabs:

```
+--------------------------------------------------------------------------------------------------+
|  [Tab 1] Market Overview   |  [Tab 2] Stock Screener   |  [Tab 3] Policy & Macro Graph           |
|  [Tab 4] Stock Dossier     |  [Tab 5] Daily Alpha      |  [Tab 6] Document Drop-in Inbox         |
+--------------------------------------------------------------------------------------------------+
```

### Tab 1: Market Overview & Panic Radar
- **Market Regime Badge**: Shows whether the overall market is in a healthy `BULLISH` mode, `ACCUMULATION` mode (institutions quietly buying), `DISTRIBUTION` (smart money selling), or `PANIC/VOLATILE`.
- **Advance/Decline Ratio**: Shows how many stocks went up vs. down across the market today.
- **Sector Performance**: Bar charts displaying which sectors (Defence, IT, Railways, Banking, Autos) are gaining or losing momentum.
- **Panic Radar**: Alerts you if the market dropped heavily ($\ge 1.5\%$), activating the bargain finder.

### Tab 2: Quantitative Stock Screener
- **The Filterable Stock Table**: Displays top-ranked stocks scored out of 100 based on technical buying flow and fundamental acceleration.
- **Interactive Controls**:
  - Filter by Index: **Nifty 200** (Top 200 liquid stocks) or **Nifty 500** (Broader universe).
  - Minimum Score Slider: Filter for stocks with high scores (e.g., Score $\ge 75$).
  - Market Cap Tier: Large Cap, Mid Cap, Small Cap.
- **Download to Excel/CSV**: Click the **Download Screener CSV** button to export the ranked list to Microsoft Excel.

### Tab 3: Causal Knowledge Graph & Policy Shocks
- **Macro Trigger Dropdown**: Select an event (e.g., `UNION_BUDGET_2026_RAIL_CAPEX`, `COMMODITY_CRUDE_OIL`, `GEOPOLITICAL_RED_SEA_ATTACKS`, or `DEFENCE_INDIGENIZATION_DAP`).
- **Hop Depth Slider**: Choose how many steps downstream to trace (1 to 4 steps).
- **What It Tells You**:
  - **Green Cards (Beneficiaries)**: Companies that directly profit from the policy or shock, along with the exact transmission mechanism (e.g., *"Budget capex $\to$ railway wagon tenders $\to$ Titagarh Rail Systems"*).
  - **Red Cards (Impaired / Victims)**: Companies whose profit margins get squeezed (e.g., *"Crude oil surge $\to$ raw monomer cost inflation $\to$ Asian Paints"*).

### Tab 4: Stock Intelligence Dossier
- **Search Any Stock**: Type any stock symbol (e.g., `HAL`, `TITAGARH`, `KAYNES`, `PIDILITIND`, `RELIANCE`).
- **What You See**:
  1. **Current Market Price & Delivery Flow**: Today's price, percentage change, and **Delivery Spike Ratio** (if $> 2.0\times$, institutions bought twice their usual volume).
  2. **Quarterly P&L Trend**: Sales, profit growth, and profit margin trajectory over the past quarters.
  3. **Forensic Safety Status**: Green **APPROVED** badge if the company passed all debt and promoter pledge checks.
  4. **Distilled Business Profile**: Operating cyclicality, key revenue drivers, input sensitivities, and order book size.
  5. **Concall Transcript Search**: Type a keyword like *"order book"*, *"capex"*, or *"margin guidance"* to instantly retrieve exact quotes spoken by management in investor conference calls.

### Tab 5: EOD Daily Alpha Reports
- **Top 5 High-Conviction Setups**: Displays the system's top 5 stock picks of the day with exact trading levels:
  - **Recommended Entry Range**: Safe price window to enter without chasing highs.
  - **Target Price**: Projected upside target (typically $+18\%$).
  - **Stop Loss**: Safety cut-off level to protect capital (typically $-6\%$).
  - **Risk-to-Reward Ratio**: Guaranteed minimum $1:2.5$ or $1:3.0$ ratio (you risk ₹1 to potentially make ₹3).
- **Catalysts & Downside Risks**: Clear bullet points explaining what will drive the stock up and what risks to watch for.
- **Synthesize Fresh Report Button**: Click to run a new analysis on demand.

### Tab 6: Local Document Drop-in Inbox
- **File Upload Area**: Drag and drop any research PDF (e.g., Broker report, Annual Report) or chart screenshot (PNG/JPG).
- **Process Inbox Button**: Click the button to automatically scan the files, extract text using Optical Character Recognition (OCR), extract price targets and tickers, and index everything into the search database.

---

## 4. Running Tasks via the Terminal (Copy & Paste Commands)

If you prefer using the terminal instead of the web dashboard, here are simple copy-paste commands:

### 1. Find Today's Top Ranked Stocks
```powershell
python reality_engine/cli.py screen --universe nifty200 --top 10
```
*What it does:* Scans the top 200 stocks, weeds out financially weak companies, and lists the Top 10 strongest stocks.

### 2. Inspect a Specific Stock's Full Report
```powershell
python reality_engine/cli.py inspect-stock HAL
python reality_engine/cli.py inspect-stock TITAGARH
python reality_engine/cli.py inspect-stock KAYNES
```
*What it does:* Prints the complete dossier for that stock (price, delivery spikes, quarterly profits, debt health, and management concall notes).

### 3. Generate and Export the Daily Top 5 Alpha Report
```powershell
python reality_engine/cli.py run-daily-alpha --universe nifty200 --top 5
```
*What it does:* Synthesizes deep investment theses for the Top 5 picks and automatically saves beautiful **JSON, Markdown, and HTML report files** on your computer.

### 4. Trace the Impact of a Government Policy or Macro Event
```powershell
python reality_engine/cli.py trace-causal-chain --node UNION_BUDGET_2026_RAIL_CAPEX --max-hops 3
```
*What it does:* Traces how Union Budget railway capex flows down step-by-step to listed companies.

### 5. Simulate a Global Crisis or Commodity Shock
```powershell
python reality_engine/cli.py simulate-macro-shock --shock "COMMODITY_CRUDE_OIL"
```
*What it does:* Tells you which companies profit and which companies suffer when crude oil prices spike.

### 6. Search Earnings Concall Transcripts
```powershell
python reality_engine/cli.py search-concall --query "order book capex expansion" --symbol KAYNES
```
*What it does:* Searches management speeches and analyst Q&A to show exact quotes regarding order books and plant expansions.

### 7. Process Any Files Dropped into the Inbox
```powershell
python reality_engine/cli.py process-inbox
```
*What it does:* Reads all PDFs and chart images you dropped into the `reality_engine/data/inbox/` folder and indexes them.

### 8. Check for Market Panic & Bargains
```powershell
python reality_engine/cli.py monitor-panic
```
*What it does:* Checks if the market crashed today and prints high-quality stocks being dumped by retail panic while institutions are soaking up supply.

---

## 5. Where Your Reports & Files Are Saved

Every time you run the system, it automatically saves reports in standard files that you can double-click and view:

| File Location | How to View It | What It Contains |
| :--- | :--- | :--- |
| `reality_engine/data/reports/YYYY-MM-DD/daily_alpha.html` | **Double-click to open in any web browser** | Visual terminal report with dark-mode tables, target cards, catalysts, and risks. |
| `reality_engine/data/reports/YYYY-MM-DD/daily_alpha.md` | Open with Notepad, VS Code, or Markdown viewer | Clean text document with formatted tables and investment theses. |
| `reality_engine/data/reports/YYYY-MM-DD/daily_alpha.json` | Open with any text editor | Raw machine-readable data for the daily report. |
| `reality_engine/data/reports/top_200_reality_checkpoint_*.csv` | **Double-click to open in Microsoft Excel** | Complete spreadsheet of all 200 stocks with scores, volumes, and metrics. |

*(Replace `YYYY-MM-DD` with the date, for example `2026-08-14`)*

---

## 6. How to Drop Research Documents into the System

You can teach the system about new research without writing any code:

1. Open your File Explorer and navigate to:
   `C:\Users\vermashi\Documents\kiloai\btask01\reality_engine\data\inbox`
2. Drop your files into the appropriate subfolder:
   - **Chart Screenshots / Photos**: Put them in `data/inbox/images/`
   - **PDF Reports / Filings**: Put them in `data/inbox/pdfs/`
3. Run this command in your terminal (or click the button in Tab 6 of the Dashboard):
   ```powershell
   python reality_engine/cli.py process-inbox
   ```
4. The system will read the text, recognize stock tickers, extract price targets, and move the processed files into `data/inbox/processed/`.

---

## 7. Troubleshooting & How to Report Issues in Layman Terms

If something doesn't work as expected, refer to this guide to diagnose the issue and explain it simply:

```
┌──────────────────────────────────────────────────────────────────────────────────────────────────┐
│ COMMON SYMPTOMS & HOW TO EXPLAIN THEM IN PLAIN ENGLISH                                           │
├───────────────────────────────┬──────────────────────────────┬───────────────────────────────────┤
│ What You See on Screen        │ What It Actually Means       │ What to Say When Reporting It     │
├───────────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ "No price delivery records    │ Today's market data is not   │ "The database doesn't have market │
│  found for date..."           │ downloaded yet for that date │  data for [Date]. Need to backfill"│
├───────────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ "Strict Solvency Gate:        │ The stock was filtered out   │ "Stock [Symbol] failed solvency   │
│  Filtered out N scrips"       │ because of debt or pledge    │  checks (pledge/debt too high)"   │
├───────────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ "ModuleNotFoundError" or      │ A required Python library    │ "Python is missing a package:     │
│ "No module named X"           │ is missing from your machine │  [Module Name]"                   │
├───────────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ Browser says "Site cannot     │ The Streamlit dashboard was  │ "The dashboard command hasn't been│
│  be reached" (localhost:8501) │ not started in the terminal  │  run yet in the terminal"         │
├───────────────────────────────┼──────────────────────────────┼───────────────────────────────────┤
│ Dashboard port already in use │ Another window has it open   │ "Port 8501 is busy, need to run on│
│                               │                              │  port 8502 or close other tab"    │
└───────────────────────────────┴──────────────────────────────┴───────────────────────────────────┘
```

### Self-Diagnostic Check
To verify that all 40 system checks and calculations are working properly, run:
```powershell
python -m unittest discover -s reality_engine/tests
```
If everything is working, you will see:
```text
Ran 40 tests in 3.0s
OK
```
If you ever see `FAILED` or an error, copy the last 5 lines of the terminal and share it in your feedback.
