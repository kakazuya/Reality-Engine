# Cheaper fact extraction + where “decision models” fit

**Owner:** Shivam · **Prepared:** 2026-10-24 · **Reviewer:** Claude · **Status:** research note only — no paid calls were made, no bulk runs, no code changes.

**Scope:** (1) cheaper ways to turn our documents into facts than general-purpose LLMs (DeepSeek, Claude Opus/Haiku), for concall transcripts, FY26 annual reports and investor decks; (2) the new “decision model” category (DeepInfra “Decision”: Cloudflare Clef/Clef-flash, Nace.AI Drex Max/Drex v2.0; TypeSafe Jev) and how it could fit `tasks/FRAMEWORK.md`, `AGENTS.md` §3 and the backtest harness.

**How to read the prices:** all prices are list prices captured on **2026-10-24** unless the row says otherwise. They are not bills. Output-token assumptions dominate the totals; the tables say where. Web sources are numbered `[S1]…[S32]` and listed at the end; repo sources are file paths.

---

## 1. Summary (5 bullets)

1. **The cheapest token is the one you do not send.** The repo has already measured the big lever: 59% of annual-report text repeats the prior year, and a CPU pass (XBRL for statements + year-over-year diff + section/red-flag rules + validation gate) leaves only **~9% of characters, about 12–32 page-equivalents per report**, at ~5 s/report on CPU. That is a larger saving than switching from DeepSeek to any smaller model, and it should be Tier 0 of any pipeline. (`tasks/ar_study/CPU_LEVERS.md`)
2. **Specialised document models are parsers, not extractors.** PaddleOCR-VL-1.6 (0.9B, Apache 2.0), GLM-OCR (1.33B total; vendor also cites 0.9B, MIT) and MinerU 2.5 (1.16B, Apache 2.0 + terms) are the 2026 leaders on OmniDocBench v1.6 (95.2–96.3%) and are small enough for the 4 GB laptop (4-bit) and comfortable on the RX 6700 XT. They output text/Markdown/tables; they do **not** produce facts like “capex raised 12%, funded by debt”. Hosted page OCR is $1.50–$15 per 1,000 pages; local is $0 marginal. Use local for bulk, hosted only for a bounded pilot.
3. **Specialised text extractors are narrow.** GLiNER2.5 (0.2–0.3B, CPU, Apache 2.0) is excellent for zero-shot entities, relations, classification and routing; NuExtract3 (4B, Apache 2.0, 128K context) is excellent for a **known JSON template** on text or page images. Neither is a drop-in replacement for open-ended fact mining. Small instruction models (Qwen3.5-9B at $0.10/$0.15 per 1M, Llama-3.1-8B at $0.02/$0.04) are cheap but unproven at our 25/25 gate; the free readers already pass and cost $0 cash.
4. **At our volumes, paid whole-document LLM extraction is still an $800-class exercise.** 14k concalls, 5,361 FY26 ARs and 25.8k decks: DeepSeek V4.1 Flash is roughly **$218 for the concalls, $254 for the FY26 ARs read whole, $348 for the decks read whole** (~$820 total) at the repo’s off-peak $0.15/$0.60. The CPU slice plus “decks are already page-read, chunk only” cuts the AR/deck paid-token need by roughly 10×; the concalls remain the largest paid line unless they stay on free readers. Hosted page APIs for the same AR+deck page count are **$2.8k–$27.7k**, so they are not a bulk route. The free-reader route is $0 cash but quota-bound: roughly 4–9 days for the concalls and ~9 days for the ARs at current throughput.
5. **Decision models are cheap typed gates, not extractors.** Clef-flash is $0.038 per 1M input tokens with output free; one pass over all 14k concalls costs **$5.64** (Drex v2.0 $8.90; Clef $35.62; Drex Max $17.81). They answer only the questions you define, they do not pull numbers or quotes, their calibration does not transfer to our data, and the Drex licence requires meaningful human oversight for financial decisions. Use them for triage and calibrated gates before the expensive extractor/LLM, never as the value extractor or as an unbacktested position sizer. A 100-item pilot is **≤$0.14** at 8k tokens/item.

---

## 2. What we are actually extracting (volumes and gaps)

From `tasks/coverage/coverage_2026-10-24.json` (main checkout), `tasks/FY26_AR_CHUNKING_2026-10-24.md`, `tasks/STATE.md` and `tasks/ar_study/READER_FINDINGS.md`:

| Family | Known | Chunked / read | Gap used in this note | Tokens / pages |
|---|---:|---:|---|---|
| Concall transcripts | 21,703 | 15,617 chunked; 7,477 DeepSeek-extracted | **~14,226 not yet extracted** (21,703 − 7,477) | measured 10.6k input / 23.3k output tokens per transcript (DeepSeek pilot) |
| FY26 annual reports | 5,362 filed since 2026-04-01 | 5,361 chunked (99.98%) | extraction/facts, especially charts/notes | **908,969 chunks; 563.6M tokens at 620 tokens/chunk**; mean 169.5 chunks/report (the 24-Oct subset had median 116 / mean 143); 100–300 pages/report |
| Investor decks | 27,286 | 1,441 chunked, but **26,818 decks already page-read** (11,995,750 facts) | **25,845 decks not chunked** — a chunk/search gap, not an extraction gap | ~815,837 pages read; ~30 pages/deck; 25.8k decks ≈ **774k pages** |

Two consequences:

- **Do not pay to re-extract the decks.** The extraction already happened (11.99M final numeric facts). The 25.8k gap is `raw_documents`/`document_chunks`/FTS + embeddings. A local parser can chunk them for $0; a page-OCR API would charge $1k–$12k for work already done.
- **The AR text layer is mostly good.** In the 60-report sample, 3.4% of pages had <200 characters and none of the 60 was a scan (`tasks/ANNUAL_REPORT_VALUE_STUDY.md`). OCR is therefore for scans, chart pages and broken font layers (70 reports in the FY26 pass), not for every page. That is why a 0.9B local OCR model is enough for the bulk; Mistral OCR/Azure Layout at $4–$10/1k pages is a hard-case tool.

---

## 3. Cost table for our volumes

### 3.1 Generative text routes (concall + AR + deck extraction)

Assumptions: 14,000 concalls × 10.6k input / 23.3k output tokens (measured, `tasks/STATE.md`); FY26 ARs **563.6M input tokens** (measured chunk corpus) and **282M output tokens** (0.5× input, compact JSON facts — an assumption, not a measurement); decks **774M input tokens** (1,000 tokens/page) and **387M output** if re-read whole. “— ” means the route does not do that job. Prices per 1M tokens, input/output.

