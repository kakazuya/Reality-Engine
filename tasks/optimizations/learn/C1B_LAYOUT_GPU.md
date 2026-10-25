# Task C1b — GPU layout detection for chunker v2 (GTX 1050 Ti laptop)

## Goal
Read PDF pages in their true structure before chunking, so annual-report and deck chunks keep tables whole, follow
the right column order and catch headings that font rules miss. It runs on this laptop's GPU and only where it
helps.

## Hardware (checked 2026-10-25)
- **GPU:** NVIDIA GTX 1050 Ti, 4 GB VRAM. Pascal, compute capability 6.1, CUDA, no tensor cores, so use FP32.
  DirectML is not used here.
- **CPU:** 8 threads. No UPS limit on this machine.
- No torch or onnxruntime is installed yet.

## Pipeline
1. **Triage (CPU, all pages).** Route a page to the GPU only if PyMuPDF shows:
   - a table candidate (`find_tables`, or many aligned numbers);
   - two or more text columns (x-position clustering);
   - an image-only or near-empty text layer; or
   - a deck slide.

   Clean single-column prose skips the GPU. Report the share of pages routed.
2. **Render (CPU workers).** Draw each routed page at 150 dpi, about 1,000–1,300 px on the long side.
3. **Layout (GPU, batched).** Use DocLayout-YOLO (DocStructBench weights, about 20M parameters) to get boxes for
   title, heading, text, table, figure, caption and page header/footer.
   - Fallback: PP-DocLayout-S exported to ONNX.
   - Pick the first one that runs on compute capability 6.1.
4. **Tables (GPU or CPU).** Run SLANet-plus / RapidTable (ONNX) on each table box to get cells, then emit the
   table as Markdown with its caption and units row.
5. **Text (CPU).** Take text from PyMuPDF's text layer inside each box. Use RapidOCR on the CUDA build only for
   image-only boxes. Reading order comes from sorting the boxes by column.
6. **Chunk (CPU workers).** Apply the chunker_v2 rules to the structured page: heading, then section, and a table
   stays whole as one chunk.
7. **Write.** A single writer commits once per 500 documents, and the FTS index is rebuilt once at the end.

## Install (needs Shivam's OK; PyPI only)
1. Get a CUDA build that still supports compute capability 6.1, and verify it first: `torch.cuda.is_available()`
   plus one convolution on the GPU.
   - Recent CUDA 12.8+ wheels may have dropped Pascal. If so, use the cu126 or cu118 builds.
2. Then `doclayout-yolo` (or `paddlex` for the fallback), `onnxruntime-gpu` for RapidTable/RapidOCR, and `pymupdf`.
3. Install into a project venv `.venv-layout` and record the exact versions.

## Pilot and acceptance
1. Run 50 annual reports and 50 decks, sampled from different companies.
2. Speed: pages/s, GPU VRAM peak (must stay under 3.5 GB), CPU %, and the share of pages routed to the GPU.
3. Quality, hand-checked on 100 routed pages:
   - share of tables kept whole and correct (cells, units);
   - reading-order errors on multi-column pages;
   - headings found.

   Compare against chunker_v2 without layout.
4. Retrieval: run the C2 harness (`eval_retrieval.py`, FTS) on the AR and deck questions, comparing old, v2 and
   v2+layout chunks.
5. Projection: full AR and deck corpus page count × routed share ÷ pages/s, giving the hours for a full run.

## Rules
Local data only. Raw PDFs are read from D: and outputs go to `.tmp/c1b/`. No live DB writes, no paid APIs, and no
internet beyond the approved PyPI installs.

## Depends on
C1 (`chunker_v2.py` and the C2 harness) being merged first.
