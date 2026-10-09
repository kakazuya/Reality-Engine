"""Shared constants for the price-side information-diffusion study (read-only on all databases)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)
PRICES = ROOT / "reality_engine/data/parquet/daily_price_delivery.parquet"
FEED = ROOT / "analysis/bse_announcements.db"
LIVE = ROOT / "reality_engine/data/equity_intelligence.db"

# Event window in sessions relative to t0 (first session whose close-to-close return can contain the news).
TAU = list(range(-5, 21))            # -5 .. +20
EST_LO, EST_HI = 250, 31             # estimation window = [t0-250, t0-31]
MIN_EST_OBS = 150
LIQ_MIN_TURNOVER_LACS = 50.0         # trailing-60d median turnover floor (INR lakh)
OPEN_MIN, CLOSE_MIN = 9 * 60 + 15, 15 * 60 + 30   # NSE continuous session, IST

# Material families (a-priori list, NOT chosen from outcomes): another one of these near t0 contaminates a stratum.
MATERIAL = {
    "Financial Results", "Outcome of Board Meeting", "Award of Order / Receipt of Order", "Acquisition",
    "Credit Rating", "Press Release / Media Release", "Earnings Call Transcript", "Analyst / Investor Meet",
    "Investor Presentation", "Change in Management", "Resignation of Director",
    "Resignation of Chief Financial Officer (CFO)", "Dividend", "Open Offer", "Scheme of Arrangement",
    "Memorandum of Understanding /Agreements", "Raising of Funds", "Allotment of Equity Shares",
    "Integrated Filing (Financial)", "Clarification", "Daily Buy Back of equity shares", "Board Meeting",
}
ISO_PRE, ISO_POST = 2, 10           # isolation: no other material event-day in [t0-2, t0+10]