| Route (hosting) | Price (2026-10-24) | 14k concalls | 5,361 FY26 ARs | 25.8k decks | Licence | Quality on our documents |
|---|---|---:|---:|---:|---|---|
| **Current free readers** (OpenCode Go/Zen/Kilo: LongCat, Cat Jam, Gemma 4 31B/26B, Space Bunny, Big Pickle, Muse 1.3) | **$0 marginal** + 2× $10/mo Go; Zen ~1,800 calls / 35M tokens/day per IP; Go ~56–69k AR pages/day/account | **$0 cash, ~4–9 days/quota** | **$0 cash, ~9 days** at 120k pages/day | decks already read; chunking is CPU | provider terms; some free models train on inputs | **Proven**: 25/25 must-find, <1% numbers not in text, depth ≥4,500 on the 110-piece gate. Concall quality is below DeepSeek (LongCat 66% auto recall vs DeepSeek 78% in the blind judge; DeepSeek captured 88% on the 50-question test). Quota and model churn are the risk. `tasks/ar_study/READER_FINDINGS.md` |
| **DeepSeek V4.1 Flash** (OpenCode Go off-peak; DeepInfra; Cloudflare) | **$0.15 / $0.60** off-peak (repo); DeepInfra promo **$0.098 / $0.294**; Cloudflare **$0.30 / $1.20**; MIT | **$218** | **$254 whole / $22.8 on the 9% CPU slice** | **$348 whole / ~$0 if chunk-only** | MIT | Best concall judge score in the repo pilot (25.2/30 blind Opus); output tokens make it expensive for open-ended AR work. Use for hard cases/QA, not bulk. |
| **DeepSeek V4.1 Flash, DeepInfra promo** | $0.098 / $0.294 | $110 | $138 | $190 | MIT | Same model; promotional price, verify before budgeting. |
| **Qwen3.5-9B** (DeepInfra, SiliconFlow, Together, Parasail, OpenRouter) | **$0.10 / $0.15** (DeepInfra/SiliconFlow); flex $0.08/$0.12; Together $0.17/$0.25; OpenRouter default $0.17/$0.25 | **$64** | **$99** | **$135** | Apache 2.0 | Cheap, multimodal, 262K context; **unproven** at 25/25 / <1% wrong numbers on Indian ARs. Candidate for a narrow schema, not open-ended mining. |
| **Llama-3.1-8B** (DeepInfra, Cloudflare) | $0.02 / $0.04 (DeepInfra); Cloudflare fp8-fast $0.045/$0.384 | **$16** | **$23** | **$31** | Llama licence | Likely below the bar on depth/number fidelity; use for classification only. |
| **Gemma-4-26B** (DeepInfra; Google free tier) | $0.07 / $0.34 (DeepInfra); free on Google with tight per-key limits | **$121** | **$135** | **$186** | Gemma terms | Passed 25/25 in the repo with the exhaustive prompt; good free route, not a paid bargain. |
| **NuExtract3 API** (NuMind) | **$1.00 / $5.00**; ~$0.001/text page input | **$498** at 5k output/doc; **$1,779** at 23.3k output | **$1,973** | **$2,709** | Apache 2.0 weights; API terms | Template-bound JSON; strong on known fields; **not** open-ended fact mining; Indian AR quality unproven. The API is not cheaper than DeepSeek for bulk; the weights are the point. |
| **NuExtract3 local** (4B, HF/Ollama) | $0 licence + GPU | **$0 marginal** | **$0 marginal** | **$0 marginal** | Apache 2.0 | 4B VLM, 128K context; fits the 12 GB PC at 4-bit; tight on the 4 GB laptop; measure pages/min. |
| **GLiNER2.5 local** (0.2–0.3B encoder) | $0 licence; CPU | **$0 marginal** | **$0 marginal** | **$0 marginal** | Apache 2.0 | Entities, relations, classification, routing; **does not extract values/periods/units**; ideal pre-filter/weak labeler. |

**Price sources for 3.1:** free-reader terms from `tasks/OPENCODE_ORCHESTRATION.md` and `tasks/ar_study/READER_FINDINGS.md`; DeepSeek from `reality_engine/scripts/concall_deepseek.py` and `[S4]`; Qwen/Llama/Gemma from `[S3]`/`[S15]`; NuExtract from `[S5]`.

**Reading the table:** the free readers are still the cash winner for prose; paid generative models are only justified for hard cases or when quota/time matters. The 9% CPU slice is what makes DeepSeek/Qwen affordable on ARs. NuExtract API is not a cost win at $5/M output; its local weights are.

### 3.2 Page routes (AR + deck pages)

Assumptions: 5,361 ARs × 200 pages = **1,072,200 pages**; 25,800 decks × 30 pages = **774,000 pages**; combined **1,846,200 pages**. The AR/deck text layer exists for most pages; page APIs are only needed for scans/charts/broken pages, so treat these as upper bounds.

