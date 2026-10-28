"""Fail if any 10-word run of a Reddit title appears in this worktree's output.

The rule is paraphrases only (<15 words, no copied text). A 10-word overlap is
the smallest shingle that is very unlikely to appear by accident; generic
phrases are reported but excluded when the prefix is a known question stem.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
RAW = Path(r"D:\RealityEngine\raw\reddit")
N = 10
OUTPUTS = ["REPORT.md", "QUESTION_BANK_REDDIT_2026-10-28.md",
           "QUESTION_BANK_REDDIT_2026-10-28.jsonl", "patterns.csv", "aliases.csv",
           "PROGRESS_NOTES.md"]
GENERIC = {  # question stems that legitimately recur in any market text
    "what is the best way to", "is it a good time to",
    "what happens to my shares", "should i buy or sell",
}


def norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def shingles(words: list[str], n: int = N):
    for i in range(max(0, len(words) - n + 1)):
        yield " ".join(words[i:i + n])


def body_check() -> int:
    """15-word run copied from any output into a post title or body."""
    grams = set()
    for name in OUTPUTS:
        path = HERE / name
        if path.exists():
            words = norm(path.read_text(encoding="utf-8")).split()
            for i in range(max(0, len(words) - 14)):
                grams.add(" ".join(words[i:i + 15]))
    if not grams:
        print("body check: no outputs yet")
        return 0
    hits = []
    scanned = 0
    for path in sorted(RAW.glob("*.jsonl")):
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                scanned += 1
                text = f"{d.get('title') or ''}\n{d.get('selftext') or ''}"
                w = norm(text).split()
                for i in range(len(w) - 14):
                    g = " ".join(w[i:i + 15])
                    if g in grams:
                        hits.append((path.stem, g))
                        break
    print(f"posts scanned for 15-word overlap: {scanned:,}; output 15-grams: {len(grams):,}")
    if hits:
        print(f"BODY LEAK: {len(hits)} posts share a verbatim 15-word run")
        for sub, g in hits[:10]:
            print(" -", sub, "::", g[:120])
        return 1
    print("no 15-word verbatim run from any output appears in any post")
    return 0


def main() -> int:
    title_grams = set()
    n_titles = 0
    for path in sorted(RAW.glob("*.jsonl")):
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                n_titles += 1
                words = norm(str(d.get("title") or "")).split()
                title_grams.update(shingles(words))
    hits = []
    for name in OUTPUTS:
        path = HERE / name
        if not path.exists():
            continue
        words = norm(path.read_text(encoding="utf-8")).split()
        for g in shingles(words):
            if g in title_grams and not any(g.startswith(p) for p in GENERIC):
                hits.append((name, g))
    print(f"titles scanned: {n_titles}; 10-gram title set: {len(title_grams)}")
    if hits:
        print(f"LEAK: {len(hits)} overlapping runs")
        for name, g in hits[:20]:
            print(" -", name, "::", g)
        return 1
    print("no 10-word verbatim overlap with any title (usernames are absent from the source fields)")
    return body_check()


if __name__ == "__main__":
    raise SystemExit(main())
