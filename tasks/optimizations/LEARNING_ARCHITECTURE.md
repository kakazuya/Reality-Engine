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
  retired (Shivam). Whether Qwen is kept is decided by the quality test below.
- **Chunking that follows document structure.** Cutting by length is out. Chunks follow the document's own units:
  - a results note, a table or a schedule stays whole;
  - concalls split by speaker turn, with Q&A pairs together;
  - decks split one slide per chunk;
  - circulars split by clause or paragraph, with scheme numbers kept.

  Every chunk gets a short header (company, document type, period, section, date) before embedding. This costs no
  model calls and lifts retrieval quality.
- **Quality test before spending.** 200 labelled query→passage pairs from EVAL25-style questions. Each candidate
  model × chunking setup is scored on recall@10. The money goes to the winner.
- **Cost model, measured rather than guessed.** Corpus tokens × the provider's price per million tokens.
  - The one-off backfill is the $300 bucket.
  - The daily flow (new filings, circulars, transcripts) plus query embeddings is the $40 per month bucket.
  - First step: a $0 job counts the tokens in the corpus still to embed and in the average daily new flow, and
    reads the current price. Nothing is spent until Shivam sees that table.
- **Local GPU option for the daily flow.** The RX 6700 XT has 12 GB, which is not enough for an 8B model in fp16.
  A 0.6B–4B embedding model in the same family (ONNX/DirectML, quantised) could take the daily flow for free, but
  only if it lands in the same vector space as the primary or wins on the quality test. Run it with duty cycling,
  because full GPU load has tripped the UPS twice.

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
| Local embedding of the daily flow (if it passes the test), OCR | GPU, duty-cycled |
| Primary embedding backfill | DeepInfra, inside the $300 |
| Question-set labelling, shock triage | DeepSeek Go plan, $0, off-peak |
| Review of samples, design | Claude |

Raw data is stored on D. The working databases and indexes stay on C until C free space falls under 60 GB; then cold
indexes move to D.

## Build order (after the current G0–G4 merges)
1. **C0:** $0 measurement job — tokens still to embed, average daily new tokens, the current price → cost table for
   Shivam.
2. **C1:** structure-aware chunker + chunk headers, tested on 50 documents of each type.
3. **C2:** retrieval quality set (200 pairs) + model/chunking bake-off (only paid embeds Shivam approves).
4. **C3:** `causal_edges`, plus the event-study / difference-in-differences / dose-response / placebo toolkit, and
   its first run on tariffs Mar-2025, OMC Q4-Q1, and gold Jun-Jul 2026.
5. **C4:** question-set labels + the first 5 linear probes, with a probe-vs-LLM accuracy report.