| Route | Price (2026-10-24) | FY26 ARs | 25.8k decks | Both | Licence / hosting | Notes |
|---|---|---:|---:|---:|---|---|
| **PaddleOCR-VL-1.6** (0.9B) | $0 + hardware | $0 marginal | $0 marginal | $0 marginal | Apache 2.0; local | 96.34 OmniDocBench v1.6; 109 languages incl. Hindi; 0.9B fits 4 GB at 4-bit; two-stage PP-DocLayoutV3 + VLM. `[S8][S9]` |
| **GLM-OCR** (1.33B; vendor also cites 0.9B) | $0 + hardware | $0 | $0 | $0 | MIT; local | 95.22 OmniDocBench; 1.86 pages/s vendor single-replica; 8 languages (no Hindi listed); tables/code/stamps. `[S10]` |
| **MinerU 2.5 Pro** (1.16B) | $0 + hardware | $0 | $0 | $0 | Apache 2.0 + additional terms; local | 95.75 OmniDocBench; full PDF→Markdown/JSON; 109 languages; commercial conditions above thresholds. `[S11]` |
| **dots.mocr** (3B; dots.ocr 1.7B) | $0 + hardware | $0 | $0 | $0 | MIT + additional terms; local | ~84 olmOCR-Bench; layout/reading order; SVG/chart reconstruction; 100+ languages. `[S12]` |
| **olmOCR-2** (8B) | $0 + hardware | $0 | $0 | $0 | Apache 2.0; local | 82.4 olmOCR-Bench; PC only (12 GB, 4-bit tight); laptop no. `[S13]` |
| **Chandra OCR 2** (5.3B) | $0 + hardware | $0 | $0 | $0 | OpenRAIL-M (modified); local | 85.9 olmOCR-Bench; handwriting/faded scans; PC only; commercial restrictions. `[S14]` |
| **Mistral OCR 4.1** | **$4/1k pages**, batch **$2/1k**; Document AI **$5/1k** | $4,289 ($2,144 batch) | $3,096 ($1,548 batch) | $7,385 ($3,692 batch) | Mistral API | Strong layout; 2.7× Azure Read; 4.1 is current, OCR 3 was $2/1k. `[S16][S17]` |
| **Azure Document Intelligence — Read** | $1.50/1k pages ($0.60 above 1M/mo) | $1,608 | $1,161 | $2,769 | Azure | Text only; no table structure. `[S18][S19]` |
| **Azure DI — Layout** | $10/1k pages | $10,722 | $7,740 | $18,462 | Azure | Tables/structure; 6.7× Read. |
| **Google Document AI — Enterprise OCR** | $1.50/1k (1k–5M), $0.60 above; add-ons $6/1k | $1,608 | $1,161 | $2,769 | Google Cloud | Text only. `[S20]` |
| **Google Document AI — Layout Parser** | $10/1k | $10,722 | $7,740 | $18,462 | Google Cloud | Chunking/layout. |
| **AWS Textract — DetectDocumentText** | $1.50/1k (first 1M), $0.60 above | $1,608 | $1,161 | $2,769 | AWS | Text only. `[S21]` |
| **AWS Textract — Tables** | $15/1k (first 1M), $10 above | $16,083 | $11,610 | $27,693 | AWS | Most expensive table route. |
| **LlamaParse — Fast** | $1.25/1k pages (1 credit/page; $1.25/1k credits) | $1,340 | $968 | $2,308 | LlamaCloud | Text/spatial only; no Markdown. `[S22][S23]` |
| **LlamaParse — Agentic** | $12.50/1k pages (10 credits/page) | $13,402 | $9,675 | $23,078 | LlamaCloud | Agentic parse; 10× Fast. |
| **Marker + Surya** | $0 + hardware | $0 | $0 | $0 | GPL-3.0; commercial licence from Datalab; local | Fast PDF→Markdown; good tables; older than 2026 SOTA; laptop CPU/GPU. `[S24]` |
| **Docling / SmolDocling** | $0 + hardware | $0 | $0 | $0 | Docling MIT; SmolDocling CDLA-Permissive-2.0; local | CPU-first; 256M SmolDocling; lower accuracy than the 0.9–1.3B VLMs; good for text-layer PDFs. `[S25][S26]` |
| **DePlot / MatCha / ChartGemma** (chart-to-table) | $0 + hardware | $0 | $0 | $0 | DePlot Apache 2.0; ChartGemma MIT; MatCha: check model card; local | 2023–24 chart models; superseded by 2026 small VLMs on charts; use only if a chart-only page is cheap. `[S27][S28]` |
| **Nanonets-OCR-s / GOT-OCR2.0 / Qwen3-VL-2B/4B/8B** | $0 + hardware (or host) | $0 | $0 | $0 | Apache 2.0 (verify each model card) | General/small VLMs; Qwen3-VL-8B PC only; 2B/4B laptop; Nanonets 3B local. `[S29][S30]` |

**Reading the table:** if you must use a hosted page API, the cheapest useful combination is **Azure/Google/AWS plain OCR at $1.50/1k** for text-only pages, and **Mistral OCR at $2–$4/1k or Document AI at $5/1k** for layout; LlamaParse Agentic is the premium option. None of them is justified for the bulk when PaddleOCR-VL/GLM-OCR/MinerU run locally for $0. The local models are also the only ones that fit the “no paid calls, read-only data” constraint.

### 3.3 Decision-model pass costs (typed questions, one pass)

These are **input-token-only**; output is free, and one request can ask many questions about the same state (the state is read and billed once). Costs below are one pass over the whole text. Prices from `[S31]` (2026-10-24).

| Model | Params / context / licence | Price per 1M input | 14k concalls | FY26 ARs (564M) | 25.8k decks (774M) | Hosting |
|---|---|---:|---:|---:|---:|---|
| **Clef** | 27B, 64k, Apache 2.0 | **$0.24** (20% off) | **$35.62** | **$135.27** | **$185.76** | DeepInfra; Workers AI; System One-compatible |
| **Clef-flash** | 9B, 24k, Apache 2.0 | **$0.038** (50% off) | **$5.64** | **$21.42** | **$29.41** | DeepInfra; Workers AI |
| **Drex Max** | 27B, 256k, RAIL-M | **$0.12** | **$17.81** | **$67.64** | **$92.88** | DeepInfra; OpenRouter |
| **Drex v2.0** | 35B MoE / 3B active, 128k, RAIL-M | **$0.06** | **$8.90** | **$33.82** | **$46.44** | DeepInfra; OpenRouter |
| **Jev** (reference) | TypeSafe System One, hosted | input-token priced; output free | not priced here | not priced here | not priced here | TypeSafe API; OpenRouter |

If you only send the 9% CPU slice, divide the AR/deck columns by ~11: Clef-flash ~$1.9 for the AR slice, Drex v2.0 ~$3.0. That is the intended use: a cheap gate before the extractor.

---

## 4. What each candidate is good for (and where it is not)

### 4.1 Text → facts

