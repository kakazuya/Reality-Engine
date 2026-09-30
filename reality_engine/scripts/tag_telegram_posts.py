"""Tag Telegram posts with companies using screener.in/company/<slug> links found in the message text or buttons.
Deterministic (no guessing): slug may be an NSE symbol or a BSE code; both resolve through master_companies.
Writes telegram_post_tags(post_id, symbol, isin, method, position) and fills telegram_posts.detected_symbols_json
(only if currently empty) + intelligence_fts.symbol for the matching 'tg:<post_id>' rows.
    python reality_engine/scripts/tag_telegram_posts.py [--dry-run]"""
import json, re, sqlite3, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
c = sqlite3.connect(ROOT / "reality_engine/data/equity_intelligence.db", timeout=600)
dry = "--dry-run" in sys.argv
by_sym = {}; by_bse = {}
for sym, isin, bse in c.execute("select nse_symbol, isin, bse_code from master_companies"):  # include is_active=0 rows: master flags some live names (e.g. HFCL) inactive
    if sym: by_sym[sym.upper()] = (sym, isin)
    if bse: by_bse[str(bse)] = (sym, isin)
def resolve(slug):
    s = re.sub(r"%26", "&", slug).upper()
    return by_bse.get(s) if s.isdigit() else by_sym.get(s) or by_sym.get(s.replace("-", "")) 
SC = re.compile(r"screener\.in/company/([A-Za-z0-9&%_-]+)", re.I)
c.execute("create table if not exists telegram_post_tags(post_id text, symbol text, isin text, method text, position int, primary key(post_id, symbol))")
tags, unresolved, posts = [], [], 0
for pid, text, bl in c.execute("select id, raw_message_text, button_links_json from telegram_posts where channel_id='-1002413883243'"):
    hay = (text or "")
    try:
        j = json.loads(bl or "{}"); hay += " " + " ".join((j.get("urls") or []) + [b.get("url") or "" for b in (j.get("buttons") or [])])
    except Exception: pass
    seen = []
    for m in SC.finditer(hay):
        slug = m.group(1)
        r = resolve(slug)
        if r and r[0] not in [s for s, _ in seen]: seen.append(r)
        elif not r: unresolved.append(slug)
    if seen:
        posts += 1
        for i, (s, isin) in enumerate(seen): tags.append((pid, s, isin, "screener_link", i))
print(f"posts tagged: {posts}, tags: {len(tags)}, unresolved slugs: {len(unresolved)} e.g. {sorted(set(unresolved))[:12]}")
if dry: sys.exit(0)
with c:
    c.executemany("insert or replace into telegram_post_tags values (?,?,?,?,?)", tags)
    first = {}
    for pid, s, isin, _, pos in tags: first.setdefault(pid, []).append(s)
    c.executemany("update telegram_posts set detected_symbols_json=? where id=? and (detected_symbols_json is null or detected_symbols_json in ('[]',''))",
                  [(json.dumps(v), pid) for pid, v in first.items()])
prim = {f"tg:{pid}": next((s, i) for p, s, i, _, pos in tags if p == pid and pos == 0) for pid in {t[0] for t in tags}}
upd = [(s, i, rowid) for rowid, cid in c.execute("select rowid, chunk_id from intelligence_fts where source_type like 'TG_%'") if cid in prim for s, i in [prim[cid]]]
with c: c.executemany("update intelligence_fts set symbol=?, isin=? where rowid=?", upd)
print("fts rows updated:", len(upd))
