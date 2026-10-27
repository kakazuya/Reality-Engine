"""One live BSE header probe (outside the 200-sample fetch)."""
import json
from reality_engine.ingestion.bse_fundamentals_client import fetch_header

h = fetch_header(500002)
print(json.dumps(h, indent=1)[:1500] if h else "NO ANSWER")