| Candidate | What it actually does | Best role | Limit on Indian ARs / concalls |
|---|---|---|---|
| **GLiNER2 / GLiNER2.5** | Schema-conditioned encoder: zero-shot NER, text classification, structured/JSON extraction, relation extraction, span attributes; 74M/0.2B/0.3B; CPU; 4,096 words; Apache 2.0 | Pre-label entities/relations; route chunks; build silver labels; cheap classification gates | No numeric normalization, no period/unit/standalone-consolidated logic, no open-ended “find every fact”; table cells are not its job. `[S6][S7]` |
| **NuExtract 1.5/2.0/3** | Template-driven JSON extraction from text or page images; 2.0 4B/8B based on Qwen2.5-VL; NuExtract3 4B, 128K, Apache 2.0, local/API | Known fields: order book, capex, guidance, borrowing maturity, auditor modifications, BRSR rows | You must author the template; it fills values, it does not discover new fact families; Indian multi-column/notes formats unproven; output $5/M makes the API expensive for bulk. `[S5]` |
| **Small instruction models** (Qwen3.5-9B, Llama-3.1-8B, Gemma-4-26B/12B, Phi-4) | General chat + JSON schema; cheap per token | Narrow classification/JSON on the CPU slice; fallback when free quota is exhausted | The repo’s small/free models needed exhaustive prompts and multiple readers to hit 25/25; Llama-8B-class is likely below the bar on depth/number fidelity. Use only after a pilot. `[S1][S2]` |
| **Embeddings** (Nemotron-8B, Qwen3-8B, EmbeddingGemma) | Retrieve/chunk similarity | Route to the right 9% slice; dedupe; retrieve for QA | **They retrieve, they do not extract values.** A vector is not a fact; do not count an embedding pass as extraction. `tasks/STATE.md`, `AGENTS.md` §3 |
| **Table extraction** (Docling TableFormer, Table Transformer, PyMuPDF find_tables, Camelot, img2table) | Detect table structure/cells | Fixed-format statutory tables; XBRL cross-check | Scrambled columns in text layer; scanned tables need OCR; always validate subtotals/units against XBRL (`financial_validator.py`, `challenger/gate.py`). `[S25]` |
| **Decision models** (Clef/Drex/Jev) | Score typed questions (`noul`, `choice`, `score`) with calibrated probabilities; no text | Triage/gates: capex/order/guidance change, red flags, routing | Cannot extract a value, quote or page; only answers the options you define; calibration transfer is unproven; no explanation. `[S31]` |

### 4.2 Images / charts / unstructured pages

The 2026 OCR landscape changed: small dedicated document VLMs beat 30B–235B general VLMs on OmniDocBench at a fraction of the compute. The practical ranking for us:

1. **PaddleOCR-VL-1.6 (0.9B, Apache 2.0)** — the default. 96.34 OmniDocBench v1.6, text/formula/table/reading order, 109 languages including Hindi, two-stage layout + recognition. Fits the laptop at 4-bit; best accuracy per watt.
2. **GLM-OCR (1.33B, MIT)** — close second (95.22), strongest on complex tables/code/stamps; 1.86 pages/s vendor benchmark; only 8 languages (check Hindi/Devanagari before PIB regional use).
3. **MinerU 2.5 Pro (1.16B, Apache 2.0 + terms)** — full PDF→Markdown/JSON pipeline, tables/formulas, 109 languages; the easiest “replace the whole parser” option; commercial terms above thresholds.
4. **dots.mocr (3B, MIT + terms)** — layout/reading order and chart→SVG; PC only; good when structure matters more than raw text.
5. **olmOCR-2 (8B, Apache 2.0)** — strongest audit-friendly option, but 8B needs the PC (12 GB, 4-bit tight), not the laptop.
6. **Chandra OCR 2 (5.3B, OpenRAIL-M)** — handwriting/faded scans; PC only; licence restrictions.
7. **Docling/SmolDocling, Marker+Surya** — CPU-fast, text-layer PDFs; lower accuracy than the 0.9–1.3B VLMs; Marker is GPL-3.0 (commercial licence available).
8. **Hosted APIs** — Mistral OCR ($2–$4/1k), Azure/Google/AWS ($1.50/1k text, $10–$15/1k layout/tables), LlamaParse ($1.25–$12.50/1k). Use only for a bounded hard-case pilot; at our page counts they are $2.8k–$27.7k.
9. **Chart-only models (DePlot/MatCha/ChartGemma)** — 2023–24 technology; superseded by the 2026 VLMs for charts. Keep as a fallback only if a chart page cannot go through PaddleOCR-VL/dots.mocr.

**None of these public benchmarks is an Indian annual report.** OmniDocBench/olmOCR-Bench are a prior, not proof; the pilot must score our 25/25 must-find facts, <1% numbers not in text, and table/units, not just text similarity.

**Local feasibility**

| Model | Laptop (8 cores, GTX 1050 Ti 4 GB) | PC (RX 6700 XT 12 GB, DirectML) | Note |
|---|---|---|---|
| GLiNER2.5 (74M–0.3B) | **CPU: yes** | yes | No GPU required; sub-second per chunk class; measure. |
| PaddleOCR-VL-1.6 (0.9B) | **4-bit: yes (tight); CPU fallback** | yes | Best local default; measure pages/min and VRAM on both. |
| GLM-OCR (1.33B; 0.9B cited) | **4-bit: yes (tight)** | yes | MIT; check Devanagari. |
| MinerU 2.5 (1.16B) | **4-bit: yes (tight)** | yes | Full pipeline; more RAM. |
| NuExtract3 (4B) | **4-bit: tight; short context only** | yes | Vision encoder + 4B; PC preferred. |
| dots.mocr (3B) | 4-bit: tight | yes | PC preferred. |
| DeepSeek-OCR-2 (3.39B) | 4-bit: tight | yes | Apache 2.0; older benchmark. |
| olmOCR-2 (8B) | **no** | 4-bit: maybe (12 GB tight) | 8B + vision. |
| Chandra OCR 2 (5.3B) | **no** | yes | OpenRAIL. |
| Qwen3-VL-2B/4B | yes | yes | General VLM; chart/QA fallback. |
| Qwen3-VL-8B / Qwen3.5-9B | **no** | yes | 8–9B. |
| SmolDocling (256M) / Docling | **CPU: yes** | yes | Lower accuracy; fast. |
| Marker+Surya | CPU/GPU: yes (smaller models) | yes | GPL-3.0; commercial licence. |

The laptop is a **CPU + 4 GB GPU** box: use it for GLiNER2.5, PaddleOCR-VL/GLM-OCR on selected pages, and text-layer parsing. The PC is the bulk OCR box. DirectML support is uneven for the newest VLMs; if a model does not run under DirectML, use ONNX/CPU or the PC’s llama.cpp/Vulkan path, and measure before promising throughput.

### 4.3 Provider scan (what changed, what did not)

