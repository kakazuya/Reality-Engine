# VOCAB_PASS1 — measured vocabulary pass over the pilot's extracted phrases

Status: v4.1 decision 2, first measured pass (30 Oct 2026). Read-only on every store.
Program: `python tasks/arch_v4/vocab_pass1.py` (deterministic; `--json` prints the same
numbers as JSON). This is the number the label layer is sized from; it is a pass, not the
final vocabulary.

## 1. What was measured

The 60-company pilot universe (`tasks/pilot60/UNIVERSE.csv`, 60 ISINs) over the three
extractions that already run:

| source | field | distinct phrases | occurrences |
|---|---|---:|---:|
| concall | `concall_facts.cc_items.metric` | 16,039 | 21,606 |
| annual report | `ar_facts.ar_facts.category` | 20,005 | 1,021,844 |
| deck | `deck_figures.facts.metric` (via `pages.sha256`, 1,254 pilot deck hashes) | 113,972 | 772,131 |
| **surface layer** | union, verbatim | **148,652** | **1,691,352** |

The **surface layer is the measured size of "keep every phrase verbatim"**: 148,652
distinct strings for 60 companies. Nothing here is thrown away.

Normalisation used (declared, in the program, so the measurement is reproducible): lowercase,
`&`→and, `_`/`-`/`/`→space, 32-phrase alias map (`profit after tax`→`pat`,
`related party`→`rpt`, `cash flow`→`cash_flow`, `joint venture`→`jv`, …), plural
singularisation, and stripping of 140 entity tokens (the pilot companies' own name/symbol
words), geography and period words (`fy`, `q1`, `india`, months, …). Months/periods and
entity names are dims on the claim, not topics.

## 2. Label layer: how many topics the phrases need

Two independent methods, same phrase set:

| method | result |
|---|---|
| **A. greedy set cover over a declared 153-topic vocabulary** (the registry's own §A.6 method; candidates = 8 level-1 families + 145 level-2 head topics) | **137 topics used**, covering **64.81%** of occurrences (50.34% of distinct phrases) |
| **B. lexical clustering** (token-set Jaccard 0.6, greedy representative) | 49,904 clusters; **11,467 clusters needed for 95%** |

Coverage curve for method A (topics chosen → % of occurrences covered):

| topics | 20 | 40 | 60 | 80 | 100 | 120 | 137 |
|---|---:|---:|---:|---:|---:|---:|---:|
| covered | 45.3% | 58.3% | 62.4% | 64.1% | 64.6% | 64.8% | **64.8%** |

Per source, share of occurrences containing at least one declared topic: concall **68.6%**,
annual report **68.7%**, deck **62.7%**.

**The finding, stated plainly:** a topic vocabulary of 60–80 labels is a good *operating*
size — 60 declared topics already cover 62.4% of occurrences, 80 cover 64.1%, and the
marginal topic after ~120 adds almost nothing. But **token matching saturates at ~65%**:
the remaining 35% of occurrences are deck line labels and AR section phrases
(`Asepto total capacity target`, `↑ 16% on account of higher shipments`, `signal`,
`market_data`) whose words are not a topic. So:

- the label layer **cannot be mined lexically** (method B needs 11.5 k clusters), and
- **the 95% target applies to the head of surfaces, not to raw occurrences**: 64,948
  surfaces (43.7% of distinct phrases) carry 95% of occurrences. That head is the mapping
  workload; the other 83,704 surfaces (5% of occurrences) are `other:<raw>` by design.
- reaching 95% of *occurrences* with 60–80 labels needs a **semantic** mapper over the
  64,948 head surfaces (the local embedding index / a reader), then the hand check. It is a
  build job, not a vocabulary-size choice. **Open for Shivam:** restate the gate as
  "≥95% of occurrences labelled *or* explicitly `other`" (measured: 100% by construction,
  since every surface gets a label or an `other:<raw>` id) versus "≥95% labelled with a
  declared topic" (measured ceiling with token matching: 64.8%).

## 3. Twenty sample mappings for the hand check

Stratified sample: 10 most frequent mapped surfaces, 4 mid-frequency mapped, 6 from the
unmatched tail. Verdicts are the hand check (✗ = the label loses the claim's meaning).

| # | surface (verbatim) | mapped topic | family | occurrences | hand check |
|---:|---|---|---|---:|---|
| 1 | subsidiary | subsidiary | segments_business | 23,618 | ✓ |
| 2 | subsidiaries | subsidiary | segments_business | 22,978 | ✓ (plural variant of the same surface) |
| 3 | shareholding | shareholding | ownership_market | 18,917 | ✓ |
| 4 | remuneration | remuneration | people_governance | 17,537 | ✓ |
| 5 | related_party_transaction | rpt | people_governance | 15,057 | ✓ |
| 6 | csr | csr | people_governance | 14,732 | ✓ |
| 7 | related_party | rpt | people_governance | 14,603 | ✓ |
| 8 | employee_benefits | employee | people_governance | 14,054 | ~ parent only; the L2 topic must be `employee_benefits` |
| 9 | governance | governance | people_governance | 13,365 | ✓ |
| 10 | EBITDA | ebitda | financial_performance | 12,890 | ✓ |
| 11 | Apollo Structural Heavy Sales Mix Q3FY24 | revenue | financial_performance | 2 | ✓ (sales mix = revenue mix; brand tokens stay in the surface) |
| 12 | Apollo Structural Heavy Sales Mix Q4FY24 | revenue | financial_performance | 2 | ✓ |
| 13 | Apollo Structural Light Capacity | capacity | operations_other | 2 | ✓ |
| 14 | Apollo Structural Light EBITDA/Ton Q2FY24 | ebitda | financial_performance | 2 | ✓ (the `/Ton` unit is a facet, not a label) |
| 15 | signal | *other* | operations_other | 39,143 | ✓ correctly `other` (AR extractor bucket, not a topic) |
| 16 | market_data | *other* | operations_other | 4,156 | ✓ correctly `other` |
| 17 | ratio | *other* | operations_other | 4,118 | ✓ correctly `other` (needs the named ratio) |
| 18 | leases | *other* | operations_other | 3,603 | ✗ should map to `lease` |
| 19 | financials | *other* | operations_other | 3,444 | ✗ should map to `financials` (statement family) |
| 20 | joint_venture | *other* | operations_other | 3,162 | ✗ should map to `jv` (alias gap: `joint venture`→`jv`) |

Hand-check arithmetic: **13 of 14 produced mappings are exactly right (92.9%)**, one is
parent-level only; **3 of 6 `other` calls are wrong** and each is one declared row
(`lease`, `financials`, `joint venture`→`jv`). Every fix is mechanical, which is the point:
the check is cheap and it found the gaps in one pass.

## 4. Pipeline, tables and the release check (as specified)

Build (read-only on sources):

1. **Surface ingest** — every extracted phrase is inserted verbatim, with its source
   document: `(surface, source_kind, doc_id, isin, page_or_piece, known_at)`.
2. **Normalise + map** — the declared alias map, then the semantic mapper over the head
   surfaces; unresolved → `other:<surface>`.
3. **Cluster the tail** — `other` surfaces are clustered by the same token-Jaccard pass;
   a cluster with ≥20 occurrences, ≥3 companies and ≥2 doc types queues for promotion.
4. **Promote** — promotion is one hand-edited row (topic id, parent family, definition,
   registry atom ids), logged with the date and the evidence; the row count of the label
   layer grows only by promotion or by a new measured pass.

Tables: `vocab.surface(surface_id, surface_verbatim, norm_key, source_kind, doc_id, isin,
page_ref, known_at, occurrences)`, `vocab.label(label_id, parent_id, level, label,
definition, registry_atoms, created_at, promoted_from)`, `vocab.map(surface_id, label_id,
method, confidence, reviewed_by, reviewed_at)`, `vocab.other_cluster(cluster_id, tokens,
n, n_companies, n_doctypes, first_seen, status)`. Labels share ids with the registry atoms
(`label.registry_atoms`), so a claim joins to the number it is about.

Release check (runnable, no model):

- **coverage**: 100% of surfaces have a `map` row (a label or `other:<raw>`); share of
  occurrences carrying a declared label is reported, never asserted to be 95%.
- **precision**: a stratified random sample of 100 mappings must be ≥95% exact (this pass
  produced 92.9% on its 20-sample and found 3 mechanical fixes → the gate works).
- **head coverage**: the 64,948 surfaces carrying 95% of occurrences are each mapped; new
  surfaces entering the head (`occurrences ≥ 20`) queue for review instead of staying
  `other`.
- **growth**: the label layer grows only by promotion; the surface layer grows without
  bound. A failed case whose phrase is already a surface is a *mapping* bug (one row), not
  a vocabulary gap.

## 5. What this changes in the v4 design

- §A.5's 2,242-row lexicon stays the *query* lexicon (bank wording → atoms). The
  **document** lexicon is this surface layer (148,652 rows for 60 companies) and its label
  layer is the 8 × L2 topic set above — two different things, two different tables.
- The `topic` dim in the registry takes label ids from `vocab.label`, not free text.
- §H gets a WP for the semantic mapping pass and the release check; VOCAB_PASS2 (after the
  mapper) re-measures the same numbers, and that is the number the 95% gate uses.
