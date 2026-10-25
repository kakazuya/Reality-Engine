# Learning architecture: cause and effect, embeddings on budget, LLMs fading out (2026-10-25)

Shivam's constraints:
- Find cause and effect, not correlations.
- Embedding/chunking quality matters most: use Nemotron-class models, not bge-small.
- Budget: at most $300 one-off (setup, this month), then at most $40 per month.
- Run on this PC, so that over time most work is matrix maths and the LLM does less and less.

## 1. Cause and effect: what counts as proof
A link "X causes Y" (a policy causes revenue growth, a tariff causes a margin fall, a commodity move causes a stock
move) is stored only when it passes all five tests below. Each test runs with fixed code on point-in-time data.

1. **Timing.** X was public (`known_at`) before Y moved. Y is measured as an *abnormal* move: the stock's return
   minus what market, sector and factor exposure predict. A raw return is never used.
   - The event window opens **4 trading sessions before** `known_at` (Shivam, 2026-10-25): people hear through contacts
     and take positions early.
   - Abnormal return and delivery volume over sessions −4…−1 are stored separately as `pre_event_drift`. A link whose
     move is mostly pre-event is tagged `leaked`. It still counts as cause, but the tradable edge starts later or is gone.
   - The pre-event drift also becomes its own signal: unusual delivery and abnormal returns with no public news yet.
2. **Control group.** Exposed companies are compared with matched unexposed ones (same sector and size, no exposure),
   over the same window. This is difference-in-differences: the market-wide part cancels out.
3. **Dose-response.** The effect must grow with exposure. A company with 60% of revenue in the affected segment must
   move more than one with 10%. The weights come from the point-in-time universe table, so this test is cheap. It is
   also the strongest filter against spurious correlation, because a coincidence rarely scales with exposure.
4. **Mechanism.** Price alone is not enough. The fundamental channel must show up later in the filings: XBRL revenue,
   margin or volume in the next 1–2 quarters, or management confirming it in a concall. A price move with no
   fundamental follow-through is labelled `sentiment`, not `cause`.
5. **Out of sample, corrected for many tries.** The test is written down before the outcome window is looked at
   (walk-forward). It must hold on events it was not fitted on. The false-discovery rate is controlled
   (Benjamini–Hochberg) across all the links tested that month. Placebo dates (the same test on random non-event
   dates) must show no effect.

What is stored per link (`causal_edges`):
- effect size with confidence interval;
- number of events;
- dose-response slope;
- mechanism evidence ids;
- out-of-sample hit rate;
- last re-test date.

Links that stop passing on new events decay and drop out. Natural experiments carry the most weight because
companies cannot pick their exposure to them: sudden tariffs, wars, unscheduled RBI moves, sudden duty changes.

## 2. Embeddings and chunking on the budget
- **One high-quality vector space, not three.** Today there are three vector indexes:
  - Nemotron-3-Embed-8B (340k chunks, paid);
  - Qwen3-8B annual reports (partial);
  - bge-small (old).

  Pick one primary model and backfill everything into it, so every search compares like with like. bge-small is
  retired (Shivam).
  - **Qwen3-8B is already tested and dropped as a primary.** The 2026-10-19 test used 51 concall questions.
  - hit@5 scores:

    | Model | hit@5 |
    |---|---|
    | Nemotron-8B | 94.1% |
    | Nemotron-1B | 90.2% |
    | Gemini-001 | 88.2% |
    | Qwen3-8B | 84.3% |
    | EmbeddingGemma | 80.4% |
    | bge-small | 51.0% |

  - The AR Qwen index is only 4.5% done, so nothing is lost.
  - The 2026-10-24 annual-report test (48 questions, all on DeepInfra) is in
    `reality_engine/data/embed_test_ar/results.json` and `rerank_results.json`:
    - Nemotron-3.5-Embed-8B ties Nemotron-3-Embed-8B at $0.035/M: hit@5 95.8%, MRR 0.773 vs 0.775. 3.5 gives no
      gain, so the 340k index stays on 3.
    - The 1B models are both 87.5% at $0.015/M. The 1B NVFP4 is 85.4% at $0.01/M.
    - Qwen3-8B 83.3%; bge-m3 83.3%.
    - Re-ranking the 1B NVFP4's top 20 with Nemotron-3.5-Rerank-8B lifts hit@1 from 56% to 81% and MRR from
      0.70 to 0.88, for about $0.0007 per search. Cheap base + reranker is the main alternative to the 8B for the
      annual-report backfill.
  - C2 re-runs this test on the new chunks and on all doc types, not only concalls. The finalists are Nemotron-8B,
    Gemini-001 and anything new from C0.
- **Re-chunk the past corpus, not only new filings.** The old chunks were cut by length. Re-chunking costs $0
  (code only), but every new chunk needs a new vector, so the backfill is priced from local token counts in C0.
  - C2 first proves on a sample that the new chunks beat the old ones.
  - Then the backfill runs per doc type, highest value first: concalls, results notes, AR notes, decks, then circulars.