- **OpenRouter** is an aggregator, not a price leader: Qwen3.5-9B defaults to $0.17/$0.25, with a 5.5% credit-purchase fee; pass-through pricing means the host’s price is the price. `[S1][S2]`
- **DeepInfra** is at the low end for the same weights: Qwen3.5-9B $0.10/$0.15 (flex $0.08/$0.12), DeepSeek V4.1 Flash $0.098/$0.294 promo, and the four decision models. It also gives zero-retention and JSON schema. `[S3][S4]`
- **SiliconFlow** matches DeepInfra at $0.10/$0.15 for Qwen3.5-9B; **Together** is higher ($0.17/$0.25); **Parasail** $0.10/$0.25. The spread for identical weights is ~1.7×, not 10×. `[S2]`
- **Cloudflare Workers AI** is cheap for small Llama/Qwen/Gemma models (Llama-3.1-8B fp8-fast $0.045/$0.384; Qwen3-30B $0.051/$0.335; Gemma-4-26B $0.10/$0.30) but expensive for DeepSeek V4.1 Flash ($0.30/$1.20) and it does not host the document parsers. `[S15]`
- **Mistral** is the page-OCR specialist, not a token bargain: OCR 4.1 $4/1k pages ($2 batch), Document AI $5/1k. `[S16]`
- **Google/Azure/AWS** converge on $1.50/1k plain OCR; structure costs $10–$15/1k; custom extraction $30–$70/1k. None is cheaper than local at our volume. `[S18][S20][S21]`
- **Groq/Fireworks/Nebius/Novita** did not surface a cheaper route at the catalog level in this scan; their pitch is speed/catalog, not a lower price for the same weights. If a specific model matters, price it at the provider before use; do not assume the aggregator is cheapest.

**Bottom line:** provider arbitrage is a few percent to ~1.7×. The big levers are (a) don’t send the 91% that rules/diff can drop, (b) use a 0.9–1.3B local parser for pages, (c) use a 0.2–0.3B encoder for entities/routing, (d) use a 4B template extractor for known fields, and (e) keep the free readers for prose and DeepSeek for hard cases/QA.

---

## 5. Recommended tiered pipeline

### Tier 0 — CPU, free, do this first (no model purchase)

1. **Text layer + XBRL.** PyMuPDF text; statements from `results_xbrl.db`, not the PDF; use the PDF only as a cross-check. This removes the hardest multi-column tables.
2. **Year-over-year diff.** 59% of AR text repeats; 32% of pages are ≥80% repeated. Store repeated text once; send only changed/new text. Run newest year first and diff backwards for the first report per company.
3. **Section/red-flag rules + validation gate.** Keep auditor/CARO/C&AG/MR-3, contingent liabilities, commitments, related-party, borrowings maturity, CSR, ratings, going-concern language; validate tables by subtotal/total, balance-sheet identity, or XBRL match. `challenger/gate.py`, `columns.py`, `financial_validator.py`.
4. **Route with embeddings/FTS, not extraction.** Use the Nemotron-8B/Qwen3-8B indexes to choose the 9% slice and to retrieve for QA. Never count retrieval as extraction.
5. **Expected effect:** ~9% of characters, 12–32 page-equivalents/report, ~5 s/report CPU, ~18 CPU-hours for 12.7k reports (2–3 h on 8 workers). This is measured in `tasks/ar_study/CPU_LEVERS.md`.

### Tier 1 — local specialised models for the bulk

| Job | Model | Why | Where |
|---|---|---|---|
| Scanned/broken pages, charts, tables | **PaddleOCR-VL-1.6** (0.9B, Apache 2.0) | Best accuracy/size; 109 languages; fits 4 GB at 4-bit | PC first; laptop for selected pages |
| Complex tables/stamps/code | **GLM-OCR** (1.33B, MIT) | 95.22 OmniDocBench; strong tables; 1.86 pages/s vendor | PC; laptop 4-bit |
| Full PDF→Markdown/JSON | **MinerU 2.5** (1.16B, Apache 2.0 + terms) | End-to-end layout/table/formula pipeline; 109 languages | PC |
| Entity/relation tagging, routing, silver labels | **GLiNER2.5** (0.2–0.3B, Apache 2.0) | CPU, one pass, schema-driven; no hallucinated free text | Laptop/PC CPU |
| Known-field JSON extraction | **NuExtract3** (4B, Apache 2.0) | Template-bound; text or page image; 128K | PC; API only for a ≤$1 pilot |
| Text-layer tables | **Docling TableFormer / PyMuPDF find_tables / Camelot** | No GPU; fast; validate against XBRL | Laptop CPU |

Output goes to `document_chunks`, `deck_figures`, `ar_facts` with page/quote/known_at, never to the decision context raw. For decks, **chunk the existing 26,818 page-read decks**; do not re-extract.

### Tier 2 — free readers for prose, paid models for hard cases

1. **Free readers first** (LongCat, Cat Jam, Gemma 4 31B/26B, Space Bunny, Big Pickle, Muse 1.3) on the Tier-0 slice, using the exhaustive prompt and the 25/25 admission gate. They are proven and $0 cash.
2. **DeepSeek V4.1 Flash** only for: low-confidence pieces, conflicting readers, numeric anomalies, final QA, and concalls where its 25.2/30 judge score is worth $0.0156/doc. Off-peak only; no bulk.
3. **Small instruction models** (Qwen3.5-9B) only if a pilot shows cost-adjusted quality ≥ free readers; otherwise they are a fallback when quota is exhausted, not a replacement.

### Tier 3 — decision models as gates

1. **Triage gate:** Clef-flash/Drex v2.0 on each chunk/announcement: “is there a capex/order/guidance change, which direction, how material, which segment?” One request, 8–12 questions, input-only billing. High-confidence positives go to Tier 2 extractor; negatives are dropped; low-confidence abstain to human/LLM.
2. **Red-flag gate:** text-only questions (“going-concern language?”, “auditor qualification?”, “pledge/related-party stress?”) on the AR/announcement slice. The numeric solvency gate (pledge >15%, IC <2.5, D/E >1.5) stays deterministic; the decision model cannot override it.
3. **Thesis/regime gates:** atomic questions for a card (customer concentration, guidance conditionality, capex funding, regime risk-on/off). Use probabilities as features/peer lenses in `model_explainer_rankings`/`composite_screener`, not as the trunk.
4. **Never** use a decision model to extract numbers/quotes, to set position size without calibration + backtest, or to make a fully automated financial decision (Drex licence + FRAMEWORK human oversight).

---

## 6. Pilot designs

### 6.1 Extraction pilot (≤ $1, 25/25 gate)

**Goal:** prove a cheaper route reaches the existing admission bar before switching any production reader.

