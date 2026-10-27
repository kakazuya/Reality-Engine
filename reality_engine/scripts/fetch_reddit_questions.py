"""Fetch Indian-market subreddit posts from the Arctic Shift Reddit archive (public, no auth).

Raw JSONL goes to D:/RealityEngine/raw/reddit/<subreddit>.jsonl. Used only as a reference for how people
phrase stock/policy questions; post text is never committed to git.

    python -m reality_engine.scripts.fetch_reddit_questions --since 2024-04-01 --min-score 3
"""
import argparse
import datetime as dt
import json
import os
import time
import urllib.parse
import urllib.request

API = "https://arctic-shift.photon-reddit.com/api/posts/search"
OUT = r"D:\RealityEngine\raw\reddit"
SUBS = [
    "IndianStockMarket", "IndiaInvestments", "DalalStreetTalks", "StockMarketIndia", "IndianStreetBets",
    "NSEbets", "mutualfunds", "IndianEconomy", "personalfinanceindia", "FIREIndia", "IndiaBusiness",
    "indianstocks", "ShareMarketIndia", "IndiaTax", "IPOIndia",
]
FIELDS = "id,title,selftext,created_utc,score,num_comments,link_flair_text,subreddit"


def get(params):
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "reality-engine-research/0.1"})
    for attempt in range(4):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r).get("data") or []
        except Exception as e:  # noqa: BLE001 - retry transient API errors
            if attempt == 3:
                print("  give up:", e)
                return None
            time.sleep(5 * (attempt + 1))


def fetch_sub(sub, since, min_score):
    path = os.path.join(OUT, f"{sub}.jsonl")
    seen, after = set(), int(since.timestamp())
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                p = json.loads(line)
                seen.add(p["id"])
                after = max(after, int(p["created_utc"]))
    n = 0
    with open(path, "a", encoding="utf-8") as f:
        while True:
            rows = get({"subreddit": sub, "after": after, "sort": "asc", "limit": 100, "fields": FIELDS})
            time.sleep(1.0)
            if not rows:
                break
            for p in rows:
                if p["id"] not in seen and (p.get("score") or 0) >= min_score:
                    f.write(json.dumps(p, ensure_ascii=False) + "\n")
                    seen.add(p["id"])
                    n += 1
            last = int(rows[-1]["created_utc"])
            if last <= after:
                break
            after = last
    print(f"{sub}: +{n} posts (total {len(seen)})", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="2024-04-01")
    ap.add_argument("--min-score", type=int, default=3)
    ap.add_argument("--subs", default=",".join(SUBS))
    a = ap.parse_args()
    os.makedirs(OUT, exist_ok=True)
    since = dt.datetime.fromisoformat(a.since).replace(tzinfo=dt.timezone.utc)
    for sub in a.subs.split(","):
        fetch_sub(sub.strip(), since, a.min_score)


if __name__ == "__main__":
    main()
