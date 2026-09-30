"""Tag YouTube/Telegram video chunks with company symbols (title-guided + exact-name matching).

Precision over recall: a chunk gets a symbol only if the company's distinctive name token really
appears in that chunk's text (fuzzy, to survive Hinglish spelling), and the company is either named
in the video title or matched by a multi-word legal name. Everything is stored in chunk_symbol_tags
(all matches, with score+method); document_chunks.symbol/isin get the top match and the FTS symbol
column is updated so `symbol:XYZ` searches work.

  python reality_engine/scripts/tag_video_chunks.py --dry-run [--limit 3]
  python reality_engine/scripts/tag_video_chunks.py
"""
from __future__ import annotations

import argparse
import csv
import difflib
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "reality_engine/data/equity_intelligence.db"
SUFFIX = {"limited", "ltd", "pvt", "private", "co", "company", "corporation", "corp", "inc", "the", "of", "and"}
GENERIC = {"india", "indian", "industries", "industry", "bharat", "global", "international", "enterprises", "group",
           "holdings", "services", "technologies", "technology", "tech", "systems", "financial", "finance", "capital",
           "power", "energy", "engineering", "infra", "infrastructure", "projects", "products", "solutions", "new", "first"}
EQ = re.compile(r"INE[0-9A-Z]{4}01[0-9A-Z]{3}")


def norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]+", " ", (s or "").lower().replace("&", " and "))).strip()


def load_master(conn):
    comp = {}
    for sym, isin, name in conn.execute("select nse_symbol, isin, company_name from master_companies where is_active=1"):
        if not sym or not EQ.fullmatch(isin or ""):
            continue
        toks = [t for t in norm(name).split() if t not in SUFFIX]
        comp[sym] = {"isin": isin, "toks": toks, "name": " ".join(toks),
                     "distinct": [t for t in toks if t not in GENERIC and len(t) >= 4 and not t.isdigit()]}
    return comp


def title_candidates(title: str, comp, token_index, ticker_index):
    """Match title fragments to companies by two-way token coverage -> {symbol: score}.

    A company matches a fragment when >=75% of the fragment's content tokens appear (fuzzily) in the
    company's name AND >=50% of the company's distinctive tokens appear in the fragment. This keeps
    'Frontier Springs' away from 'Frontier Capital' and 'Steel Strip Wheels' away from SAIL.
    """
    out = {}
    parts = [p for p in re.split(r"[|,/:;]| & | and | vs | - | l ", title or "") if len(norm(p)) >= 3]
    for p in parts:
        q = norm(p)
        ftoks = [t for t in q.split() if t not in SUFFIX and len(t) >= 3 and not t.isdigit()]
        content = [t for t in ftoks if t not in GENERIC] or ftoks
        if not content:
            continue
        if q.replace(" ", "") in ticker_index:
            for sym in ticker_index[q.replace(" ", "")]:
                out[sym] = max(out.get(sym, 0), 0.95)
        pool = set()
        for t in content:
            near = [t] if t in token_index else difflib.get_close_matches(t, token_index, n=3, cutoff=0.86)
            for nt in near:
                pool.update(token_index[nt])
        found = {}
        for sym in pool:
            c = comp[sym]
            ctoks = set(c["toks"])
            def has(t):
                return t in ctoks or bool(difflib.get_close_matches(t, ctoks, n=1, cutoff=0.86))
            fcov = sum(has(t) for t in content) / len(content)
            dist = c["distinct"] or c["toks"]
            dcov = sum(any(t == d or difflib.SequenceMatcher(None, t, d).ratio() >= 0.86 for t in ftoks) for d in dist) / max(len(dist), 1)
            if fcov >= 0.75 and dcov >= 0.5:
                found[sym] = round(0.5 * fcov + 0.5 * dcov, 3)
        if 0 < len(found) <= 3:          # a fragment that fits many companies is too ambiguous to trust
            for sym, sc in found.items():
                out[sym] = max(out.get(sym, 0), sc)
    return out


def chunk_hits(text_norm: str, words: set, sym: str, c) -> float:
    """Score how strongly this chunk mentions company `sym` (0 = not at all)."""
    if c["name"] and len(c["toks"]) >= 2 and f" {c['name']} " in f" {text_norm} ":
        return 1.0
    for tok in c["distinct"][:2]:
        if tok in words:
            return 0.9
        if len(tok) >= 6 and difflib.get_close_matches(tok, words, n=1, cutoff=0.86):
            return 0.75
    return 0.0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    conn = sqlite3.connect(DB, timeout=600)
    comp = load_master(conn)
    token_index, ticker_index = defaultdict(list), defaultdict(list)
    for sym, c in comp.items():
        ticker_index[re.sub(r"[^a-z0-9]", "", sym.lower())].append(sym)
        for t in set(c["toks"]):
            token_index[t].append(sym)
    docs = conn.execute("select doc_id, title, source_url from raw_documents where sha256_hash like 'yt:%' order by doc_id").fetchall()
    if a.limit:
        docs = docs[:a.limit]
    conn.execute("create table if not exists chunk_symbol_tags(chunk_id integer, symbol text, isin text, score real, method text,"
                 " primary key(chunk_id, symbol))")
    tags, primary = [], {}
    for doc_id, title, url in docs:
        cands = title_candidates(title, comp, token_index, ticker_index)
        chunks = conn.execute("select chunk_id, content from document_chunks where doc_id=? and chunk_index<100000 order by chunk_index", (doc_id,)).fetchall()
        summary = Counter()
        for cid, content in chunks:
            tn = norm(content.split("\n", 1)[-1]); words = set(tn.split())
            scores = {}
            for sym in cands:
                s = chunk_hits(tn, words, sym, comp[sym])
                if s:
                    scores[sym] = (s, "title+text")
            if not scores and len(chunks):
                # exact multi-word legal-name mention without a title hint
                for sym, c in comp.items():
                    if len(c["toks"]) >= 2 and c["name"] and f" {c['name']} " in f" {tn} " and len(c["name"]) >= 9:
                        scores[sym] = (0.8, "name_exact")
            for sym, (s, m) in scores.items():
                tags.append((cid, sym, comp[sym]["isin"], s, m))
                summary[sym] += 1
            if scores:
                top = max(scores.items(), key=lambda kv: kv[1][0])[0]
                primary[cid] = (top, comp[top]["isin"])
        print(f"doc {doc_id} | {(title or '')[:70]} | title-cands={sorted(cands)} | tagged chunks per symbol={dict(summary)} of {len(chunks)}")
    print(f"tags={len(tags)} primary-tagged chunks={len(primary)}")
    if a.dry_run:
        return 0
    with conn:
        conn.executemany("insert or replace into chunk_symbol_tags values (?,?,?,?,?)", tags)
        conn.executemany("update document_chunks set symbol=?, isin=? where chunk_id=?", [(s, i, cid) for cid, (s, i) in primary.items()])
    # FTS symbol column: map chunk_id -> rowid once (source_type is UNINDEXED, so this is one scan)
    ids = set(str(c) for c in primary)
    upd = []
    for rowid, cid in conn.execute("select rowid, chunk_id from intelligence_fts where source_type like 'YouTube%'"):
        if cid in ids:
            s, i = primary[int(cid)]
            upd.append((s, i, rowid))
    with conn:
        conn.executemany("update intelligence_fts set symbol=?, isin=? where rowid=?", upd)
    print(f"fts rows updated: {len(upd)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