- **Sample:** the existing 110 study pieces / gold set (`tasks/ar_study/challenger/gold_mustfind.json`, `gold_numbers.json`, `ar_queue.py test-export`). Start with **50 of the 110 study pieces**, selecting the pieces that cover all 25 must-find facts so the API bill stays under $1; add a small unseen FY26 holdout only as a second wave.
- **Arms:**
  - **A (control):** current free reader (LongCat or Gemma 4 31B) on the same pieces.
  - **B (CPU slice + NuExtract3):** Tier-0 9% slice → NuExtract3 template for 6 fact families (cash flow, contract liabilities, capital commitments, contingent liabilities, auditor/KAM, BRSR related-party). Local weights preferred ($0); API only if local is unavailable.
  - **C (local OCR + NuExtract3):** PaddleOCR-VL/GLM-OCR on chart/scan/table pages only → NuExtract3; measure whether OCR improves the must-find items that the text layer misses.
- **Scoring (same as `READER_FINDINGS.md`):** 25/25 must-find; <1% of numbers not found in the text; regrouped numbers <0.5%; depth ≥4,500 facts; page/quote valid; every piece answered; pages/min and $/report.
- **Budget:** 50 pieces × 18k chars ≈ 9k tokens = 450k input × $1/M = **$0.45**; 50 × 2k output × $5/M = **$0.50**; total **$0.95**. If local weights work, **$0**. Add $0 for PaddleOCR-VL/GLiNER2.5 local.
- **Decision rule:** switch bulk to the local route only if it matches or beats the free reader on 25/25 and <1% not-in-text, at ≥ current pages/min and ≤ $0.02/report. If it fails, keep free readers and use NuExtract3 only for the 6 known fields.

### 6.2 Decision-model pilot (≤ $0.50, 100 labelled items)

**Goal:** measure accuracy and calibration of Clef-flash and Drex v2.0 on our documents; decide whether they can be a triage gate.

- **Sample (100 items):**
  - 40 concall chunks from 2024–2026 with known capex/order/guidance statements (from `cc_items` where `value_in_quote` passes; hand-check 20).
  - 30 BSE announcement chunks (order wins, capex, guidance, rating actions, auditor changes) with hand labels.
  - 30 AR passages (the 17 gold must-find items + 13 additional notes/contingent/auditor passages).
- **Labels:** `has_capex_change`, `capex_direction` (raise/cut/none/unclear), `capex_magnitude` (none/<5%/5–15%/>15%), `has_order_change`, `guidance_direction` (raise/maintain/cut/withdraw/none), `is_material`, `red_flag`. Two independent labels for 20 items; report Cohen’s kappa.
- **Split:** 50 dev / 50 test; fit any temperature/threshold on dev only; evaluate once on test. With 100 items, report bootstrap 95% CIs and treat this as a screen, not proof.
- **Models:** Clef-flash and Drex v2.0 (cheap); Clef and Drex Max on 20 items only if the cheap ones look promising.
- **Metrics:** accuracy/macro-F1 for choices; AUROC for `noul`; **Brier score**, **ECE (5–10 bins)**, reliability slope; selective accuracy at 50%/70% coverage (abstain when p ∈ [0.4, 0.6]); cost per 1k items; latency.
- **Baselines:** keyword/regex, current free-reader labels, DeepSeek labels. The decision model must beat the keyword baseline and approach the free reader at a fraction of the cost to be useful.
- **Budget:** 100 × 8k tokens = 0.8M input. Clef-flash **$0.0304**; Drex v2.0 **$0.048**; both **$0.0784**. Add 20 × 8k on Clef ($0.0384) and Drex Max ($0.0192) → **$0.136**. At 32k tokens/item, both cheap models = **$0.3136**; still under $0.50.
- **Decision rule:** if Clef-flash has ECE ≤0.10, Brier ≤0.20, AUROC ≥0.75 and selective accuracy ≥ the free reader at 70% coverage, use it as a triage gate (not a value extractor). If not, keep it out of production; do not tune thresholds on the test set.

**Exact request shape (DeepInfra `/v1/decisions`)**

```bash
curl https://api.deepinfra.com/v1/decisions \
  -H "Authorization: Bearer $DEEPINFRA_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "Cloudflare/clef-flash",
    "state": {
      "doc_type": "CONCALL_TRANSCRIPT",
      "symbol": "TITAGARH",
      "as_of": "2026-07-31",
      "text": "…chunk text, up to the model context…"
    },
    "questions": {
      "capex_change": {
        "type": "noul",
        "instructions": "Does management state a change in capex plans versus the prior quarter?",
        "criteria": {"true": "A change is stated", "false": "No change or not discussed"}
      },
      "capex_direction": {
        "type": "choice",
        "instructions": "Direction of the capex change",
        "criteria": {"raise": "Increase or new capex", "cut": "Cut, defer or cancel", "none": "No change", "unclear": "Cannot tell"}
      },
      "capex_magnitude": {
        "type": "score",
        "instructions": "Size of the capex change",
        "criteria": ["none", "<5%", "5-15%", ">15%"]
      },
      "order_change": {
        "type": "noul",
        "instructions": "Is there a new order win, order-book change or cancellation?"
      },
      "guidance_direction": {
        "type": "choice",
        "instructions": "Guidance direction versus prior guidance",
        "criteria": {"raise": "Raised", "maintain": "Maintained", "cut": "Cut", "withdraw": "Withdrawn", "none": "No guidance"}
      },
      "segment": {
        "type": "choice",
        "instructions": "Which segment does the statement concern?",
        "criteria": {"rail": "Rail systems", "defence": "Defence", "other": "Other/unknown"}
      },
      "material": {
        "type": "noul",
        "instructions": "Would this change a long-only thesis materially?"
      }
    }
  }'
```

The reply mirrors the question keys:

```json
{
  "model": "Cloudflare/clef-flash",
  "answers": {
    "capex_change": {"type": "noul", "noul": 0.91},
    "capex_direction": {"type": "choice", "choice": "raise", "probabilities": {"raise": 0.77, "cut": 0.05, "none": 0.12, "unclear": 0.06}, "confidence": 0.77},
    "capex_magnitude": {"type": "score", "score": 2.1, "legend": {"0": "none", "1": "<5%", "2": "5-15%", "3": ">15%"}, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.55, "3": 0.25}, "confidence": 0.55}
  },
  "usage": {"input_tokens": 8123, "output_tokens": 3}
}
```

