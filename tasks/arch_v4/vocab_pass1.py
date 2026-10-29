"""VOCAB_PASS1 — first measured pass over the pilot's existing extracted phrases.

v4.1 decision 2: the extraction vocabulary has an exhaustive *surface* layer (every
phrase kept verbatim, unlimited) and a small *label* layer (~60-80 topics, two levels).
This program measures what the held phrases actually need:

    python tasks/arch_v4/vocab_pass1.py            # print the measurement
    python tasks/arch_v4/vocab_pass1.py --json     # machine-readable summary

Phrases come from the three extractions that already run, filtered to the 60-company
pilot universe (tasks/pilot60/UNIVERSE.csv): ``concall_facts.cc_items.metric``,
``deck_figures.facts.metric`` and ``ar_facts.category``.  Read-only, bounded, no model,
no install.

Two measurements, same phrase set:
  (A) greedy set cover over candidate topic tokens -> the smallest topic set covering
      95% of phrase occurrences (the decision's own rule, the registry's §A.6 method);
  (B) lexical clustering (token-set Jaccard) -> how many clusters 95% would need when
      no declared topic vocabulary is allowed.  (B) is reported because it shows which
      sources are phrase lists and which are already labels.

Output is a single report; nothing is written.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
DATA = Path(os.environ.get("REALITY_DATA_ROOT") or (ROOT / "reality_engine" / "data"))
UNIVERSE = ROOT / "tasks" / "pilot60" / "UNIVERSE.csv"

# --- declared alias map: multi-word/abbreviation forms that are the SAME topic.
PHRASE_ALIASES = [
    ("profit after tax", "pat"), ("profit before tax", "pbt"),
    ("net profit", "pat"), ("profit for the period", "pat"),
    ("revenue from operations", "revenue"), ("total revenue", "revenue"),
    ("net sales", "revenue"), ("net revenue", "revenue"), ("sales", "revenue"),
    ("operating profit", "ebitda"), ("operating margin", "ebitda_margin"),
    ("order book", "order_book"), ("order inflow", "order_intake"),
    ("order intake", "order_intake"), ("order value", "order_value"),
    ("net debt", "net_debt"), ("working capital", "working_capital"),
    ("cash flow from operations", "cfo"), ("free cash flow", "fcf"),
    ("earnings per share", "eps"), ("book value", "book_value"),
    ("total debt", "debt"), ("gross npa", "gross_npa"), ("net npa", "net_npa"),
    ("capacity utilisation", "capacity_utilisation"), ("capacity utilization", "capacity_utilisation"),
    ("market share", "market_share"), ("unit volume", "volume"),
    ("research and development", "rnd"), ("related party transaction", "rpt"),
    ("related party transactions", "rpt"), ("related party", "rpt"),
    ("cash flow", "cash_flow"), ("cash flows", "cash_flow"),
]
STOP = set("a an the of and or in for to from on by with as at is are was were be "
           "been its it this that these those versus vs per pct percent rs cr crore "
           "crores lakh lakhs million billion mn bn inr usd no not than then".split())
GEO_PERIOD = set("india indian asia asia pacific europe us usa uk america africa "
                 "middle east global domestic overseas international north south east west "
                 "fy fys yoy qoq year years quarter quarters h1 h2 q1 q2 q3 q4 "
                 "january february march april may june july august september october november december "
                 "projected projection estimate estimated target guidance".split())
PRE = sorted(PHRASE_ALIASES, key=lambda p: -len(p[0]))
FAMILIES = {
    "financial_performance": "revenue pat pbt ebitda ebit profit margin eps growth income loss result",
    "costs_balance_sheet": "cost expense debt borrowing cash receivable inventory payable capex cwip asset liabilit equity net_debt working_capital cfo fcf tax dividend",
    "segments_business": "segment business product category division portfolio brand customer client geography subsidiary vertic order_book",
    "demand_orders": "order_intake order_book order_value order demand volume despatch dispatch capacity_utilisation utilisation backlog pipeline market_share",
    "guidance_risk": "guidance outlook expect risk concern delay headwind tailwind vision",
    "people_governance": "board promoter management remuneration governance csr succession employee esop kpi auditor rpt",
    "ownership_market": "shareholding pledge fii dii mf public holding float price delivery rsi sma mcap",
    "policy_macro": "policy tariff gst budget rbi repo inflation monsoon rain commodity gold oil coal steel subsidy scheme pli",
}
DEFAULT_FAMILY = "operations_other"
HEADS = set(" ".join(FAMILIES.values()).split()) | {
    "ebit", "np", "npa", "nim", "interest", "depreciation", "amortisation", "amortization",
    "opex", "turnover", "arr", "collection", "debtor", "creditor", "supply", "churn",
    "subsidiary", "associate", "jv", "acquisition", "merger", "commissioning",
    "utilisation", "generation", "realisation", "asp", "spread", "yield",
    "advance", "deposit", "loan", "provision", "slippage", "restructuring", "impairment",
    "profit", "income", "loss", "asset", "liability", "equity", "capital", "investment",
    "material", "shipment", "packaging", "commissioning", "demand", "supply", "competition",
    "price", "subsidy", "employee", "rnd", "production", "sales", "receipt", "payment",
    "capacity", "expansion", "order", "realisation", "utilisation", "backlog", "pipeline",
    "cash_flow", "market_share", "order_intake", "order_book", "net_debt", "working_capital",
}
# declared non-topics: bucket words that carry no claim on their own
NON_TOPIC = {"total", "net", "other", "value", "area", "financial", "gross", "new",
             "change", "increase", "decrease", "growth", "current", "previous", "period",
             "year", "quarter", "rate", "share", "unit"}


def declared_topics() -> list[str]:
    return sorted(t for t in HEADS if t not in NON_TOPIC)


def ro(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{path.as_posix()}?mode=ro&immutable=1", uri=True, timeout=90)


def pilot_isins() -> list[str]:
    with open(UNIVERSE, encoding="utf-8") as f:
        return [r["isin"] for r in csv.DictReader(f) if r.get("isin")]


def entity_tokens(isins: list[str]) -> frozenset[str]:
    """Company-name and symbol tokens: a phrase already attached to the entity."""
    out: set[str] = set()
    try:
        p = DATA / "equity_intelligence.db"
        c = ro(p)
        q = ",".join("?" * len(isins))
        for row in c.execute(f"SELECT company_name, nse_symbol FROM master_companies WHERE isin IN ({q})", isins):
            for v in row:
                if v:
                    out.update(re.findall(r"[a-z][a-z0-9]*", str(v).lower()))
        c.close()
    except Exception as exc:                       # never fail the measurement on this
        print("entity-token read skipped:", exc)
    out -= {"ltd", "limited", "company", "co", "industries", "india", "indian", "and", "of", "the"}
    return frozenset(out)


def singular(t: str) -> str:
    if len(t) > 4 and t.endswith("ies"):
        return t[:-3] + "y"
    if len(t) > 3 and t.endswith("s") and not t.endswith("ss"):
        return t[:-1]
    return t


def words_of(phrase: str, ents: frozenset[str]) -> frozenset[str]:
    s = " " + phrase.lower() + " "
    s = s.replace("&", " and ").replace("%", " pct ").replace("/", " ").replace("_", " ").replace("-", " ")
    for long, short in PRE:
        s = s.replace(" " + long + " ", " " + short + " ")
    out = []
    for t in re.findall(r"[a-z][a-z0-9]*", s):
        if t in STOP or t in GEO_PERIOD or t in ents or t.isdigit():
            continue
        out.append(singular(t))
    return frozenset(out)


def family_of(toks: frozenset[str]) -> str:
    text = " " + " ".join(sorted(toks)) + " "
    best, score = DEFAULT_FAMILY, 0
    for fam, words in FAMILIES.items():
        n = sum(1 for w in words.split() if " " + w + " " in text)
        if n > score:
            best, score = fam, n
    return best


def collect(isins: list[str]) -> tuple[Counter, dict[str, Counter]]:
    q = ",".join("?" * len(isins))
    per_source: dict[str, Counter] = {}

    cc = ro(DATA / "concall_facts.db")
    per_source["concall"] = Counter({m: n for m, n in cc.execute(
        f"SELECT metric, count(*) FROM cc_items WHERE isin IN ({q}) "
        f"AND metric IS NOT NULL GROUP BY 1", isins)})
    cc.close()

    ar = ro(DATA / "ar_facts.db")
    per_source["annual_report"] = Counter({m: n for m, n in ar.execute(
        f"SELECT category, count(*) FROM ar_facts WHERE isin IN ({q}) "
        f"AND category IS NOT NULL GROUP BY 1", isins)})
    ar.close()

    df = ro(DATA / "deck_figures.db")
    hashes = [r[0] for r in df.execute(f"SELECT DISTINCT sha256 FROM pages WHERE isin IN ({q})", isins)]
    deck: Counter = Counter()
    for i in range(0, len(hashes), 400):
        chunk = hashes[i:i + 400]
        hq = ",".join("?" * len(chunk))
        for m, n in df.execute(f"SELECT metric, count(*) FROM facts WHERE sha256 IN ({hq}) "
                               f"AND metric IS NOT NULL GROUP BY 1", chunk):
            deck[m] += n
    per_source["deck"] = deck
    df.close()
    return Counter({m: n for c in per_source.values() for m, n in c.items()}), per_source


def set_cover(phrase_n: dict[int, int], phrase_toks: dict[int, frozenset[str]],
              candidates: set[str], target: float = 0.95) -> dict:
    """Greedy: pick the declared topic covering the most uncovered occurrences."""
    total = sum(phrase_n.values())
    covered: set[int] = set()
    chosen: list[tuple[str, int]] = []
    while sum(phrase_n[i] for i in covered) < target * total:
        gain: Counter = Counter()
        for i, n in phrase_n.items():
            if i in covered:
                continue
            for t in phrase_toks[i]:
                if t in candidates:
                    gain[t] += n
        gain = {t: g for t, g in gain.items() if g and t not in {c for c, _ in chosen}}
        if not gain:
            break
        token, add = max(gain.items(), key=lambda kv: (kv[1], kv[0]))
        chosen.append((token, add))
        covered.update(i for i, ts in phrase_toks.items() if token in ts)
    return {"chosen": chosen, "covered": sum(phrase_n[i] for i in covered),
            "total": total}


def lexical_clusters(norm_counts: Counter, jacc: float) -> int:
    order = sorted(norm_counts.items(), key=lambda kv: (-kv[1], " ".join(sorted(kv[0]))))
    idx: dict[str, list[int]] = defaultdict(list)
    reps: list[frozenset[str]] = []
    for tset, _n in order:
        cand: set[int] = set()
        for t in tset:
            cand.update(idx[t][-300:])
        best, best_j = -1, 0.0
        for ci in cand:
            rep = reps[ci]
            inter, union = len(tset & rep), len(tset | rep)
            j = inter / union if union else 0.0
            if j >= jacc and j > best_j:
                best, best_j = ci, j
        if best < 0:
            reps.append(tset)
            best = len(reps) - 1
            for t in tset:
                idx[t].append(best)
    return len(reps)


def cluster_k95(norm_counts: Counter, jacc: float) -> tuple[int, int]:
    order = sorted(norm_counts.items(), key=lambda kv: (-kv[1], " ".join(sorted(kv[0]))))
    total = sum(norm_counts.values())
    idx: dict[str, list[int]] = defaultdict(list)
    reps: list[frozenset[str]] = []
    sizes: list[int] = []
    for tset, n in order:
        cand: set[int] = set()
        for t in tset:
            cand.update(idx[t][-300:])
        best, best_j = -1, 0.0
        for ci in cand:
            rep = reps[ci]
            inter, union = len(tset & rep), len(tset | rep)
            j = inter / union if union else 0.0
            if j >= jacc and j > best_j:
                best, best_j = ci, j
        if best < 0:
            reps.append(tset)
            sizes.append(0)
            best = len(reps) - 1
            for t in tset:
                idx[t].append(best)
        sizes[best] += n
    sizes.sort(reverse=True)
    cum, k = 0, None
    for i, s in enumerate(sizes, 1):
        cum += s
        if k is None and cum >= 0.95 * total:
            k = i
    return len(sizes), k or 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--jacc", type=float, default=0.6)
    args = ap.parse_args(argv)

    isins = pilot_isins()
    ents = entity_tokens(isins)
    by_phrase, per_source = collect(isins)

    # phrase -> token set (one row per verbatim phrase, in a stable order)
    items = [(p, n, words_of(p, ents)) for p, n in sorted(by_phrase.items())]
    items = [(p, n, ts) for p, n, ts in items if ts]
    phrase_n = {i: n for i, (_p, n, _ts) in enumerate(items)}
    phrase_toks = {i: ts for i, (_p, _n, ts) in enumerate(items)}
    total = sum(phrase_n.values())
    declared = declared_topics()

    # (A) greedy set cover over the DECLARED topic vocabulary
    cover = set_cover(phrase_n, phrase_toks, set(declared))
    # marginal value of each further topic (the curve the decision asks for)
    curve = []
    gained = 0
    for i, (t, n) in enumerate(cover["chosen"], 1):
        gained += n
        curve.append((i, t, round(100.0 * gained / total, 2)))
    at = {n: round(100.0 * sum(x for _i, _t, x in curve[:n]) / 100, 2) for n in (60, 80, len(curve))}
    # simpler: coverage after k chosen topics
    at = {}
    gained = 0
    for i, (_t, n) in enumerate(cover["chosen"], 1):
        gained += n
        if i in (20, 40, 60, 80, 100, 120):
            at[i] = round(100.0 * gained / total, 2)

    # coverage of the declared set per source
    per_source_cov = {}
    for src, ctr in per_source.items():
        src_phrases = [(p, n, words_of(p, ents)) for p, n in sorted(ctr.items())]
        src_phrases = [(p, n, ts) for p, n, ts in src_phrases if ts]
        src_total = sum(n for _p, n, _ts in src_phrases)
        hit = sum(n for _p, n, ts in src_phrases if ts & set(declared))
        per_source_cov[src] = {"occurrences": src_total,
                               "declared_topic_hit_pct": round(100.0 * hit / max(1, src_total), 2)}
    # how many declared topics are actually hit at all (the rest are dead weight)
    hit_topics = {t for _p, _n, ts in items for t in ts if t in set(declared)}

    # (B) lexical clustering, no declared vocabulary
    norm_counts: Counter = Counter()
    for _p, n, ts in items:
        norm_counts[ts] += n
    n_clusters, k95 = cluster_k95(norm_counts, args.jacc)

    # phrase concentration: how many verbatim surfaces carry 95% of the occurrences
    by_freq = sorted(by_phrase.values(), reverse=True)
    cum, n95 = 0, None
    for i, n in enumerate(by_freq, 1):
        cum += n
        if n95 is None and cum >= 0.95 * sum(by_freq):
            n95 = i
    # 20 sample mappings for the hand check: 14 mapped, 6 unmatched tail
    # most specific declared topic in the phrase wins (a label layer picks the head,
    # not the first broad word it sees)
    gain_of = {t: n for t, n in cover["chosen"]}

    def pick_topic(ts: frozenset[str]) -> str | None:
        hits = [t for t in ts if t in set(declared)]
        return min(hits, key=lambda t: (gain_of.get(t, total), t)) if hits else None

    ordered = sorted(items, key=lambda it: -it[1])
    matched = [it for it in ordered if it[2] & set(declared)]
    unmatched = [it for it in ordered if not (it[2] & set(declared))]
    picks = matched[:10] + matched[len(matched) // 3:len(matched) // 3 + 4] + unmatched[:6]
    seen, samples = set(), []
    for p, n, ts in picks:
        if p in seen:
            continue
        seen.add(p)
        samples.append({"surface": p, "tokens": " ".join(sorted(ts)),
                        "topic": pick_topic(ts), "family": family_of(ts), "occurrences": n})
    samples = samples[:20]

    summary = {
        "pilot_isins": len(isins),
        "entity_tokens": len(ents),
        "phrases_verbatim": len(by_phrase),
        "phrases_used": len(items),
        "phrases_total_occurrences": total,
        "per_source": {k: {"distinct": len(v), "occurrences": sum(v.values())}
                       for k, v in per_source.items()},
        "per_source_declared_coverage": per_source_cov,
        "declared_topics": len(declared),
        "declared_topics_hit": len(hit_topics),
        "declared_topics_unused": sorted(set(declared) - hit_topics),
        "surfaces_for_95pct": n95,
        "tail_surfaces": len(by_phrase) - (n95 or 0),
        "topics_for_95pct": len(cover["chosen"]),
        "coverage_at_k": at,
        "covered_occurrences_pct": round(100.0 * cover["covered"] / total, 2),
        "covered_distinct_phrases_pct": round(100.0 * len(
            [i for i, ts in phrase_toks.items() if any(t in ts for t, _n in cover["chosen"])]
        ) / max(1, len(items)), 2),
        "other_occurrences_pct": round(100.0 * (total - cover["covered"]) / total, 2),
        "topics": [{"topic": t, "covers": n} for t, n in cover["chosen"]],
        "curve": curve,
        "lexical_clusters": n_clusters,
        "lexical_clusters_for_95pct": k95,
        "jaccard": args.jacc,
        "level1_families": len(FAMILIES) + 1,
        "samples": samples,
        "alias_map": [[a, b] for a, b in PHRASE_ALIASES],
    }
    if args.json:
        print(json.dumps(summary, indent=1, ensure_ascii=False))
        return 0

    print("pilot universe:", len(isins), "ISINs; entity tokens stripped:", len(ents))
    for k, v in summary["per_source"].items():
        print(f"  {k:<14} distinct {v['distinct']:>7}  occurrences {v['occurrences']:>9}"
              f"  declared-topic hit {per_source_cov[k]['declared_topic_hit_pct']:>5}%")
    print(f"verbatim phrases {len(by_phrase):>7}  occurrences {total:>9}")
    print(f"surfaces carrying 95% of occurrences: {n95} (tail {len(by_phrase) - (n95 or 0)} surfaces)")
    print(f"declared topic vocabulary: {len(declared)} ({len(hit_topics)} hit by at least one phrase)")
    print(f"\ntopics needed for 95% of occurrences (greedy set cover): {len(cover['chosen'])}")
    print(f"  covered {summary['covered_occurrences_pct']}% of occurrences, "
          f"{summary['covered_distinct_phrases_pct']}% of distinct phrases; "
          f"other tail {summary['other_occurrences_pct']}%")
    print("  coverage after k topics:", at)
    print("  topics 1-40:", ", ".join(t for t, _n in cover["chosen"][:40]))
    print(f"\nlexical clustering at Jaccard {args.jacc}: {n_clusters} clusters; "
          f"{k95} needed for 95% (no declared vocabulary)")
    print("\n20 sample mappings for the hand check:")
    for s in samples:
        print(f"  {s['surface'][:56]:<56} -> {str(s['topic']):<18} [{s['family']}] n={s['occurrences']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