- **Topic-change splitting** applies only to long runs of prose with no structure (AR MD&A, long circular
  paragraphs).
  - Embedding every sentence multiplies vector calls by 10–30×. So free LLMs (OpenCode Go `-free`, Kilo free,
    Google free tier) mark the topic boundaries and write the one-line chunk summaries instead.
  - Both stay optional until C2 shows a gain.
  - If C0 confirms Google's embedding free tier and its rate limits, sentence-level similarity can run there at $0.
- **Chunking that follows document structure.** Cutting by length is out. Chunks follow the document's own units:
  - a results note, a table or a schedule stays whole;
  - concalls split by speaker turn, with Q&A pairs together;
  - decks split one slide per chunk;
  - circulars split by clause or paragraph, with scheme numbers kept.

  Every chunk gets a short header (company, document type, period, section, date) before embedding. This costs no
  model calls and lifts retrieval quality.
- **Quality test before spending.** 200 labelled query→passage pairs from EVAL25-style questions. Each candidate
  model × chunking setup is scored on recall@10. The money goes to the winner.
- **Provider choice is open (Shivam, 2026-10-25), not DeepInfra only.** C0 compares every serious embedding
  provider on the same footing:
  - Google, Meta-hosted endpoints, OpenCode, CoreWeave, Cerebras, DeepInfra, Nebius, Together, Fireworks, and
    other OpenAI-compatible hosts;
  - plus the model owners' own APIs.

  The criteria are model quality on our 200-pair test, price per million tokens, rate limits, batch discounts and
  data-retention terms. Price matters only among models that pass the quality bar. The provider is swappable
  because vectors are stored per model, never per provider.
- **Cost model, measured rather than guessed.** Corpus tokens × the provider's price per million tokens.
  - The one-off backfill is the $300 bucket.
  - The daily flow (new filings, circulars, transcripts) plus query embeddings is the $40 per month bucket.
  - First step: a $0 job counts the tokens in the corpus still to embed and in the average daily new flow, and
    reads the current price. Nothing is spent until Shivam sees that table.
- **No local embedding model** (Shivam, 2026-10-25). Embeddings come from the chosen provider. Local compute is
  spent on the database side instead: vector search (NumPy memmap; FAISS or hnswlib if needed), DuckDB, SQLite FTS5,
  and statsmodels/scikit-learn for the event studies and probes. No model runs locally to answer queries.

## 3. Making the LLM do less over time
- **Stage 1 (now): the LLM labels.** DeepSeek Flash answers the question sets (yes/no/unknown + quote) on new
  documents. Every answer is stored as a label on the chunk it came from.
- **Stage 2: linear probes on embeddings.** For each question ("pending licence?", "entering a new sector?",
  "guidance raised?"), a small logistic-regression head is trained on the stored chunk vectors using those labels.
  - Answering is then one dot product per chunk: matrix multiplication, on this PC, about free.
  - A probe takes over a question only when its out-of-sample accuracy matches the LLM's on held-out labels.
- **Stage 3: the LLM handles only the hard cases.** The LLM is called when:
  - the probe is unsure (score near 0.5);
  - the document type is new;
  - a shock detector fired.

  Those answers become new labels and the probes are retrained weekly (active learning). The share of decisions
  made by probes rather than the LLM is reported every week. It should keep rising.
- **Numbers never need an LLM.** XBRL, prices, NAV, commodity series and flows go through fixed code.
- **Forecasting is also mostly maths.** Each causal edge is an effect size × the company's exposure weight × a decay
  over the horizon. Each forecast is computed, logged and scored when its horizon ends, and calibrated per question
  type.

## 4. Compute on this PC
| work | runs on |
|---|---|
| Vector search (memmap, already 0.2–0.7 s), probes, event studies, difference-in-differences, calibration | CPU/NumPy |
| OCR of image-only pages | GPU, duty-cycled |
| Primary embedding backfill | DeepInfra, inside the $300 |
| Question-set labelling, shock triage | DeepSeek Go plan, $0, off-peak |
| Review of samples, design | Claude |

Raw data is stored on D. The working databases and indexes stay on C until C free space falls under 60 GB; then cold
indexes move to D.

## Build order (after the current G0–G4 merges)
1. **C0:** $0 measurement job — tokens still to embed, average daily new tokens, and prices and limits across all
   providers listed above → cost table for Shivam.
2. **C1:** structure-aware chunker + chunk headers, tested on 50 documents of each type.
3. **C2:** retrieval quality set (200 pairs) + model/chunking bake-off (only paid embeds Shivam approves).
4. **C3:** `causal_edges`, plus the event-study / difference-in-differences / dose-response / placebo toolkit, and
   its first run on tariffs Mar-2025, OMC Q4-Q1, and gold Jun-Jul 2026.
5. **C4:** question-set labels + the first 5 linear probes, with a probe-vs-LLM accuracy report.

## Storage: identical files are stored once (Shivam, 2026-10-25)
- Raw files on D are content-addressed. Files with the same sha256 are hard-linked, so one copy on disk serves every
  path that refers to it. This covers results PDFs a company files twice (standalone + consolidated, revisions) and
  decks re-filed under new names.
- Job `dedupe_raw` scans `D:\RealityEngine` by size, then by sha256, hard-links duplicates on the same volume, and
  reports the bytes saved. New downloads check the sha index before writing.