**API facts to respect** (`[S31]`):
- Endpoint: `POST https://api.deepinfra.com/v1/decisions`; aliases `/v1/systemone` and `/typesafe/v1/systemone` (Jev/TypeSafe SDK base `https://api.deepinfra.com/typesafe`).
- `state`: string, JSON object, or array; `questions`: 1–64 properties in the schema; **Drex Max page says up to 16 questions per request** — use 8–12 to be safe.
- `choice`: 2–52 options; `score`: 2–10 ordered levels; `noul`: optional `criteria.true/false` descriptions.
- Images: up to 4, data URI or `{content_type, base64}`, body <13 MiB; each image 64–~4,000 input tokens; `usage.image_tokens`.
- Drex Max: states >8,192 tokens are filtered to relevant passages; billed only tokens read. Long-state filtering is not available on image requests.
- Output is free; `usage.input_tokens` is the bill.
- Licences: Clef/Clef-flash Apache 2.0; Drex Max/Drex v2.0 Nace AI Open RAIL-M with **no fully automated financial decisions without qualified human oversight**.

**Trading-workflow gates (concrete, under FRAMEWORK.md)**

| Gate | Question shape | Where it sits | What it may/may not do |
|---|---|---|---|
| **Event triage** | `noul` material event + `choice` type (capex/order/guidance/rating/auditor) + `score` magnitude | After EOD/announcement ingestion, before `event_graph`/hypothesis queue | May drop low-confidence non-events and route positives to Tier 2. May not create a trade by itself. |
| **Solvency/red-flag** | `noul` going-concern/auditor qualification/pledge stress + `score` severity | After ensemble rank, beside the deterministic gate | May add a text flag/veto; may not override pledge >15%, IC <2.5, D/E >1.5. |
| **Thesis check** | 6 atomic questions: customer concentration, guidance conditionality, capex funding, related-party dependence, accounting change, segment mix | In a hypothesis card / `composite_screener` | Probabilities become features; the card must still pass the harness. |
| **Regime** | `choice` risk-on/neutral/risk-off + `score` confidence from a JSON state (rates, inflation, trend, FII/DII, breadth) | As an all-peers lens / conditional ranking | A peer lens, not the trunk; no hard market timing without a test. |
| **Position sizing** | `score` conviction / `noul` “is the thesis intact?” | Only after calibration + backtest | May scale within the 10% ADV / 10% allocation / 8% kill limits; never set size directly from an uncalibrated probability. |

**Harness integration:** add a `DecisionGate` card under `reality_engine/harness/cards/`, consume only `state` fields known at `t` (PIT), pre-register the threshold and the question set, run the H0x pipeline (`book.py`, `costs_tax.py`, `stats.py`, `ledger.py`) with the same 30 bp/tax/benchmark and 499 placebos, and append every variant to the ledger. Run it across the four separate periods required by FRAMEWORK §6; do not fit thresholds on 2026 (2026 is live). A gate that only improves a backtest after seeing the test period is not a gate.

**Honest limits**

- **Not a reasoner.** It scores options; it cannot discover a fact family or explain why. Datacamp’s summary of the independent tests: Red Hat found decision models did not give faster, cheaper or better answers than LLM-as-a-judge overall; the “Just Ask Jev” paper found pooled calibration but not within-benchmark calibration; keeping only the half of answers furthest from 50% raised median accuracy from 0.793 to 0.933. `[S31][S32]`
- **Calibration does not transfer.** Calibrate on our labels; use temperature scaling on a dev split; report Brier/ECE; abstain near 0.5.
- **Order bias / prompt sensitivity.** TypeSafe’s own docs list math, dates, long irrelevant context, adversarial text and first-option bias; Red Hat found a prompt tuned for one model hurt another by 3.7 pp. `[S31][S32]`
- **No explanations.** Keep the input state, probabilities and thresholds for audit; pair with an LLM only when a reason is needed.
- **Licence.** Drex is RAIL-M with human-oversight restrictions for financial decisions; Clef is Apache 2.0. For production gates, prefer Clef/Clef-flash unless Shivam accepts the Drex terms with human review.
- **Hype check.** The category is real and useful as a fast gate, but it is not a new brain. It is a packaged scorer; the innovation is the typed interface and calibration training, not a new reasoning architecture. `[S31]`

---

## 7. Open questions

1. **Pilot sample:** approve 40 concall chunks + 30 BSE announcements + 30 AR passages, with Claude/hand labels? Or use only the 25/25 AR set?
2. **Target label:** is “material change in capex/orders/guidance” the right first gate, or do you want “red flag / solvency stress” first?
3. **Human-in-the-loop:** for production, restrict to Apache-2.0 Clef, or allow Drex with the required human review?
4. **Budget:** is ≤$0.50 for the decision pilot and ≤$1 for the extraction pilot approved? (Design only; no calls run.)
5. **Local hardware:** is the RX 6700 XT PC available for the bulk OCR run, or laptop-only? This decides PaddleOCR-VL vs CPU Docling.
6. **Labels/outcomes:** which outcome should calibration target — 20/60-day excess return, event materiality, or human judgment? A probability is only useful if the label is defined.
7. **Languages:** do we need Hindi/regional PIB and concall support now? PaddleOCR-VL/GLiNER2.5 multi cover it; GLM-OCR’s 8-language list may not.
8. **Volume basis:** should the cost table use 14k concalls (all known minus extracted) or the full 21.7k backfill? The difference is ~$120 at DeepSeek.
9. **Deck scope:** confirm decks only need chunking (the 11.99M facts are trusted), not re-extraction. If they need re-reading, the page costs apply.
10. **JEV:** do you want the TypeSafe Jev API evaluated alongside Clef/Drex in the same pilot, or is DeepInfra’s decision endpoint the only route?

---

## 8. Sources

### Web (accessed 2026-10-24)

