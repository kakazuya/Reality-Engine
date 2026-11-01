# Task: research cheaper fact-extraction methods + where "decision-making models" fit (report only)

Owner: Shivam (2026-10-24). Reviewer: Claude. Web research + reading our repo; no paid calls, no bulk runs.

## Questions from Shivam

1. Search OpenRouter, DeepInfra and other inference providers (Together, Fireworks, Groq, Nebius, SiliconFlow,
   Novita, Mistral, Google, Azure, AWS, Cloudflare Workers AI...) for a **cheaper way to extract facts** from our
   documents than general-purpose LLMs (DeepSeek, Claude Opus/Haiku).
   - Text: is there a model that turns text directly into structured facts more cheaply? (Clarify the limits of
     embeddings: they retrieve, they don't extract values. Look at extraction-specialised models: GLiNER / GLiNER2,
     NuExtract (1.5/2.0, incl. vision), small instruction models fine-tuned for JSON/IE, "structured outputs" on small
     models, NER + relation extraction, table extraction.)
   - Images/charts/unstructured pages: specialised document models instead of general LLMs — OCR/VLM parsers
     (olmOCR, dots.ocr, MinerU, PaddleOCR-VL, Nanonets-OCR, Docling/SmolDocling, Marker+Surya, GOT-OCR, Qwen2.5/3-VL
     small, Mistral OCR, chart-to-table models like DePlot/MatCha/ChartGemma), hosted APIs priced per page (Mistral OCR,
     LlamaParse, Azure Document Intelligence, Google Document AI, AWS Textract), and which can run locally on this
     laptop (8 cores, GTX 1050 Ti 4 GB) or the PC (RX 6700 XT, DirectML).
   - For each candidate: what it extracts, price (per 1M tokens or per page, with date and source URL), speed,
     hosting (which providers), licence, and expected quality on Indian annual reports / concall transcripts /
     investor decks. Build a cost table for OUR volumes (from `tasks/coverage/coverage_2026-10-24.json`: concalls
     ~14k to read, decks ~25.8k to chunk, FY26 annual reports 5,361 with charts; ~620 tokens/chunk, ~130 chunks/AR,
     ~100–300 pages/AR) versus the current free-reader route (OpenCode Go/Zen/Kilo free models) and DeepSeek.
   - Recommend a tiered pipeline (e.g. cheap specialised parser/extractor for the bulk, LLM only for hard cases and
     QA), with a small pilot design (≤ $1, our 25/25 must-find gate) to prove quality before switching.

2. "We also plan to use decision-making models like JEV from TypeSafe or DEC. How can we use them in our workflow?"
   The names are unclear. Identify the most likely meanings and say which you think Shivam means (candidates to check:
   Meta's JEPA / V-JEPA family (LeCun's joint-embedding predictive architectures), Decision Transformer, DEC = Deep
   Embedded Clustering, any 2025–26 "decision model" products whose names resemble "JEV" / "TypeSafe" / "DEC").
   For the best-matching candidates: what they are, whether they are usable today (weights/API), and concretely where
   they could fit in our workflow per `tasks/FRAMEWORK.md` (cash-only long book, proof rules, all-peers ensemble in
   AGENTS.md §3, the backtest harness in tasks/backtests): e.g. as a peer lens, a regime model, a sequence model over
   the dense substrate, or not useful. Be honest where it is hype or doesn't fit. List the clarifying question for
   Shivam.

## Output

`tasks/research/EXTRACTION_AND_DECISION_MODELS_2026-10-24.md` with: summary (5 bullets), the cost table, the
recommended tiered pipeline + pilot, the decision-model section, open questions, and every source URL. Final answer =
the summary + cost table + pilot + the clarifying question.