- **[S1]** OpenRouter, Qwen3.5-9B model page: https://openrouter.ai/qwen/qwen3.5-9b
- **[S2]** VernaOne, Qwen3.5-9B provider comparison (prices, tiers, 5.5% credit fee): https://verna.one/models/qwen3.5-9b
- **[S3]** DeepInfra, pricing: https://deepinfra.com/pricing
- **[S4]** DeepInfra, DeepSeek V4.1 Flash model page: https://deepinfra.com/deepseek-ai/DeepSeek-V4.1-Flash-1017
- **[S5]** NuExtract pricing: https://about.nuextract.ai/pricing ; NuExtract3 model card: https://huggingface.co/numind/NuExtract3
- **[S6]** GLiNER2.5 model page (params, licence, no GPU): https://fastino.ai/models/gliner2-5
- **[S7]** GLiNER2 repository: https://github.com/fastino-ai/GLiNER2
- **[S8]** PaddleOCR-VL model card: https://huggingface.co/PaddlePaddle/PaddleOCR-VL ; PaddleOCR repo: https://github.com/PaddlePaddle/PaddleOCR
- **[S9]** PaddleOCR-VL-1.5 paper: https://arxiv.org/html/2601.21957v2
- **[S10]** GLM-OCR / open-source OCR ranking (params, licence, OmniDocBench, speed): https://roboflow.com/blog/best-open-source-ocr-models ; https://aitechmodel.com/best-open-source-ocr-models/ ; official docs: https://docs.z.ai/guides/vlm/glm-ocr
- **[S11]** MinerU: https://github.com/opendatalab/MinerU
- **[S12]** dots.ocr: https://huggingface.co/rednote-hilab/dots.ocr ; dots.mocr: https://huggingface.co/dots-studio/dots.mocr ; licence: https://huggingface.co/rednote-hilab/dots.ocr/blob/main/dots.ocr%20LICENSE%20AGREEMENT
- **[S13]** olmOCR: https://github.com/allenai/olmocr
- **[S14]** Chandra OCR 2: https://huggingface.co/datalab-to/chandra-ocr-2
- **[S15]** Cloudflare Workers AI pricing: https://developers.cloudflare.com/workers-ai/platform/pricing/
- **[S16]** Mistral pricing (OCR per 1,000 pages; OCR 4.1 / Document AI rates): https://mistral.ai/pricing ; rate audit: https://docuocr.com/ocr-pricing-per-1000-pages ; https://docuocr.com/mistral-ocr-pricing
- **[S17]** Mistral OCR pricing context: https://agentscamp.com/tools/mistral-ocr
- **[S18]** Azure Document Intelligence pricing: https://azure.microsoft.com/en-us/pricing/details/ai-document-intelligence/
- **[S19]** Azure OCR rate audit: https://docuocr.com/azure-ocr-pricing
- **[S20]** Google Document AI pricing: https://cloud.google.com/document-ai/pricing
- **[S21]** AWS Textract pricing: https://aws.amazon.com/textract/pricing/
- **[S22]** LlamaParse pricing: https://www.llamaindex.ai/pricing
- **[S23]** LlamaParse credit rates: https://docs.cloud.llamaindex.ai/pricing
- **[S24]** Marker: https://github.com/datalab-to/marker
- **[S25]** Docling: https://github.com/docling-project/docling
- **[S26]** SmolDocling: https://huggingface.co/docling-project/SmolDocling-256M-preview
- **[S27]** DePlot: https://huggingface.co/google/deplot
- **[S28]** ChartGemma: https://huggingface.co/ahmed-masry/chartgemma
- **[S29]** Nanonets-OCR-s: https://huggingface.co/nanonets/Nanonets-OCR-s
- **[S30]** Qwen3-VL-8B: https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
- **[S31]** Decision models: DeepInfra Clef docs: https://docs.deepinfra.com/integrations/clef ; DeepInfra decision category: https://deepinfra.com/models/decision ; Clef: https://deepinfra.com/Cloudflare/clef ; Clef-flash: https://deepinfra.com/Cloudflare/clef-flash ; Drex Max: https://deepinfra.com/nace-ai/drex-max ; Drex v2.0: https://deepinfra.com/nace-ai/drex-v2.0 ; API schema: https://deepinfra.com/nace-ai/drex-max/api ; TypeSafe Jev: https://docs.typesafe.ai/introduction ; OpenRouter Jev Router: https://openrouter.ai/docs/guides/routing/routers/jev-router ; Datacamp decision-model explainer: https://www.datacamp.com/tutorial/what-are-ai-decision-models ; Cloudflare Clef launch: https://blog.cloudflare.com/clef-decision-models/
- **[S32]** Independent decision-model tests (as cited by Datacamp): https://developers.redhat.com/articles/2026/10/02/benchmarking-ai-decision-models-against-traditional-guardrails ; https://arxiv.org/abs/2609.29429

### Repo (read-only)

- `tasks/FRAMEWORK.md` — authority: cash-only long book, 10% allocation, 8% kill, 5%/8% portfolio DD, 10% ADV, 0.30% round trip, after-tax, 2021–2025 evidence, 2026 live, four periods, fluke control.
- `AGENTS.md` §3 — all-peers ensemble; decision models are a peer/gate, not the trunk.
- `tasks/coverage/coverage_2026-10-24.json` — concall/deck/AR counts and gaps (main checkout).
- `tasks/FY26_AR_CHUNKING_2026-10-24.md` — 5,361 FY26 ARs, 908,969 chunks, 563.6M tokens, 70 garbled-font reports, 1 SDC hang.
- `tasks/ar_study/CPU_LEVERS.md` — 59% repeated text; ~9% LLM slice; 12–32 page-equivalents/report; ~5 s/report CPU.
- `tasks/ar_study/READER_FINDINGS.md` — 25/25 gate, depth ≥4,500, <1% not in text, free-reader quotas and pass list.
- `tasks/OPENCODE_AR_HANDBOOK.md`, `tasks/OPENCODE_ORCHESTRATION.md` — free-reader route, Go/Zen quotas, 56–69k AR pages/day/account.
- `tasks/STATE.md` — DeepSeek pilot 10.6k in / 23.3k out, 25.2/30, $17.69 for 1,056, $338 for 21,695; deck 815,837 pages read, 11,995,750 facts.
- `reality_engine/scripts/concall_deepseek.py` — `PRICE_IN, PRICE_OUT = 0.15, 0.60`.
- `reality_engine/harness/` — `book.py`, `costs_tax.py`, `stats.py`, `ledger.py`; H01/H02 reports and 499-draw placebo pattern.
- `tasks/backtests/H01_report.md`, `H02_report.md` — ledger/BH/placebo conventions to reuse for a gate.

---

### One-line answer to “JEV from TypeSafe or DEC”

**JEV = TypeSafe Jev**, the reference “System One” decision model: input state + typed questions (`noul`/`choice`/`score`) → probabilities, no generated text; the “Jev Router” is a routing product built on it. **DEC was a wrong guess and is dropped**; the actual category Shivam means is DeepInfra’s “Decision” models: **Cloudflare Clef/Clef-flash** and **Nace.AI Drex Max/Drex v2.0**, all System One-compatible, with the four prices/contexts above. They are usable today through DeepInfra/OpenRouter/TypeSafe; Clef is Apache 2.0 and the Drex models are RAIL-M with human-oversight terms. They fit our workflow as cheap typed triage/calibrated gates, not as extractors or autonomous traders.
